"""Dictionary Pull Orchestrator - Background extraction of sys_dictionary metadata.

Pulls field-level metadata (column labels, types, references, mandatory/read-only)
from ServiceNow sys_dictionary for all registered tables (CSDM + Preflight + custom).
Stores results in SnTableRegistry + SnFieldMapping.

Follows the same in-memory job tracking pattern as _DATA_PULL_JOBS in server.py
and the threading patterns from data_pull_executor.py.
"""

from __future__ import annotations

import json
import logging
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, select, func

from ..database import engine
from ..models import Instance, JobRun, JobEvent, JobRunStatus
from ..models_sn import SnTableRegistry, SnFieldMapping, SnCustomTableRequest
from ..services.integration_sync_runner import resolve_delta_decision
from ..csdm_table_catalog import (
    get_all_table_names as get_csdm_table_names,
    get_table_group,
    get_local_table_name,
    get_table_label,
)
from .sn_client import ServiceNowClient, ServiceNowClientError
from .sn_dictionary import extract_full_dictionary
from .sn_client_factory import create_client_for_instance
from ..table_registry_catalog import PREFLIGHT_SN_TABLE_MAP

logger = logging.getLogger(__name__)

_DICT_PULL_RUN_MODULE = "preflight"
_DICT_PULL_RUN_TYPE = "dict_pull"
_ACTIVE_RUN_STATUSES = (JobRunStatus.queued, JobRunStatus.running)
_ORPHAN_RUN_GRACE_SECONDS = 30


def _json_dumps(payload: Optional[dict]) -> Optional[str]:
    if payload is None:
        return None
    try:
        return json.dumps(payload, sort_keys=True)
    except Exception:
        return None


def _append_dict_run_event(
    session: Session,
    run: JobRun,
    *,
    event_type: str,
    summary: Optional[str] = None,
    payload: Optional[dict] = None,
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


def _load_dict_run(session: Session, run_uid: str) -> Optional[JobRun]:
    return session.exec(select(JobRun).where(JobRun.run_uid == run_uid)).first()


def _create_dictionary_pull_run_record(instance_id: int, source_context: str = "preflight") -> str:
    run_uid = uuid.uuid4().hex
    now = datetime.utcnow()
    with Session(engine) as session:
        run = JobRun(
            run_uid=run_uid,
            instance_id=instance_id,
            module=_DICT_PULL_RUN_MODULE,
            job_type=_DICT_PULL_RUN_TYPE,
            mode="smart",
            status=JobRunStatus.queued,
            queue_total=0,
            queue_completed=0,
            progress_pct=0,
            message="Queued dictionary pull.",
            metadata_json=_json_dumps({"source": source_context}),
            created_at=now,
            updated_at=now,
            last_heartbeat_at=now,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_dict_run_event(
            session,
            run,
            event_type="queued",
            summary="Dictionary pull queued.",
            payload={"instance_id": instance_id},
        )
        session.commit()
    return run_uid


def _mark_dict_run_running(session: Session, run_uid: str, table_names: List[str]) -> None:
    run = _load_dict_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = JobRunStatus.running
    run.started_at = now
    run.completed_at = None
    run.queue_total = len(table_names)
    run.queue_completed = 0
    run.current_index = 1 if table_names else None
    run.current_data_type = table_names[0] if table_names else None
    run.progress_pct = 0
    run.estimated_remaining_seconds = None
    run.error_message = None
    run.message = f"Discovering dictionary for {len(table_names)} table(s)."
    run.requested_data_types_json = _json_dumps(table_names)
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_dict_run_event(
        session,
        run,
        event_type="started",
        summary="Dictionary pull started.",
        payload={"queue_total": len(table_names)},
    )
    session.commit()


def _mark_dict_run_table_started(
    session: Session,
    run_uid: str,
    sn_table_name: str,
    *,
    index: int,
    total: int,
) -> None:
    run = _load_dict_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    run.status = JobRunStatus.running
    run.current_data_type = sn_table_name
    run.current_index = index
    run.queue_total = max(int(run.queue_total or 0), total)
    run.progress_pct = int(round((float(run.queue_completed or 0) / float(max(total, 1))) * 100))
    run.message = f"Pulling database schema/dictionary entries for {sn_table_name} ({index} of {total})"
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_dict_run_event(
        session,
        run,
        event_type="item_started",
        summary=f"Started dictionary for {sn_table_name}.",
        payload={"sn_table_name": sn_table_name, "index": index, "total": total},
    )
    session.commit()


def _mark_dict_run_table_completed(
    session: Session,
    run_uid: str,
    sn_table_name: str,
    *,
    status: str,
    index: int,
    total: int,
    elapsed_seconds: float,
    completed_durations: List[float],
    error: Optional[str] = None,
) -> None:
    run = _load_dict_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    queue_total = max(int(run.queue_total or 0), total)
    queue_completed = max(int(run.queue_completed or 0), index)
    run.queue_total = queue_total
    run.queue_completed = queue_completed
    run.current_data_type = None
    run.current_index = None
    run.progress_pct = int(round((float(queue_completed) / float(max(queue_total, 1))) * 100))
    run.message = f"{sn_table_name}: {status}"
    if completed_durations:
        avg_duration = sum(completed_durations) / len(completed_durations)
        remaining = max(0, queue_total - queue_completed)
        run.estimated_remaining_seconds = round(avg_duration * remaining, 1)
    else:
        run.estimated_remaining_seconds = None
    run.updated_at = now
    run.last_heartbeat_at = now
    if error:
        run.error_message = error
    _append_dict_run_event(
        session,
        run,
        event_type="item_completed",
        summary=f"Finished dictionary for {sn_table_name} ({status}).",
        payload={
            "sn_table_name": sn_table_name,
            "status": status,
            "index": index,
            "total": total,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "error": error,
        },
    )
    session.commit()


def _mark_dict_run_finished(
    session: Session,
    run_uid: str,
    *,
    status: JobRunStatus,
    queue_completed: int,
    queue_total: int,
    message: str,
    error_message: Optional[str] = None,
) -> None:
    run = _load_dict_run(session, run_uid)
    if not run:
        return
    now = datetime.utcnow()
    normalized_total = max(int(run.queue_total or 0), int(queue_total or 0))
    normalized_completed = min(max(int(queue_completed or 0), 0), max(normalized_total, 0))
    run.status = status
    run.completed_at = now
    run.queue_total = normalized_total
    run.queue_completed = normalized_completed
    run.current_data_type = None
    run.current_index = None
    run.progress_pct = 100 if normalized_total > 0 else 0
    run.estimated_remaining_seconds = 0
    run.message = message
    run.error_message = error_message
    run.updated_at = now
    run.last_heartbeat_at = now
    _append_dict_run_event(
        session,
        run,
        event_type=status.value,
        summary=message,
        payload={"queue_completed": normalized_completed, "queue_total": normalized_total},
    )
    session.commit()


def _serialize_dict_run_status(run: JobRun, instance_id: int) -> dict:
    raw_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    mapped_status = "running"
    if raw_status == JobRunStatus.completed.value:
        mapped_status = "completed"
    elif raw_status in {JobRunStatus.failed.value, JobRunStatus.cancelled.value}:
        mapped_status = "failed"

    total = int(run.queue_total or 0)
    completed = min(max(int(run.queue_completed or 0), 0), max(total, 0))
    percent_complete = float(run.progress_pct or 0)
    if total > 0 and percent_complete <= 0:
        percent_complete = round((completed / total) * 100, 1)

    return {
        "status": mapped_status,
        "raw_status": raw_status,
        "instance_id": instance_id,
        "run_uid": run.run_uid,
        "total_tables": total,
        "completed_tables": completed,
        "current_table": run.current_data_type,
        "percent_complete": percent_complete,
        "eta_seconds": run.estimated_remaining_seconds,
        "error": run.error_message,
        "message": run.message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


def recover_interrupted_dictionary_runs() -> int:
    """Mark stale queued/running dictionary runs as failed after restart."""
    with Session(engine) as session:
        stale_runs = session.exec(
            select(JobRun)
            .where(JobRun.module == _DICT_PULL_RUN_MODULE)
            .where(JobRun.job_type == _DICT_PULL_RUN_TYPE)
            .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
        ).all()
        if not stale_runs:
            return 0

        now = datetime.utcnow()
        for run in stale_runs:
            run.status = JobRunStatus.failed
            run.completed_at = now
            run.current_data_type = None
            run.current_index = None
            run.progress_pct = 100
            run.estimated_remaining_seconds = 0
            run.error_message = run.error_message or "Interrupted (server restart)"
            run.message = "Interrupted (server restart)"
            run.updated_at = now
            run.last_heartbeat_at = now
            session.add(run)
            session.add(
                JobEvent(
                    run_id=run.id,
                    event_type=JobRunStatus.failed.value,
                    summary="Dictionary pull interrupted by server restart.",
                    data_json=_json_dumps({"reason": "server_restart"}),
                    created_at=now,
                )
            )
        session.commit()
        return len(stale_runs)


# ============================================
# PROGRESS TRACKING
# ============================================

@dataclass
class DictionaryPullProgress:
    """In-memory progress tracker for a dictionary pull operation."""

    instance_id: int
    cancel_event: Optional[threading.Event] = None
    run_uid: Optional[str] = None
    total_tables: int = 0
    completed_tables: int = 0
    current_table: Optional[str] = None
    status: str = "running"  # "running" | "completed" | "failed"
    started_at: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None
    table_times: List[float] = field(default_factory=list)  # seconds per table, for ETA


_DICT_PULL_LOCK = threading.Lock()
_DICT_PULL_JOBS: Dict[int, DictionaryPullProgress] = {}
_DICT_PULL_THREADS: Dict[int, threading.Thread] = {}


# ============================================
# PUBLIC API
# ============================================

def start_dictionary_pull(instance_id: int, source_context: str = "preflight") -> bool:
    """Start a background dictionary pull for the given instance.

    Returns True if a new thread was started, False if already running.
    """
    with _DICT_PULL_LOCK:
        existing_thread = _DICT_PULL_THREADS.get(instance_id)
        if existing_thread and existing_thread.is_alive():
            return False

        with Session(engine) as session:
            existing_run = session.exec(
                select(JobRun)
                .where(JobRun.instance_id == instance_id)
                .where(JobRun.module == _DICT_PULL_RUN_MODULE)
                .where(JobRun.job_type == _DICT_PULL_RUN_TYPE)
                .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
                .order_by(JobRun.created_at.desc())
            ).first()
        if existing_run:
            return False

        cancel_event = threading.Event()
        run_uid = _create_dictionary_pull_run_record(instance_id, source_context=source_context)
        progress = DictionaryPullProgress(
            instance_id=instance_id,
            run_uid=run_uid,
            cancel_event=cancel_event,
        )
        _DICT_PULL_JOBS[instance_id] = progress

        def _runner() -> None:
            try:
                pull_dictionary_for_instance(instance_id, cancel_event)
            finally:
                with _DICT_PULL_LOCK:
                    if _DICT_PULL_THREADS.get(instance_id) is thread:
                        _DICT_PULL_THREADS.pop(instance_id, None)

        thread = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"dict_pull_instance_{instance_id}",
        )
        _DICT_PULL_THREADS[instance_id] = thread
        thread.start()
        return True


def cancel_dictionary_pull(instance_id: int) -> bool:
    """Request cancellation for an active dictionary pull on an instance."""
    requested = False
    with _DICT_PULL_LOCK:
        progress = _DICT_PULL_JOBS.get(instance_id)
        if progress and progress.cancel_event:
            progress.cancel_event.set()
            requested = True
        thread = _DICT_PULL_THREADS.get(instance_id)
        if thread and thread.is_alive():
            requested = True
    return requested


def get_dictionary_pull_status(instance_id: int) -> dict:
    """Return current progress for a dictionary pull, suitable for API response."""
    with _DICT_PULL_LOCK:
        progress = _DICT_PULL_JOBS.get(instance_id)
        thread = _DICT_PULL_THREADS.get(instance_id)
        thread_alive = bool(thread and thread.is_alive())
        # If in-memory progress says running but worker thread is gone,
        # treat the in-memory state as stale and fall back to durable run state.
        if progress and progress.status == "running" and not thread_alive:
            _DICT_PULL_JOBS.pop(instance_id, None)
            progress = None

    if progress:
        # Calculate ETA
        eta_seconds: Optional[float] = None
        if progress.table_times and progress.status == "running":
            avg_time = sum(progress.table_times) / len(progress.table_times)
            remaining = progress.total_tables - progress.completed_tables
            eta_seconds = round(avg_time * remaining, 1)

        percent = 0
        if progress.total_tables > 0:
            percent = round(progress.completed_tables / progress.total_tables * 100, 1)

        return {
            "status": progress.status,
            "instance_id": progress.instance_id,
            "run_uid": progress.run_uid,
            "total_tables": progress.total_tables,
            "completed_tables": progress.completed_tables,
            "current_table": progress.current_table,
            "percent_complete": percent,
            "eta_seconds": eta_seconds,
            "error": progress.error,
        }

    with Session(engine) as session:
        active_run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == _DICT_PULL_RUN_MODULE)
            .where(JobRun.job_type == _DICT_PULL_RUN_TYPE)
            .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
            .order_by(JobRun.created_at.desc())
        ).first()
        # Reconcile orphaned durable runs (no worker thread alive).
        if active_run and not thread_alive:
            heartbeat = (
                active_run.last_heartbeat_at
                or active_run.updated_at
                or active_run.started_at
                or active_run.created_at
            )
            age_seconds = (datetime.utcnow() - heartbeat).total_seconds() if heartbeat else 0
            if age_seconds >= _ORPHAN_RUN_GRACE_SECONDS:
                now = datetime.utcnow()
                active_run.status = JobRunStatus.failed
                active_run.completed_at = now
                active_run.current_data_type = None
                active_run.current_index = None
                active_run.progress_pct = 100
                active_run.estimated_remaining_seconds = 0
                active_run.error_message = active_run.error_message or "Dictionary pull worker not running"
                active_run.message = "Dictionary pull interrupted (worker not running)."
                active_run.updated_at = now
                active_run.last_heartbeat_at = now
                session.add(active_run)
                session.add(
                    JobEvent(
                        run_id=active_run.id,
                        event_type=JobRunStatus.failed.value,
                        summary="Dictionary pull run marked failed (orphaned run state).",
                        data_json=_json_dumps({"reason": "orphaned_run_state"}),
                        created_at=now,
                    )
                )
                session.commit()
                session.refresh(active_run)
                active_run = None
        latest_run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == _DICT_PULL_RUN_MODULE)
            .where(JobRun.job_type == _DICT_PULL_RUN_TYPE)
            .order_by(JobRun.created_at.desc())
        ).first()

    run = active_run or latest_run
    if not run:
        return {"status": "idle", "instance_id": instance_id}

    return _serialize_dict_run_status(run, instance_id=instance_id)


# ============================================
# WORKER
# ============================================

def pull_dictionary_for_instance(
    instance_id: int,
    cancel_event: threading.Event,
) -> None:
    """Main worker: pull dictionary for all tables of an instance.

    1. Connect to instance
    2. Determine full table list (CSDM + Preflight + custom)
    3. Batch-pull sys_db_object for table labels
    4. For each table: extract_full_dictionary -> store in registry + field mappings
    """
    with _DICT_PULL_LOCK:
        progress = _DICT_PULL_JOBS.get(instance_id)
        if not progress:
            progress = DictionaryPullProgress(instance_id=instance_id)
            _DICT_PULL_JOBS[instance_id] = progress
    run_uid = progress.run_uid

    with Session(engine) as session:
        # Load instance and create client
        instance = session.get(Instance, instance_id)
        if not instance:
            error_message = f"Instance {instance_id} not found"
            progress.status = "failed"
            progress.error = error_message
            if run_uid:
                _mark_dict_run_finished(
                    session,
                    run_uid,
                    status=JobRunStatus.failed,
                    queue_completed=0,
                    queue_total=0,
                    message=error_message,
                    error_message=error_message,
                )
            return

        try:
            client = create_client_for_instance(instance)
        except Exception as exc:
            error_message = f"Failed to create client: {exc}"
            progress.status = "failed"
            progress.error = error_message
            if run_uid:
                _mark_dict_run_finished(
                    session,
                    run_uid,
                    status=JobRunStatus.failed,
                    queue_completed=0,
                    queue_total=0,
                    message=error_message,
                    error_message=error_message,
                )
            return

        # Determine all tables to process
        all_sn_tables = _get_all_tables_for_instance(session, instance_id)
        progress.total_tables = len(all_sn_tables)
        if run_uid:
            _mark_dict_run_running(session, run_uid, all_sn_tables)

        if not all_sn_tables:
            progress.status = "completed"
            if run_uid:
                _mark_dict_run_finished(
                    session,
                    run_uid,
                    status=JobRunStatus.completed,
                    queue_completed=0,
                    queue_total=0,
                    message="No tables required dictionary sync.",
                )
            return

        # Batch-pull sys_db_object for table labels
        table_labels = _batch_pull_sys_db_object(client, all_sn_tables)
        had_table_failures = False

        # Process each table with smart delta decision
        for i, sn_table_name in enumerate(all_sn_tables):
            index = i + 1
            if cancel_event.is_set():
                progress.status = "failed"
                progress.error = "Cancelled"
                if run_uid:
                    _mark_dict_run_finished(
                        session,
                        run_uid,
                        status=JobRunStatus.cancelled,
                        queue_completed=progress.completed_tables,
                        queue_total=progress.total_tables,
                        message="Dictionary pull cancelled.",
                        error_message="Cancelled by user.",
                    )
                return

            progress.current_table = sn_table_name
            if run_uid:
                _mark_dict_run_table_started(
                    session,
                    run_uid,
                    sn_table_name,
                    index=index,
                    total=progress.total_tables,
                )
            table_start = time.monotonic()
            table_status = "completed"
            table_error: Optional[str] = None

            try:
                # Get existing registry to check watermark and field count
                registry = session.exec(
                    select(SnTableRegistry)
                    .where(SnTableRegistry.instance_id == instance_id)
                    .where(SnTableRegistry.sn_table_name == sn_table_name)
                ).first()

                # Determine sync mode using resolve_delta_decision
                watermark = registry.last_schema_refresh_at if registry else None
                local_field_count = registry.field_count if registry else 0

                # For dictionary pulls, we don't have a remote count easily available
                # so we use None and rely on watermark-based delta
                decision = resolve_delta_decision(
                    local_count=local_field_count,
                    remote_count=None,  # Not practical to get field count from remote
                    watermark=watermark,
                    delta_probe_count=None,  # Will use watermark-based delta
                )

                # Skip if decision says no changes
                if decision.mode == "skip":
                    logger.debug("Skipping %s - no changes detected", sn_table_name)
                    table_status = "skipped"
                else:
                    # Pull dictionary with watermark for delta mode
                    since = decision.since if decision.mode == "delta" else None
                    dict_data = extract_full_dictionary(client, sn_table_name, since=since)

                    if dict_data:
                        _store_dictionary_entries(
                            session=session,
                            instance_id=instance_id,
                            sn_table_name=sn_table_name,
                            dict_data=dict_data,
                            table_label=table_labels.get(sn_table_name),
                        )
                        logger.debug(
                            "Pulled %s: mode=%s, fields=%d",
                            sn_table_name, decision.mode, len(dict_data.get("fields", []))
                        )
                    else:
                        table_status = "skipped"
            except Exception as exc:
                table_status = "failed"
                had_table_failures = True
                table_error = str(exc)
                logger.warning(
                    "Dictionary pull failed for table %s (instance %d): %s",
                    sn_table_name, instance_id, exc,
                )
                # Continue with remaining tables even if one fails

            elapsed = time.monotonic() - table_start
            progress.table_times.append(elapsed)
            progress.completed_tables = index
            if table_status == "failed":
                progress.error = table_error
            if run_uid:
                _mark_dict_run_table_completed(
                    session,
                    run_uid,
                    sn_table_name,
                    status=table_status,
                    index=index,
                    total=progress.total_tables,
                    elapsed_seconds=elapsed,
                    completed_durations=progress.table_times,
                    error=table_error,
                )

        progress.current_table = None
        progress.status = "failed" if had_table_failures else "completed"
        if not had_table_failures:
            progress.error = None
        logger.info(
            "Dictionary pull completed for instance %d: %d/%d tables",
            instance_id, progress.completed_tables, progress.total_tables,
        )
        if run_uid:
            final_status = JobRunStatus.failed if had_table_failures else JobRunStatus.completed
            final_message = (
                "Dictionary pull completed with table failures."
                if had_table_failures
                else "Dictionary pull completed."
            )
            _mark_dict_run_finished(
                session,
                run_uid,
                status=final_status,
                queue_completed=progress.completed_tables,
                queue_total=progress.total_tables,
                message=final_message,
                error_message=progress.error if had_table_failures else None,
            )


# ============================================
# TABLE LIST HELPERS
# ============================================

def _get_all_tables_for_instance(session: Session, instance_id: int) -> List[str]:
    """Return combined list of CSDM + Preflight + custom tables for an instance.

    Deduplicates by SN table name.
    """
    seen: set[str] = set()
    result: List[str] = []

    # CSDM tables from the catalog
    for name in get_csdm_table_names():
        if name not in seen:
            seen.add(name)
            result.append(name)

    # Preflight tables
    for sn_name in PREFLIGHT_SN_TABLE_MAP.values():
        if sn_name not in seen:
            seen.add(sn_name)
            result.append(sn_name)

    # Custom tables requested by users for this instance
    custom_requests = session.exec(
        select(SnCustomTableRequest.sn_table_name)
        .where(SnCustomTableRequest.instance_id == instance_id)
        .where(SnCustomTableRequest.status.in_(["validated", "schema_created", "active"]))
    ).all()
    for row in custom_requests:
        name = row if isinstance(row, str) else row[0] if row else None
        if name and name not in seen:
            seen.add(name)
            result.append(name)

    return result


# ============================================
# BATCH SYS_DB_OBJECT PULL
# ============================================

def _batch_pull_sys_db_object(
    client: ServiceNowClient,
    table_names: List[str],
) -> Dict[str, Optional[str]]:
    """Batch-pull sys_db_object to get table labels using nameIN query.

    Returns dict mapping sn_table_name -> label (or None if not found).
    """
    labels: Dict[str, Optional[str]] = {}
    if not table_names:
        return labels

    # ServiceNow has URL length limits; chunk into batches of ~50 tables
    chunk_size = 50
    for i in range(0, len(table_names), chunk_size):
        chunk = table_names[i:i + chunk_size]
        name_list = ",".join(chunk)
        query = f"nameIN{name_list}"

        try:
            records = client.get_records(
                table="sys_db_object",
                query=query,
                fields=["name", "label"],
                limit=len(chunk),
            )
            for rec in records:
                name = rec.get("name", "")
                label = rec.get("label", "")
                if name:
                    labels[name] = label or None
        except ServiceNowClientError as exc:
            logger.warning("Batch sys_db_object pull failed: %s", exc)

    return labels


# ============================================
# STORE DICTIONARY ENTRIES
# ============================================

def _store_dictionary_entries(
    session: Session,
    instance_id: int,
    sn_table_name: str,
    dict_data: dict,
    table_label: Optional[str] = None,
) -> None:
    """Store extracted dictionary data into SnTableRegistry + SnFieldMapping.

    Creates or updates the registry entry and replaces field mappings.
    """
    fields = dict_data.get("fields", [])
    table_info = dict_data.get("table_info")
    parent_table = dict_data.get("parent_table")

    local_name = get_local_table_name(sn_table_name)
    group = get_table_group(sn_table_name)
    display_label = get_table_label(sn_table_name)

    # Determine source classification
    source = "csdm"
    if sn_table_name in PREFLIGHT_SN_TABLE_MAP.values():
        source = "preflight"
    elif group == "custom":
        source = "custom"

    # Use table_info label if available, fall back to batch-pulled label
    effective_label = None
    if table_info and table_info.label:
        effective_label = table_info.label
    elif table_label:
        effective_label = table_label

    # Find or create registry entry
    registry = session.exec(
        select(SnTableRegistry)
        .where(SnTableRegistry.instance_id == instance_id)
        .where(SnTableRegistry.sn_table_name == sn_table_name)
    ).first()

    if not registry:
        registry = SnTableRegistry(
            instance_id=instance_id,
            sn_table_name=sn_table_name,
            local_table_name=local_name,
            priority_group=group,
            display_label=display_label,
            source=source,
            sn_table_label=effective_label,
            parent_table=parent_table,
            parent_local_table=get_local_table_name(parent_table) if parent_table else None,
            is_custom=(group == "custom"),
            field_count=len(fields),
        )
        session.add(registry)
        session.flush()
    else:
        registry.field_count = len(fields)
        registry.source = source
        registry.sn_table_label = effective_label
        registry.parent_table = parent_table
        registry.parent_local_table = get_local_table_name(parent_table) if parent_table else None
        registry.updated_at = datetime.utcnow()
        session.add(registry)
        session.flush()

    # Upsert field mappings (merge instead of delete-replace)
    existing_mappings_by_element = {
        fm.sn_element: fm
        for fm in session.exec(
            select(SnFieldMapping).where(SnFieldMapping.registry_id == registry.id)
        ).all()
    }

    for f_info in fields:
        existing_fm = existing_mappings_by_element.get(f_info.element)
        if existing_fm:
            # Update existing field mapping
            existing_fm.sn_internal_type = f_info.internal_type
            existing_fm.sn_max_length = f_info.max_length
            existing_fm.sn_reference_table = f_info.reference_table if f_info.is_reference else None
            existing_fm.is_reference = f_info.is_reference
            existing_fm.is_active = f_info.is_active
            existing_fm.column_label = f_info.column_label
            existing_fm.is_mandatory = f_info.is_mandatory
            existing_fm.is_read_only = f_info.is_read_only
            existing_fm.source_table = f_info.source_table
            session.add(existing_fm)
        else:
            # Create new field mapping
            fm = SnFieldMapping(
                registry_id=registry.id,
                sn_element=f_info.element,
                local_column=f_info.element,
                sn_internal_type=f_info.internal_type,
                sn_max_length=f_info.max_length,
                sn_reference_table=f_info.reference_table if f_info.is_reference else None,
                db_column_type="TEXT",
                is_reference=f_info.is_reference,
                is_primary_key=(f_info.element == "sys_id"),
                is_active=f_info.is_active,
                column_label=f_info.column_label,
                is_mandatory=f_info.is_mandatory,
                is_read_only=f_info.is_read_only,
                source_table=f_info.source_table,
            )
            session.add(fm)

    # Update field_count to reflect actual stored mappings (not just delta changes)
    session.flush()  # Ensure new mappings are persisted
    actual_field_count = session.exec(
        select(func.count(SnFieldMapping.id))
        .where(SnFieldMapping.registry_id == registry.id)
    ).one()
    registry.field_count = actual_field_count
    registry.last_schema_refresh_at = datetime.utcnow()
    session.add(registry)
    session.commit()

    logger.debug(
        "Stored %d fields for %s (instance %d)",
        len(fields), sn_table_name, instance_id,
    )


# ============================================
# BACKFILL
# ============================================

def backfill_missing_labels(instance_id: int) -> int:
    """Backfill column_label for existing field mappings that are missing labels.

    Useful for instances that were registered before the dictionary pull feature.

    Returns the number of fields updated.
    """
    updated = 0

    with Session(engine) as session:
        instance = session.get(Instance, instance_id)
        if not instance:
            logger.warning("Instance %d not found for backfill", instance_id)
            return 0

        client = create_client_for_instance(instance)

        # Find registries with field mappings missing labels
        registries = session.exec(
            select(SnTableRegistry)
            .where(SnTableRegistry.instance_id == instance_id)
        ).all()

        for registry in registries:
            # Check if any fields are missing labels
            missing_label_fields = session.exec(
                select(SnFieldMapping)
                .where(SnFieldMapping.registry_id == registry.id)
                .where(
                    (SnFieldMapping.column_label == None) |
                    (SnFieldMapping.column_label == "")
                )
            ).all()

            if not missing_label_fields:
                continue

            # Pull fresh dictionary for this table
            dict_data = extract_full_dictionary(client, registry.sn_table_name)
            if not dict_data:
                continue

            # Build lookup from fresh data
            fresh_fields = {f.element: f for f in dict_data.get("fields", [])}

            # Update missing labels
            for fm in missing_label_fields:
                fresh = fresh_fields.get(fm.sn_element)
                if fresh and fresh.column_label:
                    fm.column_label = fresh.column_label
                    fm.is_mandatory = fresh.is_mandatory
                    fm.is_read_only = fresh.is_read_only
                    fm.source_table = fresh.source_table
                    session.add(fm)
                    updated += 1

            session.commit()

    logger.info(
        "Backfill completed for instance %d: %d fields updated",
        instance_id, updated,
    )
    return updated
