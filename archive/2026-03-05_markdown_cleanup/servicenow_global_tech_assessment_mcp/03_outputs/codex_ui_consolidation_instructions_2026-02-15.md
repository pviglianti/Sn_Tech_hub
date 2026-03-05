# Codex UI Consolidation Instructions

> Date: 2026-02-15
> Context: Part of the merged UI consolidation plan (`03_outputs/plan_ui_consolidation_2026-02-15.md`)

## Overview

You have **4 tasks** across 2 waves. Wave 1 tasks are independent of each other and independent of Claude's work — start them immediately. Wave 2 tasks depend on Claude completing Group 1A (openTab) and 1B (formatDate) first.

**Codebase root:** `/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub/`

**Test command:** `./venv/bin/python -m pytest tests/ -q` (expect 87 passing)

**IMPORTANT:** Run tests after EACH task. Do not batch changes.

## Execution Update (2026-02-15 by Codex)

Completed:
- `Task 1C` DONE
- `Task 1D` DONE
- `Task 2A` DONE
- `Task 2B` DONE

Validation:
- `./venv/bin/python -m pytest tests/ -q` -> `98 passed, 8 warnings`

Notes:
- `Task 2C` was completed by Claude and is already merged (`ResultsFilterTable.js`).
- `assessment_detail.html` and `scan_detail.html` now use both `ResultsFilterTable` and `ArtifactList`.
- `result_detail.html` and `artifact_record.html` now use `ArtifactDetail`.

---

## Wave 1 — Start Immediately (no dependencies)

These two tasks are pure Python backend refactors. They touch no frontend code and have zero conflict with anything Claude is doing simultaneously.

### Task 1C: Promote `_get_class_label()` to shared utility

**Goal:** The function `_get_class_label(sys_class_name)` is duplicated byte-for-byte in two files. Move it to `artifact_detail_defs.py` as a public function and import from both consumers.

**Files to modify:**

1. **`src/artifact_detail_defs.py`** — Add the public function after the `COMMON_INHERITED_FIELDS` list (around line 33, before `ARTIFACT_DETAIL_DEFS`).

2. **`src/services/artifact_detail_puller.py`** — Delete lines 42–57 (the local `_get_class_label` function). Update the import at the top to include `get_class_label`:
   ```python
   from ..artifact_detail_defs import ARTIFACT_DETAIL_DEFS, get_class_label
   ```
   Then find-and-replace `_get_class_label(` → `get_class_label(` in this file.

3. **`src/web/routes/artifacts.py`** — Delete lines 47–57 (the local `_get_class_label` function). Update the import at the top:
   ```python
   from ...artifact_detail_defs import (
       ARTIFACT_DETAIL_DEFS,
       COMMON_INHERITED_FIELDS,
       get_class_label,
       get_detail_def,
   )
   ```
   Then find-and-replace `_get_class_label(` → `get_class_label(` in this file.

**Implementation — add to `src/artifact_detail_defs.py`:**

```python
def get_class_label(sys_class_name: str) -> str:
    """User-friendly label for an artifact class.

    Checks APP_FILE_CLASS_CATALOG first, falls back to humanizing the table name.
    """
    # Import here to avoid circular dependency at module load time
    from .app_file_class_catalog import APP_FILE_CLASS_CATALOG

    for entry in APP_FILE_CLASS_CATALOG:
        if entry["sys_class_name"] == sys_class_name:
            return entry["label"]
    defn = ARTIFACT_DETAIL_DEFS.get(sys_class_name)
    if defn:
        return defn["local_table"].replace("asmt_", "").replace("_", " ").title()
    return sys_class_name
```

**Where to insert:** After `COMMON_INHERITED_FIELDS` definition (line ~33), before the `ARTIFACT_DETAIL_DEFS` dict (line ~40). Add a blank line before and after.

**Verification:**
1. `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass
2. `grep -rn "_get_class_label" src/` should return ZERO results (the private version should be completely gone)
3. `grep -rn "get_class_label" src/` should show imports in `artifact_detail_puller.py` and `artifacts.py`, plus the definition in `artifact_detail_defs.py`

**Commit:** `git commit -m "refactor: promote _get_class_label to shared utility in artifact_detail_defs"`

---

### Task 1D: Extract `_query_artifacts_for_scans()` helper

**Goal:** The two endpoints `api_assessment_artifacts()` (lines 207–284) and `api_scan_artifacts()` (lines 292–357) in `artifacts.py` share ~60 lines of identical query logic. Extract the shared part into a helper function.

**File to modify:** `src/web/routes/artifacts.py` (one file only)

**DEPENDENCY:** If you do 1C first (recommended), use `get_class_label` in the new helper. If you haven't done 1C yet, use the existing local `_get_class_label`.

**Implementation:**

1. Add this helper function ABOVE line 207 (before `api_assessment_artifacts`), after the existing `_query_artifact_table` function:

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
        ScanResult.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
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

2. Replace `api_assessment_artifacts` (lines 207–284) with:

```python
@artifacts_router.get("/api/assessments/{assessment_id}/artifacts")
async def api_assessment_artifacts(
    assessment_id: int,
    sys_class_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """Return artifacts for all scan results in an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    scans = session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all()
    return _query_artifacts_for_scans(
        session, list(scans), assessment.instance_id, sys_class_name, limit, offset
    )
```

3. Replace `api_scan_artifacts` (lines 292–357) with:

```python
@artifacts_router.get("/api/scans/{scan_id}/artifacts")
async def api_scan_artifacts(
    scan_id: int,
    sys_class_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """Return artifacts for a single scan's results."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    assessment = session.get(Assessment, scan.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return _query_artifacts_for_scans(
        session, [scan_id], assessment.instance_id, sys_class_name, limit, offset
    )
```

**Verification:**
1. `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass
2. Manually test (if app running): `GET /api/assessments/1/artifacts` and `GET /api/scans/1/artifacts` return same shape as before

**Commit:** `git commit -m "refactor: extract _query_artifacts_for_scans shared helper in artifacts.py"`

---

## Wave 2 — After Claude Completes Group 1A + 1B

**WAIT:** Do not start these until Claude confirms Group 1A (openTab in app.js) and 1B (formatDate replacement) are merged and tests pass. These tasks depend on:
- `window.openTab()` existing in `app.js` with `tab:activated` custom event dispatch
- `formatDate()` being the sole date formatting function (no more `formatAssessmentDate`/`formatScanDate`)

### Task 2A: Create `ArtifactList.js`

**Goal:** Extract the duplicated artifact list rendering + filtering + loading from `assessment_detail.html` and `scan_detail.html` into a reusable JS module.

**Files to create:**
- `src/web/static/js/ArtifactList.js`

**Files to modify:**
- `src/web/templates/base.html` — add `<script src="/static/js/ArtifactList.js"></script>` BEFORE the `{% block scripts %}` tag (so it loads before page scripts)
- `src/web/templates/assessment_detail.html` — replace artifact rendering/refresh/filter code with ArtifactList init
- `src/web/templates/scan_detail.html` — replace artifact rendering/refresh/filter code with ArtifactList init

**Complete implementation for `ArtifactList.js`:**

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
 *   al.refresh();
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

**Template changes — assessment_detail.html:**

Find and DELETE these sections (artifact-specific JS):
- `setArtifactLoading` function
- `renderArtifactRows` function
- `refreshArtifacts` function
- The 3 event listeners for `artifactApply`, `artifactClassFilter`, `artifactReset`

Replace with (add BEFORE the lazy-load event listener):
```javascript
var artifactList = new ArtifactList({
    apiUrl: '/api/assessments/' + assessmentId + '/artifacts',
    instanceId: assessmentInstanceId,
    bodyId: 'artifactBody', emptyId: 'artifactEmpty',
    loadingId: 'artifactLoading', metaId: 'artifactMeta',
    filterId: 'artifactClassFilter', badgeId: 'artifactsTabBadge',
});
artifactList.bindControls('artifactApply', 'artifactReset');
```

Update the `tab:activated` listener (which Claude already created in 1A) to use `artifactList.refresh()`:
```javascript
// In the tab:activated listener, change:
//   refreshArtifacts();
// to:
//   artifactList.refresh();
```

**Template changes — scan_detail.html:**

Find and DELETE these sections:
- `setScanArtifactLoading` function (lines 393–396)
- `renderScanArtifactRows` function (lines 398–423)
- `refreshScanArtifacts` function (lines 425–465)
- The 3 event listeners for `scanArtifactApply`, `scanArtifactClassFilter`, `scanArtifactReset` (lines 467–473)

Replace with:
```javascript
var scanArtifactList = new ArtifactList({
    apiUrl: '/api/scans/' + scanId + '/artifacts',
    instanceId: scanInstanceId,
    bodyId: 'scanArtifactBody', emptyId: 'scanArtifactEmpty',
    loadingId: 'scanArtifactLoading', metaId: 'scanArtifactMeta',
    filterId: 'scanArtifactClassFilter', badgeId: 'scanArtifactsTabBadge',
});
scanArtifactList.bindControls('scanArtifactApply', 'scanArtifactReset');
```

Update the `tab:activated` listener to use `scanArtifactList.refresh()`.

**Verification:**
1. `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass
2. Start app, open assessment detail → click Artifacts tab → data loads, filter works, badge updates
3. Open scan detail → click Artifacts tab → same behavior
4. Confirm Apply/Reset buttons work, class filter dropdown populates from API response

**Commit:** `git commit -m "refactor: extract ArtifactList.js reusable component, replace duplicate code in assessment + scan templates"`

---

### Task 2B: Create `ArtifactDetail.js`

**Goal:** Extract duplicated artifact detail (field-value table) + code content (pre blocks) rendering from `result_detail.html` and `artifact_record.html`.

**Files to create:**
- `src/web/static/js/ArtifactDetail.js`

**Files to modify:**
- `src/web/templates/base.html` — add `<script src="/static/js/ArtifactDetail.js"></script>` (same location as ArtifactList.js)
- `src/web/templates/result_detail.html` — replace `loadCodeContent` + `loadArtifactDetail` with ArtifactDetail calls
- `src/web/templates/artifact_record.html` — replace `loadArtifactRecord` with ArtifactDetail call

**Complete implementation for `ArtifactDetail.js`:**

```javascript
/**
 * ArtifactDetail — Reusable artifact detail + code renderer.
 *
 * Two standalone functions:
 *   ArtifactDetail.loadCode(opts)   — loads code content blocks
 *   ArtifactDetail.loadDetail(opts) — loads full field-value table + code + raw JSON
 *   ArtifactDetail.escapeHtml(str)  — HTML entity escaping
 */
window.ArtifactDetail = (function () {
    'use strict';

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

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

**Template changes — result_detail.html:**

DELETE:
- `loadCodeContent` function (the one that fetches `/api/artifacts/.../code`)
- `loadArtifactDetail` function
- The monkey-patch at lines 648–652 (`_origResultTab`)
- The DOMContentLoaded listener for loadCodeContent

REPLACE WITH:
```javascript
// Code content on main tab — auto-loads on page load
document.addEventListener('DOMContentLoaded', function () {
    ArtifactDetail.loadCode({
        sysClassName: resultTableName,
        sysId: resultSysId,
        instanceId: resultInstanceId,
        cardId: 'codeContentCard',
        containerId: 'codeContentContainer',
        loadingId: 'codeContentLoading',
    });
});

// Artifact detail tab — lazy-loaded via tab:activated event (from Group 1A)
var _artifactDetailLoaded = false;
document.addEventListener('tab:activated', function(e) {
    if (e.detail.tabName === 'artifact' && !_artifactDetailLoaded) {
        _artifactDetailLoaded = true;
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

**IMPORTANT:** Check that variables `resultTableName`, `resultSysId`, `resultInstanceId` are still defined at the top of the script block. They should be — they're set from Jinja template variables. Do NOT remove those declarations.

**Template changes — artifact_record.html:**

DELETE the entire `loadArtifactRecord` function (lines 69–155) and the DOMContentLoaded listener (line 157).

REPLACE WITH:
```javascript
document.addEventListener('DOMContentLoaded', function () {
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
});
```

Keep the 3 `const` declarations at the top (`artifactClass`, `artifactSysId`, `artifactInstanceId`).

**Verification:**
1. `./venv/bin/python -m pytest tests/ -q` — all 87 tests pass
2. Open a result page → Code Content card should show if artifact has code fields
3. Click "Configuration Artifact" tab → Field-value table loads with correct data
4. Open standalone artifact record page (`/artifacts/{class}/{sys_id}?instance_id=X`) → all sections render: field table, code blocks, raw JSON

**Commit:** `git commit -m "refactor: extract ArtifactDetail.js reusable component, replace duplicate code in result + artifact templates"`

---

## Execution Order Summary

```
1C (Python, independent) ─── start immediately
1D (Python, independent) ─── start immediately, use get_class_label if 1C done first
   ↓
   WAIT for Claude to confirm Group 1A + 1B complete
   ↓
2A (ArtifactList.js) ─── can run parallel with 2B
2B (ArtifactDetail.js) ── can run parallel with 2A
```

## What NOT to Touch

- Do NOT modify `app.js` — Claude is working on that (Group 1A + 1B)
- Do NOT modify the `openTab`/`openScanTab`/`openResultTab` functions — Claude is replacing those
- Do NOT modify `formatAssessmentDate`/`formatScanDate` — Claude is removing those
- Do NOT modify `ResultsFilterTable` or results rendering code — Claude owns that (Group 2C)
- Do NOT modify CSS files
- Do NOT touch any files outside the listed scope

## Communication

After completing each task:
1. Run tests (`./venv/bin/python -m pytest tests/ -q`)
2. Commit with descriptive message
3. Report: which task, files changed, test results
