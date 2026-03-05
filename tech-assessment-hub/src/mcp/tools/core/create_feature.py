"""MCP tool: create_feature — AI creates a new Feature record.

Allows the AI to explicitly create a Feature during iterative analysis,
specifying a name and optional description.  The feature is linked to an
existing assessment and automatically assigned a color_index for visual
styling.
"""

from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Assessment, Feature


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "ID of the assessment to create the feature under.",
        },
        "name": {
            "type": "string",
            "description": "Feature name.",
        },
        "description": {
            "type": "string",
            "description": "Optional feature description.",
        },
    },
    "required": ["assessment_id", "name"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    name = str(params["name"])
    description = params.get("description")

    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    feature = Feature(
        assessment_id=assessment_id,
        name=name,
        description=description,
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)

    # Assign a deterministic color_index from the auto-generated id.
    feature.color_index = feature.id % 20
    session.add(feature)
    session.commit()
    session.refresh(feature)

    return {
        "success": True,
        "feature_id": feature.id,
        "name": feature.name,
        "color_index": feature.color_index,
        "message": f"Created Feature '{name}' (id={feature.id}) on Assessment {assessment_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="create_feature",
    description=(
        "Create a new feature group under an assessment. "
        "Accepts a name and optional description. "
        "Returns the new feature_id and its color_index."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
