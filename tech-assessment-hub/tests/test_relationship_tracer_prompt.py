"""Tests for the relationship_tracer MCP prompt."""

import json

import pytest
from sqlmodel import Session

# Import registry first to avoid circular import when importing the prompt
# module directly (registry._populate_prompt_registry runs at module level).
import src.mcp.registry  # noqa: F401

from src.models import (
    Assessment, AssessmentState, AssessmentType, Feature,
    FeatureScanResult, Instance, NamingCluster, OriginType,
    Scan, ScanResult, ScanStatus, ScanType,
    StructuralRelationship, UpdateSet, UpdateSetArtifactLink,
)


def _seed_base(session: Session):
    """Create the shared Instance -> Assessment -> Scan -> ScanResult chain."""
    inst = Instance(
        name="test", url="https://test.service-now.com",
        username="admin", password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id, name="Test Assessment", number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="Test Scan", status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    sr = ScanResult(
        scan_id=scan.id, sys_id="abc123", name="My Business Rule",
        table_name="sys_script",
        origin_type=OriginType.net_new_customer,
        meta_target_table="incident",
        raw_data_json=json.dumps({
            "script": "(function executeRule(current, previous) {\n  current.update();\n})(current, previous);",
        }),
        observations="Fires on incident insert.",
    )
    session.add(sr)
    session.commit()
    session.refresh(sr)
    return inst, asmt, scan, sr


# ── Test: starting artifact context ──────────────────────────────

def test_relationship_tracer_returns_messages_with_starting_artifact(db_session: Session):
    """Handler returns messages containing the starting artifact's metadata."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, _scan, sr = _seed_base(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )

    assert "messages" in result
    assert len(result["messages"]) >= 1
    text = result["messages"][0]["content"]["text"]
    # Artifact metadata
    assert "My Business Rule" in text
    assert "sys_script" in text
    assert "incident" in text  # meta_target_table or target table
    # Code snippet should be present
    assert "current.update()" in text


# ── Test: structural relationships ───────────────────────────────

def test_relationship_tracer_includes_structural_relationships(db_session: Session):
    """When StructuralRelationship rows exist, they appear in the output."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, scan, sr = _seed_base(db_session)

    # Create a child artifact
    child_sr = ScanResult(
        scan_id=scan.id, sys_id="child456", name="Incident UI Policy",
        table_name="sys_ui_policy",
        origin_type=OriginType.net_new_customer,
    )
    db_session.add(child_sr)
    db_session.flush()

    rel = StructuralRelationship(
        instance_id=inst.id, assessment_id=asmt.id,
        parent_scan_result_id=sr.id, child_scan_result_id=child_sr.id,
        relationship_type="parent_child", parent_field="collection",
    )
    db_session.add(rel)
    db_session.commit()

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Incident UI Policy" in text
    assert "sys_ui_policy" in text


# ── Test: update set siblings ────────────────────────────────────

def test_relationship_tracer_includes_update_set_siblings(db_session: Session):
    """Artifacts sharing the same update set are listed as siblings."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, scan, sr = _seed_base(db_session)

    # Create update set + link for starting artifact
    us = UpdateSet(instance_id=inst.id, sn_sys_id="us-001", name="INC Feature Set")
    db_session.add(us)
    db_session.flush()
    link1 = UpdateSetArtifactLink(
        instance_id=inst.id, assessment_id=asmt.id,
        scan_result_id=sr.id, update_set_id=us.id,
        link_source="scan_result_current",
    )
    db_session.add(link1)
    db_session.flush()

    # Create a sibling artifact in the same update set
    sibling = ScanResult(
        scan_id=scan.id, sys_id="sib789", name="Sibling Script Include",
        table_name="sys_script_include",
        origin_type=OriginType.net_new_customer,
    )
    db_session.add(sibling)
    db_session.flush()
    link2 = UpdateSetArtifactLink(
        instance_id=inst.id, assessment_id=asmt.id,
        scan_result_id=sibling.id, update_set_id=us.id,
        link_source="scan_result_current",
    )
    db_session.add(link2)
    db_session.commit()

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "INC Feature Set" in text
    assert "Sibling Script Include" in text


# ── Test: table-level neighbors ──────────────────────────────────

def test_relationship_tracer_includes_table_neighbors(db_session: Session):
    """Other artifacts on the same table_name are included as table neighbors."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, scan, sr = _seed_base(db_session)

    # Another artifact on the same table (sys_script targeting incident)
    neighbor = ScanResult(
        scan_id=scan.id, sys_id="neigh001", name="Another Incident BR",
        table_name="sys_script",
        origin_type=OriginType.modified_ootb,
        meta_target_table="incident",
    )
    db_session.add(neighbor)
    db_session.commit()

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Another Incident BR" in text


# ── Test: naming cluster context ─────────────────────────────────

def test_relationship_tracer_includes_naming_cluster(db_session: Session):
    """When the artifact belongs to a NamingCluster, include cluster info."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, scan, sr = _seed_base(db_session)

    cluster = NamingCluster(
        instance_id=inst.id, assessment_id=asmt.id,
        cluster_label="INC_Custom",
        pattern_type="prefix",
        member_count=3,
        member_ids_json=json.dumps([sr.id, 999, 1000]),
        tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
    )
    db_session.add(cluster)
    db_session.commit()

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "INC_Custom" in text
    assert "prefix" in text


# ── Test: feature context ────────────────────────────────────────

def test_relationship_tracer_includes_feature_context(db_session: Session):
    """When FeatureScanResult links exist, include feature name + members."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, scan, sr = _seed_base(db_session)

    feature = Feature(assessment_id=asmt.id, name="Incident Automation")
    db_session.add(feature)
    db_session.flush()

    fsr = FeatureScanResult(feature_id=feature.id, scan_result_id=sr.id)
    db_session.add(fsr)
    db_session.commit()

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Incident Automation" in text


# ── Test: no session (graceful fallback) ─────────────────────────

def test_relationship_tracer_no_session_returns_static():
    """When session is None, handler returns static prompt text."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": "1", "assessment_id": "1"},
        session=None,
    )
    assert "messages" in result
    text = result["messages"][0]["content"]["text"]
    # Should contain the static analysis instructions
    assert "dependency" in text.lower() or "relationship" in text.lower()
    # Should note that no session is available
    assert "No database session" in text


# ── Test: missing result_id raises ValueError ────────────────────

def test_relationship_tracer_missing_result_raises(db_session: Session):
    """Passing a non-existent result_id raises ValueError."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    handler = PROMPT_SPECS[0].handler
    with pytest.raises(ValueError, match="ScanResult not found"):
        handler(
            {"result_id": "99999", "assessment_id": "1"},
            session=db_session,
        )


# ── Test: direction parameter ────────────────────────────────────

def test_relationship_tracer_accepts_direction_param(db_session: Session):
    """Handler accepts direction parameter without error."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, scan, sr = _seed_base(db_session)

    # Create a parent relationship (sr is the child)
    parent_sr = ScanResult(
        scan_id=scan.id, sys_id="parent001", name="Parent Dictionary",
        table_name="sys_dictionary",
        origin_type=OriginType.modified_ootb,
    )
    db_session.add(parent_sr)
    db_session.flush()
    rel = StructuralRelationship(
        instance_id=inst.id, assessment_id=asmt.id,
        parent_scan_result_id=parent_sr.id, child_scan_result_id=sr.id,
        relationship_type="field_owner", parent_field="name",
    )
    db_session.add(rel)
    db_session.commit()

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {
            "result_id": str(sr.id),
            "assessment_id": str(asmt.id),
            "direction": "inward",
        },
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Parent Dictionary" in text


# ── Test: max_depth parameter ────────────────────────────────────

def test_relationship_tracer_accepts_max_depth_param(db_session: Session):
    """Handler accepts max_depth without error and includes it in context."""
    from src.mcp.prompts.relationship_tracer import PROMPT_SPECS

    inst, asmt, _scan, sr = _seed_base(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {
            "result_id": str(sr.id),
            "assessment_id": str(asmt.id),
            "max_depth": "5",
        },
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "5" in text  # max_depth reflected in output


# ── Test: prompt registration ────────────────────────────────────

def test_relationship_tracer_registered_in_prompt_registry():
    """The prompt should be discoverable in the PROMPT_REGISTRY."""
    from src.mcp.registry import PROMPT_REGISTRY

    assert PROMPT_REGISTRY.has_prompt("relationship_tracer")
