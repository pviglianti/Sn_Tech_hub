"""SkillDispatcher — load assessment-plugin SKILL.md and run via the chosen adapter.

Single source of truth for "run AI on assessment X for stage Y":
  1. Look up the right SKILL.md by stage name
  2. Build the user message (assessment_id + any free-form instructions)
  3. Pick the adapter (CLI subprocess vs API) per app config
  4. Execute and return SkillRunResult
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from ..database import DATA_DIR
from ..models import AppConfig
from .llm_adapters import SkillRunResult
from .llm_adapters.anthropic_api import AnthropicAPIAdapter
from .llm_adapters.anthropic_subprocess import AnthropicSubprocessAdapter

logger = logging.getLogger(__name__)


# Where the plugin lives on disk. The repo ships the plugin alongside the app
# under /opt/ta-hub/app/assessment-plugin (deploy.sh tarball includes it via
# rsync from /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/assessment-plugin).
# We resolve relative to this file so it works regardless of CWD.
_PLUGIN_BASE = (Path(__file__).resolve().parents[3] / "assessment-plugin")

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

    return adapter.run(
        skill_text=skill_text,
        user_message=user_message,
        model=chosen_model,
        timeout_seconds=timeout_seconds,
        mcp_server_url=mcp_server_url,
        extra=extra,
    )
