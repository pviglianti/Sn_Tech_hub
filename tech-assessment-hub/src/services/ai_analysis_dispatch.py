"""Connected AI dispatch for the post-preflight ai_analysis stage.

Runs a tool-enabled local CLI session against the app's MCP endpoint so the
model can inspect customized results, write scope flags, and persist
relationship-aware observations through ``update_scan_result``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlmodel import Session

from ..models import Assessment, GlobalApp, ReviewStatus, ScanResult
from .ai_stage_tool_sets import STAGE_TOOL_SETS, build_batch_prompt
from .integration_properties import AIRuntimeProperties
from .llm.dispatcher_router import ResolvedConfig
from ..mcp.bridge.config_store import load_bridge_config
from ..mcp.registry import PROMPT_REGISTRY
from .query_builder import parse_list, resolve_assessment_drivers

_MCP_SERVER_ID = "tech_assessment_hub"
_MCP_TOOL_PREFIX = "mcp__tech-assessment-hub__"
_DEFAULT_HOST = (os.getenv("TECH_ASSESSMENT_HUB_HOST") or "127.0.0.1").strip()
_DEFAULT_PORT = int((os.getenv("TECH_ASSESSMENT_HUB_PORT") or "8080").strip())

_AI_ANALYSIS_FALLBACK_GUIDANCE = """\
You are running the first true AI review pass after preflight/data collection.

For the single artifact in this dispatch, work in this order:
1. Read the artifact with `get_result_detail`.
2. Decide whether it is `in_scope`, `adjacent`, `out_of_scope`, or `needs_review`
   relative to the assessment target application and tables.
3. Write a concrete functional observation in plain language:
   what triggers it, what tables/fields it reads or writes, what records it
   creates or updates, what conditions matter, and what downstream behavior it causes.
4. Only after the observation is grounded, identify other customized artifacts in
   this same assessment that are directly related to this artifact's behavior.
   Use `get_customizations` and follow up with `get_result_detail` as needed.
5. If you need extra product context about the target application itself, you may
   use `search_servicenow_docs` and `fetch_web_document` to confirm ServiceNow
   product terminology or capabilities. Treat that as supplemental context only.

Persist your findings with `update_scan_result` using:
- `review_status="review_in_progress"`
- `observations`
- `is_adjacent`
- `is_out_of_scope`
- `ai_observations` as a JSON object with this schema:
  {
    "analysis_stage": "ai_analysis",
    "scope_decision": "in_scope|adjacent|out_of_scope|needs_review",
    "scope_rationale": "<brief rationale>",
    "directly_related_result_ids": [<scan result ids>],
    "directly_related_artifacts": [
      {"result_id": <id>, "name": "<artifact name>", "relationship": "<how they connect>"}
    ]
  }

Rules:
- Engine signals and existing metadata are hints, not the source of truth.
- The assessment's configured target application/tables are the formal scope anchor.
- Never set final disposition, severity, or category in this stage.
- Out-of-scope artifacts still need a brief observation explaining why they are out.
- Adjacent artifacts remain in scope and may be grouped with direct artifacts.
- Reserve `adjacent` for artifacts that sit outside the direct target tables/forms
  but still support them. Tableless artifacts such as script includes are not
  adjacent by default; judge them as `in_scope` or `out_of_scope` based on behavior.
- Use actual customized artifact IDs when writing `directly_related_result_ids`.
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


def _resolve_rpc_url(session: Session) -> str:
    bridge_cfg = load_bridge_config(session)
    rpc_url = str(bridge_cfg.get("rpc_url") or "").strip()
    if rpc_url:
        return rpc_url

    management_base = str(bridge_cfg.get("management_base_url") or "").strip().rstrip("/")
    if management_base:
        return f"{management_base}/mcp"

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
) -> List[str]:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise RuntimeError("Claude CLI not found on PATH.")

    mcp_config = json.dumps(
        {
            "mcpServers": {
                "tech-assessment-hub": {
                    "url": rpc_url,
                    "transport": "http",
                    "description": "ServiceNow Tech Assessment Hub MCP",
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
        "--strict-mcp-config",
        "--mcp-config",
        mcp_config,
    ]
    if effort_level:
        cmd.extend(["--effort", effort_level])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    return cmd


def _build_codex_command(
    *,
    model_name: str,
    effort_level: str,
    enabled_tools: List[str],
    rpc_url: str,
    force_api_login: bool,
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
        )
    elif resolved.provider_kind == "openai":
        cmd = _build_codex_command(
            model_name=resolved.model_name,
            effort_level=resolved.effort_level,
            enabled_tools=_plain_tool_names(stage),
            rpc_url=rpc_url,
            force_api_login=runtime_props.mode == "api_key",
        )
    else:
        raise RuntimeError(
            f"Connected MCP ai_analysis dispatch is not implemented for provider '{resolved.provider_kind}'."
        )

    started = time.monotonic()
    completed = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=600,
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
    existing: Dict[str, Any] = {}
    if row.ai_observations:
        try:
            loaded = json.loads(row.ai_observations)
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {"raw_ai_observations": row.ai_observations}

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
    row.ai_observations = json.dumps(existing, sort_keys=True)


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
) -> AIDispatchSummary:
    """Run the connected-tool ai_analysis stage across customized artifacts."""

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

    rpc_url = _resolve_rpc_url(session)
    full_tool_names = list(STAGE_TOOL_SETS.get("ai_analysis", []))

    processed_count = 0
    rows = list(customized_results)
    total_rows = len(rows)
    if total_rows == 0:
        return AIDispatchSummary(
            provider_kind=resolved.provider_kind,
            model_name=resolved.model_name,
            runtime_mode=runtime_props.mode,
            batch_count=0,
            processed_count=0,
            registered_prompt_name=registered_prompt_name,
            registered_prompt_error=registered_prompt_error,
        )

    for batch_index, row in enumerate(rows):
        stage_instructions = _build_artifact_stage_instructions(
            session,
            assessment=assessment,
            row=row,
            methodology_prompt_text=registered_prompt_text,
        )
        prompt = build_batch_prompt(
            stage_instructions=stage_instructions,
            assessment_id=int(assessment.id),
            stage="ai_analysis",
            batch_index=batch_index,
            total_batches=total_rows,
            artifact_ids=[int(row.id)],
            artifact_names=[row.name or f"result_{row.id}"],
        )

        _run_cli_batch(
            prompt=prompt,
            resolved=resolved,
            runtime_props=runtime_props,
            stage="ai_analysis",
            allowed_tools=full_tool_names,
            rpc_url=rpc_url,
            auth_slot=auth_slot,
        )

        session.expire_all()
        refreshed = session.get(ScanResult, int(row.id))
        if refreshed is None or not _artifact_processed(refreshed):
            session.rollback()
            raise RuntimeError(
                f"AI analysis dispatch did not persist scope triage for result ID {int(row.id)}."
            )

        _merge_ai_trace(
            refreshed,
            resolved=resolved,
            runtime_props=runtime_props,
            batch_index=batch_index,
            total_batches=total_rows,
            registered_prompt_name=registered_prompt_name,
        )
        session.add(refreshed)
        processed_count += 1

        session.commit()

    return AIDispatchSummary(
        provider_kind=resolved.provider_kind,
        model_name=resolved.model_name,
        runtime_mode=runtime_props.mode,
        batch_count=total_rows,
        processed_count=processed_count,
        registered_prompt_name=registered_prompt_name,
        registered_prompt_error=registered_prompt_error,
    )
