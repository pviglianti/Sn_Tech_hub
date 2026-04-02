# Dependency Data AI Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface dependency chain and cluster data into the AI reasoning loop so the AI can factor dependency coupling, blast radius, and OOTB alternatives into assessment recommendations.

**Architecture:** Hybrid approach — enrich existing tool responses (`get_result_detail`, `feature_detail`) with lightweight dependency summaries, add a new `get_dependency_context` deep-dive tool, enrich deterministic observations, and update AI prompts and stage tool sets.

**Tech Stack:** Python, SQLModel, SQLAlchemy, pytest. All code lives in `tech-assessment-hub/src/` and `tech-assessment-hub/tests/`.

**Spec:** `docs/superpowers/specs/2026-03-28-dependency-ai-integration-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/mcp/tools/core/dependency_context.py` | New `get_dependency_context` MCP tool |
| Create | `tests/test_dependency_context.py` | Tests for the new tool |
| Modify | `src/mcp/tools/core/result_detail.py` | Add `dependency_summary` to response |
| Modify | `src/mcp/tools/core/feature_detail.py` | Add `dependency_risk` + `dependency_clusters` to response |
| Modify | `src/mcp/tools/pipeline/generate_observations.py` | Add dependency section to observations |
| Modify | `src/mcp/registry.py` | Register `get_dependency_context` tool |
| Modify | `src/services/ai_stage_tool_sets.py` | Add new tools to ai_analysis + ai_refinement sets |
| Modify | `src/services/ai_analysis_dispatch.py` | Add dependency awareness to AI analysis prompt |
| Extend | `tests/test_generate_observations.py` | Add dependency observation tests |

---

### Task 1: New `get_dependency_context` Tool — Tests

**Files:**
- Create: `tech-assessment-hub/tests/test_dependency_context.py`

- [ ] **Step 1: Write test scaffolding and helper**

Create the test file with the shared helper that builds Instance + Assessment + Scan + ScanResults + DependencyChain + DependencyCluster fixtures.

```python
"""Tests for the get_dependency_context MCP tool."""

import json

import pytest
from sqlmodel import Session

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    DependencyChain,
    DependencyCluster,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


def _seed_dependency_data(session: Session):
    """Create test fixtures: 3 artifacts with chains and 1 cluster."""
    inst = Instance(
        name="dep-ctx-inst",
        url="https://depctx.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Dep Context Test",
        number="ASMT0080",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="Dep Scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    sr_a = ScanResult(
        scan_id=scan.id, sys_id="aaa", table_name="sys_script",
        name="BR Alpha", origin_type=OriginType.modified_ootb,
    )
    sr_b = ScanResult(
        scan_id=scan.id, sys_id="bbb", table_name="sys_script_include",
        name="SI Beta", origin_type=OriginType.net_new_customer,
    )
    sr_c = ScanResult(
        scan_id=scan.id, sys_id="ccc", table_name="sys_ui_policy",
        name="UI Gamma", origin_type=OriginType.modified_ootb,
    )
    session.add_all([sr_a, sr_b, sr_c])
    session.flush()

    # Chain: A -> B (direct, outbound from A)
    chain_ab = DependencyChain(
        scan_id=scan.id, instance_id=inst.id, assessment_id=asmt.id,
        source_scan_result_id=sr_a.id, target_scan_result_id=sr_b.id,
        dependency_type="code_reference", direction="outbound",
        hop_count=1, chain_path_json=json.dumps([sr_a.id, sr_b.id]),
        chain_weight=3.0, criticality="high",
    )
    # Chain: C -> A (direct, inbound to A)
    chain_ca = DependencyChain(
        scan_id=scan.id, instance_id=inst.id, assessment_id=asmt.id,
        source_scan_result_id=sr_c.id, target_scan_result_id=sr_a.id,
        dependency_type="structural", direction="outbound",
        hop_count=1, chain_path_json=json.dumps([sr_c.id, sr_a.id]),
        chain_weight=3.0, criticality="medium",
    )
    # Chain: C -> B (transitive, 2-hop)
    chain_cb = DependencyChain(
        scan_id=scan.id, instance_id=inst.id, assessment_id=asmt.id,
        source_scan_result_id=sr_c.id, target_scan_result_id=sr_b.id,
        dependency_type="transitive", direction="outbound",
        hop_count=2, chain_path_json=json.dumps([sr_c.id, sr_a.id, sr_b.id]),
        chain_weight=2.0, criticality="low",
    )
    session.add_all([chain_ab, chain_ca, chain_cb])
    session.flush()

    cluster = DependencyCluster(
        scan_id=scan.id, instance_id=inst.id, assessment_id=asmt.id,
        cluster_label="incident table cluster (3 artifacts)",
        member_ids_json=json.dumps([sr_a.id, sr_b.id, sr_c.id]),
        member_count=3, internal_edge_count=3,
        coupling_score=0.85, impact_radius="very_high",
        change_risk_score=72.5, change_risk_level="high",
        circular_dependencies_json=json.dumps([[sr_a.id, sr_b.id, sr_a.id]]),
        tables_involved_json=json.dumps(["sys_script", "sys_script_include", "sys_ui_policy"]),
    )
    session.add(cluster)
    session.flush()

    return {
        "instance": inst, "assessment": asmt, "scan": scan,
        "sr_a": sr_a, "sr_b": sr_b, "sr_c": sr_c,
        "chain_ab": chain_ab, "chain_ca": chain_ca, "chain_cb": chain_cb,
        "cluster": cluster,
    }


class TestGetDependencyContextByScanResult:
    def test_returns_chains_and_clusters(self, db_session):
        data = _seed_dependency_data(db_session)
        from src.mcp.tools.core.dependency_context import handle

        result = handle(
            {"assessment_id": data["assessment"].id, "scan_result_id": data["sr_a"].id},
            db_session,
        )
        assert result["success"] is True
        assert result["artifact"]["id"] == data["sr_a"].id
        # A has 1 outbound (A->B) and 1 inbound (C->A)
        assert len(result["outbound_chains"]) == 1
        assert len(result["inbound_chains"]) == 1
        assert result["outbound_chains"][0]["target_id"] == data["sr_b"].id
        assert result["inbound_chains"][0]["source_id"] == data["sr_c"].id
        assert len(result["cluster_memberships"]) == 1
        assert result["cluster_memberships"][0]["cluster_id"] == data["cluster"].id

    def test_no_dependency_data_returns_empty(self, db_session):
        """Artifact with no chains or clusters returns empty lists."""
        data = _seed_dependency_data(db_session)
        # Create an isolated artifact with no chains
        orphan = ScanResult(
            scan_id=data["scan"].id, sys_id="zzz", table_name="sys_choice",
            name="Orphan", origin_type=OriginType.modified_ootb,
        )
        db_session.add(orphan)
        db_session.flush()

        from src.mcp.tools.core.dependency_context import handle

        result = handle(
            {"assessment_id": data["assessment"].id, "scan_result_id": orphan.id},
            db_session,
        )
        assert result["success"] is True
        assert result["inbound_chains"] == []
        assert result["outbound_chains"] == []
        assert result["cluster_memberships"] == []

    def test_invalid_scan_result_id_raises(self, db_session):
        data = _seed_dependency_data(db_session)
        from src.mcp.tools.core.dependency_context import handle

        with pytest.raises(ValueError, match="ScanResult not found"):
            handle(
                {"assessment_id": data["assessment"].id, "scan_result_id": 99999},
                db_session,
            )


class TestGetDependencyContextByCluster:
    def test_returns_cluster_with_members_and_edges(self, db_session):
        data = _seed_dependency_data(db_session)
        from src.mcp.tools.core.dependency_context import handle

        result = handle(
            {"assessment_id": data["assessment"].id, "cluster_id": data["cluster"].id},
            db_session,
        )
        assert result["success"] is True
        assert result["cluster"]["id"] == data["cluster"].id
        assert result["cluster"]["coupling_score"] == 0.85
        assert len(result["members"]) == 3
        member_ids = {m["id"] for m in result["members"]}
        assert data["sr_a"].id in member_ids
        assert len(result["internal_edges"]) >= 1

    def test_invalid_cluster_id_raises(self, db_session):
        data = _seed_dependency_data(db_session)
        from src.mcp.tools.core.dependency_context import handle

        with pytest.raises(ValueError, match="DependencyCluster not found"):
            handle(
                {"assessment_id": data["assessment"].id, "cluster_id": 99999},
                db_session,
            )


class TestGetDependencyContextValidation:
    def test_requires_at_least_one_target(self, db_session):
        data = _seed_dependency_data(db_session)
        from src.mcp.tools.core.dependency_context import handle

        with pytest.raises(ValueError, match="scan_result_id.*or.*cluster_id"):
            handle({"assessment_id": data["assessment"].id}, db_session)

    def test_requires_assessment_id(self, db_session):
        from src.mcp.tools.core.dependency_context import handle

        with pytest.raises((ValueError, KeyError)):
            handle({"scan_result_id": 1}, db_session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_context.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.mcp.tools.core.dependency_context'`

- [ ] **Step 3: Commit test file**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App
git add tech-assessment-hub/tests/test_dependency_context.py
git commit -m "test: add failing tests for get_dependency_context MCP tool"
```

---

### Task 2: New `get_dependency_context` Tool — Implementation

**Files:**
- Create: `tech-assessment-hub/src/mcp/tools/core/dependency_context.py`
- Modify: `tech-assessment-hub/src/mcp/registry.py:246-249`

- [ ] **Step 1: Create the tool implementation**

```python
"""MCP tool: get_dependency_context — deep-dive into dependency chains and clusters.

Returns full chain paths, circular dependencies, and cluster membership details
for a specific artifact or cluster. Use after seeing a concerning dependency_summary
in get_result_detail or dependency_clusters in feature_detail.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import DependencyChain, DependencyCluster, ScanResult


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment ID to scope the query.",
        },
        "scan_result_id": {
            "type": "integer",
            "description": "Optional scan result ID to get dependency chains and cluster membership for.",
        },
        "cluster_id": {
            "type": "integer",
            "description": "Optional cluster ID to get full cluster detail with members and edges.",
        },
    },
    "required": ["assessment_id"],
}


def _chains_for_artifact(
    session: Session, assessment_id: int, scan_result_id: int
) -> Dict[str, List[Dict[str, Any]]]:
    """Return inbound and outbound chains for a single artifact."""
    outbound = session.exec(
        select(DependencyChain).where(
            DependencyChain.assessment_id == assessment_id,
            DependencyChain.source_scan_result_id == scan_result_id,
        )
    ).all()
    inbound = session.exec(
        select(DependencyChain).where(
            DependencyChain.assessment_id == assessment_id,
            DependencyChain.target_scan_result_id == scan_result_id,
        )
    ).all()

    def _format_outbound(chain: DependencyChain) -> Dict[str, Any]:
        target = session.get(ScanResult, chain.target_scan_result_id)
        return {
            "target_id": chain.target_scan_result_id,
            "target_name": target.name if target else None,
            "dependency_type": chain.dependency_type,
            "hop_count": chain.hop_count,
            "chain_weight": chain.chain_weight,
            "criticality": chain.criticality,
            "chain_path": json.loads(chain.chain_path_json) if chain.chain_path_json else [],
        }

    def _format_inbound(chain: DependencyChain) -> Dict[str, Any]:
        source = session.get(ScanResult, chain.source_scan_result_id)
        return {
            "source_id": chain.source_scan_result_id,
            "source_name": source.name if source else None,
            "dependency_type": chain.dependency_type,
            "hop_count": chain.hop_count,
            "chain_weight": chain.chain_weight,
            "criticality": chain.criticality,
            "chain_path": json.loads(chain.chain_path_json) if chain.chain_path_json else [],
        }

    return {
        "outbound_chains": [_format_outbound(c) for c in outbound],
        "inbound_chains": [_format_inbound(c) for c in inbound],
    }


def _clusters_for_artifact(
    session: Session, assessment_id: int, scan_result_id: int
) -> List[Dict[str, Any]]:
    """Return all clusters that contain the given artifact."""
    all_clusters = session.exec(
        select(DependencyCluster).where(
            DependencyCluster.assessment_id == assessment_id,
        )
    ).all()

    memberships: List[Dict[str, Any]] = []
    for cluster in all_clusters:
        member_ids = json.loads(cluster.member_ids_json) if cluster.member_ids_json else []
        if scan_result_id in member_ids:
            memberships.append({
                "cluster_id": cluster.id,
                "cluster_label": cluster.cluster_label,
                "coupling_score": cluster.coupling_score,
                "impact_radius": cluster.impact_radius,
                "circular_dependencies": (
                    json.loads(cluster.circular_dependencies_json)
                    if cluster.circular_dependencies_json else []
                ),
                "change_risk_level": cluster.change_risk_level,
            })
    return memberships


def _cluster_detail(
    session: Session, assessment_id: int, cluster_id: int
) -> Dict[str, Any]:
    """Return full cluster detail with members and internal edges."""
    cluster = session.get(DependencyCluster, cluster_id)
    if not cluster or cluster.assessment_id != assessment_id:
        raise ValueError(f"DependencyCluster not found: {cluster_id}")

    member_ids = json.loads(cluster.member_ids_json) if cluster.member_ids_json else []
    members: List[Dict[str, Any]] = []
    for mid in member_ids:
        sr = session.get(ScanResult, mid)
        if sr:
            members.append({
                "id": sr.id,
                "name": sr.name,
                "table_name": sr.table_name,
                "origin_type": sr.origin_type.value if sr.origin_type else None,
            })

    # Internal edges: chains where both source and target are cluster members
    member_id_set = set(member_ids)
    internal_edges: List[Dict[str, Any]] = []
    chains = session.exec(
        select(DependencyChain).where(
            DependencyChain.assessment_id == assessment_id,
            DependencyChain.source_scan_result_id.in_(member_ids),
            DependencyChain.target_scan_result_id.in_(member_ids),
        )
    ).all()
    for chain in chains:
        internal_edges.append({
            "source_id": chain.source_scan_result_id,
            "target_id": chain.target_scan_result_id,
            "dependency_type": chain.dependency_type,
            "criticality": chain.criticality,
        })

    return {
        "cluster": {
            "id": cluster.id,
            "cluster_label": cluster.cluster_label,
            "member_count": cluster.member_count,
            "coupling_score": cluster.coupling_score,
            "impact_radius": cluster.impact_radius,
            "change_risk_score": cluster.change_risk_score,
            "change_risk_level": cluster.change_risk_level,
            "tables_involved": (
                json.loads(cluster.tables_involved_json)
                if cluster.tables_involved_json else []
            ),
            "circular_dependencies": (
                json.loads(cluster.circular_dependencies_json)
                if cluster.circular_dependencies_json else []
            ),
        },
        "members": members,
        "internal_edges": internal_edges,
    }


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = params.get("assessment_id")
    if assessment_id is None:
        raise ValueError("assessment_id is required")
    assessment_id = int(assessment_id)

    scan_result_id = params.get("scan_result_id")
    cluster_id = params.get("cluster_id")

    if scan_result_id is None and cluster_id is None:
        raise ValueError("At least one of scan_result_id or cluster_id is required")

    if scan_result_id is not None:
        scan_result_id = int(scan_result_id)
        sr = session.get(ScanResult, scan_result_id)
        if not sr:
            raise ValueError(f"ScanResult not found: {scan_result_id}")

        chain_data = _chains_for_artifact(session, assessment_id, scan_result_id)
        cluster_memberships = _clusters_for_artifact(session, assessment_id, scan_result_id)

        return {
            "success": True,
            "artifact": {
                "id": sr.id,
                "name": sr.name,
                "table_name": sr.table_name,
            },
            **chain_data,
            "cluster_memberships": cluster_memberships,
        }

    if cluster_id is not None:
        cluster_id = int(cluster_id)
        detail = _cluster_detail(session, assessment_id, cluster_id)
        return {"success": True, **detail}

    # Unreachable due to validation above
    raise ValueError("At least one of scan_result_id or cluster_id is required")


TOOL_SPEC = ToolSpec(
    name="get_dependency_context",
    description=(
        "Deep-dive into dependency chains and clusters for a specific artifact or cluster. "
        "Use after seeing a concerning dependency_summary in get_result_detail or "
        "dependency_clusters in feature_detail. Returns full chain paths, circular "
        "dependencies, and cluster membership details."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
```

- [ ] **Step 2: Register the tool in registry.py**

In `tech-assessment-hub/src/mcp/registry.py`, add immediately after the `run_ai_stage_tool` registration (line 249):

```python
    # --- Dependency context deep-dive ---
    from .tools.core.dependency_context import TOOL_SPEC as dependency_context_tool
    registry.register(dependency_context_tool)
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_context.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App
git add tech-assessment-hub/src/mcp/tools/core/dependency_context.py tech-assessment-hub/src/mcp/registry.py
git commit -m "feat: add get_dependency_context MCP tool with registry registration"
```

---

### Task 3: Enrich `get_result_detail` with Dependency Summary

**Files:**
- Modify: `tech-assessment-hub/src/mcp/tools/core/result_detail.py`
- Extend: `tech-assessment-hub/tests/test_dependency_context.py` (add enrichment tests here to reuse fixtures)

- [ ] **Step 1: Write failing tests for the enrichment**

Append to `tech-assessment-hub/tests/test_dependency_context.py`:

```python
class TestResultDetailDependencySummary:
    def test_includes_dependency_summary_when_data_exists(self, db_session):
        data = _seed_dependency_data(db_session)
        from src.mcp.tools.core.result_detail import handle

        result = handle({"result_id": data["sr_a"].id}, db_session)
        summary = result.get("dependency_summary")
        assert summary is not None
        assert summary["inbound_count"] == 1  # C->A
        assert summary["outbound_count"] == 1  # A->B
        assert summary["direct_inbound"] == 1
        assert summary["direct_outbound"] == 1
        assert summary["cluster_id"] == data["cluster"].id
        assert summary["cluster_coupling_score"] == 0.85
        assert summary["has_circular_dependencies"] is True

    def test_dependency_summary_null_when_no_data(self, db_session):
        data = _seed_dependency_data(db_session)
        orphan = ScanResult(
            scan_id=data["scan"].id, sys_id="yyy", table_name="sys_choice",
            name="Orphan2", origin_type=OriginType.modified_ootb,
        )
        db_session.add(orphan)
        db_session.flush()

        from src.mcp.tools.core.result_detail import handle

        result = handle({"result_id": orphan.id}, db_session)
        assert result.get("dependency_summary") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_context.py::TestResultDetailDependencySummary -v`

Expected: FAIL — `dependency_summary` key not present.

- [ ] **Step 3: Implement the enrichment**

In `tech-assessment-hub/src/mcp/tools/core/result_detail.py`:

Add imports at the top (after the existing imports):

```python
from ....models import (
    ScanResult, Scan, Assessment, VersionHistory, CustomerUpdateXML, UpdateSet,
    DependencyChain, DependencyCluster,
)
```

Add a helper function before `handle()`:

```python
def _dependency_summary(session: Session, result_id: int, assessment_id: int):
    """Build lightweight dependency summary for a scan result, or None if no data."""
    from sqlalchemy import func as sa_func

    outbound_q = select(sa_func.count(), sa_func.count().filter(DependencyChain.hop_count == 1)).where(
        DependencyChain.assessment_id == assessment_id,
        DependencyChain.source_scan_result_id == result_id,
    )
    outbound_total, direct_outbound = session.exec(outbound_q).one()

    inbound_q = select(sa_func.count(), sa_func.count().filter(DependencyChain.hop_count == 1)).where(
        DependencyChain.assessment_id == assessment_id,
        DependencyChain.target_scan_result_id == result_id,
    )
    inbound_total, direct_inbound = session.exec(inbound_q).one()

    # Find cluster membership
    clusters = session.exec(
        select(DependencyCluster).where(DependencyCluster.assessment_id == assessment_id)
    ).all()
    matching_cluster = None
    for cluster in clusters:
        member_ids = json.loads(cluster.member_ids_json) if cluster.member_ids_json else []
        if result_id in member_ids:
            matching_cluster = cluster
            break

    if outbound_total == 0 and inbound_total == 0 and matching_cluster is None:
        return None

    summary = {
        "inbound_count": inbound_total,
        "outbound_count": outbound_total,
        "direct_inbound": direct_inbound,
        "direct_outbound": direct_outbound,
        "cluster_id": None,
        "cluster_label": None,
        "cluster_coupling_score": None,
        "cluster_impact_radius": None,
        "cluster_change_risk_level": None,
        "has_circular_dependencies": False,
    }
    if matching_cluster:
        circ_deps = json.loads(matching_cluster.circular_dependencies_json) if matching_cluster.circular_dependencies_json else []
        summary.update({
            "cluster_id": matching_cluster.id,
            "cluster_label": matching_cluster.cluster_label,
            "cluster_coupling_score": matching_cluster.coupling_score,
            "cluster_impact_radius": matching_cluster.impact_radius,
            "cluster_change_risk_level": matching_cluster.change_risk_level,
            "has_circular_dependencies": len(circ_deps) > 0,
        })
    return summary
```

In the `handle()` function, after the version history block and before the return statement (around line 118), add:

```python
    # Dependency summary
    dep_summary = _dependency_summary(session, int(result.id), assessment.id if assessment else -1)
```

Then add `"dependency_summary": dep_summary` to the return dict (alongside the existing keys):

```python
    return {
        "success": True,
        "result": result_dict,
        "update_set": update_set_info,
        "customer_update_xml": update_xml_info,
        "version_history": version_history,
        "dependency_summary": dep_summary,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_context.py::TestResultDetailDependencySummary -v`

Expected: Both tests PASS.

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`

Expected: All tests pass (no regressions from adding a new key to the response).

- [ ] **Step 6: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App
git add tech-assessment-hub/src/mcp/tools/core/result_detail.py tech-assessment-hub/tests/test_dependency_context.py
git commit -m "feat: enrich get_result_detail with dependency_summary"
```

---

### Task 4: Enrich `feature_detail` with Cluster Context

**Files:**
- Modify: `tech-assessment-hub/src/mcp/tools/core/feature_detail.py`
- Extend: `tech-assessment-hub/tests/test_dependency_context.py`

- [ ] **Step 1: Write failing tests**

Append to `tech-assessment-hub/tests/test_dependency_context.py`. This requires adding Feature + FeatureScanResult fixtures, so add these imports at the top of the file:

```python
from src.models import (
    # ... existing imports plus:
    Feature,
    FeatureScanResult,
)
```

Then add a helper and test class:

```python
def _seed_feature_with_dependencies(session: Session):
    """Extend dependency data with a feature linked to the clustered artifacts."""
    data = _seed_dependency_data(session)
    feature = Feature(
        assessment_id=data["assessment"].id,
        name="Incident Approval Feature",
        description="Custom approval workflow",
        change_risk_score=72.5,
        change_risk_level="high",
    )
    session.add(feature)
    session.flush()

    for sr in [data["sr_a"], data["sr_b"], data["sr_c"]]:
        link = FeatureScanResult(
            feature_id=feature.id,
            scan_result_id=sr.id,
            is_primary=(sr == data["sr_a"]),
        )
        session.add(link)
    session.flush()

    data["feature"] = feature
    return data


class TestFeatureDetailDependencyEnrichment:
    def test_includes_dependency_risk_and_clusters(self, db_session):
        data = _seed_feature_with_dependencies(db_session)
        from src.mcp.tools.core.feature_detail import handle

        result = handle({"feature_id": data["feature"].id}, db_session)

        risk = result.get("dependency_risk")
        assert risk is not None
        assert risk["change_risk_score"] == 72.5
        assert risk["change_risk_level"] == "high"

        clusters = result.get("dependency_clusters")
        assert clusters is not None
        assert len(clusters) == 1
        assert clusters[0]["cluster_id"] == data["cluster"].id
        assert clusters[0]["coupling_score"] == 0.85
        assert clusters[0]["circular_dependency_count"] == 1
        # All 3 members overlap with the feature
        assert len(clusters[0]["overlap_member_ids"]) == 3

    def test_no_risk_data_returns_null(self, db_session):
        data = _seed_dependency_data(db_session)
        feature = Feature(
            assessment_id=data["assessment"].id,
            name="Empty Feature",
        )
        db_session.add(feature)
        db_session.flush()

        from src.mcp.tools.core.feature_detail import handle

        result = handle({"feature_id": feature.id}, db_session)
        assert result.get("dependency_risk") is None
        assert result.get("dependency_clusters") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_context.py::TestFeatureDetailDependencyEnrichment -v`

Expected: FAIL — `dependency_risk` key not present.

- [ ] **Step 3: Implement the enrichment**

In `tech-assessment-hub/src/mcp/tools/core/feature_detail.py`:

Add imports:

```python
import json
from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Feature, FeatureRecommendation, FeatureScanResult, ScanResult, DependencyCluster
```

Add a helper before `handle()`:

```python
def _dependency_enrichment(session: Session, feature: Feature, member_result_ids: list):
    """Build dependency_risk and dependency_clusters for a feature."""
    risk = None
    if feature.change_risk_score is not None or feature.change_risk_level is not None:
        risk = {
            "change_risk_score": feature.change_risk_score,
            "change_risk_level": feature.change_risk_level,
        }

    clusters_out = []
    if member_result_ids:
        member_set = set(member_result_ids)
        all_clusters = session.exec(
            select(DependencyCluster).where(
                DependencyCluster.assessment_id == feature.assessment_id
            )
        ).all()
        for cluster in all_clusters:
            cluster_member_ids = json.loads(cluster.member_ids_json) if cluster.member_ids_json else []
            overlap = [mid for mid in cluster_member_ids if mid in member_set]
            if overlap:
                circ_deps = json.loads(cluster.circular_dependencies_json) if cluster.circular_dependencies_json else []
                clusters_out.append({
                    "cluster_id": cluster.id,
                    "cluster_label": cluster.cluster_label,
                    "member_count": cluster.member_count,
                    "coupling_score": cluster.coupling_score,
                    "impact_radius": cluster.impact_radius,
                    "change_risk_score": cluster.change_risk_score,
                    "change_risk_level": cluster.change_risk_level,
                    "circular_dependency_count": len(circ_deps),
                    "tables_involved": json.loads(cluster.tables_involved_json) if cluster.tables_involved_json else [],
                    "overlap_member_ids": overlap,
                })

    return risk, clusters_out
```

In `handle()`, after the scan_results loop, add:

```python
    member_result_ids = [sr.id for link in links if (sr := session.get(ScanResult, link.scan_result_id))]
    dep_risk, dep_clusters = _dependency_enrichment(session, feature, member_result_ids)
```

Then add to the return dict:

```python
        "dependency_risk": dep_risk,
        "dependency_clusters": dep_clusters,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_dependency_context.py::TestFeatureDetailDependencyEnrichment -v`

Expected: Both tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App
git add tech-assessment-hub/src/mcp/tools/core/feature_detail.py tech-assessment-hub/tests/test_dependency_context.py
git commit -m "feat: enrich feature_detail with dependency_risk and dependency_clusters"
```

---

### Task 5: Enrich `generate_observations` with Dependency Context

**Files:**
- Modify: `tech-assessment-hub/src/mcp/tools/pipeline/generate_observations.py`
- Extend: `tech-assessment-hub/tests/test_generate_observations.py`

- [ ] **Step 1: Write failing tests**

Append to `tech-assessment-hub/tests/test_generate_observations.py`. First add the necessary imports at the top of the file:

```python
from src.models import (
    # ... existing imports plus:
    DependencyChain,
    DependencyCluster,
)
```

Then add the test class:

```python
class TestDependencyObservations:
    def test_observation_includes_dependency_context(self, db_session):
        """When chains and clusters exist, observations should include dependency section."""
        inst, asmt, scan, customized_a, customized_b = _seed_observation_assessment(db_session)[:5]
        # Re-fetch to get IDs
        inst_obj = db_session.exec(select(Instance).where(Instance.name == "obs-inst")).first()
        asmt_obj = db_session.exec(select(Assessment).where(Assessment.number == "ASMT0099500")).first()
        scan_obj = db_session.exec(select(Scan).where(Scan.assessment_id == asmt_obj.id)).first()
        results = db_session.exec(
            select(ScanResult).where(ScanResult.scan_id == scan_obj.id)
        ).all()
        customized = [r for r in results if r.origin_type in (OriginType.modified_ootb, OriginType.net_new_customer)]
        sr_a, sr_b = customized[0], customized[1]

        # Create dependency chain A -> B
        chain = DependencyChain(
            scan_id=scan_obj.id, instance_id=inst_obj.id, assessment_id=asmt_obj.id,
            source_scan_result_id=sr_a.id, target_scan_result_id=sr_b.id,
            dependency_type="code_reference", direction="outbound",
            hop_count=1, chain_path_json=json.dumps([sr_a.id, sr_b.id]),
            chain_weight=3.0, criticality="high",
        )
        # Create cluster containing both
        cluster = DependencyCluster(
            scan_id=scan_obj.id, instance_id=inst_obj.id, assessment_id=asmt_obj.id,
            cluster_label="test cluster (2 artifacts)",
            member_ids_json=json.dumps([sr_a.id, sr_b.id]),
            member_count=2, internal_edge_count=1,
            coupling_score=0.75, impact_radius="high",
            change_risk_score=55.0, change_risk_level="medium",
            circular_dependencies_json=json.dumps([]),
            tables_involved_json=json.dumps(["sys_script", "sys_script_include"]),
        )
        db_session.add_all([chain, cluster])
        db_session.commit()

        from src.mcp.tools.pipeline.generate_observations import handle
        result = handle({"assessment_id": asmt_obj.id, "include_usage_queries": "never"}, db_session)
        assert result["success"] is True

        # Check that sr_a's observations contain dependency context
        sr_a_refreshed = db_session.get(ScanResult, sr_a.id)
        assert "Dependency Context" in sr_a_refreshed.observations
        assert "Outbound dependencies: 1" in sr_a_refreshed.observations

        # Check structured ai_observations
        ai_obs = json.loads(sr_a_refreshed.ai_observations)
        dep_ctx = ai_obs.get("dependency_context")
        assert dep_ctx is not None
        assert dep_ctx["outbound_total"] == 1
        assert dep_ctx["cluster_id"] == cluster.id

    def test_observation_omits_dependency_when_none(self, db_session):
        """When no dependency data exists, observations should not include dependency section."""
        _seed_observation_assessment(db_session)
        asmt = db_session.exec(select(Assessment).where(Assessment.number == "ASMT0099500")).first()

        from src.mcp.tools.pipeline.generate_observations import handle
        result = handle({"assessment_id": asmt.id, "include_usage_queries": "never"}, db_session)
        assert result["success"] is True

        results = db_session.exec(select(ScanResult)).all()
        for sr in results:
            if sr.observations:
                assert "Dependency Context" not in sr.observations
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_generate_observations.py::TestDependencyObservations -v`

Expected: FAIL — "Dependency Context" not in observations.

- [ ] **Step 3: Implement the enrichment**

In `tech-assessment-hub/src/mcp/tools/pipeline/generate_observations.py`:

Add to the imports:

```python
from ....models import (
    # ... existing imports plus:
    DependencyChain,
    DependencyCluster,
)
```

Add a helper function after `_structural_signal_count()`:

```python
def _dependency_context(
    session: Session,
    *,
    assessment_id: int,
    result_id: int,
) -> Optional[Dict[str, Any]]:
    """Build dependency context for a single artifact, or None if no data."""
    from sqlalchemy import func as sa_func

    outbound_q = select(sa_func.count(), sa_func.count().filter(DependencyChain.hop_count == 1)).where(
        DependencyChain.assessment_id == assessment_id,
        DependencyChain.source_scan_result_id == result_id,
    )
    outbound_total, direct_outbound = session.exec(outbound_q).one()

    inbound_q = select(sa_func.count(), sa_func.count().filter(DependencyChain.hop_count == 1)).where(
        DependencyChain.assessment_id == assessment_id,
        DependencyChain.target_scan_result_id == result_id,
    )
    inbound_total, direct_inbound = session.exec(inbound_q).one()

    # Find cluster membership
    clusters = session.exec(
        select(DependencyCluster).where(DependencyCluster.assessment_id == assessment_id)
    ).all()
    matching_cluster = None
    for cluster in clusters:
        member_ids = json.loads(cluster.member_ids_json) if cluster.member_ids_json else []
        if result_id in member_ids:
            matching_cluster = cluster
            break

    if outbound_total == 0 and inbound_total == 0 and matching_cluster is None:
        return None

    ctx: Dict[str, Any] = {
        "inbound_total": inbound_total,
        "inbound_direct": direct_inbound,
        "outbound_total": outbound_total,
        "outbound_direct": direct_outbound,
        "cluster_id": None,
        "cluster_label": None,
        "coupling_score": None,
        "impact_radius": None,
        "change_risk_level": None,
        "circular_dependency_count": 0,
    }
    if matching_cluster:
        circ = json.loads(matching_cluster.circular_dependencies_json) if matching_cluster.circular_dependencies_json else []
        ctx.update({
            "cluster_id": matching_cluster.id,
            "cluster_label": matching_cluster.cluster_label,
            "coupling_score": matching_cluster.coupling_score,
            "impact_radius": matching_cluster.impact_radius,
            "change_risk_level": matching_cluster.change_risk_level,
            "circular_dependency_count": len(circ),
        })
    return ctx
```

Add a text formatter:

```python
def _format_dependency_observation(dep_ctx: Dict[str, Any]) -> str:
    """Format dependency context as a human-readable observation block."""
    transitive_in = dep_ctx["inbound_total"] - dep_ctx["inbound_direct"]
    transitive_out = dep_ctx["outbound_total"] - dep_ctx["outbound_direct"]
    lines = ["--- Dependency Context ---"]
    lines.append(
        f"Inbound dependencies: {dep_ctx['inbound_total']} "
        f"({dep_ctx['inbound_direct']} direct, {transitive_in} transitive)"
    )
    lines.append(
        f"Outbound dependencies: {dep_ctx['outbound_total']} "
        f"({dep_ctx['outbound_direct']} direct, {transitive_out} transitive)"
    )
    if dep_ctx.get("cluster_label"):
        lines.append(
            f"Cluster membership: \"{dep_ctx['cluster_label']}\" "
            f"(coupling: {dep_ctx['coupling_score']}, impact_radius: {dep_ctx['impact_radius']})"
        )
    if dep_ctx.get("change_risk_level"):
        lines.append(f"Change risk level: {dep_ctx['change_risk_level']}")
    if dep_ctx.get("circular_dependency_count", 0) > 0:
        lines.append(f"Circular dependencies: {dep_ctx['circular_dependency_count']} detected")
    return "\n".join(lines)
```

In the `handle()` function, inside the per-result processing loop (after `structural_count = ...` around line 345), add:

```python
            dep_ctx = _dependency_context(
                session,
                assessment_id=assessment_id,
                result_id=int(result.id),
            )
```

Update the `_format_observation` call to include dependency text. After the existing observation text assignment (`if not (result.observations or "").strip():`), append dependency text:

```python
            if dep_ctx:
                observation_text = observation_text + "\n\n" + _format_dependency_observation(dep_ctx)
```

In the `ai_observations` section, after `existing_ai_observations["deterministic_observation_baseline"] = {...}`, add:

```python
            if dep_ctx:
                existing_ai_observations["dependency_context"] = dep_ctx
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_generate_observations.py::TestDependencyObservations -v`

Expected: Both tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App
git add tech-assessment-hub/src/mcp/tools/pipeline/generate_observations.py tech-assessment-hub/tests/test_generate_observations.py
git commit -m "feat: enrich deterministic observations with dependency context"
```

---

### Task 6: Update Stage Tool Sets and AI Prompts

**Files:**
- Modify: `tech-assessment-hub/src/services/ai_stage_tool_sets.py:13-28`
- Modify: `tech-assessment-hub/src/services/ai_analysis_dispatch.py:31-67`
- Modify: `tech-assessment-hub/src/mcp/prompts/relationship_tracer.py:76-85`
- Modify: `tech-assessment-hub/src/mcp/prompts/technical_architect.py:65-74`

- [ ] **Step 1: Update stage tool sets**

In `tech-assessment-hub/src/services/ai_stage_tool_sets.py`, replace the `ai_analysis` and `ai_refinement` entries:

Replace:
```python
    "ai_analysis": [
        f"{_PREFIX}get_customizations",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}update_scan_result",
    ],
```

With:
```python
    "ai_analysis": [
        f"{_PREFIX}get_customizations",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}update_scan_result",
        f"{_PREFIX}get_dependency_context",
    ],
```

Replace:
```python
    "ai_refinement": [
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}feature_grouping_status",
    ],
```

With:
```python
    "ai_refinement": [
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}feature_grouping_status",
        f"{_PREFIX}get_dependency_context",
        f"{_PREFIX}search",
    ],
```

- [ ] **Step 2: Update AI analysis fallback guidance**

In `tech-assessment-hub/src/services/ai_analysis_dispatch.py`, append to `_AI_ANALYSIS_FALLBACK_GUIDANCE` (before the closing `"""`):

```
Dependency Awareness:
- When you read an artifact with `get_result_detail`, check the `dependency_summary`.
- If the artifact has high coupling, circular dependencies, or is in a cluster with
  impact_radius "high" or "very_high", note this in your observations.
- If you need full chain details, use `get_dependency_context` with the scan_result_id.
- Factor dependency data into scope decisions: artifacts with many inbound dependencies
  are harder to safely revert -- they are load-bearing customizations.
- Include dependency awareness in `ai_observations.directly_related_result_ids` --
  dependency chains ARE direct relationships.
```

- [ ] **Step 3: Update relationship_tracer prompt**

In `tech-assessment-hub/src/mcp/prompts/relationship_tracer.py`, in `RELATIONSHIP_TRACER_TEXT`, before the closing `## Rules` section (before line 76), insert:

```
## Dependency-Informed Analysis

The starting artifact may have computed dependency data available:
- ``get_result_detail`` returns a ``dependency_summary`` with chain counts,
  cluster membership, coupling score, and circular dependency flags.
- Use ``get_dependency_context`` with the ``scan_result_id`` for full chain
  paths and cluster membership details.
- Dependency chains ARE relationships — include them in your relationship map.
- If the artifact is in a high-coupling cluster (coupling > 0.7 or
  impact_radius "high"/"very_high"), flag the cluster as a tightly-coupled
  unit that should be assessed as a group, not piecemeal.
- Circular dependencies within a cluster mean the artifacts cannot be safely
  modified independently — note these explicitly in your output.
```

- [ ] **Step 4: Update technical_architect prompt (Mode A)**

In `tech-assessment-hub/src/mcp/prompts/technical_architect.py`, in `MODE_A_TEXT`, before the `## Rules` section (before line 65), insert:

```
## Dependency-Informed Disposition

When evaluating disposition, consider the artifact's dependency context:
- ``get_result_detail`` returns a ``dependency_summary`` — check it for cluster
  membership, coupling, and circular dependency flags.
- Artifacts with many inbound dependencies are load-bearing — suggesting
  "Replace with OOTB" or "Evaluate for Retirement" requires understanding the
  blast radius. Note the number of dependent artifacts in your rationale.
- For tightly-coupled clusters: consider whether ServiceNow provides an OOTB
  solution that replaces the whole cluster, not just this artifact. Use the
  ``search`` tool to check the local knowledge base, and use web search to look
  up OOTB alternatives (e.g., "ServiceNow OOTB [table] [what the cluster does]").
- For clusters with circular dependencies: flag as high-risk refactoring
  candidates — these cannot be safely modified piecemeal.
- When suggesting "Refactor": identify which artifacts are the coupling hubs
  (most inbound chains) and recommend refactoring those first.
```

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`

Expected: All pass. The tool set and prompt changes only affect runtime dispatch, not unit tests.

- [ ] **Step 6: Commit**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App
git add tech-assessment-hub/src/services/ai_stage_tool_sets.py tech-assessment-hub/src/services/ai_analysis_dispatch.py tech-assessment-hub/src/mcp/prompts/relationship_tracer.py tech-assessment-hub/src/mcp/prompts/technical_architect.py
git commit -m "feat: add dependency tools to AI stage sets and update all AI prompts with dependency awareness"
```

---

### Task 7: Final Integration Verification

**Files:**
- No new files — this is a verification pass.

- [ ] **Step 1: Run the complete test suite**

Run: `cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`

Expected: All tests pass. Note the total count — should be baseline (496) plus new tests from `test_dependency_context.py` (~8-10 new tests).

- [ ] **Step 2: Verify tool registration**

Run a quick smoke test to ensure the new tool is discoverable:

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -c "
from src.mcp.registry import build_registry
reg = build_registry()
assert reg.has_tool('get_dependency_context'), 'Tool not registered!'
print('get_dependency_context registered OK')
tools = [t['name'] for t in reg.list_tools()]
print(f'Total tools: {len(tools)}')
"
```

Expected: `get_dependency_context registered OK` and the total tool count.

- [ ] **Step 3: Verify stage tool sets**

```bash
cd /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App && ./tech-assessment-hub/venv/bin/python -c "
from src.services.ai_stage_tool_sets import STAGE_TOOL_SETS
ai_tools = STAGE_TOOL_SETS['ai_analysis']
ref_tools = STAGE_TOOL_SETS['ai_refinement']
assert any('get_dependency_context' in t for t in ai_tools), 'Missing from ai_analysis'
assert any('get_dependency_context' in t for t in ref_tools), 'Missing from ai_refinement'
assert any('search' in t for t in ref_tools), 'Missing search from ai_refinement'
print('Stage tool sets verified OK')
print(f'  ai_analysis: {ai_tools}')
print(f'  ai_refinement: {ref_tools}')
"
```

Expected: All assertions pass, both stage sets printed with the new tools.

- [ ] **Step 4: Commit verification marker (optional)**

No code changes in this task — just verification. If all passes, the implementation is complete.
