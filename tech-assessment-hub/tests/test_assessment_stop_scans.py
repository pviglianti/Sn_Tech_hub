from sqlmodel import select

from src.models import (
    Instance,
    Assessment,
    Scan,
    AssessmentState,
    AssessmentType,
    ScanStatus,
    ScanType,
)
from src.server import _request_cancel_assessment_scans


def test_stop_scans_requests_cancel_running_and_cancels_pending(db_session, sample_instance):
    assessment = Assessment(
        number="ASMT9999999",
        name="Test Assessment",
        instance_id=sample_instance.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    pending = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Pending scan",
        status=ScanStatus.pending,
    )
    running = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Running scan",
        status=ScanStatus.running,
    )
    db_session.add(pending)
    db_session.add(running)
    db_session.commit()

    result = _request_cancel_assessment_scans(db_session, assessment.id)
    assert result["scans_total"] == 2
    assert result["cancel_requested"] == 1
    assert result["cancelled"] == 1

    scans = db_session.exec(select(Scan).where(Scan.assessment_id == assessment.id)).all()
    by_name = {s.name: s for s in scans}

    pending_row = by_name["Pending scan"]
    assert pending_row.cancel_requested is True
    assert pending_row.status == ScanStatus.cancelled
    assert pending_row.completed_at is not None

    running_row = by_name["Running scan"]
    assert running_row.cancel_requested is True
    assert running_row.status == ScanStatus.running
