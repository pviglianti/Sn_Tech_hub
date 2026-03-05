import json
import uuid
from datetime import datetime

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Customization,
    Instance,
    JobRun,
    JobRunStatus,
    OriginType,
    ReviewStatus,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.server import (
    _assessment_review_gate_summary,
    _get_assessment_pipeline_job_snapshot,
    _mark_remaining_customizations_reviewed,
)


def _seed_review_gate_state(session):
    inst = Instance(
        name="pipe-inst",
        url="https://pipe.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Pipeline Gate Assessment",
        number="ASMT0099600",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="Pipeline Scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    pending = ScanResult(
        scan_id=scan.id,
        sys_id="p",
        table_name="sys_script",
        name="Pending BR",
        origin_type=OriginType.modified_ootb,
        review_status=ReviewStatus.pending_review,
        sys_updated_on=datetime.utcnow(),
    )
    reviewed = ScanResult(
        scan_id=scan.id,
        sys_id="r",
        table_name="sys_script_include",
        name="Reviewed SI",
        origin_type=OriginType.net_new_customer,
        review_status=ReviewStatus.reviewed,
        sys_updated_on=datetime.utcnow(),
    )
    untouched = ScanResult(
        scan_id=scan.id,
        sys_id="u",
        table_name="sys_ui_policy",
        name="Untouched OOTB",
        origin_type=OriginType.ootb_untouched,
        review_status=ReviewStatus.pending_review,
        sys_updated_on=datetime.utcnow(),
    )
    session.add_all([pending, reviewed, untouched])
    session.flush()

    session.add(
        Customization(
            scan_result_id=pending.id,
            scan_id=scan.id,
            sys_id=pending.sys_id,
            table_name=pending.table_name,
            name=pending.name,
            origin_type=pending.origin_type,
            review_status=pending.review_status,
        )
    )
    session.add(
        Customization(
            scan_result_id=reviewed.id,
            scan_id=scan.id,
            sys_id=reviewed.sys_id,
            table_name=reviewed.table_name,
            name=reviewed.name,
            origin_type=reviewed.origin_type,
            review_status=reviewed.review_status,
        )
    )
    session.commit()
    return asmt, pending


def test_review_gate_summary_and_bulk_mark_reviewed(db_session):
    asmt, pending_result = _seed_review_gate_state(db_session)

    before = _assessment_review_gate_summary(db_session, asmt.id)
    assert before["total_customized"] == 2
    assert before["reviewed"] == 1
    assert before["pending"] == 1
    assert before["all_reviewed"] is False

    changed = _mark_remaining_customizations_reviewed(db_session, asmt.id)
    assert changed == 1

    after = _assessment_review_gate_summary(db_session, asmt.id)
    assert after["total_customized"] == 2
    assert after["reviewed"] == 2
    assert after["pending"] == 0
    assert after["all_reviewed"] is True

    custom = db_session.exec(
        select(Customization).where(Customization.scan_result_id == pending_result.id)
    ).first()
    assert custom is not None
    assert custom.review_status == ReviewStatus.reviewed


def test_pipeline_job_snapshot_reads_persisted_job_run(db_session):
    asmt, _ = _seed_review_gate_state(db_session)
    run = JobRun(
        run_uid=uuid.uuid4().hex,
        instance_id=asmt.instance_id,
        module="assessment",
        job_type="reasoning_pipeline",
        mode="engines",
        status=JobRunStatus.running,
        queue_total=1,
        queue_completed=0,
        progress_pct=42,
        current_data_type="engines",
        message="Running engines stage.",
        metadata_json=json.dumps(
            {
                "assessment_id": asmt.id,
                "target_stage": "engines",
                "stage": "engines",
            }
        ),
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.commit()

    snapshot = _get_assessment_pipeline_job_snapshot(asmt.id, session=db_session)
    assert snapshot is not None
    assert snapshot["job_type"] == "reasoning_pipeline"
    assert snapshot["target_stage"] == "engines"
    assert snapshot["stage"] == "engines"
    assert snapshot["status"] == "running"
    assert snapshot["progress_percent"] == 42
