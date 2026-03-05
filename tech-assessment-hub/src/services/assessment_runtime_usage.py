"""Assessment runtime usage snapshot service."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlmodel import Session, select

from ..models import (
    Assessment,
    AssessmentRuntimeUsage,
    Feature,
    FeatureRecommendation,
    FeatureScanResult,
    GeneralRecommendation,
    Instance,
    OriginType,
    Scan,
    ScanResult,
)
from .integration_properties import load_ai_runtime_properties


_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}


def _state_value(raw: Any) -> str:
    if raw is None:
        return ""
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw)


def _run_duration_seconds(assessment: Assessment) -> Optional[int]:
    start = assessment.started_at
    end = assessment.completed_at
    if not start:
        return None
    effective_end = end or datetime.utcnow()
    return max(0, int((effective_end - start).total_seconds()))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _merge_details(existing_json: Optional[str], details: Optional[Dict[str, Any]]) -> Optional[str]:
    if details is None:
        return existing_json
    payload: Dict[str, Any] = {}
    if existing_json:
        try:
            parsed = json.loads(existing_json)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
    payload["last_updated_at"] = datetime.utcnow().isoformat()
    payload["last_details"] = details
    return json.dumps(payload, sort_keys=True)


def _count_total_results(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(ScanResult.id))
            .join(Scan, ScanResult.scan_id == Scan.id)
            .where(Scan.assessment_id == assessment_id)
        ).one(),
        default=0,
    )


def _count_customized_results(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(ScanResult.id))
            .join(Scan, ScanResult.scan_id == Scan.id)
            .where(Scan.assessment_id == assessment_id)
            .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
        ).one(),
        default=0,
    )


def _count_total_features(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(Feature.id)).where(Feature.assessment_id == assessment_id)
        ).one(),
        default=0,
    )


def _count_feature_memberships(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(FeatureScanResult.id))
            .join(Feature, FeatureScanResult.feature_id == Feature.id)
            .where(Feature.assessment_id == assessment_id)
        ).one(),
        default=0,
    )


def _count_feature_recommendations(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(FeatureRecommendation.id))
            .where(FeatureRecommendation.assessment_id == assessment_id)
        ).one(),
        default=0,
    )


def _count_general_recommendations(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(GeneralRecommendation.id))
            .where(GeneralRecommendation.assessment_id == assessment_id)
        ).one(),
        default=0,
    )


def _count_general_technical_recommendations(session: Session, assessment_id: int) -> int:
    return _safe_int(
        session.exec(
            select(func.count(GeneralRecommendation.id))
            .where(GeneralRecommendation.assessment_id == assessment_id)
            .where(func.lower(GeneralRecommendation.category).like("%technical%"))
        ).one(),
        default=0,
    )


def _get_or_create_row(session: Session, assessment: Assessment) -> AssessmentRuntimeUsage:
    row = session.exec(
        select(AssessmentRuntimeUsage).where(AssessmentRuntimeUsage.assessment_id == assessment.id)
    ).first()
    if row:
        return row

    instance = session.get(Instance, assessment.instance_id)
    runtime_props = load_ai_runtime_properties(session, instance_id=assessment.instance_id)
    now = datetime.utcnow()

    row = AssessmentRuntimeUsage(
        assessment_id=int(assessment.id),
        instance_id=int(assessment.instance_id),
        assessment_number=assessment.number,
        assessment_name=assessment.name,
        instance_name=instance.name if instance else None,
        assessment_state=_state_value(assessment.state),
        llm_runtime_mode=runtime_props.mode,
        llm_provider=runtime_props.provider,
        llm_model=runtime_props.model,
        run_started_at=assessment.started_at,
        run_completed_at=assessment.completed_at,
        run_duration_seconds=_run_duration_seconds(assessment),
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def refresh_assessment_runtime_usage(
    session: Session,
    assessment_id: int,
    *,
    mcp_calls_local_delta: int = 0,
    mcp_calls_servicenow_delta: int = 0,
    mcp_calls_local_db_delta: int = 0,
    llm_input_tokens_delta: int = 0,
    llm_output_tokens_delta: int = 0,
    estimated_cost_usd_delta: float = 0.0,
    last_event: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    commit: bool = False,
) -> Optional[AssessmentRuntimeUsage]:
    """Create/update telemetry snapshot for one assessment."""
    assessment = session.get(Assessment, int(assessment_id))
    if not assessment or assessment.id is None:
        return None

    row = _get_or_create_row(session, assessment)
    instance = session.get(Instance, assessment.instance_id)
    runtime_props = load_ai_runtime_properties(session, instance_id=assessment.instance_id)

    row.instance_id = int(assessment.instance_id)
    row.assessment_number = assessment.number
    row.assessment_name = assessment.name
    row.instance_name = instance.name if instance else row.instance_name
    row.assessment_state = _state_value(assessment.state)
    row.llm_runtime_mode = runtime_props.mode
    row.llm_provider = runtime_props.provider
    row.llm_model = runtime_props.model
    row.run_started_at = assessment.started_at
    row.run_completed_at = assessment.completed_at
    row.run_duration_seconds = _run_duration_seconds(assessment)

    row.total_results = _count_total_results(session, int(assessment.id))
    row.customized_results = _count_customized_results(session, int(assessment.id))
    row.total_features = _count_total_features(session, int(assessment.id))
    row.total_groupings = row.total_features
    row.total_feature_memberships = _count_feature_memberships(session, int(assessment.id))
    row.total_general_recommendations = _count_general_recommendations(session, int(assessment.id))
    row.total_feature_recommendations = _count_feature_recommendations(session, int(assessment.id))
    technical_general_count = _count_general_technical_recommendations(session, int(assessment.id))
    row.total_technical_recommendations = (
        int(row.total_feature_recommendations) + int(technical_general_count)
    )

    row.mcp_calls_local = max(0, int(row.mcp_calls_local or 0) + _safe_int(mcp_calls_local_delta))
    row.mcp_calls_servicenow = max(
        0,
        int(row.mcp_calls_servicenow or 0) + _safe_int(mcp_calls_servicenow_delta),
    )
    row.mcp_calls_local_db = max(
        0,
        int(row.mcp_calls_local_db or 0) + _safe_int(mcp_calls_local_db_delta),
    )

    row.llm_input_tokens = max(
        0,
        int(row.llm_input_tokens or 0) + _safe_int(llm_input_tokens_delta),
    )
    row.llm_output_tokens = max(
        0,
        int(row.llm_output_tokens or 0) + _safe_int(llm_output_tokens_delta),
    )
    row.llm_total_tokens = int(row.llm_input_tokens) + int(row.llm_output_tokens)
    row.estimated_cost_usd = round(
        max(0.0, float(row.estimated_cost_usd or 0.0) + _safe_float(estimated_cost_usd_delta)),
        6,
    )

    if last_event:
        row.last_event = last_event
    row.details_json = _merge_details(row.details_json, details)

    row.updated_at = datetime.utcnow()
    session.add(row)

    if commit:
        session.commit()
        session.refresh(row)
    return row


def refresh_all_assessment_runtime_usage(session: Session, *, commit: bool = True) -> int:
    """Ensure telemetry snapshots exist and are current for all assessments."""
    ids = []
    for raw in session.exec(select(Assessment.id)).all():
        if raw is None:
            continue
        if isinstance(raw, (tuple, list)):
            value = raw[0] if raw else None
        else:
            value = raw
        if value is None:
            continue
        ids.append(int(value))

    for assessment_id in ids:
        refresh_assessment_runtime_usage(session, assessment_id, commit=False)
    if commit and ids:
        session.commit()
    return len(ids)
