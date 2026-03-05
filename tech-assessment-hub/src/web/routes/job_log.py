"""Unified job log routes.

Provides a single cross-module run log view with standardized fields,
including CSDM ingestion logs and preflight data pull runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlmodel import Session, select

from ...database import engine, get_session
from ...models import (
    DataPullStatus,
    DataPullType,
    Instance,
    InstanceDataPull,
    JobRun,
    JobRunStatus,
    Scan,
    ScanStatus,
)
from ...models_sn import SnIngestionState, SnJobLog
from ...services.dictionary_pull_orchestrator import cancel_dictionary_pull
from ...services.condition_query_builder import conditions_to_sql_where

job_log_router = APIRouter(tags=["job-log"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_ALLOWED_MODULES = {"all", "csdm", "preflight", "initial_data", "assessment", "postflight"}
_ALLOWED_PAGE_SIZES = (25, 50, 100, 200)
_ALLOWED_SORT_FIELDS = {
    "started_at",
    "source_label",
    "source_module",
    "instance_id",
    "instance_name",
    "instance_company",
    "instance_label",
    "target_name",
    "job_type",
    "status_text",
    "status_class",
    "rows_inserted",
    "rows_updated",
    "duration_seconds",
    "error_message",
    "completed_at",
    "sort_at",
}

_JOB_LOG_FIELDS = [
    {
        "local_column": "started_at",
        "column_label": "Started",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "source_label",
        "column_label": "Module",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_label",
        "column_label": "Instance",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "target_name",
        "column_label": "Target",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "job_type",
        "column_label": "Job Type",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "status_text",
        "column_label": "Status",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "rows_inserted",
        "column_label": "Rows/Items Processed",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "rows_updated",
        "column_label": "Rows Updated",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "duration_seconds",
        "column_label": "Duration (s)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "error_message",
        "column_label": "Error",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "source_module",
        "column_label": "Module Key",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_id",
        "column_label": "Instance ID",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_name",
        "column_label": "Instance Name",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_company",
        "column_label": "Company",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "completed_at",
        "column_label": "Completed",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
]

_UNIFIED_JOB_SOURCE_SQL = """
SELECT
    'csdm' AS source_module,
    'CSDM' AS source_label,
    l.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    l.sn_table_name AS target_name,
    l.job_type AS job_type,
    COALESCE(l.status, 'unknown') AS status_text,
    CASE
        WHEN lower(COALESCE(l.status, '')) IN ('success', 'completed') THEN 'completed'
        WHEN lower(COALESCE(l.status, '')) IN ('in_progress', 'running') THEN 'running'
        WHEN lower(COALESCE(l.status, '')) IN ('started', 'queued', 'pending') THEN 'pending'
        WHEN lower(COALESCE(l.status, '')) IN ('failed', 'error') THEN 'failed'
        WHEN lower(COALESCE(l.status, '')) IN ('cancelled', 'canceled') THEN 'cancelled'
        WHEN lower(COALESCE(l.status, '')) IN ('idle', 'never') THEN 'idle'
        ELSE 'unknown'
    END AS status_class,
    CAST(COALESCE(l.rows_inserted, 0) AS INTEGER) AS rows_inserted,
    CAST(COALESCE(l.rows_updated, 0) AS INTEGER) AS rows_updated,
    COALESCE(l.started_at, l.created_at) AS started_at,
    l.completed_at AS completed_at,
    CASE
        WHEN COALESCE(l.started_at, l.created_at) IS NULL THEN NULL
        WHEN l.completed_at IS NOT NULL THEN ROUND((julianday(l.completed_at) - julianday(COALESCE(l.started_at, l.created_at))) * 86400.0, 1)
        WHEN lower(COALESCE(l.status, '')) IN ('running', 'in_progress', 'started', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(l.started_at, l.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(l.error_message, '') AS error_message,
    'csdm_job_log' AS record_source,
    NULL AS run_uid,
    NULL AS assessment_id,
    COALESCE(l.completed_at, COALESCE(l.started_at, l.created_at), l.created_at) AS sort_at
FROM csdm_job_log l
JOIN instance i ON i.id = l.instance_id

UNION ALL

SELECT
    CASE WHEN COALESCE(p.source_context, '') = 'initial_data' THEN 'initial_data' ELSE 'preflight' END AS source_module,
    CASE WHEN COALESCE(p.source_context, '') = 'initial_data' THEN 'Initial Data' ELSE 'Preflight' END AS source_label,
    p.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    p.data_type AS target_name,
    COALESCE(p.sync_mode, 'data_pull') AS job_type,
    COALESCE(p.status, 'unknown') AS status_text,
    CASE
        WHEN lower(COALESCE(p.status, '')) IN ('success', 'completed') THEN 'completed'
        WHEN lower(COALESCE(p.status, '')) IN ('in_progress', 'running') THEN 'running'
        WHEN lower(COALESCE(p.status, '')) IN ('started', 'queued', 'pending') THEN 'pending'
        WHEN lower(COALESCE(p.status, '')) IN ('failed', 'error') THEN 'failed'
        WHEN lower(COALESCE(p.status, '')) IN ('cancelled', 'canceled') THEN 'cancelled'
        WHEN lower(COALESCE(p.status, '')) IN ('idle', 'never') THEN 'idle'
        ELSE 'unknown'
    END AS status_class,
    CAST(COALESCE(p.records_pulled, 0) AS INTEGER) AS rows_inserted,
    CAST(0 AS INTEGER) AS rows_updated,
    COALESCE(p.started_at, p.updated_at, p.created_at) AS started_at,
    p.completed_at AS completed_at,
    CASE
        WHEN COALESCE(p.started_at, p.updated_at, p.created_at) IS NULL THEN NULL
        WHEN p.completed_at IS NOT NULL THEN ROUND((julianday(p.completed_at) - julianday(COALESCE(p.started_at, p.updated_at, p.created_at))) * 86400.0, 1)
        WHEN lower(COALESCE(p.status, '')) IN ('running', 'in_progress', 'started', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(p.started_at, p.updated_at, p.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(p.error_message, '') AS error_message,
    'instance_data_pull' AS record_source,
    NULL AS run_uid,
    NULL AS assessment_id,
    COALESCE(p.completed_at, COALESCE(p.started_at, p.updated_at, p.created_at), p.updated_at, p.created_at) AS sort_at
FROM instance_data_pull p
JOIN instance i ON i.id = p.instance_id
WHERE (
    p.status != 'idle'
    OR p.started_at IS NOT NULL
    OR p.completed_at IS NOT NULL
    OR p.last_pulled_at IS NOT NULL
    OR COALESCE(p.records_pulled, 0) > 0
    OR p.error_message IS NOT NULL
)

UNION ALL

SELECT
    CASE
        WHEN json_extract(r.metadata_json, '$.source') = 'initial_data' THEN 'initial_data'
        ELSE 'preflight'
    END AS source_module,
    CASE
        WHEN json_extract(r.metadata_json, '$.source') = 'initial_data' THEN 'Initial Data'
        ELSE 'Preflight'
    END AS source_label,
    r.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    'sys_dictionary' AS target_name,
    COALESCE(r.mode, 'full') AS job_type,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'unknown'
    END AS status_text,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'unknown'
    END AS status_class,
    CAST(COALESCE(r.queue_completed, 0) AS INTEGER) AS rows_inserted,
    CAST(0 AS INTEGER) AS rows_updated,
    COALESCE(r.started_at, r.created_at) AS started_at,
    r.completed_at AS completed_at,
    CASE
        WHEN COALESCE(r.started_at, r.created_at) IS NULL THEN NULL
        WHEN r.completed_at IS NOT NULL THEN ROUND((julianday(r.completed_at) - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        WHEN r.status IN ('running', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(r.error_message, '') AS error_message,
    'job_run_dict' AS record_source,
    r.run_uid AS run_uid,
    NULL AS assessment_id,
    COALESCE(r.completed_at, COALESCE(r.started_at, r.created_at), r.created_at) AS sort_at
FROM job_run r
JOIN instance i ON i.id = r.instance_id
WHERE r.job_type = 'dict_pull'

UNION ALL

SELECT
    'assessment' AS source_module,
    'Assessment' AS source_label,
    r.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    'ASMT ' || COALESCE(json_extract(r.metadata_json, '$.assessment_id'), '') AS target_name,
    COALESCE(r.mode, 'scan_workflow') AS job_type,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'unknown'
    END AS status_text,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'unknown'
    END AS status_class,
    CAST(COALESCE(r.queue_completed, 0) AS INTEGER) AS rows_inserted,
    CAST(0 AS INTEGER) AS rows_updated,
    COALESCE(r.started_at, r.created_at) AS started_at,
    r.completed_at AS completed_at,
    CASE
        WHEN COALESCE(r.started_at, r.created_at) IS NULL THEN NULL
        WHEN r.completed_at IS NOT NULL THEN ROUND((julianday(r.completed_at) - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        WHEN r.status IN ('running', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(r.error_message, '') AS error_message,
    'job_run_assessment' AS record_source,
    r.run_uid AS run_uid,
    CAST(COALESCE(json_extract(r.metadata_json, '$.assessment_id'), 0) AS INTEGER) AS assessment_id,
    COALESCE(r.completed_at, COALESCE(r.started_at, r.created_at), r.created_at) AS sort_at
FROM job_run r
JOIN instance i ON i.id = r.instance_id
WHERE r.module = 'assessment' AND r.job_type = 'assessment_scan'

UNION ALL

SELECT
    'postflight' AS source_module,
    'Post Flight' AS source_label,
    r.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    COALESCE(r.current_data_type, 'artifact_details') AS target_name,
    COALESCE(r.mode, 'artifact_pull') AS job_type,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'unknown'
    END AS status_text,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'unknown'
    END AS status_class,
    CAST(COALESCE(r.queue_completed, 0) AS INTEGER) AS rows_inserted,
    CAST(0 AS INTEGER) AS rows_updated,
    COALESCE(r.started_at, r.created_at) AS started_at,
    r.completed_at AS completed_at,
    CASE
        WHEN COALESCE(r.started_at, r.created_at) IS NULL THEN NULL
        WHEN r.completed_at IS NOT NULL THEN ROUND((julianday(r.completed_at) - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        WHEN r.status IN ('running', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(r.error_message, '') AS error_message,
    'job_run_postflight' AS record_source,
    r.run_uid AS run_uid,
    CAST(COALESCE(json_extract(r.metadata_json, '$.assessment_id'), 0) AS INTEGER) AS assessment_id,
    COALESCE(r.completed_at, COALESCE(r.started_at, r.created_at), r.created_at) AS sort_at
FROM job_run r
JOIN instance i ON i.id = r.instance_id
WHERE r.module = 'postflight' AND r.job_type = 'artifact_pull'
"""


def _normalize_module(module: str) -> str:
    normalized = (module or "all").strip().lower()
    if normalized not in _ALLOWED_MODULES:
        raise HTTPException(status_code=400, detail="Invalid module filter")
    return normalized


def _coerce_page_size(limit: int) -> int:
    if limit in _ALLOWED_PAGE_SIZES:
        return limit
    for candidate in reversed(_ALLOWED_PAGE_SIZES):
        if limit >= candidate:
            return candidate
    return 50


def _bind_positional(sql: str, values: list[Any], params: Dict[str, Any], prefix: str) -> str:
    bound_sql = sql
    for idx, value in enumerate(values):
        key = f"{prefix}_{idx}"
        bound_sql = bound_sql.replace("?", f":{key}", 1)
        params[key] = value
    return bound_sql


def _initial_condition_tree(module: str, instance_id: Optional[int]) -> Optional[Dict[str, Any]]:
    conditions: list[Dict[str, Any]] = []

    if module in {"csdm", "preflight", "initial_data", "assessment", "postflight"}:
        conditions.append(
            {
                "field": "source_module",
                "operator": "is",
                "value": module,
            }
        )

    if instance_id is not None:
        conditions.append(
            {
                "field": "instance_id",
                "operator": "equals",
                "value": str(instance_id),
            }
        )

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"logic": "AND", "conditions": conditions}


_ACTIVE_STATUS_CLASSES = {"running", "pending"}
_TERMINAL_STATUS_CLASSES = {"completed", "failed", "cancelled", "idle", "unknown"}
_CSDM_ACTIVE_STATUSES = {"queued", "in_progress", "started", "running", "pending"}
_TERMINAL_JOB_RUN_STATUSES = {
    JobRunStatus.completed,
    JobRunStatus.failed,
    JobRunStatus.cancelled,
}
_TERMINAL_PULL_STATUSES = {
    DataPullStatus.completed,
    DataPullStatus.failed,
    DataPullStatus.cancelled,
}


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_cancellable_row(record_source: str, status_class: str, status_text: str = "") -> bool:
    normalized_class = (status_class or "").strip().lower()
    normalized_text = (status_text or "").strip().lower()

    # Defensive gate: terminal/unknown statuses should never offer cancel actions,
    # even if upstream mapping is stale or inconsistent.
    if normalized_class in _TERMINAL_STATUS_CLASSES:
        return False
    if any(token in normalized_text for token in ("failed", "error", "completed", "cancelled", "canceled", "idle")):
        return False

    if normalized_class not in _ACTIVE_STATUS_CLASSES:
        return False
    return record_source in {
        "csdm_job_log",
        "instance_data_pull",
        "job_run_dict",
        "job_run_assessment",
        "job_run_postflight",
    }


def _cancel_data_pull_entry(session: Session, *, instance_id: int, target_name: str) -> bool:
    now = datetime.utcnow()
    try:
        data_type = DataPullType(target_name)
    except ValueError:
        return False

    pull = session.exec(
        select(InstanceDataPull)
        .where(InstanceDataPull.instance_id == instance_id)
        .where(InstanceDataPull.data_type == data_type)
    ).first()
    if not pull:
        return False
    if pull.status in _TERMINAL_PULL_STATUSES:
        return False

    pull.cancel_requested = pull.status == DataPullStatus.running
    pull.cancel_requested_at = now if pull.cancel_requested else None
    pull.status = DataPullStatus.cancelled
    pull.completed_at = now
    pull.error_message = "Cancelled by user"
    pull.updated_at = now
    session.add(pull)
    session.commit()
    return True


def _cancel_csdm_entry(session: Session, *, instance_id: int, target_name: str) -> bool:
    now = datetime.utcnow()
    changed = False

    try:
        from . import csdm as csdm_routes

        with csdm_routes._CSDM_JOBS_LOCK:
            job = csdm_routes._CSDM_JOBS.get(instance_id)
            if job:
                job.cancel_event.set()
                changed = True
    except Exception:
        pass

    states_stmt = select(SnIngestionState).where(SnIngestionState.instance_id == instance_id)
    if target_name:
        states_stmt = states_stmt.where(SnIngestionState.sn_table_name == target_name)
    states_stmt = states_stmt.where(SnIngestionState.last_run_status.in_(list(_CSDM_ACTIVE_STATUSES)))
    states = session.exec(states_stmt).all()
    for state in states:
        state.last_run_status = "cancelled"
        state.last_run_completed_at = now
        state.last_error = "Cancelled by user"
        state.updated_at = now
        session.add(state)
        changed = True

    logs_stmt = select(SnJobLog).where(SnJobLog.instance_id == instance_id)
    if target_name:
        logs_stmt = logs_stmt.where(SnJobLog.sn_table_name == target_name)
    logs_stmt = logs_stmt.where(SnJobLog.status.in_(list(_CSDM_ACTIVE_STATUSES)))
    logs = session.exec(logs_stmt).all()
    for log in logs:
        log.status = "cancelled"
        log.completed_at = log.completed_at or now
        if not log.error_message:
            log.error_message = "Cancelled by user"
        session.add(log)
        changed = True

    if changed:
        session.commit()
    return changed


def _extract_assessment_id_from_run(run: Optional[JobRun]) -> Optional[int]:
    if not run or not run.metadata_json:
        return None
    try:
        payload = json.loads(run.metadata_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return _safe_int(payload.get("assessment_id"))


def _request_cancel_assessment_scans(session: Session, assessment_id: int) -> bool:
    now = datetime.utcnow()
    changed = False
    scans = session.exec(select(Scan).where(Scan.assessment_id == assessment_id)).all()
    for scan in scans:
        if scan.status == ScanStatus.running:
            if not scan.cancel_requested:
                scan.cancel_requested = True
                scan.cancel_requested_at = now
                session.add(scan)
                changed = True
            continue
        if scan.status == ScanStatus.pending:
            scan.cancel_requested = True
            scan.cancel_requested_at = now
            scan.status = ScanStatus.cancelled
            scan.completed_at = now
            scan.error_message = "Cancelled by user"
            session.add(scan)
            changed = True
    return changed


def _cancel_assessment_entry(
    session: Session,
    *,
    instance_id: Optional[int],
    run_uid: Optional[str],
    assessment_id: Optional[int],
) -> bool:
    now = datetime.utcnow()
    changed = False

    if assessment_id:
        changed = _request_cancel_assessment_scans(session, assessment_id) or changed

    if instance_id is not None:
        active_pulls = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.status == DataPullStatus.running)
        ).all()
        for pull in active_pulls:
            pull.cancel_requested = True
            pull.cancel_requested_at = now
            pull.status = DataPullStatus.cancelled
            pull.completed_at = now
            pull.error_message = "Cancelled by user"
            pull.updated_at = now
            session.add(pull)
            changed = True

    run: Optional[JobRun] = None
    if run_uid:
        run = session.exec(select(JobRun).where(JobRun.run_uid == run_uid)).first()
    if not run and assessment_id:
        candidate_runs = session.exec(
            select(JobRun)
            .where(JobRun.module == "assessment")
            .where(JobRun.job_type == "assessment_scan")
            .where(JobRun.status.in_([JobRunStatus.queued, JobRunStatus.running]))
            .order_by(JobRun.created_at.desc())
            .limit(100)
        ).all()
        run = next((item for item in candidate_runs if _extract_assessment_id_from_run(item) == assessment_id), None)

    if run and run.status not in _TERMINAL_JOB_RUN_STATUSES:
        run.status = JobRunStatus.cancelled
        run.completed_at = now
        run.message = "Assessment scan workflow cancelled."
        run.error_message = "Cancelled by user"
        run.updated_at = now
        run.last_heartbeat_at = now
        session.add(run)
        changed = True

    if changed:
        session.commit()
    return changed


def _cancel_dictionary_entry(session: Session, *, instance_id: int, run_uid: Optional[str]) -> bool:
    now = datetime.utcnow()
    changed = cancel_dictionary_pull(instance_id)

    run: Optional[JobRun] = None
    if run_uid:
        run = session.exec(select(JobRun).where(JobRun.run_uid == run_uid)).first()
    if not run:
        run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.job_type == "dict_pull")
            .where(JobRun.status.in_([JobRunStatus.queued, JobRunStatus.running]))
            .order_by(JobRun.created_at.desc())
        ).first()

    if run and run.status not in _TERMINAL_JOB_RUN_STATUSES:
        run.status = JobRunStatus.cancelled
        run.completed_at = now
        run.message = "Dictionary pull cancelled."
        run.error_message = "Cancelled by user"
        run.updated_at = now
        run.last_heartbeat_at = now
        session.add(run)
        changed = True

    if changed:
        session.commit()
    return changed


def _cancel_postflight_entry(
    session: Session,
    *,
    run_uid: Optional[str],
    assessment_id: Optional[int],
) -> bool:
    now = datetime.utcnow()
    changed = False

    if assessment_id:
        changed = _request_cancel_assessment_scans(session, assessment_id) or changed

    if run_uid:
        run = session.exec(select(JobRun).where(JobRun.run_uid == run_uid)).first()
        if run and run.status not in _TERMINAL_JOB_RUN_STATUSES:
            run.status = JobRunStatus.cancelled
            run.completed_at = now
            run.message = "Postflight pull cancelled."
            run.error_message = "Cancelled by user"
            run.updated_at = now
            run.last_heartbeat_at = now
            session.add(run)
            changed = True

    if changed:
        session.commit()
    return changed


def _cancel_job_entry(session: Session, payload: Dict[str, Any]) -> bool:
    record_source = str(payload.get("record_source") or "").strip()
    instance_id = _safe_int(payload.get("instance_id"))
    target_name = str(payload.get("target_name") or "").strip()
    run_uid = str(payload.get("run_uid") or "").strip() or None
    assessment_id = _safe_int(payload.get("assessment_id"))

    if record_source == "instance_data_pull":
        if instance_id is None or not target_name:
            raise ValueError("instance_data_pull cancel requires instance_id and target_name")
        return _cancel_data_pull_entry(session, instance_id=instance_id, target_name=target_name)
    if record_source == "csdm_job_log":
        if instance_id is None:
            raise ValueError("csdm_job_log cancel requires instance_id")
        return _cancel_csdm_entry(session, instance_id=instance_id, target_name=target_name)
    if record_source == "job_run_dict":
        if instance_id is None:
            raise ValueError("job_run_dict cancel requires instance_id")
        return _cancel_dictionary_entry(session, instance_id=instance_id, run_uid=run_uid)
    if record_source == "job_run_assessment":
        return _cancel_assessment_entry(
            session,
            instance_id=instance_id,
            run_uid=run_uid,
            assessment_id=assessment_id,
        )
    if record_source == "job_run_postflight":
        return _cancel_postflight_entry(session, run_uid=run_uid, assessment_id=assessment_id)
    raise ValueError("Unsupported job record source")


def _row_to_json(row: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    for key in ("started_at", "completed_at", "sort_at"):
        value = data.get(key)
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    data["assessment_id"] = _safe_int(data.get("assessment_id"))
    status_class = str(data.get("status_class") or "").strip().lower()
    status_text = str(data.get("status_text") or "")
    record_source = str(data.get("record_source") or "").strip()
    can_cancel = _is_cancellable_row(record_source, status_class, status_text)
    data["can_cancel"] = can_cancel
    return data


@job_log_router.get("/job-log", response_class=HTMLResponse)
async def unified_job_log_page(
    request: Request,
    instance_id: Optional[int] = Query(default=None),
    module: str = Query(default="all"),
    limit: int = Query(default=200, ge=20, le=1000),
    session: Session = Depends(get_session),
):
    """Unified job log page across CSDM + preflight modules."""
    normalized_module = _normalize_module(module)

    instances = session.exec(select(Instance).order_by(Instance.name)).all()

    if instance_id is not None:
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

    return templates.TemplateResponse(
        "job_log.html",
        {
            "request": request,
            "instances": instances,
            "selected_instance_id": instance_id,
            "selected_module": normalized_module,
            "selected_limit": limit,
            "initial_page_size": _coerce_page_size(limit),
            "initial_conditions": _initial_condition_tree(normalized_module, instance_id),
        },
    )


@job_log_router.get("/api/job-log/field-schema")
async def api_job_log_field_schema():
    """Static schema metadata for the unified job log DataTable."""
    return {
        "sn_table_name": "job_log",
        "local_table_name": "job_log",
        "sn_table_label": "Unified Job Log",
        "source": "system",
        "field_count": len(_JOB_LOG_FIELDS),
        "fields": _JOB_LOG_FIELDS,
        "available_tables": [],
    }


@job_log_router.post("/api/job-log/cancel")
async def api_job_log_cancel(
    request: Request,
    session: Session = Depends(get_session),
):
    """Cancel a single active unified job-log row."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be an object")

    status_class = str(payload.get("status_class") or "").strip().lower()
    status_text = str(payload.get("status_text") or "")
    record_source = str(payload.get("record_source") or "").strip()
    if not _is_cancellable_row(record_source, status_class, status_text):
        return JSONResponse(content={"success": True, "cancelled": False, "reason": "not_cancellable"})

    try:
        cancelled = _cancel_job_entry(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return JSONResponse(content={"success": True, "cancelled": bool(cancelled)})


@job_log_router.post("/api/job-log/cancel-all-active")
async def api_job_log_cancel_all_active(
    module: str = Query("all"),
    instance_id: Optional[int] = Query(default=None),
    conditions: Optional[str] = Query(None, description="JSON condition tree"),
    session: Session = Depends(get_session),
):
    """Cancel all active (running/pending) jobs matching current filters."""
    normalized_module = _normalize_module(module)
    where_parts: list[str] = ['j."status_class" IN (\'running\', \'pending\')']
    params: Dict[str, Any] = {}

    if normalized_module in {"csdm", "preflight", "initial_data", "assessment", "postflight"}:
        where_parts.append('j."source_module" = :_module')
        params["_module"] = normalized_module

    if instance_id is not None:
        where_parts.append('j."instance_id" = :_instance_id')
        params["_instance_id"] = instance_id

    if conditions:
        try:
            parsed = json.loads(conditions)
            if parsed:
                cond_sql, cond_params = conditions_to_sql_where(parsed, table_alias="j")
                if cond_sql and cond_sql != "1=1":
                    bound_cond_sql = _bind_positional(cond_sql, cond_params, params, "_cond")
                    where_parts.append(bound_cond_sql)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid conditions: {exc}")

    where_clause = " AND ".join(f"({part})" for part in where_parts)
    select_sql = (
        f"WITH unified AS ({_UNIFIED_JOB_SOURCE_SQL}) "
        f"SELECT j.\"record_source\", j.\"instance_id\", j.\"target_name\", j.\"run_uid\", "
        f"j.\"assessment_id\", j.\"status_class\" "
        f"FROM unified AS j WHERE {where_clause}"
    )
    with engine.connect() as conn:
        result = conn.execute(text(select_sql), params)
        rows = [dict(row) for row in result.mappings().all()]

    cancelled_count = 0
    attempted_count = 0
    dedupe: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (
            row.get("record_source"),
            row.get("instance_id"),
            row.get("target_name"),
            row.get("run_uid"),
            row.get("assessment_id"),
        )
        if key in dedupe:
            continue
        dedupe.add(key)
        attempted_count += 1
        if _cancel_job_entry(session, row):
            cancelled_count += 1

    return JSONResponse(
        content={
            "success": True,
            "attempted": attempted_count,
            "cancelled": cancelled_count,
        }
    )


@job_log_router.get("/api/job-log/records")
async def api_job_log_records(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort_field: Optional[str] = Query(None),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    conditions: Optional[str] = Query(None, description="JSON condition tree"),
    module: str = Query("all"),
    instance_id: Optional[int] = Query(default=None),
):
    """Return paged unified job log rows for the reusable DataTable component."""
    normalized_module = _normalize_module(module)

    where_parts: list[str] = []
    params: Dict[str, Any] = {}

    if normalized_module in {"csdm", "preflight", "initial_data", "assessment", "postflight"}:
        where_parts.append('j."source_module" = :_module')
        params["_module"] = normalized_module

    if instance_id is not None:
        where_parts.append('j."instance_id" = :_instance_id')
        params["_instance_id"] = instance_id

    if conditions:
        try:
            parsed = json.loads(conditions)
            if parsed:
                cond_sql, cond_params = conditions_to_sql_where(parsed, table_alias="j")
                if cond_sql and cond_sql != "1=1":
                    bound_cond_sql = _bind_positional(cond_sql, cond_params, params, "_cond")
                    where_parts.append(bound_cond_sql)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid conditions: {exc}")

    where_clause = " AND ".join(f"({part})" for part in where_parts) if where_parts else "1=1"

    if sort_field and sort_field in _ALLOWED_SORT_FIELDS:
        direction = "DESC" if sort_dir == "desc" else "ASC"
        order_clause = f'j."{sort_field}" {direction}'
    else:
        order_clause = 'j."sort_at" DESC'

    base_sql = f"WITH unified AS ({_UNIFIED_JOB_SOURCE_SQL})"
    count_sql = f"{base_sql} SELECT COUNT(*) FROM unified AS j WHERE {where_clause}"

    selected_columns = [field["local_column"] for field in _JOB_LOG_FIELDS] + [
        "record_source",
        "run_uid",
        "assessment_id",
        "status_class",
        "sort_at",
    ]
    select_list = ", ".join(f'j."{col}"' for col in selected_columns)
    data_sql = (
        f"{base_sql} "
        f"SELECT {select_list} FROM unified AS j "
        f"WHERE {where_clause} "
        f"ORDER BY {order_clause} "
        f"LIMIT :_limit OFFSET :_offset"
    )

    query_params = dict(params)
    query_params["_limit"] = limit
    query_params["_offset"] = offset

    with engine.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        result = conn.execute(text(data_sql), query_params)
        rows = [_row_to_json(dict(row)) for row in result.mappings().all()]

    return {
        "sn_table_name": "job_log",
        "local_table_name": "job_log",
        "columns": _JOB_LOG_FIELDS,
        "rows": rows,
        "total": int(total),
        "offset": offset,
        "limit": limit,
    }
