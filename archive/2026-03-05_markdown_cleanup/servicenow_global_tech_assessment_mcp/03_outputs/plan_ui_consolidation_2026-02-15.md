# UI Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate ~900 lines of duplicated UI code across assessment/scan/result/artifact templates by extracting shared components, standardizing on existing utilities, and consolidating backend logic.

**Architecture:** Merge findings from two audit documents (Codex full-app UI audit + Claude assessment-specific refactor debt analysis) into a single ordered execution plan. Work is grouped into 3 waves with explicit dependencies. Claude handles frontend JS extraction; Codex handles backend Python refactors and new JS modules that depend on Claude's Group 1 work.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend (no framework), Jinja2 templates, SQLModel ORM.

---

## Source Documents

- Full-app audit: `02_working/01_notes/codex_full_app_ui_modularization_audit_2026-02-15 2.md`
- Assessment-specific debt: `02_working/01_notes/assessment_ui_refactor_debt.md`

## Codebase Root

All paths relative to: `/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub/`

## Execution Status (Updated 2026-02-15 by Codex)

Completed in this plan:
- `Task 1C` (owner: codex) DONE
  - Promoted shared `get_class_label()` to `src/artifact_detail_defs.py`
  - Removed duplicate `_get_class_label()` from:
    - `src/services/artifact_detail_puller.py`
    - `src/web/routes/artifacts.py`
  - Updated callsites/imports to use shared helper.

- `Task 1D` (owner: codex) DONE
  - Added shared `_query_artifacts_for_scans()` in `src/web/routes/artifacts.py`
  - Simplified endpoints to call helper:
    - `api_assessment_artifacts`
    - `api_scan_artifacts`
  - Response shape preserved.

- `Task 2C` (owner: claude) DONE
  - Added reusable `ResultsFilterTable.js`
  - Loaded in `src/web/templates/base.html`
  - Wired in `src/web/templates/assessment_detail.html` + `src/web/templates/scan_detail.html`

- `Task 2A` (owner: codex) DONE
  - Added reusable `ArtifactList.js`
  - Loaded in `src/web/templates/base.html`
  - Replaced duplicated artifact list/filter code in:
    - `src/web/templates/assessment_detail.html`
    - `src/web/templates/scan_detail.html`

- `Task 2B` (owner: codex) DONE
  - Added reusable `ArtifactDetail.js`
  - Loaded in `src/web/templates/base.html`
  - Replaced duplicated artifact detail/code loaders in:
    - `src/web/templates/result_detail.html`
    - `src/web/templates/artifact_record.html`

Validation run by Codex:
- `./venv/bin/python -m pytest tests/ -q`
- Result after Task 1C: `98 passed`
- Result after Task 1D: `98 passed`
- Result after Wave 2 verification (2A/2B in current merged state): `98 passed`

Notes for Claude:
- Codex tasks for Wave 1 and Wave 2 (`2A`/`2B`) are complete and stable.
- No server/app restart was performed by Codex.
- `Task 3A` is intentionally deferred to backlog (low ROI vs current priorities).
- Remaining items are downstream Wave 3+ tasks or full-app backlog opportunities tracked in `00_admin/todos.md`.

---

## Group 1 — Quick Wins (zero inter-dependencies, all parallel)

### Task 1A: Extract `openTab()` to app.js [owner:claude]

**Files:**
- Modify: `src/web/static/js/app.js` — add global `openTab()` at end
- Modify: `src/web/templates/assessment_detail.html` — delete lines 618–634 (local `openTab`), replace monkey-patch at 1381–1392 with `tab:activated` event listener
- Modify: `src/web/templates/scan_detail.html` — delete lines 381–387 (local `openScanTab`), replace monkey-patch at 566–577 with `tab:activated` event listener
- Modify: `src/web/templates/result_detail.html` — delete lines 483–501 (local `openResultTab`), replace monkey-patch at 648–652 with `tab:activated` event listener

**Implementation:**

Add to end of `app.js`:
```javascript
// ── Global Tab Switcher ──
window.openTab = function openTab(evt, tabName) {
    var container = evt && evt.currentTarget
        ? evt.currentTarget.closest('.tab-container') || document
        : document;
    container.querySelectorAll('.tab-content').forEach(function (el) {
        el.classList.remove('active');
    });
    container.querySelectorAll('.tab-btn').forEach(function (el) {
        el.classList.remove('active');
    });
    var target = document.getElementById(tabName);
    if (target) target.classList.add('active');
    if (evt && evt.currentTarget) evt.currentTarget.classList.add('active');
    document.dispatchEvent(new CustomEvent('tab:activated', { detail: { tabName: tabName } }));
};
```

In each template, replace monkey-patch blocks with event listeners:
```javascript
// assessment_detail.html — replaces lines 1381-1392
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'customizations' && !_customizationsLoaded) {
        _customizationsLoaded = true;
        refreshCustomizations();
    }
    if (e.detail.tabName === 'artifacts' && !_artifactsLoaded) {
        _artifactsLoaded = true;
        refreshArtifacts();
    }
});
```

```javascript
// scan_detail.html — replaces lines 566-577
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'scan-artifacts' && !_scanArtifactsLoaded) {
        _scanArtifactsLoaded = true;
        refreshScanArtifacts();
    }
    if (e.detail.tabName === 'scan-results' && !_scanResultsLoaded) {
        _scanResultsLoaded = true;
        refreshScanResults();
    }
});
```

```javascript
// result_detail.html — replaces lines 648-652
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'artifact') loadArtifactDetail();
});
```

**Also update:** All HTML `onclick` attributes that reference `openScanTab` or `openResultTab` must be changed to `openTab`.

**Verification:** Click every tab on assessment, scan, and result pages. Confirm correct tab shows, lazy-load fires once, no console errors.

---

### Task 1B: Use global `formatDate()` everywhere [owner:claude]

**Files:**
- Modify: `src/web/templates/assessment_detail.html` — delete `formatAssessmentDate` (lines 640–643), replace all calls with `formatDate`
- Modify: `src/web/templates/scan_detail.html` — delete `formatScanDate` (lines 226–229), replace all calls with `formatDate`
- Modify: inline `.replace('T', ' ').slice(0, 16)` patterns in artifact row rendering in both templates

**Key:** `formatDate()` already exists in app.js (lines 160–185), is timezone-aware, and loaded globally. The local variants are naive string slicers that ignore timezone.

**Search targets:**
- `formatAssessmentDate(` → `formatDate(`
- `formatScanDate(` → `formatDate(`
- `String(row.sys_updated_on).replace('T', ' ').slice(0, 16)` → `formatDate(row.sys_updated_on)`

**Verification:** Check dates render correctly on assessment detail, scan detail, and artifact rows. Dates should now respect the configured display timezone.

---

### Task 1C: Promote `_get_class_label()` to shared utility [owner:codex]

**Files:**
- Modify: `src/artifact_detail_defs.py` — add public `get_class_label()` function
- Modify: `src/services/artifact_detail_puller.py` — delete `_get_class_label()` (lines 42–57), import from `artifact_detail_defs`
- Modify: `src/web/routes/artifacts.py` — delete `_get_class_label()` (lines 47–57), import from `artifact_detail_defs`

**Implementation:** Add to `src/artifact_detail_defs.py` after `COMMON_INHERITED_FIELDS`:
```python
def get_class_label(sys_class_name: str) -> str:
    """User-friendly label for an artifact class.
    Checks APP_FILE_CLASS_CATALOG first, falls back to humanizing the table name.
    """
    from .app_file_class_catalog import APP_FILE_CLASS_CATALOG
    for entry in APP_FILE_CLASS_CATALOG:
        if entry["sys_class_name"] == sys_class_name:
            return entry["label"]
    defn = ARTIFACT_DETAIL_DEFS.get(sys_class_name)
    if defn:
        return defn["local_table"].replace("asmt_", "").replace("_", " ").title()
    return sys_class_name
```

Update imports in both consumers:
```python
# In artifacts.py and artifact_detail_puller.py:
from ...artifact_detail_defs import (
    ARTIFACT_DETAIL_DEFS,
    COMMON_INHERITED_FIELDS,
    get_class_label,
    get_detail_def,
)
```

Then replace all internal calls from `_get_class_label(...)` to `get_class_label(...)`.

**Verification:** `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass.

---

### Task 1D: Extract `_query_artifacts_for_scans()` helper [owner:codex]

**Files:**
- Modify: `src/web/routes/artifacts.py` — extract shared logic, simplify both endpoints

**Implementation:** Create helper ABOVE the two endpoints (around line 200):
```python
def _query_artifacts_for_scans(
    session: Session,
    scan_ids: List[int],
    instance_id: int,
    sys_class_name: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> Dict[str, Any]:
    """Shared artifact list query for assessment and scan endpoints."""
    if not scan_ids:
        return {"artifacts": [], "total": 0, "classes": []}

    stmt = select(ScanResult.table_name, ScanResult.sys_id).where(
        ScanResult.scan_id.in_(scan_ids)
    )
    if sys_class_name:
        stmt = stmt.where(ScanResult.table_name == sys_class_name)
    result_rows = session.exec(stmt).all()

    from collections import defaultdict
    targets: Dict[str, set] = defaultdict(set)
    for tbl, sid in result_rows:
        if tbl and sid and tbl in ARTIFACT_DETAIL_DEFS:
            targets[tbl].add(sid)

    classes = [
        {"sys_class_name": cn, "label": get_class_label(cn), "count": len(sids)}
        for cn, sids in sorted(targets.items())
    ]

    artifacts: List[Dict[str, Any]] = []
    total = 0
    summary_fields = ["sys_id", "name", "active", "sys_scope", "sys_updated_on"]

    for class_name, sys_ids in targets.items():
        defn = ARTIFACT_DETAIL_DEFS[class_name]
        avail_fields = ["sys_id"] + [f[0] for f in defn["fields"]] + [f[0] for f in COMMON_INHERITED_FIELDS]
        query_fields = [f for f in summary_fields if f in avail_fields]
        if not query_fields:
            query_fields = ["sys_id"]

        rows, count = _query_artifact_table(
            sys_class_name=class_name,
            instance_id=instance_id,
            sys_ids=list(sys_ids),
            fields=query_fields,
            limit=limit,
        )
        for row in rows:
            row["sys_class_name"] = class_name
            row["class_label"] = get_class_label(class_name)
        artifacts.extend(rows)
        total += count

    artifacts.sort(key=lambda r: (r.get("name") or "").lower())
    paginated = artifacts[offset : offset + limit]

    return {"artifacts": paginated, "total": total, "classes": classes}
```

Then simplify both endpoints to ~5 lines each:
```python
@artifacts_router.get("/api/assessments/{assessment_id}/artifacts")
async def api_assessment_artifacts(
    assessment_id: int,
    sys_class_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    scans = session.exec(select(Scan.id).where(Scan.assessment_id == assessment_id)).all()
    return _query_artifacts_for_scans(session, list(scans), assessment.instance_id, sys_class_name, limit, offset)


@artifacts_router.get("/api/scans/{scan_id}/artifacts")
async def api_scan_artifacts(
    scan_id: int,
    sys_class_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    assessment = session.get(Assessment, scan.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return _query_artifacts_for_scans(session, [scan_id], assessment.instance_id, sys_class_name, limit, offset)
```

**Dependencies:** If 1C is done first, use `get_class_label` import. If not, use existing local `_get_class_label`.

**Verification:** `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass.

---

## Group 2 — JS Modules (after Group 1)

### Task 2A: Create `ArtifactList.js` [owner:codex]

**Depends on:** 1A (tab:activated event), 1B (formatDate)

**Files:**
- Create: `src/web/static/js/ArtifactList.js`
- Modify: `src/web/templates/assessment_detail.html` — replace artifact rendering/refresh/filter code (~95 lines) with ArtifactList init
- Modify: `src/web/templates/scan_detail.html` — replace artifact rendering/refresh/filter code (~95 lines) with ArtifactList init
- Modify: `src/web/templates/base.html` — add `<script src="/static/js/ArtifactList.js"></script>` before `{% block scripts %}`

See `assessment_ui_refactor_debt.md` section 2A for complete implementation code.

**Verification:** Click Artifacts tab on assessment and scan pages. Verify loading spinner, data renders, class filter works, badge updates, apply/reset work.

---

### Task 2B: Create `ArtifactDetail.js` [owner:codex]

**Depends on:** 1A (tab:activated event)

**Files:**
- Create: `src/web/static/js/ArtifactDetail.js`
- Modify: `src/web/templates/result_detail.html` — replace loadCodeContent + loadArtifactDetail
- Modify: `src/web/templates/artifact_record.html` — replace loadArtifactRecord
- Modify: `src/web/templates/base.html` — add script tag

See `assessment_ui_refactor_debt.md` section 2B for complete implementation code.

**Verification:** Open result page → Code Content card shows. Click Artifact tab → field table loads. Open standalone artifact record → all sections render.

---

### Task 2C: Create `ResultsFilterTable.js` [owner:claude]

**Depends on:** 1A (tab:activated), 1B (formatDate)

**Files:**
- Create: `src/web/static/js/ResultsFilterTable.js`
- Modify: `src/web/templates/assessment_detail.html` — replace results rendering + filtering pipeline
- Modify: `src/web/templates/scan_detail.html` — replace results rendering + filtering pipeline
- Modify: `src/web/templates/base.html` — add script tag

**Note:** This is the riskiest change because assessment_detail has additional logic (scopedCount, totals, periodic refresh during scans). The module must support:
- `showTotals: true` for assessment-specific totals row
- `optionsApiParams` for extra class options params
- External `instance.refresh()` calls from polling loop

**Verification:** Full manual test of both results tabs with all filter combinations.

---

## Group 3 — HTML Component Extraction (after Group 2)

### Task 3A: Jinja macros for filter cards [owner:claude]

**Depends on:** 2A, 2C

**Files:**
- Create: `src/web/templates/components/results_filter_card.html`
- Create: `src/web/templates/components/artifact_filter_card.html`
- Modify: assessment_detail.html, scan_detail.html — use `{% include %}` macros

Lower priority — JS modules eliminate behavioral duplication; this is structural HTML cleanup.

---

## Full-App Audit Items NOT in This Plan (Queued)

These items from the Codex full-app audit are independent of the assessment consolidation and should be tracked separately:

| # | Item | Priority | Status |
|---|------|----------|--------|
| 3.3 | Shared polling/status engine | H | Backlog — polling is minimal (3 calls site-wide), lower urgency |
| 3.4 | Standardize API + notification layer | H | Backlog — foundation work for future |
| 3.6 | Break up App File Options mega-controller | H | **Ready for Codex** — standalone, 542-line inline script |
| 3.8 | Standardize modal framework | M | Backlog |
| 3.9 | UI-focused system properties | H | Backlog — after core consolidation |
| 3.10 | Split monolithic CSS | M | Backlog |
| 3.11 | Harden innerHTML patterns | M | Backlog |

---

## Execution Timeline

```
TIME →

Group 1 (all parallel):
  Claude: 1A (openTab) + 1B (formatDate)
  Codex:  1C (_get_class_label) + 1D (_query_artifacts_for_scans)

  ↓ merge + test

Group 2 (parallel after Group 1):
  Codex:  2A (ArtifactList.js) + 2B (ArtifactDetail.js)
  Claude: 2C (ResultsFilterTable.js)

  ↓ merge + test

Group 3:
  Claude: 3A (Jinja macros)
```

## Test Plan

After each group:
1. `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass
2. Start app, navigate to all affected pages
3. Run a scan workflow → verify polling updates correctly
4. Verify date formatting uses timezone preference everywhere
