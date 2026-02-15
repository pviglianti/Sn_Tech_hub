from datetime import datetime, timedelta

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    Scan,
    ScanStatus,
    ScanType,
)
from src.server import _build_recovered_assessment_run_status


@pytest.fixture()
def recovery_ctx(db_session, sample_instance):
    """Provide common context for scan status recovery tests."""

    def _create_assessment(state=AssessmentState.in_progress):
        assessment = Assessment(
            number="ASMT1234567",
            name="Recovery Test",
            instance_id=sample_instance.id,
            assessment_type=AssessmentType.global_app,
            state=state,
        )
        db_session.add(assessment)
        db_session.commit()
        db_session.refresh(assessment)
        return assessment

    class Ctx:
        pass

    ctx = Ctx()
    ctx.session = db_session
    ctx.instance_id = sample_instance.id
    ctx.create_assessment = _create_assessment
    return ctx


def test_recovered_status_reports_running_when_scan_rows_running(recovery_ctx):
    assessment = recovery_ctx.create_assessment()
    started_at = datetime.utcnow() - timedelta(minutes=2)
    running_scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Running scan",
        status=ScanStatus.running,
        started_at=started_at,
    )
    pending_scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Pending scan",
        status=ScanStatus.pending,
    )
    recovery_ctx.session.add(running_scan)
    recovery_ctx.session.add(pending_scan)
    recovery_ctx.session.commit()

    scans = [running_scan, pending_scan]
    counts = {"pending": 1, "running": 1, "completed": 0, "failed": 0, "cancelled": 0}
    payload = _build_recovered_assessment_run_status(assessment, scans, counts)

    assert payload is not None
    assert payload["status"] == "running"
    assert payload["stage"] == "running_scans"
    assert "recovered status" in payload["message"]


def test_recovered_status_reports_failed_when_interrupted_mid_run(recovery_ctx):
    assessment = recovery_ctx.create_assessment()
    started_at = datetime.utcnow() - timedelta(minutes=4)
    completed_scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Completed scan",
        status=ScanStatus.completed,
        started_at=started_at,
        completed_at=started_at + timedelta(minutes=1),
    )
    pending_scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Pending scan",
        status=ScanStatus.pending,
    )
    recovery_ctx.session.add(completed_scan)
    recovery_ctx.session.add(pending_scan)
    recovery_ctx.session.commit()

    scans = [completed_scan, pending_scan]
    counts = {"pending": 1, "running": 0, "completed": 1, "failed": 0, "cancelled": 0}
    payload = _build_recovered_assessment_run_status(assessment, scans, counts)

    assert payload is not None
    assert payload["status"] == "failed"
    assert payload["stage"] == "failed"
    assert "interrupted" in payload["message"].lower()


def test_recovered_status_hidden_when_no_active_or_interrupted_signal(recovery_ctx):
    assessment = recovery_ctx.create_assessment()
    pending_scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Pending scan",
        status=ScanStatus.pending,
    )
    recovery_ctx.session.add(pending_scan)
    recovery_ctx.session.commit()

    scans = [pending_scan]
    counts = {"pending": 1, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    payload = _build_recovered_assessment_run_status(assessment, scans, counts)

    assert payload is None
