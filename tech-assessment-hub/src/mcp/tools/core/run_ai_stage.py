"""MCP tool to kick off an AI stage of the assessment pipeline."""

from __future__ import annotations

from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec

AI_STAGES = {"ai_analysis", "observations", "grouping", "ai_refinement", "recommendations", "report"}


def _handler(arguments: Dict[str, Any], session: Session) -> Dict[str, Any]:
    from src.server import _start_assessment_pipeline_job
    from src.models import Assessment

    assessment_id = int(arguments["assessment_id"])
    stage = arguments.get("stage")

    if stage and stage not in AI_STAGES:
        return {"error": f"Invalid AI stage: {stage}. Valid: {sorted(AI_STAGES)}"}

    if not stage:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            return {"error": f"Assessment {assessment_id} not found"}
        stage = assessment.pipeline_stage
        if stage not in AI_STAGES:
            return {"error": f"Current stage '{stage}' is not an AI stage"}

    success = _start_assessment_pipeline_job(
        assessment_id, target_stage=stage,
    )
    return {
        "started": success,
        "assessment_id": assessment_id,
        "stage": stage,
    }


run_ai_stage_tool = ToolSpec(
    name="run_ai_stage",
    description="Kick off the next AI stage of an assessment pipeline. "
                "Optionally specify stage, provider_override, model_override.",
    input_schema={
        "type": "object",
        "properties": {
            "assessment_id": {
                "type": "string",
                "description": "The assessment ID to run the AI stage for",
            },
            "stage": {
                "type": "string",
                "description": "Specific AI stage to run. Defaults to current stage.",
                "enum": sorted(AI_STAGES),
            },
        },
        "required": ["assessment_id"],
    },
    handler=_handler,
)

# Alias for registry consistency
TOOL_SPEC = run_ai_stage_tool
