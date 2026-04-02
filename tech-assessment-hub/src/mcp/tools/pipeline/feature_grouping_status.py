"""MCP tool: feature_grouping_status.

Reads latest FeatureGroupingRun status and current grouping coverage.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    Assessment,
    FeatureGroupingRun,
)
from ....services.feature_governance import build_feature_assignment_summary


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

def _parse_summary(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

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

    assignment_summary = build_feature_assignment_summary(session, assessment_id=int(assessment_id))
    resolved_total = int(assignment_summary.get("resolved_count") or 0)
    in_scope_total = int(assignment_summary.get("in_scope_customized_total") or 0)
    coverage_ratio = resolved_total / max(1, in_scope_total) if in_scope_total else 1.0
    coverage = {
        "customized_total": in_scope_total,
        "assigned_customized": int(assignment_summary.get("assigned_count") or 0),
        "resolved_customized": resolved_total,
        "human_standalone_count": int(assignment_summary.get("human_standalone_count") or 0),
        "coverage_ratio": round(coverage_ratio, 6),
        "feature_count": int(assignment_summary.get("feature_count") or 0),
        "bucket_feature_count": int(assignment_summary.get("bucket_feature_count") or 0),
        "provisional_feature_count": int(assignment_summary.get("provisional_feature_count") or 0),
        "all_in_scope_assigned": bool(assignment_summary.get("all_in_scope_assigned")),
        "manual_override_ready": bool(assignment_summary.get("manual_override_ready")),
        "unassigned_result_ids": list(assignment_summary.get("unassigned_result_ids") or []),
        "unassigned_results": list(assignment_summary.get("unassigned_results") or []),
        "blocking_reason": assignment_summary.get("blocking_reason"),
        "composition_counts": dict(assignment_summary.get("composition_counts") or {}),
    }
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
