# Assessment UI Stack — Refactor Debt & Modularization Plan

> Created: 2026-02-15 | Status: Ready for execution
> Scope: assessment_detail, scan_detail, result_detail, artifact_record templates + artifacts.py backend

---

## 1. Executive Summary

The assessment-related UI templates contain **~530 lines of duplicated code** across 4 HTML templates, 3 JS contexts, and 1 Python route file. The duplication falls into two categories:

- **Pre-existing** (P-prefixed): Results rendering, filtering, tab switching, date formatting — existed before the artifact sprint
- **New** (N-prefixed): Artifact list rendering, artifact detail/code display, backend artifact query logic — introduced during artifact detail sprint

This document catalogs every instance with exact file paths and line numbers, then provides a prioritized, parallelizable work plan.

---

## 2. Codebase File Map

| File | Path | Role | Inline JS Lines |
|------|------|------|----------------|
| assessment_detail.html | `src/web/templates/assessment_detail.html` | Assessment view with 4 tabs (Scans, Results, Features, Artifacts) + Preflight/Postflight status | ~668 lines |
| scan_detail.html | `src/web/templates/scan_detail.html` | Scan view with 2 tabs (Results, Artifacts) | ~243 lines |
| result_detail.html | `src/web/templates/result_detail.html` | Result record with 3 sub-tabs + code content card | ~174 lines |
| artifact_record.html | `src/web/templates/artifact_record.html` | Standalone artifact detail page | ~80 lines |
| artifacts.py | `src/web/routes/artifacts.py` | Artifact API endpoints + HTML route | 441 lines Python |
| artifact_detail_puller.py | `src/services/artifact_detail_puller.py` | Post-scan artifact pull service | 248 lines Python |
| app.js | `src/web/static/js/app.js` | Global utilities (theme, formatDate, apiCall, dict pull) | 275 lines |
| DataTable.js | `src/web/static/js/DataTable.js` | Reusable schema-driven table component (used by browse pages) | ~500 lines |
| server.py | `src/server.py` | Main app — results endpoints, scan pipeline, polling | ~4200 lines |

---

## 3. Detailed Duplication Inventory

### 3.1 — Tab Switching (P6) — THREE identical implementations

**What:** Every template defines its own tab switching function with the same logic: remove `active` from all `.tab-content` and `.tab-btn`, add `active` to the selected pair.

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `openTab(evt, tabName)` | 565–581 |
| scan_detail.html | `openScanTab(evt, tabName)` | 309–315 |
| result_detail.html | `openResultTab(evt, tabName)` | 483–501 |

**Differences:** result_detail hardcodes tab IDs in an array; assessment/scan use querySelectorAll. Functionally identical.

**Impact:** 3 × ~15 = **45 lines** of duplication.

---

### 3.2 — Date Formatting (P5) — THREE implementations + ONE unused global

**What:** Each template defines a local date formatter that does `value.replace('T', ' ').slice(0, 16)`. Meanwhile, `app.js:160-185` already has a global `formatDate()` that is timezone-aware and better.

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `formatAssessmentDate(value)` | 587–590 |
| scan_detail.html | `formatScanDate(value)` | 173–176 |
| Artifact inline code | `String(row.sys_updated_on).replace('T',' ').slice(0,16)` | (inline, multiple spots) |
| **app.js** (UNUSED by templates) | `formatDate(dateString)` | 160–185 |

**Impact:** ~10 lines wasted + all template dates ignore user timezone preference.

---

### 3.3 — Results Row Rendering (P1) — TWO byte-for-byte copies

**What:** The function that builds `<tr>` elements for scan results is identical in both templates.

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `renderAssessmentResultsRows(rows)` | 610–639 |
| scan_detail.html | `renderScanRows(rows)` | 191–219 |

**Differences:** Function name only. DOM IDs differ (`assessmentResultsBody` vs `scanResultsBody`, `assessmentResultsEmpty` vs `scanResultsEmpty`).

Both render: Name (link), App File Class (code), Scan name, Customized (Yes/No), Classification (origin badge), Review, Disposition, Updated, Actions.

**Impact:** ~30 lines × 2 = **60 lines** duplicated.

---

### 3.4 — Results Loading State (P1 cont.) — TWO copies

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `setAssessmentResultsLoading(isLoading)` | 592–596 |
| scan_detail.html | `setScanResultsLoading(isLoading)` | 178–182 |

Identical: toggle `display: flex/none` on a loading overlay element.

---

### 3.5 — Results Refresh Pipeline (P2) — TWO copies

**What:** The full fetch → filter → render pipeline for results:

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `refreshAssessmentResults()` | 833–884 |
| scan_detail.html | `refreshScanResults()` | 250–284 |

Both:
1. Read customized_only checkbox, classification select, class filter select
2. Build URLSearchParams
3. Fetch from `/api/{scope}/{id}/results?...`
4. Call renderRows with results
5. Update meta text ("Showing X of Y results")

**Differences:** API URL path (`/assessments/${id}/results` vs `/scans/${id}/results`), assessment version has extra `scopedCount` logic.

**Impact:** ~46 lines × 2 = **92 lines** duplicated.

---

### 3.6 — Class Options Loader (P3) — TWO copies

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `loadAssessmentClassOptions()` | 798–831 |
| scan_detail.html | `loadScanClassOptions()` | 221–248 |

Both: fetch `/api/results/options?...`, populate class filter `<select>`, preserve current selection.

**Impact:** ~28 lines × 2 = **56 lines** duplicated.

---

### 3.7 — Classification Visibility Toggle (P4) — TWO copies

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `syncAssessmentClassificationVisibility()` | 641–646 |
| scan_detail.html | `syncScanClassificationVisibility()` | 184–189 |

Both: show/hide the "Customization Type" dropdown based on "Customized Only" checkbox state.

**Impact:** ~6 lines × 2 = **12 lines** duplicated.

---

### 3.8 — Filter Reset Handler (P8) — TWO copies

| Location | Lines |
|----------|-------|
| assessment_detail.html | 978–987 |
| scan_detail.html | 234–243 |

Both: set checkbox to true, selects to defaults, call sync + refresh.

**Impact:** ~10 lines × 2 = **20 lines** duplicated.

---

### 3.9 — Results Filter Card HTML (P7) — TWO copies

**What:** The HTML structure for the filter card (Customization Scope checkbox, Customization Type select, App File Class select, Apply/Reset buttons, meta text) is structurally identical.

| Location | Lines |
|----------|-------|
| assessment_detail.html | 398–435 (inside Results tab) |
| scan_detail.html | 58–90 (inside Results tab) |

**Differences:** DOM ID prefixes (`assessment` vs `scan`), assessment version has an extra totals meta line.

**Impact:** ~38 lines × 2 = **76 lines** duplicated HTML.

---

### 3.10 — Artifact List Rendering (N1) — TWO copies

**What:** The function that builds `<tr>` elements for artifacts.

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `renderArtifactRows(rows)` | 1075–1100 |
| scan_detail.html | `renderScanArtifactRows(rows)` | 267–292 |

**Differences:** `instanceId` variable name (`assessmentInstanceId` vs `scanInstanceId`). Otherwise identical.

Both render: Name (link to /artifacts/), Class label, Active (Yes/No/-), Scope, Updated, View button.

**Impact:** ~25 lines × 2 = **50 lines** duplicated.

---

### 3.11 — Artifact Refresh Pipeline (N2) — TWO copies

| Location | Function Name | Lines |
|----------|--------------|-------|
| assessment_detail.html | `refreshArtifacts()` | 1102–1143 |
| scan_detail.html | `refreshScanArtifacts()` | 294–334 |

Both:
1. Set loading overlay
2. Fetch from `/api/{scope}/{id}/artifacts?...`
3. Populate class filter dropdown from response `classes` array
4. Render rows
5. Update badge count + meta text

**Differences:** API URL only.

**Impact:** ~40 lines × 2 = **80 lines** duplicated.

---

### 3.12 — Artifact Detail + Code Rendering (N3) — TWO copies

**What:** Field-value table rendering AND code content `<pre>` block rendering.

| Location | Functions | Lines |
|----------|----------|-------|
| result_detail.html | `loadCodeContent()` + `loadArtifactDetail()` | 525–610 |
| artifact_record.html | `loadArtifactRecord()` (combined) | 69–140 |

Both share:
- HTML escaping: `.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')`
- Field-value row: `<td><strong>${label}</strong><br><code>${field}</code></td><td>${value}</td>`
- Code content: `<div class="info-label">${label} <code>(${field})</code></div><pre class="code-block max-h-420">${escaped}</pre>`

**Impact:** ~80 lines × 2 = **160 lines** duplicated.

---

### 3.13 — Artifact Filter Card HTML (N4) — TWO copies

| Location | Lines |
|----------|-------|
| assessment_detail.html | 492–535 (Artifacts tab) |
| scan_detail.html | 119–163 (Artifacts tab) |

Identical structure: class filter select, Apply/Reset, meta, loading overlay, table, empty state.

**Impact:** ~40 lines × 2 = **80 lines** duplicated HTML.

---

### 3.14 — Backend: Artifact List Query (N5) — TWO copies in Python

**What:** The assessment artifacts endpoint and scan artifacts endpoint share ~60 lines of identical logic.

| Location | Function | Lines |
|----------|---------|-------|
| artifacts.py | `api_assessment_artifacts()` | 207–284 |
| artifacts.py | `api_scan_artifacts()` | 292–357 |

Both:
1. Get scan_ids for the scope
2. Query ScanResult.table_name + sys_id
3. Group into `targets: Dict[str, set]`
4. Build `classes` list
5. Loop targets → `_query_artifact_table()` per class
6. Combine, sort, paginate
7. Return `{"artifacts": [], "total": N, "classes": []}`

**Differences:** How scan_ids are obtained (from assessment.scans vs direct scan_id).

**Impact:** ~60 lines × 2 = **120 lines** duplicated Python.

---

### 3.15 — Backend: `_get_class_label()` — TWO copies in Python

| Location | Lines |
|----------|-------|
| `src/services/artifact_detail_puller.py` | 42–57 |
| `src/web/routes/artifacts.py` | 47–57 |

Identical logic: check APP_FILE_CLASS_CATALOG first, fall back to humanizing the table name.

**Impact:** ~15 lines × 2 = **30 lines** duplicated Python.

---

### 3.16 — Monkey-Patching Tab Functions for Lazy Loading — THREE instances

**What:** To trigger lazy-load on first tab open, each template wraps the tab function:

```javascript
const _orig = window.openTab;
window.openTab = function(evt, tabName) {
    _orig(evt, tabName);
    if (tabName === 'target' && !_loaded) { _loaded = true; refresh(); }
};
```

| Location | Lines |
|----------|-------|
| assessment_detail.html | 1154–1162 |
| scan_detail.html | 345–353 |
| result_detail.html | 613–617 |

**Issue:** Fragile monkey-patching pattern. Should use an event/callback system.

---

## 4. Existing Reusable Components NOT Being Used

| Component | Location | What It Does | Could Replace |
|-----------|----------|-------------|--------------|
| `formatDate()` | app.js:160–185 | Timezone-aware date formatting | All 3 local date formatters |
| `apiCall()` | app.js:119–133 | Generic fetch wrapper with JSON | All raw fetch() calls |
| `DataTable.js` | static/js/DataTable.js | Full schema-driven table with sort, pagination, column picker | Results tables (overkill but demonstrates the pattern) |
| Jinja `{% include %}` | templates/components/ | 4 existing includes: record_preview_modal, admin_token_field, status_badge, form_group_input | Filter cards, loading overlays |

---

## 5. Duplication Summary

| ID | Category | Type | JS Lines | HTML Lines | Python Lines |
|----|----------|------|----------|------------|-------------|
| P1 | Results row rendering + loading | Pre-existing | 70 | — | — |
| P2 | Results refresh pipeline | Pre-existing | 92 | — | — |
| P3 | Class options loader | Pre-existing | 56 | — | — |
| P4 | Classification toggle | Pre-existing | 12 | — | — |
| P5 | Date formatting | Pre-existing | 10 | — | — |
| P6 | Tab switching | Pre-existing | 45 | — | — |
| P7 | Results filter card HTML | Pre-existing | — | 76 | — |
| P8 | Reset handler | Pre-existing | 20 | — | — |
| N1 | Artifact row rendering | New | 50 | — | — |
| N2 | Artifact refresh pipeline | New | 80 | — | — |
| N3 | Artifact detail + code | New | 160 | — | — |
| N4 | Artifact filter card HTML | New | — | 80 | — |
| N5 | Backend artifact query | New | — | — | 120 |
| N6 | `_get_class_label()` | New | — | — | 30 |
| | **TOTALS** | | **595** | **156** | **150** |

**Grand total: ~900 lines of duplicated code**

---

## 6. Consolidation Targets

### Target A: `openTab()` in app.js
- **Eliminates:** P6 (45 lines across 3 templates)
- **Creates:** ~15 lines in app.js
- **Net savings:** 30 lines
- **Risk:** Low — pure additive, then delete old functions

### Target B: Use global `formatDate()` everywhere
- **Eliminates:** P5 (10 lines + inline date formatting)
- **Creates:** 0 lines (already exists)
- **Net savings:** 10 lines + timezone correctness
- **Risk:** Low — search and replace

### Target C: `ResultsFilterTable.js` — shared results rendering module
- **Eliminates:** P1 + P2 + P3 + P4 + P8 (250 lines JS) + P7 (76 lines HTML)
- **Creates:** ~120 lines in new JS file + ~30 lines Jinja macro
- **Net savings:** ~176 lines
- **Risk:** Medium — touches heavily-used assessment + scan pages

### Target D: `ArtifactList.js` — shared artifact list module
- **Eliminates:** N1 + N2 (130 lines JS) + N4 (80 lines HTML)
- **Creates:** ~80 lines in new JS file + ~25 lines Jinja macro
- **Net savings:** ~105 lines
- **Risk:** Low — new code, not heavily tested yet

### Target E: `ArtifactDetail.js` — shared artifact detail + code renderer
- **Eliminates:** N3 (160 lines JS)
- **Creates:** ~80 lines in new JS file
- **Net savings:** ~80 lines
- **Risk:** Low — only 2 pages use it

### Target F: Backend `_query_artifacts_for_scans()` helper
- **Eliminates:** N5 (120 lines Python)
- **Creates:** ~60 lines helper function
- **Net savings:** ~60 lines
- **Risk:** Low — extract then call

### Target G: Promote `_get_class_label()` to shared utility
- **Eliminates:** N6 (30 lines Python)
- **Creates:** ~15 lines in shared location
- **Net savings:** ~15 lines
- **Risk:** Low

---

## 7. Parallelizable Work Plan

### Dependency Graph

```
Target A (openTab)     ── no dependencies, standalone
Target B (formatDate)  ── no dependencies, standalone
Target G (class label) ── no dependencies, standalone
Target F (backend)     ── no dependencies, standalone
Target D (ArtifactList.js) ── depends on A (tab callback), B (formatDate)
Target E (ArtifactDetail.js) ── depends on B (formatDate)
Target C (ResultsFilterTable.js) ── depends on A (tab callback), B (formatDate)
```

### Execution Groups

---

#### GROUP 1 — Quick Wins (can all run in parallel)

These have zero dependencies on each other and zero risk. Do all 4 simultaneously.

##### 1A — `openTab()` → app.js (Claude Code)

**What:** Extract a single global `openTab()` into `app.js`, remove all 3 template-local copies, update HTML `onclick` attributes.

**Files to modify:**
- `src/web/static/js/app.js` — add function at bottom
- `src/web/templates/assessment_detail.html` — delete lines 565–581, update monkey-patch at 1154–1162
- `src/web/templates/scan_detail.html` — delete lines 309–315, update monkey-patch at 345–353
- `src/web/templates/result_detail.html` — delete lines 483–501, update monkey-patch at 613–617

**Implementation:**

Add to `app.js`:
```javascript
/**
 * Generic tab switcher. Removes 'active' from all .tab-content and .tab-btn
 * within the closest .tab-container, then activates the target.
 * Optional onActivate callback for lazy-loading.
 */
window.openTab = function openTab(evt, tabName) {
    var container = evt && evt.currentTarget
        ? evt.currentTarget.closest('.tab-container')
        : document;
    if (!container) container = document;
    container.querySelectorAll('.tab-content').forEach(function (el) {
        el.classList.remove('active');
    });
    container.querySelectorAll('.tab-btn').forEach(function (el) {
        el.classList.remove('active');
    });
    var target = document.getElementById(tabName);
    if (target) target.classList.add('active');
    if (evt && evt.currentTarget) evt.currentTarget.classList.add('active');

    // Fire custom event for lazy-load listeners
    document.dispatchEvent(new CustomEvent('tab:activated', { detail: { tabName: tabName } }));
};
```

**Key decision:** Scoping via `.closest('.tab-container')` means tabs only affect their own container — this fixes the bug where scan_detail's `openScanTab` would accidentally deactivate assessment_detail's tabs if both were somehow on the same page.

In templates, replace monkey-patching with event listeners:
```javascript
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'artifacts' && !_artifactsLoaded) {
        _artifactsLoaded = true;
        refreshArtifacts();
    }
});
```

**Verification:** Click every tab on assessment, scan, and result pages. Confirm correct tab shows, lazy-load fires once.

---

##### 1B — Use global `formatDate()` (Claude Code)

**What:** Delete `formatAssessmentDate()` from assessment_detail.html and `formatScanDate()` from scan_detail.html. Replace all calls and inline date formatting with `formatDate()` from app.js.

**Files to modify:**
- `src/web/templates/assessment_detail.html` — delete lines 587–590, replace `formatAssessmentDate(` with `formatDate(` globally. Also replace inline `.replace('T', ' ').slice(0, 16)` patterns in artifact rows.
- `src/web/templates/scan_detail.html` — delete lines 173–176, replace `formatScanDate(` with `formatDate(` globally. Same for artifact row inline formatting.
- `src/web/templates/artifact_record.html` — replace inline date formatting with `formatDate()`.

**Gotcha:** `formatDate()` in app.js returns a locale-formatted string (e.g., "02/15/2026, 14:30") not "2026-02-15 14:30". If the existing slim format is preferred, either:
- Accept the richer format (recommended — it's better), OR
- Add a `formatDateSlim()` variant to app.js

**Verification:** Check dates render correctly on all 4 pages.

---

##### 1C — Backend: Promote `_get_class_label()` to shared utility (Codex)

**What:** The same `_get_class_label(sys_class_name)` function exists in two files. Move it to a shared location and import from both.

**Files to modify:**
- `src/artifact_detail_defs.py` — add `get_class_label()` as a public function here (it already imports APP_FILE_CLASS_CATALOG)
- `src/services/artifact_detail_puller.py` — delete `_get_class_label()` (lines 42–57), import from `artifact_detail_defs`
- `src/web/routes/artifacts.py` — delete `_get_class_label()` (lines 47–57), import from `artifact_detail_defs`

**Architectural direction:**

The function belongs in `artifact_detail_defs.py` because:
1. It uses `ARTIFACT_DETAIL_DEFS` (already defined there) as fallback
2. It uses `APP_FILE_CLASS_CATALOG` (lazy import to avoid circular dep)
3. Both consumers already import from `artifact_detail_defs`

Add as a public function (not prefixed with `_`):
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

**Dependencies:** None. Purely a Python import refactor.

**Verification:** `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass.

---

##### 1D — Backend: Extract `_query_artifacts_for_scans()` helper (Codex)

**What:** Both `api_assessment_artifacts()` and `api_scan_artifacts()` in `artifacts.py` share ~60 lines of identical logic (lines 228–284 and 308–357). Extract the shared logic into a helper.

**File to modify:**
- `src/web/routes/artifacts.py`

**Architectural direction:**

Create this helper ABOVE the two endpoints:
```python
def _query_artifacts_for_scans(
    session: Session,
    scan_ids: List[int],
    instance_id: int,
    sys_class_name: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> Dict[str, Any]:
    """Shared artifact list query for assessment and scan endpoints.

    Given a list of scan_ids:
    1. Collects distinct (table_name, sys_id) from scan_result
    2. Groups by class (only those in ARTIFACT_DETAIL_DEFS)
    3. Queries each asmt_* table for matching records
    4. Returns combined, sorted, paginated result with class counts
    """
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
        {"sys_class_name": cn, "label": _get_class_label(cn), "count": len(sids)}
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
            row["class_label"] = _get_class_label(class_name)
        artifacts.extend(rows)
        total += count

    artifacts.sort(key=lambda r: (r.get("name") or "").lower())
    paginated = artifacts[offset : offset + limit]

    return {"artifacts": paginated, "total": total, "classes": classes}
```

Then simplify both endpoints to:
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
    scan_ids = [s.id for s in session.exec(select(Scan.id).where(Scan.assessment_id == assessment_id)).all()]
    return _query_artifacts_for_scans(session, scan_ids, assessment.instance_id, sys_class_name, limit, offset)


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

**Dependencies:** If 1C is done first, use `get_class_label` import instead of `_get_class_label`. If not, use the existing local `_get_class_label`.

**Verification:** `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass. Then manually test both endpoints:
- `GET /api/assessments/1/artifacts`
- `GET /api/scans/1/artifacts`

---

#### GROUP 2 — JS Modules (can run in parallel with each other, after Group 1)

These depend on Group 1 (openTab in app.js, formatDate available).

##### 2A — `ArtifactList.js` (Codex)

**What:** Extract the duplicated artifact list rendering + filtering + loading from assessment_detail.html and scan_detail.html into a reusable JS module.

**Files to create:**
- `src/web/static/js/ArtifactList.js`

**Files to modify:**
- `src/web/templates/assessment_detail.html` — replace lines 1068–1162 with ArtifactList init
- `src/web/templates/scan_detail.html` — replace lines 258–353 with ArtifactList init
- `src/web/templates/base.html` — add `<script src="/static/js/ArtifactList.js">` before `{% block scripts %}`

**Architectural direction:**

Pattern to follow: similar to `DataTable.js` (already in the codebase at `static/js/DataTable.js`). Use a constructor function, not ES6 class (for consistency with DataTable.js which uses function prototype pattern for IE compat).

```javascript
/**
 * ArtifactList — Reusable artifact list with class filter.
 *
 * Usage:
 *   var al = new ArtifactList({
 *       apiUrl: '/api/assessments/5/artifacts',
 *       instanceId: 2,
 *       bodyId: 'artifactBody',
 *       emptyId: 'artifactEmpty',
 *       loadingId: 'artifactLoading',
 *       metaId: 'artifactMeta',
 *       filterId: 'artifactClassFilter',
 *       badgeId: 'artifactsTabBadge',
 *   });
 *   al.refresh();  // or wire to tab:activated event for lazy load
 */
window.ArtifactList = (function () {
    'use strict';

    function ArtifactList(opts) {
        this.apiUrl = opts.apiUrl;
        this.instanceId = opts.instanceId;
        this.bodyId = opts.bodyId;
        this.emptyId = opts.emptyId;
        this.loadingId = opts.loadingId;
        this.metaId = opts.metaId;
        this.filterId = opts.filterId;
        this.badgeId = opts.badgeId || null;
        this._loaded = false;
    }

    ArtifactList.prototype.setLoading = function (isLoading) {
        var overlay = document.getElementById(this.loadingId);
        if (overlay) overlay.style.display = isLoading ? 'flex' : 'none';
    };

    ArtifactList.prototype.renderRows = function (rows) {
        var tbody = document.getElementById(this.bodyId);
        var empty = document.getElementById(this.emptyId);
        if (!tbody || !empty) return;

        if (!rows.length) {
            tbody.innerHTML = '';
            empty.classList.remove('is-hidden');
            return;
        }

        empty.classList.add('is-hidden');
        var instanceId = this.instanceId;
        tbody.innerHTML = rows.map(function (row) {
            var updated = typeof formatDate === 'function' ? formatDate(row.sys_updated_on) : (row.sys_updated_on || '-');
            var active = row.active === true || row.active === 'true' ? 'Yes'
                       : row.active === false || row.active === 'false' ? 'No' : '-';
            return '<tr>'
                + '<td><a href="/artifacts/' + row.sys_class_name + '/' + row.sys_id + '?instance_id=' + instanceId + '">' + (row.name || row.sys_id) + '</a></td>'
                + '<td>' + (row.class_label || row.sys_class_name || '-') + '</td>'
                + '<td>' + active + '</td>'
                + '<td>' + (row.sys_scope || '-') + '</td>'
                + '<td>' + updated + '</td>'
                + '<td><a class="btn btn-sm" href="/artifacts/' + row.sys_class_name + '/' + row.sys_id + '?instance_id=' + instanceId + '">View</a></td>'
                + '</tr>';
        }).join('');
    };

    ArtifactList.prototype.refresh = function () {
        var self = this;
        var meta = document.getElementById(this.metaId);
        var classFilter = document.getElementById(this.filterId);
        if (!classFilter) return;

        this.setLoading(true);
        if (meta) meta.textContent = 'Loading...';

        var params = new URLSearchParams({ limit: '500' });
        if (classFilter.value) params.set('sys_class_name', classFilter.value);

        fetch(this.apiUrl + '?' + params.toString(), { cache: 'no-store' })
            .then(function (r) { if (!r.ok) throw new Error('fail'); return r.json(); })
            .then(function (payload) {
                // Populate class filter
                var classes = payload.classes || [];
                var currentVal = classFilter.value;
                classFilter.innerHTML = '<option value="">All Classes</option>';
                classes.forEach(function (cls) {
                    var opt = document.createElement('option');
                    opt.value = cls.sys_class_name;
                    opt.textContent = cls.label + ' (' + cls.count + ')';
                    classFilter.appendChild(opt);
                });
                if (currentVal) classFilter.value = currentVal;

                self.renderRows(payload.artifacts || []);

                if (self.badgeId) {
                    var badge = document.getElementById(self.badgeId);
                    if (badge) badge.textContent = String(payload.total || 0);
                }
                if (meta) meta.textContent = 'Showing ' + (payload.artifacts || []).length + ' of ' + (payload.total || 0) + ' artifacts';
            })
            .catch(function () {
                self.renderRows([]);
                if (meta) meta.textContent = 'Failed to load artifacts.';
            })
            .finally(function () {
                self.setLoading(false);
            });
    };

    ArtifactList.prototype.bindControls = function (applyId, resetId) {
        var self = this;
        var filter = document.getElementById(this.filterId);
        var apply = document.getElementById(applyId);
        var reset = document.getElementById(resetId);

        if (apply) apply.addEventListener('click', function () { self.refresh(); });
        if (filter) filter.addEventListener('change', function () { self.refresh(); });
        if (reset) reset.addEventListener('click', function () {
            if (filter) filter.value = '';
            self.refresh();
        });
    };

    return ArtifactList;
})();
```

**Usage in assessment_detail.html** (replaces ~95 lines):
```javascript
var artifactList = new ArtifactList({
    apiUrl: '/api/assessments/' + assessmentId + '/artifacts',
    instanceId: assessmentInstanceId,
    bodyId: 'artifactBody', emptyId: 'artifactEmpty',
    loadingId: 'artifactLoading', metaId: 'artifactMeta',
    filterId: 'artifactClassFilter', badgeId: 'artifactsTabBadge',
});
artifactList.bindControls('artifactApply', 'artifactReset');
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'artifacts') artifactList.refresh();
});
```

**Usage in scan_detail.html** (replaces ~95 lines):
```javascript
var scanArtifactList = new ArtifactList({
    apiUrl: '/api/scans/' + scanId + '/artifacts',
    instanceId: scanInstanceId,
    bodyId: 'scanArtifactBody', emptyId: 'scanArtifactEmpty',
    loadingId: 'scanArtifactLoading', metaId: 'scanArtifactMeta',
    filterId: 'scanArtifactClassFilter', badgeId: 'scanArtifactsTabBadge',
});
scanArtifactList.bindControls('scanArtifactApply', 'scanArtifactReset');
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'scan-artifacts') scanArtifactList.refresh();
});
```

**Dependencies:** Group 1A (openTab with `tab:activated` event) and 1B (formatDate).

**Verification:** Click Artifacts tab on both assessment and scan pages. Verify: loading spinner, data renders, class filter works, badge updates, apply/reset work.

---

##### 2B — `ArtifactDetail.js` (Codex)

**What:** Extract the duplicated artifact detail (field-value table) + code content (pre blocks) rendering from result_detail.html and artifact_record.html.

**Files to create:**
- `src/web/static/js/ArtifactDetail.js`

**Files to modify:**
- `src/web/templates/result_detail.html` — replace lines 519–610 with ArtifactDetail calls
- `src/web/templates/artifact_record.html` — replace lines 69–140 with ArtifactDetail calls
- `src/web/templates/base.html` — add script tag

**Architectural direction:**

Two standalone functions (not a class — these are simple one-shot loaders):

```javascript
window.ArtifactDetail = (function () {
    'use strict';

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    /**
     * Render code content blocks into a container.
     * @param {Object} opts
     * @param {string} opts.sysClassName - SN table name
     * @param {string} opts.sysId - Record sys_id
     * @param {number} opts.instanceId - Instance ID
     * @param {string} opts.cardId - Card element ID (shown when code exists)
     * @param {string} opts.containerId - Container for code blocks
     * @param {string} [opts.loadingId] - Loading indicator element ID
     */
    function loadCode(opts) {
        if (!opts.sysClassName || !opts.sysId || !opts.instanceId) return;

        var card = document.getElementById(opts.cardId);
        var loading = opts.loadingId ? document.getElementById(opts.loadingId) : null;
        var container = document.getElementById(opts.containerId);
        if (!card || !container) return;

        var url = '/api/artifacts/' + encodeURIComponent(opts.sysClassName)
                + '/' + encodeURIComponent(opts.sysId)
                + '/code?instance_id=' + opts.instanceId;

        fetch(url, { cache: 'no-store' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (loading) loading.style.display = 'none';
                if (!data || !data.has_code || !data.code_contents || !data.code_contents.length) return;

                card.classList.remove('is-hidden');
                container.innerHTML = data.code_contents.map(function (item) {
                    return '<div class="mt-075">'
                        + '<div class="info-label">' + escapeHtml(item.label) + ' <code>(' + escapeHtml(item.field) + ')</code></div>'
                        + '<pre class="code-block max-h-420">' + escapeHtml(item.content) + '</pre>'
                        + '</div>';
                }).join('');
            })
            .catch(function () {
                if (loading) loading.style.display = 'none';
            });
    }

    /**
     * Load full artifact detail (field-value table + optional code + raw JSON).
     * @param {Object} opts
     * @param {string} opts.sysClassName
     * @param {string} opts.sysId
     * @param {number} opts.instanceId
     * @param {string} [opts.tableId] - Field-value table element
     * @param {string} [opts.bodyId] - Table tbody element
     * @param {string} [opts.emptyId] - Empty state element
     * @param {string} [opts.loadingId] - Loading indicator
     * @param {string} [opts.codeCardId] - Code card (shown if code exists)
     * @param {string} [opts.codeContainerId] - Code container
     * @param {string} [opts.rawJsonCardId] - Raw JSON card
     * @param {string} [opts.rawJsonContentId] - Raw JSON pre element
     * @param {string} [opts.nameId] - Element to update with record name
     */
    function loadDetail(opts) {
        if (!opts.sysClassName || !opts.sysId || !opts.instanceId) return;

        var loading = opts.loadingId ? document.getElementById(opts.loadingId) : null;
        var table = opts.tableId ? document.getElementById(opts.tableId) : null;
        var tbody = opts.bodyId ? document.getElementById(opts.bodyId) : null;
        var empty = opts.emptyId ? document.getElementById(opts.emptyId) : null;
        if (!tbody) return;

        if (loading) { loading.classList.remove('is-hidden'); loading.style.display = ''; }

        var url = '/api/artifacts/' + encodeURIComponent(opts.sysClassName)
                + '/' + encodeURIComponent(opts.sysId)
                + '?instance_id=' + opts.instanceId;

        fetch(url, { cache: 'no-store' })
            .then(function (r) {
                if (loading) loading.classList.add('is-hidden');
                if (!r.ok) throw new Error('not found');
                return r.json();
            })
            .then(function (data) {
                var fieldRows = data.field_rows || [];

                // Update name element if provided
                if (opts.nameId) {
                    var nameRow = fieldRows.find(function (r) { return r.field === 'name'; });
                    if (nameRow && nameRow.value) {
                        var nameEl = document.getElementById(opts.nameId);
                        if (nameEl) nameEl.textContent = nameRow.value;
                    }
                }

                if (!fieldRows.length) {
                    if (empty) empty.classList.remove('is-hidden');
                    return;
                }

                if (table) table.classList.remove('is-hidden');
                tbody.innerHTML = fieldRows.map(function (row) {
                    var val = row.value != null ? String(row.value) : '-';
                    var escaped = escapeHtml(val);
                    var isLong = val.length > 200;
                    return '<tr>'
                        + '<td><strong>' + escapeHtml(row.label) + '</strong><br><code class="text-muted-sm">' + escapeHtml(row.field) + '</code></td>'
                        + '<td>' + (isLong ? '<pre class="code-block max-h-200">' + escaped + '</pre>' : escaped) + '</td>'
                        + '</tr>';
                }).join('');

                // Code contents
                if (opts.codeCardId && opts.codeContainerId) {
                    var codeContents = data.code_contents || [];
                    if (codeContents.length) {
                        var codeCard = document.getElementById(opts.codeCardId);
                        var codeContainer = document.getElementById(opts.codeContainerId);
                        if (codeCard && codeContainer) {
                            codeCard.classList.remove('is-hidden');
                            codeContainer.innerHTML = codeContents.map(function (item) {
                                return '<div class="mt-075">'
                                    + '<div class="info-label">' + escapeHtml(item.label) + ' <code>(' + escapeHtml(item.field) + ')</code></div>'
                                    + '<pre class="code-block max-h-420">' + escapeHtml(item.content) + '</pre>'
                                    + '</div>';
                            }).join('');
                        }
                    }
                }

                // Raw JSON
                if (opts.rawJsonCardId && opts.rawJsonContentId && data.raw_json) {
                    var rawCard = document.getElementById(opts.rawJsonCardId);
                    var rawContent = document.getElementById(opts.rawJsonContentId);
                    if (rawCard && rawContent) {
                        rawCard.classList.remove('is-hidden');
                        try { rawContent.textContent = JSON.stringify(JSON.parse(data.raw_json), null, 2); }
                        catch (e) { rawContent.textContent = data.raw_json; }
                    }
                }
            })
            .catch(function () {
                if (loading) loading.classList.add('is-hidden');
                if (empty) empty.classList.remove('is-hidden');
            });
    }

    return { loadCode: loadCode, loadDetail: loadDetail, escapeHtml: escapeHtml };
})();
```

**Usage in result_detail.html** (replaces ~100 lines):
```javascript
// Code content on main tab — auto-loads on page load
ArtifactDetail.loadCode({
    sysClassName: resultTableName,
    sysId: resultSysId,
    instanceId: resultInstanceId,
    cardId: 'codeContentCard',
    containerId: 'codeContentContainer',
    loadingId: 'codeContentLoading',
});

// Artifact detail in Configuration Artifact tab — lazy-loaded
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'artifact') {
        ArtifactDetail.loadDetail({
            sysClassName: resultTableName,
            sysId: resultSysId,
            instanceId: resultInstanceId,
            tableId: 'artifactDetailTable',
            bodyId: 'artifactDetailBody',
            emptyId: 'artifactDetailEmpty',
            loadingId: 'artifactDetailLoading',
        });
    }
});
```

**Usage in artifact_record.html** (replaces ~80 lines):
```javascript
ArtifactDetail.loadDetail({
    sysClassName: artifactClass,
    sysId: artifactSysId,
    instanceId: artifactInstanceId,
    tableId: 'artifactFieldTable',
    bodyId: 'artifactFieldBody',
    emptyId: 'artifactEmpty',
    loadingId: 'artifactLoading',
    nameId: 'artifactName',
    codeCardId: 'codeCard',
    codeContainerId: 'codeContainer',
    rawJsonCardId: 'rawJsonCard',
    rawJsonContentId: 'rawJsonContent',
});
```

**Dependencies:** Group 1A (tab:activated event). formatDate not directly needed (these render field values, not date columns).

**Verification:**
- Open a result page → Code Content card should show if the artifact has code fields
- Click Configuration Artifact tab → Field-value table loads
- Open standalone artifact record page → All sections render

---

##### 2C — `ResultsFilterTable.js` (Claude Code — more complex, needs careful testing)

**What:** Extract the duplicated scan results rendering + filtering pipeline from assessment_detail.html and scan_detail.html.

**This is the largest consolidation.** It covers P1, P2, P3, P4, P7, P8.

**Scope:** ~250 lines eliminated from 2 templates, ~120 lines new module.

**Files to create:**
- `src/web/static/js/ResultsFilterTable.js`

**Files to modify:**
- `src/web/templates/assessment_detail.html` — replace lines 592–884 + 951–987 with ResultsFilterTable init
- `src/web/templates/scan_detail.html` — replace lines 173–243 with ResultsFilterTable init
- `src/web/templates/base.html` — add script tag

**NOTE:** This is the riskiest change because assessment_detail.html has additional logic (scopedCount, totals row, periodic refresh during scans) that scan_detail.html does not. The module needs to support optional features:
- `showTotals: true` → renders the totals meta line (assessment only)
- `optionsApiParams` → extra params for the class options endpoint
- `periodicRefresh` → external code can call `instance.refresh()` from polling loop

**Dependencies:** Group 1A + 1B.

**This item should be done by Claude Code** because it requires careful handling of the assessment-specific polling integration (refreshScanStatus calls refreshAssessmentResults periodically).

**Verification:** Full manual test of both results tabs with all filter combinations.

---

#### GROUP 3 — HTML Component Extraction (after Group 2)

##### 3A — Jinja macros for filter cards (Claude Code)

After JS modules are in place, extract the remaining HTML duplication:
- `components/results_filter_card.html` — macro with `prefix` parameter
- `components/artifact_filter_card.html` — macro with `prefix` parameter

**Lower priority** — the JS modules eliminate the behavioral duplication; the HTML is just structural boilerplate. Can be done as cleanup.

---

## 8. Assignment Summary

| Group | Item | Assignee | Depends On | Est. Lines Saved |
|-------|------|----------|-----------|-----------------|
| 1 | 1A: openTab → app.js | Claude Code | — | 45 |
| 1 | 1B: Use global formatDate | Claude Code | — | 10 |
| 1 | 1C: Promote _get_class_label | Codex | — | 30 |
| 1 | 1D: Extract _query_artifacts_for_scans | Codex | — | 60 |
| 2 | 2A: ArtifactList.js | Codex | 1A, 1B | 130 |
| 2 | 2B: ArtifactDetail.js | Codex | 1A | 160 |
| 2 | 2C: ResultsFilterTable.js | Claude Code | 1A, 1B | 250 |
| 3 | 3A: Jinja filter card macros | Claude Code | 2A, 2C | 80 |
| | **TOTAL** | | | **~765** |

### Parallel Execution Map

```
TIME →

Group 1 (all parallel):
  Claude Code: 1A (openTab) + 1B (formatDate)
  Codex:       1C (_get_class_label) + 1D (_query_artifacts_for_scans)

  ↓ merge

Group 2 (parallel after Group 1):
  Codex:       2A (ArtifactList.js) + 2B (ArtifactDetail.js)
  Claude Code: 2C (ResultsFilterTable.js)

  ↓ merge

Group 3:
  Claude Code: 3A (Jinja macros)
```

---

## 9. Test Plan

After each group:
1. `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass
2. Start the app, navigate to:
   - Assessment detail → Scans tab, Results tab (with filters), Features tab, Artifacts tab
   - Scan detail → Results tab (with filters), Artifacts tab
   - Result detail → Code Content card, Version History / Update Set / Artifact tabs
   - Artifact record page → Field table, code blocks, raw JSON
3. Run a scan workflow → verify polling updates Preflight + Postflight status correctly
4. Verify date formatting uses timezone preference across all pages

---

## 10. Files Reference (complete paths)

```
src/web/templates/assessment_detail.html
src/web/templates/scan_detail.html
src/web/templates/result_detail.html
src/web/templates/artifact_record.html
src/web/templates/base.html
src/web/templates/components/  (existing includes directory)
src/web/static/js/app.js
src/web/static/js/DataTable.js  (reference pattern for new modules)
src/web/static/js/ArtifactList.js   (to create)
src/web/static/js/ArtifactDetail.js (to create)
src/web/static/js/ResultsFilterTable.js (to create)
src/web/routes/artifacts.py
src/services/artifact_detail_puller.py
src/artifact_detail_defs.py
src/server.py
```
