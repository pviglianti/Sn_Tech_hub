"""Regression tests for orphaned durable run reconciliation."""

from datetime import datetime, timedelta

from sqlmodel import select

from src.models import (
    DataPullStatus,
    DataPullType,
    InstanceDataPull,
    JobRun,
    JobRunStatus,
)
from src.services import dictionary_pull_orchestrator as dict_orch


def test_data_status_marks_orphaned_data_pull_run_failed(client, db_session, sample_instance):
    stale_time = datetime.utcnow() - timedelta(minutes=10)
    run = JobRun(
        run_uid="orphan-data-pull-run",
        instance_id=sample_instance.id,
        module="preflight",
        job_type="data_pull",
        mode="smart",
        status=JobRunStatus.running,
        queue_total=1,
        queue_completed=0,
        progress_pct=0,
        message="Pulling 1 of 1: version_history",
        current_data_type="version_history",
        started_at=stale_time,
        last_heartbeat_at=stale_time,
        created_at=stale_time,
        updated_at=stale_time,
    )
    pull = InstanceDataPull(
        instance_id=sample_instance.id,
        data_type=DataPullType.version_history,
        status=DataPullStatus.running,
        started_at=stale_time,
        updated_at=stale_time,
    )
    db_session.add(run)
    db_session.add(pull)
    db_session.commit()

    resp = client.get(f"/api/instances/{sample_instance.id}/data-status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["active_run"] is None
    assert payload["latest_run"]["status"] == "failed"

    refreshed_run = db_session.exec(select(JobRun).where(JobRun.id == run.id)).first()
    assert refreshed_run is not None
    assert refreshed_run.status == JobRunStatus.failed

    refreshed_pull = db_session.exec(select(InstanceDataPull).where(InstanceDataPull.id == pull.id)).first()
    assert refreshed_pull is not None
    assert refreshed_pull.status == DataPullStatus.failed


def test_dictionary_status_marks_orphaned_dict_run_failed(
    db_engine, db_session, sample_instance, monkeypatch
):
    monkeypatch.setattr(dict_orch, "engine", db_engine)
    with dict_orch._DICT_PULL_LOCK:
        dict_orch._DICT_PULL_JOBS.clear()
        dict_orch._DICT_PULL_THREADS.clear()

    stale_time = datetime.utcnow() - timedelta(minutes=10)
    run = JobRun(
        run_uid="orphan-dict-run",
        instance_id=sample_instance.id,
        module="preflight",
        job_type="dict_pull",
        mode="smart",
        status=JobRunStatus.running,
        queue_total=0,
        queue_completed=0,
        progress_pct=0,
        message="Discovering dictionary for 0 table(s).",
        started_at=stale_time,
        last_heartbeat_at=stale_time,
        created_at=stale_time,
        updated_at=stale_time,
    )
    db_session.add(run)
    db_session.commit()

    status = dict_orch.get_dictionary_pull_status(sample_instance.id)
    assert status["status"] == "failed"
    assert status["raw_status"] == "failed"

    refreshed_run = db_session.exec(select(JobRun).where(JobRun.id == run.id)).first()
    assert refreshed_run is not None
    assert refreshed_run.status == JobRunStatus.failed
