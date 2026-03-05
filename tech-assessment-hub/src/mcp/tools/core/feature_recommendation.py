"""MCP tool: upsert_feature_recommendation.

Persist structured feature-level OOTB replacement recommendations with product/SKU
provenance and explainability payloads.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Assessment, Feature, FeatureRecommendation


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "Feature being recommended for replace/refactor/keep/remove.",
        },
        "recommendation_id": {
            "type": "integer",
            "description": "Optional existing recommendation row ID to update.",
        },
        "recommendation_type": {
            "type": "string",
            "enum": ["replace", "refactor", "keep", "remove"],
            "description": "Disposition recommendation type for this feature.",
        },
        "ootb_capability_name": {"type": "string"},
        "product_name": {"type": "string"},
        "sku_or_license": {"type": "string"},
        "requires_plugins": {
            "description": "Array/object/string of plugin prerequisites for the recommendation.",
        },
        "fit_confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "evidence": {"description": "Structured evidence object/array/string."},
    },
    "required": ["feature_id", "recommendation_type"],
}


def _to_json_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    assessment = session.get(Assessment, feature.assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {feature.assessment_id}")

    recommendation: Optional[FeatureRecommendation] = None
    recommendation_id = params.get("recommendation_id")
    if recommendation_id is not None:
        recommendation = session.get(FeatureRecommendation, int(recommendation_id))
        if not recommendation or recommendation.feature_id != feature_id:
            raise ValueError(f"FeatureRecommendation not found for feature: {recommendation_id}")
    else:
        recommendation = FeatureRecommendation(
            instance_id=assessment.instance_id,
            assessment_id=assessment.id,
            feature_id=feature_id,
            recommendation_type=str(params["recommendation_type"]),
        )

    recommendation.recommendation_type = str(params["recommendation_type"])
    for field_name in ("ootb_capability_name", "product_name", "sku_or_license", "rationale"):
        if field_name in params:
            value = params.get(field_name)
            setattr(recommendation, field_name, None if value is None else str(value))

    if "fit_confidence" in params:
        raw_conf = params.get("fit_confidence")
        recommendation.fit_confidence = None if raw_conf in (None, "") else float(raw_conf)

    if "requires_plugins" in params:
        recommendation.requires_plugins_json = _to_json_string(params.get("requires_plugins"))
    if "evidence" in params:
        recommendation.evidence_json = _to_json_string(params.get("evidence"))

    recommendation.updated_at = datetime.utcnow()
    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)

    return {
        "success": True,
        "recommendation_id": recommendation.id,
        "feature_id": recommendation.feature_id,
        "recommendation_type": recommendation.recommendation_type,
        "product_name": recommendation.product_name,
        "sku_or_license": recommendation.sku_or_license,
        "fit_confidence": recommendation.fit_confidence,
    }


TOOL_SPEC = ToolSpec(
    name="upsert_feature_recommendation",
    description=(
        "Create or update a structured feature recommendation with OOTB capability, "
        "product/SKU provenance, plugin prerequisites, confidence, and rationale."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)

