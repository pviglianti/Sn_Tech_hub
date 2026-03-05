import json
from datetime import datetime

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    FeatureContextArtifact,
    FeatureGroupingRun,
    FeatureScanResult,
    Instance,
    NamingCluster,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
)


def _seed_assessment_with_signals(session):
    inst = Instance(
        name="seed-tools",
        url="https://seed-tools.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Seed Tools Assessment",
        number="ASMT0099001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="Seed Scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    r1 = ScanResult(
        scan_id=scan.id,
        sys_id="r1",
        table_name="sys_script",
        name="Approval BR",
        origin_type=OriginType.modified_ootb,
        sys_updated_on=datetime.utcnow(),
    )
    r2 = ScanResult(
        scan_id=scan.id,
        sys_id="r2",
        table_name="sys_script_include",
        name="ApprovalHelper",
        origin_type=OriginType.net_new_customer,
        sys_updated_on=datetime.utcnow(),
    )
    r3 = ScanResult(
        scan_id=scan.id,
        sys_id="r3",
        table_name="sys_ui_policy",
        name="OOTB UI Policy",
        origin_type=OriginType.ootb_untouched,
        sys_updated_on=datetime.utcnow(),
    )
    session.add_all([r1, r2, r3])
    session.flush()

    session.add(
        NamingCluster(
            instance_id=inst.id,
            assessment_id=asmt.id,
            cluster_label="Approval*",
            pattern_type="prefix",
            member_count=2,
            member_ids_json=json.dumps([r1.id, r2.id]),
            tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
            confidence=0.9,
        )
    )
    session.add(
        CodeReference(
            instance_id=inst.id,
            assessment_id=asmt.id,
            source_scan_result_id=r1.id,
            source_table="sys_script",
            source_field="script",
            source_name=r1.name,
            reference_type="script_include",
            target_identifier=r2.name,
            target_scan_result_id=r2.id,
            confidence=1.0,
        )
    )
    session.add(
        StructuralRelationship(
            instance_id=inst.id,
            assessment_id=asmt.id,
            parent_scan_result_id=r1.id,
            child_scan_result_id=r3.id,
            relationship_type="ui_policy_binding",
            parent_field="ui_policy",
            confidence=0.8,
        )
    )
    session.commit()

    return asmt, r1, r2, r3


def test_seed_feature_groups_tool_creates_members_and_context(db_session):
    from src.mcp.tools.pipeline.seed_feature_groups import handle

    asmt, r1, r2, r3 = _seed_assessment_with_signals(db_session)

    result = handle({"assessment_id": asmt.id}, db_session)
    assert result["success"] is True
    assert result["features_created"] >= 1
    assert result["grouped_count"] >= 2

    links = db_session.exec(select(FeatureScanResult)).all()
    assert any(link.scan_result_id == r1.id for link in links)
    assert any(link.scan_result_id == r2.id for link in links)
    assert all((link.assignment_source or "").lower() == "engine" for link in links)

    contexts = db_session.exec(select(FeatureContextArtifact)).all()
    assert any(ctx.scan_result_id == r3.id for ctx in contexts)


def test_run_feature_reasoning_creates_run_and_status_reports_it(db_session):
    from src.mcp.tools.pipeline.run_feature_reasoning import handle as run_reasoning
    from src.mcp.tools.pipeline.feature_grouping_status import handle as run_status

    asmt, _, _, _ = _seed_assessment_with_signals(db_session)

    first = run_reasoning({"assessment_id": asmt.id, "pass_type": "group_refine"}, db_session)
    assert first["success"] is True
    assert first["run_id"] is not None
    assert first["iterations_completed"] == 1

    second = run_reasoning(
        {"assessment_id": asmt.id, "run_id": first["run_id"], "pass_type": "verify"},
        db_session,
    )
    assert second["success"] is True
    assert second["status"] == "completed"

    run_row = db_session.get(FeatureGroupingRun, first["run_id"])
    assert run_row is not None
    assert run_row.iterations_completed == 2
    assert run_row.status == "completed"

    status = run_status({"assessment_id": asmt.id}, db_session)
    assert status["success"] is True
    assert status["run_found"] is True
    assert status["run"]["id"] == first["run_id"]
    assert status["coverage"]["customized_total"] >= 2


def test_mcp_registry_uses_new_feature_grouping_tools():
    from src.mcp.registry import build_registry

    registry = build_registry()
    assert registry.has_tool("seed_feature_groups")
    assert registry.has_tool("run_feature_reasoning")
    assert registry.has_tool("feature_grouping_status")
    assert registry.has_tool("generate_observations")
    assert registry.has_tool("get_usage_count")
    assert not registry.has_tool("group_by_feature")
