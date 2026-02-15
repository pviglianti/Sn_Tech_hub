"""CSDM Data Ingestion -- API Routes.

Provides web UI pages and JSON API endpoints for managing
CSDM table ingestion from ServiceNow instances.
"""

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import text
from pydantic import BaseModel
from sqlmodel import Session, select

from ...database import get_session, engine
from ...models import Instance, JobRun, JobEvent, JobRunStatus
from ...models_sn import (
    SnTableRegistry,
    SnIngestionState,
    SnJobLog,
    SnCustomTableRequest,
)
from ...csdm_table_catalog import (
    CSDM_TABLE_GROUPS,
    get_local_table_name,
    get_table_group,
    get_table_label,
    get_all_table_names,
)

logger = logging.getLogger(__name__)

_CSDM_RUN_MODULE = "csdm"
_CSDM_RUN_TYPE = "csdm_ingest"
_ACTIVE_RUN_STATUSES = [JobRunStatus.queued, JobRunStatus.running]


def _json_dumps(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if payload is None:
        return None
    try:
        return json.dumps(payload, sort_keys=True)
    except Exception:
        return None


def _json_loads_dict(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_string_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _append_csdm_run_event(
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
    run.updated_at = now
    run.last_heartbeat_at = now
    session.add(run)
    session.add(event)


def _load_csdm_run(session: Session, run_uid: str) -> Optional[JobRun]:
    return session.exec(select(JobRun).where(JobRun.run_uid == run_uid)).first()


def _create_csdm_run_record(instance_id: int, tables: List[str], mode: str) -> str:
    run_uid = uuid.uuid4().hex
    now = datetime.utcnow()
    with Session(engine) as session:
        run = JobRun(
            run_uid=run_uid,
            instance_id=instance_id,
            module=_CSDM_RUN_MODULE,
            job_type=_CSDM_RUN_TYPE,
            mode=mode,
            status=JobRunStatus.queued,
            queue_total=len(tables),
            queue_completed=0,
            progress_pct=0,
            message=f"Queued CSDM ingestion for {len(tables)} table(s).",
            requested_data_types_json=_json_dumps(list(tables)),
            metadata_json=_json_dumps({"completed_tables": [], "failed_tables": []}),
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_csdm_run_event(
            session,
            run,
            event_type="queued",
            summary="CSDM ingestion queued.",
            payload={"tables": tables, "mode": mode},
        )
        session.commit()
    return run_uid


def _mark_csdm_run_running(session: Session, run_uid: str) -> None:
    run = _load_csdm_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = JobRunStatus.running
    run.started_at = now
    run.completed_at = None
    run.current_index = 1 if (run.queue_total or 0) > 0 else None
    run.current_data_type = None
    run.progress_pct = 0
    run.error_message = None
    run.message = "Starting CSDM ingestion..."
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_csdm_run_event(
        session,
        run,
        event_type="started",
        summary="CSDM ingestion started.",
        payload={"queue_total": run.queue_total},
    )
    session.commit()


def _mark_csdm_run_table_started(
    session: Session,
    run_uid: str,
    sn_table_name: str,
    *,
    index: int,
    total: int,
) -> None:
    run = _load_csdm_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = JobRunStatus.running
    run.current_data_type = sn_table_name
    run.current_index = index
    run.queue_total = max(int(run.queue_total or 0), total)
    run.progress_pct = int(round((float(run.queue_completed or 0) / float(max(total, 1))) * 100))
    run.message = f"Ingesting {index} of {total}: {sn_table_name}"
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_csdm_run_event(
        session,
        run,
        event_type="item_started",
        summary=f"Started {sn_table_name}.",
        payload={"sn_table_name": sn_table_name, "index": index, "total": total},
    )
    session.commit()


def _mark_csdm_run_table_completed(
    session: Session,
    run_uid: str,
    sn_table_name: str,
    *,
    status: str,
    index: int,
    total: int,
    rows_inserted: int = 0,
    rows_updated: int = 0,
    error_message: Optional[str] = None,
) -> None:
    run = _load_csdm_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.queue_total = max(int(run.queue_total or 0), total)
    run.queue_completed = max(int(run.queue_completed or 0), index)
    run.current_data_type = None
    run.current_index = None
    run.progress_pct = int(round((float(run.queue_completed) / float(max(run.queue_total, 1))) * 100))
    run.message = f"{sn_table_name}: {status}"
    run.updated_at = now
    run.last_heartbeat_at = now

    metadata = _json_loads_dict(run.metadata_json)
    completed_tables = list(metadata.get("completed_tables") or [])
    failed_tables = list(metadata.get("failed_tables") or [])
    if status == "completed":
        if sn_table_name not in completed_tables:
            completed_tables.append(sn_table_name)
    else:
        if sn_table_name not in failed_tables:
            failed_tables.append(sn_table_name)
    metadata["completed_tables"] = completed_tables
    metadata["failed_tables"] = failed_tables
    run.metadata_json = _json_dumps(metadata)
    if error_message:
        run.error_message = error_message

    _append_csdm_run_event(
        session,
        run,
        event_type="item_completed",
        summary=f"Finished {sn_table_name} ({status}).",
        payload={
            "sn_table_name": sn_table_name,
            "status": status,
            "index": index,
            "total": total,
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
            "error_message": error_message,
        },
    )
    session.commit()


def _mark_csdm_run_finished(
    session: Session,
    run_uid: str,
    *,
    status: JobRunStatus,
    message: str,
    error_message: Optional[str] = None,
) -> None:
    run = _load_csdm_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = status
    run.completed_at = now
    run.current_data_type = None
    run.current_index = None
    run.progress_pct = 100 if int(run.queue_total or 0) > 0 else 0
    run.message = message
    run.error_message = error_message
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_csdm_run_event(
        session,
        run,
        event_type=status.value,
        summary=message,
        payload={"queue_completed": run.queue_completed, "queue_total": run.queue_total},
    )
    session.commit()

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
csdm_router = APIRouter(prefix="/csdm", tags=["csdm"])

# Templates -- same directory as the main app uses (src/web/templates)
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Request body models
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    instance_id: int
    tables: List[str]
    mode: str = "delta"


class CustomTableRequest(BaseModel):
    instance_id: int
    sn_table_name: str


class SchemaRefreshRequest(BaseModel):
    instance_id: int
    sn_table_name: str


# ---------------------------------------------------------------------------
# In-process job tracking (mirrors server.py _DataPullJob pattern)
# ---------------------------------------------------------------------------
@dataclass
class _CsdmIngestionJob:
    """In-process coordinator for CSDM ingestion threads."""
    instance_id: int
    run_uid: str
    tables: List[str]
    mode: str
    cancel_event: threading.Event
    thread: Optional[threading.Thread]
    started_at: datetime
    completed_tables: List[str] = field(default_factory=list)
    failed_tables: List[str] = field(default_factory=list)
    current_table: Optional[str] = None
    status: str = "running"  # running, completed, failed, cancelled


_CSDM_JOBS_LOCK = threading.Lock()
_CSDM_JOBS: Dict[int, _CsdmIngestionJob] = {}


# ---------------------------------------------------------------------------
# Background thread runner
# ---------------------------------------------------------------------------

def _run_ingestion_thread(
    instance_id: int,
    tables: List[str],
    mode: str,
    cancel_event: threading.Event,
    run_uid: str,
) -> None:
    """Background thread that processes the ingestion queue table-by-table.

    All DB state management (SnIngestionState, SnJobLog, SnTableRegistry)
    is handled inside ``ingest_table()`` — this wrapper only tracks the
    in-memory ``_CsdmIngestionJob`` for the status-polling endpoint.
    """
    try:
        from ...services.csdm_ingestion import ingest_table  # type: ignore[import]
    except ImportError:
        with _CSDM_JOBS_LOCK:
            job = _CSDM_JOBS.get(instance_id)
            if job:
                job.status = "failed"
                job.failed_tables = list(tables)
        with Session(engine) as session:
            _mark_csdm_run_finished(
                session,
                run_uid,
                status=JobRunStatus.failed,
                message="CSDM ingestion service unavailable.",
                error_message="csdm_ingestion service not available",
            )
        logger.error(
            "csdm_ingestion service not available yet -- cannot run ingestion for instance %s",
            instance_id,
        )
        return

    with _CSDM_JOBS_LOCK:
        job = _CSDM_JOBS.get(instance_id)
        if not job:
            with Session(engine) as session:
                _mark_csdm_run_finished(
                    session,
                    run_uid,
                    status=JobRunStatus.failed,
                    message="CSDM ingestion worker lost in-memory coordinator.",
                    error_message="CSDM ingestion worker lost in-memory coordinator.",
                )
            return

    with Session(engine) as session:
        _mark_csdm_run_running(session, run_uid)

    had_failures = False

    for idx, tbl in enumerate(tables, start=1):
        if cancel_event.is_set():
            with _CSDM_JOBS_LOCK:
                job.status = "cancelled"
            break

        with _CSDM_JOBS_LOCK:
            job.current_table = tbl
        with Session(engine) as session:
            _mark_csdm_run_table_started(
                session,
                run_uid,
                tbl,
                index=idx,
                total=len(tables),
            )

        table_status = "failed"
        table_error: Optional[str] = None
        rows_inserted = 0
        rows_updated = 0
        try:
            # ingest_table handles all DB state (SnIngestionState,
            # SnJobLog, SnTableRegistry row_count).
            job_log = ingest_table(
                instance_id, tbl, mode, cancel_event=cancel_event,
            )
            rows_inserted = int(job_log.rows_inserted or 0) if job_log else 0
            rows_updated = int(job_log.rows_updated or 0) if job_log else 0
            table_status = str(job_log.status or "failed") if job_log else "failed"
            with _CSDM_JOBS_LOCK:
                if table_status == "completed":
                    job.completed_tables.append(tbl)
                elif table_status == "cancelled":
                    job.status = "cancelled"
                    break
                else:
                    had_failures = True
                    job.failed_tables.append(tbl)

        except Exception as exc:
            logger.exception("Ingestion failed for %s on instance %s", tbl, instance_id)
            table_status = "failed"
            table_error = str(exc)
            had_failures = True
            with _CSDM_JOBS_LOCK:
                job.failed_tables.append(tbl)
        finally:
            with Session(engine) as session:
                _mark_csdm_run_table_completed(
                    session,
                    run_uid,
                    tbl,
                    status=table_status,
                    index=idx,
                    total=len(tables),
                    rows_inserted=rows_inserted,
                    rows_updated=rows_updated,
                    error_message=table_error,
                )

    # Final status
    final_status: JobRunStatus
    final_message: str
    final_error: Optional[str]
    with _CSDM_JOBS_LOCK:
        if job.status == "running":
            job.status = "failed" if had_failures else "completed"
        job.current_table = None
        if job.status == "cancelled":
            final_status = JobRunStatus.cancelled
            final_message = "CSDM ingestion cancelled."
            final_error = "Cancelled by user."
        elif job.status == "completed":
            final_status = JobRunStatus.completed
            final_message = "CSDM ingestion completed."
            final_error = None
        else:
            final_status = JobRunStatus.failed
            final_message = "CSDM ingestion completed with failures."
            final_error = "One or more tables failed."

    with Session(engine) as session:
        _mark_csdm_run_finished(
            session,
            run_uid,
            status=final_status,
            message=final_message,
            error_message=final_error,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_table_states(
    instance_id: int, session: Session
) -> Dict[str, Dict[str, Any]]:
    """Build a dict of sn_table_name -> state info for the template.

    Row count is sourced from SnIngestionState.total_rows_in_db (set by
    the ingestion engine's _finalize_job).  As a fallback, the registry's
    row_count is used if the state value is 0/None.
    """
    states: Dict[str, Dict[str, Any]] = {}

    # Build a lookup from registry for row counts.
    registry_rows = session.exec(
        select(SnTableRegistry).where(
            SnTableRegistry.instance_id == instance_id
        )
    ).all()
    registry_counts = {r.sn_table_name: r.row_count for r in registry_rows}

    ingestion_rows = session.exec(
        select(SnIngestionState).where(
            SnIngestionState.instance_id == instance_id
        )
    ).all()

    # Normalize engine statuses to UI-friendly values.
    _STATUS_MAP = {"completed": "success", "started": "in_progress"}

    for s in ingestion_rows:
        row_count = s.total_rows_in_db or registry_counts.get(s.sn_table_name, 0)
        raw_status = s.last_run_status or "never"
        last_run = s.last_run_completed_at or s.last_run_started_at
        states[s.sn_table_name] = {
            "status": _STATUS_MAP.get(raw_status, raw_status),
            "total_rows": row_count,
            "remote_count": s.last_remote_count or 0,
            "last_run_at": last_run.isoformat() if last_run else None,
            "last_error": s.last_error,
            "last_batch_inserted": s.last_batch_inserted or 0,
            "last_batch_updated": s.last_batch_updated or 0,
        }

    return states


def _get_job_snapshot(instance_id: int) -> Optional[Dict[str, Any]]:
    """Return current job snapshot, falling back to durable run state."""
    with _CSDM_JOBS_LOCK:
        job = _CSDM_JOBS.get(instance_id)
        if job:
            is_alive = bool(job.thread and job.thread.is_alive())
            if not is_alive and job.status == "running":
                job.status = "failed"
            return {
                "instance_id": job.instance_id,
                "run_uid": job.run_uid,
                "tables": job.tables,
                "mode": job.mode,
                "status": job.status,
                "current_table": job.current_table,
                "completed_tables": list(job.completed_tables),
                "failed_tables": list(job.failed_tables),
                "started_at": job.started_at.isoformat(),
                "is_alive": is_alive,
            }

    with Session(engine) as session:
        active_run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == _CSDM_RUN_MODULE)
            .where(JobRun.job_type == _CSDM_RUN_TYPE)
            .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
            .order_by(JobRun.created_at.desc())
        ).first()
        latest_run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == _CSDM_RUN_MODULE)
            .where(JobRun.job_type == _CSDM_RUN_TYPE)
            .order_by(JobRun.created_at.desc())
        ).first()

    run = active_run or latest_run
    if not run:
        return None

    metadata = _json_loads_dict(run.metadata_json)
    raw_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    status = raw_status
    if raw_status == JobRunStatus.queued.value:
        status = "running"
    tables = _parse_json_string_list(run.requested_data_types_json)
    completed_tables = [str(t) for t in metadata.get("completed_tables", []) if str(t).strip()]
    failed_tables = [str(t) for t in metadata.get("failed_tables", []) if str(t).strip()]

    return {
        "instance_id": instance_id,
        "run_uid": run.run_uid,
        "tables": tables,
        "mode": run.mode,
        "status": status,
        "current_table": run.current_data_type,
        "completed_tables": completed_tables,
        "failed_tables": failed_tables,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "is_alive": False,
    }


# ===================================================================
# PAGE ROUTES
# ===================================================================

@csdm_router.get("/ingestion", response_class=HTMLResponse)
async def csdm_ingestion_page(
    request: Request,
    instance_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
):
    """Render the CSDM Data Ingestion management page."""
    instances = session.exec(select(Instance)).all()

    # Determine selected instance
    selected_instance = None
    table_states: Dict[str, Dict[str, Any]] = {}
    job_snapshot = None
    recent_logs: list = []

    if instance_id:
        selected_instance = session.get(Instance, instance_id)
        if selected_instance:
            table_states = _build_table_states(instance_id, session)
            job_snapshot = _get_job_snapshot(instance_id)

            # Fetch recent job logs (last 20)
            recent_logs = session.exec(
                select(SnJobLog)
                .where(SnJobLog.instance_id == instance_id)
                .order_by(SnJobLog.created_at.desc())
                .limit(20)
            ).all()

    return templates.TemplateResponse(
        "csdm_ingestion.html",
        {
            "request": request,
            "instances": instances,
            "selected_instance": selected_instance,
            "instance_id": instance_id,
            "table_groups": CSDM_TABLE_GROUPS,
            "table_states": table_states,
            "job_snapshot": job_snapshot,
            "recent_logs": recent_logs,
            "static_version": str(int(datetime.utcnow().timestamp())),
        },
    )


# ===================================================================
# API ROUTES (JSON)
# ===================================================================

@csdm_router.post("/api/ingest")
async def api_start_ingestion(
    body: IngestRequest,
    session: Session = Depends(get_session),
):
    """Start a background ingestion queue for the given tables."""
    instance = session.get(Instance, body.instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Validate table names
    known_tables = set(get_all_table_names())
    custom_tables = {
        r.sn_table_name
        for r in session.exec(
            select(SnCustomTableRequest).where(
                SnCustomTableRequest.instance_id == body.instance_id,
                SnCustomTableRequest.status == "active",
            )
        ).all()
    }
    valid_tables = known_tables | custom_tables
    invalid = [t for t in body.tables if t not in valid_tables]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tables: {', '.join(invalid)}",
        )

    # Check if a job is already running for this instance
    with _CSDM_JOBS_LOCK:
        existing = _CSDM_JOBS.get(body.instance_id)
        if existing and existing.thread and existing.thread.is_alive():
            raise HTTPException(
                status_code=409,
                detail="An ingestion job is already running for this instance. Cancel it first.",
            )
    existing_run = session.exec(
        select(JobRun)
        .where(JobRun.instance_id == body.instance_id)
        .where(JobRun.module == _CSDM_RUN_MODULE)
        .where(JobRun.job_type == _CSDM_RUN_TYPE)
        .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
        .order_by(JobRun.created_at.desc())
    ).first()
    if existing_run:
        raise HTTPException(
            status_code=409,
            detail="An ingestion run is already active for this instance. Cancel it first.",
        )

    # Set queued status for each table
    for tbl in body.tables:
        state = session.exec(
            select(SnIngestionState).where(
                SnIngestionState.instance_id == body.instance_id,
                SnIngestionState.sn_table_name == tbl,
            )
        ).first()
        if not state:
            state = SnIngestionState(
                instance_id=body.instance_id,
                sn_table_name=tbl,
            )
            session.add(state)
        state.last_run_status = "queued"
        state.updated_at = datetime.utcnow()
    session.commit()

    # Create and start background thread
    cancel_event = threading.Event()
    now = datetime.utcnow()
    run_uid = _create_csdm_run_record(body.instance_id, body.tables, body.mode)

    thread = threading.Thread(
        target=_run_ingestion_thread,
        args=(body.instance_id, body.tables, body.mode, cancel_event, run_uid),
        daemon=True,
        name=f"csdm-ingest-{body.instance_id}",
    )

    job = _CsdmIngestionJob(
        instance_id=body.instance_id,
        run_uid=run_uid,
        tables=list(body.tables),
        mode=body.mode,
        cancel_event=cancel_event,
        thread=thread,
        started_at=now,
    )

    with _CSDM_JOBS_LOCK:
        _CSDM_JOBS[body.instance_id] = job

    thread.start()

    return JSONResponse(
        content={
            "status": "started",
            "tables": body.tables,
            "mode": body.mode,
            "instance_id": body.instance_id,
            "run_uid": run_uid,
        }
    )


@csdm_router.get("/api/status/{instance_id}")
async def api_ingestion_status(
    instance_id: int,
    session: Session = Depends(get_session),
):
    """Return current queue status, running job, and per-table states."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    table_states = _build_table_states(instance_id, session)
    job_snapshot = _get_job_snapshot(instance_id)

    # Recent logs
    recent_logs = session.exec(
        select(SnJobLog)
        .where(SnJobLog.instance_id == instance_id)
        .order_by(SnJobLog.created_at.desc())
        .limit(20)
    ).all()
    log_data = [
        {
            "id": log.id,
            "sn_table_name": log.sn_table_name,
            "job_type": log.job_type,
            "status": log.status,
            "rows_inserted": log.rows_inserted,
            "rows_updated": log.rows_updated,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "completed_at": log.completed_at.isoformat() if log.completed_at else None,
            "duration_seconds": (
                round((log.completed_at - log.started_at).total_seconds(), 1)
                if log.started_at and log.completed_at
                else None
            ),
            "error_message": log.error_message,
        }
        for log in recent_logs
    ]

    return JSONResponse(
        content=jsonable_encoder({
            "instance_id": instance_id,
            "current_job": job_snapshot,
            "tables": table_states,
            "recent_logs": log_data,
        })
    )


@csdm_router.post("/api/cancel/{instance_id}")
async def api_cancel_current(
    instance_id: int,
    table: Optional[str] = Query(default=None),
    all_jobs: bool = Query(default=False, alias="all"),
):
    """Cancel the current running job for an instance.

    If `table` is provided, marks that specific table as cancelled in DB.
    Otherwise marks ALL queued/in_progress/started tables as cancelled.
    If `all=true`, behaves like cancel-all.
    """
    with _CSDM_JOBS_LOCK:
        job = _CSDM_JOBS.get(instance_id)
        if job:
            job.cancel_event.set()

    # Update DB state — either specific table or all pending tables.
    with Session(engine) as session:
        if table:
            states = session.exec(
                select(SnIngestionState).where(
                    SnIngestionState.instance_id == instance_id,
                    SnIngestionState.sn_table_name == table,
                )
            ).all()
        else:
            states = session.exec(
                select(SnIngestionState).where(
                    SnIngestionState.instance_id == instance_id,
                    SnIngestionState.last_run_status.in_(
                        ["queued", "in_progress", "started"]
                    ),
                )
            ).all()

        for state in states:
            if state.last_run_status in ("queued", "in_progress", "started"):
                state.last_run_status = "cancelled"
                state.updated_at = datetime.utcnow()
        session.commit()

    return JSONResponse(content={"status": "cancelled", "instance_id": instance_id})


@csdm_router.post("/api/cancel-all/{instance_id}")
async def api_cancel_all(
    instance_id: int,
):
    """Cancel all jobs for an instance and mark queued tables as cancelled."""
    with _CSDM_JOBS_LOCK:
        job = _CSDM_JOBS.get(instance_id)
        if job:
            job.cancel_event.set()

    # Mark all queued/in_progress/started states as cancelled
    with Session(engine) as session:
        states = session.exec(
            select(SnIngestionState).where(
                SnIngestionState.instance_id == instance_id,
                SnIngestionState.last_run_status.in_(
                    ["queued", "in_progress", "started"]
                ),
            )
        ).all()
        for state in states:
            state.last_run_status = "cancelled"
            state.updated_at = datetime.utcnow()
        session.commit()

    return JSONResponse(content={"status": "all_cancelled", "instance_id": instance_id})


@csdm_router.post("/api/clear-rows/{instance_id}")
async def api_clear_rows(
    instance_id: int,
    body: IngestRequest,
):
    """Delete all rows from the selected mirror tables for this instance.

    Resets ingestion state so a fresh full pull can start clean.
    """
    from ...services.csdm_ingestion import drop_mirror_table_data
    from ...csdm_table_catalog import get_local_table_name

    cleared = {}
    errors = {}
    with Session(engine) as session:
        for sn_table in body.tables:
            local_name = get_local_table_name(sn_table)
            try:
                deleted = drop_mirror_table_data(local_name, instance_id)
            except Exception as exc:
                errors[sn_table] = str(exc)
                continue
            cleared[sn_table] = deleted

            # Reset ingestion state so UI shows 0 rows
            state = session.exec(
                select(SnIngestionState).where(
                    SnIngestionState.instance_id == instance_id,
                    SnIngestionState.sn_table_name == sn_table,
                )
            ).first()
            if state:
                state.total_rows_in_db = 0
                state.last_batch_inserted = 0
                state.last_batch_updated = 0
                state.last_run_status = "never"
                state.last_error = None
                state.updated_at = datetime.utcnow()
                session.add(state)

            # Also sync registry row_count
            reg = session.exec(
                select(SnTableRegistry).where(
                    SnTableRegistry.instance_id == instance_id,
                    SnTableRegistry.sn_table_name == sn_table,
                )
            ).first()
            if reg:
                reg.row_count = 0
                reg.updated_at = datetime.utcnow()
                session.add(reg)

        session.commit()

    return JSONResponse(content={
        "status": "cleared_with_errors" if errors else "cleared",
        "instance_id": instance_id,
        "cleared": cleared,
        "errors": errors,
    })


@csdm_router.post("/api/custom-tables")
async def api_add_custom_table(
    body: CustomTableRequest,
    session: Session = Depends(get_session),
):
    """Validate and register a custom ServiceNow table."""
    instance = session.get(Instance, body.instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    # Check if already registered
    existing = session.exec(
        select(SnCustomTableRequest).where(
            SnCustomTableRequest.instance_id == body.instance_id,
            SnCustomTableRequest.sn_table_name == body.sn_table_name,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Table '{body.sn_table_name}' is already registered (status: {existing.status})",
        )

    # Basic name validation
    sn_name = body.sn_table_name.strip().lower()
    if not sn_name or " " in sn_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid table name. Use the ServiceNow sys_db_object name (e.g., 'cmdb_ci_server').",
        )

    # Create request record
    request_record = SnCustomTableRequest(
        instance_id=body.instance_id,
        sn_table_name=sn_name,
        status="pending",
        requested_at=datetime.utcnow(),
    )
    session.add(request_record)
    session.commit()
    session.refresh(request_record)

    # Try to validate and register via the ingestion engine
    try:
        from ...services.csdm_ingestion import register_custom_table  # type: ignore[import]

        req_result = register_custom_table(body.instance_id, sn_name)

        # Sync request record status from result
        if req_result:
            request_record.status = req_result.status
            request_record.validated_at = req_result.validated_at
            request_record.display_label = req_result.display_label
            request_record.validation_error = req_result.validation_error
        session.commit()

        if req_result and req_result.status in ("validated", "schema_created"):
            return JSONResponse(
                content={
                    "status": "success",
                    "table_name": sn_name,
                    "local_table_name": get_local_table_name(sn_name),
                    "label": req_result.display_label or sn_name,
                }
            )
        else:
            error_detail = req_result.validation_error if req_result else "Unknown error"
            raise HTTPException(status_code=400, detail=f"Validation failed: {error_detail}")

    except ImportError:
        # Ingestion service not yet available -- accept pending
        session.commit()
        return JSONResponse(
            content={
                "status": "pending",
                "table_name": sn_name,
                "message": "Table registered. Validation will run when the ingestion service is available.",
            }
        )

    except HTTPException:
        raise

    except Exception as exc:
        request_record.status = "failed"
        request_record.validation_error = str(exc)[:500]
        session.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Validation failed: {exc}",
        )


@csdm_router.post("/api/schema/refresh")
async def api_refresh_schema(
    body: SchemaRefreshRequest,
    session: Session = Depends(get_session),
):
    """Re-fetch the dictionary for a table and apply schema changes."""
    instance = session.get(Instance, body.instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        from ...services.csdm_ingestion import refresh_table_schema  # type: ignore[import]

        result = refresh_table_schema(body.instance_id, body.sn_table_name)

        # Update registry
        registry = session.exec(
            select(SnTableRegistry).where(
                SnTableRegistry.instance_id == body.instance_id,
                SnTableRegistry.sn_table_name == body.sn_table_name,
            )
        ).first()
        if registry:
            registry.last_schema_refresh_at = datetime.utcnow()
            registry.schema_version += 1
            registry.field_count = result.get("field_count", registry.field_count)
            registry.updated_at = datetime.utcnow()
            session.commit()

        return JSONResponse(
            content={
                "status": "success",
                "table_name": body.sn_table_name,
                "field_count": result.get("field_count", 0),
                "changes": result.get("changes", []),
            }
        )

    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Schema refresh service not yet available.",
        )

    except Exception as exc:
        logger.exception(
            "Schema refresh failed for %s on instance %s",
            body.sn_table_name,
            body.instance_id,
        )
        raise HTTPException(status_code=500, detail=f"Schema refresh failed: {exc}")
