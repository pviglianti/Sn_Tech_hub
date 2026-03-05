"""MCP tool: feature_grouping_status.

Reads latest FeatureGroupingRun status and current grouping coverage.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlmodel import Session, select, func

from ...registry import ToolSpec
from ....models import (
    Assessment,
    Feature,
    FeatureGroupingRun,
    FeatureScanResult,
    OriginType,
    Scan,
    ScanResult,
)


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to inspect (required when run_id omitted).",
        },
        "run_id": {
            "type": "integer",
            "description": "Specific FeatureGroupingRun row to inspect.",
        },
    },
}


_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}


def _parse_summary(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _coverage_summary(session: Session, assessment_id: int) -> Dict[str, Any]:
    customized_total = int(
        session.exec(
            select(func.count())
            .select_from(ScanResult)
            .join(Scan, ScanResult.scan_id == Scan.id)
            .where(Scan.assessment_id == assessment_id)
            .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
        ).one()
        or 0
    )

    feature_ids = session.exec(
        select(Feature.id).where(Feature.assessment_id == assessment_id)
    ).all()
    feature_ids = [fid for fid in feature_ids if fid is not None]
    if not feature_ids:
        return {
            "customized_total": customized_total,
            "assigned_customized": 0,
            "coverage_ratio": 0.0 if customized_total else 1.0,
            "feature_count": 0,
        }

    assigned_customized = int(
        session.exec(
            select(func.count(func.distinct(FeatureScanResult.scan_result_id)))
            .select_from(FeatureScanResult)
            .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
            .where(FeatureScanResult.feature_id.in_(feature_ids))
            .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
        ).one()
        or 0
    )

    coverage_ratio = assigned_customized / max(1, customized_total) if customized_total else 1.0
    return {
        "customized_total": customized_total,
        "assigned_customized": assigned_customized,
        "coverage_ratio": round(coverage_ratio, 6),
        "feature_count": len(feature_ids),
    }


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    run_id = params.get("run_id")
    assessment_id = params.get("assessment_id")

    run = None
    if run_id is not None:
        run = session.get(FeatureGroupingRun, int(run_id))
        if not run:
            raise ValueError(f"FeatureGroupingRun not found: {run_id}")
        assessment_id = int(run.assessment_id)
    else:
        if assessment_id is None:
            raise ValueError("Provide assessment_id or run_id")
        assessment = session.get(Assessment, int(assessment_id))
        if not assessment:
            raise ValueError(f"Assessment not found: {assessment_id}")
        run = session.exec(
            select(FeatureGroupingRun)
            .where(FeatureGroupingRun.assessment_id == int(assessment_id))
            .order_by(FeatureGroupingRun.id.desc())
            .limit(1)
        ).first()

    coverage = _coverage_summary(session, int(assessment_id))
    if not run:
        return {
            "success": True,
            "assessment_id": int(assessment_id),
            "run_found": False,
            "coverage": coverage,
        }

    return {
        "success": True,
        "assessment_id": int(assessment_id),
        "run_found": True,
        "run": {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "max_iterations": run.max_iterations,
            "iterations_completed": run.iterations_completed,
            "converged": bool(run.converged),
            "summary": _parse_summary(run.summary_json),
        },
        "coverage": coverage,
    }


TOOL_SPEC = ToolSpec(
    name="feature_grouping_status",
    description=(
        "Get latest feature-grouping run status and customized-membership coverage "
        "for an assessment."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)

