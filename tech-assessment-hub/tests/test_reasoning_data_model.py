"""Tests for reasoning layer data model additions."""

import json
from datetime import datetime

from sqlalchemy import inspect

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    GroupingSignalType,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    UpdateSet,
)


def _seed_assessment(session):
    """Seed instance -> assessment -> scan -> 2 scan_results."""
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Test Assessment",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="test scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR - Approval Check",
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_script_include",
        name="ApprovalHelper",
    )
    session.add_all([sr1, sr2])
    session.flush()

    return inst, asmt, sr1, sr2


def test_grouping_signal_type_enum_exists():
    assert GroupingSignalType.update_set == "update_set"
    assert GroupingSignalType.code_reference == "code_reference"
    assert GroupingSignalType.ai_judgment == "ai_judgment"
    assert len(GroupingSignalType) == 9


def test_code_reference_table_round_trip(db_session):
    from src.models import CodeReference

    inst, asmt, sr1, sr2 = _seed_assessment(db_session)

    ref = CodeReference(
        instance_id=inst.id,
        assessment_id=asmt.id,
        source_scan_result_id=sr1.id,
        source_table="sys_script",
        source_field="script",
        source_name="BR - Approval Check",
        reference_type="script_include",
        target_identifier="ApprovalHelper",
        target_scan_result_id=sr2.id,
        line_number=42,
        code_snippet="new ApprovalHelper()",
        confidence=1.0,
    )
    db_session.add(ref)
    db_session.commit()
    db_session.refresh(ref)

    assert ref.id is not None
    assert ref.instance_id == inst.id
    assert ref.assessment_id == asmt.id
    assert ref.source_scan_result_id == sr1.id
    assert ref.target_scan_result_id == sr2.id
    assert ref.reference_type == "script_include"
    assert ref.confidence == 1.0


def test_update_set_overlap_table_round_trip(db_session):
    from src.models import UpdateSetOverlap

    inst, asmt, sr1, _ = _seed_assessment(db_session)

    us1 = UpdateSet(
        instance_id=inst.id,
        sn_sys_id="us_aaa",
        name="RITM Approval v1",
        state="closed",
        application="global",
    )
    us2 = UpdateSet(
        instance_id=inst.id,
        sn_sys_id="us_bbb",
        name="RITM Approval v2",
        state="closed",
        application="global",
    )
    db_session.add_all([us1, us2])
    db_session.flush()

    overlap = UpdateSetOverlap(
        instance_id=inst.id,
        assessment_id=asmt.id,
        update_set_a_id=us1.id,
        update_set_b_id=us2.id,
        shared_record_count=3,
        shared_records_json=json.dumps(
            [{"scan_result_id": sr1.id, "name": "BR - Approval Check", "table": "sys_script"}]
        ),
        overlap_score=0.75,
    )
    db_session.add(overlap)
    db_session.commit()
    db_session.refresh(overlap)

    assert overlap.id is not None
    assert overlap.instance_id == inst.id
    assert overlap.shared_record_count == 3
    assert overlap.overlap_score == 0.75


def test_temporal_cluster_table_round_trip(db_session):
    from src.models import TemporalCluster

    inst, asmt, sr1, sr2 = _seed_assessment(db_session)

    cluster = TemporalCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        developer="john.doe",
        cluster_start=datetime(2025, 6, 15, 10, 0, 0),
        cluster_end=datetime(2025, 6, 15, 10, 45, 0),
        record_count=5,
        record_ids_json=json.dumps([sr1.id, sr2.id]),
        avg_gap_minutes=11.25,
        tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
    )
    db_session.add(cluster)
    db_session.commit()
    db_session.refresh(cluster)

    assert cluster.id is not None
    assert cluster.instance_id == inst.id
    assert cluster.developer == "john.doe"
    assert cluster.record_count == 5
    assert cluster.avg_gap_minutes == 11.25


def test_temporal_cluster_member_round_trip(db_session):
    from src.models import TemporalCluster, TemporalClusterMember

    inst, asmt, sr1, _ = _seed_assessment(db_session)

    cluster = TemporalCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        developer="john.doe",
        cluster_start=datetime(2025, 6, 15, 10, 0, 0),
        cluster_end=datetime(2025, 6, 15, 10, 45, 0),
        record_count=1,
        record_ids_json=json.dumps([sr1.id]),
        avg_gap_minutes=0.0,
        tables_involved_json=json.dumps(["sys_script"]),
    )
    db_session.add(cluster)
    db_session.flush()

    member = TemporalClusterMember(
        instance_id=inst.id,
        assessment_id=asmt.id,
        temporal_cluster_id=cluster.id,
        scan_result_id=sr1.id,
    )
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)

    assert member.id is not None
    assert member.instance_id == inst.id
    assert member.assessment_id == asmt.id
    assert member.temporal_cluster_id == cluster.id
    assert member.scan_result_id == sr1.id


def test_structural_relationship_table_round_trip(db_session):
    from src.models import StructuralRelationship

    inst, asmt, sr1, sr2 = _seed_assessment(db_session)

    rel = StructuralRelationship(
        instance_id=inst.id,
        assessment_id=asmt.id,
        parent_scan_result_id=sr1.id,
        child_scan_result_id=sr2.id,
        relationship_type="ui_policy_action",
        parent_field="ui_policy",
        confidence=1.0,
    )
    db_session.add(rel)
    db_session.commit()
    db_session.refresh(rel)

    assert rel.id is not None
    assert rel.instance_id == inst.id
    assert rel.parent_scan_result_id == sr1.id
    assert rel.child_scan_result_id == sr2.id
    assert rel.relationship_type == "ui_policy_action"


def test_feature_has_reasoning_fields(db_session):
    _, asmt, _, _ = _seed_assessment(db_session)

    feature = Feature(
        assessment_id=asmt.id,
        name="RITM Approval Workflow",
        confidence_score=8.5,
        confidence_level="high",
        signals_json=json.dumps(
            [
                {"type": "update_set", "weight": 3},
                {"type": "code_reference", "weight": 4},
            ]
        ),
        primary_table="sc_req_item",
        primary_developer="john.doe",
        pass_number=2,
    )
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(feature)

    assert feature.confidence_score == 8.5
    assert feature.confidence_level == "high"
    assert "update_set" in feature.signals_json
    assert feature.primary_table == "sc_req_item"
    assert feature.primary_developer == "john.doe"
    assert feature.pass_number == 2


def test_scan_result_has_reasoning_fields(db_session):
    _, _, sr1, sr2 = _seed_assessment(db_session)

    sr1.ai_summary = "Business rule that checks approval status on RITM"
    sr1.ai_observations = "Pass 1: Calls ApprovalHelper script include."
    sr1.ai_pass_count = 1
    sr1.related_result_ids_json = json.dumps([sr2.id])

    db_session.add(sr1)
    db_session.commit()
    db_session.refresh(sr1)

    assert sr1.ai_summary == "Business rule that checks approval status on RITM"
    assert sr1.ai_pass_count == 1
    assert str(sr2.id) in sr1.related_result_ids_json


def test_all_reasoning_tables_created(db_engine):
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()

    assert "code_reference" in tables
    assert "update_set_overlap" in tables
    assert "temporal_cluster" in tables
    assert "temporal_cluster_member" in tables
    assert "structural_relationship" in tables
    # Phase 2 additions
    assert "update_set_artifact_link" in tables
    assert "naming_cluster" in tables
    assert "table_colocation_summary" in tables


# -------------------------------------------------------
# Phase 2 data model tests
# -------------------------------------------------------

def test_update_set_overlap_has_signal_type(db_session):
    """UpdateSetOverlap.signal_type field exists and defaults to 'content'."""
    from src.models import UpdateSetOverlap
    assert hasattr(UpdateSetOverlap, "signal_type")

    inst, asmt, sr1, _ = _seed_assessment(db_session)
    us1 = UpdateSet(instance_id=inst.id, sn_sys_id="us_x1", name="US1")
    us2 = UpdateSet(instance_id=inst.id, sn_sys_id="us_x2", name="US2")
    db_session.add_all([us1, us2])
    db_session.flush()

    overlap = UpdateSetOverlap(
        instance_id=inst.id,
        assessment_id=asmt.id,
        update_set_a_id=us1.id,
        update_set_b_id=us2.id,
        shared_record_count=1,
        shared_records_json="[]",
        overlap_score=0.5,
    )
    db_session.add(overlap)
    db_session.commit()
    db_session.refresh(overlap)

    assert overlap.signal_type == "content"
    assert overlap.evidence_json is None


def test_update_set_overlap_signal_type_custom(db_session):
    """UpdateSetOverlap.signal_type can be set to other values."""
    from src.models import UpdateSetOverlap

    inst, asmt, _, _ = _seed_assessment(db_session)
    us1 = UpdateSet(instance_id=inst.id, sn_sys_id="us_y1", name="US Y1")
    us2 = UpdateSet(instance_id=inst.id, sn_sys_id="us_y2", name="US Y2")
    db_session.add_all([us1, us2])
    db_session.flush()

    overlap = UpdateSetOverlap(
        instance_id=inst.id,
        assessment_id=asmt.id,
        update_set_a_id=us1.id,
        update_set_b_id=us2.id,
        shared_record_count=2,
        shared_records_json="[]",
        overlap_score=0.8,
        signal_type="version_history",
        evidence_json='{"chain": "vh_001 -> vh_002"}',
    )
    db_session.add(overlap)
    db_session.commit()
    db_session.refresh(overlap)

    assert overlap.signal_type == "version_history"
    assert "chain" in overlap.evidence_json


def test_update_set_artifact_link_round_trip(db_session):
    from src.models import UpdateSetArtifactLink

    inst, asmt, sr1, _ = _seed_assessment(db_session)
    us = UpdateSet(instance_id=inst.id, sn_sys_id="us_link1", name="Link US")
    db_session.add(us)
    db_session.flush()

    link = UpdateSetArtifactLink(
        instance_id=inst.id,
        assessment_id=asmt.id,
        scan_result_id=sr1.id,
        update_set_id=us.id,
        link_source="scan_result_current",
        is_current=True,
        confidence=1.0,
        evidence_json='{"source": "update_set_id FK"}',
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.id is not None
    assert link.link_source == "scan_result_current"
    assert link.is_current is True
    assert link.evidence_json is not None


def test_update_set_artifact_link_unique_constraint(db_session):
    from src.models import UpdateSetArtifactLink
    from sqlalchemy.exc import IntegrityError
    import pytest

    inst, asmt, sr1, _ = _seed_assessment(db_session)
    us = UpdateSet(instance_id=inst.id, sn_sys_id="us_dup", name="Dup US")
    db_session.add(us)
    db_session.flush()

    link1 = UpdateSetArtifactLink(
        instance_id=inst.id,
        assessment_id=asmt.id,
        scan_result_id=sr1.id,
        update_set_id=us.id,
        link_source="customer_update_xml",
    )
    db_session.add(link1)
    db_session.commit()

    link2 = UpdateSetArtifactLink(
        instance_id=inst.id,
        assessment_id=asmt.id,
        scan_result_id=sr1.id,
        update_set_id=us.id,
        link_source="customer_update_xml",
    )
    db_session.add(link2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_naming_cluster_round_trip(db_session):
    from src.models import NamingCluster

    inst, asmt, sr1, sr2 = _seed_assessment(db_session)

    cluster = NamingCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        cluster_label="RITM Approval",
        pattern_type="prefix",
        member_count=2,
        member_ids_json=json.dumps([sr1.id, sr2.id]),
        tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
        confidence=0.9,
    )
    db_session.add(cluster)
    db_session.commit()
    db_session.refresh(cluster)

    assert cluster.id is not None
    assert cluster.cluster_label == "RITM Approval"
    assert cluster.pattern_type == "prefix"
    assert cluster.member_count == 2


def test_table_colocation_summary_round_trip(db_session):
    from src.models import TableColocationSummary

    inst, asmt, sr1, sr2 = _seed_assessment(db_session)

    summary = TableColocationSummary(
        instance_id=inst.id,
        assessment_id=asmt.id,
        target_table="sc_req_item",
        record_count=2,
        record_ids_json=json.dumps([sr1.id, sr2.id]),
        artifact_types_json=json.dumps(["sys_script", "sys_script_include"]),
        developers_json=json.dumps(["john.doe"]),
    )
    db_session.add(summary)
    db_session.commit()
    db_session.refresh(summary)

    assert summary.id is not None
    assert summary.target_table == "sc_req_item"
    assert summary.record_count == 2


# -------------------------------------------------------
# Phase 3 data model tests
# -------------------------------------------------------


def test_feature_scan_result_phase3_fields_round_trip(db_session):
    from src.models import FeatureScanResult

    _, asmt, sr1, _ = _seed_assessment(db_session)

    feature = Feature(assessment_id=asmt.id, name="Approval Flow")
    db_session.add(feature)
    db_session.flush()

    link = FeatureScanResult(
        feature_id=feature.id,
        scan_result_id=sr1.id,
        is_primary=True,
        membership_type="primary",
        assignment_source="ai",
        assignment_confidence=0.91,
        evidence_json='{"signals":["update_set_overlap","code_reference"]}',
        iteration_number=2,
    )
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    assert link.membership_type == "primary"
    assert link.assignment_source == "ai"
    assert link.assignment_confidence == 0.91
    assert link.iteration_number == 2
    assert "update_set_overlap" in (link.evidence_json or "")


def test_feature_context_artifact_round_trip(db_session):
    from src.models import FeatureContextArtifact

    inst, asmt, sr1, _ = _seed_assessment(db_session)

    feature = Feature(assessment_id=asmt.id, name="Contextual Feature")
    db_session.add(feature)
    db_session.flush()

    ctx = FeatureContextArtifact(
        instance_id=inst.id,
        assessment_id=asmt.id,
        feature_id=feature.id,
        scan_result_id=sr1.id,
        context_type="code_reference_target",
        confidence=0.77,
        evidence_json='{"reference_type":"script_include"}',
        iteration_number=1,
    )
    db_session.add(ctx)
    db_session.commit()
    db_session.refresh(ctx)

    assert ctx.id is not None
    assert ctx.feature_id == feature.id
    assert ctx.context_type == "code_reference_target"
    assert ctx.confidence == 0.77
    assert ctx.iteration_number == 1


def test_feature_grouping_run_round_trip(db_session):
    from src.models import FeatureGroupingRun

    inst, asmt, _, _ = _seed_assessment(db_session)

    run = FeatureGroupingRun(
        instance_id=inst.id,
        assessment_id=asmt.id,
        status="running",
        max_iterations=5,
        iterations_completed=2,
        converged=False,
        summary_json='{"pass":"group_refine","membership_delta":0.14}',
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.max_iterations == 5
    assert run.iterations_completed == 2
    assert run.converged is False
    assert "membership_delta" in (run.summary_json or "")


def test_feature_recommendation_round_trip(db_session):
    from src.models import FeatureRecommendation

    inst, asmt, _, _ = _seed_assessment(db_session)

    feature = Feature(assessment_id=asmt.id, name="Legacy Approval Customization")
    db_session.add(feature)
    db_session.flush()

    rec = FeatureRecommendation(
        instance_id=inst.id,
        assessment_id=asmt.id,
        feature_id=feature.id,
        recommendation_type="replace",
        ootb_capability_name="Flow Designer Approval Actions",
        product_name="ServiceNow ITSM Pro",
        sku_or_license="ITSM_PRO",
        requires_plugins_json='["com.glide.hub.flow_engine"]',
        fit_confidence=0.88,
        rationale="OOTB approval orchestration replaces custom BR + Script Include chain.",
        evidence_json='{"signals":["update_set_overlap","table_colocation"]}',
    )
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)

    assert rec.id is not None
    assert rec.feature_id == feature.id
    assert rec.recommendation_type == "replace"
    assert rec.product_name == "ServiceNow ITSM Pro"
    assert rec.sku_or_license == "ITSM_PRO"
    assert rec.fit_confidence == 0.88


def test_phase3_reasoning_tables_created(db_engine):
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()

    assert "feature_context_artifact" in tables
    assert "feature_grouping_run" in tables
    assert "feature_recommendation" in tables
