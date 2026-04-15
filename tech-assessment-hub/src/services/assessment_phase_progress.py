"""Resumable assessment phase checkpoint service."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from ..models import Assessment, AssessmentPhaseProgress


RESUMABLE_STATUSES = {
    "running",
    "paused",
    "failed",
    "blocked_rate_limit",
    "blocked_cost_limit",
}


def _json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _json_loads(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return {}
    return {}


def _resolve_instance_id(session: Session, assessment_id: int) -> int:
    assessment = session.get(Assessment, int(assessment_id))
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")
    return int(assessment.instance_id)


def _get_row(session: Session, assessment_id: int, phase: str) -> Optional[AssessmentPhaseProgress]:
    return session.exec(
        select(AssessmentPhaseProgress)
        .where(AssessmentPhaseProgress.assessment_id == int(assessment_id))
        .where(AssessmentPhaseProgress.phase == str(phase))
    ).first()


def get_phase_progress(
    session: Session,
    assessment_id: int,
    phase: str,
) -> Optional[AssessmentPhaseProgress]:
    return _get_row(session, assessment_id, phase)


def start_phase_progress(
    session: Session,
    assessment_id: int,
    phase: str,
    *,
    total_items: int = 0,
    allow_resume: bool = True,
    reset_if_completed: bool = False,
    checkpoint: Optional[Dict[str, Any]] = None,
    commit: bool = False,
) -> AssessmentPhaseProgress:
    """Mark phase as running and return current checkpoint row."""
    now = datetime.utcnow()
    row = _get_row(session, assessment_id, phase)
    resolved_total = max(0, int(total_items or 0))

    if not row:
        row = AssessmentPhaseProgress(
            assessment_id=int(assessment_id),
            instance_id=_resolve_instance_id(session, assessment_id),
            phase=str(phase),
            status="running",
            total_items=resolved_total,
            completed_items=0,
            resume_from_index=0,
            run_attempt=1,
            started_at=now,
            last_checkpoint_at=now,
            updated_at=now,
        )
    else:
        restart = False
        if row.status == "completed" and reset_if_completed:
            restart = True
        elif not allow_resume:
            restart = True

        if restart:
            row.completed_items = 0
            row.resume_from_index = 0
            row.last_item_id = None
            row.last_error = None
            row.checkpoint_json = None
            row.completed_at = None
            row.run_attempt = int(row.run_attempt or 0) + 1
            row.started_at = now
        elif row.started_at is None:
            row.started_at = now

        row.status = "running"
        row.total_items = resolved_total
        row.completed_items = min(max(0, int(row.completed_items or 0)), row.total_items or int(row.completed_items or 0))
        row.resume_from_index = int(row.completed_items or 0)
        row.last_checkpoint_at = now
        row.updated_at = now

    if checkpoint:
        payload = _json_loads(row.checkpoint_json)
        payload.update(checkpoint)
        payload["phase"] = str(phase)
        payload["started_at"] = (row.started_at or now).isoformat()
        row.checkpoint_json = _json_dumps(payload)

    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    return row


def checkpoint_phase_progress(
    session: Session,
    assessment_id: int,
    phase: str,
    *,
    completed_items: Optional[int] = None,
    completed_delta: int = 0,
    total_items: Optional[int] = None,
    last_item_id: Optional[int] = None,
    status: Optional[str] = None,
    checkpoint: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    commit: bool = False,
) -> AssessmentPhaseProgress:
    """Update checkpoint counters/state for a phase."""
    row = _get_row(session, assessment_id, phase)
    if not row:
        row = start_phase_progress(
            session,
            assessment_id,
            phase,
            total_items=max(0, int(total_items or 0)),
            allow_resume=True,
            checkpoint=checkpoint,
            commit=False,
        )

    now = datetime.utcnow()
    if total_items is not None:
        row.total_items = max(0, int(total_items or 0))

    if completed_items is not None:
        row.completed_items = max(0, int(completed_items))
    elif completed_delta:
        row.completed_items = max(0, int(row.completed_items or 0) + int(completed_delta))

    if row.total_items > 0:
        row.completed_items = min(int(row.completed_items), int(row.total_items))

    row.resume_from_index = int(row.completed_items)
    if last_item_id is not None:
        row.last_item_id = int(last_item_id)

    if status:
        row.status = str(status)
        if row.status == "completed":
            row.completed_at = now
    else:
        if row.completed_items > 0 and row.status == "pending":
            row.status = "running"

    if error:
        row.last_error = str(error)

    if checkpoint:
        payload = _json_loads(row.checkpoint_json)
        payload.update(checkpoint)
        payload["phase"] = str(phase)
        payload["completed_items"] = int(row.completed_items)
        payload["total_items"] = int(row.total_items)
        payload["resume_from_index"] = int(row.resume_from_index)
        payload["last_checkpoint_at"] = now.isoformat()
        row.checkpoint_json = _json_dumps(payload)

    row.last_checkpoint_at = now
    row.updated_at = now
    session.add(row)

    if commit:
        session.commit()
        session.refresh(row)
    return row


def complete_phase_progress(
    session: Session,
    assessment_id: int,
    phase: str,
    *,
    checkpoint: Optional[Dict[str, Any]] = None,
    commit: bool = False,
) -> AssessmentPhaseProgress:
    row = _get_row(session, assessment_id, phase)
    if not row:
        row = start_phase_progress(session, assessment_id, phase, total_items=0, allow_resume=True, commit=False)

    if row.total_items > 0:
        row.completed_items = int(row.total_items)
    return checkpoint_phase_progress(
        session,
        assessment_id,
        phase,
        completed_items=row.completed_items,
        status="completed",
        checkpoint=checkpoint,
        commit=commit,
    )


def fail_phase_progress(
    session: Session,
    assessment_id: int,
    phase: str,
    *,
    status: str = "failed",
    error: Optional[str] = None,
    checkpoint: Optional[Dict[str, Any]] = None,
    commit: bool = False,
) -> AssessmentPhaseProgress:
    normalized = str(status or "failed").strip().lower()
    if not normalized:
        normalized = "failed"
    return checkpoint_phase_progress(
        session,
        assessment_id,
        phase,
        status=normalized,
        error=error,
        checkpoint=checkpoint,
        commit=commit,
    )


def reset_phase_progress(
    session: Session,
    assessment_id: int,
    phase: str,
    *,
    checkpoint: Optional[Dict[str, Any]] = None,
    commit: bool = False,
) -> Optional[AssessmentPhaseProgress]:
    """Clear resumable state so a completed phase can run again from the start."""
    row = _get_row(session, assessment_id, phase)
    if not row:
        return None

    now = datetime.utcnow()
    row.status = "pending"
    row.total_items = 0
    row.completed_items = 0
    row.resume_from_index = 0
    row.last_item_id = None
    row.last_error = None
    row.completed_at = None
    row.started_at = None
    row.last_checkpoint_at = None
    row.updated_at = now
    row.run_attempt = int(row.run_attempt or 0) + 1
    row.checkpoint_json = _json_dumps(checkpoint or {}) if checkpoint else None

    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    return row
