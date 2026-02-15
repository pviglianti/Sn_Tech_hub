# Customization Child Table + Tab Restructure

> Created: 2026-02-15 | Status: Approved
> Scope: New `customization` table, tab restructure on assessment/scan views, new MCP tool

---

## Problem

When AI reads scan results via MCP, it relies on a `customized_only=true` query parameter to filter out non-customized results. This introduces risk — wrong parameter = wrong data. Additionally, the UI shows total results count on tab badges rather than the more important customized count, and customized results aren't given first-class prominence.

## Solution

A physical child table (`customization`) that contains ONLY customized scan results. AI queries it directly with zero filtering conditions. The parent `scan_result` table remains unchanged as the source of truth for ALL results. A new "Customizations" tab becomes the primary tab on assessment and scan views.

---

## 1. Data Model

### New table: `customization`

| Column | Type | Notes |
|--------|------|-------|
| `id` | int PK | Auto-increment |
| `scan_result_id` | int FK → scan_result.id | **UNIQUE** — 1:1 with parent row |
| `scan_id` | int FK → scan.id | Denormalized for fast queries |
| `sys_id` | str | Copied from parent |
| `table_name` | str | Artifact class (sys_script_include, etc.) |
| `name` | str | Artifact name |
| `origin_type` | OriginType | `modified_ootb` or `net_new_customer` only |
| `head_owner` | HeadOwner | Copied |
| `sys_class_name` | str | Copied |
| `sys_scope` | str | Copied |
| `review_status` | ReviewStatus | Copied |
| `disposition` | Disposition | Copied |
| `recommendation` | str | Copied |
| `observations` | str | Copied |
| `sys_updated_on` | datetime | Copied |
| `created_at` | datetime | Row creation timestamp |

### Key constraints
- `scan_result_id` UNIQUE — one customization row per scan_result
- Indexes on `scan_id`, `table_name`, `origin_type`
- No `raw_data_json` — AI reads condensed fields, raw stays on parent only

### Relationship on ScanResult
```python
customization: Optional["Customization"] = Relationship(back_populates="scan_result")
```

### Customization values
- `modified_ootb` — OOTB record that has been customized
- `net_new_customer` — Customer-created from scratch

---

## 2. Sync Mechanism (Copy-on-classify)

### Path 1 — Scan executor (bulk insert)
After `scan_executor.py` classifies all results and bulk-inserts into `scan_result`, a follow-up step in the same transaction filters for customized results (`origin_type in {modified_ootb, net_new_customer}`) and bulk-inserts into `customization`.

### Path 2 — UI reclassification
When a user changes `origin_type` on result_detail disposition form:
- New origin_type is customized → UPSERT into `customization`
- New origin_type is NOT customized → DELETE from `customization` if row exists

### Path 2b — Disposition/review updates
When a user updates `disposition`, `review_status`, `recommendation`, or `observations` on a customized result, the save handler also updates the corresponding `customization` row.

No triggers, no background jobs. Python owns all sync logic.

---

## 3. Tab Restructure

### Assessment detail — 5 tabs (new order)
```
Scans | Customizations (NEW) | Features | Artifacts | Results (moved)
```
- Customizations badge: count of customized results
- Results badge: count of ALL results

### Scan detail — 3 tabs (new order)
```
Customizations (NEW, default active) | Artifacts | Results (moved)
```

---

## 4. Tab Filter Design

### Customizations tab
- **Customization Type** dropdown: `All` | `Modified OOTB` | `Net New Customer`
- **App File Class** dropdown: standard class filter
- Apply / Reset buttons
- No "Customized Only" checkbox (redundant)

### Results tab (updated)
- **Remove** "Customized Only" checkbox
- **Add** Classification dropdown: `All` (default) | `Customized` | `Uncustomized` | `Modified OOTB` | `Net New Customer` | `OOTB Untouched` | `Unknown`
- **App File Class** dropdown: same as today
- Apply / Reset buttons

---

## 5. Record View

Clicking a row in the Customizations tab navigates to `/results/{scan_result_id}` — the existing result_detail.html. No new form. The `customization.scan_result_id` FK provides the link.

---

## 6. MCP / AI Consumption

### New MCP tool: `get_customizations`
```
Input: assessment_id (required), table_name (optional), origin_type (optional), limit, offset
Query: SELECT * FROM customization WHERE scan_id IN (assessment's scan_ids)
```
No `customized_only` parameter — the table IS the filter.

### Existing `get_assessment_results`
Unchanged. Still queries `scan_result` with optional filters.

---

## 7. API Endpoints

### New endpoints
- `GET /api/assessments/{id}/customizations` — list customizations for an assessment
- `GET /api/scans/{id}/customizations` — list customizations for a scan
- `GET /api/customizations/options?assessment_id=X` — class filter options for customizations

### Modified endpoints
- `POST /api/results/{id}/disposition` — add sync to customization table on save
- `PUT /api/results/{id}` (if exists) — add sync to customization table

---

## 8. Files Affected

### New files
- `src/models.py` — add `Customization` model
- `src/web/routes/customizations.py` — new router for customization API endpoints
- `src/mcp/tools/core/customizations.py` — new MCP tool

### Modified files
- `src/services/scan_executor.py` — bulk insert into customization after classification
- `src/server.py` — register new router, update disposition save to sync customization
- `src/web/templates/assessment_detail.html` — add Customizations tab, reorder tabs, update Results filter
- `src/web/templates/scan_detail.html` — add Customizations tab, reorder tabs, update Results filter
- `src/web/templates/base.html` — include new JS if needed
