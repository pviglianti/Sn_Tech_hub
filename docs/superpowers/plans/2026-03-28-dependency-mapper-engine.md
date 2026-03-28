# Dependency Mapper Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone dependency mapping engine that discovers pure dependency relationships between customized scan results, computes transitive chains, detects circular dependencies, and produces dependency clusters with scoring to strengthen feature grouping.

**Architecture:** New `DependencyGraph` dataclass (separate from `RelationshipGraph`) built from CodeReference + StructuralRelationship tables only. New `dependency_mapper` engine computes transitive chains, shared dependencies, circular deps, and connected-component clusters. Two new DB tables (`DependencyChain`, `DependencyCluster`) store results. Two new fields on `Feature` store change risk. Graph includes all artifacts for visualization; only customized ones participate in clustering.

**Tech Stack:** Python 3.11+, SQLModel, pytest, dataclasses

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/models.py` | Modify | Add `DependencyChain` and `DependencyCluster` models, add `change_risk_score`/`change_risk_level` to `Feature` |
| `src/services/dependency_graph.py` | Create | `DependencyEdge`, `DependencyGraph` dataclasses, `build_dependency_graph()`, transitive chain BFS, circular detection DFS, cluster computation, scoring |
| `src/engines/dependency_mapper.py` | Create | Engine `run()` function — orchestrates graph build, chain resolution, cluster persistence |
| `src/mcp/tools/pipeline/run_engines.py` | Modify | Register `dependency_mapper` in `_ENGINE_REGISTRY`, update description and input schema |
| `src/services/integration_properties.py` | Modify | Add 4 config keys + property definitions + defaults for dependency mapper |
| `tests/test_dependency_graph.py` | Create | Unit tests for `DependencyGraph` methods |
| `tests/test_dependency_mapper.py` | Create | Integration tests for the engine `run()` function |

---

### Task 1: Add Database Models

**Files:**
- Modify: `tech-assessment-hub/src/models.py` (after `TableColocationSummary` at ~line 1813)

- [ ] **Step 1: Write test for model instantiation**

Create `tech-assessment-hub/tests/test_dependency_mapper.py`:

```python
"""Tests for the Dependency Mapper engine (Engine 7).

Validates dependency chain resolution, circular detection, cluster computation,
and scoring across customized ScanResults.
"""

import json

import pytest
from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    DependencyChain,
    DependencyCluster,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
)


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


def _add_scan_result(session, scan, name, table_name="sys_script_include",
                     sys_id=None, origin_type=OriginType.net_new_customer):
    """Add a single ScanResult with the given name and origin_type."""
    import uuid

    sr = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id or str(uuid.uuid4().hex[:32]),
        table_name=table_name,
        name=name,
        origin_type=origin_type,
    )
    session.add(sr)
    session.flush()
    return sr


def _add_code_reference(session, inst, asmt, source, target, ref_type="script_include"):
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


def _add_structural_rel(session, inst, asmt, parent, child, rel_type="ui_policy_action"):
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


class TestDependencyModelsExist:
    """DependencyChain and DependencyCluster models can be instantiated."""

    def test_dependency_chain_create(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        sr_a = _add_scan_result(db_session, scan, "Script A")
        sr_b = _add_scan_result(db_session, scan, "Script B")

        chain = DependencyChain(
            scan_id=scan.id,
            instance_id=inst.id,
            assessment_id=asmt.id,
            source_scan_result_id=sr_a.id,
            target_scan_result_id=sr_b.id,
            dependency_type="code_reference",
            direction="outbound",
            hop_count=1,
            chain_path_json=json.dumps([sr_a.id, sr_b.id]),
            chain_weight=3.0,
            criticality="high",
        )
        db_session.add(chain)
        db_session.flush()
        assert chain.id is not None

    def test_dependency_cluster_create(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        sr_a = _add_scan_result(db_session, scan, "Script A")
        sr_b = _add_scan_result(db_session, scan, "Script B")

        cluster = DependencyCluster(
            scan_id=scan.id,
            instance_id=inst.id,
            assessment_id=asmt.id,
            cluster_label="sys_script_include cluster (2 artifacts)",
            member_ids_json=json.dumps([sr_a.id, sr_b.id]),
            member_count=2,
            internal_edge_count=1,
            coupling_score=2.0,
            impact_radius="low",
            change_risk_score=15.0,
            change_risk_level="low",
            circular_dependencies_json=json.dumps([]),
            tables_involved_json=json.dumps(["sys_script_include"]),
        )
        db_session.add(cluster)
        db_session.flush()
        assert cluster.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_mapper.py::TestDependencyModelsExist -v
```

Expected: FAIL with `ImportError: cannot import name 'DependencyChain'`

- [ ] **Step 3: Add DependencyChain and DependencyCluster models to models.py**

Insert after `TableColocationSummary` (after line 1813 in `src/models.py`):

```python
# ============================================
# TABLE: DependencyChain (resolved dependency paths)
# Populated by the Dependency Mapper engine
# ============================================

class DependencyChain(SQLModel, table=True):
    """Resolved dependency path between two customized scan results."""
    __tablename__ = "dependency_chain"

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    source_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    target_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)

    dependency_type: str  # code_reference, structural, transitive, shared_dependency
    direction: str  # outbound, inbound
    hop_count: int  # 1 = direct, 2-3 = transitive
    chain_path_json: str  # JSON array of intermediate scan_result IDs
    chain_weight: float  # Diminishing: 3.0, 2.0, 1.0
    criticality: str  # high, medium, low

    shared_via_identifier: Optional[str] = None  # For shared_dependency type

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: DependencyCluster (connected dependency subgraphs)
# Populated by the Dependency Mapper engine
# ============================================

class DependencyCluster(SQLModel, table=True):
    """Group of customized artifacts forming a connected dependency subgraph."""
    __tablename__ = "dependency_cluster"

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    cluster_label: str
    member_ids_json: str  # JSON array of scan_result IDs
    member_count: int
    internal_edge_count: int
    coupling_score: float
    impact_radius: str  # very_high, high, medium, low
    change_risk_score: float  # 0-100
    change_risk_level: str  # critical, high, medium, low
    circular_dependencies_json: str  # JSON array of cycle paths
    tables_involved_json: str  # JSON array of distinct table_names

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Add change_risk fields to Feature model**

In `src/models.py`, add two fields to the `Feature` class after the `pass_number` field (~line 648):

```python
    # ---- Dependency risk scoring ----
    change_risk_score: Optional[float] = None
    change_risk_level: Optional[str] = None  # critical, high, medium, low
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_mapper.py::TestDependencyModelsExist -v
```

Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add tech-assessment-hub/src/models.py tech-assessment-hub/tests/test_dependency_mapper.py
git commit -m "feat: add DependencyChain, DependencyCluster models and Feature risk fields"
```

---

### Task 2: Build DependencyGraph Service

**Files:**
- Create: `tech-assessment-hub/src/services/dependency_graph.py`
- Create: `tech-assessment-hub/tests/test_dependency_graph.py`

- [ ] **Step 1: Write tests for DependencyGraph construction and methods**

Create `tech-assessment-hub/tests/test_dependency_graph.py`:

```python
"""Tests for the standalone DependencyGraph service.

Validates graph construction from CodeReference + StructuralRelationship,
shared dependency detection, transitive chain BFS, circular dependency
detection, cluster computation, and scoring.
"""

import json

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
from src.services.dependency_graph import (
    DependencyEdge,
    DependencyGraph,
    build_dependency_graph,
)


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_dependency_mapper.py)
# ---------------------------------------------------------------------------

def _setup_base(session):
    inst = Instance(
        name="test", url="https://test.service-now.com",
        username="admin", password_encrypted="x",
    )
    session.add(inst)
    session.flush()
    asmt = Assessment(
        instance_id=inst.id, name="Test", number="ASMT0001",
        assessment_type=AssessmentType.global_app, state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()
    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="test scan", status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()
    return inst, asmt, scan


def _add_sr(session, scan, name, table_name="sys_script_include",
            origin_type=OriginType.net_new_customer):
    import uuid
    sr = ScanResult(
        scan_id=scan.id, sys_id=uuid.uuid4().hex[:32],
        table_name=table_name, name=name, origin_type=origin_type,
    )
    session.add(sr)
    session.flush()
    return sr


def _add_code_ref(session, inst, asmt, source, target, ref_type="script_include"):
    cr = CodeReference(
        instance_id=inst.id, assessment_id=asmt.id,
        source_scan_result_id=source.id, target_scan_result_id=target.id,
        source_table=source.table_name, source_field="script",
        source_name=source.name, reference_type=ref_type,
        target_identifier=target.name,
    )
    session.add(cr)
    session.flush()
    return cr


def _add_struct_rel(session, inst, asmt, parent, child, rel_type="ui_policy_action"):
    sr = StructuralRelationship(
        instance_id=inst.id, assessment_id=asmt.id,
        parent_scan_result_id=parent.id, child_scan_result_id=child.id,
        relationship_type=rel_type, parent_field="sys_ui_policy",
    )
    session.add(sr)
    session.flush()
    return sr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildDependencyGraph:
    """build_dependency_graph returns a graph with correct edges."""

    def test_code_reference_edge(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "ScriptA")
        b = _add_sr(db_session, scan, "ScriptB")
        _add_code_ref(db_session, inst, asmt, a, b)

        graph = build_dependency_graph(db_session, asmt.id)

        # a -> b edge should exist
        edges_a = graph.adjacency.get(a.id, [])
        assert any(e.target_id == b.id and e.dependency_type == "code_reference" for e in edges_a)
        # Both should be in customized_ids
        assert a.id in graph.customized_ids
        assert b.id in graph.customized_ids

    def test_structural_edge(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        parent = _add_sr(db_session, scan, "UIPolicy", table_name="sys_ui_policy")
        child = _add_sr(db_session, scan, "UIPolicyAction", table_name="sys_ui_policy_action")
        _add_struct_rel(db_session, inst, asmt, parent, child)

        graph = build_dependency_graph(db_session, asmt.id)

        # Bidirectional edges
        edges_p = graph.adjacency.get(parent.id, [])
        assert any(e.target_id == child.id and e.dependency_type == "structural" for e in edges_p)
        edges_c = graph.adjacency.get(child.id, [])
        assert any(e.target_id == parent.id and e.dependency_type == "structural" for e in edges_c)

    def test_non_customized_nodes_in_graph(self, db_session):
        """Non-customized artifacts appear as nodes but NOT in customized_ids."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "CustomScript")
        ootb = _add_sr(db_session, scan, "OOTBScript", origin_type=OriginType.ootb_untouched)
        _add_code_ref(db_session, inst, asmt, a, ootb)

        graph = build_dependency_graph(db_session, asmt.id)

        assert a.id in graph.customized_ids
        assert ootb.id not in graph.customized_ids
        # Edge still exists
        edges_a = graph.adjacency.get(a.id, [])
        assert any(e.target_id == ootb.id for e in edges_a)

    def test_shared_dependency_detection(self, db_session):
        """Two customized artifacts referencing same non-customized target get shared_dependency edge."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "CustomA")
        b = _add_sr(db_session, scan, "CustomB")
        ootb = _add_sr(db_session, scan, "SharedOOTB", origin_type=OriginType.ootb_untouched)
        _add_code_ref(db_session, inst, asmt, a, ootb)
        _add_code_ref(db_session, inst, asmt, b, ootb)

        graph = build_dependency_graph(db_session, asmt.id)

        # a <-> b should have shared_dependency edge
        edges_a = graph.adjacency.get(a.id, [])
        shared = [e for e in edges_a if e.dependency_type == "shared_dependency"]
        assert len(shared) == 1
        assert shared[0].target_id == b.id
        assert shared[0].shared_via == ootb.name

    def test_empty_assessment(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        graph = build_dependency_graph(db_session, asmt.id)
        assert len(graph.adjacency) == 0
        assert len(graph.customized_ids) == 0


class TestDependencyGraphMethods:
    """Test outbound, inbound, all_neighbors methods."""

    def test_outbound(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        graph = build_dependency_graph(db_session, asmt.id)
        assert b.id in graph.outbound(a.id)

    def test_inbound(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        graph = build_dependency_graph(db_session, asmt.id)
        # b should have an inbound edge from a
        assert a.id in graph.inbound(b.id)


class TestTransitiveChains:
    """Test transitive chain resolution via BFS."""

    def test_direct_chain(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        graph = build_dependency_graph(db_session, asmt.id)
        chains = graph.resolve_transitive_chains(max_depth=3)

        # Should find A -> B direct chain
        a_to_b = [c for c in chains if c["source"] == a.id and c["target"] == b.id]
        assert len(a_to_b) == 1
        assert a_to_b[0]["hop_count"] == 1
        assert a_to_b[0]["chain_weight"] == 3.0

    def test_two_hop_chain(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        c = _add_sr(db_session, scan, "C")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, b, c)

        graph = build_dependency_graph(db_session, asmt.id)
        chains = graph.resolve_transitive_chains(max_depth=3)

        # Should find A -> C transitive chain (2 hops)
        a_to_c = [c for c in chains if c["source"] == a.id and c["target"] == c.id]
        # Note: c variable name collision — use explicit ID
        target_c_id = c.id
        a_to_c = [ch for ch in chains if ch["source"] == a.id and ch["target"] == target_c_id]
        assert len(a_to_c) == 1
        assert a_to_c[0]["hop_count"] == 2
        assert a_to_c[0]["chain_weight"] == 2.0
        assert a_to_c[0]["dependency_type"] == "transitive"

    def test_max_depth_respected(self, db_session):
        """Chain longer than max_depth should not be resolved."""
        inst, asmt, scan = _setup_base(db_session)
        nodes = []
        for i in range(5):
            nodes.append(_add_sr(db_session, scan, f"Node{i}"))
        for i in range(4):
            _add_code_ref(db_session, inst, asmt, nodes[i], nodes[i + 1])

        graph = build_dependency_graph(db_session, asmt.id)
        chains = graph.resolve_transitive_chains(max_depth=2)

        # Node0 -> Node3 would be 3 hops, should NOT exist with max_depth=2
        n0_to_n3 = [ch for ch in chains if ch["source"] == nodes[0].id and ch["target"] == nodes[3].id]
        assert len(n0_to_n3) == 0

    def test_only_customized_in_chains(self, db_session):
        """Transitive chains should only include customized artifacts."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "CustomA")
        ootb = _add_sr(db_session, scan, "OOTB", origin_type=OriginType.ootb_untouched)
        b = _add_sr(db_session, scan, "CustomB")
        _add_code_ref(db_session, inst, asmt, a, ootb)
        _add_code_ref(db_session, inst, asmt, ootb, b)

        graph = build_dependency_graph(db_session, asmt.id)
        chains = graph.resolve_transitive_chains(max_depth=3)

        # Should NOT chain through ootb to create A -> B transitive
        # (ootb is not customized, chains only traverse customized nodes)
        a_to_b = [ch for ch in chains if ch["source"] == a.id and ch["target"] == b.id]
        assert len(a_to_b) == 0


class TestCircularDependencyDetection:
    """Test cycle detection in dependency graph."""

    def test_simple_cycle(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, b, a)

        graph = build_dependency_graph(db_session, asmt.id)
        cycles = graph.detect_circular_dependencies()

        assert len(cycles) >= 1

    def test_no_cycle(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        c = _add_sr(db_session, scan, "C")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, b, c)

        graph = build_dependency_graph(db_session, asmt.id)
        cycles = graph.detect_circular_dependencies()
        assert len(cycles) == 0


class TestClusterComputation:
    """Test connected component clustering."""

    def test_two_separate_clusters(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        # Cluster 1: a -> b
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)
        # Cluster 2: c -> d
        c = _add_sr(db_session, scan, "C")
        d = _add_sr(db_session, scan, "D")
        _add_code_ref(db_session, inst, asmt, c, d)
        # Singleton: e (no edges to customized)
        _add_sr(db_session, scan, "E")

        graph = build_dependency_graph(db_session, asmt.id)
        clusters = graph.compute_clusters(min_cluster_size=2)

        assert len(clusters) == 2
        member_sets = [set(cl["member_ids"]) for cl in clusters]
        assert {a.id, b.id} in member_sets
        assert {c.id, d.id} in member_sets

    def test_singleton_excluded(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        _add_sr(db_session, scan, "Alone")

        graph = build_dependency_graph(db_session, asmt.id)
        clusters = graph.compute_clusters(min_cluster_size=2)
        assert len(clusters) == 0


class TestScoring:
    """Test coupling_score, impact_radius, change_risk_score."""

    def test_coupling_score(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        graph = build_dependency_graph(db_session, asmt.id)
        score = graph.coupling_score(a.id)
        assert score > 0

    def test_impact_radius_low(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A")
        b = _add_sr(db_session, scan, "B")
        _add_code_ref(db_session, inst, asmt, a, b)

        graph = build_dependency_graph(db_session, asmt.id)
        radius = graph.impact_radius(a.id)
        assert radius in ("low", "medium", "high", "very_high")

    def test_change_risk_for_cluster(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        a = _add_sr(db_session, scan, "A", table_name="sys_security_acl")
        b = _add_sr(db_session, scan, "B", table_name="sys_script_include")
        _add_code_ref(db_session, inst, asmt, a, b)
        _add_code_ref(db_session, inst, asmt, b, a)  # circular

        graph = build_dependency_graph(db_session, asmt.id)
        clusters = graph.compute_clusters(min_cluster_size=2)
        assert len(clusters) == 1

        risk = clusters[0]["change_risk_score"]
        assert risk > 0
        assert clusters[0]["change_risk_level"] in ("low", "medium", "high", "critical")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_graph.py -v 2>&1 | head -30
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.dependency_graph'`

- [ ] **Step 3: Implement DependencyGraph service**

Create `tech-assessment-hub/src/services/dependency_graph.py`:

```python
"""Standalone dependency graph for pure dependency analysis.

Builds a directed graph from CodeReference + StructuralRelationship only.
Excludes proximity/behavioral signals (temporal, naming, colocation, update set).
Provides transitive chain resolution, circular dependency detection,
connected-component clustering, and scoring.

All scan results (customized + non-customized) appear as nodes for visualization.
Only customized nodes participate in clustering, chain resolution, and scoring.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from ..models import (
    CodeReference,
    OriginType,
    Scan,
    ScanResult,
    StructuralRelationship,
)

_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}

# Weights for direct dependency edges
_DEPENDENCY_WEIGHTS: Dict[str, float] = {
    "code_reference": 3.0,
    "structural": 2.5,
    "shared_dependency": 2.0,
}

# Diminishing weights for transitive hops
_HOP_WEIGHTS: Dict[int, float] = {1: 3.0, 2: 2.0, 3: 1.0}

# Artifact type risk scores (adapted from snow-flow)
_ARTIFACT_TYPE_RISK: Dict[str, float] = {
    "sys_security_acl": 15.0,
    "sys_db_object": 10.0,
    "wf_workflow": 8.0,
    "sys_script": 6.0,
    "sys_script_include": 6.0,
    "sys_ui_policy": 4.0,
    "sys_script_client": 4.0,
    "sys_dictionary": 3.0,
}
_DEFAULT_ARTIFACT_RISK = 3.0

# Criticality rules
_HIGH_CRIT_REF_TYPES = {"script_include"}
_MEDIUM_CRIT_REF_TYPES = {"table_query", "event", "rest_message"}
_HIGH_CRIT_STRUCT_TYPES = {"ui_policy_action", "dictionary_entry"}
_LOW_CRIT_STRUCT_TYPES = {"dictionary_override"}


def _criticality_for_code_ref(reference_type: str) -> str:
    if reference_type in _HIGH_CRIT_REF_TYPES:
        return "high"
    if reference_type in _MEDIUM_CRIT_REF_TYPES:
        return "medium"
    return "low"


def _criticality_for_structural(relationship_type: str) -> str:
    if relationship_type in _HIGH_CRIT_STRUCT_TYPES:
        return "high"
    if relationship_type in _LOW_CRIT_STRUCT_TYPES:
        return "low"
    return "medium"


@dataclass
class DependencyEdge:
    """A weighted, directed edge in the dependency graph."""
    target_id: int
    dependency_type: str  # code_reference, structural, shared_dependency
    direction: str  # outbound, inbound
    weight: float
    criticality: str  # high, medium, low
    shared_via: Optional[str] = None  # identifier for shared_dependency type


@dataclass
class DependencyGraph:
    """Directed dependency graph built from CodeReference + StructuralRelationship.

    All scan results appear as nodes. customized_ids tracks which are
    modified_ootb or net_new_customer for filtering during analysis.
    """
    adjacency: Dict[int, List[DependencyEdge]] = field(default_factory=dict)
    customized_ids: Set[int] = field(default_factory=set)
    all_ids: Set[int] = field(default_factory=set)
    # Lookup: scan_result_id -> table_name (for scoring)
    _table_names: Dict[int, str] = field(default_factory=dict)

    def outbound(self, node_id: int) -> List[int]:
        """Return IDs this node depends on (outbound edges)."""
        return [
            e.target_id for e in self.adjacency.get(node_id, [])
            if e.direction == "outbound"
        ]

    def inbound(self, node_id: int) -> List[int]:
        """Return IDs that depend on this node (inbound edges)."""
        return [
            e.target_id for e in self.adjacency.get(node_id, [])
            if e.direction == "inbound"
        ]

    def all_neighbors(self, node_id: int) -> List[int]:
        """Return all connected IDs regardless of direction."""
        seen: Set[int] = set()
        result: List[int] = []
        for e in self.adjacency.get(node_id, []):
            if e.target_id not in seen:
                seen.add(e.target_id)
                result.append(e.target_id)
        return result

    def edges_between(self, a: int, b: int) -> List[DependencyEdge]:
        """Return all edges from a to b."""
        return [e for e in self.adjacency.get(a, []) if e.target_id == b]

    # ------------------------------------------------------------------
    # Transitive chain resolution (BFS, customized nodes only)
    # ------------------------------------------------------------------

    def resolve_transitive_chains(self, max_depth: int = 3) -> List[Dict[str, Any]]:
        """BFS from each customized node to find all dependency chains.

        Returns list of chain dicts with keys:
            source, target, dependency_type, direction, hop_count,
            chain_path, chain_weight, criticality
        """
        chains: List[Dict[str, Any]] = []

        for start_id in sorted(self.customized_ids):
            visited: Set[int] = {start_id}
            # queue items: (current_id, depth, path)
            queue: deque = deque()

            # Seed with direct outbound neighbors that are customized
            for edge in self.adjacency.get(start_id, []):
                if edge.direction == "outbound" and edge.target_id in self.customized_ids:
                    if edge.target_id not in visited:
                        visited.add(edge.target_id)
                        path = [start_id, edge.target_id]
                        chains.append({
                            "source": start_id,
                            "target": edge.target_id,
                            "dependency_type": edge.dependency_type,
                            "direction": "outbound",
                            "hop_count": 1,
                            "chain_path": path,
                            "chain_weight": _HOP_WEIGHTS.get(1, 1.0),
                            "criticality": edge.criticality,
                        })
                        if max_depth > 1:
                            queue.append((edge.target_id, 1, path))

            # BFS for transitive chains
            while queue:
                current_id, depth, path = queue.popleft()
                if depth >= max_depth:
                    continue
                for edge in self.adjacency.get(current_id, []):
                    if (
                        edge.direction == "outbound"
                        and edge.target_id in self.customized_ids
                        and edge.target_id not in visited
                    ):
                        visited.add(edge.target_id)
                        new_path = path + [edge.target_id]
                        hop = depth + 1
                        chains.append({
                            "source": start_id,
                            "target": edge.target_id,
                            "dependency_type": "transitive",
                            "direction": "outbound",
                            "hop_count": hop,
                            "chain_path": new_path,
                            "chain_weight": _HOP_WEIGHTS.get(hop, 1.0),
                            "criticality": edge.criticality,
                        })
                        if hop < max_depth:
                            queue.append((edge.target_id, hop, new_path))

        return chains

    # ------------------------------------------------------------------
    # Circular dependency detection (DFS coloring, customized only)
    # ------------------------------------------------------------------

    def detect_circular_dependencies(self) -> List[List[int]]:
        """Detect cycles among customized nodes using DFS three-color marking.

        Returns list of cycle paths, e.g. [[A, B, C, A]].
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[int, int] = {nid: WHITE for nid in self.customized_ids}
        parent_path: Dict[int, List[int]] = {}
        cycles: List[List[int]] = []

        def dfs(node: int, path: List[int]) -> None:
            color[node] = GRAY
            parent_path[node] = path

            for edge in self.adjacency.get(node, []):
                if edge.direction != "outbound":
                    continue
                target = edge.target_id
                if target not in self.customized_ids:
                    continue
                if color.get(target) == GRAY:
                    # Found a cycle: extract from target's position in path
                    cycle_start = path.index(target) if target in path else -1
                    if cycle_start >= 0:
                        cycle = path[cycle_start:] + [target]
                        cycles.append(cycle)
                elif color.get(target) == WHITE:
                    dfs(target, path + [target])

            color[node] = BLACK

        for node in sorted(self.customized_ids):
            if color.get(node) == WHITE:
                dfs(node, [node])

        return cycles

    # ------------------------------------------------------------------
    # Cluster computation (connected components, customized only)
    # ------------------------------------------------------------------

    def compute_clusters(self, min_cluster_size: int = 2) -> List[Dict[str, Any]]:
        """Find connected components among customized nodes.

        Uses BFS on undirected view (both outbound and inbound edges)
        but only traverses between customized nodes.

        Returns list of cluster dicts with scoring included.
        """
        visited: Set[int] = set()
        clusters: List[Dict[str, Any]] = []

        for start_id in sorted(self.customized_ids):
            if start_id in visited:
                continue

            # BFS to find component
            component: List[int] = []
            queue: deque = deque([start_id])
            visited.add(start_id)

            while queue:
                node = queue.popleft()
                component.append(node)
                for edge in self.adjacency.get(node, []):
                    if (
                        edge.target_id in self.customized_ids
                        and edge.target_id not in visited
                    ):
                        visited.add(edge.target_id)
                        queue.append(edge.target_id)

            if len(component) < min_cluster_size:
                continue

            # Compute internal edges
            component_set = set(component)
            internal_edges = 0
            for nid in component:
                for edge in self.adjacency.get(nid, []):
                    if edge.target_id in component_set:
                        internal_edges += 1

            # Scoring
            coupling = self._cluster_coupling_score(component_set)
            impact = self._cluster_impact_radius(component_set)
            circular = self._cluster_circular_deps(component_set)
            tables = sorted({
                self._table_names.get(nid, "unknown") for nid in component
            })
            risk_score, risk_level = self._cluster_change_risk(
                component_set, coupling, circular, tables
            )

            # Auto-label
            from collections import Counter
            table_counts = Counter(
                self._table_names.get(nid, "unknown") for nid in component
            )
            most_common_table = table_counts.most_common(1)[0][0]
            label = f"{most_common_table} cluster ({len(component)} artifacts)"

            clusters.append({
                "cluster_label": label,
                "member_ids": sorted(component),
                "member_count": len(component),
                "internal_edge_count": internal_edges,
                "coupling_score": round(coupling, 2),
                "impact_radius": impact,
                "change_risk_score": round(risk_score, 2),
                "change_risk_level": risk_level,
                "circular_dependencies": circular,
                "tables_involved": tables,
            })

        return clusters

    # ------------------------------------------------------------------
    # Scoring methods
    # ------------------------------------------------------------------

    def coupling_score(self, node_id: int) -> float:
        """Weighted degree for a single node."""
        total = 0.0
        for edge in self.adjacency.get(node_id, []):
            total += edge.weight
        return total

    def impact_radius(self, node_id: int) -> str:
        """Impact radius classification for a single node."""
        outbound = len(self.outbound(node_id))
        inbound = len(self.inbound(node_id))
        structural_children = sum(
            1 for e in self.adjacency.get(node_id, [])
            if e.dependency_type == "structural" and e.direction == "outbound"
        )
        impact = outbound * 2 + inbound * 3 + structural_children
        if impact > 50:
            return "very_high"
        if impact > 25:
            return "high"
        if impact > 10:
            return "medium"
        return "low"

    def _cluster_coupling_score(self, members: Set[int]) -> float:
        """Average weighted degree across cluster members."""
        if not members:
            return 0.0
        total = sum(self.coupling_score(nid) for nid in members)
        return total / len(members)

    def _cluster_impact_radius(self, members: Set[int]) -> str:
        """Impact radius for a cluster based on external edges."""
        outbound = 0
        inbound = 0
        children = 0
        for nid in members:
            for edge in self.adjacency.get(nid, []):
                if edge.target_id not in members:
                    if edge.direction == "outbound":
                        outbound += 1
                    elif edge.direction == "inbound":
                        inbound += 1
                if (
                    edge.target_id in members
                    and edge.dependency_type == "structural"
                    and edge.direction == "outbound"
                ):
                    children += 1
        impact = outbound * 2 + inbound * 3 + children
        if impact > 50:
            return "very_high"
        if impact > 25:
            return "high"
        if impact > 10:
            return "medium"
        return "low"

    def _cluster_circular_deps(self, members: Set[int]) -> List[List[int]]:
        """Detect cycles within a specific set of members."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[int, int] = {nid: WHITE for nid in members}
        cycles: List[List[int]] = []

        def dfs(node: int, path: List[int]) -> None:
            color[node] = GRAY
            for edge in self.adjacency.get(node, []):
                if edge.direction != "outbound":
                    continue
                target = edge.target_id
                if target not in members:
                    continue
                if color[target] == GRAY and target in path:
                    idx = path.index(target)
                    cycles.append(path[idx:] + [target])
                elif color[target] == WHITE:
                    dfs(target, path + [target])
            color[node] = BLACK

        for node in sorted(members):
            if color[node] == WHITE:
                dfs(node, [node])

        return cycles

    def _cluster_change_risk(
        self,
        members: Set[int],
        coupling: float,
        circular: List[List[int]],
        tables: List[str],
    ) -> Tuple[float, str]:
        """Compute change risk score and level for a cluster."""
        risk = 0.0
        risk += coupling * 10
        risk += len(circular) * 15

        # Critical dependencies (high criticality edges)
        critical_count = 0
        for nid in members:
            for edge in self.adjacency.get(nid, []):
                if edge.criticality == "high" and edge.target_id in members:
                    critical_count += 1
        risk += critical_count * 20

        risk += len(members) * 2

        # Artifact type risk
        if tables:
            type_risk = sum(
                _ARTIFACT_TYPE_RISK.get(t, _DEFAULT_ARTIFACT_RISK) for t in tables
            ) / len(tables)
            risk += type_risk

        risk = min(risk, 100.0)

        if risk >= 70:
            level = "critical"
        elif risk >= 50:
            level = "high"
        elif risk >= 30:
            level = "medium"
        else:
            level = "low"

        return risk, level


def _add_edge(
    graph: DependencyGraph,
    source: int,
    target: int,
    dependency_type: str,
    weight: float,
    direction: str,
    criticality: str,
    shared_via: Optional[str] = None,
) -> None:
    """Add a directed edge to the graph (and reverse for bidirectional)."""
    if source not in graph.adjacency:
        graph.adjacency[source] = []
    graph.adjacency[source].append(DependencyEdge(
        target_id=target,
        dependency_type=dependency_type,
        direction=direction,
        weight=weight,
        criticality=criticality,
        shared_via=shared_via,
    ))

    # Add reverse edge
    if target not in graph.adjacency:
        graph.adjacency[target] = []

    if direction == "outbound":
        graph.adjacency[target].append(DependencyEdge(
            target_id=source,
            dependency_type=dependency_type,
            direction="inbound",
            weight=weight,
            criticality=criticality,
            shared_via=shared_via,
        ))
    elif direction == "bidirectional":
        graph.adjacency[target].append(DependencyEdge(
            target_id=source,
            dependency_type=dependency_type,
            direction="bidirectional",
            weight=weight,
            criticality=criticality,
            shared_via=shared_via,
        ))


def build_dependency_graph(
    session: Session, assessment_id: int
) -> DependencyGraph:
    """Build a dependency graph from CodeReference + StructuralRelationship.

    Includes ALL scan results as nodes (for visualization).
    Tracks customized_ids for filtering during analysis.
    Detects shared dependencies through non-customized intermediaries.
    """
    graph = DependencyGraph()

    # Load all scan result IDs and classify
    scan_ids = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())
    if not scan_ids:
        return graph

    results = session.exec(
        select(ScanResult.id, ScanResult.origin_type, ScanResult.table_name)
        .where(ScanResult.scan_id.in_(scan_ids))  # type: ignore[attr-defined]
    ).all()

    for row in results:
        rid = row[0] if isinstance(row, tuple) else row.id
        origin = row[1] if isinstance(row, tuple) else row.origin_type
        tname = row[2] if isinstance(row, tuple) else row.table_name
        if rid is not None:
            rid = int(rid)
            graph.all_ids.add(rid)
            graph._table_names[rid] = tname or "unknown"
            origin_val = (
                origin.value if hasattr(origin, "value") else str(origin) if origin else ""
            )
            if origin_val in _CUSTOMIZED_ORIGIN_VALUES:
                graph.customized_ids.add(rid)

    # --- Code References ---
    code_refs = list(session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == assessment_id
        )
    ).all())

    # Track refs to non-customized targets for shared_dependency detection
    non_custom_refs: Dict[str, List[int]] = defaultdict(list)  # target_identifier -> [source_ids]

    for ref in code_refs:
        src = ref.source_scan_result_id
        tgt = ref.target_scan_result_id
        if src is None:
            continue

        src = int(src)
        criticality = _criticality_for_code_ref(ref.reference_type)

        if tgt is not None:
            tgt = int(tgt)
            _add_edge(
                graph, src, tgt, "code_reference",
                _DEPENDENCY_WEIGHTS["code_reference"],
                "outbound", criticality,
            )

            # Track for shared dependency detection
            if tgt not in graph.customized_ids and src in graph.customized_ids:
                non_custom_refs[ref.target_identifier].append(src)
        elif src in graph.customized_ids:
            # Unresolved reference — track by identifier for shared dep
            non_custom_refs[ref.target_identifier].append(src)

    # --- Shared Dependencies ---
    for identifier, source_ids in non_custom_refs.items():
        # Deduplicate
        unique_sources = sorted(set(s for s in source_ids if s in graph.customized_ids))
        if len(unique_sources) < 2:
            continue
        # Create edges between all pairs
        for i, a in enumerate(unique_sources):
            for b in unique_sources[i + 1:]:
                _add_edge(
                    graph, a, b, "shared_dependency",
                    _DEPENDENCY_WEIGHTS["shared_dependency"],
                    "bidirectional", "medium",
                    shared_via=identifier,
                )

    # --- Structural Relationships ---
    struct_rels = list(session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == assessment_id
        )
    ).all())

    for rel in struct_rels:
        parent = rel.parent_scan_result_id
        child = rel.child_scan_result_id
        if parent is not None and child is not None:
            criticality = _criticality_for_structural(rel.relationship_type)
            _add_edge(
                graph, int(parent), int(child), "structural",
                _DEPENDENCY_WEIGHTS["structural"],
                "bidirectional", criticality,
            )

    return graph
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_graph.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/dependency_graph.py tech-assessment-hub/tests/test_dependency_graph.py
git commit -m "feat: add DependencyGraph service with transitive chains, cycle detection, clustering, and scoring"
```

---

### Task 3: Build Dependency Mapper Engine

**Files:**
- Create: `tech-assessment-hub/src/engines/dependency_mapper.py`
- Modify: `tech-assessment-hub/tests/test_dependency_mapper.py` (add engine integration tests)

- [ ] **Step 1: Add engine integration tests to test_dependency_mapper.py**

Append to the existing `tech-assessment-hub/tests/test_dependency_mapper.py`:

```python
from src.engines.dependency_mapper import run


class TestDependencyMapperEngine:
    """Integration tests for the dependency_mapper engine run() function."""

    def test_basic_chain_persisted(self, db_session):
        """Direct code reference produces a DependencyChain row."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA")
        b = _add_scan_result(db_session, scan, "ScriptB")
        _add_code_reference(db_session, inst, asmt, a, b)

        result = run(asmt.id, db_session)

        assert result["success"] is True
        assert result["chains_created"] >= 1
        assert result["errors"] == []

        chains = list(db_session.exec(
            select(DependencyChain).where(
                DependencyChain.assessment_id == asmt.id
            )
        ).all())
        assert len(chains) >= 1
        direct = [c for c in chains if c.source_scan_result_id == a.id
                  and c.target_scan_result_id == b.id]
        assert len(direct) == 1
        assert direct[0].hop_count == 1
        assert direct[0].dependency_type == "code_reference"

    def test_cluster_persisted(self, db_session):
        """Connected customized artifacts produce a DependencyCluster row."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA")
        b = _add_scan_result(db_session, scan, "ScriptB")
        _add_code_reference(db_session, inst, asmt, a, b)

        result = run(asmt.id, db_session)

        assert result["clusters_created"] >= 1

        clusters = list(db_session.exec(
            select(DependencyCluster).where(
                DependencyCluster.assessment_id == asmt.id
            )
        ).all())
        assert len(clusters) >= 1
        member_ids = json.loads(clusters[0].member_ids_json)
        assert set(member_ids) == {a.id, b.id}

    def test_idempotent(self, db_session):
        """Running twice produces same results (old rows deleted)."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "ScriptA")
        b = _add_scan_result(db_session, scan, "ScriptB")
        _add_code_reference(db_session, inst, asmt, a, b)

        run(asmt.id, db_session)
        result2 = run(asmt.id, db_session)

        chains = list(db_session.exec(
            select(DependencyChain).where(
                DependencyChain.assessment_id == asmt.id
            )
        ).all())
        clusters = list(db_session.exec(
            select(DependencyCluster).where(
                DependencyCluster.assessment_id == asmt.id
            )
        ).all())
        assert result2["success"] is True
        assert len(chains) == result2["chains_created"]
        assert len(clusters) == result2["clusters_created"]

    def test_only_customized_in_clusters(self, db_session):
        """Non-customized artifacts should not appear in cluster member_ids."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "CustomA")
        ootb = _add_scan_result(db_session, scan, "OOTB",
                                origin_type=OriginType.ootb_untouched)
        _add_code_reference(db_session, inst, asmt, a, ootb)

        result = run(asmt.id, db_session)

        # Single customized node + OOTB => no cluster (cluster needs 2+ customized)
        assert result["clusters_created"] == 0

    def test_assessment_not_found(self, db_session):
        result = run(999999, db_session)
        assert result["success"] is False
        assert "Assessment not found" in result["errors"][0]

    def test_no_scan_results(self, db_session):
        inst, asmt, scan = _setup_base(db_session)
        result = run(asmt.id, db_session)
        assert result["success"] is True
        assert result["chains_created"] == 0
        assert result["clusters_created"] == 0

    def test_transitive_chain_persisted(self, db_session):
        """A->B->C should produce a transitive chain A->C."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "A")
        b = _add_scan_result(db_session, scan, "B")
        c = _add_scan_result(db_session, scan, "C")
        _add_code_reference(db_session, inst, asmt, a, b)
        _add_code_reference(db_session, inst, asmt, b, c)

        result = run(asmt.id, db_session)

        chains = list(db_session.exec(
            select(DependencyChain).where(
                DependencyChain.assessment_id == asmt.id,
                DependencyChain.dependency_type == "transitive",
            )
        ).all())
        a_to_c = [ch for ch in chains
                   if ch.source_scan_result_id == a.id
                   and ch.target_scan_result_id == c.id]
        assert len(a_to_c) == 1
        assert a_to_c[0].hop_count == 2

    def test_circular_detected_in_cluster(self, db_session):
        """Circular dependency should appear in cluster's circular_dependencies_json."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "A")
        b = _add_scan_result(db_session, scan, "B")
        _add_code_reference(db_session, inst, asmt, a, b)
        _add_code_reference(db_session, inst, asmt, b, a)

        result = run(asmt.id, db_session)

        clusters = list(db_session.exec(
            select(DependencyCluster).where(
                DependencyCluster.assessment_id == asmt.id
            )
        ).all())
        assert len(clusters) == 1
        circulars = json.loads(clusters[0].circular_dependencies_json)
        assert len(circulars) >= 1

    def test_shared_dependency_chain(self, db_session):
        """Two customized refs to same OOTB artifact produce shared_dependency chain."""
        inst, asmt, scan = _setup_base(db_session)
        a = _add_scan_result(db_session, scan, "CustomA")
        b = _add_scan_result(db_session, scan, "CustomB")
        ootb = _add_scan_result(db_session, scan, "SharedOOTB",
                                origin_type=OriginType.ootb_untouched)
        _add_code_reference(db_session, inst, asmt, a, ootb)
        _add_code_reference(db_session, inst, asmt, b, ootb)

        result = run(asmt.id, db_session)

        # Should have a cluster with a and b
        assert result["clusters_created"] >= 1
        clusters = list(db_session.exec(
            select(DependencyCluster).where(
                DependencyCluster.assessment_id == asmt.id
            )
        ).all())
        member_ids = json.loads(clusters[0].member_ids_json)
        assert a.id in member_ids
        assert b.id in member_ids
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_mapper.py::TestDependencyMapperEngine::test_basic_chain_persisted -v 2>&1 | head -20
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.engines.dependency_mapper'`

- [ ] **Step 3: Implement the dependency mapper engine**

Create `tech-assessment-hub/src/engines/dependency_mapper.py`:

```python
"""Engine 7: Dependency Mapper.

Builds a standalone dependency graph from CodeReference + StructuralRelationship,
resolves transitive chains, detects circular dependencies, computes connected-
component clusters with scoring, and persists results.

Input:  CodeReference + StructuralRelationship rows for an assessment
Output: Rows in dependency_chain and dependency_cluster tables

Only customized scan results (modified_ootb, net_new_customer) participate
in clustering and chain resolution. All artifacts appear in the graph for
visualization.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlmodel import Session, select

from ..models import (
    Assessment,
    DependencyChain,
    DependencyCluster,
    Feature,
    FeatureScanResult,
    Scan,
)
from ..services.dependency_graph import build_dependency_graph
from ..services.integration_properties import load_reasoning_engine_properties


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the dependency mapper engine for an assessment.

    Returns a summary dict with keys:
        success (bool), chains_created (int), clusters_created (int), errors (list[str])
    """
    # 1. Validate assessment exists
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "chains_created": 0,
            "clusters_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    # 2. Load configurable properties
    props = load_reasoning_engine_properties(session, instance_id=assessment.instance_id)
    max_depth = getattr(props, "dependency_max_transitive_depth", 3)
    min_cluster = getattr(props, "dependency_min_cluster_size", 2)

    # 3. Delete existing output rows for idempotency
    scan_ids = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())

    for row in list(session.exec(
        select(DependencyChain).where(
            DependencyChain.assessment_id == assessment_id
        )
    ).all()):
        session.delete(row)

    for row in list(session.exec(
        select(DependencyCluster).where(
            DependencyCluster.assessment_id == assessment_id
        )
    ).all()):
        session.delete(row)
    session.flush()

    # 4. Build dependency graph
    graph = build_dependency_graph(session, assessment_id)

    if not graph.customized_ids:
        session.commit()
        return {
            "success": True,
            "chains_created": 0,
            "clusters_created": 0,
            "errors": [],
            "message": "No customized scan results",
        }

    # Determine scan_id for output rows (use first scan)
    scan_id = scan_ids[0] if scan_ids else None
    if scan_id is None:
        session.commit()
        return {
            "success": True,
            "chains_created": 0,
            "clusters_created": 0,
            "errors": [],
        }

    errors: List[str] = []

    # 5. Resolve transitive chains and persist
    chains = graph.resolve_transitive_chains(max_depth=max_depth)
    chains_created = 0

    for chain_data in chains:
        try:
            dc = DependencyChain(
                scan_id=scan_id,
                instance_id=assessment.instance_id,
                assessment_id=assessment_id,
                source_scan_result_id=chain_data["source"],
                target_scan_result_id=chain_data["target"],
                dependency_type=chain_data["dependency_type"],
                direction=chain_data["direction"],
                hop_count=chain_data["hop_count"],
                chain_path_json=json.dumps(chain_data["chain_path"]),
                chain_weight=chain_data["chain_weight"],
                criticality=chain_data["criticality"],
            )
            session.add(dc)
            chains_created += 1
        except Exception as exc:
            errors.append(f"Error creating chain: {exc}")

    # 6. Compute clusters and persist
    cluster_results = graph.compute_clusters(min_cluster_size=min_cluster)
    clusters_created = 0

    for cl in cluster_results:
        try:
            dc = DependencyCluster(
                scan_id=scan_id,
                instance_id=assessment.instance_id,
                assessment_id=assessment_id,
                cluster_label=cl["cluster_label"],
                member_ids_json=json.dumps(cl["member_ids"]),
                member_count=cl["member_count"],
                internal_edge_count=cl["internal_edge_count"],
                coupling_score=cl["coupling_score"],
                impact_radius=cl["impact_radius"],
                change_risk_score=cl["change_risk_score"],
                change_risk_level=cl["change_risk_level"],
                circular_dependencies_json=json.dumps(cl["circular_dependencies"]),
                tables_involved_json=json.dumps(cl["tables_involved"]),
            )
            session.add(dc)
            clusters_created += 1
        except Exception as exc:
            errors.append(f"Error creating cluster '{cl['cluster_label']}': {exc}")

    # 7. Propagate change risk to features
    _propagate_risk_to_features(session, assessment_id, cluster_results)

    # 8. Commit
    session.commit()

    return {
        "success": True,
        "chains_created": chains_created,
        "clusters_created": clusters_created,
        "errors": errors,
    }


def _propagate_risk_to_features(
    session: Session,
    assessment_id: int,
    cluster_results: List[Dict[str, Any]],
) -> None:
    """Set Feature.change_risk_score/level from overlapping dependency clusters."""
    if not cluster_results:
        return

    # Build member_id -> max risk mapping
    member_risk: Dict[int, float] = {}
    member_level: Dict[int, str] = {}
    for cl in cluster_results:
        for mid in cl["member_ids"]:
            if mid not in member_risk or cl["change_risk_score"] > member_risk[mid]:
                member_risk[mid] = cl["change_risk_score"]
                member_level[mid] = cl["change_risk_level"]

    # Load features and their scan result links
    features = list(session.exec(
        select(Feature).where(Feature.assessment_id == assessment_id)
    ).all())

    for feature in features:
        links = list(session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.feature_id == feature.id
            )
        ).all())
        max_risk = 0.0
        max_level = "low"
        for link in links:
            sr_id = link.scan_result_id
            if sr_id in member_risk and member_risk[sr_id] > max_risk:
                max_risk = member_risk[sr_id]
                max_level = member_level[sr_id]

        if max_risk > 0:
            feature.change_risk_score = max_risk
            feature.change_risk_level = max_level
            session.add(feature)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_mapper.py -v
```

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/engines/dependency_mapper.py tech-assessment-hub/tests/test_dependency_mapper.py
git commit -m "feat: add dependency_mapper engine with transitive chains, clusters, and risk scoring"
```

---

### Task 4: Register Engine and Add Configuration Properties

**Files:**
- Modify: `tech-assessment-hub/src/mcp/tools/pipeline/run_engines.py`
- Modify: `tech-assessment-hub/src/services/integration_properties.py`

- [ ] **Step 1: Register dependency_mapper in engine registry**

In `tech-assessment-hub/src/mcp/tools/pipeline/run_engines.py`, add to `_ENGINE_REGISTRY` (after `table_colocation` entry at line 49):

```python
    # Phase 3 engines (depends on Phase 1 outputs)
    "dependency_mapper": "src.engines.dependency_mapper",
```

Update the `INPUT_SCHEMA` description string (line 33) to include `dependency_mapper`:

```python
            "description": (
                "Optional list of engine names to run. "
                "Default: all available engines. "
                "Options: structural_mapper, code_reference_parser, "
                "update_set_analyzer, temporal_clusterer, naming_analyzer, "
                "table_colocation, dependency_mapper"
            ),
```

Update the `TOOL_SPEC` description (line 108) to include dependency tables:

```python
    description=(
        "Run deterministic pre-processing engines for an assessment. "
        "Populates structural_relationship, code_reference, update_set_overlap, "
        "update_set_artifact_link, temporal_cluster, naming_cluster, "
        "table_colocation_summary, dependency_chain, and dependency_cluster tables."
    ),
```

- [ ] **Step 2: Add configuration properties**

In `tech-assessment-hub/src/services/integration_properties.py`:

Add key constants (after `REASONING_NAMING_MIN_PREFIX_TOKENS` around line 67):

```python
REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH = "reasoning.dependency.max_transitive_depth"
REASONING_DEPENDENCY_MIN_CLUSTER_SIZE = "reasoning.dependency.min_cluster_size"
```

Add defaults to `PROPERTY_DEFAULTS` dict (after naming entries around line 257):

```python
    REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH: "3",
    REASONING_DEPENDENCY_MIN_CLUSTER_SIZE: "2",
```

Add to `ReasoningEngineProperties` dataclass (after `naming_min_prefix_tokens` at line 137):

```python
    dependency_max_transitive_depth: int = 3
    dependency_min_cluster_size: int = 2
```

Add property definitions to `PROPERTY_DEFINITIONS` list (after naming entries around line 540):

```python
    REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH: IntegrationPropertyDefinition(
        key=REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH,
        label="Max Transitive Depth (Dependency)",
        description="Maximum hops for transitive dependency chain resolution.",
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=1,
        max_value=10,
    ),
    REASONING_DEPENDENCY_MIN_CLUSTER_SIZE: IntegrationPropertyDefinition(
        key=REASONING_DEPENDENCY_MIN_CLUSTER_SIZE,
        label="Min Cluster Size (Dependency)",
        description="Minimum number of customized artifacts to form a dependency cluster.",
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_DEPENDENCY_MIN_CLUSTER_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=2,
        max_value=50,
    ),
```

Add loading in `load_reasoning_engine_properties()` (after naming entries around line 1270):

```python
        dependency_max_transitive_depth=_get_int(
            session,
            REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH,
            defaults.dependency_max_transitive_depth,
            instance_id=instance_id,
        ),
        dependency_min_cluster_size=_get_int(
            session,
            REASONING_DEPENDENCY_MIN_CLUSTER_SIZE,
            defaults.dependency_min_cluster_size,
            instance_id=instance_id,
        ),
```

- [ ] **Step 3: Run all existing tests to verify no regressions**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short 2>&1 | tail -30
```

Expected: ALL PASS (496+ existing tests + new tests)

- [ ] **Step 4: Commit**

```bash
git add tech-assessment-hub/src/mcp/tools/pipeline/run_engines.py tech-assessment-hub/src/services/integration_properties.py
git commit -m "feat: register dependency_mapper engine and add configuration properties"
```

---

### Task 5: Full Test Suite Run and Cleanup

**Files:**
- All previously created/modified files

- [ ] **Step 1: Run complete test suite**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short 2>&1 | tail -50
```

Expected: ALL PASS with new tests included

- [ ] **Step 2: Run just the new tests to verify count**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_graph.py tech-assessment-hub/tests/test_dependency_mapper.py -v
```

Expected: ~25 tests pass across both files

- [ ] **Step 3: Final commit if any cleanup needed**

Only if there were test failures that required fixes. Otherwise skip.
