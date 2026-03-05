"""MCP tool: get_feature_detail — read a feature group with linked scan results.

Returns the feature record plus its linked ScanResults (via FeatureScanResult).
"""

from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Feature, FeatureRecommendation, FeatureScanResult, ScanResult


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "ID of the feature to retrieve.",
        },
    },
    "required": ["feature_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    links = session.exec(
        select(FeatureScanResult).where(FeatureScanResult.feature_id == feature_id)
    ).all()
    recommendations = session.exec(
        select(FeatureRecommendation)
        .where(FeatureRecommendation.feature_id == feature_id)
        .order_by(FeatureRecommendation.id.asc())
    ).all()

    scan_results = []
    for link in links:
        sr = session.get(ScanResult, link.scan_result_id)
        if sr:
            scan_results.append({
                "id": sr.id,
                "sys_id": sr.sys_id,
                "table_name": sr.table_name,
                "name": sr.name,
                "origin_type": sr.origin_type.value if sr.origin_type else None,
                "disposition": sr.disposition.value if sr.disposition else None,
                "review_status": sr.review_status.value if sr.review_status else None,
                "severity": sr.severity.value if sr.severity else None,
                "is_primary": link.is_primary,
                "link_notes": link.notes,
            })

    return {
        "success": True,
        "feature": {
            "id": feature.id,
            "assessment_id": feature.assessment_id,
            "name": feature.name,
            "description": feature.description,
            "parent_id": feature.parent_id,
            "disposition": feature.disposition.value if feature.disposition else None,
            "recommendation": feature.recommendation,
            "ai_summary": feature.ai_summary,
            "created_at": feature.created_at.isoformat() if feature.created_at else None,
            "updated_at": feature.updated_at.isoformat() if feature.updated_at else None,
        },
        "recommendations": [
            {
                "id": recommendation.id,
                "recommendation_type": recommendation.recommendation_type,
                "ootb_capability_name": recommendation.ootb_capability_name,
                "product_name": recommendation.product_name,
                "sku_or_license": recommendation.sku_or_license,
                "requires_plugins": recommendation.requires_plugins_json,
                "fit_confidence": recommendation.fit_confidence,
                "rationale": recommendation.rationale,
                "evidence": recommendation.evidence_json,
            }
            for recommendation in recommendations
        ],
        "scan_results": scan_results,
        "scan_result_count": len(scan_results),
    }


TOOL_SPEC = ToolSpec(
    name="get_feature_detail",
    description=(
        "Get full details for a feature group including all linked scan results. "
        "Use this after seed_feature_groups or run_feature_reasoning to inspect a feature."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
