"""Tests for the depth-first relationship-driven analysis service."""

import json

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentPhaseProgress,
    AssessmentState,
    AssessmentType,
    Customization,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.services.depth_first_analyzer import (
    DFSAnalysisResult,
    run_depth_first_analysis,
)
from src.services.relationship_graph import (
    EDGE_WEIGHTS,
    RelationshipEdge,
    RelationshipGraph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_base(session):
    """Create Instance -> Assessment -> Scan hierarchy and return them."""
    inst = Instance(
        name="dfs-test",
        url="https://dfs-test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="DFS Assessment",
        number="ASMT_DFS_001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="DFS scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    return inst, asmt, scan


def _make_sr(session, scan, sys_id, name, table="sys_script_include", origin=OriginType.net_new_customer):
    """Create and flush a ScanResult, returning the persisted object."""
    sr = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id,
        table_name=table,
        name=name,
        origin_type=origin,
    )
    session.add(sr)
    session.flush()
    return sr


def _build_graph(customized_ids, edges):
    """Build a RelationshipGraph from a list of (src, tgt, signal, weight, direction) tuples."""
    graph = RelationshipGraph()
    graph.customized_ids = set(customized_ids)
    for src, tgt, signal, weight, direction in edges:
        if src not in graph.adjacency:
            graph.adjacency[src] = []
        graph.adjacency[src].append(
            RelationshipEdge(target_id=tgt, signal_type=signal, weight=weight, direction=direction)
        )
        if direction == "bidirectional":
            if tgt not in graph.adjacency:
                graph.adjacency[tgt] = []
            graph.adjacency[tgt].append(
                RelationshipEdge(target_id=src, signal_type=signal, weight=weight, direction=direction)
            )
    return graph


# ---------------------------------------------------------------------------
# Test 1: Linear chain A->B->C
# ---------------------------------------------------------------------------

def test_linear_chain_dfs_order(db_session):
    """DFS follows a linear chain A->B->C, analyzing in that order."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "a1", "ScriptA")
    sr_b = _make_sr(db_session, scan, "b1", "ScriptB")
    sr_c = _make_sr(db_session, scan, "c1", "ScriptC")

    # Build chain: A -> B -> C with code_reference edges (weight 3.0)
    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id, sr_c.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
            (sr_b.id, sr_c.id, "code_reference", 3.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    assert result.analyzed == 3
    assert result.total_customized == 3
    # A is first in sorted order, DFS follows A->B->C
    assert result.analysis_order == [sr_a.id, sr_b.id, sr_c.id]


# ---------------------------------------------------------------------------
# Test 2: Cycle A->B->C->A
# ---------------------------------------------------------------------------

def test_cycle_all_analyzed_once(db_session):
    """Cycle A->B->C->A: all three analyzed exactly once."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "ca", "CycleA")
    sr_b = _make_sr(db_session, scan, "cb", "CycleB")
    sr_c = _make_sr(db_session, scan, "cc", "CycleC")

    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id, sr_c.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
            (sr_b.id, sr_c.id, "code_reference", 3.0, "bidirectional"),
            (sr_c.id, sr_a.id, "code_reference", 3.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    assert result.analyzed == 3
    # Each ID appears exactly once in the analysis order
    assert len(set(result.analysis_order)) == 3
    assert set(result.analysis_order) == {sr_a.id, sr_b.id, sr_c.id}


# ---------------------------------------------------------------------------
# Test 3: Depth limit
# ---------------------------------------------------------------------------

def test_depth_limit_enforced(db_session):
    """Chain of 15, max_depth=5: first 6 from seed (depth 0-5), rest from main loop."""
    inst, asmt, scan = _setup_base(db_session)

    nodes = []
    for i in range(15):
        sr = _make_sr(db_session, scan, f"dl{i:02d}", f"DeepNode{i}")
        nodes.append(sr)

    # Build linear chain: 0->1->2->...->14
    edges = []
    for i in range(14):
        edges.append((nodes[i].id, nodes[i + 1].id, "code_reference", 3.0, "bidirectional"))

    graph = _build_graph(
        customized_ids=[n.id for n in nodes],
        edges=edges,
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        max_rabbit_hole_depth=5,
        context_enrichment="never",
    )

    # All 15 should still be analyzed (from main loop fallback)
    assert result.analyzed == 15
    assert len(result.analysis_order) == 15

    # First 6 items should be the chain from seed (depth 0-5)
    # Node 0 is at depth 0, node 5 is at depth 5 -- node 6 is at depth 6 which
    # exceeds max_depth=5, so it stops there.
    first_six = result.analysis_order[:6]
    assert first_six == [nodes[i].id for i in range(6)]

    # Node 6 should appear later (from main loop or from another seed's DFS)
    assert nodes[6].id in result.analysis_order[6:]


# ---------------------------------------------------------------------------
# Test 4: Fan-out limit
# ---------------------------------------------------------------------------

def test_fanout_limit_enforced(db_session):
    """Hub with 30 neighbors, max_neighbors=10: only 10 followed in DFS."""
    inst, asmt, scan = _setup_base(db_session)

    hub = _make_sr(db_session, scan, "hub", "HubScript")

    spokes = []
    for i in range(30):
        sr = _make_sr(db_session, scan, f"sp{i:02d}", f"Spoke{i}")
        spokes.append(sr)

    # All spokes connected to hub with bidirectional edges
    edges = []
    for spoke in spokes:
        edges.append((hub.id, spoke.id, "code_reference", 3.0, "bidirectional"))

    graph = _build_graph(
        customized_ids=[hub.id] + [s.id for s in spokes],
        edges=edges,
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        max_neighbors_per_hop=10,
        context_enrichment="never",
    )

    # All 31 (hub + 30 spokes) should eventually be analyzed
    assert result.analyzed == 31

    # Hub is analyzed first (lowest ID), then up to 10 neighbors from DFS,
    # then the remaining 20 from the main loop
    assert result.analysis_order[0] == hub.id


# ---------------------------------------------------------------------------
# Test 5: Progressive grouping creates feature
# ---------------------------------------------------------------------------

def test_progressive_grouping_creates_feature(db_session):
    """Two customized artifacts with code_reference -> feature created, both members."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "pg_a", "GroupA")
    sr_b = _make_sr(db_session, scan, "pg_b", "GroupB")

    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    assert result.analyzed == 2
    assert result.features_created >= 1

    # Both should be members of the same feature
    fsr_a = db_session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == sr_a.id)
    ).first()
    fsr_b = db_session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == sr_b.id)
    ).first()

    assert fsr_a is not None
    assert fsr_b is not None
    assert fsr_a.feature_id == fsr_b.feature_id
    assert fsr_a.assignment_source == "ai"
    assert fsr_b.assignment_source == "ai"


def test_depth_first_syncs_customization_observations(db_session):
    """Depth-first analysis keeps customization child rows in sync."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "sync_a", "SyncA")
    sr_b = _make_sr(db_session, scan, "sync_b", "SyncB")

    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id],
        edges=[(sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional")],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )
    assert result.analyzed == 2

    rows = db_session.exec(
        select(Customization).where(Customization.scan_id == scan.id)
    ).all()
    assert len(rows) == 2
    by_result_id = {row.scan_result_id: row for row in rows}

    refreshed_a = db_session.get(ScanResult, sr_a.id)
    refreshed_b = db_session.get(ScanResult, sr_b.id)
    assert refreshed_a is not None
    assert refreshed_b is not None

    assert by_result_id[sr_a.id].observations == refreshed_a.observations
    assert by_result_id[sr_b.id].observations == refreshed_b.observations


# ---------------------------------------------------------------------------
# Test 6: Feature description evolution
# ---------------------------------------------------------------------------

def test_feature_description_evolves(db_session):
    """Feature description updates as more members are added."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "fe_a", "EvolutionA", table="sys_script")
    sr_b = _make_sr(db_session, scan, "fe_b", "EvolutionB", table="sys_script_include")

    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    # Find the feature
    fsr_a = db_session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == sr_a.id)
    ).first()
    assert fsr_a is not None

    feature = db_session.get(Feature, fsr_a.feature_id)
    assert feature is not None

    # With 2 members across different tables, description should mention both tables
    assert "2 artifacts" in feature.description
    assert "sys_script" in feature.description
    assert "sys_script_include" in feature.description


# ---------------------------------------------------------------------------
# Test 7: Resume from checkpoint
# ---------------------------------------------------------------------------

def test_resume_from_checkpoint(db_session):
    """Checkpoint after 5 of 10 artifacts; resume finishes remaining 5."""
    inst, asmt, scan = _setup_base(db_session)

    nodes = []
    for i in range(10):
        sr = _make_sr(db_session, scan, f"res{i:02d}", f"ResumeNode{i}")
        nodes.append(sr)

    # No edges -- each is an isolated node (no DFS rabbit holes)
    graph = _build_graph(
        customized_ids=[n.id for n in nodes],
        edges=[],
    )

    # First run: analyze 5, then simulate interruption by injecting a checkpoint
    first_five_ids = sorted([n.id for n in nodes[:5]])

    # Create a checkpoint record as if 5 were completed
    from src.services.assessment_phase_progress import start_phase_progress, checkpoint_phase_progress
    pp = start_phase_progress(
        db_session, asmt.id, "ai_analysis",
        total_items=10, allow_resume=True,
        checkpoint={
            "mode": "depth_first",
            "visited_ids": first_five_ids,
            "total_customized": 10,
        },
        commit=False,
    )
    # Set the completed items and checkpoint JSON with visited_ids
    checkpoint_phase_progress(
        db_session, asmt.id, "ai_analysis",
        completed_items=5,
        status="running",
        checkpoint={
            "mode": "depth_first",
            "visited_ids": first_five_ids,
            "total_customized": 10,
        },
        commit=False,
    )
    db_session.commit()

    # Also need the scan results to have observations for resume to "see" them as done
    for sr in nodes[:5]:
        sr.observations = f"Already analyzed: {sr.name}"
        sr.ai_observations = json.dumps({"analysis_mode": "depth_first"})
        db_session.add(sr)
    db_session.commit()

    # Now run DFS -- it should resume and only analyze the remaining 5
    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    # The result should show 10 analyzed (5 from checkpoint + 5 new)
    assert result.analyzed == 10
    # But analysis_order only shows the 5 newly-analyzed ones
    assert len(result.analysis_order) == 5
    remaining_ids = sorted([n.id for n in nodes[5:]])
    assert sorted(result.analysis_order) == remaining_ids


# ---------------------------------------------------------------------------
# Test 8: Empty graph (0 customized artifacts)
# ---------------------------------------------------------------------------

def test_empty_graph_returns_immediately(db_session):
    """0 customized artifacts -> returns immediately with zeros."""
    inst, asmt, scan = _setup_base(db_session)

    graph = RelationshipGraph()  # Empty graph

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    assert result.analyzed == 0
    assert result.total_customized == 0
    assert result.features_created == 0
    assert result.analysis_order == []


# ---------------------------------------------------------------------------
# Test 9: Back-propagation updates observations
# ---------------------------------------------------------------------------

def test_back_propagation_updates_observations(db_session):
    """When grouping artifact B with A's feature, A's observations get updated."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "bp_a", "BackpropA")
    sr_b = _make_sr(db_session, scan, "bp_b", "BackpropB")

    # Strong bidirectional edge so they get grouped together
    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    assert result.analyzed == 2

    # Refresh to get latest observations
    db_session.expire_all()
    sr_a_updated = db_session.get(ScanResult, sr_a.id)
    sr_b_updated = db_session.get(ScanResult, sr_b.id)

    # At least one should have a "[Grouped: ...]" mention from back-propagation
    # A is analyzed first, B is analyzed second. When B is grouped with A's feature,
    # A's observations should be updated with the feature name.
    combined_obs = (sr_a_updated.observations or "") + (sr_b_updated.observations or "")
    assert "[Grouped:" in combined_obs


# ---------------------------------------------------------------------------
# Test 10: Min edge weight filtering
# ---------------------------------------------------------------------------

def test_min_edge_weight_filtering(db_session):
    """Edges below min_edge_weight are not followed in DFS but artifacts still analyzed."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "mw_a", "WeightA")
    sr_b = _make_sr(db_session, scan, "mw_b", "WeightB")
    sr_c = _make_sr(db_session, scan, "mw_c", "WeightC")

    # A -> B with high weight (will be followed)
    # A -> C with low weight (will NOT be followed by DFS, but C analyzed from main loop)
    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id, sr_c.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
            (sr_a.id, sr_c.id, "table_colocation", 1.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        min_edge_weight=2.0,
        context_enrichment="never",
    )

    # All three should be analyzed
    assert result.analyzed == 3

    # DFS from A follows only B (weight 3.0 >= 2.0), not C (weight 1.0 < 2.0)
    # A is seed (depth 0), B is depth 1 via DFS, C comes from main loop
    assert result.analysis_order[0] == sr_a.id
    assert result.analysis_order[1] == sr_b.id
    # C should be analyzed last (from main loop, not from A's DFS)
    assert result.analysis_order[2] == sr_c.id


# ---------------------------------------------------------------------------
# Test 11: Observations and ai_observations are written
# ---------------------------------------------------------------------------

def test_observations_written(db_session):
    """DFS writes both observations and ai_observations to scan results."""
    inst, asmt, scan = _setup_base(db_session)

    sr = _make_sr(db_session, scan, "obs1", "ObsTest")

    graph = _build_graph(
        customized_ids=[sr.id],
        edges=[],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    assert result.analyzed == 1

    db_session.expire_all()
    sr_updated = db_session.get(ScanResult, sr.id)

    # observations should contain the artifact name
    assert "ObsTest" in sr_updated.observations

    # ai_observations should be valid JSON with analysis_mode
    ai_obs = json.loads(sr_updated.ai_observations)
    assert ai_obs["analysis_mode"] == "depth_first"
    assert ai_obs["dfs_depth"] == 0


# ---------------------------------------------------------------------------
# Test 12: Checkpoint JSON stored correctly
# ---------------------------------------------------------------------------

def test_checkpoint_json_stored(db_session):
    """Checkpoint JSON is stored with visited_ids after analysis."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "ck_a", "CheckpointA")
    sr_b = _make_sr(db_session, scan, "ck_b", "CheckpointB")

    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id],
        edges=[
            (sr_a.id, sr_b.id, "code_reference", 3.0, "bidirectional"),
        ],
    )

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
    )

    # Check the final checkpoint
    db_session.expire_all()
    phase = db_session.exec(
        select(AssessmentPhaseProgress)
        .where(AssessmentPhaseProgress.assessment_id == asmt.id)
        .where(AssessmentPhaseProgress.phase == "ai_analysis")
    ).first()

    assert phase is not None
    assert phase.status == "completed"
    assert phase.completed_items == 2

    checkpoint = json.loads(phase.checkpoint_json)
    assert checkpoint["mode"] == "depth_first"
    assert sorted(checkpoint["visited_ids"]) == sorted([sr_a.id, sr_b.id])


# ---------------------------------------------------------------------------
# Test 13: Progress and checkpoint callbacks invoked
# ---------------------------------------------------------------------------

def test_callbacks_invoked(db_session):
    """Progress and checkpoint callbacks are called for each artifact."""
    inst, asmt, scan = _setup_base(db_session)

    sr_a = _make_sr(db_session, scan, "cb_a", "CallbackA")
    sr_b = _make_sr(db_session, scan, "cb_b", "CallbackB")
    sr_c = _make_sr(db_session, scan, "cb_c", "CallbackC")

    graph = _build_graph(
        customized_ids=[sr_a.id, sr_b.id, sr_c.id],
        edges=[],
    )

    progress_calls = []
    checkpoint_calls = []

    def on_progress(pct, msg):
        progress_calls.append((pct, msg))

    def on_checkpoint(sr_id, completed, total):
        checkpoint_calls.append((sr_id, completed, total))

    result = run_depth_first_analysis(
        db_session,
        asmt.id,
        inst.id,
        graph,
        context_enrichment="never",
        progress_callback=on_progress,
        checkpoint_callback=on_checkpoint,
    )

    assert len(progress_calls) == 3
    assert len(checkpoint_calls) == 3
    # Last checkpoint should show 3 of 3
    assert checkpoint_calls[-1][1] == 3
    assert checkpoint_calls[-1][2] == 3
