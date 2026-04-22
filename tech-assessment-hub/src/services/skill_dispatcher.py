"""SkillDispatcher — load assessment-plugin SKILL.md and run via the chosen adapter.

Single source of truth for "run AI on assessment X for stage Y":
  1. Look up the right SKILL.md by stage name
  2. Build the user message (assessment_id + any free-form instructions)
  3. Pick the adapter (CLI subprocess vs API) per app config
  4. Execute and return SkillRunResult
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from sqlmodel import Session, select, func

from ..database import DATA_DIR, engine
from ..models import AppConfig, Assessment, Scan, ScanResult
from .llm_adapters import SkillRunResult
from .llm_adapters.anthropic_api import AnthropicAPIAdapter
from .llm_adapters.anthropic_subprocess import AnthropicSubprocessAdapter


# How many artifacts each chunked scope-triage session should process.
# Matches the `limit` used by get_customizations in the skill pseudocode.
_SCOPE_TRIAGE_CHUNK_SIZE = 50
# Safety cap — never loop more than this many chunks even if the skill never
# advances the pipeline. At 50 per chunk this covers 25,000 artifacts.
_SCOPE_TRIAGE_MAX_CHUNKS = 500
# Stages that support auto-chaining (multiple CLI sessions, one per page).
_CHAINED_STAGES = {"scope_triage", "ai_analysis"}

logger = logging.getLogger(__name__)


# Where the plugin lives on disk. Two layouts:
#   - VM (deploy.sh extracts src/ into /opt/ta-hub/app/, plugin beside it):
#       parents[2] == /opt/ta-hub/app  →  /opt/ta-hub/app/assessment-plugin
#   - Local dev (plugin is a sibling of tech-assessment-hub/):
#       parents[3] == repo root         →  <repo>/assessment-plugin
# First existing candidate wins; fall through to the VM path for error messages.
def _resolve_plugin_base() -> Path:
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / "assessment-plugin", here.parents[3] / "assessment-plugin"]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


_PLUGIN_BASE = _resolve_plugin_base()

# Map UI/pipeline stage names → SKILL.md folder name
STAGE_TO_SKILL: Dict[str, str] = {
    "scope_triage": "scope-triage",
    "ai_analysis": "scope-triage",       # alias used in pipeline
    "observations": "observations",
    "feature_grouping": "feature-grouping",
    "ai_refinement": "refinement",
    "refinement": "refinement",
    "recommendations": "recommendations",
    "report": "report",
}

DEFAULT_DISPATCHER = "skill_api"   # "skill_api" (Anthropic API) or "cli" (claude subprocess)
DEFAULT_MODEL = "claude-opus-4-6"


class SkillNotFoundError(Exception):
    pass


def _load_skill(stage: str) -> str:
    folder = STAGE_TO_SKILL.get(stage)
    if not folder:
        raise SkillNotFoundError(f"No skill mapping for stage '{stage}'")
    skill_path = _PLUGIN_BASE / "skills" / folder / "SKILL.md"
    if not skill_path.exists():
        raise SkillNotFoundError(f"SKILL.md not found at {skill_path}")
    return skill_path.read_text(encoding="utf-8")


def _get_app_config(session: Session, key: str, default: str) -> str:
    row = session.exec(select(AppConfig).where(AppConfig.key == key)).first()
    if row and row.value is not None:
        return str(row.value).strip() or default
    return default


def run_skill(
    *,
    session: Session,
    assessment_id: int,
    stage: str,
    user_instructions: Optional[str] = None,
    dispatcher: Optional[str] = None,
    model: Optional[str] = None,
    mcp_server_url: Optional[str] = None,
    timeout_seconds: int = 1800,
    extra: Optional[Dict[str, Any]] = None,
) -> SkillRunResult:
    """Load the SKILL.md for `stage`, execute via the selected adapter, return result."""
    skill_text = _load_skill(stage)

    user_msg_lines = [f"Run the {stage} stage for assessment_id={assessment_id}."]
    if user_instructions:
        user_msg_lines.append("")
        user_msg_lines.append("Additional instructions from the operator:")
        user_msg_lines.append(user_instructions)
    user_message = "\n".join(user_msg_lines)

    # Resolve dispatcher choice
    chosen = (dispatcher or _get_app_config(session, "ai.dispatcher", DEFAULT_DISPATCHER)).strip().lower()
    chosen_model = (model or _get_app_config(session, "ai.default_model_name", DEFAULT_MODEL)).strip() or DEFAULT_MODEL

    # Resolve MCP server URL — only used by the API adapter
    if not mcp_server_url:
        mcp_server_url = _get_app_config(
            session, "mcp.public_url", "https://136-112-232-229.nip.io/mcp"
        )

    if chosen == "cli":
        adapter = AnthropicSubprocessAdapter()
    else:
        adapter = AnthropicAPIAdapter()

    if not adapter.is_available():
        # Fall back to the other adapter if the preferred one isn't usable
        fallback = AnthropicSubprocessAdapter() if chosen != "cli" else AnthropicAPIAdapter()
        if fallback.is_available():
            logger.warning(
                "Adapter '%s' unavailable; falling back to '%s'",
                adapter.name, fallback.name,
            )
            adapter = fallback
        else:
            return SkillRunResult(
                success=False,
                output="",
                transport=adapter.name,
                error=(
                    f"No usable AI adapter — neither '{adapter.name}' nor "
                    f"the alternative is configured (need ANTHROPIC_API_KEY for API "
                    f"path, or `claude` CLI + key for CLI path)."
                ),
            )

    # Ensure the CLI adapter can wire up the plugin's MCP server.
    #
    # The plugin's packaged .mcp.json points at the PUBLIC URL
    # (https://<vm>.nip.io/mcp) so Desktop / Cowork / CLI installs on user
    # PCs can reach the hub. But when the adapter runs on the VM itself, the
    # VM can't hairpin to its own public URL (GCP VPC NAT/routing) — it
    # times out. So we write a runtime .mcp.json pointing at the LOCAL URL
    # and hand that to the CLI instead. Users override with AppConfig key
    # "mcp.cli_url".
    cli_url = _get_app_config(session, "mcp.cli_url", "http://127.0.0.1:8080/mcp")
    runtime_mcp_config = {
        "mcpServers": {
            "tech-assessment-hub": {"type": "http", "url": cli_url},
        }
    }
    runtime_config_path = DATA_DIR / "logs" / "ai_prompts" / "ta-hub-cli.mcp.json"
    try:
        runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_config_path.write_text(
            json.dumps(runtime_mcp_config, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.exception("failed to write runtime mcp config; falling back to plugin .mcp.json")
        runtime_config_path = _PLUGIN_BASE / ".mcp.json"

    adapter_extra = dict(extra or {})
    adapter_extra.setdefault("mcp_config_path", str(runtime_config_path))

    # Compute the per-run stream log path. This file is what the SSE route
    # tails so the browser sees events as they happen. Every run gets a fresh
    # file keyed by timestamp + uuid so tails never collide.
    stamp = time.strftime("%Y%m%dT%H%M%S")
    stream_id = adapter_extra.get("stream_id") or f"{stamp}-{uuid.uuid4().hex[:8]}"
    adapter_extra["stream_id"] = stream_id
    stream_log_path = (
        DATA_DIR / "logs" / "ai_prompts" / f"assessment_{assessment_id}"
        / f"{stage}-{stream_id}.stream.jsonl"
    )
    adapter_extra["stream_log_path"] = str(stream_log_path)

    result = adapter.run(
        skill_text=skill_text,
        user_message=user_message,
        model=chosen_model,
        timeout_seconds=timeout_seconds,
        mcp_server_url=mcp_server_url,
        extra=adapter_extra,
    )

    _write_run_trace(
        assessment_id=assessment_id,
        stage=stage,
        skill_text=skill_text,
        user_message=user_message,
        adapter_name=adapter.name,
        model=chosen_model,
        result=result,
        stream_id=stream_id,
    )

    # Attach the stream id onto the result so callers can reference it in
    # responses without keeping state elsewhere.
    try:
        if isinstance(result.raw, dict):
            result.raw.setdefault("stream_id", stream_id)
        else:
            result.raw = {"stream_id": stream_id}
    except Exception:
        pass

    return result


def start_skill_background(
    *,
    assessment_id: int,
    stage: str,
    user_instructions: Optional[str] = None,
    dispatcher: Optional[str] = None,
    model: Optional[str] = None,
    mcp_server_url: Optional[str] = None,
    timeout_seconds: int = 1800,
    extra: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Path]:
    """Kick off `run_skill` in a background thread and return (stream_id, path).

    The HTTP route returns immediately with this stream_id; the SSE route
    tails the stream_log_path until the `_stream_end` sentinel appears.
    """
    stamp = time.strftime("%Y%m%dT%H%M%S")
    stream_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    stream_log_path = (
        DATA_DIR / "logs" / "ai_prompts" / f"assessment_{assessment_id}"
        / f"{stage}-{stream_id}.stream.jsonl"
    )
    stream_log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create the file synchronously BEFORE returning so the SSE route never
    # 404s on the first poll. The browser subscribes to
    # /api/assessments/{id}/ai-stream?stream_id=... the instant run-stage
    # responds — if the background thread hasn't yet opened the file, SSE
    # hits FileNotFoundError and returns 404 while the thread is still
    # spinning up (which in chained mode includes a triaged-count DB query
    # before launching the first subprocess). An empty preamble line makes
    # the SSE route happy and is silently ignored by JSON parsers.
    try:
        with stream_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "_dispatch_started",
                "stream_id": stream_id,
                "stage": stage,
                "assessment_id": assessment_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }) + "\n")
    except Exception:
        logger.exception("failed to pre-create stream file %s", stream_log_path)

    merged_extra = dict(extra or {})
    merged_extra["stream_id"] = stream_id
    merged_extra["stream_log_path"] = str(stream_log_path)

    def _target() -> None:
        try:
            if stage in _CHAINED_STAGES:
                _run_chained_scope_triage(
                    assessment_id=assessment_id,
                    stage=stage,
                    user_instructions=user_instructions,
                    dispatcher=dispatcher,
                    model=model,
                    mcp_server_url=mcp_server_url,
                    timeout_seconds=timeout_seconds,
                    merged_extra=merged_extra,
                    stream_log_path=stream_log_path,
                )
            else:
                with Session(engine) as bg_session:
                    run_skill(
                        session=bg_session,
                        assessment_id=assessment_id,
                        stage=stage,
                        user_instructions=user_instructions,
                        dispatcher=dispatcher,
                        model=model,
                        mcp_server_url=mcp_server_url,
                        timeout_seconds=timeout_seconds,
                        extra=merged_extra,
                    )
        except Exception:
            logger.exception(
                "background run_skill crashed for assessment=%s stage=%s",
                assessment_id, stage,
            )
            # Record the crash in the stream file so SSE subscribers see it.
            try:
                with stream_log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "type": "_stream_error",
                        "error": "background run crashed — see service logs",
                    }) + "\n")
                    f.write(json.dumps({"type": "_stream_end"}) + "\n")
            except Exception:
                pass

    thread = threading.Thread(
        target=_target, name=f"ai-run-{assessment_id}-{stage}-{stream_id}", daemon=True,
    )
    thread.start()
    return stream_id, stream_log_path


def _count_triaged_results(session: Session, assessment_id: int) -> int:
    """Count ScanResults in the assessment that carry a scope_decision in
    ai_observations. Used for resume-after-crash and no-progress detection."""
    q = (
        select(func.count(ScanResult.id))
        .select_from(ScanResult)
        .join(Scan, Scan.id == ScanResult.scan_id)
        .where(Scan.assessment_id == assessment_id)
        .where(ScanResult.ai_observations.is_not(None))
        .where(ScanResult.ai_observations.like('%"scope_decision"%'))
    )
    try:
        return int(session.exec(q).one() or 0)
    except Exception:
        logger.exception("_count_triaged_results failed for assessment=%s", assessment_id)
        return 0


def _run_chained_scope_triage(
    *,
    assessment_id: int,
    stage: str,
    user_instructions: Optional[str],
    dispatcher: Optional[str],
    model: Optional[str],
    mcp_server_url: Optional[str],
    timeout_seconds: int,
    merged_extra: Dict[str, Any],
    stream_log_path: Path,
) -> None:
    """Loop scope-triage as N short CLI sessions until the pipeline advances or
    no new artifacts get triaged. Each session is a fresh claude subprocess
    with its own context — no accumulation across chunks, so we avoid the
    rate-limit backoffs that killed long single-session runs."""

    # Starting offset: resume at however many are already triaged so we don't
    # redo earlier batches on a re-run after a crash/kill.
    with Session(engine) as s:
        offset = _count_triaged_results(s, assessment_id)
    last_triaged = offset

    for chunk_i in range(_SCOPE_TRIAGE_MAX_CHUNKS):
        chunk_instructions_lines = [
            f"Chunk {chunk_i + 1}: process the customizations page starting at "
            f"offset={offset} with limit={_SCOPE_TRIAGE_CHUNK_SIZE}, then exit.",
            "Do NOT fetch the next page within this session — the dispatcher "
            "launches a fresh session for each chunk.",
            "Skip any artifact whose ai_observations already contains a "
            "scope_decision — it was triaged in a prior chunk.",
        ]
        if user_instructions:
            chunk_instructions_lines.insert(0, user_instructions)
        chunk_instructions = "\n".join(chunk_instructions_lines)

        # Intermediate sessions must not close the SSE stream; only the final
        # sentinel we emit after the loop should terminate the browser feed.
        chunk_extra = dict(merged_extra)
        chunk_extra["suppress_stream_end"] = True

        # Mark chunk boundaries in the stream for the UI.
        try:
            with stream_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "_chunk_start",
                    "chunk": chunk_i + 1,
                    "offset": offset,
                    "page_size": _SCOPE_TRIAGE_CHUNK_SIZE,
                }) + "\n")
        except Exception:
            pass

        # Cap per-chunk wall time so a stuck chunk doesn't hold the whole
        # auto-chain loop for 30 minutes. 6 minutes is plenty for 50
        # artifacts with the fast scope-brief tool; anything longer than
        # that is the CLI in a retry/backoff loop and we're better off
        # killing it and letting the next chunk take a fresh swing.
        per_chunk_timeout = min(int(timeout_seconds or 1800), 360)

        with Session(engine) as bg_session:
            result = run_skill(
                session=bg_session,
                assessment_id=assessment_id,
                stage=stage,
                user_instructions=chunk_instructions,
                dispatcher=dispatcher,
                model=model,
                mcp_server_url=mcp_server_url,
                timeout_seconds=per_chunk_timeout,
                extra=chunk_extra,
            )

        # Reap anything that somehow survived the session (belt-and-braces).
        try:
            from .llm_adapters.anthropic_subprocess import _reap_stale_claude_children
            _reap_stale_claude_children(max_age_seconds=30)
        except Exception:
            pass

        # Decide whether another chunk is needed.
        with Session(engine) as s:
            assessment = s.get(Assessment, assessment_id)
            pipeline_stage = (assessment.pipeline_stage if assessment else "") or ""
            new_triaged = _count_triaged_results(s, assessment_id)

        try:
            with stream_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "_chunk_end",
                    "chunk": chunk_i + 1,
                    "triaged_total": new_triaged,
                    "success": bool(result.success),
                    "error": result.error,
                }) + "\n")
        except Exception:
            pass

        # Stop conditions:
        # 1) The skill advanced the pipeline past scope_triage/ai_analysis.
        if pipeline_stage and pipeline_stage not in _CHAINED_STAGES:
            logger.info(
                "chained scope_triage done — assessment=%s pipeline_stage=%s",
                assessment_id, pipeline_stage,
            )
            break
        # 2) No new triages happened this chunk — prevent infinite loop.
        #    A chunk with zero progress AND a hard failure gives up; a
        #    chunk with zero progress but no error gets one more try in
        #    case the CLI just came up slow.
        if new_triaged <= last_triaged:
            if not result.success:
                logger.warning(
                    "chained scope_triage halted — chunk=%s made no progress "
                    "and adapter reported error=%s. Stopping.",
                    chunk_i + 1, result.error,
                )
                break
            # Give it one more try next iteration; no-progress-twice bails.
            if chunk_i > 0:
                logger.warning(
                    "chained scope_triage halted — chunk=%s made no progress "
                    "and previous chunk also stalled. Bailing.",
                    chunk_i + 1,
                )
                break
        # 3) Partial progress on a failed chunk: continue. A timeout /
        #    internal retry loop / SIGKILL that still managed to triage
        #    some artifacts is NOT a reason to stop the whole run — the
        #    next fresh CLI session will pick up where this one left off.
        if not result.success and new_triaged > last_triaged:
            logger.warning(
                "chained scope_triage chunk=%s failed (%s) but triaged "
                "%s new artifacts — continuing with next chunk.",
                chunk_i + 1, result.error, new_triaged - last_triaged,
            )

        offset = new_triaged
        last_triaged = new_triaged

    # Emit the single final sentinel so SSE closes cleanly.
    try:
        with stream_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "type": "_stream_end",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }) + "\n")
    except Exception:
        pass


def _write_run_trace(
    *,
    assessment_id: int,
    stage: str,
    skill_text: str,
    user_message: str,
    adapter_name: str,
    model: str,
    result: SkillRunResult,
    stream_id: Optional[str] = None,
) -> None:
    """Persist prompt + output + usage per run so failures are debuggable."""
    try:
        trace_dir = DATA_DIR / "logs" / "ai_prompts" / f"assessment_{assessment_id}"
        trace_dir.mkdir(parents=True, exist_ok=True)
        # Reuse the stream_id for the base name so all artifacts from one run
        # share the same filename stem (<stage>-<stream_id>.{prompt|output|...}).
        base_name = f"{stage}-{stream_id}" if stream_id else f"{stage}-{time.strftime('%Y%m%dT%H%M%S')}"
        base = trace_dir / base_name
        (base.with_suffix(".prompt.txt")).write_text(
            f"{skill_text}\n\n---\n\nUser request:\n{user_message}\n",
            encoding="utf-8",
        )
        (base.with_suffix(".output.txt")).write_text(result.output or "", encoding="utf-8")
        summary = {
            "assessment_id": assessment_id,
            "stage": stage,
            "stream_id": stream_id,
            "adapter": adapter_name,
            "model": model,
            "success": result.success,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
            "tool_call_count": result.tool_call_count,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_read_tokens": result.cache_read_tokens,
            "cache_write_tokens": result.cache_write_tokens,
        }
        (base.with_suffix(".summary.json")).write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        if result.raw:
            (base.with_suffix(".raw.json")).write_text(
                json.dumps(result.raw, indent=2, default=str), encoding="utf-8"
            )
    except Exception:
        logger.exception("failed to write run trace for assessment=%s stage=%s", assessment_id, stage)
