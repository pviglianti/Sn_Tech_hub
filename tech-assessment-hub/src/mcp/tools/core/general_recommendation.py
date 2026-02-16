"""MCP tool: save_general_recommendation — AI writes assessment-level recommendations.

General technical recommendations not tied to specific artifacts -
e.g., governance gaps, platform maturity observations, upgrade risk themes.
"""

from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Assessment, GeneralRecommendation, Severity


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment this recommendation belongs to.",
        },
        "title": {
            "type": "string",
            "description": "Short recommendation title.",
        },
        "description": {
            "type": "string",
            "description": "Detailed recommendation text.",
        },
        "category": {
            "type": "string",
            "description": "Category: platform_maturity, governance, upgrade_risk, performance, security, best_practice.",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Severity level.",
        },
        "created_by": {
            "type": "string",
            "description": "Who created this (default: ai_agent).",
            "default": "ai_agent",
        },
    },
    "required": ["assessment_id", "title"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    severity = Severity(params["severity"]) if params.get("severity") else None

    recommendation = GeneralRecommendation(
        assessment_id=assessment_id,
        title=params["title"],
        description=params.get("description"),
        category=params.get("category"),
        severity=severity,
        created_by=params.get("created_by", "ai_agent"),
    )

    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)

    return {
        "success": True,
        "recommendation_id": recommendation.id,
        "title": recommendation.title,
        "message": f"General recommendation saved for assessment {assessment_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="save_general_recommendation",
    description=(
        "Save a general technical recommendation for an assessment. "
        "These are high-level observations not tied to a specific artifact - "
        "governance gaps, platform maturity themes, upgrade risk patterns, etc."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
