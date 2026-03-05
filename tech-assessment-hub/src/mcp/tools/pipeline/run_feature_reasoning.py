"""MCP tool: run_feature_reasoning.

Executes one reasoning pass for feature grouping orchestration. The AI client
controls looping by calling this tool iteratively until convergence.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session, select

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
from ....services.integration_properties import load_reasoning_engine_properties
from .seed_feature_groups import seed_feature_groups


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to run one reasoning pass for.",
        },
        "run_id": {
            "type": "integer",
            "description": "Existing FeatureGroupingRun ID to continue.",
        },
        "pass_type": {
            "type": "string",
            "enum": ["auto", "observe", "group_refine", "verify"],
            "default": "auto",
            "description": "Reasoning pass type. auto chooses based on current state.",
        },
        "force_seed": {
            "type": "boolean",
            "default": False,
            "description": "Force deterministic re-seeding during this pass.",
        },
        "seed_min_group_size": {
            "type": "integer",
            "default": 2,
            "description": "Minimum group size when calling seed_feature_groups.",
        },
        "seed_min_edge_weight": {
            "type": "number",
            "default": 2.0,
            "description": "Min edge weight when calling seed_feature_groups.",
        },
        "max_iterations": {
            "type": "integer",
            "description": "Override max iterations for this run.",
        },
        "membership_delta_threshold": {
            "type": "number",
            "description": "Override convergence threshold for membership delta.",
        },
        "min_assignment_confidence": {
            "type": "number",
            "description": "Override high-confidence threshold for membership changes.",
        },
    },
    "required": ["assessment_id"],
}


_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}

_SOURCE_PRIORITY = {"human": 3, "ai": 2, "engine": 1}


def _origin_value(result: ScanResult) -> Optional[str]:
    if result.origin_type is None:
        return None
    if hasattr(result.origin_type, "value"):
        return result.origin_type.value
    return str(result.origin_type)


def _membership_snapshot(session: Session, assessment_id: int) -> Dict[int, Dict[str, Any]]:
    """Return best current feature assignment per customized result."""
    rows = session.exec(
        select(FeatureScanResult, Feature, ScanResult)
        .join(Feature, FeatureScanResult.feature_id == Feature.id)
        .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Feature.assessment_id == assessment_id)
        .where(Scan.assessment_id == assessment_id)
    ).all()

    best_by_result: Dict[int, Dict[str, Any]] = {}
    for link, feature, result in rows:
        if result.id is None:
            continue
        if (_origin_value(result) or "") not in _CUSTOMIZED_ORIGIN_VALUES:
            continue

        source = (link.assignment_source or "engine").strip().lower()
        source_priority = _SOURCE_PRIORITY.get(source, 0)
        confidence = float(link.assignment_confidence or 0.0)
        rank = (
            source_priority,
            1 if link.is_primary else 0,
            confidence,
            int(link.iteration_number or 0),
            link.created_at.isoformat() if link.created_at else "",
            int(link.id or 0),
        )
        existing = best_by_result.get(result.id)
        if existing is None or rank > existing["rank"]:
            best_by_result[result.id] = {
                "feature_id": int(feature.id),
                "assignment_source": source,
                "assignment_confidence": confidence,
                "iteration_number": int(link.iteration_number or 0),
                "rank": rank,
            }

    return {rid: {k: v for k, v in payload.items() if k != "rank"} for rid, payload in best_by_result.items()}


def _membership_delta(
    before: Dict[int, Dict[str, Any]],
    after: Dict[int, Dict[str, Any]],
    *,
    min_assignment_confidence: float,
) -> Dict[str, Any]:
    all_result_ids = sorted(set(before.keys()) | set(after.keys()))
    if not all_result_ids:
        return {
            "total_results_considered": 0,
            "changed_results": 0,
            "high_confidence_changes": 0,
            "delta_ratio": 0.0,
            "changed_result_ids": [],
        }

    changed_result_ids = []
    high_confidence_changes = 0
    for result_id in all_result_ids:
        before_feature = (before.get(result_id) or {}).get("feature_id")
        after_payload = after.get(result_id) or {}
        after_feature = after_payload.get("feature_id")
        if before_feature == after_feature:
            continue
        changed_result_ids.append(result_id)
        if float(after_payload.get("assignment_confidence") or 0.0) >= float(min_assignment_confidence):
            high_confidence_changes += 1

    changed_count = len(changed_result_ids)
    delta_ratio = changed_count / max(1, len(all_result_ids))
    return {
        "total_results_considered": len(all_result_ids),
        "changed_results": changed_count,
        "high_confidence_changes": high_confidence_changes,
        "delta_ratio": round(delta_ratio, 6),
        "changed_result_ids": changed_result_ids,
    }


def _has_engine_memberships(session: Session, assessment_id: int) -> bool:
    row = session.exec(
        select(FeatureScanResult.id)
        .join(Feature, FeatureScanResult.feature_id == Feature.id)
        .where(Feature.assessment_id == assessment_id)
        .where(FeatureScanResult.assignment_source == "engine")
        .limit(1)
    ).first()
    return row is not None


def _resolve_run(
    session: Session,
    *,
    assessment_id: int,
    run_id: Optional[int],
    max_iterations: int,
) -> FeatureGroupingRun:
    if run_id is not None:
        run = session.get(FeatureGroupingRun, int(run_id))
        if not run:
            raise ValueError(f"FeatureGroupingRun not found: {run_id}")
        if int(run.assessment_id) != int(assessment_id):
            raise ValueError(f"Run {run_id} does not belong to assessment {assessment_id}")
        return run

    run = FeatureGroupingRun(
        instance_id=session.get(Assessment, assessment_id).instance_id,  # type: ignore[arg-type]
        assessment_id=assessment_id,
        status="running",
        started_at=datetime.utcnow(),
        completed_at=None,
        max_iterations=max_iterations,
        iterations_completed=0,
        converged=False,
        summary_json=None,
    )
    session.add(run)
    session.flush()
    return run


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    props = load_reasoning_engine_properties(session, instance_id=assessment.instance_id)
    pass_type = str(params.get("pass_type", "auto")).strip().lower()
    if pass_type not in {"auto", "observe", "group_refine", "verify"}:
        raise ValueError("pass_type must be one of: auto, observe, group_refine, verify")

    max_iterations = int(params.get("max_iterations", props.feature_max_iterations))
    membership_delta_threshold = float(
        params.get("membership_delta_threshold", props.feature_membership_delta_threshold)
    )
    min_assignment_confidence = float(
        params.get("min_assignment_confidence", props.feature_min_assignment_confidence)
    )

    run = _resolve_run(
        session,
        assessment_id=assessment_id,
        run_id=params.get("run_id"),
        max_iterations=max_iterations,
    )

    run.status = "running"
    run.updated_at = datetime.utcnow()
    run.max_iterations = max_iterations

    before_snapshot = _membership_snapshot(session, assessment_id)

    force_seed = bool(params.get("force_seed", False))
    if pass_type == "auto":
        pass_type = "group_refine" if (force_seed or not _has_engine_memberships(session, assessment_id)) else "verify"

    run.iterations_completed = int(run.iterations_completed or 0) + 1
    current_iteration = int(run.iterations_completed)
    seed_result: Optional[Dict[str, Any]] = None

    if pass_type == "group_refine":
        seed_result = seed_feature_groups(
            session,
            assessment_id=assessment_id,
            min_group_size=max(1, int(params.get("seed_min_group_size", 2))),
            min_edge_weight=max(0.0, float(params.get("seed_min_edge_weight", 2.0))),
            reset_existing=True,
            iteration_number=current_iteration,
            commit=False,
        )

    # observe / verify currently read-only pass types.
    after_snapshot = _membership_snapshot(session, assessment_id)
    delta = _membership_delta(
        before_snapshot,
        after_snapshot,
        min_assignment_confidence=min_assignment_confidence,
    )

    converged = (
        float(delta["delta_ratio"]) < float(membership_delta_threshold)
        and int(delta["high_confidence_changes"]) == 0
    )
    run.converged = bool(converged)
    should_stop_for_iterations = int(run.iterations_completed) >= int(max_iterations)
    pass_completed = pass_type in {"verify"}
    is_done = bool(converged or should_stop_for_iterations or pass_completed)

    run.status = "completed" if is_done else "running"
    if is_done:
        run.completed_at = datetime.utcnow()

    summary_payload = {
        "assessment_id": assessment_id,
        "pass_type": pass_type,
        "iteration_number": current_iteration,
        "delta": delta,
        "membership_delta_threshold": membership_delta_threshold,
        "min_assignment_confidence": min_assignment_confidence,
        "seed_result": seed_result,
        "timestamp": datetime.utcnow().isoformat(),
    }
    run.summary_json = json.dumps(summary_payload, sort_keys=True)
    run.updated_at = datetime.utcnow()
    session.add(run)
    session.commit()
    session.refresh(run)

    return {
        "success": True,
        "assessment_id": assessment_id,
        "run_id": run.id,
        "status": run.status,
        "pass_type": pass_type,
        "iteration_number": current_iteration,
        "iterations_completed": run.iterations_completed,
        "max_iterations": run.max_iterations,
        "converged": run.converged,
        "delta": delta,
        "membership_delta_threshold": membership_delta_threshold,
        "min_assignment_confidence": min_assignment_confidence,
        "seed_result": seed_result,
        "should_continue": not is_done,
        "next_recommended_pass": None if is_done else "verify",
    }


TOOL_SPEC = ToolSpec(
    name="run_feature_reasoning",
    description=(
        "Run a single feature-reasoning pass (observe, group_refine, verify). "
        "Returns membership delta and convergence signals; caller decides whether to loop."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)

