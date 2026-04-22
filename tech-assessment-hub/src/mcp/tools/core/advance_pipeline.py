"""MCP tool: advance_pipeline — move an assessment to the next pipeline stage.

Replaces the bash-curl pattern every SKILL.md used at its end:

    curl -s -X POST .../advance-pipeline -d '{"target_stage": "observations", "force": true}'

Which no longer works now that the CLI adapter disallows Bash. Skills should
call this MCP tool instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Assessment, PipelineStage


_VALID_STAGES = {s.value for s in PipelineStage}


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment whose pipeline_stage should change.",
        },
        "target_stage": {
            "type": "string",
            "enum": sorted(_VALID_STAGES),
            "description": (
                "Stage to move the assessment into. Call at the very end of a "
                "skill's work — e.g. scope-triage → 'observations', "
                "observations → 'review', grouping → 'ai_refinement', "
                "ai_refinement → 'recommendations', recommendations → 'report', "
                "report → 'complete'."
            ),
        },
    },
    "required": ["assessment_id", "target_stage"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    target_raw = str(params["target_stage"]).strip().lower()

    if target_raw not in _VALID_STAGES:
        raise ValueError(
            f"target_stage must be one of: {sorted(_VALID_STAGES)}; got '{target_raw}'"
        )

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise ValueError(f"Assessment {assessment_id} not found")

    previous = (
        assessment.pipeline_stage.value
        if hasattr(assessment.pipeline_stage, "value")
        else str(assessment.pipeline_stage)
    )
    now = datetime.utcnow()
    assessment.pipeline_stage = PipelineStage(target_raw)
    assessment.pipeline_stage_updated_at = now
    assessment.updated_at = now
    session.add(assessment)
    session.commit()

    return {
        "success": True,
        "assessment_id": assessment_id,
        "previous_stage": previous,
        "current_stage": target_raw,
        "message": f"Assessment {assessment_id} pipeline_stage: {previous} → {target_raw}",
    }


TOOL_SPEC = ToolSpec(
    name="advance_pipeline",
    description=(
        "Advance an assessment to the next pipeline stage at the END of a skill "
        "run. Replaces the old curl-based advance-pipeline call. Call exactly "
        "once when your stage's work is fully persisted. Valid targets are the "
        "PipelineStage enum values (ai_analysis, engines, observations, review, "
        "grouping, ai_refinement, recommendations, report, complete)."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
