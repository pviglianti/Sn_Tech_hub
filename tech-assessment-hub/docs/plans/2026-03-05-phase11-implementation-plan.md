# Phase 11 — AI-Driven Feature Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the pipeline so engines produce read-only relationship signals and AI creates all features via iterative depth-first analysis using MCP tools and prompts.

**Architecture:** Engine outputs become discovery context for AI reasoning. Three new MCP authoring tools (`create_feature`, `add_result_to_feature`, `remove_result_from_feature`) give AI explicit feature creation capability. `seed_feature_groups` becomes read-only `get_suggested_groupings`. Pipeline mode (`local_subscription` vs `api`) determines behavior — no `analysis_mode` toggle.

**Tech Stack:** Python 3, SQLModel, pytest, Jinja2 templates, CSS

---

## Pre-Requisites

- Branch: `3_5_2026_TA_PostP6andMCPskills`
- All 585+ tests passing
- Design doc committed: `docs/plans/2026-03-05-phase11-ai-driven-feature-architecture-design.md`

---

## Task 1: Remove `analysis_mode` from Assessment Model

The `analysis_mode` field on Assessment is premature — pipeline mode determines behavior, not a property toggle.

**Files:**
- Modify: `src/models.py:283` (remove `analysis_mode` field)
- Modify: `src/server.py:1602-1603` (remove `effective_mode` reads)
- Modify: `src/server.py:1898-1902` (remove grouping mode check)
- Modify: `src/server.py:8361-8378` (remove snapshot at assessment creation)
- Modify: `src/services/integration_properties.py:75-80,118-121,244-251` (remove `analysis_mode` property + select options)
- Test: Run full regression

**Step 1: Remove field from Assessment model**

In `src/models.py:283`, delete:
```python
analysis_mode: str = "sequential"  # "sequential" or "depth_first"
```

**Step 2: Remove property definitions**

In `src/services/integration_properties.py`:
- Delete `AI_ANALYSIS_MODE` constant (line 77)
- Delete `AI_ANALYSIS_MODE_OPTIONS` (lines 118-121)
- Remove `analysis_mode` from `AIAnalysisProperties` dataclass (line 249)
- Remove the matching entry from `PROPERTY_DEFINITIONS` list
- Remove from `load_ai_analysis_properties()` if it reads `analysis_mode`

**Step 3: Remove all `analysis_mode` / `effective_mode` reads from server.py**

In `src/server.py`:
- Lines 1602-1603: Remove `effective_mode = getattr(assessment, "analysis_mode", None) or ai_props.analysis_mode`
- Lines 1898-1902: Remove `effective_grouping_mode` logic — grouping always runs with its default behavior for now
- Lines 8361-8363: Remove the `ai_props.analysis_mode` snapshot
- Line 8378: Remove `analysis_mode=initial_analysis_mode` from Assessment constructor

**Step 4: Run full regression**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`
Expected: All tests pass (some tests may need `analysis_mode` references removed)

**Step 5: Commit**

```bash
git add src/models.py src/server.py src/services/integration_properties.py tests/
git commit -m "refactor: remove analysis_mode from Assessment model

Pipeline mode (local_subscription vs api) determines AI behavior,
not a per-assessment property toggle. DFS is how AI always works."
```

---

## Task 2: Create `create_feature` MCP Tool

AI needs to create features explicitly. Currently only `seed_feature_groups` creates them.

**Files:**
- Create: `src/mcp/tools/core/create_feature.py`
- Modify: `src/mcp/registry.py:208-221` (register new tool)
- Create: `tests/test_create_feature_tool.py`

**Step 1: Write failing tests**

Create `tests/test_create_feature_tool.py`:
```python
"""Tests for MCP create_feature tool."""
import pytest
from sqlmodel import Session

from src.mcp.tools.core.create_feature import handle
from src.models import Assessment, Feature, Instance, Scan


@pytest.fixture
def assessment_with_scan(session: Session) -> Assessment:
    inst = Instance(name="test", url="https://test.service-now.com")
    session.add(inst)
    session.flush()
    a = Assessment(name="Test", instance_id=inst.id, assessment_type="global")
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_create_feature_basic(session: Session, assessment_with_scan):
    result = handle(
        {"assessment_id": assessment_with_scan.id, "name": "Approval Workflow"},
        session,
    )
    assert result["success"] is True
    assert result["feature_id"] > 0
    assert result["name"] == "Approval Workflow"

    feature = session.get(Feature, result["feature_id"])
    assert feature is not None
    assert feature.name == "Approval Workflow"
    assert feature.assessment_id == assessment_with_scan.id


def test_create_feature_with_description(session: Session, assessment_with_scan):
    result = handle(
        {
            "assessment_id": assessment_with_scan.id,
            "name": "Incident Management",
            "description": "Custom incident workflow modifications",
        },
        session,
    )
    assert result["success"] is True
    feature = session.get(Feature, result["feature_id"])
    assert feature.description == "Custom incident workflow modifications"


def test_create_feature_gets_color_index(session: Session, assessment_with_scan):
    result = handle(
        {"assessment_id": assessment_with_scan.id, "name": "Test Feature"},
        session,
    )
    feature = session.get(Feature, result["feature_id"])
    assert feature.color_index is not None
    assert 0 <= feature.color_index < 20


def test_create_feature_invalid_assessment(session: Session):
    with pytest.raises(ValueError, match="Assessment not found"):
        handle({"assessment_id": 99999, "name": "Bad"}, session)
```

**Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_create_feature_tool.py -v`
Expected: FAIL — module not found

**Step 3: Implement create_feature tool**

Create `src/mcp/tools/core/create_feature.py`:
```python
"""MCP tool: create_feature — AI creates a new feature group.

Allows the AI to create a Feature record for grouping related
customized scan results during iterative analysis.
"""

from datetime import datetime
from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Assessment, Feature

FEATURE_COLOR_COUNT = 20

INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "ID of the assessment this feature belongs to.",
        },
        "name": {
            "type": "string",
            "description": "Feature name (can be refined later via update_feature).",
        },
        "description": {
            "type": "string",
            "description": "Optional feature description.",
        },
    },
    "required": ["assessment_id", "name"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    feature = Feature(
        assessment_id=assessment_id,
        name=params["name"],
        description=params.get("description"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(feature)
    session.flush()  # Get ID for color_index

    feature.color_index = feature.id % FEATURE_COLOR_COUNT
    session.add(feature)
    session.commit()
    session.refresh(feature)

    return {
        "success": True,
        "feature_id": feature.id,
        "name": feature.name,
        "color_index": feature.color_index,
        "message": f"Created feature '{feature.name}' (id={feature.id}).",
    }


TOOL_SPEC = ToolSpec(
    name="create_feature",
    description=(
        "Create a new feature group for an assessment. Use this to start grouping "
        "related customized scan results. Feature name and description can be "
        "refined later via update_feature as more context is discovered."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

**Step 4: Register in registry.py**

In `src/mcp/registry.py`, after the `update_feature` import (line 210), add:
```python
from .tools.core.create_feature import TOOL_SPEC as create_feature_tool
```
And after `registry.register(update_feature_tool)` (line 217):
```python
registry.register(create_feature_tool)
```

**Step 5: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_create_feature_tool.py -v`
Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add src/mcp/tools/core/create_feature.py src/mcp/registry.py tests/test_create_feature_tool.py
git commit -m "feat: add create_feature MCP tool for AI feature authoring"
```

---

## Task 3: Create `add_result_to_feature` and `remove_result_from_feature` MCP Tools

AI needs to manage feature membership — add/remove customized results to/from features.

**Files:**
- Create: `src/mcp/tools/core/feature_membership.py`
- Modify: `src/mcp/registry.py` (register both tools)
- Create: `tests/test_feature_membership_tools.py`

**Step 1: Write failing tests**

Create `tests/test_feature_membership_tools.py`:
```python
"""Tests for MCP feature membership tools (add/remove result to/from feature)."""
import pytest
from sqlmodel import Session, select

from src.mcp.tools.core.feature_membership import handle_add, handle_remove
from src.models import (
    Assessment, Feature, FeatureScanResult, Instance, OriginType, Scan, ScanResult,
)


@pytest.fixture
def setup_data(session: Session):
    inst = Instance(name="test", url="https://test.service-now.com")
    session.add(inst)
    session.flush()
    a = Assessment(name="Test", instance_id=inst.id, assessment_type="global")
    session.add(a)
    session.flush()
    scan = Scan(assessment_id=a.id, instance_id=inst.id, scan_type="full")
    session.add(scan)
    session.flush()

    # Customized result
    sr_custom = ScanResult(
        scan_id=scan.id, instance_id=inst.id,
        name="ApprovalBR", origin_type=OriginType.modified_ootb,
    )
    # Non-customized result
    sr_ootb = ScanResult(
        scan_id=scan.id, instance_id=inst.id,
        name="OOB_Script", origin_type=OriginType.ootb_untouched,
    )
    session.add_all([sr_custom, sr_ootb])
    session.flush()

    feature = Feature(assessment_id=a.id, name="Approval Workflow")
    session.add(feature)
    session.commit()
    session.refresh(feature)
    session.refresh(sr_custom)
    session.refresh(sr_ootb)
    return {"feature": feature, "sr_custom": sr_custom, "sr_ootb": sr_ootb}


def test_add_customized_result(session: Session, setup_data):
    result = handle_add(
        {
            "feature_id": setup_data["feature"].id,
            "scan_result_id": setup_data["sr_custom"].id,
        },
        session,
    )
    assert result["success"] is True
    link = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == setup_data["feature"].id,
            FeatureScanResult.scan_result_id == setup_data["sr_custom"].id,
        )
    ).first()
    assert link is not None
    assert link.assignment_source == "ai"


def test_reject_non_customized_result(session: Session, setup_data):
    with pytest.raises(ValueError, match="not a customized"):
        handle_add(
            {
                "feature_id": setup_data["feature"].id,
                "scan_result_id": setup_data["sr_ootb"].id,
            },
            session,
        )


def test_add_idempotent(session: Session, setup_data):
    """Adding same result twice should not create duplicate."""
    handle_add(
        {"feature_id": setup_data["feature"].id, "scan_result_id": setup_data["sr_custom"].id},
        session,
    )
    result = handle_add(
        {"feature_id": setup_data["feature"].id, "scan_result_id": setup_data["sr_custom"].id},
        session,
    )
    assert result["success"] is True
    assert "already" in result["message"].lower()

    links = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == setup_data["feature"].id,
            FeatureScanResult.scan_result_id == setup_data["sr_custom"].id,
        )
    ).all()
    assert len(links) == 1


def test_remove_result(session: Session, setup_data):
    handle_add(
        {"feature_id": setup_data["feature"].id, "scan_result_id": setup_data["sr_custom"].id},
        session,
    )
    result = handle_remove(
        {"feature_id": setup_data["feature"].id, "scan_result_id": setup_data["sr_custom"].id},
        session,
    )
    assert result["success"] is True
    link = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == setup_data["feature"].id,
            FeatureScanResult.scan_result_id == setup_data["sr_custom"].id,
        )
    ).first()
    assert link is None


def test_remove_nonexistent(session: Session, setup_data):
    result = handle_remove(
        {"feature_id": setup_data["feature"].id, "scan_result_id": setup_data["sr_custom"].id},
        session,
    )
    assert result["success"] is True
    assert "not found" in result["message"].lower() or "no membership" in result["message"].lower()
```

**Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_feature_membership_tools.py -v`
Expected: FAIL — module not found

**Step 3: Implement feature_membership tools**

Create `src/mcp/tools/core/feature_membership.py`:
```python
"""MCP tools: add_result_to_feature / remove_result_from_feature.

AI manages feature membership — only customized scan results can be members.
"""

from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    Feature, FeatureScanResult, OriginType, ScanResult,
)

_CUSTOMIZED_ORIGINS = {OriginType.modified_ootb.value, OriginType.net_new_customer.value}

# ---- Add ----

ADD_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {"type": "integer", "description": "Feature to add result to."},
        "scan_result_id": {"type": "integer", "description": "Customized scan result to add."},
    },
    "required": ["feature_id", "scan_result_id"],
}


def handle_add(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    scan_result_id = int(params["scan_result_id"])

    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    sr = session.get(ScanResult, scan_result_id)
    if not sr:
        raise ValueError(f"ScanResult not found: {scan_result_id}")

    if sr.origin_type not in _CUSTOMIZED_ORIGINS:
        raise ValueError(
            f"ScanResult {scan_result_id} is not a customized record "
            f"(origin_type={sr.origin_type}). Only customized results can be feature members."
        )

    # Idempotent — check existing
    existing = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature_id,
            FeatureScanResult.scan_result_id == scan_result_id,
        )
    ).first()
    if existing:
        return {
            "success": True,
            "message": f"Result {scan_result_id} already in feature {feature_id}.",
            "feature_id": feature_id,
            "scan_result_id": scan_result_id,
        }

    link = FeatureScanResult(
        feature_id=feature_id,
        scan_result_id=scan_result_id,
        is_primary=True,
        membership_type="primary",
        assignment_source="ai",
        assignment_confidence=1.0,
    )
    session.add(link)
    session.commit()

    return {
        "success": True,
        "feature_id": feature_id,
        "scan_result_id": scan_result_id,
        "message": f"Added result {scan_result_id} to feature '{feature.name}'.",
    }


ADD_TOOL_SPEC = ToolSpec(
    name="add_result_to_feature",
    description=(
        "Add a customized scan result to a feature group. Only customized results "
        "(modified_ootb, net_new_customer) can be feature members. Idempotent — "
        "adding the same result twice is a no-op."
    ),
    input_schema=ADD_INPUT_SCHEMA,
    handler=handle_add,
    permission="write",
)


# ---- Remove ----

REMOVE_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {"type": "integer", "description": "Feature to remove result from."},
        "scan_result_id": {"type": "integer", "description": "Scan result to remove."},
    },
    "required": ["feature_id", "scan_result_id"],
}


def handle_remove(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    scan_result_id = int(params["scan_result_id"])

    link = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature_id,
            FeatureScanResult.scan_result_id == scan_result_id,
        )
    ).first()

    if not link:
        return {
            "success": True,
            "message": f"No membership found for result {scan_result_id} in feature {feature_id}.",
            "feature_id": feature_id,
            "scan_result_id": scan_result_id,
        }

    session.delete(link)
    session.commit()

    return {
        "success": True,
        "feature_id": feature_id,
        "scan_result_id": scan_result_id,
        "message": f"Removed result {scan_result_id} from feature {feature_id}.",
    }


REMOVE_TOOL_SPEC = ToolSpec(
    name="remove_result_from_feature",
    description=(
        "Remove a scan result from a feature group. If the membership doesn't exist, "
        "this is a no-op (idempotent)."
    ),
    input_schema=REMOVE_INPUT_SCHEMA,
    handler=handle_remove,
    permission="write",
)
```

**Step 4: Register both tools in registry.py**

In `src/mcp/registry.py`, after the create_feature import, add:
```python
from .tools.core.feature_membership import ADD_TOOL_SPEC as add_result_to_feature_tool
from .tools.core.feature_membership import REMOVE_TOOL_SPEC as remove_result_from_feature_tool
```
And register:
```python
registry.register(add_result_to_feature_tool)
registry.register(remove_result_from_feature_tool)
```

**Step 5: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_feature_membership_tools.py -v`
Expected: All 5 tests PASS

**Step 6: Commit**

```bash
git add src/mcp/tools/core/feature_membership.py src/mcp/registry.py tests/test_feature_membership_tools.py
git commit -m "feat: add add_result_to_feature and remove_result_from_feature MCP tools

AI can now explicitly manage feature membership. Only customized results
accepted. Idempotent add/remove operations."
```

---

## Task 4: Refactor `seed_feature_groups` to Read-Only `get_suggested_groupings`

The existing tool writes Feature/FeatureScanResult/FeatureContextArtifact records. Refactor it to return suggested groupings as JSON without writing anything.

**Files:**
- Modify: `src/mcp/tools/pipeline/seed_feature_groups.py` (refactor handle to return suggestions)
- Modify: `src/mcp/registry.py:195` (update import name if tool name changes)
- Modify: `src/server.py:1882-1920` (grouping stage handler)
- Modify: `tests/test_feature_grouping_pipeline_tools.py` (update expectations)
- Create: `tests/test_get_suggested_groupings.py`

**Step 1: Add a read-only mode to seed_feature_groups**

Rather than fully replacing the tool (which would break `api` mode fallback), add a `dry_run` parameter that returns suggestions without writing. The tool name stays `seed_feature_groups` for backward compatibility, but gains `dry_run=true` for AI use.

In `src/mcp/tools/pipeline/seed_feature_groups.py`:

Add to `INPUT_SCHEMA["properties"]`:
```python
"dry_run": {
    "type": "boolean",
    "description": "If true, return suggested groupings as JSON without creating any records.",
    "default": False,
},
```

In `seed_feature_groups()` function, after computing `components` and before creating Feature records (~line 670), add a branch:
```python
if dry_run:
    suggestions = []
    for idx, component in enumerate(components):
        suggestions.append({
            "suggested_feature_name": f"Cluster {idx + 1}",
            "member_result_ids": sorted(component),
            "member_count": len(component),
            "signal_summary": dict(signal_counts_for_component),
            "confidence_score": round(cluster_confidence, 3),
        })
    return {
        "success": True,
        "dry_run": True,
        "assessment_id": assessment_id,
        "suggested_groupings": suggestions,
        "total_suggestions": len(suggestions),
        "ungrouped_result_ids": sorted(set(eligible_customized_ids) - grouped_customized_ids),
    }
```

Also register a convenience alias tool `get_suggested_groupings` that calls the same handler with `dry_run=True` forced.

**Step 2: Write test for dry_run mode**

Create `tests/test_get_suggested_groupings.py`:
```python
"""Tests for seed_feature_groups dry_run (get_suggested_groupings) mode."""
import pytest
from sqlmodel import Session, select

from src.mcp.tools.pipeline.seed_feature_groups import handle
from src.models import Assessment, Feature, FeatureScanResult, Instance, Scan


def test_dry_run_returns_suggestions_without_writing(session: Session):
    """dry_run=True should return suggestions but create no Feature records."""
    # (Setup assessment with engine data — use existing fixture pattern)
    # ...
    result = handle({"assessment_id": assessment_id, "dry_run": True}, session)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert "suggested_groupings" in result

    # Verify NO Feature records created
    features = session.exec(select(Feature).where(Feature.assessment_id == assessment_id)).all()
    assert len(features) == 0
```

**Step 3: Update grouping stage in server.py**

In `src/server.py` grouping handler (~line 1882), the logic should be:
- Pipeline always calls `seed_feature_groups` in write mode as the deterministic fallback
- If features already exist (created by AI during ai_analysis), set `reset_existing=False`
- Remove all `analysis_mode` / `effective_grouping_mode` references

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_get_suggested_groupings.py tests/test_feature_grouping_pipeline_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/mcp/tools/pipeline/seed_feature_groups.py src/server.py src/mcp/registry.py tests/
git commit -m "feat: add dry_run mode to seed_feature_groups (get_suggested_groupings)

AI can now call seed_feature_groups with dry_run=True to get suggested
groupings without writing records. Alias tool get_suggested_groupings
registered for convenience."
```

---

## Task 5: Update Depth-First Analyzer to Use AI Authoring Tools

The existing `depth_first_analyzer.py` already has the DFS traversal algorithm (created by Codex). Update it to use the new AI authoring tools pattern and remove the `analysis_mode` dependency.

**Files:**
- Modify: `src/services/depth_first_analyzer.py` (remove analysis_mode refs, use create_feature pattern)
- Modify: `src/server.py:1596-1644` (simplify ai_analysis handler — remove mode branching)
- Modify: `tests/test_depth_first_analyzer.py` (update if needed)

**Step 1: Update server.py ai_analysis handler**

The handler currently branches on `effective_mode == "depth_first"`. Since AI always works depth-first when connected, the logic should be:
- The sequential handler remains the DEFAULT (for `api` mode pipelines)
- The DFS path is triggered by a new mechanism (e.g., the AI calls tools directly via MCP, or we detect MCP subscription mode)
- For now, keep both paths but remove the `analysis_mode` branching — use a simpler detection like checking if DFS is explicitly requested via pipeline params

Simplify to:
```python
if stage == PipelineStage.ai_analysis.value:
    ai_props = load_ai_analysis_properties(session, instance_id=assessment.instance_id)
    pipeline_prompt_props = load_pipeline_prompt_properties(session, instance_id=assessment.instance_id)
    instance_id = assessment.instance_id

    # Check if relationship graph has data (engines ran successfully)
    graph = build_relationship_graph(session, assessment_id)
    use_dfs = len(graph.customized_ids) > 0 and len(graph.adjacency) > 0

    if use_dfs:
        # ... existing DFS code, minus analysis_mode references ...
    else:
        # ... existing sequential code ...
```

**Step 2: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_depth_first_analyzer.py tests/test_phase7_pipeline_stages.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/server.py src/services/depth_first_analyzer.py tests/
git commit -m "refactor: simplify ai_analysis handler — auto-detect DFS from graph data

Remove analysis_mode branching. If engines produced relationship data,
use DFS traversal. Otherwise fall back to sequential."
```

---

## Task 6: Feature Color Coding CSS + Legend

Add the visual layer for feature-colored results.

**Files:**
- Modify: `src/web/static/css/style.css` (add 20 feature color classes + customization badge)
- Modify: `src/web/templates/assessment_detail.html` (feature color legend card)
- Create: `tests/test_feature_color_coding.py`

**Step 1: Add CSS classes**

In `src/web/static/css/style.css`, add:
```css
/* Feature color palette (20 colors) */
.feature-color-0 { border-left: 4px solid #4A90D9; }
.feature-color-1 { border-left: 4px solid #E67E22; }
.feature-color-2 { border-left: 4px solid #2ECC71; }
.feature-color-3 { border-left: 4px solid #E74C3C; }
.feature-color-4 { border-left: 4px solid #9B59B6; }
.feature-color-5 { border-left: 4px solid #1ABC9C; }
.feature-color-6 { border-left: 4px solid #F1C40F; }
.feature-color-7 { border-left: 4px solid #3498DB; }
.feature-color-8 { border-left: 4px solid #E91E63; }
.feature-color-9 { border-left: 4px solid #00BCD4; }
.feature-color-10 { border-left: 4px solid #FF9800; }
.feature-color-11 { border-left: 4px solid #8BC34A; }
.feature-color-12 { border-left: 4px solid #795548; }
.feature-color-13 { border-left: 4px solid #607D8B; }
.feature-color-14 { border-left: 4px solid #FF5722; }
.feature-color-15 { border-left: 4px solid #673AB7; }
.feature-color-16 { border-left: 4px solid #009688; }
.feature-color-17 { border-left: 4px solid #CDDC39; }
.feature-color-18 { border-left: 4px solid #F44336; }
.feature-color-19 { border-left: 4px solid #2196F3; }

.feature-color-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
}

/* Customization badge in related lists */
.badge-customization {
    background-color: #FF9800;
    color: #fff;
    font-size: 0.75rem;
    padding: 2px 6px;
    border-radius: 3px;
    margin-left: 4px;
}

.is-assessment-customization {
    font-weight: 600;
}
```

**Step 2: Add feature color legend to assessment_detail.html**

In the assessment detail template, add a collapsible card showing the feature color legend (only when features exist). This renders server-side using the feature list + `FEATURE_COLORS` constant.

**Step 3: Write verification test**

Create `tests/test_feature_color_coding.py`:
```python
"""Tests for feature color assignment."""
from src.models import Feature


def test_color_index_deterministic():
    """color_index = id % 20"""
    for fid in [1, 20, 21, 40, 100]:
        f = Feature(id=fid, assessment_id=1, name="test")
        f.color_index = fid % 20
        assert 0 <= f.color_index < 20
        assert f.color_index == fid % 20
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tests/test_feature_color_coding.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/web/static/css/style.css src/web/templates/assessment_detail.html tests/test_feature_color_coding.py
git commit -m "feat: add feature color coding CSS + legend card

20-color palette for features. Color-coded left borders on results.
Customization badge class for related lists. Feature legend on
assessment detail page."
```

---

## Task 7: Customization Badges in Result Detail Related Lists

When viewing a result's code references, structural relationships, update set contents — highlight items that are also customizations in this assessment.

**Files:**
- Modify: `src/server.py` or relevant API routes (add `is_assessment_customization` flag to related-item payloads)
- Modify: `src/web/templates/result_detail.html` (render badges + clickable links)

**Step 1: Enrich API payloads**

In the API endpoints that return code references, structural relationships, and update set contents for a result — add an `is_assessment_customization: bool` field by checking if the referenced `scan_result_id` exists as a customized record in the same assessment.

**Step 2: Update result_detail.html**

For each related item in the template:
- If `is_assessment_customization` is true, render `<span class="badge badge-customization">Customization</span>` and wrap the name in a link to `/assessments/{assessment_id}/results/{result_id}`
- If it belongs to a feature, show a feature color dot

**Step 3: Commit**

```bash
git add src/ tests/
git commit -m "feat: add customization badges and clickable links in result detail

Related lists (code refs, structural rels, update set contents) now
highlight items that are also customizations in this assessment with
[Customization] badge and clickable link to result detail."
```

---

## Task 8: Graph API Endpoint for Codex D3 Visualization

**Files:**
- Modify: `src/server.py` (add `GET /api/assessments/{id}/relationship-graph`)
- Create: `tests/test_relationship_graph_api.py`

**Step 1: Write failing test**

```python
def test_relationship_graph_api(client, session, assessment_with_engine_data):
    response = client.get(f"/api/assessments/{assessment_with_engine_data.id}/relationship-graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert "features" in data
```

**Step 2: Implement endpoint**

```python
@app.get("/api/assessments/{assessment_id}/relationship-graph")
async def get_relationship_graph_api(assessment_id: int, request: Request):
    with Session(engine) as session:
        graph = build_relationship_graph(session, assessment_id)
        # Build nodes, edges, features JSON from graph + Feature records
        # Include color_hex from FEATURE_COLORS[feature.color_index]
        return JSONResponse({"nodes": nodes, "edges": edges, "features": features})
```

**Step 3: Run tests and commit**

```bash
git add src/server.py tests/test_relationship_graph_api.py
git commit -m "feat: add GET /api/assessments/{id}/relationship-graph endpoint

Returns nodes/edges/features JSON for Codex D3 graph visualization.
Nodes include feature color info and customization status."
```

---

## Task 9: Full Regression + Admin File Updates

**Files:**
- Modify: `servicenow_global_tech_assessment_mcp/00_admin/insights.md`
- Modify: `servicenow_global_tech_assessment_mcp/00_admin/todos.md`
- Modify: `servicenow_global_tech_assessment_mcp/00_admin/context.md`

**Step 1: Run full regression**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`
Expected: All tests pass

**Step 2: Update admin files**

- `insights.md`: Add Phase 11 architecture decision
- `todos.md`: Mark Phase 11 tasks complete, add Phase 11E (Codex) task
- `context.md`: Update current status

**Step 3: Commit**

```bash
git add servicenow_global_tech_assessment_mcp/00_admin/
git commit -m "docs: update admin files for Phase 11 completion"
```

---

## Summary

| Task | What | Estimated Effort |
|------|------|-----------------|
| 1 | Remove `analysis_mode` from Assessment + properties | 15 min |
| 2 | Create `create_feature` MCP tool | 15 min |
| 3 | Create `add_result_to_feature` + `remove_result_from_feature` tools | 20 min |
| 4 | Refactor `seed_feature_groups` with `dry_run` mode | 25 min |
| 5 | Update DFS analyzer + simplify ai_analysis handler | 15 min |
| 6 | Feature color coding CSS + legend | 15 min |
| 7 | Customization badges in result detail | 20 min |
| 8 | Graph API endpoint for Codex | 15 min |
| 9 | Full regression + admin updates | 10 min |
