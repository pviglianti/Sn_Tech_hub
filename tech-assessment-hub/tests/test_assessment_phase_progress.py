"""Tests for resumable assessment phase checkpoint behavior."""

from datetime import datetime

from sqlmodel import Session, select

from src.models import (
    Assessment,
    AssessmentPhaseProgress,
    AssessmentState,
    AssessmentType,
    OriginType,
    Scan,
    ScanResult,
    ScanType,
)
from src.services.assessment_phase_progress import (
    checkpoint_phase_progress,
    complete_phase_progress,
    start_phase_progress,
)
from src.mcp.tools.pipeline.generate_observations import handle as generate_observations_handle


def _seed_assessment(db_session: Session, instance_id: int) -> Assessment:
    assessment = Assessment(
        number="ASMT-PHASE-0001",
        name="Phase Progress Seed",
        instance_id=instance_id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        started_at=datetime.utcnow(),
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)
    return assessment


def test_phase_progress_resumes_from_last_checkpoint(db_session: Session, sample_instance):
    assessment = _seed_assessment(db_session, sample_instance.id)

    row = start_phase_progress(
        db_session,
        assessment.id,
        "observations",
        total_items=10,
        allow_resume=True,
        commit=True,
    )
    assert row.resume_from_index == 0

    row = checkpoint_phase_progress(
        db_session,
        assessment.id,
        "observations",
        completed_items=3,
        last_item_id=123,
        status="running",
        checkpoint={"resume_from_index": 3},
        commit=True,
    )
    assert row.completed_items == 3
    assert row.resume_from_index == 3

    resumed = start_phase_progress(
        db_session,
        assessment.id,
        "observations",
        total_items=10,
        allow_resume=True,
        commit=True,
    )
    assert resumed.resume_from_index == 3

    done = complete_phase_progress(
        db_session,
        assessment.id,
        "observations",
        checkpoint={"resume_from_index": 10},
        commit=True,
    )
    assert done.status == "completed"
    assert done.completed_items == 10
    assert done.resume_from_index == 10


def test_generate_observations_supports_resume_index(db_session: Session, sample_instance):
    assessment = _seed_assessment(db_session, sample_instance.id)

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="Metadata",
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    for idx in range(3):
        db_session.add(
            ScanResult(
                scan_id=scan.id,
                sys_id=f"sys_{idx}",
                table_name="sys_script",
                name=f"Artifact {idx}",
                origin_type=OriginType.modified_ootb,
            )
        )
    db_session.commit()

    first = generate_observations_handle(
        {
            "assessment_id": assessment.id,
            "include_usage_queries": "never",
            "max_results": 3,
            "resume_from_index": 0,
        },
        db_session,
    )
    assert first["success"] is True
    assert first["processed_count"] == 3
    assert first["next_resume_index"] == 3
    assert first["remaining_customized"] == 0

    second = generate_observations_handle(
        {
            "assessment_id": assessment.id,
            "include_usage_queries": "never",
            "max_results": 3,
            "resume_from_index": 2,
        },
        db_session,
    )
    assert second["success"] is True
    assert second["processed_count"] == 1
    assert second["next_resume_index"] == 3
    assert second["remaining_customized"] == 0

    row = db_session.exec(
        select(AssessmentPhaseProgress).where(
            AssessmentPhaseProgress.assessment_id == assessment.id,
            AssessmentPhaseProgress.phase == "observations",
        )
    ).first()
    assert row is not None
    assert row.resume_from_index == 3
    assert row.completed_items == 3
