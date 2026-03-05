import json
from datetime import datetime

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    GeneralRecommendation,
    Instance,
    OriginType,
    ReviewStatus,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
    UpdateSet,
    UpdateSetArtifactLink,
)


def _seed_observation_assessment(session):
    inst = Instance(
        name="obs-inst",
        url="https://obs.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Observation Assessment",
        number="ASMT0099500",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="Observation Scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    customized_a = ScanResult(
        scan_id=scan.id,
        sys_id="a",
        table_name="sys_script",
        name="Approval BR",
        origin_type=OriginType.modified_ootb,
        sys_updated_on=datetime.utcnow(),
    )
    customized_b = ScanResult(
        scan_id=scan.id,
        sys_id="b",
        table_name="sys_script_include",
        name="ApprovalHelper",
        origin_type=OriginType.net_new_customer,
        sys_updated_on=datetime.utcnow(),
    )
    untouched = ScanResult(
        scan_id=scan.id,
        sys_id="c",
        table_name="sys_ui_policy",
        name="OOTB Policy",
        origin_type=OriginType.ootb_untouched,
        sys_updated_on=datetime.utcnow(),
    )
    session.add_all([customized_a, customized_b, untouched])
    session.flush()

    update_set = UpdateSet(
        instance_id=inst.id,
        sn_sys_id="us-obs-1",
        name="Approval Feature",
        state="complete",
    )
    session.add(update_set)
    session.flush()
    session.add(
        UpdateSetArtifactLink(
            instance_id=inst.id,
            assessment_id=asmt.id,
            scan_result_id=customized_a.id,
            update_set_id=update_set.id,
            link_source="customer_update_xml",
            confidence=0.95,
        )
    )
    session.add(
        StructuralRelationship(
            instance_id=inst.id,
            assessment_id=asmt.id,
            parent_scan_result_id=customized_a.id,
            child_scan_result_id=customized_b.id,
            relationship_type="script_call",
            parent_field="script",
            confidence=0.8,
        )
    )
    session.commit()
    return asmt, customized_a, customized_b, untouched


def test_generate_observations_writes_customized_results_and_landscape_summary(db_session):
    from src.mcp.tools.pipeline.generate_observations import handle

    asmt, customized_a, customized_b, untouched = _seed_observation_assessment(db_session)
    result = handle(
        {
            "assessment_id": asmt.id,
            "batch_size": 2,
            "include_usage_queries": "never",
        },
        db_session,
    )

    assert result["success"] is True
    assert result["processed_count"] == 2
    assert result["total_customized"] == 2
    assert result["batches_processed"] == 1

    refreshed_a = db_session.get(ScanResult, customized_a.id)
    refreshed_b = db_session.get(ScanResult, customized_b.id)
    refreshed_c = db_session.get(ScanResult, untouched.id)

    assert refreshed_a.observations
    assert refreshed_b.observations
    assert refreshed_a.review_status == ReviewStatus.pending_review
    assert refreshed_b.review_status == ReviewStatus.pending_review
    assert refreshed_a.ai_pass_count >= 1
    assert refreshed_b.ai_pass_count >= 1

    ai_payload = json.loads(refreshed_a.ai_observations or "{}")
    assert ai_payload.get("generator") == "deterministic_pipeline_v1"
    assert "update_set_signal_count" in ai_payload

    assert refreshed_c.observations is None

    summary_rows = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "landscape_summary")
    ).all()
    assert len(summary_rows) == 1
    assert "customized artifacts" in (summary_rows[0].description or "")


def test_generate_observations_respects_max_results(db_session):
    from src.mcp.tools.pipeline.generate_observations import handle

    asmt, _, _, _ = _seed_observation_assessment(db_session)
    result = handle(
        {
            "assessment_id": asmt.id,
            "max_results": 1,
            "include_usage_queries": "never",
        },
        db_session,
    )
    assert result["success"] is True
    assert result["processed_count"] == 1
    assert result["total_customized"] == 1
