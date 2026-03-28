"""Tests for the DependencyGraph service.

Validates graph construction from CodeReference + StructuralRelationship,
transitive chain resolution, circular dependency detection, clustering,
and scoring — all restricted to dependency signals only.
"""

import uuid

import pytest
from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
)
from src.services.dependency_graph import build_dependency_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_base(session):
    """Create Instance + Assessment + Scan scaffolding."""
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
        name="Test",
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


def _add_sr(session, scan, name, table_name="sys_script_include",
            origin_type=OriginType.net_new_customer):
    """Add a single ScanResult."""
    sr = ScanResult(
        scan_id=scan.id,
        sys_id=uuid.uuid4().hex[:32],
        table_name=table_name,
        name=name,
        origin_type=origin_type,
    )
    session.add(sr)
    session.flush()
    return sr


def _add_code_ref(session, inst, asmt, source, target,
                  ref_type="script_include"):
    """Add a CodeReference between two scan results."""
    cr = CodeReference(
        instance_id=inst.id,
        assessment_id=asmt.id,
        source_scan_result_id=source.id,
        target_scan_result_id=target.id,
        source_table=source.table_name,
        source_field="script",
        source_name=source.name,
        reference_type=ref_type,
        target_identifier=target.name,
    )
    session.add(cr)
    session.flush()
    return cr


def _add_struct_rel(session, inst, asmt, parent, child,
                    rel_type="ui_policy_action"):
    """Add a StructuralRelationship between two scan results."""
    sr = StructuralRelationship(
        instance_id=inst.id,
        assessment_id=asmt.id,
        parent_scan_result_id=parent.id,
        child_scan_result_id=child.id,
        relationship_type=rel_type,
        parent_field="sys_ui_policy",
    )
    session.add(sr)
    session.flush()
    return sr


# ===========================================================================
# TestBuildDependencyGraph
# ===========================================================================

class TestBuildDependencyGraph:
    """Graph construction from DB rows."""

    def test_code_reference_edge(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)

        # a→b outbound
        assert b.id in g.outbound(a.id)
        # b←a inbound
        assert a.id in g.inbound(b.id)

    def test_structural_edge(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        p = _add_sr(db_session, scan, "Parent")
        c = _add_sr(db_session, scan, "Child")
        _add_struct_rel(db_session, inst, asmt, p, c)

        g = build_dependency_graph(db_session, asmt.id)

        # structural edges are bidirectional
        assert c.id in g.all_neighbors(p.id)
        assert p.id in g.all_neighbors(c.id)

    def test_non_customized_nodes_in_graph(self, db_session):
        """Non-customized nodes appear in all_ids but NOT in customized_ids."""
        inst, asmt, scan = _setup_base(db_session)
        cust = _add_sr(db_session, scan, "Cust",
                       origin_type=OriginType.net_new_customer)
        ootb = _add_sr(db_session, scan, "OOTB",
                       origin_type=OriginType.ootb_untouched)

        g = build_dependency_graph(db_session, asmt.id)

        assert cust.id in g.customized_ids
        assert ootb.id not in g.customized_ids
        assert cust.id in g.all_ids
        assert ootb.id in g.all_ids

    def test_shared_dependency_detection(self, db_session):
        """Two customized sources referencing same non-customized target
        should produce shared_dependency edges between the sources."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        ootb = _add_sr(db_session, scan, "SharedLib",
                       origin_type=OriginType.ootb_untouched)

        # Both A and B reference the same OOTB target
        _add_code_ref(db_session, inst, asmt, a, ootb, ref_type="script_include")
        _add_code_ref(db_session, inst, asmt, b, ootb, ref_type="script_include")

        g = build_dependency_graph(db_session, asmt.id)

        # Should have shared_dependency edge between a and b
        edges = g.edges_between(a.id, b.id)
        shared = [e for e in edges if e.dependency_type == "shared_dependency"]
        assert len(shared) >= 1
        assert shared[0].shared_via is not None

    def test_empty_assessment(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        g = build_dependency_graph(db_session, asmt.id)

        assert len(g.adjacency) == 0
        assert len(g.all_ids) == 0


# ===========================================================================
# TestDependencyGraphMethods
# ===========================================================================

class TestDependencyGraphMethods:
    """Basic graph traversal methods."""

    def test_outbound(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)

        assert b.id in g.outbound(a.id)
        assert a.id not in g.outbound(b.id)

    def test_inbound(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)

        assert a.id in g.inbound(b.id)
        assert b.id not in g.inbound(a.id)


# ===========================================================================
# TestTransitiveChains
# ===========================================================================

class TestTransitiveChains:
    """resolve_transitive_chains tests."""

    def test_direct_chain(self, db_session):
        """Direct edge (hop 1) appears as a chain."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)
        chains = g.resolve_transitive_chains(max_depth=3)

        # Should find A→B chain
        direct = [c for c in chains if c["source"] == a.id and c["target"] == b.id]
        assert len(direct) >= 1
        assert direct[0]["hop_count"] == 1
        assert direct[0]["chain_weight"] == 3.0

    def test_two_hop_chain(self, db_session):
        """Transitive chain A→B→C should yield A→C at hop 2."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        c = _add_sr(db_session, scan, "C")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, b, c)

        g = build_dependency_graph(db_session, asmt.id)
        chains = g.resolve_transitive_chains(max_depth=3)

        # Capture c.id before the list comprehension to avoid variable collision
        target_c_id = c.id
        two_hop = [ch for ch in chains
                   if ch["source"] == a.id and ch["target"] == target_c_id
                   and ch["hop_count"] == 2]
        assert len(two_hop) >= 1
        assert two_hop[0]["chain_weight"] == 2.0
        assert two_hop[0]["dependency_type"] == "transitive"

    def test_max_depth_respected(self, db_session):
        """Chains beyond max_depth should not appear."""
        inst, asmt, scan = _setup_base(db_session)
        nodes = [_add_sr(db_session, scan, f"N{i}") for i in range(5)]
        for i in range(4):
            _add_code_ref(db_session, inst, asmt, nodes[i], nodes[i + 1])

        g = build_dependency_graph(db_session, asmt.id)
        chains = g.resolve_transitive_chains(max_depth=2)

        # Should not find hop_count > 2
        assert all(c["hop_count"] <= 2 for c in chains)

    def test_only_customized_in_chains(self, db_session):
        """Non-customized nodes should not appear as chain endpoints."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A",
                    origin_type=OriginType.net_new_customer)
        ootb = _add_sr(db_session, scan, "OOTB",
                       origin_type=OriginType.ootb_untouched)
        _add_code_ref(db_session, inst, asmt, a, ootb)

        g = build_dependency_graph(db_session, asmt.id)
        chains = g.resolve_transitive_chains()

        # No chain should have ootb as source or target
        for ch in chains:
            assert ch["source"] in g.customized_ids
            assert ch["target"] in g.customized_ids


# ===========================================================================
# TestCircularDependencyDetection
# ===========================================================================

class TestCircularDependencyDetection:
    """detect_circular_dependencies tests."""

    def test_simple_cycle(self, db_session):
        """A→B→C→A should be detected."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        c = _add_sr(db_session, scan, "C")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, b, c)
        _add_code_ref(db_session, inst, asmt, c, a)

        g = build_dependency_graph(db_session, asmt.id)
        cycles = g.detect_circular_dependencies()

        assert len(cycles) >= 1
        # Each cycle should start and end with same node
        for cycle in cycles:
            assert cycle[0] == cycle[-1]

    def test_no_cycle(self, db_session):
        """Linear chain should detect no cycles."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)
        cycles = g.detect_circular_dependencies()

        assert len(cycles) == 0


# ===========================================================================
# TestClusterComputation
# ===========================================================================

class TestClusterComputation:
    """compute_clusters tests."""

    def test_two_separate_clusters(self, db_session):
        """Two disconnected pairs should form two clusters."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        c = _add_sr(db_session, scan, "C")
        d = _add_sr(db_session, scan, "D")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, c, d)

        g = build_dependency_graph(db_session, asmt.id)
        clusters = g.compute_clusters(min_cluster_size=2)

        assert len(clusters) == 2
        member_sets = [set(cl["member_ids"]) for cl in clusters]
        assert {a.id, b.id} in member_sets
        assert {c.id, d.id} in member_sets

    def test_singleton_excluded(self, db_session):
        """Single isolated customized node should not form a cluster."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        lone = _add_sr(db_session, scan, "Lone")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)
        clusters = g.compute_clusters(min_cluster_size=2)

        # Only one cluster (a, b) — lone is excluded
        assert len(clusters) == 1
        assert lone.id not in clusters[0]["member_ids"]


# ===========================================================================
# TestScoring
# ===========================================================================

class TestScoring:
    """Scoring method tests."""

    def test_coupling_score(self, db_session):
        """coupling_score should sum edge weights for a node."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        c = _add_sr(db_session, scan, "C")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, a, c)

        g = build_dependency_graph(db_session, asmt.id)
        score = g.coupling_score(a.id)

        # Two outbound code_reference edges, each weight 3.0
        assert score == 6.0

    def test_impact_radius_low(self, db_session):
        """Single outbound edge should give low impact."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        g = build_dependency_graph(db_session, asmt.id)
        radius = g.impact_radius(a.id)

        assert radius == "low"

    def test_change_risk_for_cluster(self, db_session):
        """Cluster with cycle and high-criticality edges should score high."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A", table_name="sys_security_acl")
        b = _add_sr(db_session, scan, "B", table_name="sys_security_acl")
        c = _add_sr(db_session, scan, "C", table_name="sys_security_acl")
        # Create a cycle with script_include refs (high criticality)
        _add_code_ref(db_session, inst, asmt, a, b, ref_type="script_include")
        _add_code_ref(db_session, inst, asmt, b, c, ref_type="script_include")
        _add_code_ref(db_session, inst, asmt, c, a, ref_type="script_include")

        g = build_dependency_graph(db_session, asmt.id)
        clusters = g.compute_clusters(min_cluster_size=2)

        assert len(clusters) >= 1
        cl = clusters[0]
        # cycle + high criticality + ACL type risk → should be high or critical
        assert cl["change_risk_level"] in ("high", "critical")
        assert cl["change_risk_score"] > 0
