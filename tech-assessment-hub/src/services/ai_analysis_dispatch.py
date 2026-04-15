"""Connected AI dispatch for the post-preflight ai_analysis stage.

Runs a tool-enabled local CLI session against the app's MCP endpoint so the
model can inspect customized results, write scope flags, and persist
relationship-aware observations through ``update_scan_result``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlmodel import Session

logger = logging.getLogger(__name__)

from ..models import Assessment, GlobalApp, ReviewStatus, ScanResult
from .ai_stage_tool_sets import STAGE_TOOL_SETS, build_batch_prompt
from .integration_properties import AIRuntimeProperties
from .llm.dispatcher_router import ResolvedConfig
from ..mcp.bridge.config_store import load_bridge_config
from ..mcp.registry import PROMPT_REGISTRY
from .query_builder import parse_list, resolve_assessment_drivers
from .ai_observation_history import load_ai_observation_payload, merge_ai_observation_payload
from .ai_swarm import (
    build_ai_analysis_swarm_prompt,
    build_claude_swarm_agents,
    build_claude_swarm_append_system_prompt,
    build_codex_swarm_config_overrides,
    effective_ai_analysis_batch_size,
    swarm_enabled,
)

_MCP_SERVER_ID = "tech_assessment_hub"
_MCP_TOOL_PREFIX = "mcp__tech-assessment-hub__"
_DEFAULT_HOST = (os.getenv("TECH_ASSESSMENT_HUB_HOST") or "127.0.0.1").strip()
_DEFAULT_PORT = int((os.getenv("TECH_ASSESSMENT_HUB_PORT") or "8080").strip())

_AI_ANALYSIS_FALLBACK_GUIDANCE = """\
## Scope Triage

You are reviewing ONLY customized results (Modified OOTB or Customer Created).
Not every customized result is in scope — scans pick up out-of-scope items too.
Your job is to classify each artifact as in_scope, adjacent, or out_of_scope.
Both in_scope and adjacent are IN SCOPE for the assessment — only out_of_scope
is excluded. Adjacent just means "in scope but on a different table."

### How to decide

**Step 1: Check the artifact's table.**
Call `get_result_detail` for the artifact. Look at its table (collection field).

**Step 2: Is the table one of the assessment's target tables?**
- YES → **in_scope**. Done. A customized artifact directly on a target table
  is automatically in scope.

**Step 3: No table field (e.g. script includes)?**
- Check if something related to the target tables calls this script, OR if
  the script itself does something with the target tables (queries, creates,
  updates records on them).
- YES → **in_scope**
- NO connection to target tables → **out_of_scope**

**Step 4: Table exists but is NOT a target table?**
- Check if the artifact references, queries, creates, or updates records on
  the target tables. Examples:
  - A dictionary entry on `change_request` that is a reference field pointing
    to `incident` → **adjacent**
  - A business rule on `change_request` whose script queries or creates
    incident records → **adjacent**
  - A dictionary override on a non-target table for a field that references
    a target table → **adjacent**
- If NO reference to target tables at all → **out_of_scope**

### What to write
Call `update_scan_result`:
- `review_status` = `review_in_progress`
- `observations` = ONE sentence: what it is + why you classified it
- `is_out_of_scope` = true if out of scope
- `is_adjacent` = true if adjacent (leave both false for in_scope)
- `ai_observations` = `{"analysis_stage":"ai_analysis","scope_decision":"in_scope|adjacent|out_of_scope","scope_rationale":"<1 sentence>"}`

### Speed rules
- ONE call to `get_result_detail` per artifact. That's it.
- Do NOT call `get_customizations` unless you genuinely need cross-artifact context.
- Do NOT do deep code analysis — just enough to determine scope.
- If already triaged (observations exist), skip it entirely.
- Never set disposition. Never set review_status to "reviewed".
"""


@dataclass(frozen=True)
class AIDispatchSummary:
    """Summary of ai_analysis CLI execution."""

    provider_kind: str
    model_name: str
    runtime_mode: str
    batch_count: int
    processed_count: int
    registered_prompt_name: Optional[str] = None
    registered_prompt_error: Optional[str] = None


def _artifact_processed(row: ScanResult) -> bool:
    review_status = row.review_status.value if row.review_status else None
    has_observation = bool((row.observations or "").strip())
    return review_status == ReviewStatus.review_in_progress.value and (
        has_observation or bool(row.is_adjacent) or bool(row.is_out_of_scope)
    )


def _chunked(items: Sequence[ScanResult], size: int) -> Iterable[List[ScanResult]]:
    if size <= 0:
        size = len(items) or 1
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def _extract_prompt_text(prompt_result: Dict[str, Any]) -> str:
    messages = prompt_result.get("messages") or []
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    return ""


def _try_registered_prompt_text(
    session: Session,
    *,
    prompt_name: str,
    arguments: Dict[str, Any],
) -> tuple[Optional[str], Optional[str]]:
    if not PROMPT_REGISTRY.has_prompt(prompt_name):
        return None, f"Prompt not registered: {prompt_name}"
    try:
        prompt_result = PROMPT_REGISTRY.get_prompt(
            prompt_name,
            arguments,
            session=session,
        )
        text = _extract_prompt_text(prompt_result)
        if not text:
            return None, f"Prompt returned no text: {prompt_name}"
        return text, None
    except Exception as exc:
        return None, str(exc)


def _build_assessment_scope_context(session: Session, assessment: Assessment) -> str:
    global_app = None
    if assessment.target_app_id:
        global_app = session.get(GlobalApp, int(assessment.target_app_id))

    drivers = resolve_assessment_drivers(assessment, global_app)
    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []
    app_file_classes = parse_list(assessment.app_file_classes_json)

    lines = [
        "## Assessment Scope",
        f"- Assessment ID: {int(assessment.id)}",
        f"- Assessment Type: {assessment.assessment_type.value if assessment.assessment_type else 'unknown'}",
    ]
    if global_app:
        lines.append(f"- Target Application: {global_app.label} ({global_app.name})")
        if global_app.parent_table:
            lines.append(f"- Parent Table Context: {global_app.parent_table}")
    if target_tables:
        lines.append(f"- Direct Target Tables: {', '.join(target_tables)}")
    if keywords:
        lines.append(f"- Scope Keywords: {', '.join(keywords[:12])}")
    if app_file_classes:
        lines.append(f"- Included App File Classes: {', '.join(app_file_classes)}")

    lines.extend(
        [
            "",
            "Scope instructions:",
            "- `in_scope`: directly implements or alters behavior on the target application/tables/forms.",
            "- `adjacent`: not directly on the target table, but meaningfully supports or interacts with it.",
            "- `out_of_scope`: unrelated to the target application/tables, or trivial noise.",
            "- `adjacent` is mainly for table-bound artifacts outside the direct target tables/forms.",
            "- Tableless artifacts (for example script includes) are not adjacent by default; classify them by behavior as `in_scope` or `out_of_scope`.",
            "- Treat the target application definition above as the source of truth for scope decisions.",
        ]
    )
    return "\n".join(lines)


def _build_artifact_stage_instructions(
    session: Session,
    *,
    assessment: Assessment,
    row: ScanResult,
    methodology_prompt_text: Optional[str],
) -> str:
    sections = [_build_assessment_scope_context(session, assessment)]
    if methodology_prompt_text:
        sections.append(methodology_prompt_text.strip())

    artifact_prompt_text = None
    if methodology_prompt_text:
        artifact_prompt_text, _ = _try_registered_prompt_text(
            session,
            prompt_name="artifact_analyzer",
            arguments={
                "result_id": str(int(row.id)),
                "assessment_id": str(int(assessment.id)),
            },
        )
    if artifact_prompt_text:
        sections.append(artifact_prompt_text.strip())

    sections.append(_AI_ANALYSIS_FALLBACK_GUIDANCE.strip())
    return "\n\n---\n\n".join(section for section in sections if section)


def _build_batch_stage_instructions(
    session: Session,
    *,
    assessment: Assessment,
    rows: Sequence[ScanResult],
    methodology_prompt_text: Optional[str],
    runtime_props: AIRuntimeProperties,
    provider_kind: str,
) -> str:
    # Scope triage uses a thin, focused prompt — skip the full methodology
    # document to keep the context small and the model fast.
    if len(rows) == 1:
        sections = [
            _build_assessment_scope_context(session, assessment),
            _AI_ANALYSIS_FALLBACK_GUIDANCE.strip(),
        ]
    else:
        sections = [_build_assessment_scope_context(session, assessment)]
        sections.append(_AI_ANALYSIS_FALLBACK_GUIDANCE.strip())
        sections.append(
            """\
## Multi-Artifact Batch Rules
This session is responsible for multiple artifacts. Treat each artifact independently:
- read each artifact with `get_result_detail` before updating it,
- persist the scope decision for each artifact separately,
- never assume one artifact's decision automatically applies to another,
- do not end the run until every artifact in the batch has been triaged or explicitly marked `needs_review`.
""".strip()
        )
    if swarm_enabled(runtime_props):
        sections.append(
            build_ai_analysis_swarm_prompt(
                provider_kind=provider_kind,
                max_workers=max(1, runtime_props.max_concurrent_sessions),
            ).strip()
        )
    return "\n\n---\n\n".join(section for section in sections if section)


def _resolve_rpc_url(session: Session) -> str:
    bridge_cfg = load_bridge_config(session)
    rpc_url = str(bridge_cfg.get("rpc_url") or "").strip()
    if rpc_url:
        return rpc_url

    management_base = str(bridge_cfg.get("management_base_url") or "").strip().rstrip("/")
    if management_base:
        return f"{management_base}/mcp"

    # Read the actual running server URL from data/server.url (written by
    # daemon_start.py).  The server auto-selects a free port, so the default
    # 8080 may not match the real port.
    _url_file = Path(__file__).resolve().parents[2] / "data" / "server.url"
    try:
        live_url = _url_file.read_text().strip().rstrip("/")
        if live_url:
            return f"{live_url}/mcp"
    except (OSError, ValueError):
        pass

    return f"http://{_DEFAULT_HOST}:{_DEFAULT_PORT}/mcp"


def _plain_tool_names(stage: str) -> List[str]:
    full_names = STAGE_TOOL_SETS.get(stage, [])
    plain_names: List[str] = []
    for tool_name in full_names:
        if tool_name.startswith(_MCP_TOOL_PREFIX):
            plain_names.append(tool_name[len(_MCP_TOOL_PREFIX) :])
        else:
            plain_names.append(tool_name)
    return plain_names


def _api_key_env(provider_kind: str, auth_slot: Any) -> Dict[str, str]:
    env_var_name = (getattr(auth_slot, "env_var_name", None) or "").strip()
    api_key = (getattr(auth_slot, "api_key", None) or "").strip()

    if env_var_name:
        inherited = os.getenv(env_var_name)
        if inherited:
            return {env_var_name: inherited}
        if api_key:
            return {env_var_name: api_key}
        raise RuntimeError(f"Configured API key env var is empty: {env_var_name}")

    if not api_key:
        raise RuntimeError("Active API key auth slot is missing a usable key.")

    if provider_kind == "openai":
        return {"OPENAI_API_KEY": api_key}
    if provider_kind == "anthropic":
        return {"ANTHROPIC_API_KEY": api_key}
    if provider_kind == "google":
        return {"GEMINI_API_KEY": api_key, "GOOGLE_API_KEY": api_key}

    raise RuntimeError(f"Unsupported provider for api_key mode: {provider_kind}")


def _parse_cli_json(stdout: str) -> Dict[str, Any]:
    stdout = (stdout or "").strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {"raw_output": stdout[:4000]}


def _build_claude_command(
    *,
    model_name: str,
    effort_level: str,
    allowed_tools: List[str],
    rpc_url: str,
    runtime_props: AIRuntimeProperties,
    stage: str,
    pass_key: Optional[str] = None,
) -> List[str]:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError("Claude CLI not found on PATH.")

    mcp_config = json.dumps(
        {
            "mcpServers": {
                "tech-assessment-hub": {
                    "type": "http",
                    "url": rpc_url,
                }
            }
        }
    )
    cmd = [
        claude_bin,
        "-p",
        "--output-format",
        "json",
        "--model",
        model_name,
        "--permission-mode",
        "bypassPermissions",
        "--no-session-persistence",
        "--mcp-config",
        mcp_config,
    ]
    if effort_level:
        cmd.extend(["--effort", effort_level])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    if swarm_enabled(runtime_props):
        cmd.extend(
            [
                "--agents",
                build_claude_swarm_agents(stage=stage, pass_key=pass_key),
                "--append-system-prompt",
                build_claude_swarm_append_system_prompt(
                    stage=stage,
                    pass_key=pass_key,
                    max_workers=max(1, runtime_props.max_concurrent_sessions),
                ),
            ]
        )
    return cmd


def _build_codex_command(
    *,
    model_name: str,
    effort_level: str,
    enabled_tools: List[str],
    rpc_url: str,
    force_api_login: bool,
    runtime_props: AIRuntimeProperties,
) -> List[str]:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        raise RuntimeError("Codex CLI not found on PATH.")

    cmd = [
        codex_bin,
        "exec",
        "--model",
        model_name,
        "--json",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
    ]

    overrides = [
        f'mcp_servers.{_MCP_SERVER_ID}.url="{rpc_url}"',
        f"mcp_servers.{_MCP_SERVER_ID}.enabled=true",
        f"mcp_servers.{_MCP_SERVER_ID}.required=true",
        f"mcp_servers.{_MCP_SERVER_ID}.tool_timeout_sec=120",
    ]
    if enabled_tools:
        serialized_tools = ",".join(f'"{name}"' for name in enabled_tools)
        overrides.append(
            f"mcp_servers.{_MCP_SERVER_ID}.enabled_tools=[{serialized_tools}]"
        )
    if effort_level:
        overrides.append(f'model_reasoning_effort="{effort_level}"')
    if force_api_login:
        overrides.append('forced_login_method="api"')
    if swarm_enabled(runtime_props):
        overrides.extend(build_codex_swarm_config_overrides(runtime_props))

    for override in overrides:
        cmd.extend(["-c", override])
    return cmd


def _run_cli_batch(
    *,
    prompt: str,
    resolved: ResolvedConfig,
    runtime_props: AIRuntimeProperties,
    stage: str,
    allowed_tools: List[str],
    rpc_url: str,
    auth_slot: Any,
    pass_key: Optional[str] = None,
    cli_timeout_seconds: int = 900,
) -> Dict[str, Any]:
    env = os.environ.copy()
    if runtime_props.mode == "api_key":
        env.update(_api_key_env(resolved.provider_kind, auth_slot))

    if resolved.provider_kind == "anthropic":
        cmd = _build_claude_command(
            model_name=resolved.model_name,
            effort_level=resolved.effort_level,
            allowed_tools=allowed_tools,
            rpc_url=rpc_url,
            runtime_props=runtime_props,
            stage=stage,
            pass_key=pass_key,
        )
    elif resolved.provider_kind == "openai":
        cmd = _build_codex_command(
            model_name=resolved.model_name,
            effort_level=resolved.effort_level,
            enabled_tools=_plain_tool_names(stage),
            rpc_url=rpc_url,
            force_api_login=runtime_props.mode == "api_key",
            runtime_props=runtime_props,
        )
    else:
        raise RuntimeError(
            f"Connected MCP ai_analysis dispatch is not implemented for provider '{resolved.provider_kind}'."
        )

    # Write prompt to a debug file for inspection, but always pipe the full
    # prompt via stdin.  --strict-mcp-config blocks local file reads, so the
    # model cannot read a bootstrap file reference.
    prompt_dir = Path(__file__).resolve().parents[2] / "data" / "ai_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_dir / f"prompt_{stage}_{os.getpid()}_{int(time.time())}.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    started = time.monotonic()
    completed = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=cli_timeout_seconds,
        env=env,
    )
    duration = time.monotonic() - started

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(
            f"{resolved.provider_kind} CLI exited {completed.returncode}: {stderr[:800]}"
        )

    parsed_output = _parse_cli_json(completed.stdout)
    return {"duration_seconds": duration, "llm_output": parsed_output}


def _merge_ai_trace(
    row: ScanResult,
    *,
    resolved: ResolvedConfig,
    runtime_props: AIRuntimeProperties,
    batch_index: int,
    total_batches: int,
    registered_prompt_name: Optional[str],
) -> None:
    existing = load_ai_observation_payload(row.ai_observations)
    existing.setdefault("analysis_stage", "ai_analysis")
    existing["dispatch_trace"] = {
        "provider_kind": resolved.provider_kind,
        "model_name": resolved.model_name,
        "runtime_mode": runtime_props.mode,
        "batch_index": batch_index,
        "total_batches": total_batches,
        "registered_prompt": registered_prompt_name,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    row.ai_observations = json.dumps(
        merge_ai_observation_payload(row.ai_observations, existing),
        sort_keys=True,
    )


def _build_artifact_context(session: Session, result: ScanResult) -> str:
    """Read artifact data from DB and format as prompt context. No MCP needed."""
    from ..mcp.tools.core.result_detail import handle as get_result_detail_handle

    try:
        detail = get_result_detail_handle(
            {"result_id": int(result.id)}, session
        )
    except Exception:
        detail = {"result": {"id": result.id, "name": result.name, "table_name": result.table_name}}

    r = detail.get("result", {})
    artifact = detail.get("artifact_detail") or {}

    # Extract just the fields needed for scope decision
    lines = [
        f"ID: {r.get('id')}",
        f"Name: {r.get('name')}",
        f"Table: {r.get('table_name')}",
        f"Target Table: {r.get('meta_target_table', '')}",
        f"Class: {r.get('sys_class_name')}",
        f"Origin: {r.get('origin_type')}",
        f"Scope: {r.get('sys_scope', '')}",
    ]

    # Add script snippet if present (truncated for speed)
    script = None
    for key in ("script", "code_body", "condition", "template"):
        val = artifact.get(key)
        if val and isinstance(val, str) and val.strip():
            script = val.strip()
            break
    if not script and r.get("raw_data"):
        for key in ("script", "code_body", "meta_code_body", "condition"):
            val = r["raw_data"].get(key)
            if val and isinstance(val, str) and val.strip():
                script = val.strip()
                break
    if script:
        if len(script) > 2000:
            script = script[:2000] + "\n... (truncated)"
        lines.append(f"Script/Code:\n```\n{script}\n```")

    # Add collection/table from artifact detail
    for key in ("collection", "table", "name"):
        val = artifact.get(key)
        if val and key not in ("name",):
            lines.append(f"Artifact {key}: {val}")

    return "\n".join(lines)


def _parse_scope_response(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse CLI JSON output to extract scope decision."""
    stdout = (stdout or "").strip()
    if not stdout:
        return None

    # Claude -p --output-format json wraps in {"result": "..."}
    try:
        wrapper = json.loads(stdout)
        text = wrapper.get("result", stdout)
    except json.JSONDecodeError:
        text = stdout

    # Look for JSON in the response text
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and "scope_decision" in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # Try to find JSON block in markdown code fence
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{") and "scope_decision" in cleaned:
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue

    # Last resort: try whole text as JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "scope_decision" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    return None


def _build_triage_cli_command(
    resolved: ResolvedConfig,
    runtime_props: AIRuntimeProperties,
) -> List[str]:
    """Build a tool-free CLI command for scope triage (no MCP)."""
    if resolved.provider_kind == "anthropic":
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("Claude CLI not found on PATH.")
        cmd = [
            claude_bin,
            "-p",
            "--output-format",
            "json",
            "--model",
            resolved.model_name,
            "--permission-mode",
            "bypassPermissions",
            "--no-session-persistence",
        ]
        if resolved.effort_level:
            cmd.extend(["--effort", resolved.effort_level])
        return cmd

    elif resolved.provider_kind == "openai":
        codex_bin = shutil.which("codex")
        if not codex_bin:
            raise RuntimeError("Codex CLI not found on PATH.")
        cmd = [
            codex_bin,
            "exec",
            "--model",
            resolved.model_name,
            "--json",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        if resolved.effort_level:
            cmd.extend(["-c", f'model_reasoning_effort="{resolved.effort_level}"'])
        return cmd

    elif resolved.provider_kind == "google":
        gemini_bin = shutil.which("gemini")
        if not gemini_bin:
            raise RuntimeError("Gemini CLI not found on PATH.")
        cmd = [gemini_bin, "-p", "--output-format", "json"]
        if resolved.model_name:
            cmd.extend(["--model", resolved.model_name])
        return cmd

    raise RuntimeError(f"Unsupported provider: {resolved.provider_kind}")


def run_ai_analysis_dispatch(
    session: Session,
    *,
    assessment: Assessment,
    resolved: ResolvedConfig,
    runtime_props: AIRuntimeProperties,
    customized_results: Sequence[ScanResult],
    batch_size: int,
    registered_prompt_name: Optional[str],
    registered_prompt_text: Optional[str],
    registered_prompt_error: Optional[str],
    cli_timeout_seconds: int = 900,
) -> AIDispatchSummary:
    """Tool-free AI scope triage. Reads artifact data from DB, sends to CLI
    as prompt context, parses JSON response, writes result back to DB.
    No MCP connection needed — fast and reliable."""

    if runtime_props.mode == "disabled":
        raise RuntimeError("AI runtime mode is disabled.")

    auth_slot = resolved.auth_slot
    slot_kind = (getattr(auth_slot, "slot_kind", None) or "").strip().lower()
    if runtime_props.mode == "local_subscription" and slot_kind != "cli":
        raise RuntimeError(
            "AI runtime mode is local_subscription, but the active auth slot is not a CLI subscription."
        )
    if runtime_props.mode == "api_key" and slot_kind != "api_key":
        raise RuntimeError(
            "AI runtime mode is api_key, but the active auth slot is not an API key."
        )

    # Build scope context once
    scope_ctx = _build_assessment_scope_context(session, assessment)

    # Build tool-free CLI command (no MCP, no tool calls)
    env = os.environ.copy()
    if runtime_props.mode == "api_key":
        env.update(_api_key_env(resolved.provider_kind, auth_slot))
    cmd = _build_triage_cli_command(resolved, runtime_props)

    # Skip already-triaged artifacts
    processed_count = 0
    rows = [r for r in customized_results if not _artifact_processed(r)]
    already_done = len(customized_results) - len(rows)
    if already_done:
        logger.info("Skipping %d already-triaged artifacts, %d remaining.", already_done, len(rows))
    total_rows = len(rows)
    if total_rows == 0:
        return AIDispatchSummary(
            provider_kind=resolved.provider_kind,
            model_name=resolved.model_name,
            runtime_mode=runtime_props.mode,
            batch_count=0,
            processed_count=already_done,
            registered_prompt_name=registered_prompt_name,
            registered_prompt_error=registered_prompt_error,
        )

    prompt_dir = Path(__file__).resolve().parents[2] / "data" / "ai_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    for idx, row in enumerate(rows):
        # Read artifact data from DB (no MCP call)
        artifact_ctx = _build_artifact_context(session, row)

        prompt = (
            f"{scope_ctx}\n\n"
            f"{_AI_ANALYSIS_FALLBACK_GUIDANCE}\n\n"
            f"## Artifact to Classify (#{idx + 1} of {total_rows})\n\n"
            f"{artifact_ctx}\n\n"
            '## Required Output\n'
            'Respond with ONLY a JSON object, no other text:\n'
            '{"scope_decision": "in_scope|adjacent|out_of_scope", '
            '"scope_rationale": "<1 sentence>", '
            '"observations": "<1 sentence: what it is + why you classified it>"}\n'
        )

        # Debug file
        prompt_file = prompt_dir / f"triage_{os.getpid()}_{row.id}.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        try:
            started = time.monotonic()
            completed = subprocess.run(
                cmd, input=prompt, capture_output=True,
                text=True, timeout=cli_timeout_seconds, env=env,
            )
            duration = time.monotonic() - started

            if completed.returncode != 0:
                logger.warning("CLI failed for artifact %s (exit %s): %s",
                    row.id, completed.returncode, (completed.stderr or "")[:200])
                continue

            parsed = _parse_scope_response(completed.stdout)
            if not parsed or "scope_decision" not in parsed:
                logger.warning("No scope decision in output for artifact %s", row.id)
                continue

            # Write to DB directly — no MCP needed
            scope = parsed["scope_decision"]
            row.review_status = ReviewStatus.review_in_progress
            row.observations = parsed.get("observations", parsed.get("scope_rationale", ""))
            row.is_out_of_scope = scope == "out_of_scope"
            row.is_adjacent = scope == "adjacent"

            ai_obs = load_ai_observation_payload(row.ai_observations)
            ai_obs.update({
                "analysis_stage": "ai_analysis",
                "scope_decision": scope,
                "scope_rationale": parsed.get("scope_rationale", ""),
                "dispatch_trace": {
                    "provider_kind": resolved.provider_kind,
                    "model_name": resolved.model_name,
                    "duration_seconds": round(duration, 1),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            })
            row.ai_observations = json.dumps(
                merge_ai_observation_payload(row.ai_observations, ai_obs),
                sort_keys=True,
            )
            session.add(row)
            session.commit()
            processed_count += 1
            logger.info("Triaged %s/%s (id=%s): %s [%.1fs]",
                idx + 1, total_rows, row.id, scope, duration)

        except subprocess.TimeoutExpired:
            logger.warning("Timeout for artifact %s after %ss", row.id, cli_timeout_seconds)
            continue
        except Exception as exc:
            logger.warning("Error triaging artifact %s: %s", row.id, exc)
            continue

    return AIDispatchSummary(
        provider_kind=resolved.provider_kind,
        model_name=resolved.model_name,
        runtime_mode=runtime_props.mode,
        batch_count=total_rows,
        processed_count=processed_count,
        registered_prompt_name=registered_prompt_name,
        registered_prompt_error=registered_prompt_error,
    )
