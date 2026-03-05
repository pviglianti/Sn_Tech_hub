"""
P3C UI Contract Tests

Validates that the P3B API builder functions return data structures
matching what the P3C JS components (FeatureHierarchyTree.js,
GroupingSignalsPanel.js, result_detail.html grouping-evidence) expect.

These tests protect against contract drift between Codex (API) and
Claude (UI) — if an API shape changes, these tests catch it before
the UI silently renders undefined fields.
"""

import json
from datetime import datetime, timedelta

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    Feature,
    FeatureContextArtifact,
    FeatureRecommendation,
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
    TemporalClusterMember,
    UpdateSet,
    UpdateSetArtifactLink,
    UpdateSetOverlap,
)
from src.server import (
    _build_feature_hierarchy_payload,
    _build_grouping_signals_payload,
    _build_result_grouping_evidence_payload,
)


# ── Shared fixture ────────────────────────────────────────────────────


@pytest.fixture()
def ui_contract_ctx(db_session):
    """
    Minimal data fixture designed specifically for UI contract validation.
    Creates: 1 instance, 1 assessment, 1 scan, 3 results (2 customized + 1 ootb),
    1 feature with members + context, 1 ungrouped result, engine signals,
    and update sets.
    """
    instance = Instance(
        name="ui-contract-inst",
        url="https://uicontract.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.flush()

    assessment = Assessment(
        number="ASMT-UI-001",
        name="UI Contract Test Assessment",
        instance_id=instance.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(assessment)
    db_session.flush()

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="Scan A",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    # r1: customized (modified_ootb) — will be a feature member
    r1 = ScanResult(
        scan_id=scan.id,
        table_name="sys_script",
        name="BR - OnBefore Insert",
        sys_id="sr-ui-001",
        origin_type=OriginType.modified_ootb,
        is_customized=True,
    )
    # r2: customized (net_new_customer) — will be ungrouped
    r2 = ScanResult(
        scan_id=scan.id,
        table_name="sys_ui_action",
        name="Custom UI Action",
        sys_id="sr-ui-002",
        origin_type=OriginType.net_new_customer,
        is_customized=True,
    )
    # r3: not customized (ootb_untouched) — will be context artifact
    r3 = ScanResult(
        scan_id=scan.id,
        table_name="sys_script_include",
        name="OOB Script Include",
        sys_id="sr-ui-003",
        origin_type=OriginType.ootb_untouched,
        is_customized=False,
    )
    db_session.add_all([r1, r2, r3])
    db_session.flush()

    # Feature with r1 as member
    feature = Feature(
        name="Approval Workflow",
        description="Approval automation feature",
        assessment_id=assessment.id,
        instance_id=instance.id,
    )
    db_session.add(feature)
    db_session.flush()

    # r1 → feature member (customized)
    link1 = FeatureScanResult(
        feature_id=feature.id,
        scan_result_id=r1.id,
        is_primary=True,
        membership_type="primary",
        assignment_source="ai",
        assignment_confidence=0.91,
        iteration_number=2,
    )
    # r3 → feature context artifact (non-customized)
    ctx1 = FeatureContextArtifact(
        feature_id=feature.id,
        scan_result_id=r3.id,
        instance_id=instance.id,
        assessment_id=assessment.id,
        context_type="structural_neighbor",
        confidence=0.77,
        iteration_number=1,
    )
    db_session.add_all([link1, ctx1])
    db_session.flush()

    # Engine signals
    now = datetime.utcnow()

    us1 = UpdateSet(
        instance_id=instance.id,
        sn_sys_id="us-ui-001",
        name="US - Approval changes",
    )
    db_session.add(us1)
    db_session.flush()

    us_link = UpdateSetArtifactLink(
        update_set_id=us1.id,
        scan_result_id=r1.id,
        instance_id=instance.id,
        assessment_id=assessment.id,
        link_source="customer_update_xml",
        is_current=True,
        confidence=0.95,
    )
    db_session.add(us_link)

    tc = TemporalCluster(
        assessment_id=assessment.id,
        instance_id=instance.id,
        developer="admin",
        cluster_start=now - timedelta(hours=1),
        cluster_end=now,
        record_count=1,
        record_ids_json=json.dumps([r1.id]),
        avg_gap_minutes=20.0,
        tables_involved_json=json.dumps(["sys_script"]),
    )
    db_session.add(tc)
    db_session.flush()

    tcm = TemporalClusterMember(
        instance_id=instance.id,
        assessment_id=assessment.id,
        temporal_cluster_id=tc.id,
        scan_result_id=r1.id,
    )
    db_session.add(tcm)

    nc = NamingCluster(
        assessment_id=assessment.id,
        instance_id=instance.id,
        cluster_label="Approval*",
        pattern_type="prefix",
        member_count=2,
        member_ids_json=json.dumps([r1.id, r2.id]),
        tables_involved_json=json.dumps(["sys_script", "sys_ui_action"]),
        confidence=0.88,
    )
    db_session.add(nc)
    db_session.flush()

    sr_rel = StructuralRelationship(
        assessment_id=assessment.id,
        instance_id=instance.id,
        parent_scan_result_id=r1.id,
        child_scan_result_id=r3.id,
        relationship_type="ui_policy_binding",
        parent_field="ui_policy",
        confidence=0.8,
    )
    db_session.add(sr_rel)

    tcs = TableColocationSummary(
        assessment_id=assessment.id,
        instance_id=instance.id,
        target_table="sys_script",
        record_count=3,
        record_ids_json=json.dumps([r1.id, r2.id, r3.id]),
        artifact_types_json=json.dumps(["sys_script", "sys_ui_action"]),
        developers_json=json.dumps(["admin"]),
    )
    db_session.add(tcs)

    # Feature recommendation (OOTB replacement)
    rec = FeatureRecommendation(
        instance_id=instance.id,
        assessment_id=assessment.id,
        feature_id=feature.id,
        recommendation_type="replace",
        ootb_capability_name="Approval Engine",
        product_name="ServiceNow ITSM",
        sku_or_license="ITSM Pro",
        requires_plugins_json=json.dumps(["com.snc.change_management"]),
        fit_confidence=0.87,
        rationale="Native approval engine covers all custom approval logic.",
        evidence_json=json.dumps({"signal_count": 3}),
    )
    db_session.add(rec)
    db_session.commit()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.session = db_session
    ctx.assessment = assessment
    ctx.scan = scan
    ctx.r1 = r1
    ctx.r2 = r2
    ctx.r3 = r3
    ctx.feature = feature
    ctx.recommendation = rec
    return ctx


# ── FeatureHierarchyTree.js contract tests ────────────────────────────


def test_hierarchy_summary_object_matches_ui_component(ui_contract_ctx):
    """
    FeatureHierarchyTree.refresh() reads data.summary.feature_count,
    data.summary.customized_member_count, data.summary.ungrouped_customized_count.
    Verify these fields exist and are correct integers.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    assert "summary" in payload
    summary = payload["summary"]
    for key in ("feature_count", "customized_member_count", "context_artifact_count", "ungrouped_customized_count"):
        assert key in summary, f"summary missing '{key}'"
        assert isinstance(summary[key], int), f"summary['{key}'] should be int"

    assert summary["feature_count"] >= 1
    assert summary["customized_member_count"] >= 1


def test_hierarchy_member_rows_have_nested_scan_result(ui_contract_ctx):
    """
    FeatureHierarchyTree._renderMemberRow reads member.scan_result.id,
    member.scan_result.name, member.scan_result.table_name,
    member.scan_result.origin_type, plus member.assignment_source,
    member.assignment_confidence.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    features = payload["features"]
    assert len(features) >= 1

    # Find a feature with members
    feature_node = None
    for f in features:
        if f["members"]:
            feature_node = f
            break
    assert feature_node is not None, "Expected at least one feature with members"

    member = feature_node["members"][0]

    # Nested scan_result object
    assert "scan_result" in member
    sr = member["scan_result"]
    for key in ("id", "name", "table_name", "origin_type", "is_customized"):
        assert key in sr, f"member.scan_result missing '{key}'"

    # Top-level assignment fields
    for key in ("assignment_source", "assignment_confidence", "membership_type", "iteration_number"):
        assert key in member, f"member missing '{key}'"

    # Customized members only
    assert sr["is_customized"] is True


def test_hierarchy_context_rows_have_nested_scan_result(ui_contract_ctx):
    """
    FeatureHierarchyTree._renderContextRow reads ctx.scan_result.id,
    ctx.scan_result.name, ctx.scan_result.table_name,
    plus ctx.context_type and ctx.confidence.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    # Find feature with context artifacts
    feature_node = None
    for f in payload["features"]:
        if f["context_artifacts"]:
            feature_node = f
            break
    assert feature_node is not None, "Expected a feature with context_artifacts"

    ctx = feature_node["context_artifacts"][0]
    assert "scan_result" in ctx
    sr = ctx["scan_result"]
    for key in ("id", "name", "table_name"):
        assert key in sr, f"context.scan_result missing '{key}'"

    for key in ("context_type", "confidence"):
        assert key in ctx, f"context missing '{key}'"


def test_hierarchy_ungrouped_uses_app_file_class_structure(ui_contract_ctx):
    """
    FeatureHierarchyTree._renderUngroupedBucket reads ungrouped_customizations
    as an array of { app_file_class, count, results: [{id, name, table_name, origin_type}] }.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    assert "ungrouped_customizations" in payload
    ungrouped = payload["ungrouped_customizations"]
    assert isinstance(ungrouped, list)

    if ungrouped:
        bucket = ungrouped[0]
        assert "app_file_class" in bucket
        assert "count" in bucket
        assert "results" in bucket
        assert isinstance(bucket["results"], list)
        if bucket["results"]:
            item = bucket["results"][0]
            for key in ("id", "name", "table_name", "origin_type"):
                assert key in item, f"ungrouped result missing '{key}'"


# ── GroupingSignalsPanel.js contract tests ────────────────────────────


_EXPECTED_SIGNAL_TYPES = {
    "update_set_overlap",
    "update_set_artifact_link",
    "code_reference",
    "structural_relationship",
    "temporal_cluster",
    "naming_cluster",
    "table_colocation",
}


def test_signals_counts_include_all_seven_types(ui_contract_ctx):
    """
    GroupingSignalsPanel SIGNAL_TYPE_META has 7 keys. The API must return
    all 7 in signal_counts even if zero-valued.
    """
    payload = _build_grouping_signals_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    assert "signal_counts" in payload
    counts = payload["signal_counts"]
    for stype in _EXPECTED_SIGNAL_TYPES:
        assert stype in counts, f"signal_counts missing '{stype}'"
        assert isinstance(counts[stype], int)


def test_signals_rows_have_links_object_with_member_result_ids(ui_contract_ctx):
    """
    GroupingSignalsPanel._renderSignalRow reads signal.type, signal.label,
    signal.member_count, signal.confidence. The 'links' field must be an
    object (not array) with member_result_ids and member_result_urls.
    """
    payload = _build_grouping_signals_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    signals = payload["signals"]
    assert len(signals) >= 1

    signal = signals[0]
    for key in ("type", "id", "label", "member_count", "confidence", "links"):
        assert key in signal, f"signal missing '{key}'"

    links = signal["links"]
    assert isinstance(links, dict), "links should be dict, not array"
    assert "member_result_ids" in links
    assert "member_result_urls" in links


def test_signals_total_signals_field_present(ui_contract_ctx):
    """
    GroupingSignalsPanel.refresh() reads data.total_signals as fallback badge count.
    """
    payload = _build_grouping_signals_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    assert "total_signals" in payload
    assert isinstance(payload["total_signals"], int)
    assert payload["total_signals"] == len(payload["signals"])


# ── result_detail.html grouping evidence contract tests ───────────────


def test_evidence_has_deterministic_signals_not_generic_signals(ui_contract_ctx):
    """
    result_detail.html reads data.deterministic_signals (NOT data.signals).
    Verify the key name is correct.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    assert "deterministic_signals" in payload
    assert "signals" not in payload  # Should NOT have generic 'signals' key


def test_evidence_has_related_update_sets_structure(ui_contract_ctx):
    """
    result_detail.html reads data.related_update_sets.update_sets and
    data.related_update_sets.overlaps.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    assert "related_update_sets" in payload
    rel_us = payload["related_update_sets"]
    assert "update_sets" in rel_us
    assert "overlaps" in rel_us
    assert isinstance(rel_us["update_sets"], list)
    assert isinstance(rel_us["overlaps"], list)

    if rel_us["update_sets"]:
        us = rel_us["update_sets"][0]
        for key in ("update_set_name", "link_source", "is_current", "confidence"):
            assert key in us, f"update_set missing '{key}'"


def test_evidence_has_related_artifacts_structure(ui_contract_ctx):
    """
    result_detail.html reads data.related_artifacts.customized and
    data.related_artifacts.context, each with scan_result nested object.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    assert "related_artifacts" in payload
    rel_art = payload["related_artifacts"]
    assert "customized" in rel_art
    assert "context" in rel_art
    assert isinstance(rel_art["customized"], list)
    assert isinstance(rel_art["context"], list)


def test_evidence_has_iteration_history(ui_contract_ctx):
    """
    result_detail.html renders iteration_history with iteration_number,
    assignment_source, feature_id.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    assert "iteration_history" in payload
    assert isinstance(payload["iteration_history"], list)

    if payload["iteration_history"]:
        item = payload["iteration_history"][0]
        for key in ("iteration_number", "assignment_source", "feature_id"):
            assert key in item, f"iteration_history item missing '{key}'"


def test_evidence_feature_assignments_have_membership_type(ui_contract_ctx):
    """
    result_detail.html renders fa.membership_type column.
    Verify it's present in the response.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    assert "feature_assignments" in payload
    if payload["feature_assignments"]:
        fa = payload["feature_assignments"][0]
        for key in ("feature_id", "feature_name", "membership_type", "assignment_source",
                     "assignment_confidence", "iteration_number"):
            assert key in fa, f"feature_assignment missing '{key}'"


# ── FeatureRecommendation contract tests (P4C) ──────────────────────────


def test_hierarchy_feature_node_has_recommendations_array(ui_contract_ctx):
    """
    FeatureHierarchyTree._renderFeatureNode reads feature.recommendations
    as an array of recommendation cards.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    # Find the feature that has a recommendation
    feature_node = None
    for f in payload["features"]:
        if f.get("recommendations"):
            feature_node = f
            break
    assert feature_node is not None, "Expected a feature with recommendations"
    assert isinstance(feature_node["recommendations"], list)
    assert len(feature_node["recommendations"]) >= 1


def test_hierarchy_recommendation_card_has_required_fields(ui_contract_ctx):
    """
    FeatureHierarchyTree._renderRecommendationCard reads rec.recommendation_type,
    rec.ootb_capability_name, rec.product_name, rec.sku_or_license,
    rec.requires_plugins, rec.fit_confidence, rec.rationale.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    rec = None
    for f in payload["features"]:
        if f.get("recommendations"):
            rec = f["recommendations"][0]
            break
    assert rec is not None, "Expected at least one recommendation"

    for key in ("id", "recommendation_type", "fit_confidence"):
        assert key in rec, f"recommendation missing required '{key}'"

    # Optional but expected fields from the test fixture
    assert "ootb_capability_name" in rec
    assert "product_name" in rec
    assert "sku_or_license" in rec
    assert "requires_plugins" in rec
    assert "rationale" in rec
    assert "evidence" in rec


def test_hierarchy_recommendation_type_values_valid(ui_contract_ctx):
    """
    JS uses typeColors/typeIcons with keys: replace, refactor, keep, remove.
    Verify the API returns one of these valid values.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    valid_types = {"replace", "refactor", "keep", "remove"}
    for f in payload["features"]:
        for rec in f.get("recommendations", []):
            assert rec["recommendation_type"] in valid_types, (
                f"Invalid recommendation_type: {rec['recommendation_type']}"
            )


def test_hierarchy_recommendation_requires_plugins_is_list(ui_contract_ctx):
    """
    JS does Array.isArray(rec.requires_plugins). API must return a list, not JSON string.
    """
    payload = _build_feature_hierarchy_payload(
        ui_contract_ctx.session,
        assessment_id=ui_contract_ctx.assessment.id,
    )

    for f in payload["features"]:
        for rec in f.get("recommendations", []):
            plugins = rec.get("requires_plugins")
            if plugins is not None:
                assert isinstance(plugins, list), "requires_plugins must be list, not string"


def test_evidence_has_feature_recommendations(ui_contract_ctx):
    """
    result_detail.html reads data.feature_recommendations array.
    Verify it's present and correctly structured.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    assert "feature_recommendations" in payload
    recs = payload["feature_recommendations"]
    assert isinstance(recs, list)

    if recs:
        rec = recs[0]
        for key in ("id", "recommendation_type", "ootb_capability_name",
                     "product_name", "sku_or_license", "requires_plugins",
                     "fit_confidence", "rationale"):
            assert key in rec, f"feature_recommendation missing '{key}'"


def test_evidence_recommendation_confidence_is_float(ui_contract_ctx):
    """
    result_detail.html does Math.round(rec.fit_confidence * 100).
    Verify it's a float, not string.
    """
    payload = _build_result_grouping_evidence_payload(
        ui_contract_ctx.session,
        result_id=ui_contract_ctx.r1.id,
    )

    for rec in payload.get("feature_recommendations", []):
        if rec.get("fit_confidence") is not None:
            assert isinstance(rec["fit_confidence"], float), "fit_confidence must be float"
