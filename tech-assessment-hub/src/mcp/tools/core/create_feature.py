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
        "feature_kind": {
            "type": "string",
            "enum": ["functional", "bucket"],
            "description": "Feature kind. functional for solution features, bucket for leftover categorical groupings.",
        },
        "composition_type": {
            "type": "string",
            "enum": ["direct", "adjacent", "mixed"],
            "description": "Optional initial composition hint. Usually recalculated from members.",
        },
        "name_status": {
            "type": "string",
            "enum": ["provisional", "final", "human_locked"],
            "description": "Naming lifecycle state for this feature.",
        },
        "bucket_key": {
            "type": "string",
            "description": "Optional bucket taxonomy key such as form_fields or acl.",
        },
    },
    "required": ["assessment_id", "name"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    name = str(params["name"])
    description = params.get("description")
    bucket_key = params.get("bucket_key")
    feature_kind = str(
        params.get("feature_kind") or ("bucket" if bucket_key else "functional")
    ).strip().lower()
    composition_type = params.get("composition_type")
    name_status = str(params.get("name_status") or "provisional").strip().lower()

    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    if feature_kind not in {"functional", "bucket"}:
        raise ValueError("feature_kind must be one of: functional, bucket")
    if name_status not in {"provisional", "final", "human_locked"}:
        raise ValueError("name_status must be one of: provisional, final, human_locked")
    if composition_type is not None:
        composition_type = str(composition_type).strip().lower()
        if composition_type not in {"direct", "adjacent", "mixed"}:
            raise ValueError("composition_type must be one of: direct, adjacent, mixed")
    if bucket_key is not None:
        bucket_key = str(bucket_key).strip().lower() or None

    feature = Feature(
        assessment_id=assessment_id,
        name=name,
        description=description,
        feature_kind=feature_kind,
        composition_type=composition_type,
        name_status=name_status,
        bucket_key=bucket_key,
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
        "feature_kind": feature.feature_kind,
        "composition_type": feature.composition_type,
        "name_status": feature.name_status,
        "bucket_key": feature.bucket_key,
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
