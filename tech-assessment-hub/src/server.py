# server.py - FastAPI Application

from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sqlalchemy import func, desc, text, case, or_
import threading
import time
import os
import logging
import uuid
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .database import get_session, create_db_and_tables, engine
from .models import (
    Instance, Assessment, Scan, ScanResult, Customization, Feature, FeatureScanResult, FeatureContextArtifact, FeatureRecommendation,
    GlobalApp, AppFileClass, NumberSequence,
    ConnectionStatus, AssessmentState, AssessmentType, PipelineStage,
    ScanStatus,
    OriginType, HeadOwner, ReviewStatus, Disposition, Severity, FindingCategory,
    InstanceDataPull, DataPullType, DataPullStatus,
    Scope, Package, Application, UpdateSet, CustomerUpdateXML, VersionHistory,
    MetadataCustomization, InstancePlugin, PluginView, TableDefinition, InstanceAppFileType,
    AppConfig, JobRun, JobEvent, JobRunStatus,
    CodeReference, StructuralRelationship, UpdateSetOverlap,
    TemporalCluster, NamingCluster, TableColocationSummary, UpdateSetArtifactLink,
    BestPractice, BestPracticeCategory,
)
from .services.encryption import encrypt_password, decrypt_password
from .services.sn_client import ServiceNowClient, ServiceNowClientError
from .services.scan_executor import run_scans_for_assessment, execute_scan, reset_scan_state, classify_scan_results
from .services.data_pull_executor import (
    run_data_pulls_for_instance,
    execute_data_pull,
    DataPullMode,
    _estimate_expected_total,
    _get_db_derived_watermark,
    get_data_type_labels,
    get_assessment_preflight_data_types,
    get_assessment_preflight_model_map,
    get_data_pull_storage_tables,
)
from .services.integration_sync_runner import resolve_delta_decision
from .services.integration_properties import load_preflight_concurrent_types, load_ai_analysis_properties
from .services.contextual_lookup import gather_artifact_context
from .services.dictionary_pull_orchestrator import (
    start_dictionary_pull,
    get_dictionary_pull_status,
)
from .table_registry_catalog import get_all_default_sn_tables, get_table_source
from .seed_data import run_seed
from .mcp.server import handle_request as handle_mcp_request
from .mcp.tools.pipeline.run_engines import handle as run_preprocessing_engines_handle
from .mcp.tools.pipeline.seed_feature_groups import handle as seed_feature_groups_handle
from .mcp.tools.pipeline.run_feature_reasoning import handle as run_feature_reasoning_handle
from .mcp.tools.pipeline.generate_observations import handle as generate_observations_handle
from .mcp.bridge import (
    BRIDGE_MANAGER,
    load_bridge_config,
    save_bridge_config,
)
from .mcp.runtime.capabilities import get_capability_snapshot
from .mcp.runtime.audit import tail_audit_events
from .mcp.runtime.registry import load_runtime_config, save_runtime_config
from .inventory_class_catalog import inventory_class_tables
from .app_file_class_catalog import default_assessment_availability_for_instance_file_type
from .web.routes import analytics as analytics_routes
from .web.routes.analytics import analytics_router
from .web.routes.artifacts import artifacts_router
from .web.routes.csdm import csdm_router
from .web.routes.data_browser import data_browser_router
from .web.routes.dynamic_browser import dynamic_browser_router
from .web.routes.instances import create_instances_router
from .web.routes.job_log import job_log_router
from .web.routes.mcp_admin import mcp_admin_router
from .web.routes.preferences import create_preferences_router
from .web.routes.customizations import customizations_router
from .web.routes.pulls import create_pulls_router
import json
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

@dataclass
class _DataPullJob:
    """In-process coordinator for instance-level data pull threads."""

    instance_id: int
    run_uid: str
    data_types: List[str]
    mode: str
    cancel_event: threading.Event
    thread: Optional[threading.Thread]
    started_at: datetime


_DATA_PULL_JOBS_LOCK = threading.Lock()
_DATA_PULL_JOBS: Dict[int, _DataPullJob] = {}
_DATA_PULL_RUN_MODULE = "preflight"
_DATA_PULL_RUN_TYPE = "data_pull"
_TERMINAL_PULL_STATUSES = {
    DataPullStatus.completed.value,
    DataPullStatus.failed.value,
    DataPullStatus.cancelled.value,
}

# ── Proactive VH pull infrastructure ──
# Per-instance threading.Event that signals when the VH pull completes.
# Keyed by instance_id.  Created by _start_proactive_vh_pull(), consumed
# by Stage 5 in _run_scans_background().
_VH_EVENTS_LOCK = threading.Lock()
_VH_EVENTS: Dict[int, threading.Event] = {}


def _json_dumps(payload: Any) -> Optional[str]:
    if payload is None:
        return None
    try:
        return json.dumps(payload, sort_keys=True)
    except Exception:
        return None


def _append_data_pull_event(
    session: Session,
    run: JobRun,
    *,
    event_type: str,
    summary: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    now = datetime.utcnow()
    event = JobEvent(
        run_id=run.id,
        event_type=event_type,
        summary=summary,
        data_json=_json_dumps(payload),
        created_at=now,
    )
    run.last_heartbeat_at = now
    run.updated_at = now
    session.add(run)
    session.add(event)


def _create_data_pull_run_record(instance_id: int, data_types: List[str], mode: str, source_context: str = "preflight") -> str:
    run_uid = uuid.uuid4().hex
    now = datetime.utcnow()
    with Session(engine) as session:
        run = JobRun(
            run_uid=run_uid,
            instance_id=instance_id,
            module=_DATA_PULL_RUN_MODULE,
            job_type=_DATA_PULL_RUN_TYPE,
            mode=mode,
            status=JobRunStatus.queued,
            queue_total=len(data_types),
            queue_completed=0,
            progress_pct=0,
            message=f"Queued {len(data_types)} pull type(s).",
            requested_data_types_json=_json_dumps(list(data_types)),
            metadata_json=_json_dumps({"source": source_context}),
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_data_pull_event(
            session,
            run,
            event_type="queued",
            summary="Data pull run queued.",
            payload={"mode": mode, "data_types": data_types},
        )
        session.commit()
    return run_uid


def _load_data_pull_run(session: Session, run_uid: str) -> Optional[JobRun]:
    return session.exec(select(JobRun).where(JobRun.run_uid == run_uid)).first()


def _mark_data_pull_run_running(session: Session, run_uid: str, total: int) -> None:
    run = _load_data_pull_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = JobRunStatus.running
    run.started_at = now
    run.completed_at = None
    run.queue_total = max(0, int(total or 0))
    run.queue_completed = 0
    run.current_index = 1 if run.queue_total > 0 else None
    run.current_data_type = None
    run.progress_pct = 0
    run.estimated_remaining_seconds = None
    run.error_message = None
    run.message = "Starting data pulls..."
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_data_pull_event(
        session,
        run,
        event_type="started",
        summary="Data pull run started.",
        payload={"queue_total": run.queue_total},
    )
    session.commit()


def _mark_data_pull_run_item_started(
    session: Session,
    run_uid: str,
    data_type: DataPullType,
    index: int,
    total: int,
) -> None:
    run = _load_data_pull_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = JobRunStatus.running
    run.current_data_type = data_type.value
    run.current_index = index
    run.queue_total = max(run.queue_total, total)
    run.progress_pct = int(round((max(run.queue_completed, 0) / max(total, 1)) * 100))
    run.message = f"Pulling {index} of {total}: {data_type.value}"
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_data_pull_event(
        session,
        run,
        event_type="item_started",
        summary=f"Started {data_type.value}.",
        payload={"data_type": data_type.value, "index": index, "total": total},
    )
    session.commit()


def _mark_data_pull_run_item_completed(
    session: Session,
    run_uid: str,
    data_type: DataPullType,
    pull: InstanceDataPull,
    index: int,
    total: int,
) -> None:
    run = _load_data_pull_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.queue_total = max(run.queue_total, total)
    run.queue_completed = max(run.queue_completed, index)
    run.current_data_type = None
    run.current_index = None
    run.progress_pct = int(round((run.queue_completed / max(total, 1)) * 100))
    run.message = f"{data_type.value}: {pull.status.value}"
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_data_pull_event(
        session,
        run,
        event_type="item_completed",
        summary=f"Finished {data_type.value} ({pull.status.value}).",
        payload={
            "data_type": data_type.value,
            "status": pull.status.value,
            "records_pulled": pull.records_pulled,
            "expected_total": pull.expected_total,
            "index": index,
            "total": total,
        },
    )
    session.commit()


def _mark_data_pull_run_finished(
    session: Session,
    run_uid: str,
    *,
    status: JobRunStatus,
    queue_completed: int,
    queue_total: int,
    message: str,
    error_message: Optional[str] = None,
) -> None:
    run = _load_data_pull_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = status
    run.completed_at = now
    run.queue_total = max(run.queue_total, queue_total)
    run.queue_completed = min(max(queue_completed, 0), max(run.queue_total, 0))
    run.current_data_type = None
    run.current_index = None
    run.progress_pct = 100
    run.error_message = error_message
    run.message = message
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_data_pull_event(
        session,
        run,
        event_type=status.value,
        summary=message,
        payload={"queue_completed": run.queue_completed, "queue_total": run.queue_total},
    )
    session.commit()


@dataclass
class _AssessmentScanJob:
    """In-process coordinator for assessment scan workflows."""

    assessment_id: int
    run_uid: str
    mode: str
    stage: str
    status: str
    message: str
    started_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]
    thread: Optional[threading.Thread]
    postflight_details: Optional[List[Dict[str, Any]]] = None


_ASSESSMENT_SCAN_JOBS_LOCK = threading.Lock()
_ASSESSMENT_SCAN_JOBS: Dict[int, _AssessmentScanJob] = {}
_ASSESSMENT_SCAN_MODE_LABELS = {
    "full": "Refresh Scans",
    "delta": "Refresh Delta",
    "rebuild": "Rebuild Scans",
}
_ASSESSMENT_SCAN_STAGE_LABELS = {
    "queued": "Queued",
    "validating_instance": "Validating instance connection",
    "preflight_required_sync": "Syncing required preflight data",
    "running_scans": "Running scans",
    "postflight_artifact_pull": "Pulling artifact details",
    "preflight_optional_sync": "Syncing remaining preflight data",
    "version_history_catchup": "Completing version history catch-up",
    "completed": "Completed",
    "failed": "Failed",
}
_ASSESSMENT_SCAN_RUN_MODULE = "assessment"
_ASSESSMENT_SCAN_RUN_TYPE = "assessment_scan"
_POSTFLIGHT_RUN_MODULE = "postflight"
_POSTFLIGHT_RUN_TYPE = "artifact_pull"


@dataclass
class _AssessmentPipelineJob:
    """In-process coordinator for post-scan pipeline stages."""

    assessment_id: int
    run_uid: str
    target_stage: str
    stage: str
    status: str
    message: str
    progress_percent: int
    started_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]
    thread: Optional[threading.Thread]


_ASSESSMENT_PIPELINE_JOBS_LOCK = threading.Lock()
_ASSESSMENT_PIPELINE_JOBS: Dict[int, _AssessmentPipelineJob] = {}
_ASSESSMENT_PIPELINE_RUN_MODULE = "assessment"
_ASSESSMENT_PIPELINE_RUN_TYPE = "reasoning_pipeline"
_PIPELINE_STAGE_ORDER: List[str] = [
    PipelineStage.scans.value,
    PipelineStage.ai_analysis.value,
    PipelineStage.engines.value,
    PipelineStage.observations.value,
    PipelineStage.review.value,
    PipelineStage.grouping.value,
    PipelineStage.ai_refinement.value,
    PipelineStage.recommendations.value,
    PipelineStage.report.value,
    PipelineStage.complete.value,
]
_PIPELINE_STAGE_LABELS: Dict[str, str] = {
    PipelineStage.scans.value: "Scans",
    PipelineStage.ai_analysis.value: "AI Analysis",
    PipelineStage.engines.value: "Engines",
    PipelineStage.observations.value: "Observations",
    PipelineStage.review.value: "Review",
    PipelineStage.grouping.value: "Grouping",
    PipelineStage.ai_refinement.value: "AI Refinement",
    PipelineStage.recommendations.value: "Recommendations",
    PipelineStage.report.value: "Report",
    PipelineStage.complete.value: "Complete",
}
_PIPELINE_STAGE_AUTONEXT: Dict[str, str] = {
    PipelineStage.ai_analysis.value: PipelineStage.engines.value,
    PipelineStage.engines.value: PipelineStage.observations.value,
    PipelineStage.observations.value: PipelineStage.review.value,
    PipelineStage.grouping.value: PipelineStage.ai_refinement.value,
    PipelineStage.ai_refinement.value: PipelineStage.recommendations.value,
    PipelineStage.recommendations.value: PipelineStage.report.value,
    PipelineStage.report.value: PipelineStage.complete.value,
}


def _assessment_scan_progress_percent(
    stage: str,
    status: str,
    scan_counts: Optional[Dict[str, int]] = None,
) -> int:
    if status == "completed":
        return 100
    if status == "failed":
        return 100
    if stage == "queued":
        return 5
    if stage == "validating_instance":
        return 12
    if stage == "preflight_required_sync":
        return 28
    if stage == "running_scans":
        counts = scan_counts or {}
        total = int(counts.get("total") or 0)
        done = int(counts.get("completed") or 0) + int(counts.get("failed") or 0) + int(counts.get("cancelled") or 0)
        if total > 0:
            return min(85, 35 + int((done / total) * 50))
        return 40
    if stage == "postflight_artifact_pull":
        return 88
    if stage == "preflight_optional_sync":
        return 93
    if stage == "version_history_catchup":
        return 97
    return 10


def _assessment_scan_job_status_to_run_status(status: str) -> JobRunStatus:
    normalized = (status or "").strip().lower()
    if normalized == "completed":
        return JobRunStatus.completed
    if normalized == "failed":
        return JobRunStatus.failed
    if normalized == "cancelled":
        return JobRunStatus.cancelled
    if normalized in {"queued", "pending"}:
        return JobRunStatus.queued
    return JobRunStatus.running


def _pipeline_stage_value(raw_stage: Any) -> str:
    if raw_stage is None:
        return PipelineStage.scans.value
    if hasattr(raw_stage, "value"):
        return str(raw_stage.value)
    stage = str(raw_stage).strip().lower()
    return stage if stage in _PIPELINE_STAGE_ORDER else PipelineStage.scans.value


def _pipeline_stage_index(stage_value: str) -> int:
    try:
        return _PIPELINE_STAGE_ORDER.index(_pipeline_stage_value(stage_value))
    except ValueError:
        return 0


def _assessment_pipeline_job_status_to_run_status(status: str) -> JobRunStatus:
    normalized = (status or "").strip().lower()
    if normalized == "completed":
        return JobRunStatus.completed
    if normalized == "failed":
        return JobRunStatus.failed
    if normalized == "cancelled":
        return JobRunStatus.cancelled
    if normalized in {"queued", "pending"}:
        return JobRunStatus.queued
    return JobRunStatus.running


def _assessment_pipeline_metadata(raw: Optional[str]) -> Dict[str, Any]:
    parsed = _safe_json(raw, {})
    if isinstance(parsed, dict):
        return parsed
    return {}


def _find_assessment_pipeline_run(
    session: Session,
    assessment_id: int,
    *,
    active_only: bool,
) -> Optional[JobRun]:
    stmt = (
        select(JobRun)
        .where(JobRun.module == _ASSESSMENT_PIPELINE_RUN_MODULE)
        .where(JobRun.job_type == _ASSESSMENT_PIPELINE_RUN_TYPE)
    )
    if active_only:
        stmt = stmt.where(JobRun.status.in_([JobRunStatus.queued, JobRunStatus.running]))
    runs = session.exec(stmt.order_by(JobRun.created_at.desc()).limit(200)).all()
    for run in runs:
        metadata = _assessment_pipeline_metadata(run.metadata_json)
        if int(metadata.get("assessment_id") or 0) == assessment_id:
            return run
    return None


def _create_assessment_pipeline_run_record(assessment_id: int, target_stage: str) -> Optional[str]:
    now = datetime.utcnow()
    with Session(engine) as session:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            return None
        run_uid = uuid.uuid4().hex
        run = JobRun(
            run_uid=run_uid,
            instance_id=assessment.instance_id,
            module=_ASSESSMENT_PIPELINE_RUN_MODULE,
            job_type=_ASSESSMENT_PIPELINE_RUN_TYPE,
            mode=target_stage,
            status=JobRunStatus.queued,
            queue_total=1,
            queue_completed=0,
            progress_pct=5,
            current_data_type=target_stage,
            message=f"Queued pipeline stage: {target_stage}",
            metadata_json=_json_dumps(
                {
                    "assessment_id": assessment_id,
                    "target_stage": target_stage,
                    "stage": target_stage,
                }
            ),
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_data_pull_event(
            session,
            run,
            event_type="queued",
            summary="Assessment pipeline stage queued.",
            payload={"assessment_id": assessment_id, "target_stage": target_stage},
        )
        session.commit()
        return run_uid


def _update_assessment_pipeline_run_state(
    assessment_id: int,
    run_uid: Optional[str],
    *,
    stage: str,
    status: str,
    message: str,
    progress_percent: Optional[int] = None,
) -> None:
    if not run_uid:
        return
    with Session(engine) as session:
        run = _load_data_pull_run(session, run_uid)
        if not run:
            return
        run_status = _assessment_pipeline_job_status_to_run_status(status)
        now = datetime.utcnow()
        run.status = run_status
        if run_status in {JobRunStatus.running, JobRunStatus.queued} and not run.started_at:
            run.started_at = now
        if run_status in {JobRunStatus.completed, JobRunStatus.failed, JobRunStatus.cancelled}:
            run.completed_at = now
            run.queue_completed = 1
        else:
            run.completed_at = None
            run.queue_completed = 0
        run.queue_total = 1
        run.current_data_type = stage
        run.current_index = None if run.queue_completed else 1
        if progress_percent is None:
            progress_percent = 100 if run.queue_completed else 20
        run.progress_pct = max(0, min(100, int(progress_percent)))
        run.message = message
        run.error_message = message if run_status == JobRunStatus.failed else None
        metadata = _assessment_pipeline_metadata(run.metadata_json)
        metadata["assessment_id"] = assessment_id
        metadata["stage"] = stage
        run.metadata_json = _json_dumps(metadata)
        run.updated_at = now
        run.last_heartbeat_at = now
        event_type = run_status.value if run_status in {
            JobRunStatus.completed,
            JobRunStatus.failed,
            JobRunStatus.cancelled,
        } else "progress"
        _append_data_pull_event(
            session,
            run,
            event_type=event_type,
            summary=message,
            payload={
                "assessment_id": assessment_id,
                "stage": stage,
                "status": status,
                "progress_percent": run.progress_pct,
            },
        )
        session.commit()


def _serialize_assessment_pipeline_run(run: JobRun, *, is_alive: bool) -> Dict[str, Any]:
    raw_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    status = raw_status
    if raw_status in {JobRunStatus.queued.value, JobRunStatus.running.value}:
        status = "running"
    elif raw_status == JobRunStatus.cancelled.value:
        status = "failed"

    metadata = _assessment_pipeline_metadata(run.metadata_json)
    stage = _pipeline_stage_value(metadata.get("stage") or run.current_data_type or run.mode)
    target_stage = _pipeline_stage_value(metadata.get("target_stage") or run.mode or stage)
    return {
        "run_uid": run.run_uid,
        "status": status,
        "message": run.message,
        "is_alive": is_alive,
        "job_type": _ASSESSMENT_PIPELINE_RUN_TYPE,
        "target_stage": target_stage,
        "target_stage_label": _PIPELINE_STAGE_LABELS.get(target_stage, target_stage.title()),
        "stage": stage,
        "stage_label": _PIPELINE_STAGE_LABELS.get(stage, stage.title()),
        "progress_percent": int(run.progress_pct or 0),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _set_assessment_pipeline_job_state(
    assessment_id: int,
    *,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    message: Optional[str] = None,
    progress_percent: Optional[int] = None,
) -> None:
    run_uid: Optional[str] = None
    resolved_stage = stage
    resolved_status = status
    resolved_message = message
    resolved_progress = progress_percent

    with _ASSESSMENT_PIPELINE_JOBS_LOCK:
        job = _ASSESSMENT_PIPELINE_JOBS.get(assessment_id)
        if not job:
            return
        run_uid = job.run_uid
        if stage is not None:
            job.stage = _pipeline_stage_value(stage)
        if status is not None:
            job.status = status
        if message is not None:
            job.message = message
        if progress_percent is not None:
            job.progress_percent = max(0, min(100, int(progress_percent)))
        job.updated_at = datetime.utcnow()
        if job.status in {"completed", "failed"}:
            job.finished_at = job.updated_at

        resolved_stage = job.stage
        resolved_status = job.status
        resolved_message = job.message
        resolved_progress = job.progress_percent

    if resolved_stage and resolved_status and resolved_message is not None:
        _update_assessment_pipeline_run_state(
            assessment_id,
            run_uid,
            stage=resolved_stage,
            status=resolved_status,
            message=resolved_message,
            progress_percent=resolved_progress,
        )


def _get_assessment_pipeline_job_snapshot(
    assessment_id: int,
    *,
    session: Session,
) -> Optional[Dict[str, Any]]:
    with _ASSESSMENT_PIPELINE_JOBS_LOCK:
        in_memory = _ASSESSMENT_PIPELINE_JOBS.get(assessment_id)
        if in_memory:
            is_alive = bool(in_memory.thread and in_memory.thread.is_alive())
            if in_memory.status == "running" and not is_alive:
                in_memory.status = "failed"
                if not in_memory.message:
                    in_memory.message = "Pipeline job exited unexpectedly."
                in_memory.updated_at = datetime.utcnow()
                in_memory.finished_at = in_memory.updated_at
            return {
                "run_uid": in_memory.run_uid,
                "status": in_memory.status,
                "message": in_memory.message,
                "is_alive": is_alive,
                "job_type": _ASSESSMENT_PIPELINE_RUN_TYPE,
                "target_stage": in_memory.target_stage,
                "target_stage_label": _PIPELINE_STAGE_LABELS.get(in_memory.target_stage, in_memory.target_stage.title()),
                "stage": in_memory.stage,
                "stage_label": _PIPELINE_STAGE_LABELS.get(in_memory.stage, in_memory.stage.title()),
                "progress_percent": max(0, min(100, int(in_memory.progress_percent))),
                "started_at": in_memory.started_at.isoformat() if in_memory.started_at else None,
                "updated_at": in_memory.updated_at.isoformat() if in_memory.updated_at else None,
                "finished_at": in_memory.finished_at.isoformat() if in_memory.finished_at else None,
            }

    run = _find_assessment_pipeline_run(session, assessment_id, active_only=False)
    if not run:
        return None
    return _serialize_assessment_pipeline_run(run, is_alive=False)


def _set_assessment_pipeline_stage(
    assessment_id: int,
    stage: str,
    *,
    session: Optional[Session] = None,
) -> None:
    target_stage = _pipeline_stage_value(stage)
    now = datetime.utcnow()
    if session is not None:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            return
        assessment.pipeline_stage = PipelineStage(target_stage)
        assessment.pipeline_stage_updated_at = now
        assessment.updated_at = now
        session.add(assessment)
        session.commit()
        return

    with Session(engine) as run_session:
        assessment = run_session.get(Assessment, assessment_id)
        if not assessment:
            return
        assessment.pipeline_stage = PipelineStage(target_stage)
        assessment.pipeline_stage_updated_at = now
        assessment.updated_at = now
        run_session.add(assessment)
        run_session.commit()


def _assessment_review_gate_summary(session: Session, assessment_id: int) -> Dict[str, Any]:
    rows = session.exec(
        select(ScanResult.review_status, func.count())
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Scan.assessment_id == assessment_id)
        .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
        .group_by(ScanResult.review_status)
    ).all()

    reviewed = 0
    pending = 0
    in_progress = 0
    for status, count in rows:
        key = status.value if hasattr(status, "value") else str(status)
        normalized = str(key or "").strip().lower()
        value = int(count or 0)
        if normalized == ReviewStatus.reviewed.value:
            reviewed += value
        elif normalized == ReviewStatus.review_in_progress.value:
            in_progress += value
        else:
            pending += value

    total = reviewed + pending + in_progress
    return {
        "reviewed": reviewed,
        "pending": pending,
        "in_progress": in_progress,
        "total_customized": total,
        "all_reviewed": total > 0 and reviewed >= total,
    }


def _assessment_scan_metadata(raw: Optional[str]) -> Dict[str, Any]:
    parsed = _safe_json(raw, {})
    if isinstance(parsed, dict):
        return parsed
    return {}


def _assessment_scan_counts(session: Session, assessment_id: int) -> Dict[str, int]:
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "total": 0}
    rows = session.exec(
        select(Scan.status, func.count())
        .where(Scan.assessment_id == assessment_id)
        .group_by(Scan.status)
    ).all()
    total = 0
    for status, count in rows:
        key = status.value if hasattr(status, "value") else str(status)
        normalized = str(key or "").strip().lower()
        value = int(count or 0)
        total += value
        if normalized in counts:
            counts[normalized] = value
    counts["total"] = total
    return counts


def _find_assessment_scan_run(
    session: Session,
    assessment_id: int,
    *,
    active_only: bool,
) -> Optional[JobRun]:
    stmt = (
        select(JobRun)
        .where(JobRun.module == _ASSESSMENT_SCAN_RUN_MODULE)
        .where(JobRun.job_type == _ASSESSMENT_SCAN_RUN_TYPE)
    )
    if active_only:
        stmt = stmt.where(JobRun.status.in_([JobRunStatus.queued, JobRunStatus.running]))
    runs = session.exec(stmt.order_by(JobRun.created_at.desc()).limit(200)).all()
    for run in runs:
        metadata = _assessment_scan_metadata(run.metadata_json)
        if int(metadata.get("assessment_id") or 0) == assessment_id:
            return run
    return None


def _create_assessment_scan_run_record(assessment_id: int, mode: str) -> Optional[str]:
    now = datetime.utcnow()
    with Session(engine) as session:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            return None
        run_uid = uuid.uuid4().hex
        run = JobRun(
            run_uid=run_uid,
            instance_id=assessment.instance_id,
            module=_ASSESSMENT_SCAN_RUN_MODULE,
            job_type=_ASSESSMENT_SCAN_RUN_TYPE,
            mode=mode,
            status=JobRunStatus.queued,
            queue_total=0,
            queue_completed=0,
            progress_pct=5,
            current_data_type="queued",
            message="Queued scan workflow.",
            metadata_json=_json_dumps({"assessment_id": assessment_id}),
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_data_pull_event(
            session,
            run,
            event_type="queued",
            summary="Assessment scan workflow queued.",
            payload={"assessment_id": assessment_id, "mode": mode},
        )
        session.commit()
        return run_uid


def _update_assessment_scan_run_state(
    assessment_id: int,
    run_uid: Optional[str],
    *,
    stage: str,
    status: str,
    message: str,
) -> None:
    if not run_uid:
        return
    with Session(engine) as session:
        run = _load_data_pull_run(session, run_uid)
        if not run:
            return

        scan_counts = _assessment_scan_counts(session, assessment_id)
        queue_total = int(scan_counts.get("total") or 0)
        queue_completed = (
            int(scan_counts.get("completed") or 0)
            + int(scan_counts.get("failed") or 0)
            + int(scan_counts.get("cancelled") or 0)
        )
        run_status = _assessment_scan_job_status_to_run_status(status)
        now = datetime.utcnow()

        run.status = run_status
        if run_status in {JobRunStatus.running, JobRunStatus.queued} and not run.started_at:
            run.started_at = now
        if run_status in {JobRunStatus.completed, JobRunStatus.failed, JobRunStatus.cancelled}:
            run.completed_at = now
        else:
            run.completed_at = None

        run.queue_total = queue_total
        run.queue_completed = min(max(queue_completed, 0), max(queue_total, 0))
        run.current_data_type = stage
        if run_status == JobRunStatus.running and queue_total > 0 and run.queue_completed < queue_total:
            run.current_index = run.queue_completed + 1
        else:
            run.current_index = None
        run.progress_pct = _assessment_scan_progress_percent(stage, status, scan_counts=scan_counts)
        run.message = message
        run.error_message = message if run_status == JobRunStatus.failed else None
        run.updated_at = now
        run.last_heartbeat_at = now

        event_type = run_status.value if run_status in {
            JobRunStatus.completed,
            JobRunStatus.failed,
            JobRunStatus.cancelled,
        } else "progress"
        _append_data_pull_event(
            session,
            run,
            event_type=event_type,
            summary=message,
            payload={
                "assessment_id": assessment_id,
                "stage": stage,
                "status": status,
                "queue_completed": run.queue_completed,
                "queue_total": run.queue_total,
            },
        )
        session.commit()


def _serialize_assessment_scan_run(
    run: JobRun,
    *,
    assessment_id: int,
    is_alive: bool,
    scan_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    raw_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    status = raw_status
    if raw_status in {JobRunStatus.queued.value, JobRunStatus.running.value}:
        status = "running"
    elif raw_status == JobRunStatus.cancelled.value:
        status = "failed"

    stage = run.current_data_type or "queued"
    mode = run.mode or "full"
    progress_percent = run.progress_pct
    if progress_percent is None:
        progress_percent = _assessment_scan_progress_percent(stage, status, scan_counts=scan_counts)

    return {
        "assessment_id": assessment_id,
        "run_uid": run.run_uid,
        "mode": mode,
        "mode_label": _ASSESSMENT_SCAN_MODE_LABELS.get(mode, mode.title()),
        "stage": stage,
        "stage_label": _ASSESSMENT_SCAN_STAGE_LABELS.get(stage, stage.replace("_", " ").title()),
        "status": status,
        "message": run.message,
        "is_alive": is_alive,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "finished_at": run.completed_at.isoformat() if run.completed_at else None,
        "progress_percent": int(progress_percent or 0),
    }


def _set_assessment_scan_job_state(
    assessment_id: int,
    *,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    run_uid: Optional[str] = None
    resolved_stage: Optional[str] = stage
    resolved_status: Optional[str] = status
    resolved_message: Optional[str] = message
    with _ASSESSMENT_SCAN_JOBS_LOCK:
        job = _ASSESSMENT_SCAN_JOBS.get(assessment_id)
        if not job:
            return
        run_uid = job.run_uid
        if stage is not None:
            job.stage = stage
        if status is not None:
            job.status = status
        if message is not None:
            job.message = message
        job.updated_at = datetime.utcnow()
        if job.status in {"completed", "failed"}:
            job.finished_at = job.updated_at
        resolved_stage = job.stage
        resolved_status = job.status
        resolved_message = job.message

    if resolved_stage and resolved_status and resolved_message is not None:
        _update_assessment_scan_run_state(
            assessment_id,
            run_uid,
            stage=resolved_stage,
            status=resolved_status,
            message=resolved_message,
        )


def _update_assessment_postflight_details(
    assessment_id: int,
    sys_class_name: str,
    label: str,
    status: str,
    pulled: int,
    total: int,
    pf_run_uid: Optional[str] = None,
) -> None:
    """Thread-safe update of per-class postflight artifact pull progress.

    Updates both in-memory state (for live polling) and the postflight
    JobRun metadata_json (for persistence across restarts).
    """
    detail_entry = {
        "sys_class_name": sys_class_name,
        "label": label,
        "status": status,
        "pulled": pulled,
        "total": total,
    }

    with _ASSESSMENT_SCAN_JOBS_LOCK:
        job = _ASSESSMENT_SCAN_JOBS.get(assessment_id)
        if job:
            if job.postflight_details is None:
                job.postflight_details = []
            # Update existing entry or append new one
            found = False
            for entry in job.postflight_details:
                if entry["sys_class_name"] == sys_class_name:
                    entry["label"] = label
                    entry["status"] = status
                    entry["pulled"] = pulled
                    entry["total"] = total
                    found = True
                    break
            if not found:
                job.postflight_details.append(dict(detail_entry))
            # Persist to DB via postflight JobRun metadata_json
            details_snapshot = list(job.postflight_details)
        else:
            details_snapshot = [detail_entry]

    if pf_run_uid:
        try:
            with Session(engine) as persist_session:
                pf_run = persist_session.exec(
                    select(JobRun).where(JobRun.run_uid == pf_run_uid)
                ).first()
                if pf_run:
                    existing_meta = {}
                    if pf_run.metadata_json:
                        try:
                            existing_meta = json.loads(pf_run.metadata_json)
                        except Exception:
                            existing_meta = {}
                    existing_meta["postflight_details"] = details_snapshot
                    pf_run.metadata_json = _json_dumps(existing_meta)
                    pf_run.updated_at = datetime.utcnow()
                    persist_session.add(pf_run)
                    persist_session.commit()
        except Exception:
            pass  # non-fatal — in-memory state is primary during active run


def _get_assessment_scan_job_snapshot(
    assessment_id: int,
    *,
    scan_counts: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    in_memory_job: Optional[_AssessmentScanJob] = None
    is_alive = False
    with _ASSESSMENT_SCAN_JOBS_LOCK:
        in_memory_job = _ASSESSMENT_SCAN_JOBS.get(assessment_id)
        if in_memory_job:
            is_alive = bool(in_memory_job.thread and in_memory_job.thread.is_alive())
            if in_memory_job.status == "running" and not is_alive:
                in_memory_job.status = "failed"
                if not in_memory_job.message:
                    in_memory_job.message = "Background scan job exited unexpectedly."
                in_memory_job.updated_at = datetime.utcnow()
                in_memory_job.finished_at = in_memory_job.updated_at

    with Session(engine) as session:
        run = _find_assessment_scan_run(session, assessment_id, active_only=True)
        if not run:
            run = _find_assessment_scan_run(session, assessment_id, active_only=False)
        if run:
            return _serialize_assessment_scan_run(
                run,
                assessment_id=assessment_id,
                is_alive=is_alive,
                scan_counts=scan_counts,
            )

    if not in_memory_job:
        return None

    mode_label = _ASSESSMENT_SCAN_MODE_LABELS.get(in_memory_job.mode, in_memory_job.mode.title())
    stage_label = _ASSESSMENT_SCAN_STAGE_LABELS.get(
        in_memory_job.stage,
        in_memory_job.stage.replace("_", " ").title(),
    )
    return {
        "assessment_id": in_memory_job.assessment_id,
        "mode": in_memory_job.mode,
        "mode_label": mode_label,
        "stage": in_memory_job.stage,
        "stage_label": stage_label,
        "status": in_memory_job.status,
        "message": in_memory_job.message,
        "is_alive": is_alive,
        "started_at": in_memory_job.started_at.isoformat() if in_memory_job.started_at else None,
        "updated_at": in_memory_job.updated_at.isoformat() if in_memory_job.updated_at else None,
        "finished_at": in_memory_job.finished_at.isoformat() if in_memory_job.finished_at else None,
        "progress_percent": _assessment_scan_progress_percent(
            in_memory_job.stage,
            in_memory_job.status,
            scan_counts=scan_counts,
        ),
    }


def _build_recovered_assessment_run_status(
    assessment: Assessment,
    scans: List[Scan],
    status_counts: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    """Build fallback status when in-memory scan job state is unavailable.

    This happens after server restarts because in-process job tracking is reset.
    """
    if assessment.state != AssessmentState.in_progress:
        return None
    if not scans:
        return None

    running_count = int(status_counts.get("running") or 0)
    pending_count = int(status_counts.get("pending") or 0)
    started_at_values = [scan.started_at for scan in scans if scan.started_at]
    has_started_any = bool(started_at_values)

    # Only surface fallback when there is evidence of an active/interrupted run.
    if running_count <= 0 and not (pending_count > 0 and has_started_any):
        return None

    now = datetime.utcnow()
    scan_counts = {**status_counts, "total": len(scans)}

    if running_count > 0:
        stage = "running_scans"
        status = "running"
        message = "Scan workflow is active (recovered status)."
        finished_at = None
    else:
        stage = "failed"
        status = "failed"
        message = "Scan workflow was interrupted (likely server restart). Restart scans to continue."
        finished_at = now

    started_at = min(started_at_values) if started_at_values else now
    stage_label = _ASSESSMENT_SCAN_STAGE_LABELS.get(stage, stage.replace("_", " ").title())

    return {
        "assessment_id": assessment.id,
        "mode": "recovered",
        "mode_label": "Scan Workflow",
        "stage": stage,
        "stage_label": stage_label,
        "status": status,
        "message": message,
        "is_alive": False,
        "started_at": started_at.isoformat(),
        "updated_at": now.isoformat(),
        "finished_at": finished_at.isoformat() if finished_at else None,
        "progress_percent": _assessment_scan_progress_percent(stage, status, scan_counts=scan_counts),
    }


def _assessment_data_sync_summary(session: Session, instance_id: int) -> Dict[str, Any]:
    tracked_types = list(ASSESSMENT_PREFLIGHT_DATA_TYPES)
    pulls = session.exec(
        select(InstanceDataPull)
        .where(InstanceDataPull.instance_id == instance_id)
        .where(InstanceDataPull.data_type.in_(tracked_types))
    ).all()
    pull_map = {pull.data_type: pull for pull in pulls}

    details: List[Dict[str, Any]] = []
    counts = {
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "idle": 0,
    }

    for data_type in tracked_types:
        pull = pull_map.get(data_type)
        model_class = ASSESSMENT_PREFLIGHT_MODEL_MAP.get(data_type)
        local_count = 0
        if model_class:
            local_count = session.exec(
                select(func.count())
                .select_from(model_class)
                .where(model_class.instance_id == instance_id)
            ).one()

        status = "idle"
        if pull and pull.status:
            status = pull.status.value
        if status not in counts:
            status = "idle"
        counts[status] += 1
        details.append(
            {
                "data_type": data_type.value,
                "label": DATA_TYPE_LABELS.get(data_type.value, data_type.value),
                "status": status,
                "records_pulled": pull.records_pulled if pull else 0,
                "expected_total": pull.expected_total if pull else None,
                "local_count": local_count,
                "last_remote_count": pull.last_remote_count if pull else None,
                "last_local_count": pull.last_local_count if pull else None,
                "error_message": pull.error_message if pull else None,
                "started_at": pull.started_at.isoformat() if pull and pull.started_at else None,
                "completed_at": pull.completed_at.isoformat() if pull and pull.completed_at else None,
            }
        )

    required_set = set(ASSESSMENT_PREFLIGHT_REQUIRED_TYPES)
    required_details = [row for row in details if DataPullType(row["data_type"]) in required_set]
    required_remaining = sum(1 for row in required_details if row["status"] != "completed")
    remaining = sum(1 for row in details if row["status"] != "completed")

    return {
        "instance_id": instance_id,
        "total": len(details),
        "remaining": remaining,
        "required_total": len(required_details),
        "required_remaining": required_remaining,
        "counts": counts,
        "details": details,
    }


def _start_assessment_scan_job(assessment_id: int, mode: str) -> bool:
    """Start assessment scan workflow if one is not already running."""
    with Session(engine) as session:
        existing_run = _find_assessment_scan_run(session, assessment_id, active_only=True)
        if existing_run:
            return False

    with _ASSESSMENT_SCAN_JOBS_LOCK:
        existing = _ASSESSMENT_SCAN_JOBS.get(assessment_id)
        if existing and existing.thread and existing.thread.is_alive() and existing.status == "running":
            return False

        run_uid = _create_assessment_scan_run_record(assessment_id, mode)
        if not run_uid:
            return False

        now = datetime.utcnow()
        job = _AssessmentScanJob(
            assessment_id=assessment_id,
            run_uid=run_uid,
            mode=mode,
            stage="queued",
            status="running",
            message="Queued scan workflow.",
            started_at=now,
            updated_at=now,
            finished_at=None,
            thread=None,
        )

        def _runner(job_ref: _AssessmentScanJob) -> None:
            try:
                _run_scans_background(assessment_id, mode=mode)
                _set_assessment_scan_job_state(
                    assessment_id,
                    stage="completed",
                    status="completed",
                    message="Scan workflow completed.",
                )
            except Exception as exc:
                logger.exception("Assessment scan workflow failed for assessment_id=%s mode=%s", assessment_id, mode)
                _set_assessment_scan_job_state(
                    assessment_id,
                    stage="failed",
                    status="failed",
                    message=f"Scan workflow failed: {exc}",
                )
            finally:
                with Session(engine) as session:
                    run = _load_data_pull_run(session, job_ref.run_uid)
                    if run and run.status in {JobRunStatus.queued, JobRunStatus.running}:
                        _update_assessment_scan_run_state(
                            assessment_id,
                            job_ref.run_uid,
                            stage="failed",
                            status="failed",
                            message="Background scan worker exited unexpectedly.",
                        )
                with _ASSESSMENT_SCAN_JOBS_LOCK:
                    current = _ASSESSMENT_SCAN_JOBS.get(assessment_id)
                    if current is job_ref:
                        current.thread = None

        thread = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"assessment_scan_{assessment_id}_{mode}",
            args=(job,),
        )
        job.thread = thread
        _ASSESSMENT_SCAN_JOBS[assessment_id] = job
        thread.start()
        return True


def _mark_remaining_customizations_reviewed(session: Session, assessment_id: int) -> int:
    """Bulk mark pending customized results as reviewed for review-gate bypass."""
    rows = session.exec(
        select(ScanResult)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Scan.assessment_id == assessment_id)
        .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
        .where(ScanResult.review_status != ReviewStatus.reviewed)
    ).all()
    if not rows:
        return 0

    ids: List[int] = []
    for row in rows:
        row.review_status = ReviewStatus.reviewed
        session.add(row)
        if row.id is not None:
            ids.append(int(row.id))
    session.commit()

    if ids:
        customization_rows = session.exec(
            select(Customization).where(Customization.scan_result_id.in_(ids))
        ).all()
        for custom in customization_rows:
            custom.review_status = ReviewStatus.reviewed
            session.add(custom)
        session.commit()
    return len(rows)


def _run_assessment_pipeline_stage(
    assessment_id: int,
    *,
    target_stage: str,
    skip_review: bool = False,
) -> None:
    stage = _pipeline_stage_value(target_stage)
    _set_assessment_pipeline_job_state(
        assessment_id,
        stage=stage,
        status="running",
        message=f"Starting {stage} stage.",
        progress_percent=15,
    )
    _set_assessment_pipeline_stage(assessment_id, stage)

    with Session(engine) as session:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            raise ValueError(f"Assessment not found: {assessment_id}")

        success_message = f"{stage} stage completed."

        if stage == PipelineStage.ai_analysis.value:
            # --- AI Analysis: gather contextual enrichment for customized artifacts ---
            ai_props = load_ai_analysis_properties(session, instance_id=assessment.instance_id)
            instance_id = assessment.instance_id

            # Query customized ScanResults via Scan -> ScanResult join
            customized = session.exec(
                select(ScanResult)
                .join(Scan, ScanResult.scan_id == Scan.id)
                .where(Scan.assessment_id == assessment_id)
                .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
            ).all()

            total = len(customized)
            if total == 0:
                success_message = "AI Analysis stage completed (0 customized artifacts found)."
            else:
                # Determine batch processing
                batch_size = ai_props.batch_size if ai_props.batch_size > 0 else total
                analyzed_count = 0

                for i, sr in enumerate(customized):
                    # Gather context via the contextual lookup service
                    ctx = gather_artifact_context(
                        session, instance_id, sr.id, ai_props.context_enrichment
                    )

                    # Build analysis result dict
                    references = ctx.get("references") or []
                    human_ctx = ctx.get("human_context") or {}
                    artifact_info = ctx.get("artifact") or {}

                    human_context_present = bool(
                        human_ctx.get("observations")
                        or human_ctx.get("disposition")
                        or human_ctx.get("features")
                    )

                    analysis_result = {
                        "artifact_name": artifact_info.get("name") or sr.name,
                        "artifact_table": artifact_info.get("table_name") or sr.table_name,
                        "context_enrichment_mode": ai_props.context_enrichment,
                        "references_found": sum(1 for r in references if r.get("resolved")),
                        "has_local_data": ctx.get("has_local_table_data", False),
                        "human_context_present": human_context_present,
                        "update_sets_count": len(ctx.get("update_sets") or []),
                    }

                    sr.ai_observations = json.dumps(analysis_result, sort_keys=True)
                    session.add(sr)
                    analyzed_count += 1

                    # Commit in batches
                    if analyzed_count % batch_size == 0:
                        session.commit()

                    # Update progress
                    progress = 15 + int((i + 1) / total * 80)
                    _set_assessment_pipeline_job_state(
                        assessment_id,
                        stage=stage,
                        status="running",
                        message=f"Analyzing artifact {i + 1}/{total}...",
                        progress_percent=progress,
                    )

                session.commit()
                success_message = (
                    f"AI Analysis stage completed ({analyzed_count}/{total} customized artifacts analyzed)."
                )

        elif stage == PipelineStage.engines.value:
            result = run_preprocessing_engines_handle({"assessment_id": assessment_id}, session)
            if not result.get("success"):
                errors = result.get("errors") or []
                raise RuntimeError("; ".join(errors) if errors else "Engine run failed.")
            engines_run = len(result.get("engines_run") or [])
            success_message = f"Engines stage completed ({engines_run} engine(s) run)."

        elif stage == PipelineStage.observations.value:
            result = generate_observations_handle({"assessment_id": assessment_id}, session)
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "Observation generation failed.")
            processed = int(result.get("processed_count") or 0)
            total = int(result.get("total_customized") or 0)
            success_message = f"Observations generated for {processed}/{total} customized artifacts."

        elif stage == PipelineStage.grouping.value:
            if skip_review:
                _mark_remaining_customizations_reviewed(session, assessment_id)
            result = seed_feature_groups_handle({"assessment_id": assessment_id}, session)
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "Feature grouping failed.")
            features_created = int(result.get("features_created") or 0)
            grouped_count = int(result.get("grouped_count") or 0)
            success_message = (
                f"Grouping stage completed ({grouped_count} customized results grouped; "
                f"{features_created} feature(s) created)."
            )

        elif stage == PipelineStage.recommendations.value:
            pass_count = 0
            response = run_feature_reasoning_handle(
                {"assessment_id": assessment_id, "pass_type": "auto"},
                session,
            )
            pass_count += 1
            while response.get("should_continue"):
                max_iterations = int(response.get("max_iterations") or 3)
                if pass_count >= max_iterations:
                    break
                response = run_feature_reasoning_handle(
                    {
                        "assessment_id": assessment_id,
                        "run_id": response.get("run_id"),
                        "pass_type": "auto",
                    },
                    session,
                )
                pass_count += 1
            if not response.get("success", True):
                raise RuntimeError(response.get("error") or "Feature reasoning failed.")
            success_message = (
                f"Recommendation stage verification completed in {pass_count} pass(es); "
                f"converged={bool(response.get('converged'))}."
            )

        elif stage == PipelineStage.review.value:
            gate = _assessment_review_gate_summary(session, assessment_id)
            if not gate.get("all_reviewed") and not skip_review:
                raise RuntimeError(
                    "Review gate not satisfied. Mark all customized artifacts reviewed or pass skip_review=true."
                )
            if skip_review:
                reviewed_count = _mark_remaining_customizations_reviewed(session, assessment_id)
                success_message = f"Review gate bypassed; marked {reviewed_count} result(s) as reviewed."
            else:
                success_message = "Review gate satisfied."

        next_stage = _PIPELINE_STAGE_AUTONEXT.get(stage)
        if next_stage:
            _set_assessment_pipeline_stage(assessment_id, next_stage, session=session)

    _set_assessment_pipeline_job_state(
        assessment_id,
        stage=stage,
        status="completed",
        message=success_message,
        progress_percent=100,
    )


def _start_assessment_pipeline_job(
    assessment_id: int,
    *,
    target_stage: str,
    skip_review: bool = False,
) -> bool:
    """Start a post-scan pipeline stage if no active pipeline stage is running."""
    normalized_target = _pipeline_stage_value(target_stage)
    with Session(engine) as session:
        existing_run = _find_assessment_pipeline_run(session, assessment_id, active_only=True)
        if existing_run:
            return False

    with _ASSESSMENT_PIPELINE_JOBS_LOCK:
        existing = _ASSESSMENT_PIPELINE_JOBS.get(assessment_id)
        if existing and existing.thread and existing.thread.is_alive() and existing.status == "running":
            return False

        run_uid = _create_assessment_pipeline_run_record(assessment_id, normalized_target)
        if not run_uid:
            return False

        now = datetime.utcnow()
        job = _AssessmentPipelineJob(
            assessment_id=assessment_id,
            run_uid=run_uid,
            target_stage=normalized_target,
            stage=normalized_target,
            status="running",
            message=f"Queued pipeline stage: {normalized_target}",
            progress_percent=5,
            started_at=now,
            updated_at=now,
            finished_at=None,
            thread=None,
        )

        def _runner(job_ref: _AssessmentPipelineJob) -> None:
            try:
                _run_assessment_pipeline_stage(
                    assessment_id,
                    target_stage=normalized_target,
                    skip_review=skip_review,
                )
            except Exception as exc:
                logger.exception(
                    "Assessment pipeline stage failed for assessment_id=%s stage=%s",
                    assessment_id,
                    normalized_target,
                )
                _set_assessment_pipeline_job_state(
                    assessment_id,
                    stage=normalized_target,
                    status="failed",
                    message=f"Pipeline stage failed: {exc}",
                    progress_percent=100,
                )
            finally:
                with Session(engine) as session:
                    run = _load_data_pull_run(session, job_ref.run_uid)
                    if run and run.status in {JobRunStatus.queued, JobRunStatus.running}:
                        _update_assessment_pipeline_run_state(
                            assessment_id,
                            job_ref.run_uid,
                            stage=normalized_target,
                            status="failed",
                            message="Background pipeline worker exited unexpectedly.",
                            progress_percent=100,
                        )
                with _ASSESSMENT_PIPELINE_JOBS_LOCK:
                    current = _ASSESSMENT_PIPELINE_JOBS.get(assessment_id)
                    if current is job_ref:
                        current.thread = None

        thread = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"assessment_pipeline_{assessment_id}_{normalized_target}",
            args=(job,),
        )
        job.thread = thread
        _ASSESSMENT_PIPELINE_JOBS[assessment_id] = job
        thread.start()
        return True


def _cleanup_legacy_instance_data_pull_rows() -> None:
    """Delete InstanceDataPull rows with unknown data_type values.

    This prevents API endpoints (and SQLAlchemy enum coercion) from crashing when
    we rename/remove DataPullType enum values across app versions.
    """
    valid_values = [dt.value for dt in DataPullType]
    if not valid_values:
        return

    placeholders = ", ".join([f":v{i}" for i in range(len(valid_values))])
    params = {f"v{i}": value for i, value in enumerate(valid_values)}
    stmt = text(
        f"DELETE FROM instance_data_pull WHERE data_type NOT IN ({placeholders})"
    )
    with engine.connect() as conn:
        try:
            conn.execute(stmt, params)
            conn.commit()
        except Exception:
            # Best-effort cleanup; don't block startup if the table isn't present yet.
            pass


def _get_active_data_pull_job(instance_id: int) -> Optional[_DataPullJob]:
    """Return active job for an instance, cleaning up finished jobs."""
    with _DATA_PULL_JOBS_LOCK:
        job = _DATA_PULL_JOBS.get(instance_id)
        if not job or not job.thread:
            _DATA_PULL_JOBS.pop(instance_id, None)
            return None
        if job.thread.is_alive():
            return job
        _DATA_PULL_JOBS.pop(instance_id, None)
        return None


def _start_data_pull_job(instance_id: int, data_types: List[str], mode: str, source_context: str = "preflight") -> bool:
    """
    Start a data pull job for an instance if one isn't already running.

    Returns:
        True if a new job thread was started, False if a job is already running.
    """
    with _DATA_PULL_JOBS_LOCK:
        existing = _DATA_PULL_JOBS.get(instance_id)
        if existing and existing.thread and existing.thread.is_alive():
            return False

        run_uid = _create_data_pull_run_record(instance_id, data_types, mode, source_context=source_context)
        cancel_event = threading.Event()
        job = _DataPullJob(
            instance_id=instance_id,
            run_uid=run_uid,
            data_types=list(data_types),
            mode=mode,
            cancel_event=cancel_event,
            thread=None,
            started_at=datetime.utcnow(),
        )

        def _runner(job_ref: _DataPullJob) -> None:
            try:
                _run_data_pulls_background(
                    instance_id,
                    data_types,
                    mode,
                    cancel_event=cancel_event,
                    run_uid=job_ref.run_uid,
                    source_context=source_context,
                )
            finally:
                with Session(engine) as session:
                    run = _load_data_pull_run(session, job_ref.run_uid)
                    if run and run.status in {JobRunStatus.queued, JobRunStatus.running}:
                        _mark_data_pull_run_finished(
                            session,
                            job_ref.run_uid,
                            status=JobRunStatus.failed,
                            queue_completed=run.queue_completed or 0,
                            queue_total=run.queue_total or len(job_ref.data_types),
                            message="Background pull worker exited unexpectedly.",
                            error_message="Background pull worker exited unexpectedly.",
                        )
                with _DATA_PULL_JOBS_LOCK:
                    if _DATA_PULL_JOBS.get(instance_id) is job_ref:
                        _DATA_PULL_JOBS.pop(instance_id, None)

        thread = threading.Thread(
            target=_runner,
            args=(job,),
            daemon=True,
            name=f"data_pull_instance_{instance_id}",
        )
        job.thread = thread
        _DATA_PULL_JOBS[instance_id] = job
        thread.start()
        return True


def _get_or_create_vh_event(instance_id: int) -> threading.Event:
    """Get or create a VH completion event for an instance."""
    with _VH_EVENTS_LOCK:
        if instance_id not in _VH_EVENTS:
            _VH_EVENTS[instance_id] = threading.Event()
        return _VH_EVENTS[instance_id]


def _clear_vh_event(instance_id: int) -> None:
    """Remove the VH event for an instance after consumption."""
    with _VH_EVENTS_LOCK:
        _VH_EVENTS.pop(instance_id, None)


def _is_vh_pull_active(instance_id: int) -> bool:
    """Check if a VH pull is currently running for this instance."""
    with Session(engine) as session:
        pull = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type == DataPullType.version_history)
            .where(InstanceDataPull.status == DataPullStatus.running)
        ).first()
        return pull is not None


def _start_proactive_vh_pull(instance_id: int) -> bool:
    """Start a proactive VH pull in a background thread.

    Pulls ALL version history states (no filter) so classification has
    complete data.  Creates a threading.Event that Stage 5 of the
    assessment workflow can wait on.

    Returns True if a new pull was started, False if one is already
    running or the instance doesn't exist.
    """
    if _is_vh_pull_active(instance_id):
        # Already running — just ensure an event exists for waiters
        _get_or_create_vh_event(instance_id)
        return False

    event = _get_or_create_vh_event(instance_id)
    event.clear()  # Reset for this pull cycle

    def _vh_pull_worker() -> None:
        try:
            with Session(engine) as bg_session:
                instance = bg_session.get(Instance, instance_id)
                if not instance:
                    return
                password = decrypt_password(instance.password_encrypted)
                client = ServiceNowClient(
                    instance.url, instance.username, password,
                    instance_id=instance.id,
                )
                # Phase 1: current-only (fast, unblocks classification)
                execute_data_pull(
                    session=bg_session,
                    instance=instance,
                    client=client,
                    data_type=DataPullType.version_history,
                    mode=DataPullMode.smart.value,
                    version_state_filter="current",
                )
                # Signal that current records are ready — assessment
                # workflow can proceed with classification.
                event.set()
                # Phase 2: backfill remaining states (all, no filter)
                execute_data_pull(
                    session=bg_session,
                    instance=instance,
                    client=client,
                    data_type=DataPullType.version_history,
                    mode=DataPullMode.smart.value,
                )
        except Exception as exc:
            logger.warning("Proactive VH pull failed for instance %s: %s", instance_id, exc)
        finally:
            event.set()  # Ensure event fires even on failure

    thread = threading.Thread(
        target=_vh_pull_worker,
        daemon=True,
        name=f"proactive_vh_{instance_id}",
    )
    thread.start()
    logger.info("Started proactive VH pull for instance %s", instance_id)
    return True


DATA_TYPE_LABELS = get_data_type_labels()

ASSESSMENT_PREFLIGHT_DATA_TYPES: List[DataPullType] = get_assessment_preflight_data_types()

ASSESSMENT_PREFLIGHT_REQUIRED_TYPES: List[DataPullType] = [
    DataPullType.metadata_customization,
    DataPullType.app_file_types,
    DataPullType.version_history,
    DataPullType.customer_update_xml,
    DataPullType.update_sets,
]

ASSESSMENT_PREFLIGHT_MODEL_MAP = get_assessment_preflight_model_map()


def _get_assessment_preflight_stale_minutes(default: int = 10) -> int:
    raw = (os.getenv("TECH_ASSESSMENT_PREFLIGHT_STALE_MINUTES") or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


ASSESSMENT_PREFLIGHT_STALE_MINUTES = _get_assessment_preflight_stale_minutes()


def _get_assessment_preflight_wait_seconds(default: int = 900) -> int:
    raw = (os.getenv("TECH_ASSESSMENT_PREFLIGHT_WAIT_SECONDS") or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


ASSESSMENT_PREFLIGHT_WAIT_SECONDS = _get_assessment_preflight_wait_seconds()

DATA_PULL_STORAGE_TABLE_MAP: Dict[DataPullType, str] = get_data_pull_storage_tables()


def normalize_instance_url(url: str) -> str:
    """
    Normalize a ServiceNow instance URL to just the base URL.
    Handles cases like:
    - dev12345.service-now.com -> https://dev12345.service-now.com
    - https://dev12345.service-now.com/login.do -> https://dev12345.service-now.com
    - https://dev12345.service-now.com/now/nav/ui/home -> https://dev12345.service-now.com
    """
    url = url.strip()

    # Add scheme if missing
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    # Parse and extract just scheme + netloc (host)
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    return base_url


def _safe_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}


def _parse_csv_ints(value: Optional[str]) -> List[int]:
    if not value:
        return []
    result: List[int] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            result.append(int(chunk))
    return result


def _parse_csv_strings(value: Optional[str]) -> List[str]:
    if not value:
        return []
    values: List[str] = []
    for chunk in value.split(","):
        cleaned = chunk.strip()
        if cleaned:
            values.append(cleaned)
    return values


def _parse_json_string_list(value: Optional[str]) -> List[str]:
    parsed = _safe_json(value, [])
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return []


_DISPLAY_LABEL_ACRONYMS = {
    "acl",
    "api",
    "ci",
    "cmn",
    "cmdb",
    "db",
    "id",
    "kmf",
    "rest",
    "sn",
    "ui",
    "url",
    "xml",
}


def _humanize_technical_name(value: Optional[str]) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""

    normalized = cleaned.replace("_", " ").replace(".", " ").replace("-", " ")
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return cleaned

    parts: List[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in _DISPLAY_LABEL_ACRONYMS:
            parts.append(lowered.upper())
        else:
            parts.append(token[:1].upper() + token[1:].lower())
    return " ".join(parts)


def _resolve_app_file_display_label(
    *,
    explicit_label: Optional[str] = None,
    record_name: Optional[str] = None,
    sys_class_name: Optional[str] = None,
) -> str:
    normalized_sys_class = str(sys_class_name or "").strip()

    def _normalized_candidate(candidate: Optional[str]) -> str:
        cleaned = str(candidate or "").strip()
        if not cleaned:
            return ""
        if cleaned == normalized_sys_class or ("_" in cleaned and " " not in cleaned):
            humanized = _humanize_technical_name(cleaned)
            if humanized:
                return humanized
        return cleaned

    for candidate in (explicit_label, record_name):
        cleaned = _normalized_candidate(candidate)
        if cleaned:
            return cleaned
    return _humanize_technical_name(normalized_sys_class) or normalized_sys_class


def _ordered_unique_strings(values: List[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _assessment_selected_class_names(assessments: List[Assessment]) -> List[str]:
    selected: List[str] = []
    seen = set()
    for assessment in assessments:
        for class_name in _parse_json_string_list(assessment.app_file_classes_json):
            if class_name in seen:
                continue
            seen.add(class_name)
            selected.append(class_name)
    return selected


def _instance_app_file_type_class_names(session: Session, instance_ids: List[int]) -> set:
    if not instance_ids:
        return set()
    rows = session.exec(
        select(InstanceAppFileType.sys_class_name)
        .where(InstanceAppFileType.instance_id.in_(instance_ids))
        .where(InstanceAppFileType.sys_class_name.is_not(None))
    ).all()
    return {str(value).strip() for value in rows if str(value or "").strip()}


def _results_option_app_file_classes(
    session: Session,
    *,
    instance_id: Optional[int] = None,
    assessment_ids: Optional[List[int]] = None,
    scan_ids: Optional[List[int]] = None,
    customized_only: bool = True,
    customization_type: str = "all",
) -> List[str]:
    selected_assessment_ids = list(assessment_ids or [])
    selected_scan_ids = list(scan_ids or [])

    class_conditions = _scan_result_conditions(
        instance_id=instance_id,
        assessment_ids=selected_assessment_ids,
        scan_ids=selected_scan_ids,
        customized_only=customized_only,
        customization_type=customization_type,
    )
    class_stmt = (
        select(ScanResult.table_name)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .join(Assessment, Scan.assessment_id == Assessment.id)
    )
    if class_conditions:
        class_stmt = class_stmt.where(*class_conditions)
    observed_rows = session.exec(class_stmt).all()
    observed_classes = sorted({str(value).strip() for value in observed_rows if str(value or "").strip()})

    ordered_assessment_ids: List[int] = []
    seen_assessment_ids = set()
    for assessment_id in selected_assessment_ids:
        if assessment_id in seen_assessment_ids:
            continue
        seen_assessment_ids.add(assessment_id)
        ordered_assessment_ids.append(assessment_id)

    if selected_scan_ids:
        scan_assessment_rows = session.exec(
            select(Scan.assessment_id).where(Scan.id.in_(selected_scan_ids))
        ).all()
        for assessment_id in scan_assessment_rows:
            if not assessment_id or assessment_id in seen_assessment_ids:
                continue
            seen_assessment_ids.add(assessment_id)
            ordered_assessment_ids.append(assessment_id)

    scoped_assessments: List[Assessment] = []
    if ordered_assessment_ids:
        assessment_rows = session.exec(
            select(Assessment).where(Assessment.id.in_(ordered_assessment_ids))
        ).all()
        assessments_by_id = {assessment.id: assessment for assessment in assessment_rows}
        scoped_assessments = [
            assessments_by_id[assessment_id]
            for assessment_id in ordered_assessment_ids
            if assessment_id in assessments_by_id
        ]
    elif instance_id is not None:
        scoped_assessments = session.exec(
            select(Assessment)
            .where(Assessment.instance_id == instance_id)
            .order_by(desc(Assessment.created_at), desc(Assessment.id))
        ).all()

    selected_classes = _assessment_selected_class_names(scoped_assessments)

    scoped_instance_ids: List[int] = []
    if instance_id is not None:
        scoped_instance_ids.append(instance_id)
    for assessment in scoped_assessments:
        if assessment.instance_id not in scoped_instance_ids:
            scoped_instance_ids.append(assessment.instance_id)

    catalog_classes = _instance_app_file_type_class_names(session, scoped_instance_ids)

    if selected_classes:
        selected_in_catalog = [
            class_name
            for class_name in selected_classes
            if (not catalog_classes) or (class_name in catalog_classes)
        ]
        if selected_in_catalog:
            return _ordered_unique_strings(selected_in_catalog)

    if catalog_classes:
        return sorted(class_name for class_name in observed_classes if class_name in catalog_classes)

    return observed_classes


def _scan_option_app_file_class(scan: Scan) -> Optional[str]:
    query_params = _safe_json(scan.query_params_json, {})
    if isinstance(query_params, dict):
        class_name = str(query_params.get("app_file_class") or "").strip()
        if class_name:
            return class_name
    if scan.scan_type == ScanType.update_xml:
        return "sys_update_xml"
    return None


def _assessment_file_class_options(session: Session, instance_id: Optional[int]) -> List[Dict[str, Any]]:
    """
    Return class options for assessment forms.

    For an instance, this is driven by instance_app_file_type + is_available_for_assessment.
    Seeded AppFileClass rows are only used when no instance is selected.
    """
    seeded_rows = session.exec(
        select(AppFileClass).where(AppFileClass.is_active == True).order_by(AppFileClass.display_order.asc())
    ).all()
    seeded_by_class = {row.sys_class_name: row for row in seeded_rows}

    if instance_id is not None:
        cached_rows = session.exec(
            select(InstanceAppFileType)
            .where(InstanceAppFileType.instance_id == instance_id)
            .where(InstanceAppFileType.sys_class_name.is_not(None))
            .where(InstanceAppFileType.is_available_for_assessment == True)
            .order_by(InstanceAppFileType.priority.asc(), InstanceAppFileType.sys_class_name.asc())
        ).all()
        options: List[Dict[str, Any]] = []
        seen = set()
        for cached in cached_rows:
            class_name = (cached.sys_class_name or "").strip()
            if not class_name or class_name in seen:
                continue
            seen.add(class_name)
            seeded = seeded_by_class.get(class_name)
            options.append({
                "sys_class_name": class_name,
                "label": (
                    seeded.label
                    if seeded and str(seeded.label or "").strip()
                    else _resolve_app_file_display_label(
                        explicit_label=cached.label,
                        record_name=cached.name,
                        sys_class_name=class_name,
                    )
                ),
                "is_important": bool(seeded.is_important) if seeded else False,
                "is_default_for_assessment": bool(cached.is_default_for_assessment),
                "display_order": seeded.display_order if seeded else (cached.priority or 9999),
            })
        return options

    return [
        {
            "sys_class_name": row.sys_class_name,
            "label": _resolve_app_file_display_label(
                explicit_label=row.label,
                record_name=row.sys_class_name,
                sys_class_name=row.sys_class_name,
            ),
            "is_important": bool(row.is_important),
            "is_default_for_assessment": bool(row.is_important),
            "display_order": row.display_order,
        }
        for row in seeded_rows
    ]


def _default_selected_file_classes(session: Session, instance_id: Optional[int]) -> List[str]:
    options = _assessment_file_class_options(session, instance_id)
    selected = [item["sys_class_name"] for item in options if bool(item.get("is_default_for_assessment"))]
    if selected:
        return selected
    return [item["sys_class_name"] for item in options if bool(item.get("is_important"))]


def _preserve_unavailable_selected_file_classes(
    *,
    submitted_class_names: List[str],
    existing_class_names: List[str],
    available_options: List[Dict[str, Any]],
) -> List[str]:
    available_names = {str(item.get("sys_class_name") or "").strip() for item in available_options}
    preserved_unavailable = [name for name in existing_class_names if name and name not in available_names]
    merged = list(submitted_class_names)
    for class_name in preserved_unavailable:
        if class_name not in merged:
            merged.append(class_name)
    return merged


def _normalize_customization_type(value: Optional[str]) -> str:
    normalized = (value or "all").strip().lower()
    if normalized in {"modified_ootb", "net_new_customer", "all"}:
        return normalized
    return "all"


def _scan_result_conditions(
    *,
    instance_id: Optional[int] = None,
    assessment_ids: Optional[List[int]] = None,
    scan_ids: Optional[List[int]] = None,
    customized_only: bool = True,
    customization_type: str = "all",
    table_names: Optional[List[str]] = None,
) -> List[Any]:
    conditions: List[Any] = []

    if instance_id:
        conditions.append(Assessment.instance_id == instance_id)

    if assessment_ids:
        conditions.append(Assessment.id.in_(assessment_ids))

    if scan_ids:
        conditions.append(Scan.id.in_(scan_ids))

    resolved_customization_type = _normalize_customization_type(customization_type)
    if customized_only:
        if resolved_customization_type == "all":
            conditions.append(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
        else:
            conditions.append(ScanResult.origin_type == resolved_customization_type)
    elif resolved_customization_type != "all":
        conditions.append(ScanResult.origin_type == resolved_customization_type)

    if table_names:
        conditions.append(ScanResult.table_name.in_(table_names))

    return conditions


def _scan_results_base_stmt() -> Any:
    return (
        select(ScanResult, Scan, Assessment, Instance)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .join(Assessment, Scan.assessment_id == Assessment.id)
        .join(Instance, Assessment.instance_id == Instance.id)
    )


def _scan_results_count_stmt() -> Any:
    return (
        select(func.count())
        .select_from(ScanResult)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .join(Assessment, Scan.assessment_id == Assessment.id)
    )


def _build_scan_result_payload(
    result: ScanResult,
    scan: Scan,
    assessment: Assessment,
    instance: Instance,
) -> Dict[str, Any]:
    origin_value = result.origin_type.value if result.origin_type else None
    is_customized = origin_value in _CUSTOMIZED_ORIGIN_VALUES
    return {
        "id": result.id,
        "name": result.name,
        "sys_id": result.sys_id,
        "table_name": result.table_name,
        "origin_type": origin_value,
        "is_customized": is_customized,
        "customization_classification": origin_value if is_customized else None,
        "review_status": result.review_status.value if result.review_status else None,
        "disposition": result.disposition.value if result.disposition else None,
        "severity": result.severity.value if result.severity else None,
        "category": result.category.value if result.category else None,
        "finding_title": result.finding_title,
        "sys_updated_on": result.sys_updated_on.isoformat() if result.sys_updated_on else None,
        "scan": {
            "id": scan.id,
            "name": scan.name,
            "scan_type": scan.scan_type.value if scan.scan_type else None,
            "status": scan.status.value if scan.status else None,
        },
        "assessment": {
            "id": assessment.id,
            "number": assessment.number,
            "name": assessment.name,
            "state": assessment.state.value if assessment.state else None,
        },
        "instance": {
            "id": instance.id,
            "name": instance.name,
            "company": instance.company,
        },
    }


def _resolve_head_owner_label(result: ScanResult, instance: Optional[Instance]) -> str:
    if result.origin_type == OriginType.modified_ootb:
        return "SN"
    if result.origin_type == OriginType.net_new_customer:
        if instance and instance.company and instance.company.strip():
            return instance.company.strip()
        if instance and instance.name and instance.name.strip():
            return instance.name.strip()
        return "Customer"
    if result.head_owner == HeadOwner.store_upgrade:
        return "SN"
    if result.head_owner:
        return result.head_owner.value
    return "Unknown"


def _query_scan_results_payload(
    session: Session,
    *,
    instance_id: Optional[int] = None,
    assessment_ids: Optional[List[int]] = None,
    scan_ids: Optional[List[int]] = None,
    customized_only: bool = True,
    customization_type: str = "all",
    table_names: Optional[List[str]] = None,
    limit: int = 500,
    offset: int = 0,
) -> Dict[str, Any]:
    conditions = _scan_result_conditions(
        instance_id=instance_id,
        assessment_ids=assessment_ids,
        scan_ids=scan_ids,
        customized_only=customized_only,
        customization_type=customization_type,
        table_names=table_names,
    )

    count_stmt = _scan_results_count_stmt()
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(session.exec(count_stmt).one() or 0)

    data_stmt = _scan_results_base_stmt()
    if conditions:
        data_stmt = data_stmt.where(*conditions)
    rows = session.exec(
        data_stmt
        .order_by(desc(ScanResult.sys_updated_on), desc(ScanResult.id))
        .offset(offset)
        .limit(limit)
    ).all()

    results: List[Dict[str, Any]] = []
    for result, scan, assessment, instance in rows:
        results.append(_build_scan_result_payload(result, scan, assessment, instance))

    return {
        "total": total,
        "count": len(results),
        "offset": offset,
        "limit": limit,
        "results": results,
    }


def _origin_type_value(result: ScanResult) -> Optional[str]:
    if result.origin_type is None:
        return None
    if hasattr(result.origin_type, "value"):
        return result.origin_type.value
    return str(result.origin_type)


def _is_customized_result(result: ScanResult) -> bool:
    return (_origin_type_value(result) or "") in _CUSTOMIZED_ORIGIN_VALUES


def _build_compact_result_payload(result: ScanResult) -> Dict[str, Any]:
    origin_value = _origin_type_value(result)
    return {
        "id": result.id,
        "scan_id": result.scan_id,
        "sys_id": result.sys_id,
        "name": result.name,
        "table_name": result.table_name,
        "origin_type": origin_value,
        "is_customized": origin_value in _CUSTOMIZED_ORIGIN_VALUES,
        "sys_updated_on": result.sys_updated_on.isoformat() if result.sys_updated_on else None,
    }


def _parse_result_id_list(value: Optional[str]) -> List[int]:
    parsed = _safe_json(value, [])
    result_ids: List[int] = []
    if not isinstance(parsed, list):
        return result_ids
    for item in parsed:
        candidate = None
        if isinstance(item, dict):
            candidate = item.get("scan_result_id") or item.get("result_id") or item.get("id")
        else:
            candidate = item
        try:
            if candidate is not None:
                result_ids.append(int(candidate))
        except (TypeError, ValueError):
            continue
    return result_ids


def _scoped_scan_results(
    session: Session,
    *,
    assessment_id: int,
    scan_id: Optional[int] = None,
) -> List[ScanResult]:
    stmt = (
        select(ScanResult)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Scan.assessment_id == assessment_id)
    )
    if scan_id is not None:
        stmt = stmt.where(Scan.id == scan_id)
    return session.exec(stmt).all()


def _safe_float(value: Any, default: float = 1.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


_GROUPING_SIGNAL_KEYS = [
    "update_set_overlap",
    "update_set_artifact_link",
    "code_reference",
    "structural_relationship",
    "temporal_cluster",
    "naming_cluster",
    "table_colocation",
]


def _build_grouping_signals_payload(
    session: Session,
    *,
    assessment_id: int,
    scan_id: Optional[int] = None,
) -> Dict[str, Any]:
    scoped_results = _scoped_scan_results(session, assessment_id=assessment_id, scan_id=scan_id)
    scoped_result_ids = {row.id for row in scoped_results if row.id is not None}

    update_set_name_by_id: Dict[int, str] = {}
    # Requery update-set names only for rows related to this assessment to keep payload scoped.
    assessment_update_set_ids = {
        row
        for row in session.exec(
            select(UpdateSetArtifactLink.update_set_id)
            .where(UpdateSetArtifactLink.assessment_id == assessment_id)
        ).all()
        if row is not None
    }
    assessment_update_set_ids.update(
        row
        for row in session.exec(
            select(UpdateSetOverlap.update_set_a_id)
            .where(UpdateSetOverlap.assessment_id == assessment_id)
        ).all()
        if row is not None
    )
    assessment_update_set_ids.update(
        row
        for row in session.exec(
            select(UpdateSetOverlap.update_set_b_id)
            .where(UpdateSetOverlap.assessment_id == assessment_id)
        ).all()
        if row is not None
    )
    if assessment_update_set_ids:
        for update_set in session.exec(
            select(UpdateSet).where(UpdateSet.id.in_(list(assessment_update_set_ids)))
        ).all():
            if update_set.id is not None:
                update_set_name_by_id[update_set.id] = update_set.name

    signal_counts: Dict[str, int] = {key: 0 for key in _GROUPING_SIGNAL_KEYS}
    signals: List[Dict[str, Any]] = []

    def _add_signal(
        *,
        signal_type: str,
        signal_id: int,
        label: str,
        member_ids: List[int],
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        evidence: Optional[Any] = None,
        fallback_member_count: int = 0,
    ) -> None:
        scoped_member_ids = sorted({mid for mid in member_ids if mid in scoped_result_ids})
        if scan_id is not None and not scoped_member_ids:
            return

        member_count = len(scoped_member_ids)
        if member_count == 0 and scan_id is None and fallback_member_count > 0:
            member_count = int(fallback_member_count)
        if member_count <= 0:
            return

        signal_counts[signal_type] = signal_counts.get(signal_type, 0) + 1
        signals.append(
            {
                "type": signal_type,
                "id": signal_id,
                "label": label,
                "member_count": member_count,
                "confidence": _safe_float(confidence, default=1.0),
                "links": {
                    "member_result_ids": scoped_member_ids,
                    "member_result_urls": [f"/results/{rid}" for rid in scoped_member_ids],
                },
                "metadata": metadata or {},
                "evidence": evidence if evidence is not None else {},
            }
        )

    for row in session.exec(
        select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == assessment_id)
    ).all():
        member_ids = _parse_result_id_list(row.shared_records_json)
        name_a = update_set_name_by_id.get(row.update_set_a_id, f"Update Set {row.update_set_a_id}")
        name_b = update_set_name_by_id.get(row.update_set_b_id, f"Update Set {row.update_set_b_id}")
        _add_signal(
            signal_type="update_set_overlap",
            signal_id=row.id,
            label=f"{name_a} <> {name_b} ({row.signal_type})",
            member_ids=member_ids,
            confidence=_safe_float(row.overlap_score, default=1.0),
            metadata={
                "update_set_a_id": row.update_set_a_id,
                "update_set_b_id": row.update_set_b_id,
                "update_set_a_name": name_a,
                "update_set_b_name": name_b,
                "signal_type": row.signal_type,
                "shared_record_count": row.shared_record_count,
            },
            evidence=_safe_json(row.evidence_json, {}),
            fallback_member_count=int(row.shared_record_count or 0),
        )

    link_stmt = (
        select(UpdateSetArtifactLink, ScanResult)
        .join(ScanResult, UpdateSetArtifactLink.scan_result_id == ScanResult.id)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(UpdateSetArtifactLink.assessment_id == assessment_id)
    )
    if scan_id is not None:
        link_stmt = link_stmt.where(Scan.id == scan_id)
    for link, result in session.exec(link_stmt).all():
        update_set_name = update_set_name_by_id.get(link.update_set_id, f"Update Set {link.update_set_id}")
        _add_signal(
            signal_type="update_set_artifact_link",
            signal_id=link.id,
            label=f"{update_set_name} -> {result.name} ({link.link_source})",
            member_ids=[result.id] if result.id is not None else [],
            confidence=_safe_float(link.confidence, default=1.0),
            metadata={
                "update_set_id": link.update_set_id,
                "update_set_name": update_set_name,
                "scan_result_id": result.id,
                "link_source": link.link_source,
                "is_current": bool(link.is_current),
            },
            evidence=_safe_json(link.evidence_json, {}),
            fallback_member_count=1,
        )

    code_stmt = (
        select(CodeReference)
        .where(CodeReference.assessment_id == assessment_id)
    )
    for ref in session.exec(code_stmt).all():
        member_ids = [ref.source_scan_result_id]
        if ref.target_scan_result_id:
            member_ids.append(ref.target_scan_result_id)
        _add_signal(
            signal_type="code_reference",
            signal_id=ref.id,
            label=f"{ref.source_name} -> {ref.target_identifier} ({ref.reference_type})",
            member_ids=member_ids,
            confidence=_safe_float(ref.confidence, default=1.0),
            metadata={
                "source_scan_result_id": ref.source_scan_result_id,
                "target_scan_result_id": ref.target_scan_result_id,
                "source_table": ref.source_table,
                "source_field": ref.source_field,
                "reference_type": ref.reference_type,
                "line_number": ref.line_number,
            },
            evidence={"code_snippet": ref.code_snippet} if ref.code_snippet else {},
        )

    structural_stmt = (
        select(StructuralRelationship)
        .where(StructuralRelationship.assessment_id == assessment_id)
    )
    for rel in session.exec(structural_stmt).all():
        _add_signal(
            signal_type="structural_relationship",
            signal_id=rel.id,
            label=f"{rel.relationship_type}: {rel.parent_scan_result_id} -> {rel.child_scan_result_id}",
            member_ids=[rel.parent_scan_result_id, rel.child_scan_result_id],
            confidence=_safe_float(rel.confidence, default=1.0),
            metadata={
                "relationship_type": rel.relationship_type,
                "parent_scan_result_id": rel.parent_scan_result_id,
                "child_scan_result_id": rel.child_scan_result_id,
                "parent_field": rel.parent_field,
            },
        )

    for cluster in session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == assessment_id)
    ).all():
        member_ids = _parse_result_id_list(cluster.record_ids_json)
        _add_signal(
            signal_type="temporal_cluster",
            signal_id=cluster.id,
            label=f"{cluster.developer} ({cluster.cluster_start.isoformat()} - {cluster.cluster_end.isoformat()})",
            member_ids=member_ids,
            confidence=1.0,
            metadata={
                "developer": cluster.developer,
                "cluster_start": cluster.cluster_start.isoformat() if cluster.cluster_start else None,
                "cluster_end": cluster.cluster_end.isoformat() if cluster.cluster_end else None,
                "avg_gap_minutes": cluster.avg_gap_minutes,
            },
            fallback_member_count=int(cluster.record_count or 0),
        )

    for cluster in session.exec(
        select(NamingCluster).where(NamingCluster.assessment_id == assessment_id)
    ).all():
        member_ids = _parse_result_id_list(cluster.member_ids_json)
        _add_signal(
            signal_type="naming_cluster",
            signal_id=cluster.id,
            label=f"{cluster.cluster_label} ({cluster.pattern_type})",
            member_ids=member_ids,
            confidence=_safe_float(cluster.confidence, default=1.0),
            metadata={
                "cluster_label": cluster.cluster_label,
                "pattern_type": cluster.pattern_type,
            },
            fallback_member_count=int(cluster.member_count or 0),
        )

    for summary in session.exec(
        select(TableColocationSummary).where(TableColocationSummary.assessment_id == assessment_id)
    ).all():
        member_ids = _parse_result_id_list(summary.record_ids_json)
        _add_signal(
            signal_type="table_colocation",
            signal_id=summary.id,
            label=f"{summary.target_table} ({summary.record_count} artifacts)",
            member_ids=member_ids,
            confidence=1.0,
            metadata={
                "target_table": summary.target_table,
                "artifact_types": _safe_json(summary.artifact_types_json, []),
                "developers": _safe_json(summary.developers_json, []),
            },
            fallback_member_count=int(summary.record_count or 0),
        )

    signals.sort(
        key=lambda row: (
            row.get("type") or "",
            -(int(row.get("member_count") or 0)),
            -(float(row.get("confidence") or 0.0)),
            int(row.get("id") or 0),
        )
    )

    return {
        "assessment_id": assessment_id,
        "scan_id": scan_id,
        "signal_counts": signal_counts,
        "signals": signals,
        "total_signals": len(signals),
        "generated_at": datetime.utcnow().isoformat(),
    }


def _build_feature_hierarchy_payload(
    session: Session,
    *,
    assessment_id: int,
    scan_id: Optional[int] = None,
) -> Dict[str, Any]:
    scoped_results = _scoped_scan_results(session, assessment_id=assessment_id, scan_id=scan_id)
    scoped_result_by_id = {row.id: row for row in scoped_results if row.id is not None}
    scoped_result_ids = set(scoped_result_by_id.keys())

    features = session.exec(
        select(Feature)
        .where(Feature.assessment_id == assessment_id)
        .order_by(Feature.id.asc())
    ).all()
    feature_ids = [feature.id for feature in features if feature.id is not None]
    recommendations_by_feature: Dict[int, List[Dict[str, Any]]] = {}
    if feature_ids:
        recommendation_rows = session.exec(
            select(FeatureRecommendation)
            .where(FeatureRecommendation.assessment_id == assessment_id)
            .where(FeatureRecommendation.feature_id.in_(feature_ids))
            .order_by(FeatureRecommendation.id.asc())
        ).all()
        for recommendation in recommendation_rows:
            recommendations_by_feature.setdefault(recommendation.feature_id, []).append(
                {
                    "id": recommendation.id,
                    "recommendation_type": recommendation.recommendation_type,
                    "ootb_capability_name": recommendation.ootb_capability_name,
                    "product_name": recommendation.product_name,
                    "sku_or_license": recommendation.sku_or_license,
                    "requires_plugins": _safe_json(recommendation.requires_plugins_json, []),
                    "fit_confidence": recommendation.fit_confidence,
                    "rationale": recommendation.rationale,
                    "evidence": _safe_json(recommendation.evidence_json, {}),
                    "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
                    "updated_at": recommendation.updated_at.isoformat() if recommendation.updated_at else None,
                }
            )

    members_by_feature: Dict[int, List[Dict[str, Any]]] = {}
    context_by_feature: Dict[int, List[Dict[str, Any]]] = {}
    assigned_customized_result_ids: set = set()

    if feature_ids:
        link_stmt = (
            select(FeatureScanResult, ScanResult)
            .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
            .join(Scan, ScanResult.scan_id == Scan.id)
            .where(FeatureScanResult.feature_id.in_(feature_ids))
            .where(Scan.assessment_id == assessment_id)
        )
        if scan_id is not None:
            link_stmt = link_stmt.where(Scan.id == scan_id)

        for link, result in session.exec(link_stmt).all():
            if result.id not in scoped_result_ids:
                continue
            origin_value = _origin_type_value(result)
            payload = {
                "link_id": link.id,
                "feature_id": link.feature_id,
                "scan_result": _build_compact_result_payload(result),
                "membership_type": link.membership_type,
                "assignment_source": link.assignment_source,
                "assignment_confidence": link.assignment_confidence,
                "iteration_number": link.iteration_number,
                "is_primary": bool(link.is_primary),
                "notes": link.notes,
                "evidence": _safe_json(link.evidence_json, {}),
            }
            if origin_value in _CUSTOMIZED_ORIGIN_VALUES:
                members_by_feature.setdefault(link.feature_id, []).append(payload)
                assigned_customized_result_ids.add(result.id)
            else:
                context_payload = {
                    "id": None,
                    "feature_id": link.feature_id,
                    "scan_result": _build_compact_result_payload(result),
                    "context_type": "legacy_feature_link",
                    "confidence": link.assignment_confidence if link.assignment_confidence is not None else 1.0,
                    "iteration_number": link.iteration_number,
                    "assignment_source": link.assignment_source,
                    "evidence": _safe_json(link.evidence_json, {}),
                }
                context_by_feature.setdefault(link.feature_id, []).append(context_payload)

        context_stmt = (
            select(FeatureContextArtifact, ScanResult)
            .join(ScanResult, FeatureContextArtifact.scan_result_id == ScanResult.id)
            .join(Scan, ScanResult.scan_id == Scan.id)
            .where(FeatureContextArtifact.assessment_id == assessment_id)
            .where(FeatureContextArtifact.feature_id.in_(feature_ids))
        )
        if scan_id is not None:
            context_stmt = context_stmt.where(Scan.id == scan_id)

        for context, result in session.exec(context_stmt).all():
            if result.id not in scoped_result_ids:
                continue
            payload = {
                "id": context.id,
                "feature_id": context.feature_id,
                "scan_result": _build_compact_result_payload(result),
                "context_type": context.context_type,
                "confidence": context.confidence,
                "iteration_number": context.iteration_number,
                "evidence": _safe_json(context.evidence_json, {}),
            }
            context_by_feature.setdefault(context.feature_id, []).append(payload)

    feature_nodes: Dict[int, Dict[str, Any]] = {}
    children_by_parent: Dict[int, List[int]] = {}
    root_feature_ids: List[int] = []
    for feature in features:
        if feature.id is None:
            continue
        node = {
            "id": feature.id,
            "name": feature.name,
            "description": feature.description,
            "parent_id": feature.parent_id,
            "disposition": feature.disposition.value if feature.disposition else None,
            "recommendation": feature.recommendation,
            "ai_summary": feature.ai_summary,
            "recommendations": recommendations_by_feature.get(feature.id, []),
            "confidence_score": feature.confidence_score,
            "confidence_level": feature.confidence_level,
            "members": sorted(
                members_by_feature.get(feature.id, []),
                key=lambda item: (
                    str(item["scan_result"].get("table_name") or ""),
                    str(item["scan_result"].get("name") or ""),
                    int(item["scan_result"].get("id") or 0),
                ),
            ),
            "context_artifacts": sorted(
                context_by_feature.get(feature.id, []),
                key=lambda item: (
                    str(item["scan_result"].get("table_name") or ""),
                    str(item["scan_result"].get("name") or ""),
                    int(item["scan_result"].get("id") or 0),
                ),
            ),
            "children": [],
        }
        feature_nodes[feature.id] = node
        if feature.parent_id and feature.parent_id in feature_nodes:
            children_by_parent.setdefault(feature.parent_id, []).append(feature.id)
        elif feature.parent_id and feature.parent_id not in feature_nodes:
            # Parent may be defined later in sequence.
            children_by_parent.setdefault(feature.parent_id, []).append(feature.id)
        else:
            root_feature_ids.append(feature.id)

    # Resolve parent/child links now that all nodes exist.
    for feature_id, node in feature_nodes.items():
        parent_id = node.get("parent_id")
        if parent_id and parent_id in feature_nodes:
            if feature_id not in children_by_parent.setdefault(parent_id, []):
                children_by_parent[parent_id].append(feature_id)
            if feature_id in root_feature_ids:
                root_feature_ids.remove(feature_id)

    def _render_feature_node(feature_id: int) -> Optional[Dict[str, Any]]:
        node = feature_nodes[feature_id]
        rendered_children: List[Dict[str, Any]] = []
        for child_id in sorted(children_by_parent.get(feature_id, [])):
            if child_id not in feature_nodes:
                continue
            child = _render_feature_node(child_id)
            if child is not None:
                rendered_children.append(child)
        rendered = dict(node)
        rendered["children"] = rendered_children
        rendered["member_count"] = len(rendered["members"])
        rendered["context_artifact_count"] = len(rendered["context_artifacts"])
        rendered["subtree_member_count"] = rendered["member_count"] + sum(
            child.get("subtree_member_count", 0) for child in rendered_children
        )
        rendered["subtree_context_artifact_count"] = rendered["context_artifact_count"] + sum(
            child.get("subtree_context_artifact_count", 0) for child in rendered_children
        )
        if scan_id is not None and rendered["subtree_member_count"] == 0 and rendered["subtree_context_artifact_count"] == 0:
            return None
        return rendered

    hierarchy: List[Dict[str, Any]] = []
    for feature_id in sorted(set(root_feature_ids)):
        if feature_id not in feature_nodes:
            continue
        rendered = _render_feature_node(feature_id)
        if rendered is not None:
            hierarchy.append(rendered)

    # Include orphaned children if parent rows are missing from scope.
    rendered_ids = set()
    stack = list(hierarchy)
    while stack:
        node = stack.pop()
        rendered_ids.add(node["id"])
        stack.extend(node.get("children", []))
    for feature_id in sorted(feature_nodes.keys()):
        if feature_id in rendered_ids:
            continue
        rendered = _render_feature_node(feature_id)
        if rendered is not None:
            hierarchy.append(rendered)

    ungrouped_by_class: Dict[str, List[Dict[str, Any]]] = {}
    for result in scoped_results:
        if result.id is None or not _is_customized_result(result):
            continue
        if result.id in assigned_customized_result_ids:
            continue
        key = str(result.table_name or "unknown")
        ungrouped_by_class.setdefault(key, []).append(_build_compact_result_payload(result))

    ungrouped = [
        {
            "app_file_class": app_file_class,
            "count": len(rows),
            "results": sorted(
                rows,
                key=lambda row: (
                    str(row.get("name") or ""),
                    int(row.get("id") or 0),
                ),
            ),
        }
        for app_file_class, rows in sorted(ungrouped_by_class.items(), key=lambda item: item[0])
    ]

    def _count_feature_nodes(nodes: List[Dict[str, Any]]) -> int:
        total = 0
        for node in nodes:
            total += 1
            total += _count_feature_nodes(node.get("children", []))
        return total

    context_total = sum(len(rows) for rows in context_by_feature.values())

    return {
        "assessment_id": assessment_id,
        "scan_id": scan_id,
        "features": hierarchy,
        "ungrouped_customizations": ungrouped,
        "summary": {
            "feature_count": _count_feature_nodes(hierarchy),
            "customized_member_count": len(assigned_customized_result_ids),
            "context_artifact_count": context_total,
            "ungrouped_customized_count": sum(item["count"] for item in ungrouped),
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


def _build_feature_recommendation_payload(recommendation: FeatureRecommendation) -> Dict[str, Any]:
    return {
        "id": recommendation.id,
        "instance_id": recommendation.instance_id,
        "assessment_id": recommendation.assessment_id,
        "feature_id": recommendation.feature_id,
        "recommendation_type": recommendation.recommendation_type,
        "ootb_capability_name": recommendation.ootb_capability_name,
        "product_name": recommendation.product_name,
        "sku_or_license": recommendation.sku_or_license,
        "requires_plugins": _safe_json(recommendation.requires_plugins_json, []),
        "fit_confidence": recommendation.fit_confidence,
        "rationale": recommendation.rationale,
        "evidence": _safe_json(recommendation.evidence_json, {}),
        "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
        "updated_at": recommendation.updated_at.isoformat() if recommendation.updated_at else None,
    }


def _build_result_grouping_evidence_payload(session: Session, *, result_id: int) -> Dict[str, Any]:
    result = session.get(ScanResult, result_id)
    if not result:
        raise ValueError("Result not found")
    scan = session.get(Scan, result.scan_id)
    if not scan:
        raise ValueError("Scan not found")
    assessment = session.get(Assessment, scan.assessment_id)
    if not assessment:
        raise ValueError("Assessment not found")

    assignment_rows = session.exec(
        select(FeatureScanResult, Feature)
        .join(Feature, FeatureScanResult.feature_id == Feature.id)
        .where(FeatureScanResult.scan_result_id == result_id)
        .where(Feature.assessment_id == assessment.id)
        .order_by(FeatureScanResult.iteration_number.asc(), FeatureScanResult.created_at.asc(), Feature.id.asc())
    ).all()

    feature_assignments: List[Dict[str, Any]] = []
    feature_ids: List[int] = []
    for link, feature in assignment_rows:
        feature_assignments.append(
            {
                "link_id": link.id,
                "feature_id": feature.id,
                "feature_name": feature.name,
                "feature_description": feature.description,
                "is_primary": bool(link.is_primary),
                "membership_type": link.membership_type,
                "assignment_source": link.assignment_source,
                "assignment_confidence": link.assignment_confidence,
                "iteration_number": link.iteration_number,
                "created_at": link.created_at.isoformat() if link.created_at else None,
                "notes": link.notes,
                "evidence": _safe_json(link.evidence_json, {}),
            }
        )
        if feature.id is not None:
            feature_ids.append(feature.id)

    feature_recommendations: List[Dict[str, Any]] = []
    if feature_ids:
        recommendation_rows = session.exec(
            select(FeatureRecommendation)
            .where(FeatureRecommendation.assessment_id == assessment.id)
            .where(FeatureRecommendation.feature_id.in_(feature_ids))
            .order_by(FeatureRecommendation.id.asc())
        ).all()
        feature_recommendations = [
            _build_feature_recommendation_payload(row) for row in recommendation_rows
        ]

    grouping_payload = _build_grouping_signals_payload(
        session,
        assessment_id=assessment.id,
        scan_id=scan.id,
    )
    deterministic_signals = [
        signal
        for signal in grouping_payload["signals"]
        if result_id in signal.get("links", {}).get("member_result_ids", [])
    ]

    update_set_links = session.exec(
        select(UpdateSetArtifactLink, UpdateSet)
        .join(UpdateSet, UpdateSetArtifactLink.update_set_id == UpdateSet.id)
        .where(UpdateSetArtifactLink.assessment_id == assessment.id)
        .where(UpdateSetArtifactLink.scan_result_id == result_id)
        .order_by(UpdateSetArtifactLink.id.asc())
    ).all()

    related_update_sets: List[Dict[str, Any]] = []
    update_set_ids: set = set()
    for link, update_set in update_set_links:
        if update_set.id is not None:
            update_set_ids.add(update_set.id)
        related_update_sets.append(
            {
                "link_id": link.id,
                "update_set_id": update_set.id,
                "update_set_name": update_set.name,
                "link_source": link.link_source,
                "is_current": bool(link.is_current),
                "confidence": link.confidence,
                "evidence": _safe_json(link.evidence_json, {}),
            }
        )

    if result.update_set_id and result.update_set_id not in update_set_ids:
        update_set = session.get(UpdateSet, result.update_set_id)
        if update_set:
            update_set_ids.add(update_set.id)
            related_update_sets.append(
                {
                    "link_id": None,
                    "update_set_id": update_set.id,
                    "update_set_name": update_set.name,
                    "link_source": "scan_result_current_fk",
                    "is_current": True,
                    "confidence": 1.0,
                    "evidence": {"source": "scan_result.update_set_id"},
                }
            )

    related_overlaps: List[Dict[str, Any]] = []
    overlap_rows = session.exec(
        select(UpdateSetOverlap)
        .where(UpdateSetOverlap.assessment_id == assessment.id)
        .where(
            or_(
                UpdateSetOverlap.update_set_a_id.in_(list(update_set_ids)) if update_set_ids else False,
                UpdateSetOverlap.update_set_b_id.in_(list(update_set_ids)) if update_set_ids else False,
            )
        )
    ).all() if update_set_ids else []

    for overlap in overlap_rows:
        member_ids = _parse_result_id_list(overlap.shared_records_json)
        if member_ids and result_id not in set(member_ids):
            continue
        related_overlaps.append(
            {
                "id": overlap.id,
                "update_set_a_id": overlap.update_set_a_id,
                "update_set_b_id": overlap.update_set_b_id,
                "shared_record_count": overlap.shared_record_count,
                "overlap_score": overlap.overlap_score,
                "signal_type": overlap.signal_type,
                "evidence": _safe_json(overlap.evidence_json, {}),
            }
        )

    related_customized: List[Dict[str, Any]] = []
    related_context: List[Dict[str, Any]] = []
    seen_customized_ids: set = set()
    seen_context_keys: set = set()

    if feature_ids:
        related_member_rows = session.exec(
            select(FeatureScanResult, ScanResult, Feature)
            .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
            .join(Feature, FeatureScanResult.feature_id == Feature.id)
            .where(FeatureScanResult.feature_id.in_(feature_ids))
            .where(ScanResult.id != result_id)
            .where(Feature.assessment_id == assessment.id)
        ).all()
        for link, related_result, feature in related_member_rows:
            row_payload = {
                "feature_id": feature.id,
                "feature_name": feature.name,
                "scan_result": _build_compact_result_payload(related_result),
                "membership_type": link.membership_type,
                "assignment_source": link.assignment_source,
                "assignment_confidence": link.assignment_confidence,
                "iteration_number": link.iteration_number,
                "evidence": _safe_json(link.evidence_json, {}),
            }
            if _is_customized_result(related_result):
                if related_result.id in seen_customized_ids:
                    continue
                seen_customized_ids.add(related_result.id)
                related_customized.append(row_payload)
            else:
                key = (feature.id, related_result.id, "legacy_feature_link")
                if key in seen_context_keys:
                    continue
                seen_context_keys.add(key)
                related_context.append(
                    {
                        "feature_id": feature.id,
                        "feature_name": feature.name,
                        "scan_result": _build_compact_result_payload(related_result),
                        "context_type": "legacy_feature_link",
                        "confidence": link.assignment_confidence if link.assignment_confidence is not None else 1.0,
                        "iteration_number": link.iteration_number,
                        "assignment_source": link.assignment_source,
                        "evidence": _safe_json(link.evidence_json, {}),
                    }
                )

        context_rows = session.exec(
            select(FeatureContextArtifact, ScanResult, Feature)
            .join(ScanResult, FeatureContextArtifact.scan_result_id == ScanResult.id)
            .join(Feature, FeatureContextArtifact.feature_id == Feature.id)
            .where(FeatureContextArtifact.feature_id.in_(feature_ids))
            .where(ScanResult.id != result_id)
            .where(Feature.assessment_id == assessment.id)
        ).all()
        for context, related_result, feature in context_rows:
            key = (feature.id, related_result.id, context.context_type)
            if key in seen_context_keys:
                continue
            seen_context_keys.add(key)
            related_context.append(
                {
                    "feature_id": feature.id,
                    "feature_name": feature.name,
                    "scan_result": _build_compact_result_payload(related_result),
                    "context_type": context.context_type,
                    "confidence": context.confidence,
                    "iteration_number": context.iteration_number,
                    "evidence": _safe_json(context.evidence_json, {}),
                }
            )

    iteration_history = [
        {
            "iteration_number": item["iteration_number"],
            "assignment_source": item["assignment_source"],
            "feature_id": item["feature_id"],
            "feature_name": item["feature_name"],
            "assignment_confidence": item["assignment_confidence"],
            "created_at": item["created_at"],
        }
        for item in feature_assignments
    ]

    return {
        "result": {
            **_build_compact_result_payload(result),
            "assessment_id": assessment.id,
            "instance_id": assessment.instance_id,
        },
        "feature_assignments": feature_assignments,
        "feature_recommendations": feature_recommendations,
        "deterministic_signals": deterministic_signals,
        "related_update_sets": {
            "update_sets": related_update_sets,
            "overlaps": related_overlaps,
        },
        "related_artifacts": {
            "customized": related_customized,
            "context": related_context,
        },
        "iteration_history": iteration_history,
        "generated_at": datetime.utcnow().isoformat(),
    }


def _clear_instance_data_types(session: Session, instance_id: int, data_types: List[DataPullType]) -> None:
    for dt in data_types:
        table = DATA_PULL_STORAGE_TABLE_MAP.get(dt)
        if table:
            session.exec(text(f"DELETE FROM {table} WHERE instance_id = :id").bindparams(id=instance_id))

        pull = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type == dt)
        ).first()
        if pull:
            pull.status = DataPullStatus.idle
            pull.records_pulled = 0
            pull.last_pulled_at = None
            pull.started_at = None
            pull.completed_at = None
            pull.error_message = None
            pull.last_sys_updated_on = None
            pull.expected_total = None
            pull.expected_total_at = None
            pull.cancel_requested = False
            pull.cancel_requested_at = None
            pull.run_uid = None
            session.add(pull)

    session.commit()


def _request_cancel_data_pulls(
    session: Session,
    instance_id: int,
    data_types: List[DataPullType],
    signal_workers: bool,
) -> None:
    """Request cancellation for running/queued data pulls."""
    now = datetime.utcnow()
    for dt in data_types:
        pull = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type == dt)
        ).first()
        if not pull:
            pull = InstanceDataPull(
                instance_id=instance_id,
                data_type=dt,
                status=DataPullStatus.cancelled,
                cancel_requested=False,
                cancel_requested_at=None,
                completed_at=now,
                error_message="Cancelled by user",
            )
            session.add(pull)
            continue

        # Don't rewrite historical results.
        if pull.status in (DataPullStatus.completed, DataPullStatus.failed):
            continue

        # Make cancel authoritative immediately for UI.
        # cancel_requested is a transient signal for in-flight workers; only set it if we believe a worker thread is alive.
        pull.cancel_requested = signal_workers and pull.status == DataPullStatus.running
        pull.cancel_requested_at = now if pull.cancel_requested else None
        pull.status = DataPullStatus.cancelled
        pull.completed_at = now
        pull.error_message = "Cancelled by user"
        pull.updated_at = now
        session.add(pull)
    session.commit()


def _run_scans_background(assessment_id: int, mode: str = "full") -> None:
    """Run scans in a background thread to avoid blocking the request."""
    _set_assessment_scan_job_state(
        assessment_id,
        stage="validating_instance",
        status="running",
        message="Validating instance connection...",
    )
    with Session(engine) as bg_session:
        assessment = bg_session.get(Assessment, assessment_id)
        if not assessment:
            raise RuntimeError("Assessment not found")
        instance = assessment.instance or bg_session.get(Instance, assessment.instance_id)
        if not instance:
            raise RuntimeError("Instance not found")
        password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(
            instance.url,
            instance.username,
            password,
            instance_id=instance.id,
        )
        test_result = client.test_connection()
        if not test_result.get("success"):
            message = test_result.get("message") or "Connection test failed"
            raise RuntimeError(message)
        _set_assessment_scan_job_state(
            assessment_id,
            stage="preflight_sync",
            status="running",
            message="Syncing preflight datasets...",
        )
        # If a proactive VH pull is running/complete, exclude VH from the
        # preflight — it will be handled by Stage 5 (VH wait) instead.
        # IMPORTANT: Only check for an existing event — don't create one.
        # _start_proactive_vh_pull is the only creator; if it never ran,
        # there is no event and VH must stay in the preflight.
        with _VH_EVENTS_LOCK:
            vh_event = _VH_EVENTS.get(instance.id)
        proactive_vh_active = _is_vh_pull_active(instance.id) or (vh_event is not None and vh_event.is_set())
        all_preflight_types = list(ASSESSMENT_PREFLIGHT_DATA_TYPES)
        if proactive_vh_active and DataPullType.version_history in all_preflight_types:
            all_preflight_types.remove(DataPullType.version_history)
        # Single preflight pass: all types probed + pulled.  Concurrent types
        # (VH, customer_update_xml) run in background threads; sequential types
        # complete in the main thread.  The function returns WITHOUT joining
        # concurrent threads so the pipeline can proceed to scans immediately.
        preflight_plan = _run_assessment_preflight_data_sync(
            session=bg_session,
            instance=instance,
            client=client,
            stale_minutes=ASSESSMENT_PREFLIGHT_STALE_MINUTES,
            data_types=all_preflight_types,
            wait_for_running=True,
            wait_timeout_seconds=ASSESSMENT_PREFLIGHT_WAIT_SECONDS,
            version_history_current_only=True,
        )
        bg_concurrent_threads = preflight_plan.get("_concurrent_threads", [])
        bg_concurrent_errors = preflight_plan.get("_concurrent_errors", {})
        _set_assessment_scan_job_state(
            assessment_id,
            stage="running_scans",
            status="running",
            message="Running assessment scans...",
        )
        run_scans_for_assessment(bg_session, assessment, client, mode=mode, skip_classification=True)
        # ── Post Flight: pull full artifact details for scan results ──
        _set_assessment_scan_job_state(
            assessment_id,
            stage="postflight_artifact_pull",
            status="running",
            message="Pulling artifact details...",
        )
        pf_run_uid = None
        try:
            from .services.artifact_detail_puller import pull_artifact_details_for_assessment

            # Create a durable JobRun for postflight tracking
            pf_now = datetime.utcnow()
            pf_run_uid = uuid.uuid4().hex
            pf_run = JobRun(
                run_uid=pf_run_uid,
                instance_id=instance.id,
                module=_POSTFLIGHT_RUN_MODULE,
                job_type=_POSTFLIGHT_RUN_TYPE,
                mode="artifact_pull",
                status=JobRunStatus.running,
                queue_total=0,
                queue_completed=0,
                progress_pct=0,
                message="Pulling artifact details for scan results...",
                metadata_json=_json_dumps({"assessment_id": assessment_id}),
                created_at=pf_now,
                started_at=pf_now,
                updated_at=pf_now,
                last_heartbeat_at=pf_now,
            )
            bg_session.add(pf_run)
            bg_session.commit()

            def _postflight_cb(
                sys_class_name: str,
                label: str,
                status: str,
                pulled: int,
                total: int,
            ) -> None:
                _update_assessment_postflight_details(
                    assessment_id, sys_class_name, label, status, pulled, total,
                    pf_run_uid=pf_run_uid,
                )

            summary = pull_artifact_details_for_assessment(
                session=bg_session,
                assessment=assessment,
                client=client,
                engine=engine,
                progress_callback=_postflight_cb,
            )

            # Mark postflight JobRun as completed
            bg_session.refresh(pf_run)
            pf_run.status = JobRunStatus.completed
            pf_run.completed_at = datetime.utcnow()
            pf_run.progress_pct = 100
            pf_run.queue_total = summary.get("total_classes", 0)
            pf_run.queue_completed = summary.get("total_classes", 0)
            pf_run.current_data_type = f"{summary.get('total_pulled', 0)} artifacts"
            pf_run.message = f"Pulled {summary.get('total_pulled', 0)} artifacts across {summary.get('total_classes', 0)} classes."
            pf_run.updated_at = datetime.utcnow()
            bg_session.add(pf_run)
            bg_session.commit()

        except Exception as exc:
            logger.warning("Postflight artifact pull failed (non-fatal): %s", exc)
            if pf_run_uid:
                try:
                    pf_run = bg_session.exec(
                        select(JobRun).where(JobRun.run_uid == pf_run_uid)
                    ).first()
                    if pf_run:
                        pf_run.status = JobRunStatus.failed
                        pf_run.completed_at = datetime.utcnow()
                        pf_run.error_message = str(exc)[:500]
                        pf_run.updated_at = datetime.utcnow()
                        bg_session.add(pf_run)
                        bg_session.commit()
                except Exception:
                    pass
        # ── Stage 5: Wait for concurrent preflight threads + proactive VH ──
        # Join any background preflight threads (VH, customer_update_xml)
        # that were still running while scans + artifact pull proceeded.
        if bg_concurrent_threads:
            _set_assessment_scan_job_state(
                assessment_id,
                stage="waiting_for_concurrent_preflight",
                status="running",
                message="Waiting for background data pulls to complete...",
            )
            for t in bg_concurrent_threads:
                t.join(timeout=7200)  # 2hr safety net
            for dt_name, exc in bg_concurrent_errors.items():
                if exc:
                    logger.error("Concurrent preflight pull %s failed: %s", dt_name, exc)
        # Also wait for proactive VH pull (from instance add/test) if active.
        with _VH_EVENTS_LOCK:
            vh_event = _VH_EVENTS.get(instance.id)
        if vh_event is not None:
            if not vh_event.is_set():
                _set_assessment_scan_job_state(
                    assessment_id,
                    stage="waiting_for_vh",
                    status="running",
                    message="Waiting for version history pull to complete...",
                )
                vh_complete = vh_event.wait(timeout=3600)  # 1hr max
                if not vh_complete:
                    logger.warning(
                        "VH pull timed out for instance %s (assessment %s)",
                        instance.id, assessment_id,
                    )
            _clear_vh_event(instance.id)

        _set_assessment_scan_job_state(
            assessment_id,
            stage="version_history_catchup",
            status="running",
            message="Running version history catch-up...",
        )
        _run_assessment_version_history_postscan_catchup(
            session=bg_session,
            instance=instance,
            client=client,
        )
        # ── Stage 6: Re-classify results now that full VH data is available ──
        _set_assessment_scan_job_state(
            assessment_id,
            stage="classifying_results",
            status="running",
            message="Classifying scan results with full version history...",
        )
        classify_scan_results(session=bg_session, assessment_id=assessment_id)


def _run_single_scan_background(scan_id: int, mode: str = "full") -> None:
    """Run a single scan in a background thread."""
    with Session(engine) as bg_session:
        scan = bg_session.get(Scan, scan_id)
        if not scan:
            return
        assessment = bg_session.get(Assessment, scan.assessment_id)
        if not assessment:
            return
        instance = assessment.instance or bg_session.get(Instance, assessment.instance_id)
        if not instance:
            return
        password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(
            instance.url,
            instance.username,
            password,
            instance_id=instance.id,
        )
        test_result = client.test_connection()
        if not test_result.get("success"):
            return

        last_completed_at = scan.completed_at
        clear_results = mode == "full"
        reset_scan_state(bg_session, scan, clear_results=clear_results)
        bg_session.commit()

        file_class = None
        if scan.query_params_json:
            try:
                params = json.loads(scan.query_params_json)
                file_class_name = params.get("app_file_class")
                if file_class_name:
                    file_class = bg_session.exec(
                        select(AppFileClass).where(AppFileClass.sys_class_name == file_class_name)
                    ).first()
                    if not file_class:
                        cached_type = bg_session.exec(
                            select(InstanceAppFileType)
                            .where(InstanceAppFileType.instance_id == assessment.instance_id)
                            .where(InstanceAppFileType.sys_class_name == file_class_name)
                        ).first()
                        if cached_type:
                            file_class = AppFileClass(
                                sys_class_name=file_class_name,
                                label=cached_type.label or cached_type.name or file_class_name,
                                target_table_field=cached_type.source_field,
                                has_script=True,
                                is_important=False,
                                display_order=cached_type.priority or 9999,
                                is_active=True,
                            )
            except json.JSONDecodeError:
                file_class = None

        since = last_completed_at if mode == "delta" else None
        execute_scan(
            session=bg_session,
            scan=scan,
            client=client,
            instance_id=assessment.instance_id,
            file_class=file_class,
            enable_customization=True,
            enable_version_history=True,
            since=since,
            append_mode=(mode == "delta"),
        )


def _run_data_pulls_background(
    instance_id: int,
    data_types: List[str],
    mode: str = "full",
    cancel_event: Optional[threading.Event] = None,
    run_uid: Optional[str] = None,
    source_context: str = "preflight",
) -> None:
    """Run data pulls in a background thread to avoid blocking the request."""
    with Session(engine) as bg_session:
        if run_uid:
            _mark_data_pull_run_running(bg_session, run_uid, total=len(data_types))

        instance = bg_session.get(Instance, instance_id)
        if not instance:
            if run_uid:
                _mark_data_pull_run_finished(
                    bg_session,
                    run_uid,
                    status=JobRunStatus.failed,
                    queue_completed=0,
                    queue_total=len(data_types),
                    message="Instance not found.",
                    error_message="Instance not found.",
                )
            return
        password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(
            instance.url,
            instance.username,
            password,
            instance_id=instance.id,
        )
        test_result = client.test_connection()
        if not test_result.get("success"):
            if run_uid:
                message = test_result.get("message") or "Connection test failed."
                _mark_data_pull_run_finished(
                    bg_session,
                    run_uid,
                    status=JobRunStatus.failed,
                    queue_completed=0,
                    queue_total=len(data_types),
                    message=message,
                    error_message=message,
                )
            return

        # Convert string data types to enum
        pull_types = []
        for dt in data_types:
            try:
                pull_types.append(DataPullType(dt))
            except ValueError:
                continue

        if not pull_types:
            if run_uid:
                _mark_data_pull_run_finished(
                    bg_session,
                    run_uid,
                    status=JobRunStatus.failed,
                    queue_completed=0,
                    queue_total=0,
                    message="No valid data types were provided.",
                    error_message="No valid data types were provided.",
                )
            return

        # Pass mode straight through — execute_data_pull handles smart/delta/full
        # decision via resolve_delta_decision (single decision point).
        pull_mode = DataPullMode(mode) if mode in ("full", "delta", "smart") else DataPullMode.full
        completed_count = 0

        def _on_pull_start(data_type: DataPullType, index: int, total: int) -> None:
            if run_uid:
                _mark_data_pull_run_item_started(bg_session, run_uid, data_type, index, total)

        def _on_pull_complete(
            data_type: DataPullType,
            pull: InstanceDataPull,
            index: int,
            total: int,
        ) -> None:
            nonlocal completed_count
            completed_count = max(completed_count, index)
            # Stamp source_context on the pull record so the job log knows origin.
            if pull.source_context != source_context:
                pull.source_context = source_context
                bg_session.add(pull)
                bg_session.commit()
            if run_uid:
                _mark_data_pull_run_item_completed(bg_session, run_uid, data_type, pull, index, total)

        try:
            results = run_data_pulls_for_instance(
                bg_session,
                instance,
                client,
                pull_types,
                pull_mode,
                cancel_event=cancel_event,
                run_uid=run_uid,
                on_pull_start=_on_pull_start,
                on_pull_complete=_on_pull_complete,
            )
        except Exception as exc:
            if run_uid:
                _mark_data_pull_run_finished(
                    bg_session,
                    run_uid,
                    status=JobRunStatus.failed,
                    queue_completed=completed_count,
                    queue_total=len(pull_types),
                    message=f"Data pull run failed: {exc}",
                    error_message=str(exc),
                )
            raise

        statuses = [pull.status.value for pull in results.values()]
        if any(status == DataPullStatus.failed.value for status in statuses):
            final_status = JobRunStatus.failed
            final_message = "One or more pull types failed."
            final_error = "One or more pull types failed."
        elif any(status == DataPullStatus.cancelled.value for status in statuses) or (
            cancel_event and cancel_event.is_set()
        ):
            final_status = JobRunStatus.cancelled
            final_message = "Pull run cancelled."
            final_error = "Cancelled by user."
        else:
            final_status = JobRunStatus.completed
            final_message = "Pull run completed."
            final_error = None

        if run_uid:
            _mark_data_pull_run_finished(
                bg_session,
                run_uid,
                status=final_status,
                queue_completed=completed_count,
                queue_total=len(pull_types),
                message=final_message,
                error_message=final_error,
            )


def _build_assessment_preflight_plan(
    session: Session,
    instance_id: int,
    stale_minutes: int = ASSESSMENT_PREFLIGHT_STALE_MINUTES,
    data_types: Optional[List[DataPullType]] = None,
    now: Optional[datetime] = None,
    client: Optional[ServiceNowClient] = None,
    version_state_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Plan pre-scan cache sync for assessment execution.

    Uses the shared resolve_delta_decision contract (count + probe) for
    every data type, ensuring consistent skip/delta/full decisions across
    all integration paths.

    When *client* is provided, remote record counts and delta probe counts
    are fetched so that incomplete caches are detected and the smart
    decision logic can determine the optimal mode.
    """
    target_data_types = data_types or list(ASSESSMENT_PREFLIGHT_DATA_TYPES)
    reference_now = now or datetime.utcnow()

    full_types: List[DataPullType] = []
    delta_types: List[DataPullType] = []
    skip_types: List[DataPullType] = []
    fresh_types: List[DataPullType] = []
    decisions: Dict[str, str] = {}

    for dt in target_data_types:
        model_class = ASSESSMENT_PREFLIGHT_MODEL_MAP.get(dt)
        if not model_class:
            decisions[dt.value] = "unsupported"
            continue

        pull = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type == dt)
        ).first()

        if pull and pull.status == DataPullStatus.running:
            skip_types.append(dt)
            decisions[dt.value] = "already_running"
            continue

        # No time-based freshness gate — always fall through to
        # resolve_delta_decision which uses count + delta probes.

        # For VH with a state filter, count only matching local records
        # so the comparison with the remote count is apples-to-apples.
        vh_filter = version_state_filter if dt == DataPullType.version_history else None
        local_stmt = (
            select(func.count())
            .select_from(model_class)
            .where(model_class.instance_id == instance_id)
        )
        if vh_filter:
            local_stmt = local_stmt.where(func.lower(model_class.state) == vh_filter.lower())
        local_count = session.exec(local_stmt).one()

        if local_count == 0:
            full_types.append(dt)
            decisions[dt.value] = "full_empty_cache"
            continue

        # --- Unified delta decision via resolve_delta_decision ---
        watermark = _get_db_derived_watermark(session, instance_id, dt)
        if watermark is None and pull:
            watermark = pull.last_sys_updated_on

        remote_count = None
        delta_probe_count = None
        if client:
            try:
                remote_count = _estimate_expected_total(
                    session, client, dt, since=None, instance_id=instance_id,
                    version_state_filter=vh_filter,
                )
            except Exception:
                remote_count = None
            if watermark is not None:
                try:
                    delta_probe_count = _estimate_expected_total(
                        session, client, dt, since=watermark, instance_id=instance_id,
                        version_state_filter=vh_filter,
                    )
                except Exception:
                    delta_probe_count = None

        decision = resolve_delta_decision(
            local_count=local_count,
            remote_count=remote_count,
            watermark=watermark,
            delta_probe_count=delta_probe_count,
        )

        if decision.mode == "skip":
            fresh_types.append(dt)
            decisions[dt.value] = f"fresh ({decision.reason})"
        elif decision.mode == "delta":
            delta_types.append(dt)
            decisions[dt.value] = f"delta ({decision.reason})"
        else:
            full_types.append(dt)
            decisions[dt.value] = f"full ({decision.reason})"

    return {
        "full": full_types,
        "delta": delta_types,
        "skip": skip_types,
        "fresh": fresh_types,
        "stale_minutes": stale_minutes,
        "decisions": decisions,
    }


def _wait_for_running_pulls(
    session: Session,
    instance_id: int,
    data_types: List[DataPullType],
    timeout_seconds: int,
) -> bool:
    """Wait until selected data pulls are not running, or timeout."""
    if not data_types:
        return True
    if timeout_seconds <= 0:
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        running = session.exec(
            select(func.count())
            .select_from(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type.in_(data_types))
            .where(InstanceDataPull.status == DataPullStatus.running)
        ).one()
        if running == 0:
            return True
        session.expire_all()
        time.sleep(1)
    return False


def _run_assessment_preflight_data_sync(
    session: Session,
    instance: Instance,
    client: ServiceNowClient,
    stale_minutes: int = ASSESSMENT_PREFLIGHT_STALE_MINUTES,
    data_types: Optional[List[DataPullType]] = None,
    wait_for_running: bool = False,
    wait_timeout_seconds: int = ASSESSMENT_PREFLIGHT_WAIT_SECONDS,
    version_history_current_only: bool = False,
) -> Dict[str, Any]:
    """Sync Data Browser datasets needed for scan-time classification."""
    vh_state_filter = "current" if version_history_current_only else None
    plan = _build_assessment_preflight_plan(
        session=session,
        instance_id=instance.id,
        stale_minutes=stale_minutes,
        data_types=data_types,
        client=client,
        version_state_filter=vh_state_filter,
    )

    if wait_for_running and plan["skip"]:
        _wait_for_running_pulls(
            session=session,
            instance_id=instance.id,
            data_types=plan["skip"],
            timeout_seconds=wait_timeout_seconds,
        )
        plan = _build_assessment_preflight_plan(
            session=session,
            instance_id=instance.id,
            stale_minutes=stale_minutes,
            data_types=data_types,
            client=client,
            version_state_filter=vh_state_filter,
        )

    full_types = list(plan["full"])
    delta_types = list(plan["delta"])

    # ── Concurrent preflight types ─────────────────────────────────────
    # Types listed in PREFLIGHT_CONCURRENT_TYPES run in their own threads
    # (own Session + Client each) while remaining types run in main thread.
    concurrent_type_names = load_preflight_concurrent_types(session, instance.id)
    concurrent_dt_set = set()
    for name in concurrent_type_names:
        try:
            concurrent_dt_set.add(DataPullType(name))
        except ValueError:
            logger.warning("Unknown concurrent preflight type: %s", name)

    # Build per-type work items: (DataPullType, mode_str)
    concurrent_work: List[Tuple[DataPullType, str]] = []
    for dt in list(full_types):
        if dt in concurrent_dt_set:
            full_types.remove(dt)
            concurrent_work.append((dt, DataPullMode.full.value))
    for dt in list(delta_types):
        if dt in concurrent_dt_set:
            delta_types.remove(dt)
            concurrent_work.append((dt, DataPullMode.delta.value))

    # Launch one thread per concurrent type.
    inst_id = instance.id
    concurrent_threads: List[threading.Thread] = []
    concurrent_errors: Dict[str, Optional[Exception]] = {}

    for dt, mode_str in concurrent_work:
        concurrent_errors[dt.value] = None

        def _concurrent_worker(
            _dt: DataPullType = dt,
            _mode: str = mode_str,
        ) -> None:
            try:
                with Session(engine) as bg_session:
                    bg_inst = bg_session.get(Instance, inst_id)
                    if not bg_inst:
                        return
                    pw = decrypt_password(bg_inst.password_encrypted)
                    bg_client = ServiceNowClient(
                        bg_inst.url, bg_inst.username, pw,
                        instance_id=bg_inst.id,
                    )
                    extra_kwargs: Dict[str, Any] = {}
                    if _dt == DataPullType.version_history and version_history_current_only:
                        extra_kwargs["version_state_filter"] = "current"
                    execute_data_pull(
                        session=bg_session,
                        instance=bg_inst,
                        client=bg_client,
                        data_type=_dt,
                        mode=_mode,
                        **extra_kwargs,
                    )
            except Exception as exc:
                concurrent_errors[_dt.value] = exc
                logger.warning("%s preflight thread failed: %s", _dt.value, exc)

        t = threading.Thread(
            target=_concurrent_worker,
            daemon=True,
            name=f"preflight_{dt.value}_{inst_id}",
        )
        t.start()
        concurrent_threads.append(t)

    # Sequential types run in the main thread (full then delta).
    if full_types:
        run_data_pulls_for_instance(
            session=session,
            instance=instance,
            client=client,
            data_types=full_types,
            mode=DataPullMode.full,
        )

    if delta_types:
        run_data_pulls_for_instance(
            session=session,
            instance=instance,
            client=client,
            data_types=delta_types,
            mode=DataPullMode.delta,
        )

    # Touch fresh/skip types so they appear in the job log with current timestamps.
    # These types were verified as up-to-date; updating completed_at ensures they
    # sort alongside the actual pulls in the unified job log view.
    fresh_and_skip = list(plan.get("fresh", [])) + list(plan.get("skip", []))
    if fresh_and_skip:
        now = datetime.utcnow()
        for dt in fresh_and_skip:
            pull = session.exec(
                select(InstanceDataPull)
                .where(InstanceDataPull.instance_id == instance.id)
                .where(InstanceDataPull.data_type == dt)
            ).first()
            if pull:
                pull.completed_at = now
                pull.updated_at = now
                if pull.status != DataPullStatus.running:
                    pull.status = DataPullStatus.completed
                if not pull.started_at:
                    pull.started_at = now
                session.add(pull)
        session.commit()

    # Return concurrent threads to the caller so the pipeline can proceed
    # to scans without waiting.  Caller joins them before classification.
    plan["_concurrent_threads"] = concurrent_threads
    plan["_concurrent_errors"] = concurrent_errors
    return plan


def _run_assessment_version_history_postscan_catchup(
    session: Session,
    instance: Instance,
    client: ServiceNowClient,
) -> None:
    """After scans, fill remaining version-history rows (non-current + older states).

    If the prior VH pull used a state filter (e.g., state=current), the local count
    reflects only filtered records. The smart mode would see local(50K) << remote(500K)
    and decide "full" — re-downloading everything. Instead, we detect the filter and
    use delta from the watermark, pulling only records updated since the last pull.
    """
    # Check if the prior VH pull used a state filter
    pull = session.exec(
        select(InstanceDataPull)
        .where(InstanceDataPull.instance_id == instance.id)
        .where(InstanceDataPull.data_type == DataPullType.version_history)
    ).first()

    if pull and pull.state_filter_applied:
        # Prior pull was filtered (e.g., current-only). Use delta from watermark
        # instead of count-based smart mode which would incorrectly decide "full".
        watermark = _get_db_derived_watermark(session, instance.id, DataPullType.version_history)
        if watermark is None and pull:
            watermark = pull.last_sys_updated_on

        if watermark:
            logger.info(
                "VH catchup: prior pull had state_filter=%s, using delta from watermark %s",
                pull.state_filter_applied, watermark,
            )
            run_data_pulls_for_instance(
                session=session,
                instance=instance,
                client=client,
                data_types=[DataPullType.version_history],
                mode=DataPullMode.delta,
            )
        else:
            # No watermark available — fall back to full (rare: first-ever pull was filtered)
            logger.info("VH catchup: no watermark available despite state_filter=%s, using full", pull.state_filter_applied)
            run_data_pulls_for_instance(
                session=session,
                instance=instance,
                client=client,
                data_types=[DataPullType.version_history],
                mode=DataPullMode.full,
            )
        return

    # No state filter on prior pull — use standard smart mode decision
    mode = _determine_smart_mode_for_type(session, instance, client, DataPullType.version_history)
    if mode == "skip":
        return
    pull_mode = DataPullMode.delta if mode == "delta" else DataPullMode.full
    run_data_pulls_for_instance(
        session=session,
        instance=instance,
        client=client,
        data_types=[DataPullType.version_history],
        mode=pull_mode,
    )


def _determine_smart_mode_for_type(
    session: Session,
    instance: Instance,
    client: ServiceNowClient,
    data_type: DataPullType,
) -> str:
    """Determine the optimal sync mode for a data type using smart analysis."""
    # Model mapping for local count
    model_class = ASSESSMENT_PREFLIGHT_MODEL_MAP.get(data_type)
    if not model_class:
        return "full"

    # Get local count
    local_count = session.exec(
        select(func.count())
        .select_from(model_class)
        .where(model_class.instance_id == instance.id)
    ).one()

    # Get remote count
    try:
        remote_count = _estimate_expected_total(session, client, data_type, since=None, instance_id=instance.id) or 0
    except Exception:
        remote_count = 0

    # Get existing pull record for watermark info
    pull = session.exec(
        select(InstanceDataPull)
        .where(InstanceDataPull.instance_id == instance.id)
        .where(InstanceDataPull.data_type == data_type)
    ).first()

    last_sys_updated_on = _get_db_derived_watermark(session, instance.id, data_type)
    if last_sys_updated_on is None and pull:
        last_sys_updated_on = pull.last_sys_updated_on

    delta_probe_count = None
    if last_sys_updated_on is not None:
        delta_probe_count = _estimate_expected_total(
            session,
            client,
            data_type,
            since=last_sys_updated_on,
            instance_id=instance.id,
            inclusive=False,
        )

    decision = resolve_delta_decision(
        local_count=local_count,
        remote_count=remote_count,
        watermark=last_sys_updated_on,
        delta_probe_count=delta_probe_count,
    )

    # Store decision in pull record
    if pull:
        pull.sync_mode = decision.mode
        pull.last_local_count = local_count
        pull.last_remote_count = remote_count
        pull.sync_decision_reason = decision.reason
        session.add(pull)
        session.commit()

    return decision.mode


def _apply_instance_metrics(instance: Instance, metrics: Dict[str, Any]) -> None:
    instance.inventory_json = json.dumps(metrics.get("inventory") or {})
    instance.task_counts_json = json.dumps(metrics.get("task_counts") or {})
    instance.update_set_counts_json = json.dumps(metrics.get("update_set_counts") or {})
    instance.sys_update_xml_counts_json = json.dumps(metrics.get("sys_update_xml_counts") or {})
    instance.sys_update_xml_total = metrics.get("sys_update_xml_total")
    instance.sys_metadata_customization_count = metrics.get("sys_metadata_customization_count")
    instance.instance_dob = metrics.get("instance_dob")
    instance.instance_age_years = metrics.get("instance_age_years")
    instance.custom_scoped_app_count_x = (metrics.get("custom_scoped_app_counts") or {}).get("x")
    instance.custom_scoped_app_count_u = (metrics.get("custom_scoped_app_counts") or {}).get("u")
    instance.custom_table_count_x = (metrics.get("custom_table_counts") or {}).get("x")
    instance.custom_table_count_u = (metrics.get("custom_table_counts") or {}).get("u")
    instance.custom_field_count_x = (metrics.get("custom_field_counts") or {}).get("x")
    instance.custom_field_count_u = (metrics.get("custom_field_counts") or {}).get("u")
    instance.metrics_last_refreshed_at = datetime.utcnow()


def _refresh_instance_metrics(instance: Instance) -> Dict[str, Any]:
    password = decrypt_password(instance.password_encrypted)
    client = ServiceNowClient(
        instance.url,
        instance.username,
        password,
        instance_id=instance.id,
    )
    test_result = client.test_connection()
    if not test_result.get("success"):
        raise ServiceNowClientError(test_result.get("message", "Authentication failed"))

    instance.connection_status = ConnectionStatus.connected
    instance.last_connected = datetime.utcnow()
    if test_result.get("version"):
        instance.instance_version = test_result.get("version")

    metrics = client.get_instance_metrics()
    _apply_instance_metrics(instance, metrics)
    return metrics


def _sync_app_file_types_for_instance(
    session: Session,
    instance: Instance,
    *,
    mode: str = "smart",
) -> str:
    """
    Sync sys_app_file_type cache for an instance.

    Returns effective mode: full, delta, or skip.
    """
    password = decrypt_password(instance.password_encrypted)
    client = ServiceNowClient(
        instance.url,
        instance.username,
        password,
        instance_id=instance.id,
    )
    test_result = client.test_connection()
    if not test_result.get("success"):
        raise ServiceNowClientError(test_result.get("message", "Authentication failed"))

    effective_mode = mode
    if mode == "smart":
        effective_mode = _determine_smart_mode_for_type(
            session=session,
            instance=instance,
            client=client,
            data_type=DataPullType.app_file_types,
        )
    if effective_mode == "skip":
        return "skip"

    pull_mode = DataPullMode.delta if effective_mode == "delta" else DataPullMode.full
    run_data_pulls_for_instance(
        session=session,
        instance=instance,
        client=client,
        data_types=[DataPullType.app_file_types],
        mode=pull_mode,
    )
    return effective_mode


MCP_ADMIN_TOKEN_ENV = "TECH_ASSESSMENT_MCP_ADMIN_TOKEN"
MCP_ADMIN_TOKEN_KEY = "mcp_admin_token"


def _is_loopback_host(host: Optional[str]) -> bool:
    if not host:
        return False
    return host in {"127.0.0.1", "::1", "localhost"}


def _resolve_mcp_admin_token(session: Session) -> str:
    env_token = (os.getenv(MCP_ADMIN_TOKEN_ENV) or "").strip()
    if env_token:
        return env_token

    row = session.exec(
        select(AppConfig)
        .where(AppConfig.key == MCP_ADMIN_TOKEN_KEY)
        .where(AppConfig.instance_id.is_(None))
    ).first()
    if not row:
        return ""
    return (row.value or "").strip()


def require_mcp_admin(request: Request, session: Session = Depends(get_session)) -> Dict[str, Any]:
    expected_token = _resolve_mcp_admin_token(session)
    provided = (request.headers.get("x-mcp-admin-token") or request.query_params.get("admin_token") or "").strip()

    if expected_token:
        if provided != expected_token:
            raise HTTPException(status_code=403, detail="MCP admin token required")
        return {"mode": "token", "actor": request.headers.get("x-mcp-actor") or "admin_token"}

    # Fallback for local-only development if token not configured.
    client_host = request.client.host if request.client else None
    if _is_loopback_host(client_host):
        return {"mode": "local_trust", "actor": "local_operator"}

    raise HTTPException(
        status_code=403,
        detail=(
            "MCP admin token not configured for remote access. "
            f"Set {MCP_ADMIN_TOKEN_ENV} or app_config key '{MCP_ADMIN_TOKEN_KEY}'."
        ),
    )

# Create FastAPI app
app = FastAPI(
    title="Tech Assessment Hub",
    description="ServiceNow Technical Assessment Tool",
    version="0.1.0"
)

# Setup templates and static files
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "web" / "templates")
app.mount("/static", StaticFiles(directory=BASE_DIR / "web" / "static"), name="static")
app.include_router(artifacts_router)
app.include_router(customizations_router)
app.include_router(csdm_router)
app.include_router(data_browser_router)
app.include_router(dynamic_browser_router)
app.include_router(analytics_router)
app.include_router(mcp_admin_router)
app.include_router(job_log_router)
app.include_router(create_preferences_router(require_mcp_admin))
app.include_router(
    create_instances_router(
        templates=templates,
        normalize_instance_url=normalize_instance_url,
        start_data_pull_job=lambda instance_id, data_types, mode, source_context="preflight": _start_data_pull_job(instance_id, data_types, mode, source_context=source_context),
        refresh_instance_metrics=lambda instance: _refresh_instance_metrics(instance),
        apply_instance_metrics=lambda instance, metrics: _apply_instance_metrics(instance, metrics),
        sync_app_file_types_for_instance=lambda session, instance, mode="smart": _sync_app_file_types_for_instance(
            session, instance, mode=mode
        ),
        resolve_app_file_display_label=lambda **kwargs: _resolve_app_file_display_label(**kwargs),
        coerce_bool_payload_field=lambda payload, field_name: _coerce_bool_payload_field(payload, field_name),
        parse_app_file_type_ids_payload=lambda payload: _parse_app_file_type_ids_payload(payload),
        set_instance_app_file_type_assessment_flags=lambda *args, **kwargs: _set_instance_app_file_type_assessment_flags(
            *args, **kwargs
        ),
        apply_instance_app_file_type_assessment_flags=lambda row, **kwargs: _apply_instance_app_file_type_assessment_flags(
            row, **kwargs
        ),
        start_proactive_vh_pull=_start_proactive_vh_pull,
    )
)
app.include_router(
    create_pulls_router(
        templates=templates,
        start_data_pull_job=lambda instance_id, data_types, mode: _start_data_pull_job(instance_id, data_types, mode),
        clear_instance_data_types=lambda session, instance_id, data_types: _clear_instance_data_types(
            session, instance_id, data_types
        ),
        get_active_data_pull_job=lambda instance_id: _get_active_data_pull_job(instance_id),
        request_cancel_data_pulls=lambda session, instance_id, data_types, signal_workers: _request_cancel_data_pulls(
            session, instance_id, data_types, signal_workers
        ),
    )
)
templates.env.globals["static_version"] = str(int(datetime.utcnow().timestamp()))


# Compatibility export for legacy direct imports from src.server in tests/tools.
async def api_config_summary(
    instance_ids: str = "",
    range: str = "all_time",
    custom_value: Optional[int] = None,
    custom_unit: Optional[str] = None,
    session: Session = Depends(get_session),
):
    original_catalog = analytics_routes.inventory_class_tables
    analytics_routes.inventory_class_tables = inventory_class_tables
    try:
        return await analytics_routes.api_config_summary(
            instance_ids=instance_ids,
            range=range,
            custom_value=custom_value,
            custom_unit=custom_unit,
            session=session,
        )
    finally:
        analytics_routes.inventory_class_tables = original_catalog


# ============================================
# STARTUP EVENT
# ============================================

@app.on_event("startup")
def on_startup():
    """Initialize database and seed data on startup"""
    create_db_and_tables()
    # Run seed data (idempotent - only inserts if not exists)
    run_seed()
    _cleanup_legacy_instance_data_pull_rows()
    # Mark any CSDM ingestion jobs that were running when the server stopped.
    from .services.csdm_ingestion import recover_interrupted_jobs
    recover_interrupted_jobs()
    # If the server restarted mid-pull, background threads are gone; avoid stuck "running" state.
    with Session(engine) as session:
        stale_runs = session.exec(
            select(JobRun)
            .where(JobRun.status.in_([JobRunStatus.queued, JobRunStatus.running]))
        ).all()
        if stale_runs:
            now = datetime.utcnow()
            for run in stale_runs:
                run.status = JobRunStatus.failed
                run.completed_at = now
                run.current_data_type = None
                run.current_index = None
                run.progress_pct = 100
                run.error_message = run.error_message or "Interrupted (server restart)"
                run.message = "Interrupted (server restart)"
                run.updated_at = now
                run.last_heartbeat_at = now
                session.add(run)
                session.add(
                    JobEvent(
                        run_id=run.id,
                        event_type=JobRunStatus.failed.value,
                        summary="Run interrupted by server restart.",
                        data_json=_json_dumps(
                            {
                                "reason": "server_restart",
                                "module": run.module,
                                "job_type": run.job_type,
                            }
                        ),
                        created_at=now,
                    )
                )
            session.commit()

        stale_pulls = session.exec(
            select(InstanceDataPull).where(InstanceDataPull.status == DataPullStatus.running)
        ).all()
        if stale_pulls:
            now = datetime.utcnow()
            for pull in stale_pulls:
                pull.status = DataPullStatus.failed
                pull.completed_at = now
                pull.error_message = "Interrupted (server restart)"
                pull.updated_at = now
                session.add(pull)
            session.commit()

        # cancel_requested is a transient worker signal; ensure it doesn't block future pulls.
        stale_cancel_flags = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.status != DataPullStatus.running)
            .where(InstanceDataPull.cancel_requested == True)  # noqa: E712 - SQLAlchemy boolean compare
        ).all()
        if stale_cancel_flags:
            for pull in stale_cancel_flags:
                pull.cancel_requested = False
                pull.cancel_requested_at = None
                pull.updated_at = datetime.utcnow()
                session.add(pull)
            session.commit()

        stale_scans = session.exec(
            select(Scan).where(Scan.status == ScanStatus.running)
        ).all()
        if stale_scans:
            now = datetime.utcnow()
            for scan in stale_scans:
                scan.status = ScanStatus.failed
                scan.completed_at = now
                scan.error_message = scan.error_message or "Interrupted (server restart)"
                scan.cancel_requested = False
                scan.cancel_requested_at = None
                session.add(scan)
            session.commit()

        stale_scan_cancel_flags = session.exec(
            select(Scan)
            .where(Scan.status != ScanStatus.running)
            .where(Scan.cancel_requested == True)  # noqa: E712 - SQLAlchemy boolean compare
        ).all()
        if stale_scan_cancel_flags:
            now = datetime.utcnow()
            for scan in stale_scan_cancel_flags:
                scan.cancel_requested = False
                scan.cancel_requested_at = None
                session.add(scan)
            session.commit()

        bridge_cfg = load_bridge_config(session)
        if bridge_cfg.get("enabled"):
            BRIDGE_MANAGER.start(bridge_cfg)


@app.on_event("shutdown")
def on_shutdown():
    """Stop in-process sidecar bridge on app shutdown."""
    BRIDGE_MANAGER.stop()


# ============================================
# WEB UI ROUTES
# ============================================

def _build_dashboard_payload(session: Session) -> Dict[str, Any]:
    """Collect dashboard metrics and instance data used by dashboard-style views."""
    instances = session.exec(select(Instance)).all()
    instance_count = session.exec(select(func.count()).select_from(Instance)).one()
    assessment_count = session.exec(select(func.count()).select_from(Assessment)).one()
    scan_count = session.exec(select(func.count()).select_from(Scan)).one()
    result_count = session.exec(select(func.count()).select_from(ScanResult)).one()

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for severity, count in session.exec(
        select(ScanResult.severity, func.count()).group_by(ScanResult.severity)
    ).all():
        if not severity:
            continue
        key = severity.value if hasattr(severity, "value") else str(severity)
        severity_counts[key] = int(count or 0)

    return {
        "instance_count": int(instance_count or 0),
        "assessment_count": int(assessment_count or 0),
        "scan_count": int(scan_count or 0),
        "result_count": int(result_count or 0),
        "severity_counts": severity_counts,
        "instances": instances,
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    """Main dashboard page"""
    # Keep this endpoint fast: don't load whole tables (ScanResult can be very large).
    payload = _build_dashboard_payload(session)
    return templates.TemplateResponse("index.html", {"request": request, **payload})


def _coerce_bool_payload_field(payload: Dict[str, Any], field_name: str) -> Tuple[bool, Optional[bool]]:
    if field_name not in payload:
        return False, None

    raw_value = payload.get(field_name)
    if isinstance(raw_value, bool):
        return True, raw_value
    if isinstance(raw_value, int):
        return True, bool(raw_value)
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True, True
        if normalized in {"false", "0", "no", "off"}:
            return True, False
    raise HTTPException(status_code=400, detail=f"Invalid boolean value for {field_name}")


def _parse_app_file_type_ids_payload(payload: Dict[str, Any]) -> List[int]:
    raw_ids = payload.get("app_file_type_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=400, detail="app_file_type_ids must be a non-empty array")

    parsed_ids: List[int] = []
    seen_ids = set()
    for raw_id in raw_ids:
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            continue
        if parsed <= 0 or parsed in seen_ids:
            continue
        seen_ids.add(parsed)
        parsed_ids.append(parsed)

    if not parsed_ids:
        raise HTTPException(status_code=400, detail="No valid app_file_type_ids provided")
    return parsed_ids


def _set_instance_app_file_type_assessment_flags(
    session: Session,
    *,
    instance_id: int,
    app_file_type_id: int,
    is_available_for_assessment: Optional[bool] = None,
    is_default_for_assessment: Optional[bool] = None,
    commit: bool = True,
) -> Optional[InstanceAppFileType]:
    row = session.exec(
        select(InstanceAppFileType)
        .where(InstanceAppFileType.id == app_file_type_id)
        .where(InstanceAppFileType.instance_id == instance_id)
    ).first()
    if not row:
        return None

    _apply_instance_app_file_type_assessment_flags(
        row,
        is_available_for_assessment=is_available_for_assessment,
        is_default_for_assessment=is_default_for_assessment,
    )
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    return row


def _apply_instance_app_file_type_assessment_flags(
    row: InstanceAppFileType,
    *,
    is_available_for_assessment: Optional[bool] = None,
    is_default_for_assessment: Optional[bool] = None,
) -> None:
    if is_available_for_assessment is not None:
        row.is_available_for_assessment = bool(is_available_for_assessment)
        if not row.is_available_for_assessment:
            row.is_default_for_assessment = False

    if is_default_for_assessment is not None:
        if bool(is_default_for_assessment) and not bool(row.is_available_for_assessment):
            row.is_available_for_assessment = True
        row.is_default_for_assessment = bool(is_default_for_assessment)


async def instance_assessment_app_file_options_page(
    request: Request,
    instance_id: int,
    session: Session = Depends(get_session),
):
    """Compatibility export for direct test imports after route extraction."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    def _load_rows() -> List[InstanceAppFileType]:
        return session.exec(
            select(InstanceAppFileType)
            .where(InstanceAppFileType.instance_id == instance_id)
            .order_by(
                case((InstanceAppFileType.priority.is_(None), 1), else_=0),
                InstanceAppFileType.priority.asc(),
                InstanceAppFileType.label.asc(),
                InstanceAppFileType.sys_class_name.asc(),
            )
        ).all()

    app_file_types = _load_rows()
    auto_sync_status: Optional[str] = None
    auto_sync_message: Optional[str] = None

    if not app_file_types:
        try:
            effective_mode = _sync_app_file_types_for_instance(session, instance, mode="smart")
            if effective_mode == "skip":
                _sync_app_file_types_for_instance(session, instance, mode="full")
            app_file_types = _load_rows()
            auto_sync_status = "completed" if app_file_types else "empty"
        except Exception as exc:
            logger.warning(
                "Auto-sync of app_file_types failed for instance_id=%s: %s",
                instance_id,
                exc,
            )
            auto_sync_status = "failed"
            auto_sync_message = str(exc)

    available_count = sum(1 for row in app_file_types if bool(row.is_available_for_assessment))
    default_count = sum(
        1
        for row in app_file_types
        if bool(row.is_available_for_assessment) and bool(row.is_default_for_assessment)
    )
    display_labels_by_id = {
        row.id: _resolve_app_file_display_label(
            explicit_label=row.label,
            record_name=row.name,
            sys_class_name=row.sys_class_name,
        )
        for row in app_file_types
        if row.id is not None
    }
    return templates.TemplateResponse(
        "instance_assessment_app_file_options.html",
        {
            "request": request,
            "instance": instance,
            "app_file_types": app_file_types,
            "display_labels_by_id": display_labels_by_id,
            "available_count": available_count,
            "default_count": default_count,
            "auto_sync_status": auto_sync_status,
            "auto_sync_message": auto_sync_message,
        },
    )


@app.post("/mcp")
async def mcp_endpoint(request: Request, session: Session = Depends(get_session)):
    """MCP JSON-RPC endpoint."""
    payload = await request.json()
    request_context = {
        "actor": request.headers.get("x-mcp-actor")
        or request.headers.get("x-forwarded-user")
        or (request.client.host if request.client else "unknown"),
        "client_host": request.client.host if request.client else None,
    }
    if isinstance(payload, list):
        return [handle_mcp_request(item, session, request_context=request_context) for item in payload]
    return handle_mcp_request(payload, session, request_context=request_context)


# ============================================
# MCP CAPABILITY / HEALTH ROUTES
# ============================================

@app.get("/api/mcp/capabilities")
async def api_mcp_capabilities(session: Session = Depends(get_session)):
    """User-facing unified tool catalog (engine details hidden)."""
    snapshot = get_capability_snapshot(session, include_admin=False)
    return {
        "success": True,
        "tools": snapshot.get("tools", []),
        "metrics": snapshot.get("metrics", {}),
        "degraded_capabilities": snapshot.get("degraded_capabilities", []),
    }


@app.get("/api/mcp/health")
async def api_mcp_health(session: Session = Depends(get_session)):
    """Aggregate MCP runtime health without exposing per-tool engine internals."""
    snapshot = get_capability_snapshot(session, include_admin=False)
    bridge = snapshot.get("bridge", {})
    status = bridge.get("status", {}) if isinstance(bridge, dict) else {}
    return {
        "success": True,
        "health_state": status.get("health_state", "unavailable"),
        "bridge_running": bool(status.get("running")),
        "degraded_capabilities": snapshot.get("degraded_capabilities", []),
        "metrics": snapshot.get("metrics", {}),
        "bridge": bridge,
    }


@app.get("/api/mcp/admin/diagnostics")
async def api_mcp_admin_diagnostics(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Admin-only diagnostics with runtime source visibility and audit tail."""
    snapshot = get_capability_snapshot(session, include_admin=True)
    return {
        "success": True,
        "snapshot": snapshot,
        "audit_tail": tail_audit_events(limit=300),
    }


@app.get("/api/mcp/runtime/config")
async def api_mcp_runtime_get_config(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Admin-only runtime route/priority config."""
    return {"success": True, "config": load_runtime_config(session)}


@app.post("/api/mcp/runtime/config")
async def api_mcp_runtime_update_config(
    request: Request,
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Admin-only update for runtime route/priority config."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    current = load_runtime_config(session)
    merged = dict(current)
    merged.update(payload)
    saved = save_runtime_config(session, merged)
    return {"success": True, "config": saved}


# ============================================
# MCP BRIDGE MANAGEMENT ROUTES
# ============================================

@app.get("/api/mcp/bridge/config")
async def api_mcp_bridge_get_config(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Get persisted MCP bridge sidecar configuration."""
    return {"success": True, "config": load_bridge_config(session)}


@app.post("/api/mcp/bridge/config")
async def api_mcp_bridge_update_config(
    request: Request,
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Update persisted MCP bridge sidecar configuration."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    current = load_bridge_config(session)
    merged = dict(current)
    merged.update(payload)
    saved = save_bridge_config(session, merged)
    return {"success": True, "config": saved}


@app.get("/api/mcp/bridge/status")
async def api_mcp_bridge_status(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Get sidecar runtime status and optional health endpoint status."""
    config = load_bridge_config(session)
    status = BRIDGE_MANAGER.status()

    health_url = config.get("health_url") or ""
    health = None
    if health_url:
        try:
            health_resp = requests.get(health_url, timeout=5)
            health = {
                "ok": health_resp.ok,
                "status_code": health_resp.status_code,
                "body": health_resp.text[:500],
            }
        except Exception as exc:
            health = {"ok": False, "error": str(exc)}

    return {"success": True, "status": status, "health": health}


@app.post("/api/mcp/bridge/start")
async def api_mcp_bridge_start(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Start bridge sidecar using saved config."""
    config = load_bridge_config(session)
    return BRIDGE_MANAGER.start(config)


@app.post("/api/mcp/bridge/stop")
async def api_mcp_bridge_stop(_: Dict[str, Any] = Depends(require_mcp_admin)):
    """Stop bridge sidecar process."""
    return BRIDGE_MANAGER.stop()


@app.post("/api/mcp/bridge/restart")
async def api_mcp_bridge_restart(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Restart bridge sidecar process using saved config."""
    config = load_bridge_config(session)
    return BRIDGE_MANAGER.restart(config)


@app.get("/api/mcp/bridge/logs")
async def api_mcp_bridge_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Tail bridge sidecar logs."""
    return {"success": True, "logs": BRIDGE_MANAGER.tail_logs(limit)}


@app.post("/api/mcp/bridge/reload")
async def api_mcp_bridge_reload(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Proxy /mcp/reload to configured management base URL."""
    config = load_bridge_config(session)
    return BRIDGE_MANAGER.trigger_reload(config)


@app.post("/api/mcp/bridge/reconnect-all")
async def api_mcp_bridge_reconnect_all(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Proxy /mcp/reconnect-all to configured management base URL."""
    config = load_bridge_config(session)
    return BRIDGE_MANAGER.trigger_reconnect_all(config)


@app.post("/api/mcp/bridge/reconnect/{server_name}")
async def api_mcp_bridge_reconnect_server(
    server_name: str,
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Proxy /mcp/{name}/reconnect to configured management base URL."""
    config = load_bridge_config(session)
    return BRIDGE_MANAGER.trigger_reconnect(config, server_name)


@app.get("/api/mcp/bridge/state")
async def api_mcp_bridge_state(
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """Proxy /mcp/state to configured management base URL."""
    config = load_bridge_config(session)
    return BRIDGE_MANAGER.fetch_state(config)


@app.get("/api/mcp/bridge/events")
async def api_mcp_bridge_events(
    source: str = Query(default="local", pattern="^(local|remote)$"),
    session: Session = Depends(get_session),
    _: Dict[str, Any] = Depends(require_mcp_admin),
):
    """
    Stream bridge events.
    - local: emits sidecar lifecycle + heartbeat events
    - remote: relays configured remote event_url SSE data
    """
    config = load_bridge_config(session)

    if source == "remote":
        event_url = config.get("event_url") or ""
        if not event_url:
            raise HTTPException(status_code=400, detail="event_url is not configured")

        def remote_generator():
            try:
                for data in BRIDGE_MANAGER.remote_event_stream(config):
                    yield f"data: {data}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'bridge.remote_error', 'error': str(exc)})}\n\n"

        return StreamingResponse(remote_generator(), media_type="text/event-stream")

    def local_generator():
        for event in BRIDGE_MANAGER.iter_local_events():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(local_generator(), media_type="text/event-stream")


# ============================================
# ASSESSMENT ROUTES
# ============================================

@app.get("/api/instances/{instance_id}/app-file-classes")
async def get_instance_app_file_classes(
    instance_id: int,
    session: Session = Depends(get_session),
):
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    app_file_classes = _assessment_file_class_options(session, instance_id)
    default_selected = _default_selected_file_classes(session, instance_id)
    return {
        "instance_id": instance_id,
        "app_file_classes": app_file_classes,
        "default_selected": default_selected,
    }


@app.get("/assessments", response_class=HTMLResponse)
async def list_assessments(request: Request, session: Session = Depends(get_session)):
    """List all assessments"""
    assessments = session.exec(select(Assessment)).all()
    return templates.TemplateResponse("assessments.html", {
        "request": request,
        "assessments": assessments
    })


@app.get("/assessments/new", response_class=HTMLResponse)
async def new_assessment_form(
    request: Request,
    instance_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """Show new assessment form"""
    instances = session.exec(select(Instance)).all()
    global_apps = session.exec(select(GlobalApp).order_by(GlobalApp.display_order)).all()
    selected_instance_id = instance_id
    if selected_instance_id is None and instances:
        selected_instance_id = instances[0].id

    app_file_classes = _assessment_file_class_options(session, selected_instance_id)
    selected_class_names = _default_selected_file_classes(session, selected_instance_id)

    return templates.TemplateResponse("assessment_form.html", {
        "request": request,
        "action": "New",
        "assessment": None,
        "instances": instances,
        "global_apps": global_apps,
        "app_file_classes": app_file_classes,
        "selected_class_names": selected_class_names,
        "selected_instance_id": selected_instance_id,
    })


@app.post("/assessments/add")
async def add_assessment(
    request: Request,
    name: str = Form(...),
    instance_id: int = Form(...),
    assessment_type: str = Form(...),
    description: str = Form(None),
    target_app_id: int = Form(None),
    target_tables: str = Form(None),
    target_plugins: str = Form(None),
    scope_filter: str = Form("global"),
    session: Session = Depends(get_session)
):
    """Create a new assessment"""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Ensure app file types are up to date when creating an assessment.
    # This keeps the class source-of-truth aligned before scan setup.
    try:
        _sync_app_file_types_for_instance(session, instance, mode="smart")
    except Exception as exc:
        logger.warning(
            "App file type sync skipped for instance_id=%s during assessment create: %s",
            instance_id,
            exc,
        )

    # Get next assessment number
    number_seq = session.exec(
        select(NumberSequence).where(NumberSequence.prefix == "ASMT")
    ).first()

    if number_seq:
        assessment_number = number_seq.next_number()
        session.add(number_seq)
    else:
        assessment_number = "ASMT0000001"

    # Get selected app file classes from form
    form_data = await request.form()
    selected_classes = form_data.getlist("app_file_classes")
    if not selected_classes:
        selected_classes = _default_selected_file_classes(session, instance_id)
    app_file_classes_json = json.dumps(selected_classes) if selected_classes else None

    # Create assessment
    assessment = Assessment(
        number=assessment_number,
        name=name,
        description=description,
        instance_id=instance_id,
        assessment_type=AssessmentType(assessment_type),
        state=AssessmentState.pending,
        target_app_id=target_app_id if assessment_type == "global_app" else None,
        target_tables_json=target_tables if assessment_type == "table" else None,
        target_plugins_json=target_plugins if assessment_type == "plugin" else None,
        app_file_classes_json=app_file_classes_json,
        scope_filter=scope_filter
    )
    session.add(assessment)
    session.commit()
    session.refresh(assessment)

    return RedirectResponse(url=f"/assessments/{assessment.id}", status_code=303)


@app.get("/assessments/{assessment_id}", response_class=HTMLResponse)
async def view_assessment(
    request: Request,
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """View assessment details with scans and results"""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    def _label_for(dt: DataPullType) -> str:
        return DATA_TYPE_LABELS.get(dt.value, dt.value)

    required_set = set(ASSESSMENT_PREFLIGHT_REQUIRED_TYPES)
    assessment_has_scans = bool(assessment.scans)

    if assessment_has_scans:
        # Assessment has run — show plan with real probe-based decisions
        preflight_plan = _build_assessment_preflight_plan(
            session=session,
            instance_id=assessment.instance_id,
            stale_minutes=ASSESSMENT_PREFLIGHT_STALE_MINUTES,
        )

        sync_summary = _assessment_data_sync_summary(session, assessment.instance_id)
        pull_status_map: Dict[DataPullType, str] = {}
        sync_detail_map: Dict[str, Dict[str, Any]] = {}
        for row in sync_summary.get("details", []):
            try:
                dt = DataPullType(row.get("data_type"))
            except Exception:
                continue
            pull_status_map[dt] = str(row.get("status") or "idle")
            sync_detail_map[row.get("data_type")] = row

        def _preflight_ui_status(dt: DataPullType, bucket: str) -> str:
            pull_status = pull_status_map.get(dt, "idle")
            if pull_status in {"failed", "cancelled"}:
                return pull_status
            if pull_status == "completed":
                return "completed"
            if bucket == "fresh":
                return "completed"
            return "pending"

        def _make_item(dt: DataPullType, bucket: str) -> Dict[str, Any]:
            detail = sync_detail_map.get(dt.value, {})
            return {
                "data_type": dt.value,
                "label": _label_for(dt),
                "status": _preflight_ui_status(dt, bucket),
                "is_required": dt in required_set,
                "local_count": detail.get("local_count") or 0,
                "records_pulled": detail.get("records_pulled") or 0,
                "expected_total": detail.get("expected_total"),
                "decision": preflight_plan["decisions"].get(dt.value, ""),
            }

        def _preflight_group_status(items: List[Dict[str, Any]]) -> str:
            statuses = {row.get("status") for row in items}
            if "failed" in statuses:
                return "failed"
            if "cancelled" in statuses:
                return "cancelled"
            if "pending" in statuses:
                return "pending"
            return "completed"

        preflight_summary = {
            "full": [_make_item(dt, "full") for dt in preflight_plan["full"]],
            "delta": [_make_item(dt, "delta") for dt in preflight_plan["delta"]],
            "fresh": [_make_item(dt, "fresh") for dt in preflight_plan["fresh"]],
            "skip": [_make_item(dt, "skip") for dt in preflight_plan["skip"]],
            "pending_all": [],
            "stale_minutes": preflight_plan["stale_minutes"],
            "decisions": preflight_plan["decisions"],
        }

        preflight_summary["full_status"] = _preflight_group_status(preflight_summary["full"])
        preflight_summary["delta_status"] = _preflight_group_status(preflight_summary["delta"])
        preflight_summary["fresh_status"] = _preflight_group_status(preflight_summary["fresh"])
        preflight_summary["skip_status"] = _preflight_group_status(preflight_summary["skip"])
    else:
        # Fresh assessment — no probes have run, don't speculate on buckets.
        # Show all preflight data types in a single "Pending" group.
        all_types = list(ASSESSMENT_PREFLIGHT_DATA_TYPES)
        preflight_summary = {
            "full": [],
            "delta": [],
            "fresh": [],
            "skip": [],
            "pending_all": [
                {
                    "data_type": dt.value,
                    "label": _label_for(dt),
                    "status": "pending",
                    "is_required": dt in required_set,
                    "local_count": 0,
                    "records_pulled": 0,
                    "expected_total": None,
                    "decision": "awaiting_probes",
                }
                for dt in all_types
            ],
            "stale_minutes": ASSESSMENT_PREFLIGHT_STALE_MINUTES,
            "decisions": {dt.value: "awaiting_probes" for dt in all_types},
            "full_status": "completed",
            "delta_status": "completed",
            "fresh_status": "completed",
            "skip_status": "completed",
        }

    return templates.TemplateResponse("assessment_detail.html", {
        "request": request,
        "assessment": assessment,
        "preflight_summary": preflight_summary,
    })


@app.get("/assessments/{assessment_id}/edit", response_class=HTMLResponse)
async def edit_assessment_form(
    request: Request,
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Show edit assessment form"""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    instances = session.exec(select(Instance)).all()
    global_apps = session.exec(select(GlobalApp).order_by(GlobalApp.display_order)).all()
    app_file_classes = _assessment_file_class_options(session, assessment.instance_id)
    selected_class_names = _parse_json_string_list(assessment.app_file_classes_json)
    if not selected_class_names:
        selected_class_names = _default_selected_file_classes(session, assessment.instance_id)

    return templates.TemplateResponse("assessment_form.html", {
        "request": request,
        "action": "Edit",
        "assessment": assessment,
        "instances": instances,
        "global_apps": global_apps,
        "app_file_classes": app_file_classes,
        "selected_class_names": selected_class_names,
        "selected_instance_id": assessment.instance_id,
    })


@app.post("/assessments/{assessment_id}")
async def update_assessment(
    request: Request,
    assessment_id: int,
    name: str = Form(...),
    instance_id: int = Form(...),
    assessment_type: str = Form(...),
    description: str = Form(None),
    target_app_id: int = Form(None),
    target_tables: str = Form(None),
    target_plugins: str = Form(None),
    scope_filter: str = Form("global"),
    session: Session = Depends(get_session)
):
    """Update an existing assessment"""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    form_data = await request.form()
    selected_classes = form_data.getlist("app_file_classes")
    if not selected_classes:
        selected_classes = _default_selected_file_classes(session, instance_id)
    elif assessment.instance_id == instance_id:
        selected_classes = _preserve_unavailable_selected_file_classes(
            submitted_class_names=selected_classes,
            existing_class_names=_parse_json_string_list(assessment.app_file_classes_json),
            available_options=_assessment_file_class_options(session, instance_id),
        )
    app_file_classes_json = json.dumps(selected_classes) if selected_classes else None

    if assessment.instance_id != instance_id:
        instance = session.get(Instance, instance_id)
        if instance:
            try:
                _sync_app_file_types_for_instance(session, instance, mode="smart")
            except Exception as exc:
                logger.warning(
                    "App file type sync skipped for instance_id=%s during assessment update: %s",
                    instance_id,
                    exc,
                )

    assessment.name = name
    assessment.description = description
    assessment.instance_id = instance_id
    assessment.assessment_type = AssessmentType(assessment_type)
    assessment.scope_filter = scope_filter
    assessment.app_file_classes_json = app_file_classes_json

    if assessment_type == "global_app":
        assessment.target_app_id = target_app_id
        assessment.target_tables_json = None
        assessment.target_plugins_json = None
    elif assessment_type == "table":
        assessment.target_app_id = None
        assessment.target_tables_json = target_tables
        assessment.target_plugins_json = None
    elif assessment_type == "plugin":
        assessment.target_app_id = None
        assessment.target_tables_json = None
        assessment.target_plugins_json = target_plugins
    else:
        assessment.target_app_id = None
        assessment.target_tables_json = None
        assessment.target_plugins_json = None

    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/start")
async def start_assessment(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Start an assessment - changes state to in_progress"""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.pending:
        raise HTTPException(status_code=400, detail="Assessment must be in pending state to start")

    assessment.state = AssessmentState.in_progress
    assessment.started_at = datetime.utcnow()
    assessment.pipeline_stage = PipelineStage.scans
    assessment.pipeline_stage_updated_at = datetime.utcnow()
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/run-scans")
async def run_assessment_scans(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Run scans for an assessment using the backend rules engine."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.in_progress:
        raise HTTPException(status_code=400, detail="Assessment must be in progress to run scans")

    assessment.pipeline_stage = PipelineStage.scans
    assessment.pipeline_stage_updated_at = datetime.utcnow()
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    _start_assessment_scan_job(assessment_id, "full")

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/refresh-scans")
async def refresh_assessment_scans(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Refresh all scans (full) for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.in_progress:
        raise HTTPException(status_code=400, detail="Assessment must be in progress to refresh scans")

    assessment.pipeline_stage = PipelineStage.scans
    assessment.pipeline_stage_updated_at = datetime.utcnow()
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    _start_assessment_scan_job(assessment_id, "full")

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/refresh-scans-delta")
async def refresh_assessment_scans_delta(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Refresh all scans using delta mode (since last completion)."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.in_progress:
        raise HTTPException(status_code=400, detail="Assessment must be in progress to refresh scans")

    assessment.pipeline_stage = PipelineStage.scans
    assessment.pipeline_stage_updated_at = datetime.utcnow()
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    _start_assessment_scan_job(assessment_id, "delta")

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/rebuild-scans")
async def rebuild_assessment_scans(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Rebuild scans (delete and recreate) for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.in_progress:
        raise HTTPException(status_code=400, detail="Assessment must be in progress to rebuild scans")

    assessment.pipeline_stage = PipelineStage.scans
    assessment.pipeline_stage_updated_at = datetime.utcnow()
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    _start_assessment_scan_job(assessment_id, "rebuild")

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/complete")
async def complete_assessment(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Complete an assessment - changes state to completed"""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.in_progress:
        raise HTTPException(status_code=400, detail="Assessment must be in progress to complete")

    assessment.state = AssessmentState.completed
    assessment.completed_at = datetime.utcnow()
    assessment.pipeline_stage = PipelineStage.complete
    assessment.pipeline_stage_updated_at = datetime.utcnow()
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


def _request_cancel_assessment_scans(session: Session, assessment_id: int) -> Dict[str, int]:
    """Request cancellation of all scans under an assessment.

    - Running scans: set cancel_requested flag (executor should stop ASAP).
    - Pending scans: mark cancelled immediately (they haven't started).
    - Completed/failed/cancelled: no change.
    """
    scans = session.exec(select(Scan).where(Scan.assessment_id == assessment_id)).all()
    changed = 0
    requested = 0
    cancelled = 0

    for scan in scans:
        if scan.status == ScanStatus.running and not scan.cancel_requested:
            scan.cancel_requested = True
            scan.cancel_requested_at = datetime.utcnow()
            requested += 1
            changed += 1
            continue

        if scan.status == ScanStatus.pending:
            scan.cancel_requested = True
            scan.cancel_requested_at = datetime.utcnow()
            scan.status = ScanStatus.cancelled
            scan.completed_at = datetime.utcnow()
            scan.error_message = "Cancelled by user"
            cancelled += 1
            changed += 1

    if changed:
        session.add_all(scans)
        session.commit()

    return {"scans_total": len(scans), "cancel_requested": requested, "cancelled": cancelled}


@app.post("/assessments/{assessment_id}/stop-scans")
async def stop_assessment_scans(assessment_id: int, session: Session = Depends(get_session)):
    """Stop active scan execution without cancelling the assessment itself."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    _request_cancel_assessment_scans(session, assessment_id)
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/cancel")
async def cancel_assessment(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Cancel an assessment (and request cancellation of any running scans)."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state == AssessmentState.completed:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed assessment")

    _request_cancel_assessment_scans(session, assessment_id)
    assessment.state = AssessmentState.cancelled
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


@app.post("/assessments/{assessment_id}/reopen")
async def reopen_assessment(assessment_id: int, session: Session = Depends(get_session)):
    """Reopen a cancelled assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if assessment.state != AssessmentState.cancelled:
        raise HTTPException(status_code=400, detail="Assessment is not cancelled")

    assessment.state = AssessmentState.in_progress if assessment.started_at else AssessmentState.pending
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()

    return RedirectResponse(url=f"/assessments/{assessment_id}", status_code=303)


# ============================================
# SCAN RESULTS ROUTES
# ============================================

@app.get("/scans/{scan_id}", response_class=HTMLResponse)
async def view_scan(
    request: Request,
    scan_id: int,
    session: Session = Depends(get_session)
):
    """View scan details."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    return templates.TemplateResponse("scan_detail.html", {
        "request": request,
        "scan": scan,
    })


@app.post("/scans/{scan_id}/retry")
async def retry_scan(scan_id: int):
    """Retry a single scan (full)."""
    threading.Thread(
        target=_run_single_scan_background,
        args=(scan_id, "full"),
        daemon=True
    ).start()
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.post("/scans/{scan_id}/refresh-delta")
async def refresh_scan_delta(scan_id: int):
    """Retry a single scan using delta mode."""
    threading.Thread(
        target=_run_single_scan_background,
        args=(scan_id, "delta"),
        daemon=True
    ).start()
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.post("/scans/{scan_id}/cancel")
async def cancel_scan(scan_id: int, session: Session = Depends(get_session)):
    """Request cancellation of a running scan."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    scan.cancel_requested = True
    scan.cancel_requested_at = datetime.utcnow()
    if scan.status != ScanStatus.running:
        scan.status = ScanStatus.cancelled
        scan.completed_at = datetime.utcnow()
        scan.error_message = "Cancelled by user"
    session.add(scan)
    session.commit()
    return RedirectResponse(url=f"/scans/{scan_id}", status_code=303)


@app.get("/results", response_class=HTMLResponse)
async def list_results(request: Request, session: Session = Depends(get_session)):
    """Results explorer with cascading filters."""
    instances = session.exec(select(Instance).order_by(Instance.name.asc())).all()
    return templates.TemplateResponse("results.html", {
        "request": request,
        "instances": instances,
    })


@app.get("/results/{result_id}", response_class=HTMLResponse)
async def view_result(
    request: Request,
    result_id: int,
    session: Session = Depends(get_session)
):
    """View a single scan result."""
    result = session.get(ScanResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    scan = session.get(Scan, result.scan_id)
    assessment = session.get(Assessment, scan.assessment_id) if scan else None
    features = []
    current_feature_ids: List[int] = []
    instance: Optional[Instance] = None
    if assessment:
        instance = session.get(Instance, assessment.instance_id)
        features = session.exec(
            select(Feature).where(Feature.assessment_id == assessment.id).order_by(Feature.name.asc())
        ).all()
    current_links = session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == result_id)
    ).all()
    current_feature_ids = [link.feature_id for link in current_links]

    version_history_rows: List[VersionHistory] = []
    related_update_set: Optional[UpdateSet] = None
    related_customer_update: Optional[CustomerUpdateXML] = None
    related_metadata_customization: Optional[MetadataCustomization] = None
    update_set_updates: List[CustomerUpdateXML] = []

    if assessment:
        version_stmt = (
            select(VersionHistory)
            .where(VersionHistory.instance_id == assessment.instance_id)
        )
        if result.sys_update_name and result.sys_id:
            version_stmt = version_stmt.where(
                or_(
                    VersionHistory.sys_update_name == result.sys_update_name,
                    VersionHistory.customer_update_sys_id == result.sys_id,
                )
            )
        elif result.sys_update_name:
            version_stmt = version_stmt.where(VersionHistory.sys_update_name == result.sys_update_name)
        elif result.sys_id:
            version_stmt = version_stmt.where(VersionHistory.customer_update_sys_id == result.sys_id)
        version_history_rows = session.exec(
            version_stmt.order_by(
                case((func.lower(VersionHistory.state) == "current", 0), else_=1),
                desc(VersionHistory.sys_recorded_at),
                desc(VersionHistory.id),
            )
        ).all()

        related_metadata_customization = session.exec(
            select(MetadataCustomization)
            .where(MetadataCustomization.instance_id == assessment.instance_id)
            .where(
                or_(
                    MetadataCustomization.sys_metadata_sys_id == result.sys_id,
                    MetadataCustomization.sys_update_name == result.sys_update_name,
                )
            )
            .order_by(desc(MetadataCustomization.sys_updated_on), desc(MetadataCustomization.id))
        ).first()

        if result.customer_update_xml_id:
            related_customer_update = session.get(CustomerUpdateXML, result.customer_update_xml_id)

        if related_customer_update is None and result.sys_update_name:
            related_customer_update = session.exec(
                select(CustomerUpdateXML)
                .where(CustomerUpdateXML.instance_id == assessment.instance_id)
                .where(CustomerUpdateXML.name == result.sys_update_name)
                .order_by(desc(CustomerUpdateXML.sys_recorded_at), desc(CustomerUpdateXML.sys_updated_on), desc(CustomerUpdateXML.id))
            ).first()

        if related_customer_update is None and result.sys_id:
            related_customer_update = session.exec(
                select(CustomerUpdateXML)
                .where(CustomerUpdateXML.instance_id == assessment.instance_id)
                .where(CustomerUpdateXML.target_sys_id == result.sys_id)
                .order_by(desc(CustomerUpdateXML.sys_recorded_at), desc(CustomerUpdateXML.sys_updated_on), desc(CustomerUpdateXML.id))
            ).first()

        related_update_set_id = result.update_set_id
        if related_update_set_id is None and related_customer_update and related_customer_update.update_set_id:
            related_update_set_id = related_customer_update.update_set_id

        if related_update_set_id:
            related_update_set = session.get(UpdateSet, related_update_set_id)
        elif related_customer_update and related_customer_update.update_set_sn_sys_id:
            related_update_set = session.exec(
                select(UpdateSet)
                .where(UpdateSet.instance_id == assessment.instance_id)
                .where(UpdateSet.sn_sys_id == related_customer_update.update_set_sn_sys_id)
            ).first()

        if related_update_set:
            update_set_updates = session.exec(
                select(CustomerUpdateXML)
                .where(CustomerUpdateXML.instance_id == assessment.instance_id)
                .where(CustomerUpdateXML.update_set_id == related_update_set.id)
                .order_by(desc(CustomerUpdateXML.sys_recorded_at), desc(CustomerUpdateXML.sys_updated_on), desc(CustomerUpdateXML.id))
            ).all()
        elif related_customer_update and related_customer_update.update_set_sn_sys_id:
            update_set_updates = session.exec(
                select(CustomerUpdateXML)
                .where(CustomerUpdateXML.instance_id == assessment.instance_id)
                .where(CustomerUpdateXML.update_set_sn_sys_id == related_customer_update.update_set_sn_sys_id)
                .order_by(desc(CustomerUpdateXML.sys_recorded_at), desc(CustomerUpdateXML.sys_updated_on), desc(CustomerUpdateXML.id))
            ).all()

    instance_base_url = (instance.url.rstrip("/") if instance and instance.url else None)
    metadata_record_url = (
        f"{instance_base_url}/sys_metadata.do?sys_id={result.sys_id}&sysparm_ignore_class=true"
        if instance_base_url and result.sys_id
        else None
    )

    config_record_table = result.table_name or None
    config_record_sys_id = result.sys_id or None

    config_record_label = None
    if related_customer_update and related_customer_update.target_name and related_customer_update.target_name.strip():
        config_record_label = related_customer_update.target_name.strip()
    elif version_history_rows and version_history_rows[0].record_name and version_history_rows[0].record_name.strip():
        config_record_label = version_history_rows[0].record_name.strip()
    elif config_record_table and config_record_sys_id:
        config_record_label = f"{config_record_table}:{config_record_sys_id}"

    config_record_url = (
        f"{instance_base_url}/{config_record_table}.do?sys_id={config_record_sys_id}"
        if instance_base_url and config_record_table and config_record_sys_id
        else None
    )

    update_set_url = (
        f"{instance_base_url}/sys_update_set.do?sys_id={related_update_set.sn_sys_id}"
        if instance_base_url and related_update_set and related_update_set.sn_sys_id
        else None
    )
    customer_update_record_url = (
        f"/data-browser/record?instance_id={assessment.instance_id}&data_type={DataPullType.customer_update_xml.value}&record_id={related_customer_update.id}"
        if assessment and related_customer_update
        else None
    )
    metadata_customization_record_url = (
        f"/data-browser/record?instance_id={assessment.instance_id}&data_type={DataPullType.metadata_customization.value}&record_id={related_metadata_customization.id}"
        if assessment and related_metadata_customization
        else None
    )
    update_set_record_url = (
        f"/data-browser/record?instance_id={assessment.instance_id}&data_type={DataPullType.update_sets.value}&record_id={related_update_set.id}"
        if assessment and related_update_set
        else None
    )
    head_owner_label = _resolve_head_owner_label(result, instance)

    return templates.TemplateResponse("result_detail.html", {
        "request": request,
        "result": result,
        "head_owner_label": head_owner_label,
        "scan": scan,
        "assessment": assessment,
        "instance": instance,
        "features": features,
        "current_feature_ids": current_feature_ids,
        "version_history_rows": version_history_rows,
        "related_customer_update": related_customer_update,
        "related_metadata_customization": related_metadata_customization,
        "related_update_set": related_update_set,
        "update_set_updates": update_set_updates,
        "metadata_record_url": metadata_record_url,
        "config_record_table": config_record_table,
        "config_record_sys_id": config_record_sys_id,
        "config_record_label": config_record_label,
        "config_record_url": config_record_url,
        "update_set_url": update_set_url,
        "customer_update_record_url": customer_update_record_url,
        "metadata_customization_record_url": metadata_customization_record_url,
        "update_set_record_url": update_set_record_url,
        "review_statuses": [status.value for status in ReviewStatus],
        "dispositions": [disp.value for disp in Disposition],
        "severities": [sev.value for sev in Severity],
        "categories": [cat.value for cat in FindingCategory],
    })


@app.post("/results/{result_id}/update")
async def update_result(
    result_id: int,
    review_status: Optional[str] = Form(default=None),
    disposition: Optional[str] = Form(default=None),
    severity: Optional[str] = Form(default=None),
    category: Optional[str] = Form(default=None),
    assigned_to: Optional[str] = Form(default=None),
    is_adjacent: Optional[str] = Form(default=None),
    finding_title: Optional[str] = Form(default=None),
    finding_description: Optional[str] = Form(default=None),
    recommendation: Optional[str] = Form(default=None),
    observations: Optional[str] = Form(default=None),
    feature_id: Optional[int] = Form(default=None),
    new_feature_name: Optional[str] = Form(default=None),
    new_feature_description: Optional[str] = Form(default=None),
    session: Session = Depends(get_session)
):
    """Update a scan result's review fields and feature link."""
    result = session.get(ScanResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    if review_status in ReviewStatus._value2member_map_:
        result.review_status = ReviewStatus(review_status)
    if disposition in Disposition._value2member_map_:
        result.disposition = Disposition(disposition)
    if severity in Severity._value2member_map_:
        result.severity = Severity(severity)
    if category in FindingCategory._value2member_map_:
        result.category = FindingCategory(category)

    result.assigned_to = _clean(assigned_to)
    result.finding_title = _clean(finding_title)
    result.finding_description = _clean(finding_description)
    result.recommendation = _clean(recommendation)
    result.observations = _clean(observations)
    result.is_adjacent = bool(is_adjacent)

    scan = session.get(Scan, result.scan_id)
    assessment_id = scan.assessment_id if scan else None

    new_feature_name_clean = _clean(new_feature_name)
    new_feature_description_clean = _clean(new_feature_description)
    if new_feature_name_clean and assessment_id:
        new_feature = Feature(
            assessment_id=assessment_id,
            name=new_feature_name_clean,
            description=new_feature_description_clean
        )
        session.add(new_feature)
        session.commit()
        session.refresh(new_feature)
        feature_id = new_feature.id

    if feature_id:
        existing_links = session.exec(
            select(FeatureScanResult).where(FeatureScanResult.scan_result_id == result_id)
        ).all()
        for link in existing_links:
            session.delete(link)
        session.add(FeatureScanResult(feature_id=feature_id, scan_result_id=result_id, is_primary=True))

    session.add(result)
    session.commit()

    # Sync customization child table
    from .services.customization_sync import sync_single_result
    sync_single_result(session, result)

    return RedirectResponse(url=f"/results/{result_id}", status_code=303)


@app.post("/api/results/{result_id}/review-status")
async def api_update_result_review_status(
    result_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Update result review status (and optional observations) via JSON API."""
    result = session.get(ScanResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    payload: Dict[str, Any] = {}
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    review_status_raw = str(payload.get("review_status") or "").strip()
    if review_status_raw not in ReviewStatus._value2member_map_:
        raise HTTPException(
            status_code=400,
            detail=f"review_status must be one of: {', '.join(ReviewStatus._value2member_map_.keys())}",
        )

    observations_raw = payload.get("observations")
    observations: Optional[str] = None
    if observations_raw is not None:
        observations_text = str(observations_raw).strip()
        observations = observations_text or None

    result.review_status = ReviewStatus(review_status_raw)
    if observations_raw is not None:
        result.observations = observations
    session.add(result)
    session.commit()
    session.refresh(result)

    from .services.customization_sync import sync_single_result

    sync_single_result(session, result)

    return {
        "success": True,
        "result": {
            "id": result.id,
            "scan_id": result.scan_id,
            "review_status": result.review_status.value if hasattr(result.review_status, "value") else str(result.review_status),
            "observations": result.observations,
        },
    }


# ============================================
# API ROUTES (for AJAX and future MCP)
# ============================================

@app.get("/api/instances")
async def api_list_instances(session: Session = Depends(get_session)):
    """API: List all instances"""
    instances = session.exec(select(Instance)).all()
    return {"instances": [
        {
            "id": i.id,
            "name": i.name,
            "company": i.company,
            "url": i.url,
            "connection_status": i.connection_status.value,
            "instance_version": i.instance_version,
            "last_connected": i.last_connected.isoformat() if i.last_connected else None,
            "metrics_last_refreshed_at": i.metrics_last_refreshed_at.isoformat() if i.metrics_last_refreshed_at else None
        }
        for i in instances
    ]}


@app.get("/api/assessments/{assessment_id}/scan-status")
async def api_assessment_scan_status(
    assessment_id: int,
    session: Session = Depends(get_session)
):
    """Return scan status counts and per-scan details for polling."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    data_sync = _assessment_data_sync_summary(session, assessment.instance_id)

    scans = session.exec(
        select(Scan).where(Scan.assessment_id == assessment_id).order_by(Scan.id.asc())
    ).all()

    status_counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    scan_list = []
    for scan in scans:
        status_counts[scan.status.value] = status_counts.get(scan.status.value, 0) + 1
        scan_list.append({
            "id": scan.id,
            "name": scan.name,
            "scan_type": scan.scan_type.value,
            "status": scan.status.value,
            "records_found": scan.records_found,
            "records_customized": scan.records_customized,
            "records_customer_customized": scan.records_customer_customized,
            "records_ootb_modified": scan.records_ootb_modified,
            "started_at": scan.started_at.isoformat() if scan.started_at else None,
            "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
            "error_message": scan.error_message,
            "cancel_requested": scan.cancel_requested,
            "cancel_requested_at": scan.cancel_requested_at.isoformat() if scan.cancel_requested_at else None,
        })

    run_status = _get_assessment_scan_job_snapshot(
        assessment_id,
        scan_counts={
            **status_counts,
            "total": len(scans),
        },
    )
    if not run_status:
        run_status = _build_recovered_assessment_run_status(
            assessment=assessment,
            scans=scans,
            status_counts=status_counts,
        )

    # Grab postflight artifact pull details — prefer in-memory, fall back to DB
    postflight_details = None
    with _ASSESSMENT_SCAN_JOBS_LOCK:
        _pf_job = _ASSESSMENT_SCAN_JOBS.get(assessment_id)
        if _pf_job and _pf_job.postflight_details:
            postflight_details = list(_pf_job.postflight_details)

    if postflight_details is None:
        # Fall back to persisted postflight details from the latest postflight JobRun
        pf_run = session.exec(
            select(JobRun)
            .where(JobRun.module == _POSTFLIGHT_RUN_MODULE)
            .where(JobRun.job_type == _POSTFLIGHT_RUN_TYPE)
            .where(JobRun.instance_id == assessment.instance_id)
            .order_by(JobRun.created_at.desc())
            .limit(5)
        ).all()
        for run in pf_run:
            if run.metadata_json:
                try:
                    meta = json.loads(run.metadata_json)
                    if int(meta.get("assessment_id") or 0) == assessment_id:
                        postflight_details = meta.get("postflight_details")
                        break
                except Exception:
                    pass

    pipeline_stage = _pipeline_stage_value(assessment.pipeline_stage)
    pipeline_run = _get_assessment_pipeline_job_snapshot(assessment_id, session=session)
    review_gate = _assessment_review_gate_summary(session, assessment_id)

    return {
        "assessment_id": assessment_id,
        "counts": {
            **status_counts,
            "total": len(scans),
        },
        "scans": scan_list,
        "run_status": run_status,
        "data_sync": data_sync,
        "postflight_details": postflight_details,
        "pipeline": {
            "stage": pipeline_stage,
            "stage_label": _PIPELINE_STAGE_LABELS.get(pipeline_stage, pipeline_stage.title()),
            "stage_updated_at": (
                assessment.pipeline_stage_updated_at.isoformat()
                if assessment.pipeline_stage_updated_at
                else None
            ),
            "active_run": pipeline_run,
            "review_gate": review_gate,
        },
        "last_updated": datetime.utcnow().isoformat(),
    }


@app.post("/api/assessments/{assessment_id}/advance-pipeline")
async def api_advance_pipeline_stage(
    assessment_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Advance assessment reasoning pipeline by triggering the next stage job."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    payload: Dict[str, Any] = {}
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    raw_target_stage = payload.get("target_stage")
    if not raw_target_stage:
        raise HTTPException(status_code=400, detail="target_stage is required")
    target_stage = _pipeline_stage_value(raw_target_stage)

    allowed_targets = {
        PipelineStage.ai_analysis.value,
        PipelineStage.engines.value,
        PipelineStage.observations.value,
        PipelineStage.review.value,
        PipelineStage.grouping.value,
        PipelineStage.ai_refinement.value,
        PipelineStage.recommendations.value,
        PipelineStage.report.value,
    }
    if target_stage not in allowed_targets:
        raise HTTPException(
            status_code=400,
            detail=f"target_stage must be one of: {', '.join(sorted(allowed_targets))}",
        )

    skip_review = bool(payload.get("skip_review", False))
    force = bool(payload.get("force", False))
    rerun = bool(payload.get("rerun", False))

    current_stage = _pipeline_stage_value(assessment.pipeline_stage)
    current_index = _pipeline_stage_index(current_stage)
    target_index = _pipeline_stage_index(target_stage)

    # Re-run: allow reset from complete back to ai_analysis
    if rerun and current_stage == PipelineStage.complete.value and target_stage == PipelineStage.ai_analysis.value:
        _set_assessment_pipeline_stage(assessment_id, PipelineStage.scans.value, session=session)
        started = _start_assessment_pipeline_job(
            assessment_id,
            target_stage=target_stage,
            skip_review=skip_review,
        )
        if not started:
            raise HTTPException(
                status_code=409,
                detail="A pipeline stage run is already active for this assessment.",
            )
        pipeline_run = _get_assessment_pipeline_job_snapshot(assessment_id, session=session)
        refreshed = session.get(Assessment, assessment_id)
        return {
            "success": True,
            "assessment_id": assessment_id,
            "requested_stage": target_stage,
            "current_stage": _pipeline_stage_value(refreshed.pipeline_stage if refreshed else assessment.pipeline_stage),
            "rerun": True,
            "pipeline_run": pipeline_run,
            "review_gate": _assessment_review_gate_summary(session, assessment_id),
        }

    if not force:
        if target_index < current_index:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot move backwards from {current_stage} to {target_stage}.",
            )
        allow_review_bypass = (
            current_stage == PipelineStage.review.value
            and target_stage == PipelineStage.grouping.value
            and skip_review
        )
        if target_index > current_index + 1 and not allow_review_bypass:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid stage transition from {current_stage} to {target_stage}. "
                    "Advance stages sequentially."
                ),
            )

    review_gate = _assessment_review_gate_summary(session, assessment_id)
    if target_stage == PipelineStage.grouping.value and not skip_review and not review_gate["all_reviewed"]:
        raise HTTPException(
            status_code=409,
            detail="Review gate not satisfied. Mark all customized results reviewed or pass skip_review=true.",
        )

    if target_stage == PipelineStage.review.value:
        skipped_count = 0
        if skip_review and not review_gate["all_reviewed"]:
            skipped_count = _mark_remaining_customizations_reviewed(session, assessment_id)
            review_gate = _assessment_review_gate_summary(session, assessment_id)
        _set_assessment_pipeline_stage(assessment_id, PipelineStage.review.value, session=session)
        return {
            "success": True,
            "assessment_id": assessment_id,
            "requested_stage": target_stage,
            "current_stage": PipelineStage.review.value,
            "skipped_review_count": skipped_count,
            "review_gate": review_gate,
            "pipeline_run": None,
        }

    started = _start_assessment_pipeline_job(
        assessment_id,
        target_stage=target_stage,
        skip_review=skip_review,
    )
    if not started:
        raise HTTPException(
            status_code=409,
            detail="A pipeline stage run is already active for this assessment.",
        )

    pipeline_run = _get_assessment_pipeline_job_snapshot(assessment_id, session=session)
    refreshed = session.get(Assessment, assessment_id)
    return {
        "success": True,
        "assessment_id": assessment_id,
        "requested_stage": target_stage,
        "current_stage": _pipeline_stage_value(refreshed.pipeline_stage if refreshed else assessment.pipeline_stage),
        "skip_review": skip_review,
        "pipeline_run": pipeline_run,
        "review_gate": _assessment_review_gate_summary(session, assessment_id),
    }


@app.get("/api/results/options")
async def api_results_options(
    instance_id: Optional[int] = Query(default=None),
    assessment_ids: str = Query(default=""),
    scan_ids: str = Query(default=""),
    customized_only: bool = Query(default=True),
    customization_type: str = Query(default="all"),
    session: Session = Depends(get_session),
):
    """Return cascading filter options for the Results pages."""
    selected_assessment_ids = _parse_csv_ints(assessment_ids)
    selected_scan_ids = _parse_csv_ints(scan_ids)
    resolved_customization_type = _normalize_customization_type(customization_type)

    instances = session.exec(select(Instance).order_by(Instance.name.asc())).all()
    assessments_stmt = select(Assessment)
    if instance_id:
        assessments_stmt = assessments_stmt.where(Assessment.instance_id == instance_id)
    assessments = session.exec(assessments_stmt.order_by(desc(Assessment.created_at), desc(Assessment.id))).all()

    recommended_assessment_ids: List[int] = []
    if instance_id:
        latest_assessment = session.exec(
            select(Assessment.id)
            .where(Assessment.instance_id == instance_id)
            .order_by(desc(Assessment.created_at), desc(Assessment.id))
            .limit(1)
        ).first()
        if latest_assessment:
            recommended_assessment_ids = [latest_assessment]

    scan_option_conditions = _scan_result_conditions(
        instance_id=instance_id,
        assessment_ids=selected_assessment_ids,
        customized_only=customized_only,
        customization_type=resolved_customization_type,
    )
    scans_stmt = (
        select(Scan)
        .distinct()
        .join(Assessment, Scan.assessment_id == Assessment.id)
        .join(ScanResult, ScanResult.scan_id == Scan.id)
    )
    if scan_option_conditions:
        scans_stmt = scans_stmt.where(*scan_option_conditions)
    scans = session.exec(scans_stmt.order_by(desc(Scan.created_at), desc(Scan.id))).all()

    scoped_count_conditions = _scan_result_conditions(
        instance_id=instance_id,
        assessment_ids=selected_assessment_ids,
        scan_ids=selected_scan_ids,
        customized_only=customized_only,
        customization_type=resolved_customization_type,
    )
    app_file_classes = _results_option_app_file_classes(
        session,
        instance_id=instance_id,
        assessment_ids=selected_assessment_ids,
        scan_ids=selected_scan_ids,
        customized_only=customized_only,
        customization_type=resolved_customization_type,
    )

    count_stmt = _scan_results_count_stmt()
    if scoped_count_conditions:
        count_stmt = count_stmt.where(*scoped_count_conditions)
    scoped_count = int(session.exec(count_stmt).one() or 0)

    return {
        "instance_id": instance_id,
        "recommended_assessment_ids": recommended_assessment_ids,
        "selected_assessment_ids": selected_assessment_ids,
        "selected_scan_ids": selected_scan_ids,
        "customized_only": customized_only,
        "customization_type": resolved_customization_type,
        "scoped_count": scoped_count,
        "instances": [
            {
                "id": instance.id,
                "name": instance.name,
                "company": instance.company,
            }
            for instance in instances
        ],
        "assessments": [
            {
                "id": assessment.id,
                "instance_id": assessment.instance_id,
                "number": assessment.number,
                "name": assessment.name,
                "state": assessment.state.value if assessment.state else None,
                "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
            }
            for assessment in assessments
        ],
        "scans": [
            {
                "id": scan.id,
                "assessment_id": scan.assessment_id,
                "name": scan.name,
                "scan_type": scan.scan_type.value if scan.scan_type else None,
                "status": scan.status.value if scan.status else None,
                "records_found": scan.records_found,
                "records_customized": scan.records_customized,
                "records_customer_customized": scan.records_customer_customized,
                "records_ootb_modified": scan.records_ootb_modified,
                "app_file_class": _scan_option_app_file_class(scan),
            }
            for scan in scans
        ],
        "app_file_classes": app_file_classes,
    }


@app.get("/api/results/query")
async def api_results_query(
    instance_id: Optional[int] = Query(default=None),
    assessment_ids: str = Query(default=""),
    scan_ids: str = Query(default=""),
    customized_only: bool = Query(default=True),
    customization_type: str = Query(default="all"),
    app_file_classes: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Query scan results with cascading filters used by all results views."""
    payload = _query_scan_results_payload(
        session=session,
        instance_id=instance_id,
        assessment_ids=_parse_csv_ints(assessment_ids),
        scan_ids=_parse_csv_ints(scan_ids),
        customized_only=customized_only,
        customization_type=_normalize_customization_type(customization_type),
        table_names=_parse_csv_strings(app_file_classes),
        limit=limit,
        offset=offset,
    )
    return payload


@app.get("/api/assessments/{assessment_id}/results")
async def api_assessment_results(
    assessment_id: int,
    customized_only: bool = Query(default=True),
    customization_type: str = Query(default="all"),
    app_file_classes: str = Query(default=""),
    scan_ids: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Query results scoped to a single assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    selected_scan_ids = _parse_csv_ints(scan_ids)
    payload = _query_scan_results_payload(
        session=session,
        assessment_ids=[assessment_id],
        scan_ids=selected_scan_ids,
        customized_only=customized_only,
        customization_type=_normalize_customization_type(customization_type),
        table_names=_parse_csv_strings(app_file_classes),
        limit=limit,
        offset=offset,
    )
    payload["assessment_id"] = assessment_id
    return payload


@app.get("/api/scans/{scan_id}/results")
async def api_scan_results(
    scan_id: int,
    customized_only: bool = Query(default=True),
    customization_type: str = Query(default="all"),
    app_file_classes: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    """Query results scoped to a single scan."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    payload = _query_scan_results_payload(
        session=session,
        scan_ids=[scan_id],
        customized_only=customized_only,
        customization_type=_normalize_customization_type(customization_type),
        table_names=_parse_csv_strings(app_file_classes),
        limit=limit,
        offset=offset,
    )
    payload["scan_id"] = scan_id
    return payload


@app.get("/api/assessments/{assessment_id}/grouping-signals")
async def api_assessment_grouping_signals(
    assessment_id: int,
    session: Session = Depends(get_session),
):
    """Unified grouping-signal summary for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return _build_grouping_signals_payload(session, assessment_id=assessment_id)


@app.get("/api/scans/{scan_id}/grouping-signals")
async def api_scan_grouping_signals(
    scan_id: int,
    session: Session = Depends(get_session),
):
    """Unified grouping-signal summary for a single scan."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _build_grouping_signals_payload(
        session,
        assessment_id=scan.assessment_id,
        scan_id=scan_id,
    )


@app.get("/api/results/{result_id}/grouping-evidence")
async def api_result_grouping_evidence(
    result_id: int,
    session: Session = Depends(get_session),
):
    """Result-level evidence used for feature grouping decisions."""
    result = session.get(ScanResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    try:
        return _build_result_grouping_evidence_payload(session, result_id=result_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/assessments/{assessment_id}/feature-hierarchy")
async def api_assessment_feature_hierarchy(
    assessment_id: int,
    session: Session = Depends(get_session),
):
    """Assessment-scoped feature hierarchy with member/context split."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return _build_feature_hierarchy_payload(session, assessment_id=assessment_id)


@app.get("/api/scans/{scan_id}/feature-hierarchy")
async def api_scan_feature_hierarchy(
    scan_id: int,
    session: Session = Depends(get_session),
):
    """Scan-scoped subset of feature hierarchy with ungrouped bucket."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _build_feature_hierarchy_payload(
        session,
        assessment_id=scan.assessment_id,
        scan_id=scan_id,
    )


@app.get("/api/features/{feature_id}/recommendations")
async def api_feature_recommendations(
    feature_id: int,
    session: Session = Depends(get_session),
):
    """Get structured OOTB recommendations persisted for a feature."""
    feature = session.get(Feature, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    rows = session.exec(
        select(FeatureRecommendation)
        .where(FeatureRecommendation.feature_id == feature_id)
        .order_by(FeatureRecommendation.id.asc())
    ).all()
    return {
        "feature_id": feature_id,
        "assessment_id": feature.assessment_id,
        "recommendations": [_build_feature_recommendation_payload(row) for row in rows],
    }


@app.post("/api/features/{feature_id}/recommendations")
async def api_upsert_feature_recommendation(
    feature_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Create or update a structured feature recommendation row."""
    feature = session.get(Feature, feature_id)
    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    assessment = session.get(Assessment, feature.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    recommendation_id = payload.get("id")
    recommendation: Optional[FeatureRecommendation] = None
    if recommendation_id is not None:
        recommendation = session.get(FeatureRecommendation, int(recommendation_id))
        if not recommendation or recommendation.feature_id != feature_id:
            raise HTTPException(status_code=404, detail="Recommendation not found for feature")
    else:
        recommendation = FeatureRecommendation(
            instance_id=assessment.instance_id,
            assessment_id=assessment.id,
            feature_id=feature_id,
            recommendation_type="keep",
        )

    if "recommendation_type" in payload:
        recommendation.recommendation_type = str(payload.get("recommendation_type") or "").strip() or recommendation.recommendation_type
    if not str(recommendation.recommendation_type or "").strip():
        raise HTTPException(status_code=400, detail="recommendation_type is required")

    for field_name in (
        "ootb_capability_name",
        "product_name",
        "sku_or_license",
        "rationale",
    ):
        if field_name in payload:
            value = payload.get(field_name)
            setattr(recommendation, field_name, None if value is None else str(value))

    if "fit_confidence" in payload:
        raw = payload.get("fit_confidence")
        recommendation.fit_confidence = None if raw in (None, "") else float(raw)

    if "requires_plugins" in payload:
        raw_plugins = payload.get("requires_plugins")
        if raw_plugins is None:
            recommendation.requires_plugins_json = None
        elif isinstance(raw_plugins, str):
            recommendation.requires_plugins_json = raw_plugins
        else:
            recommendation.requires_plugins_json = json.dumps(raw_plugins, sort_keys=True)

    if "evidence" in payload:
        raw_evidence = payload.get("evidence")
        if raw_evidence is None:
            recommendation.evidence_json = None
        elif isinstance(raw_evidence, str):
            recommendation.evidence_json = raw_evidence
        else:
            recommendation.evidence_json = json.dumps(raw_evidence, sort_keys=True)

    recommendation.updated_at = datetime.utcnow()
    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)

    return {
        "success": True,
        "recommendation": _build_feature_recommendation_payload(recommendation),
    }


@app.get("/api/instances/{instance_id}/inventory")
async def api_instance_inventory(
    instance_id: int,
    session: Session = Depends(get_session)
):
    """API: Get inventory counts for an instance"""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    if instance.inventory_json:
        return {"success": True, "inventory": _safe_json(instance.inventory_json, {}), "cached": True}

    password = decrypt_password(instance.password_encrypted)
    client = ServiceNowClient(
        instance.url,
        instance.username,
        password,
        instance_id=instance.id,
    )

    try:
        inventory = client.scan_inventory(scope="global")
        instance.inventory_json = json.dumps(inventory)
        instance.metrics_last_refreshed_at = datetime.utcnow()
        session.add(instance)
        session.commit()
        return {"success": True, "inventory": inventory}
    except ServiceNowClientError as e:
        return {"success": False, "error": str(e)}


# ── Best Practice Admin API ──────────────────────────────────────────

def _best_practice_to_dict(bp: BestPractice) -> Dict[str, Any]:
    """Serialize a BestPractice row to a JSON-safe dict."""
    return {
        "id": bp.id,
        "code": bp.code,
        "title": bp.title,
        "category": bp.category.value if hasattr(bp.category, "value") else bp.category,
        "severity": bp.severity,
        "description": bp.description,
        "detection_hint": bp.detection_hint,
        "recommendation": bp.recommendation,
        "applies_to": bp.applies_to,
        "is_active": bp.is_active,
        "source_url": bp.source_url,
    }


@app.get("/api/best-practices")
async def api_list_best_practices(
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    session: Session = Depends(get_session),
):
    """List all best practice checks with optional filtering."""
    stmt = select(BestPractice).order_by(BestPractice.category, BestPractice.severity, BestPractice.code)
    if category:
        stmt = stmt.where(BestPractice.category == category)
    if is_active is not None:
        stmt = stmt.where(BestPractice.is_active == is_active)
    rows = session.exec(stmt).all()
    return {"best_practices": [_best_practice_to_dict(bp) for bp in rows]}


@app.post("/api/best-practices", status_code=201)
async def api_create_best_practice(
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    """Create a new best practice check."""
    bp = BestPractice(
        code=payload["code"],
        title=payload["title"],
        category=BestPracticeCategory(payload["category"]),
        severity=payload.get("severity", "medium"),
        description=payload.get("description"),
        detection_hint=payload.get("detection_hint"),
        recommendation=payload.get("recommendation"),
        applies_to=payload.get("applies_to"),
        is_active=payload.get("is_active", True),
        source_url=payload.get("source_url"),
    )
    session.add(bp)
    session.commit()
    session.refresh(bp)
    return _best_practice_to_dict(bp)


@app.put("/api/best-practices/{bp_id}")
async def api_update_best_practice(
    bp_id: int,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    """Update an existing best practice check."""
    bp = session.get(BestPractice, bp_id)
    if not bp:
        raise HTTPException(status_code=404, detail="Best practice not found")
    for key in ("title", "severity", "description", "detection_hint",
                "recommendation", "applies_to", "is_active", "source_url"):
        if key in payload:
            setattr(bp, key, payload[key])
    if "category" in payload:
        bp.category = BestPracticeCategory(payload["category"])
    bp.updated_at = datetime.utcnow()
    session.add(bp)
    session.commit()
    session.refresh(bp)
    return _best_practice_to_dict(bp)


@app.get("/admin/best-practices", response_class=HTMLResponse)
async def admin_best_practices_page(
    request: Request,
    session: Session = Depends(get_session),
):
    """Admin page for managing best practice checks."""
    categories = [c.value for c in BestPracticeCategory]
    return templates.TemplateResponse("admin_best_practices.html", {
        "request": request,
        "categories": categories,
    })
