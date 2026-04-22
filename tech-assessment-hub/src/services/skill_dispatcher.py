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
import time
from pathlib import Path
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from ..database import DATA_DIR
from ..models import AppConfig
from .llm_adapters import SkillRunResult
from .llm_adapters.anthropic_api import AnthropicAPIAdapter
from .llm_adapters.anthropic_subprocess import AnthropicSubprocessAdapter

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
    )

    return result


def _write_run_trace(
    *,
    assessment_id: int,
    stage: str,
    skill_text: str,
    user_message: str,
    adapter_name: str,
    model: str,
    result: SkillRunResult,
) -> None:
    """Persist prompt + output + usage per run so failures are debuggable."""
    try:
        trace_dir = DATA_DIR / "logs" / "ai_prompts" / f"assessment_{assessment_id}"
        trace_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        base = trace_dir / f"{stage}-{stamp}"
        (base.with_suffix(".prompt.txt")).write_text(
            f"{skill_text}\n\n---\n\nUser request:\n{user_message}\n",
            encoding="utf-8",
        )
        (base.with_suffix(".output.txt")).write_text(result.output or "", encoding="utf-8")
        summary = {
            "assessment_id": assessment_id,
            "stage": stage,
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
