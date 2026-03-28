"""Tests for the shared relationship graph builder."""

import json

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
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
from src.services.relationship_graph import (
    EDGE_WEIGHTS,
    RelationshipGraph,
    build_relationship_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_base(session):
    """Create Instance -> Assessment -> Scan hierarchy and return them."""
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

    return inst, asmt, scan


def _make_scan_result(scan, sys_id, name, origin_type=None):
    """Create a ScanResult with minimal required fields."""
    return ScanResult(
        scan_id=scan.id,
        sys_id=sys_id,
        table_name="sys_script_include",
        name=name,
        origin_type=origin_type,
    )


# ---------------------------------------------------------------------------
# Tests: EDGE_WEIGHTS shared constant
# ---------------------------------------------------------------------------

def test_edge_weights_expected_keys():
    """EDGE_WEIGHTS should contain all expected signal types."""
    expected_keys = {
        "dependency_cluster",
        "ai_relationship",
        "update_set_overlap",
        "update_set_artifact_link",
        "code_reference",
        "structural_relationship",
        "temporal_cluster",
        "naming_cluster",
        "table_colocation",
    }
    assert set(EDGE_WEIGHTS.keys()) == expected_keys


def test_edge_weights_values():
    """EDGE_WEIGHTS should have known values."""
    assert EDGE_WEIGHTS["update_set_overlap"] == 3.0
    assert EDGE_WEIGHTS["update_set_artifact_link"] == 2.5
    assert EDGE_WEIGHTS["code_reference"] == 3.0
    assert EDGE_WEIGHTS["structural_relationship"] == 2.5
    assert EDGE_WEIGHTS["temporal_cluster"] == 1.8
    assert EDGE_WEIGHTS["naming_cluster"] == 2.0
    assert EDGE_WEIGHTS["table_colocation"] == 1.2


# ---------------------------------------------------------------------------
# Tests: Empty graph
# ---------------------------------------------------------------------------

def test_empty_graph_no_scans(db_session):
    """Assessment with no scans returns an empty graph."""
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Empty",
        number="ASMT0099",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    db_session.add(asmt)
    db_session.flush()

    graph = build_relationship_graph(db_session, asmt.id)
    assert graph.adjacency == {}
    assert graph.customized_ids == set()


def test_empty_graph_nonexistent_assessment(db_session):
    """A non-existent assessment ID returns an empty graph."""
    graph = build_relationship_graph(db_session, 999999)
    assert graph.adjacency == {}
    assert graph.customized_ids == set()


# ---------------------------------------------------------------------------
# Tests: RelationshipGraph methods
# ---------------------------------------------------------------------------

def test_neighbors_basic():
    """neighbors() returns all neighbor IDs (deduplicated)."""
    from src.services.relationship_graph import RelationshipEdge

    graph = RelationshipGraph()
    graph.adjacency[1] = [
        RelationshipEdge(target_id=2, signal_type="code_reference", weight=3.0, direction="outgoing"),
        RelationshipEdge(target_id=3, signal_type="structural_relationship", weight=2.5, direction="bidirectional"),
        RelationshipEdge(target_id=2, signal_type="naming_cluster", weight=2.0, direction="bidirectional"),
    ]

    neighbors = graph.neighbors(1)
    assert set(neighbors) == {2, 3}
    # Should deduplicate — even though 2 appears twice, it's listed once
    assert len(neighbors) == 2


def test_neighbors_min_weight_filter():
    """neighbors() with min_weight filters out low-weight edges."""
    from src.services.relationship_graph import RelationshipEdge

    graph = RelationshipGraph()
    graph.adjacency[1] = [
        RelationshipEdge(target_id=2, signal_type="code_reference", weight=3.0, direction="outgoing"),
        RelationshipEdge(target_id=3, signal_type="table_colocation", weight=1.2, direction="bidirectional"),
        RelationshipEdge(target_id=4, signal_type="temporal_cluster", weight=1.8, direction="bidirectional"),
    ]

    # min_weight=2.0 should only return node 2 (weight 3.0)
    neighbors = graph.neighbors(1, min_weight=2.0)
    assert neighbors == [2]

    # min_weight=1.5 should return node 2 and 4
    neighbors = graph.neighbors(1, min_weight=1.5)
    assert set(neighbors) == {2, 4}


def test_neighbors_no_edges():
    """neighbors() for a node with no edges returns empty list."""
    graph = RelationshipGraph()
    assert graph.neighbors(999) == []


def test_customized_neighbors():
    """customized_neighbors() returns only neighbors that are customized."""
    from src.services.relationship_graph import RelationshipEdge

    graph = RelationshipGraph()
    graph.customized_ids = {2, 4}
    graph.adjacency[1] = [
        RelationshipEdge(target_id=2, signal_type="code_reference", weight=3.0, direction="outgoing"),
        RelationshipEdge(target_id=3, signal_type="structural_relationship", weight=2.5, direction="bidirectional"),
        RelationshipEdge(target_id=4, signal_type="naming_cluster", weight=2.0, direction="bidirectional"),
    ]

    customized = graph.customized_neighbors(1)
    assert set(customized) == {2, 4}


def test_customized_neighbors_with_min_weight():
    """customized_neighbors() respects min_weight filter."""
    from src.services.relationship_graph import RelationshipEdge

    graph = RelationshipGraph()
    graph.customized_ids = {2, 3, 4}
    graph.adjacency[1] = [
        RelationshipEdge(target_id=2, signal_type="code_reference", weight=3.0, direction="outgoing"),
        RelationshipEdge(target_id=3, signal_type="table_colocation", weight=1.2, direction="bidirectional"),
        RelationshipEdge(target_id=4, signal_type="temporal_cluster", weight=1.8, direction="bidirectional"),
    ]

    customized = graph.customized_neighbors(1, min_weight=2.0)
    assert customized == [2]


def test_edge_weight_method():
    """edge_weight() returns max weight between two nodes."""
    from src.services.relationship_graph import RelationshipEdge

    graph = RelationshipGraph()
    graph.adjacency[1] = [
        RelationshipEdge(target_id=2, signal_type="code_reference", weight=3.0, direction="outgoing"),
        RelationshipEdge(target_id=2, signal_type="naming_cluster", weight=2.0, direction="bidirectional"),
        RelationshipEdge(target_id=3, signal_type="table_colocation", weight=1.2, direction="bidirectional"),
    ]

    assert graph.edge_weight(1, 2) == 3.0
    assert graph.edge_weight(1, 3) == 1.2
    assert graph.edge_weight(1, 999) == 0.0


def test_edge_types_method():
    """edge_types() returns all signal types between two nodes."""
    from src.services.relationship_graph import RelationshipEdge

    graph = RelationshipGraph()
    graph.adjacency[1] = [
        RelationshipEdge(target_id=2, signal_type="code_reference", weight=3.0, direction="outgoing"),
        RelationshipEdge(target_id=2, signal_type="naming_cluster", weight=2.0, direction="bidirectional"),
        RelationshipEdge(target_id=3, signal_type="table_colocation", weight=1.2, direction="bidirectional"),
    ]

    types = graph.edge_types(1, 2)
    assert set(types) == {"code_reference", "naming_cluster"}

    types = graph.edge_types(1, 3)
    assert types == ["table_colocation"]

    types = graph.edge_types(1, 999)
    assert types == []


# ---------------------------------------------------------------------------
# Tests: build_relationship_graph with engine data
# ---------------------------------------------------------------------------

def test_build_graph_code_references(db_session):
    """Code references create directed edges in the graph."""
    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "aaa", "ScriptA", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "bbb", "ScriptB", OriginType.modified_ootb)
    db_session.add_all([sr1, sr2])
    db_session.flush()

    code_ref = CodeReference(
        instance_id=inst.id,
        assessment_id=asmt.id,
        source_scan_result_id=sr1.id,
        target_scan_result_id=sr2.id,
        source_table="sys_script_include",
        source_field="script",
        source_name="ScriptA",
        reference_type="GlideRecord",
        target_identifier="ScriptB",
    )
    db_session.add(code_ref)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    # Both should be customized
    assert sr1.id in graph.customized_ids
    assert sr2.id in graph.customized_ids

    # Outgoing edge from sr1 -> sr2
    assert sr2.id in graph.neighbors(sr1.id)
    types = graph.edge_types(sr1.id, sr2.id)
    assert "code_reference" in types

    # Code references are outgoing, so sr2 should NOT have sr1 as neighbor
    # (no bidirectional edge, only incoming reverse)
    # Actually _add_edge with "outgoing" only adds forward, not reverse
    neighbors_of_sr2 = graph.neighbors(sr2.id)
    assert sr1.id not in neighbors_of_sr2


def test_build_graph_structural_relationships(db_session):
    """Structural relationships create bidirectional edges."""
    inst, asmt, scan = _setup_base(db_session)

    sr_parent = _make_scan_result(scan, "p1", "ParentScript", OriginType.net_new_customer)
    sr_child = _make_scan_result(scan, "c1", "ChildScript", OriginType.net_new_customer)
    db_session.add_all([sr_parent, sr_child])
    db_session.flush()

    rel = StructuralRelationship(
        instance_id=inst.id,
        assessment_id=asmt.id,
        parent_scan_result_id=sr_parent.id,
        child_scan_result_id=sr_child.id,
        relationship_type="parent_child",
        parent_field="sys_id",
    )
    db_session.add(rel)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    # Bidirectional — both should see each other
    assert sr_child.id in graph.neighbors(sr_parent.id)
    assert sr_parent.id in graph.neighbors(sr_child.id)

    assert graph.edge_weight(sr_parent.id, sr_child.id) == EDGE_WEIGHTS["structural_relationship"]


def test_build_graph_update_set_artifact_links(db_session):
    """Artifacts in the same update set get bidirectional edges."""
    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "a1", "ArtifactA", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "b1", "ArtifactB", OriginType.modified_ootb)
    sr3 = _make_scan_result(scan, "c1", "ArtifactC", OriginType.net_new_customer)
    db_session.add_all([sr1, sr2, sr3])
    db_session.flush()

    # Create an update set
    us = UpdateSet(
        instance_id=inst.id,
        sn_sys_id="us001",
        name="Feature US",
    )
    db_session.add(us)
    db_session.flush()

    # Link sr1 and sr2 to the same update set
    link1 = UpdateSetArtifactLink(
        instance_id=inst.id,
        assessment_id=asmt.id,
        scan_result_id=sr1.id,
        update_set_id=us.id,
        link_source="scan_result_current",
    )
    link2 = UpdateSetArtifactLink(
        instance_id=inst.id,
        assessment_id=asmt.id,
        scan_result_id=sr2.id,
        update_set_id=us.id,
        link_source="scan_result_current",
    )
    db_session.add_all([link1, link2])
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    # sr1 and sr2 should be connected
    assert sr2.id in graph.neighbors(sr1.id)
    assert sr1.id in graph.neighbors(sr2.id)

    # sr3 should not be connected to sr1 or sr2
    assert sr3.id not in graph.neighbors(sr1.id)
    assert sr3.id not in graph.neighbors(sr2.id)


def test_build_graph_naming_clusters(db_session):
    """Naming cluster members get bidirectional edges."""
    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "n1", "HR_Script1", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "n2", "HR_Script2", OriginType.net_new_customer)
    sr3 = _make_scan_result(scan, "n3", "HR_Policy1", OriginType.modified_ootb)
    db_session.add_all([sr1, sr2, sr3])
    db_session.flush()

    cluster = NamingCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        cluster_label="HR_",
        pattern_type="prefix",
        member_count=3,
        member_ids_json=json.dumps([sr1.id, sr2.id, sr3.id]),
        tables_involved_json=json.dumps(["sys_script_include"]),
    )
    db_session.add(cluster)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    # All three should be connected to each other
    assert sr2.id in graph.neighbors(sr1.id)
    assert sr3.id in graph.neighbors(sr1.id)
    assert sr1.id in graph.neighbors(sr2.id)
    assert sr3.id in graph.neighbors(sr2.id)

    assert graph.edge_weight(sr1.id, sr2.id) == EDGE_WEIGHTS["naming_cluster"]


def test_build_graph_temporal_clusters(db_session):
    """Temporal cluster members get bidirectional edges."""
    from datetime import datetime

    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "t1", "ScriptT1", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "t2", "ScriptT2", OriginType.net_new_customer)
    db_session.add_all([sr1, sr2])
    db_session.flush()

    cluster = TemporalCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        developer="alice",
        cluster_start=datetime(2025, 1, 1),
        cluster_end=datetime(2025, 1, 2),
        record_count=2,
        record_ids_json=json.dumps([sr1.id, sr2.id]),
        avg_gap_minutes=30.0,
        tables_involved_json=json.dumps(["sys_script_include"]),
    )
    db_session.add(cluster)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    assert sr2.id in graph.neighbors(sr1.id)
    assert sr1.id in graph.neighbors(sr2.id)
    assert graph.edge_weight(sr1.id, sr2.id) == EDGE_WEIGHTS["temporal_cluster"]


def test_build_graph_table_colocation(db_session):
    """Table colocation members get bidirectional edges."""
    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "tc1", "ScriptTC1", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "tc2", "ScriptTC2", OriginType.modified_ootb)
    db_session.add_all([sr1, sr2])
    db_session.flush()

    coloc = TableColocationSummary(
        instance_id=inst.id,
        assessment_id=asmt.id,
        target_table="incident",
        record_count=2,
        record_ids_json=json.dumps([sr1.id, sr2.id]),
        artifact_types_json=json.dumps(["sys_script_include"]),
        developers_json=json.dumps(["alice"]),
    )
    db_session.add(coloc)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    assert sr2.id in graph.neighbors(sr1.id)
    assert sr1.id in graph.neighbors(sr2.id)
    assert graph.edge_weight(sr1.id, sr2.id) == EDGE_WEIGHTS["table_colocation"]


def test_build_graph_update_set_overlaps(db_session):
    """Update set overlap members get bidirectional edges."""
    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "ov1", "ScriptOV1", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "ov2", "ScriptOV2", OriginType.modified_ootb)
    db_session.add_all([sr1, sr2])
    db_session.flush()

    # Create two update sets for the overlap
    us_a = UpdateSet(instance_id=inst.id, sn_sys_id="us_a", name="US A")
    us_b = UpdateSet(instance_id=inst.id, sn_sys_id="us_b", name="US B")
    db_session.add_all([us_a, us_b])
    db_session.flush()

    overlap = UpdateSetOverlap(
        instance_id=inst.id,
        assessment_id=asmt.id,
        update_set_a_id=us_a.id,
        update_set_b_id=us_b.id,
        shared_record_count=2,
        shared_records_json=json.dumps([sr1.id, sr2.id]),
        overlap_score=0.8,
    )
    db_session.add(overlap)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    assert sr2.id in graph.neighbors(sr1.id)
    assert sr1.id in graph.neighbors(sr2.id)
    assert graph.edge_weight(sr1.id, sr2.id) == EDGE_WEIGHTS["update_set_overlap"]


def test_build_graph_customized_ids_tracking(db_session):
    """Graph correctly identifies customized vs non-customized scan results."""
    inst, asmt, scan = _setup_base(db_session)

    sr_custom = _make_scan_result(scan, "c1", "CustomScript", OriginType.net_new_customer)
    sr_modified = _make_scan_result(scan, "m1", "ModifiedScript", OriginType.modified_ootb)
    sr_ootb = _make_scan_result(scan, "o1", "OotbScript", OriginType.ootb_untouched)
    sr_unknown = _make_scan_result(scan, "u1", "UnknownScript", OriginType.unknown)
    db_session.add_all([sr_custom, sr_modified, sr_ootb, sr_unknown])
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    # net_new_customer and modified_ootb should be customized
    assert sr_custom.id in graph.customized_ids
    assert sr_modified.id in graph.customized_ids

    # ootb_untouched and unknown should NOT be customized
    assert sr_ootb.id not in graph.customized_ids
    assert sr_unknown.id not in graph.customized_ids


def test_build_graph_multiple_signal_types(db_session):
    """Two nodes connected by multiple signal types have multiple edges."""
    inst, asmt, scan = _setup_base(db_session)

    sr1 = _make_scan_result(scan, "m1", "ScriptM1", OriginType.net_new_customer)
    sr2 = _make_scan_result(scan, "m2", "ScriptM2", OriginType.net_new_customer)
    db_session.add_all([sr1, sr2])
    db_session.flush()

    # Code reference: sr1 -> sr2
    code_ref = CodeReference(
        instance_id=inst.id,
        assessment_id=asmt.id,
        source_scan_result_id=sr1.id,
        target_scan_result_id=sr2.id,
        source_table="sys_script_include",
        source_field="script",
        source_name="ScriptM1",
        reference_type="GlideRecord",
        target_identifier="ScriptM2",
    )
    db_session.add(code_ref)

    # Naming cluster: sr1 and sr2
    cluster = NamingCluster(
        instance_id=inst.id,
        assessment_id=asmt.id,
        cluster_label="Script",
        pattern_type="prefix",
        member_count=2,
        member_ids_json=json.dumps([sr1.id, sr2.id]),
        tables_involved_json=json.dumps(["sys_script_include"]),
    )
    db_session.add(cluster)
    db_session.commit()

    graph = build_relationship_graph(db_session, asmt.id)

    edge_types = graph.edge_types(sr1.id, sr2.id)
    assert "code_reference" in edge_types
    assert "naming_cluster" in edge_types

    # Max weight should be 3.0 (code_reference) since naming_cluster is 2.0
    assert graph.edge_weight(sr1.id, sr2.id) == 3.0
