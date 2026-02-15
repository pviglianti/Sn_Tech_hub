# Customization Child Table Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a physical `customization` child table for pre-filtered customized scan results, add Customizations tab to assessment/scan views, reorder tabs, update Results filter, and create a new MCP tool.

**Architecture:** One new SQLModel (`Customization`) with FK to `scan_result`. Copy-on-classify sync in scan_executor (bulk) and result update endpoint (per-record). New API router + MCP tool. UI tabs reordered with Customizations first.

**Tech Stack:** Python/FastAPI, SQLModel, SQLite, Jinja2 templates, vanilla JS

---

## Work Streams (Parallelizable)

```
Stream A (Backend Model + Sync):  Tasks 1 → 2 → 3
Stream B (API + MCP):             Task 4 → 5  (after Task 1)
Stream C (UI Templates):          Task 6 → 7  (after Task 4)
Stream D (Tests):                 Task 8       (after Tasks 1-5)
```

Streams A and B can start in parallel once Task 1 is committed.
Stream C starts after Stream B (needs API endpoints).
Stream D can overlap with Stream C.

---

### Task 1: Create Customization Model

**Files:**
- Modify: `src/models.py` — add Customization class after ScanResult (after line 509)

**Step 1: Add the Customization model**

Add after the `ScanResult` class (after line 509, before the `Feature` class at line 516):

```python
# ============================================
# TABLE: Customization (child of ScanResult)
# Pre-filtered: only customized results (modified_ootb, net_new_customer)
# AI reads this table directly — no query conditions needed.
# ============================================

class Customization(SQLModel, table=True):
    """Child table of ScanResult containing only customized results.

    This table is a denormalized projection of scan_result rows where
    origin_type is 'modified_ootb' or 'net_new_customer'. It exists so
    that MCP/AI can SELECT * without filtering conditions, eliminating
    the risk of accidentally reading non-customized data.

    Sync: populated by scan_executor (bulk) and result update endpoint (per-record).
    """
    __tablename__ = "customization"

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True, sa_column_kwargs={"unique": True})
    scan_id: int = Field(foreign_key="scan.id", index=True)

    # Copied from parent scan_result
    sys_id: str = Field(index=True)
    table_name: str = Field(index=True)
    name: str
    origin_type: Optional[OriginType] = Field(default=None, index=True)
    head_owner: Optional[HeadOwner] = None
    sys_class_name: Optional[str] = None
    sys_scope: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.pending_review
    disposition: Optional[Disposition] = None
    recommendation: Optional[str] = None
    observations: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    scan_result: ScanResult = Relationship(back_populates="customization")
    scan: Scan = Relationship(back_populates="customizations")
```

**Step 2: Add relationship back-populates on ScanResult and Scan**

On `ScanResult` (after line 509, in the relationships section):
```python
    customization: Optional["Customization"] = Relationship(back_populates="scan_result")
```

On `Scan` (after line 412, in the relationships section):
```python
    customizations: List["Customization"] = Relationship(back_populates="scan")
```

**Step 3: Verify table creation**

Run: `cd "/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub" && ./venv/bin/python -c "from sqlmodel import SQLModel, create_engine; from src.models import *; e = create_engine('sqlite://'); SQLModel.metadata.create_all(e); print('OK')" `
Expected: `OK` with no errors

**Step 4: Commit**

```bash
git add src/models.py
git commit -m "feat: add Customization child table model"
```

---

### Task 2: Create Sync Helper Module

**Files:**
- Create: `src/services/customization_sync.py`

**Step 1: Create the sync helper**

```python
"""Customization table sync helpers.

Provides functions to keep the customization child table in sync with
scan_result. Called from scan_executor (bulk) and result update (per-record).
"""

from datetime import datetime
from typing import List, Optional

from sqlmodel import Session, select

from ..models import Customization, OriginType, ScanResult


CUSTOMIZED_ORIGIN_TYPES = {OriginType.modified_ootb, OriginType.net_new_customer}


def is_customized(origin_type: Optional[OriginType]) -> bool:
    """Return True if the origin_type counts as a customization."""
    return origin_type in CUSTOMIZED_ORIGIN_TYPES


def _build_customization_from_result(result: ScanResult) -> Customization:
    """Create a Customization row from a ScanResult."""
    return Customization(
        scan_result_id=result.id,
        scan_id=result.scan_id,
        sys_id=result.sys_id,
        table_name=result.table_name,
        name=result.name,
        origin_type=result.origin_type,
        head_owner=result.head_owner,
        sys_class_name=result.sys_class_name,
        sys_scope=result.sys_scope,
        review_status=result.review_status,
        disposition=result.disposition,
        recommendation=result.recommendation,
        observations=result.observations,
        sys_updated_on=result.sys_updated_on,
    )


def bulk_sync_for_scan(session: Session, scan_id: int) -> int:
    """Populate customization rows for all customized results in a scan.

    Typically called once after scan_executor completes a scan.
    Skips results that already have a customization row.
    Returns the number of rows inserted.
    """
    results = session.exec(
        select(ScanResult)
        .where(ScanResult.scan_id == scan_id)
        .where(ScanResult.origin_type.in_([ot.value for ot in CUSTOMIZED_ORIGIN_TYPES]))
    ).all()

    existing_result_ids = set(
        session.exec(
            select(Customization.scan_result_id)
            .where(Customization.scan_id == scan_id)
        ).all()
    )

    count = 0
    for result in results:
        if result.id not in existing_result_ids:
            session.add(_build_customization_from_result(result))
            count += 1

    if count:
        session.commit()
    return count


def sync_single_result(session: Session, result: ScanResult) -> None:
    """Sync a single scan_result's customization row after an update.

    - If result is customized and no customization row exists → INSERT
    - If result is customized and row exists → UPDATE fields
    - If result is NOT customized and row exists → DELETE
    """
    existing = session.exec(
        select(Customization)
        .where(Customization.scan_result_id == result.id)
    ).first()

    if is_customized(result.origin_type):
        if existing:
            # Update mutable fields
            existing.origin_type = result.origin_type
            existing.head_owner = result.head_owner
            existing.review_status = result.review_status
            existing.disposition = result.disposition
            existing.recommendation = result.recommendation
            existing.observations = result.observations
            existing.name = result.name
            existing.sys_scope = result.sys_scope
            existing.sys_updated_on = result.sys_updated_on
            session.add(existing)
        else:
            session.add(_build_customization_from_result(result))
    elif existing:
        session.delete(existing)
```

**Step 2: Commit**

```bash
git add src/services/customization_sync.py
git commit -m "feat: add customization sync helper module"
```

---

### Task 3: Wire Sync into Scan Executor + Result Update

**Files:**
- Modify: `src/services/scan_executor.py` — add bulk_sync call after scan completion (after line 938)
- Modify: `src/server.py` — add sync_single_result call in update_result endpoint (after line 3865)

**Step 1: Add bulk sync to scan_executor.py**

After line 938 (after `session.commit()` at end of `execute_scan()`), add:

```python
    # Sync customization child table
    from .customization_sync import bulk_sync_for_scan
    bulk_sync_for_scan(session, scan.id)
```

The exact insertion point is after these lines (935-938):
```python
    scan.status = ScanStatus.completed
    scan.completed_at = datetime.utcnow()
    session.add(scan)
    session.commit()
```

**Step 2: Add per-record sync to result update endpoint**

In `src/server.py`, in the `update_result()` function (line 3799), add the sync call after `session.commit()` at line 3868.

After:
```python
    session.add(result)
    session.commit()
```

Add:
```python
    # Sync customization child table
    from .services.customization_sync import sync_single_result
    sync_single_result(session, result)
    session.commit()
```

**Step 3: Run existing tests**

Run: `cd "/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub" && ./venv/bin/python -m pytest tests/ -q`
Expected: All 87 tests pass (no regressions)

**Step 4: Commit**

```bash
git add src/services/scan_executor.py src/server.py
git commit -m "feat: wire customization sync into scan executor and result update"
```

---

### Task 4: Create Customizations API Router

**Files:**
- Create: `src/web/routes/customizations.py`
- Modify: `src/server.py` — import and register the router (lines 63-73 imports, line 2380 registration)

**Step 1: Create the router**

```python
"""Customizations API router.

Endpoints for the customization child table — pre-filtered customized
scan results. No customized_only parameter needed; the table IS the filter.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, desc, func, select

from ...models import (
    Assessment,
    Customization,
    OriginType,
    Scan,
)
from ...server import get_session

customizations_router = APIRouter(tags=["customizations"])


def _build_customization_payload(row: Customization) -> Dict[str, Any]:
    """Build JSON-serializable dict from a Customization row."""
    return {
        "id": row.id,
        "scan_result_id": row.scan_result_id,
        "scan_id": row.scan_id,
        "sys_id": row.sys_id,
        "table_name": row.table_name,
        "name": row.name,
        "origin_type": row.origin_type.value if row.origin_type else None,
        "head_owner": row.head_owner.value if row.head_owner else None,
        "sys_class_name": row.sys_class_name,
        "sys_scope": row.sys_scope,
        "review_status": row.review_status.value if row.review_status else None,
        "disposition": row.disposition.value if row.disposition else None,
        "recommendation": row.recommendation,
        "observations": row.observations,
        "sys_updated_on": row.sys_updated_on.isoformat() if row.sys_updated_on else None,
    }


@customizations_router.get("/api/assessments/{assessment_id}/customizations")
async def api_assessment_customizations(
    assessment_id: int,
    origin_type: Optional[str] = Query(default=None),
    table_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """List customizations for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    scan_ids = [
        row for row in session.exec(
            select(Scan.id).where(Scan.assessment_id == assessment_id)
        ).all()
    ]
    if not scan_ids:
        return {"customizations": [], "total": 0, "classes": []}

    return _query_customizations(session, scan_ids, origin_type, table_name, limit, offset)


@customizations_router.get("/api/scans/{scan_id}/customizations")
async def api_scan_customizations(
    scan_id: int,
    origin_type: Optional[str] = Query(default=None),
    table_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """List customizations for a scan."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    return _query_customizations(session, [scan_id], origin_type, table_name, limit, offset)


def _query_customizations(
    session: Session,
    scan_ids: List[int],
    origin_type: Optional[str],
    table_name: Optional[str],
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    """Shared query logic for customization endpoints."""
    conditions = [Customization.scan_id.in_(scan_ids)]

    if origin_type:
        conditions.append(Customization.origin_type == origin_type)
    if table_name:
        conditions.append(Customization.table_name == table_name)

    # Total count
    count_stmt = select(func.count()).select_from(Customization).where(*conditions)
    total = int(session.exec(count_stmt).one() or 0)

    # Class breakdown
    class_stmt = (
        select(Customization.table_name, Customization.sys_class_name, func.count())
        .where(Customization.scan_id.in_(scan_ids))
        .group_by(Customization.table_name, Customization.sys_class_name)
        .order_by(Customization.table_name)
    )
    classes = [
        {"table_name": tn, "sys_class_name": cn, "label": cn or tn, "count": c}
        for tn, cn, c in session.exec(class_stmt).all()
    ]

    # Fetch rows
    stmt = (
        select(Customization)
        .where(*conditions)
        .order_by(Customization.name.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(stmt).all()

    return {
        "customizations": [_build_customization_payload(r) for r in rows],
        "total": total,
        "classes": classes,
    }


@customizations_router.get("/api/customizations/options")
async def api_customizations_options(
    assessment_id: Optional[int] = Query(default=None),
    scan_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
):
    """Return filter options (class list) for customizations."""
    conditions = []
    if assessment_id:
        scan_ids = list(session.exec(
            select(Scan.id).where(Scan.assessment_id == assessment_id)
        ).all())
        if scan_ids:
            conditions.append(Customization.scan_id.in_(scan_ids))
        else:
            return {"classes": [], "total": 0}
    elif scan_id:
        conditions.append(Customization.scan_id == scan_id)

    class_stmt = (
        select(Customization.table_name, Customization.sys_class_name, func.count())
        .group_by(Customization.table_name, Customization.sys_class_name)
        .order_by(Customization.table_name)
    )
    if conditions:
        class_stmt = class_stmt.where(*conditions)

    classes = [
        {"table_name": tn, "sys_class_name": cn, "label": cn or tn, "count": c}
        for tn, cn, c in session.exec(class_stmt).all()
    ]

    count_stmt = select(func.count()).select_from(Customization)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(session.exec(count_stmt).one() or 0)

    return {"classes": classes, "total": total}
```

**Step 2: Register the router in server.py**

Add to imports (around line 73):
```python
from .web.routes.customizations import customizations_router
```

Add to router registration (around line 2380):
```python
app.include_router(customizations_router)
```

**Step 3: Run tests**

Run: `cd "/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub" && ./venv/bin/python -m pytest tests/ -q`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/web/routes/customizations.py src/server.py
git commit -m "feat: add customizations API router"
```

---

### Task 5: Create MCP Tool

**Files:**
- Create: `src/mcp/tools/core/customizations.py`
- Modify: `src/mcp/tools/core/__init__.py` — register the tool

**Step 1: Create the MCP tool**

```python
"""MCP tool: get_customizations

Returns customized scan results from the customization child table.
No customized_only parameter needed — the table IS the filter.
"""

from typing import Any, Dict

from sqlmodel import Session, func, select

from ....models import Assessment, Customization, Scan
from ...registry import ToolSpec

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment ID to retrieve customizations for.",
        },
        "origin_type": {
            "type": "string",
            "description": "Filter by origin: 'modified_ootb' or 'net_new_customer'.",
            "enum": ["modified_ootb", "net_new_customer"],
        },
        "table_name": {
            "type": "string",
            "description": "Filter by ServiceNow table (e.g., sys_script_include).",
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return (default 50).",
            "default": 50,
        },
        "offset": {
            "type": "integer",
            "description": "Offset for pagination (default 0).",
            "default": 0,
        },
    },
    "required": ["assessment_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = params.get("assessment_id")
    if assessment_id is None:
        raise ValueError("assessment_id is required")

    assessment = session.get(Assessment, int(assessment_id))
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    scan_ids = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == int(assessment_id))
    ).all())

    if not scan_ids:
        return {"success": True, "total": 0, "customizations": [], "assessment_name": assessment.name}

    query = select(Customization).where(Customization.scan_id.in_(scan_ids))

    origin_type = params.get("origin_type")
    if origin_type:
        query = query.where(Customization.origin_type == origin_type)

    table_name = params.get("table_name")
    if table_name:
        query = query.where(Customization.table_name == table_name)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    # Paginate
    limit = min(params.get("limit", 50), 200)
    offset = params.get("offset", 0)
    query = query.order_by(Customization.name.asc()).offset(offset).limit(limit)

    rows = session.exec(query).all()

    condensed = []
    for r in rows:
        condensed.append({
            "id": r.id,
            "scan_result_id": r.scan_result_id,
            "sys_id": r.sys_id,
            "table_name": r.table_name,
            "name": r.name,
            "origin_type": r.origin_type.value if r.origin_type else None,
            "head_owner": r.head_owner.value if r.head_owner else None,
            "sys_class_name": r.sys_class_name,
            "sys_scope": r.sys_scope,
            "review_status": r.review_status.value if r.review_status else None,
            "disposition": r.disposition.value if r.disposition else None,
            "sys_updated_on": r.sys_updated_on.isoformat() if r.sys_updated_on else None,
        })

    return {
        "success": True,
        "assessment_name": assessment.name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "customizations": condensed,
    }


TOOL_SPEC = ToolSpec(
    name="get_customizations",
    description=(
        "Retrieve customized scan results for an assessment from the customization "
        "child table. This table contains ONLY customized results (modified_ootb, "
        "net_new_customer) — no filtering needed. Returns condensed fields for "
        "token efficiency. Supports pagination with limit/offset."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
```

**Step 2: Register in `__init__.py`**

Check the current `__init__.py` pattern and add the new tool's TOOL_SPEC to the registry list. Look for where other TOOL_SPECs are collected and add `customizations.TOOL_SPEC`.

**Step 3: Commit**

```bash
git add src/mcp/tools/core/customizations.py src/mcp/tools/core/__init__.py
git commit -m "feat: add get_customizations MCP tool"
```

---

### Task 6: Update Assessment Detail Template

**Files:**
- Modify: `src/web/templates/assessment_detail.html`

This is the largest task. Changes:
1. Reorder tabs: Scans | **Customizations** | Features | Artifacts | Results
2. Add Customizations tab content with filters
3. Update Results tab: remove "Customized Only" checkbox, add Classification dropdown defaulting to "All"
4. Add JS for customizations tab loading

**Step 1: Reorder tab buttons (lines 306-319)**

Replace the tab-nav section with new order. Add Customizations between Scans and Features. Move Results to the end.

New tab order:
```html
<div class="tab-nav">
    <button class="tab-btn active" onclick="openTab(event, 'scans')">
        Scans <span class="badge">{{ assessment.scans | length }}</span>
    </button>
    <button class="tab-btn" onclick="openTab(event, 'customizations')" id="customizationsTabBtn">
        Customizations <span class="badge" id="customizationsTabBadge">{{ assessment.records_customized }}</span>
    </button>
    <button class="tab-btn" onclick="openTab(event, 'features')">
        Features <span class="badge">{{ assessment.features | length }}</span>
    </button>
    <button class="tab-btn" onclick="openTab(event, 'artifacts')" id="artifactsTabBtn">
        Artifacts <span class="badge" id="artifactsTabBadge">0</span>
    </button>
    <button class="tab-btn" onclick="openTab(event, 'results')">
        Results <span class="badge" id="assessmentResultsTabBadge">{{ assessment.total_findings }}</span>
    </button>
</div>
```

**Step 2: Add Customizations tab content**

Add a new `<div id="customizations" class="tab-content">` between the Scans tab-content and Results tab-content. Include:

- Filter card with:
  - **Customization Type** dropdown: All | Modified OOTB | Net New Customer
  - **App File Class** dropdown (populated via API)
  - Apply / Reset buttons
  - Meta text
- Loading overlay
- Results table (Name, Class, Origin, Scope, Review, Disposition, Updated, Actions)
- Empty state

The table row rendering links to `/results/{scan_result_id}` — the existing result detail page.

**Step 3: Update Results tab filter card (lines 398-435)**

Remove the "Customized Only" checkbox. Replace with a Classification dropdown:
```html
<div class="filter-group">
    <label for="assessmentResultsClassification">Classification</label>
    <select id="assessmentResultsClassification" class="form-control">
        <option value="all" selected>All Results</option>
        <option value="customized">Customized</option>
        <option value="uncustomized">Uncustomized</option>
        <option value="modified_ootb">Modified OOTB</option>
        <option value="net_new_customer">Net New Customer</option>
        <option value="ootb_untouched">OOTB Untouched</option>
        <option value="unknown">Unknown</option>
    </select>
</div>
```

Remove the `assessmentResultsClassificationGroup` conditional visibility logic (it was tied to the checkbox).

**Step 4: Add customizations tab JS**

Add functions:
- `setCustomizationsLoading(isLoading)` — toggle loading overlay
- `renderCustomizationRows(rows)` — build `<tr>` elements, link to `/results/${row.scan_result_id}`
- `refreshCustomizations()` — fetch from `/api/assessments/${assessmentId}/customizations`, populate class filter, render rows, update badge + meta
- Lazy-load: listen for `tab:activated` event (or monkey-patch openTab) with tabName `'customizations'`

**Step 5: Update Results tab JS**

Modify `refreshAssessmentResults()`:
- Read the new Classification dropdown instead of checkbox + classification combo
- Map dropdown value to API params:
  - `"all"` → `customized_only=false`
  - `"customized"` → `customized_only=true, customization_type=all`
  - `"uncustomized"` → custom condition (origin NOT in customized set)
  - `"modified_ootb"` → `customized_only=true, customization_type=modified_ootb`
  - etc.
- Remove `syncAssessmentClassificationVisibility()` (no longer needed)

Update reset handler: set Classification dropdown to `"all"` (not "customized").

**Step 6: Verify and commit**

Manual test: navigate to assessment detail, verify all 5 tabs work, Customizations loads data, Results shows all by default.

```bash
git add src/web/templates/assessment_detail.html
git commit -m "feat: add Customizations tab and reorder assessment tabs"
```

---

### Task 7: Update Scan Detail Template

**Files:**
- Modify: `src/web/templates/scan_detail.html`

Mirrors Task 6 but for the scan view.

**Step 1: Reorder tab buttons (lines 47-54)**

New order:
```html
<div class="tab-nav">
    <button type="button" class="tab-btn active" onclick="openScanTab(event, 'scan-customizations')" id="scanCustomizationsTabBtn">
        Customizations <span class="badge" id="scanCustomizationsTabBadge">{{ scan.records_customized }}</span>
    </button>
    <button type="button" class="tab-btn" onclick="openScanTab(event, 'scan-artifacts')" id="scanArtifactsTabBtn">
        Artifacts <span class="badge" id="scanArtifactsTabBadge">0</span>
    </button>
    <button type="button" class="tab-btn" onclick="openScanTab(event, 'scan-results')">
        Results <span class="badge" id="scanResultsTabBadge">{{ scan.records_found }}</span>
    </button>
</div>
```

Note: Customizations is the **default active tab** on scan detail.

**Step 2: Add Customizations tab content**

New `<div id="scan-customizations" class="tab-content active">` — same pattern as assessment version but with scan-prefixed IDs. Filter card with Customization Type + App File Class dropdowns. Table, loading, empty state.

**Step 3: Update Results tab**

- Move from first to last position
- Change from `active` to non-active
- Remove "Customized Only" checkbox, add Classification dropdown (same as assessment)
- Default to "All"

**Step 4: Add customizations JS + update Results JS**

Same pattern as Task 6:
- `refreshScanCustomizations()` fetching from `/api/scans/${scanId}/customizations`
- Auto-load on page load (since it's the default tab)
- Update results refresh to use Classification dropdown instead of checkbox

**Step 5: Verify and commit**

```bash
git add src/web/templates/scan_detail.html
git commit -m "feat: add Customizations tab and reorder scan tabs"
```

---

### Task 8: Tests

**Files:**
- Create: `tests/test_customization_sync.py`
- Modify: `tests/conftest.py` — add customization-related fixtures if needed

**Step 1: Write model creation test**

```python
def test_customization_table_created(db_engine):
    """Customization table exists after metadata.create_all."""
    from sqlalchemy import inspect
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()
    assert "customization" in tables
```

**Step 2: Write bulk sync tests**

```python
def test_bulk_sync_creates_customization_rows(db_session, sample_instance):
    """bulk_sync_for_scan populates customization for customized results."""
    # Create assessment, scan, and results with mixed origin_types
    # Call bulk_sync_for_scan
    # Assert: only modified_ootb and net_new_customer results have customization rows
    # Assert: ootb_untouched results do NOT have customization rows

def test_bulk_sync_skips_existing(db_session, sample_instance):
    """bulk_sync_for_scan does not duplicate existing customization rows."""

def test_bulk_sync_returns_count(db_session, sample_instance):
    """bulk_sync_for_scan returns the number of rows inserted."""
```

**Step 3: Write single result sync tests**

```python
def test_sync_creates_customization_for_new_customized_result(db_session, sample_instance):
    """sync_single_result creates row when result becomes customized."""

def test_sync_deletes_customization_when_reclassified(db_session, sample_instance):
    """sync_single_result removes row when result is no longer customized."""

def test_sync_updates_fields_on_existing(db_session, sample_instance):
    """sync_single_result updates disposition/review on existing customization."""
```

**Step 4: Write API endpoint tests**

```python
def test_assessment_customizations_endpoint(db_session, sample_instance):
    """GET /api/assessments/{id}/customizations returns only customized results."""

def test_scan_customizations_endpoint(db_session, sample_instance):
    """GET /api/scans/{id}/customizations returns only customized results."""

def test_customizations_filter_by_origin_type(db_session, sample_instance):
    """origin_type parameter filters customizations correctly."""
```

**Step 5: Run all tests**

Run: `cd "/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub" && ./venv/bin/python -m pytest tests/ -q`
Expected: All tests pass (87 existing + new tests)

**Step 6: Commit**

```bash
git add tests/test_customization_sync.py tests/conftest.py
git commit -m "test: add customization sync and API tests"
```

---

### Task 9: Backfill Existing Data (One-time migration)

**Files:**
- Create: `src/scripts/backfill_customizations.py`

**Step 1: Create backfill script**

A standalone script that scans all existing `scan_result` rows with customized origin_types and populates the `customization` table. Run once after deployment.

```python
"""One-time backfill: populate customization table from existing scan_results."""

from sqlmodel import Session, select
from ..models import Customization, ScanResult, OriginType
from ..services.customization_sync import CUSTOMIZED_ORIGIN_TYPES, _build_customization_from_result


def backfill(session: Session) -> int:
    results = session.exec(
        select(ScanResult).where(
            ScanResult.origin_type.in_([ot.value for ot in CUSTOMIZED_ORIGIN_TYPES])
        )
    ).all()

    existing = set(session.exec(select(Customization.scan_result_id)).all())
    count = 0
    for result in results:
        if result.id not in existing:
            session.add(_build_customization_from_result(result))
            count += 1

    session.commit()
    return count
```

**Step 2: Commit**

```bash
git add src/scripts/backfill_customizations.py
git commit -m "feat: add one-time customization backfill script"
```

---

## Parallel Execution Summary

```
TIME →

Stream A (Claude Code):
  Task 1 (model) → Task 2 (sync helper) → Task 3 (wire sync)

Stream B (parallel agent after Task 1):
  Task 4 (API router) → Task 5 (MCP tool)

Stream C (after Task 4):
  Task 6 (assessment_detail.html) + Task 7 (scan_detail.html) — can be parallel

Stream D (after Streams A+B):
  Task 8 (tests) → Task 9 (backfill script)
```

Tasks 6 and 7 are the largest and can themselves be done in parallel by separate agents since they modify different files.
