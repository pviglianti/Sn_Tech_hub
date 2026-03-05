import json
from datetime import datetime, timedelta

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    Feature,
    FeatureRecommendation,
    FeatureContextArtifact,
    FeatureScanResult,
    Instance,
    NamingCluster,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
    TableColocationSummary,
    TemporalCluster,
    UpdateSet,
    UpdateSetArtifactLink,
    UpdateSetOverlap,
)
from src.server import (
    _build_feature_hierarchy_payload,
    _build_grouping_signals_payload,
    _build_result_grouping_evidence_payload,
)


@pytest.fixture()
def phase3_ctx(db_session):
    instance = Instance(
        name="phase3-inst",
        url="https://phase3.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.flush()

    assessment = Assessment(
        number="ASMT0002001",
        name="Phase 3 Assessment",
        instance_id=instance.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(assessment)
    db_session.flush()

    scan_1 = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="Scan 1",
        status=ScanStatus.completed,
    )
    scan_2 = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="Scan 2",
        status=ScanStatus.completed,
    )
    db_session.add(scan_1)
    db_session.add(scan_2)
    db_session.flush()

    now = datetime.utcnow()
    r1 = ScanResult(
        scan_id=scan_1.id,
        sys_id="r1",
        table_name="sys_script",
        name="Approval BR",
        origin_type=OriginType.modified_ootb,
        sys_updated_on=now,
    )
    r2 = ScanResult(
        scan_id=scan_1.id,
        sys_id="r2",
        table_name="sys_script_include",
        name="ApprovalHelper",
        origin_type=OriginType.net_new_customer,
        sys_updated_on=now - timedelta(minutes=1),
    )
    r3 = ScanResult(
        scan_id=scan_1.id,
        sys_id="r3",
        table_name="sys_ui_policy",
        name="Approval UI Policy",
        origin_type=OriginType.ootb_untouched,
        sys_updated_on=now - timedelta(minutes=2),
    )
    r4 = ScanResult(
        scan_id=scan_2.id,
        sys_id="r4",
        table_name="sys_script",
        name="Escalation BR",
        origin_type=OriginType.modified_ootb,
        sys_updated_on=now - timedelta(minutes=3),
    )
    db_session.add_all([r1, r2, r3, r4])
    db_session.flush()

    us1 = UpdateSet(
        instance_id=instance.id,
        sn_sys_id="us1",
        name="Approval Feature",
        state="complete",
    )
    us2 = UpdateSet(
        instance_id=instance.id,
        sn_sys_id="us2",
        name="Escalation Feature",
        state="complete",
    )
    db_session.add_all([us1, us2])
    db_session.flush()

    db_session.add(
        UpdateSetArtifactLink(
            instance_id=instance.id,
            assessment_id=assessment.id,
            scan_result_id=r1.id,
            update_set_id=us1.id,
            link_source="customer_update_xml",
            confidence=0.95,
            evidence_json='{"reason":"matched update_guid"}',
        )
    )
    db_session.add(
        UpdateSetArtifactLink(
            instance_id=instance.id,
            assessment_id=assessment.id,
            scan_result_id=r4.id,
            update_set_id=us2.id,
            link_source="scan_result_current",
            confidence=1.0,
            is_current=True,
        )
    )
    db_session.add(
        UpdateSetOverlap(
            instance_id=instance.id,
            assessment_id=assessment.id,
            update_set_a_id=us1.id,
            update_set_b_id=us2.id,
            shared_record_count=2,
            shared_records_json=json.dumps([{"scan_result_id": r1.id}, {"scan_result_id": r4.id}]),
            overlap_score=0.71,
            signal_type="temporal_sequence",
            evidence_json='{"adjacent_commits": true}',
        )
    )

    db_session.add(
        CodeReference(
            instance_id=instance.id,
            assessment_id=assessment.id,
            source_scan_result_id=r1.id,
            source_table="sys_script",
            source_field="script",
            source_name=r1.name,
            reference_type="script_include",
            target_identifier=r2.name,
            target_scan_result_id=r2.id,
            line_number=18,
            confidence=0.9,
        )
    )
    db_session.add(
        StructuralRelationship(
            instance_id=instance.id,
            assessment_id=assessment.id,
            parent_scan_result_id=r1.id,
            child_scan_result_id=r3.id,
            relationship_type="ui_policy_binding",
            parent_field="ui_policy",
            confidence=0.8,
        )
    )
    db_session.add(
        TemporalCluster(
            instance_id=instance.id,
            assessment_id=assessment.id,
            developer="admin",
            cluster_start=now - timedelta(hours=1),
            cluster_end=now,
            record_count=2,
            record_ids_json=json.dumps([r1.id, r4.id]),
            avg_gap_minutes=20.0,
            tables_involved_json=json.dumps(["sys_script"]),
        )
    )
    db_session.add(
        NamingCluster(
            instance_id=instance.id,
            assessment_id=assessment.id,
            cluster_label="Approval*",
            pattern_type="prefix",
            member_count=2,
            member_ids_json=json.dumps([r1.id, r2.id]),
            tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
            confidence=0.88,
        )
    )
    db_session.add(
        TableColocationSummary(
            instance_id=instance.id,
            assessment_id=assessment.id,
            target_table="sc_req_item",
            record_count=3,
            record_ids_json=json.dumps([r1.id, r2.id, r3.id]),
            artifact_types_json=json.dumps(["sys_script", "sys_script_include", "sys_ui_policy"]),
            developers_json=json.dumps(["admin"]),
        )
    )

    feature_root = Feature(assessment_id=assessment.id, name="Approval Workflow")
    feature_child = Feature(assessment_id=assessment.id, name="Approval UI", parent_id=None)
    db_session.add(feature_root)
    db_session.flush()
    feature_child.parent_id = feature_root.id
    db_session.add(feature_child)
    db_session.flush()

    db_session.add(
        FeatureScanResult(
            feature_id=feature_root.id,
            scan_result_id=r1.id,
            membership_type="primary",
            assignment_source="ai",
            assignment_confidence=0.92,
            iteration_number=2,
            evidence_json='{"signals":["update_set_overlap","code_reference"]}',
        )
    )
    db_session.add(
        FeatureScanResult(
            feature_id=feature_root.id,
            scan_result_id=r3.id,
            membership_type="supporting",
            assignment_source="engine",
            assignment_confidence=0.6,
            iteration_number=1,
            evidence_json='{"signals":["structural_relationship"]}',
        )
    )
    db_session.add(
        FeatureScanResult(
            feature_id=feature_child.id,
            scan_result_id=r1.id,
            membership_type="supporting",
            assignment_source="engine",
            assignment_confidence=0.7,
            iteration_number=1,
            evidence_json='{"signals":["table_colocation"]}',
        )
    )
    db_session.add(
        FeatureScanResult(
            feature_id=feature_child.id,
            scan_result_id=r2.id,
            membership_type="primary",
            assignment_source="engine",
            assignment_confidence=0.85,
            iteration_number=1,
            evidence_json='{"signals":["naming_cluster"]}',
        )
    )

    db_session.add(
        FeatureContextArtifact(
            instance_id=instance.id,
            assessment_id=assessment.id,
            feature_id=feature_root.id,
            scan_result_id=r3.id,
            context_type="structural_neighbor",
            confidence=0.76,
            iteration_number=2,
            evidence_json='{"relation":"ui_policy_binding"}',
        )
    )
    db_session.add(
        FeatureContextArtifact(
            instance_id=instance.id,
            assessment_id=assessment.id,
            feature_id=feature_child.id,
            scan_result_id=r4.id,
            context_type="temporal_neighbor",
            confidence=0.66,
            iteration_number=1,
            evidence_json='{"cluster":"admin-window"}',
        )
    )

    db_session.commit()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.session = db_session
    ctx.instance = instance
    ctx.assessment = assessment
    ctx.scan_1 = scan_1
    ctx.scan_2 = scan_2
    ctx.r1 = r1
    ctx.r2 = r2
    ctx.r3 = r3
    ctx.r4 = r4
    ctx.feature_root = feature_root
    ctx.feature_child = feature_child
    return ctx


def _flatten_feature_nodes(nodes):
    flat = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        flat.append(node)
        stack.extend(node.get("children", []))
    return flat


def test_grouping_signals_assessment_scope_returns_unified_shape(phase3_ctx):
    payload = _build_grouping_signals_payload(
        phase3_ctx.session,
        assessment_id=phase3_ctx.assessment.id,
    )

    assert "signal_counts" in payload
    assert "signals" in payload
    assert payload["signal_counts"]["update_set_overlap"] >= 1
    assert payload["signal_counts"]["temporal_cluster"] >= 1
    assert payload["signal_counts"]["naming_cluster"] >= 1

    first = payload["signals"][0]
    for key in ("type", "id", "label", "member_count", "confidence", "links"):
        assert key in first
    assert "member_result_ids" in first["links"]


def test_grouping_signals_scan_scope_filters_members_to_scan(phase3_ctx):
    payload = _build_grouping_signals_payload(
        phase3_ctx.session,
        assessment_id=phase3_ctx.assessment.id,
        scan_id=phase3_ctx.scan_1.id,
    )

    scan_1_ids = {phase3_ctx.r1.id, phase3_ctx.r2.id, phase3_ctx.r3.id}
    for row in payload["signals"]:
        member_ids = set(row["links"]["member_result_ids"])
        assert member_ids.issubset(scan_1_ids)
    assert all(phase3_ctx.r4.id not in row["links"]["member_result_ids"] for row in payload["signals"])


def test_feature_hierarchy_separates_members_context_and_ungrouped(phase3_ctx):
    payload = _build_feature_hierarchy_payload(
        phase3_ctx.session,
        assessment_id=phase3_ctx.assessment.id,
    )

    all_nodes = _flatten_feature_nodes(payload["features"])
    root = next(node for node in all_nodes if node["id"] == phase3_ctx.feature_root.id)
    root_member_ids = {member["scan_result"]["id"] for member in root["members"]}
    root_context_ids = {ctx["scan_result"]["id"] for ctx in root["context_artifacts"]}

    assert phase3_ctx.r1.id in root_member_ids
    assert phase3_ctx.r3.id not in root_member_ids
    assert phase3_ctx.r3.id in root_context_ids

    ungrouped_ids = {
        row["id"]
        for bucket in payload["ungrouped_customizations"]
        for row in bucket["results"]
    }
    assert phase3_ctx.r4.id in ungrouped_ids
    assert phase3_ctx.r3.id not in ungrouped_ids


def test_result_grouping_evidence_returns_assignments_signals_and_history(phase3_ctx):
    payload = _build_result_grouping_evidence_payload(
        phase3_ctx.session,
        result_id=phase3_ctx.r1.id,
    )

    assert payload["result"]["id"] == phase3_ctx.r1.id
    assert len(payload["feature_assignments"]) >= 2
    assert any(item["assignment_source"] == "ai" for item in payload["feature_assignments"])
    assert payload["deterministic_signals"]
    assert payload["related_update_sets"]["update_sets"]

    history_iterations = [item["iteration_number"] for item in payload["iteration_history"]]
    assert history_iterations == sorted(history_iterations)


def test_feature_recommendations_are_exposed_in_hierarchy_and_result_evidence(phase3_ctx):
    rec = FeatureRecommendation(
        instance_id=phase3_ctx.instance.id,
        assessment_id=phase3_ctx.assessment.id,
        feature_id=phase3_ctx.feature_root.id,
        recommendation_type="replace",
        ootb_capability_name="Flow Designer Approval",
        product_name="ServiceNow ITSM Pro",
        sku_or_license="ITSM_PRO",
        fit_confidence=0.87,
        rationale="OOTB flow actions replace custom approval chain.",
        evidence_json='{"signals":["code_reference","update_set_overlap"]}',
    )
    phase3_ctx.session.add(rec)
    phase3_ctx.session.commit()

    hierarchy = _build_feature_hierarchy_payload(
        phase3_ctx.session,
        assessment_id=phase3_ctx.assessment.id,
    )
    all_nodes = _flatten_feature_nodes(hierarchy["features"])
    root = next(node for node in all_nodes if node["id"] == phase3_ctx.feature_root.id)
    assert root["recommendations"]
    assert root["recommendations"][0]["product_name"] == "ServiceNow ITSM Pro"

    evidence = _build_result_grouping_evidence_payload(
        phase3_ctx.session,
        result_id=phase3_ctx.r1.id,
    )
    assert evidence["feature_recommendations"]
    assert any(item["id"] == rec.id for item in evidence["feature_recommendations"])
