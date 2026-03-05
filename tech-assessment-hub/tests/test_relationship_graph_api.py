import json
from datetime import datetime

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
)
from src.server import _build_relationship_graph_payload


@pytest.fixture()
def graph_ctx(db_session):
    instance = Instance(
        name="graph-inst",
        url="https://graph.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.flush()

    assessment = Assessment(
        number="ASMT0091001",
        name="Graph Assessment",
        instance_id=instance.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(assessment)
    db_session.flush()

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="Graph Scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    now = datetime.utcnow()

    table_result = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000011",
        table_name="sys_db_object",
        name="incident",
        origin_type=OriginType.ootb_untouched,
        raw_data_json=json.dumps({"name": "incident"}),
        sys_updated_on=now,
    )
    ui_policy = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000022",
        table_name="sys_ui_policy",
        name="VIP Policy",
        origin_type=OriginType.net_new_customer,
        meta_target_table="incident",
        raw_data_json=json.dumps({"table": "incident"}),
        sys_updated_on=now,
    )
    ui_policy_action = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000033",
        table_name="sys_ui_policy_action",
        name="Set VIP Mandatory",
        origin_type=OriginType.modified_ootb,
        meta_target_table="incident",
        raw_data_json=json.dumps({
            "ui_policy": {"value": "00000000000000000000000000000022"},
            "table": "incident",
        }),
        sys_updated_on=now,
    )
    dictionary_result = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000044",
        table_name="sys_dictionary",
        name="incident.u_vip_level",
        origin_type=OriginType.net_new_customer,
        raw_data_json=json.dumps({"name": "incident", "element": "u_vip_level"}),
        sys_updated_on=now,
    )
    choice_result = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000055",
        table_name="sys_choice",
        name="VIP Choice",
        origin_type=OriginType.net_new_customer,
        raw_data_json=json.dumps({"name": "incident", "element": "u_vip_level"}),
        sys_updated_on=now,
    )
    script_include = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000066",
        table_name="sys_script_include",
        name="VIPUtils",
        origin_type=OriginType.net_new_customer,
        sys_updated_on=now,
    )
    business_rule = ScanResult(
        scan_id=scan.id,
        sys_id="00000000000000000000000000000077",
        table_name="sys_script",
        name="BR VIP Route",
        origin_type=OriginType.modified_ootb,
        raw_data_json=json.dumps({"table": "incident"}),
        sys_updated_on=now,
    )

    db_session.add_all([
        table_result,
        ui_policy,
        ui_policy_action,
        dictionary_result,
        choice_result,
        script_include,
        business_rule,
    ])
    db_session.flush()

    db_session.add(
        StructuralRelationship(
            instance_id=instance.id,
            assessment_id=assessment.id,
            parent_scan_result_id=ui_policy.id,
            child_scan_result_id=ui_policy_action.id,
            relationship_type="ui_policy_action",
            parent_field="ui_policy",
            confidence=1.0,
        )
    )
    db_session.add(
        CodeReference(
            instance_id=instance.id,
            assessment_id=assessment.id,
            source_scan_result_id=business_rule.id,
            source_table="sys_script",
            source_field="script",
            source_name=business_rule.name,
            reference_type="script_include",
            target_identifier=script_include.name,
            target_scan_result_id=script_include.id,
            confidence=0.93,
        )
    )

    feature = Feature(assessment_id=assessment.id, name="VIP Routing")
    db_session.add(feature)
    db_session.flush()
    db_session.add(FeatureScanResult(feature_id=feature.id, scan_result_id=business_rule.id, membership_type="primary"))
    db_session.add(FeatureScanResult(feature_id=feature.id, scan_result_id=script_include.id, membership_type="supporting"))

    db_session.commit()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.instance = instance
    ctx.assessment = assessment
    ctx.scan = scan
    ctx.table_result = table_result
    ctx.ui_policy = ui_policy
    ctx.ui_policy_action = ui_policy_action
    ctx.dictionary_result = dictionary_result
    ctx.choice_result = choice_result
    ctx.script_include = script_include
    ctx.business_rule = business_rule
    ctx.feature = feature
    return ctx


def _result_ids(payload):
    ids = []
    for node in payload.get("nodes", []):
        if node.get("node_type") == "artifact" and node.get("result_id") is not None:
            ids.append(int(node.get("result_id")))
    return ids


def test_relationship_graph_artifact_mode_infers_reference_and_target_table(graph_ctx, db_session):
    payload = _build_relationship_graph_payload(
        db_session,
        result_id=graph_ctx.ui_policy_action.id,
        assessment_id=graph_ctx.assessment.id,
        max_neighbors=30,
    )

    result_ids = _result_ids(payload)
    assert graph_ctx.ui_policy.id in result_ids
    assert graph_ctx.table_result.id in result_ids

    edge_types = {edge.get("edge_type") for edge in payload.get("edges", [])}
    assert "reference_field" in edge_types
    assert "target_table" in edge_types


def test_relationship_graph_artifact_mode_honors_exclude_ids(graph_ctx, db_session):
    payload = _build_relationship_graph_payload(
        db_session,
        result_id=graph_ctx.ui_policy_action.id,
        assessment_id=graph_ctx.assessment.id,
        max_neighbors=30,
        exclude_result_ids=[graph_ctx.ui_policy.id, graph_ctx.table_result.id],
    )

    result_ids = _result_ids(payload)
    assert graph_ctx.ui_policy.id not in result_ids
    assert graph_ctx.table_result.id not in result_ids


def test_relationship_graph_feature_mode_centers_feature(graph_ctx, db_session):
    payload = _build_relationship_graph_payload(
        db_session,
        feature_id=graph_ctx.feature.id,
        assessment_id=graph_ctx.assessment.id,
        max_neighbors=30,
    )

    assert payload.get("mode") == "feature"
    assert payload.get("center_node", {}).get("node_type") == "feature"
    result_ids = _result_ids(payload)
    assert graph_ctx.business_rule.id in result_ids
    assert graph_ctx.script_include.id in result_ids


def test_relationship_graph_table_mode_returns_table_center(graph_ctx, db_session):
    payload = _build_relationship_graph_payload(
        db_session,
        table_name="sys_ui_policy_action",
        assessment_id=graph_ctx.assessment.id,
        max_neighbors=30,
    )

    center = payload.get("center_node") or {}
    assert payload.get("mode") == "table"
    assert center.get("node_type") == "table"
    assert center.get("table_name") == "sys_ui_policy_action"


def test_relationship_graph_api_requires_single_seed(client):
    response = client.get("/api/relationship-graph/neighborhood")
    assert response.status_code == 400


def test_relationship_graph_page_renders(client, graph_ctx):
    response = client.get(
        f"/relationship-graph?result_id={graph_ctx.ui_policy_action.id}&assessment_id={graph_ctx.assessment.id}"
    )
    assert response.status_code == 200
    assert "Relationship Graph" in response.text
