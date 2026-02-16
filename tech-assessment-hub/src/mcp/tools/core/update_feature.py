"""MCP tool: update_feature — AI writes feature-level analysis.

Allows the AI to record description, disposition, recommendation,
and ai_summary on a Feature group.
"""

from datetime import datetime
from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Disposition, Feature


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "ID of the feature to update.",
        },
        "name": {
            "type": "string",
            "description": "Feature name.",
        },
        "description": {
            "type": "string",
            "description": "Feature description.",
        },
        "disposition": {
            "type": "string",
            "enum": ["remove", "keep_as_is", "keep_and_refactor", "needs_analysis"],
            "description": "Overall disposition for the feature.",
        },
        "recommendation": {
            "type": "string",
            "description": "Recommendation text.",
        },
        "ai_summary": {
            "type": "string",
            "description": "AI-generated summary of the feature analysis.",
        },
    },
    "required": ["feature_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    updated_fields = []

    if "disposition" in params:
        feature.disposition = Disposition(params["disposition"])
        updated_fields.append("disposition")

    for text_field in ("name", "description", "recommendation", "ai_summary"):
        if text_field in params:
            setattr(feature, text_field, params[text_field])
            updated_fields.append(text_field)

    if not updated_fields:
        return {"success": True, "message": "No fields to update.", "feature_id": feature_id}

    feature.updated_at = datetime.utcnow()
    session.add(feature)
    session.commit()
    session.refresh(feature)

    return {
        "success": True,
        "feature_id": feature_id,
        "updated_fields": updated_fields,
        "message": f"Updated {len(updated_fields)} field(s) on Feature {feature_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="update_feature",
    description=(
        "Update a feature group with AI analysis: name, description, disposition, "
        "recommendation, and ai_summary. Only specified fields are updated."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
