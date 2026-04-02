import json
from datetime import datetime

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    Feature,
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


def test_feature_grouping_status_reports_bucket_and_mixed_feature_counts(db_session):
    from src.mcp.tools.pipeline.feature_grouping_status import handle as run_status
    from src.services.feature_governance import refresh_feature_metadata

    asmt, r1, r2, _ = _seed_assessment_with_signals(db_session)
    r2.is_adjacent = True
    db_session.add(r2)
    db_session.flush()

    solution_feature = Feature(
        assessment_id=asmt.id,
        name="Working Feature 01",
        feature_kind="functional",
        name_status="provisional",
    )
    bucket_feature = Feature(
        assessment_id=asmt.id,
        name="ACL",
        feature_kind="bucket",
        name_status="final",
        bucket_key="acl",
    )
    db_session.add(solution_feature)
    db_session.add(bucket_feature)
    db_session.flush()

    db_session.add(
        FeatureScanResult(
            feature_id=solution_feature.id,
            scan_result_id=r1.id,
            assignment_source="ai",
            is_primary=True,
        )
    )
    db_session.add(
        FeatureScanResult(
            feature_id=solution_feature.id,
            scan_result_id=r2.id,
            assignment_source="ai",
            is_primary=True,
        )
    )

    r4 = ScanResult(
        scan_id=r1.scan_id,
        sys_id="r4",
        table_name="sys_security_acl",
        name="ACL Leftover",
        origin_type=OriginType.modified_ootb,
        is_adjacent=True,
    )
    db_session.add(r4)
    db_session.flush()
    db_session.add(
        FeatureScanResult(
            feature_id=bucket_feature.id,
            scan_result_id=r4.id,
            assignment_source="ai",
            is_primary=True,
        )
    )
    refresh_feature_metadata(db_session, assessment_id=asmt.id, commit=False)
    db_session.commit()

    status = run_status({"assessment_id": asmt.id}, db_session)
    assert status["success"] is True
    coverage = status["coverage"]
    assert coverage["bucket_feature_count"] == 1
    assert coverage["provisional_feature_count"] == 1
    assert coverage["composition_counts"]["mixed"] >= 1
    assert coverage["all_in_scope_assigned"] is True


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


def test_seed_feature_groups_skips_out_of_scope_and_uses_ai_relationships(db_session):
    from src.mcp.tools.pipeline.seed_feature_groups import handle

    asmt, r1, r2, _ = _seed_assessment_with_signals(db_session)
    r2.is_out_of_scope = True
    db_session.add(r2)
    db_session.commit()

    result = handle({"assessment_id": asmt.id}, db_session)
    assert result["success"] is True

    links = db_session.exec(select(FeatureScanResult)).all()
    assert all(link.scan_result_id != r2.id for link in links)


def test_seed_feature_groups_can_use_ai_relationship_ids_without_engine_signals(db_session):
    from src.mcp.tools.pipeline.seed_feature_groups import handle

    asmt, r1, r2, _ = _seed_assessment_with_signals(db_session)
    code_refs = db_session.exec(select(CodeReference)).all()
    for row in code_refs:
        db_session.delete(row)
    naming_rows = db_session.exec(select(NamingCluster)).all()
    for row in naming_rows:
        db_session.delete(row)

    r1.ai_observations = json.dumps(
        {
            "analysis_stage": "ai_analysis",
            "scope_decision": "in_scope",
            "directly_related_result_ids": [r2.id],
        }
    )
    r2.ai_observations = json.dumps(
        {
            "analysis_stage": "ai_analysis",
            "scope_decision": "in_scope",
            "directly_related_result_ids": [r1.id],
        }
    )
    db_session.add(r1)
    db_session.add(r2)
    db_session.commit()

    result = handle({"assessment_id": asmt.id}, db_session)
    assert result["success"] is True
    assert result["grouped_count"] >= 2

    links = db_session.exec(select(FeatureScanResult)).all()
    assert any(link.scan_result_id == r1.id for link in links)
    assert any(link.scan_result_id == r2.id for link in links)


def test_group_by_feature_preserves_human_links(db_session):
    """Re-running group_by_feature must preserve human-authored feature links."""
    from src.mcp.tools.pipeline.feature_grouping import handle as group_handle
    from src.models import Feature

    asmt, r1, _, _ = _seed_assessment_with_signals(db_session)

    manual_feature = Feature(assessment_id=asmt.id, name="Human Feature")
    db_session.add(manual_feature)
    db_session.flush()
    human_link = FeatureScanResult(
        feature_id=manual_feature.id,
        scan_result_id=r1.id,
        is_primary=True,
        assignment_source="human",
    )
    db_session.add(human_link)
    db_session.commit()

    result = group_handle({"assessment_id": asmt.id}, db_session)
    assert result["success"] is True

    db_session.expire_all()
    surviving = db_session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == manual_feature.id,
            FeatureScanResult.scan_result_id == r1.id,
        )
    ).first()
    assert surviving is not None
    assert surviving.assignment_source == "human"


def test_group_by_feature_only_links_customized(db_session):
    """group_by_feature should only create links for customized results, not OOTB."""
    from src.mcp.tools.pipeline.feature_grouping import handle as group_handle

    asmt, _, _, r3 = _seed_assessment_with_signals(db_session)

    result = group_handle({"assessment_id": asmt.id, "min_group_size": 1}, db_session)
    assert result["success"] is True

    link_for_ootb = db_session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == r3.id)
    ).first()
    assert link_for_ootb is None


def test_mcp_registry_uses_new_feature_grouping_tools():
    from src.mcp.registry import build_registry

    registry = build_registry()
    assert registry.has_tool("seed_feature_groups")
    assert registry.has_tool("get_suggested_groupings")
    assert registry.has_tool("run_feature_reasoning")
    assert registry.has_tool("feature_grouping_status")
    assert registry.has_tool("generate_observations")
    assert registry.has_tool("get_usage_count")
    assert not registry.has_tool("group_by_feature")


# ---------------------------------------------------------------------------
# dry_run / get_suggested_groupings tests
# ---------------------------------------------------------------------------


def test_seed_feature_groups_dry_run_writes_nothing(db_session):
    """dry_run=True computes suggestions but creates no Feature/FeatureScanResult/Context rows."""
    from src.mcp.tools.pipeline.seed_feature_groups import handle
    from src.models import Feature

    asmt, r1, r2, r3 = _seed_assessment_with_signals(db_session)

    result = handle({"assessment_id": asmt.id, "dry_run": True}, db_session)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["cluster_count"] >= 1
    assert result["grouped_count"] >= 2
    assert result["features_created"] == 0  # no writes in dry_run

    # Verify suggested_groups payload is populated
    assert "suggested_groups" in result
    assert len(result["suggested_groups"]) >= 1
    group = result["suggested_groups"][0]
    assert "suggested_feature_name" in group
    assert "member_result_ids" in group
    assert "members" in group
    assert "signal_counts" in group
    assert "confidence_score" in group
    assert r1.id in group["member_result_ids"] or r2.id in group["member_result_ids"]

    # Verify NO DB records were created
    features = db_session.exec(select(Feature).where(Feature.assessment_id == asmt.id)).all()
    assert len(features) == 0
    links = db_session.exec(select(FeatureScanResult)).all()
    assert len(links) == 0
    contexts = db_session.exec(select(FeatureContextArtifact)).all()
    assert len(contexts) == 0


def test_get_suggested_groupings_tool_is_read_only(db_session):
    """get_suggested_groupings tool handler returns suggestions without DB writes."""
    from src.mcp.tools.pipeline.seed_feature_groups import handle_suggestions
    from src.models import Feature

    asmt, r1, r2, r3 = _seed_assessment_with_signals(db_session)

    result = handle_suggestions({"assessment_id": asmt.id}, db_session)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert "suggested_groups" in result
    assert len(result["suggested_groups"]) >= 1

    # Confirm zero writes
    features = db_session.exec(select(Feature).where(Feature.assessment_id == asmt.id)).all()
    assert len(features) == 0
    links = db_session.exec(select(FeatureScanResult)).all()
    assert len(links) == 0


def test_seed_feature_groups_write_mode_still_creates_records(db_session):
    """Default (dry_run=False) write path still creates Feature + FeatureScanResult rows (api mode)."""
    from src.mcp.tools.pipeline.seed_feature_groups import handle
    from src.models import Feature

    asmt, r1, r2, r3 = _seed_assessment_with_signals(db_session)

    result = handle({"assessment_id": asmt.id}, db_session)
    assert result["success"] is True
    assert result["dry_run"] is False
    assert result["features_created"] >= 1

    features = db_session.exec(select(Feature).where(Feature.assessment_id == asmt.id)).all()
    assert len(features) >= 1
    links = db_session.exec(select(FeatureScanResult)).all()
    assert len(links) >= 2  # r1 and r2 should be members


def test_dry_run_and_write_produce_same_groupings(db_session):
    """dry_run suggestions and write-mode clusters have matching member sets."""
    from src.mcp.tools.pipeline.seed_feature_groups import seed_feature_groups

    asmt, r1, r2, r3 = _seed_assessment_with_signals(db_session)

    # First: dry_run
    dry = seed_feature_groups(
        db_session, assessment_id=asmt.id, dry_run=True, commit=False,
    )
    dry_member_sets = [
        set(g["member_result_ids"]) for g in dry["suggested_groups"]
    ]

    # Then: write
    write = seed_feature_groups(
        db_session, assessment_id=asmt.id, dry_run=False, commit=False,
    )
    write_member_sets = []
    for cluster in write["clusters"]:
        fid = cluster["feature_id"]
        member_ids = {
            int(link.scan_result_id)
            for link in db_session.exec(
                select(FeatureScanResult).where(FeatureScanResult.feature_id == fid)
            ).all()
        }
        write_member_sets.append(member_ids)

    assert len(dry_member_sets) == len(write_member_sets)
    for dry_set in dry_member_sets:
        assert dry_set in write_member_sets
