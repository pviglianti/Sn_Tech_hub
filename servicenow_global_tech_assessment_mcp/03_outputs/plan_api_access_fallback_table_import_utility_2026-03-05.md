# API-Access Fallback Table Import Utility Plan (2026-03-05)

## Objective
Provide a manual fallback ingest path for instance tables when API pulls are rejected/blocked (security policy, ACL restrictions, endpoint denial, or network controls).

Users should be able to export data from ServiceNow (or another approved source) and upload it into the app for a selected **instance + table** using CSV/XLS/XLSX/JSON/XML.

## User Experience (Target)
1. User clicks `Import File` icon/button from an instance+table context (dynamic browser table page, table index row action, or relationship-graph table context).
2. App opens `/imports/table-file` in a **new tab** with `instance_id` + `table_name` prefilled.
3. User uploads file and sees a staging preview:
- detected columns
- mapped columns (to `SnFieldMapping`)
- row count
- validation warnings/errors
4. User runs **Dry Run** first:
- shows `will_insert`, `will_update`, `ambiguous`, `rejected`
- highlights missing required fields
5. User confirms import only after dry run.
6. App performs batch upsert/insert and returns import summary + downloadable error report.

## Core Rules
- `sys_updated_on` is **mandatory** for every row.
- If missing/null/unparseable: row rejected; if widespread, import fails with explicit error telling user to re-export.
- `sys_id` is **recommended** but not mandatory.
- If `sys_id` is missing:
  - show a warning with explicit confirm step before final import.
  - fallback matching uses deterministic key strategy (below).

## Matching / Upsert Strategy
### Primary key path (preferred)
- Match existing mirror row by `(_instance_id, sys_id)` when `sys_id` exists.
- Upsert if incoming `sys_updated_on` is newer/equal, skip if older (configurable policy).

### Fallback path when `sys_id` missing
Use deterministic key hierarchy:
1. table-specific configured key set (future property per table), else
2. standard candidate keys in order: `number`, then `name`, then `(name + sys_created_on)` if available.

Rules:
- If exactly one existing row matches fallback key: update.
- If zero matches: insert.
- If multiple matches: mark row ambiguous and reject unless user enables an explicit "insert ambiguous as new" option (default off).

## Supported Formats
- CSV (UTF-8 with header row)
- XLS / XLSX
- JSON (array of objects)
- XML (row-based parser for flat records)

## Architecture / Components
### Backend
- New router: `src/web/routes/table_import.py`
- New service: `src/services/table_file_import.py`
- New import staging/result models:
  - `TableFileImportRun`
  - `TableFileImportIssue` (row/field-level validation results)
- Reuse existing dynamic registry/mappings:
  - `SnTableRegistry`
  - `SnFieldMapping`
- Reuse existing DB write patterns for mirror tables (`upsert_batch` compatible path where possible).

### Frontend
- New page template: `src/web/templates/table_file_import.html`
- Reuse `DataTable.js` for preview and issues tables.
- Reuse `ConditionBuilder.js` for optional row filtering before import.

## API Endpoints (Proposed)
- `GET /imports/table-file?instance_id=&table_name=` (page)
- `POST /api/imports/table-file/preview` (upload + parse + validate)
- `POST /api/imports/table-file/dry-run` (compute insert/update/ambiguous counts)
- `POST /api/imports/table-file/commit` (confirmed write)
- `GET /api/imports/table-file/runs` (history)
- `GET /api/imports/table-file/runs/{id}` (details + issues)

## Validation Checklist
- Instance/table exists and is registered (`SnTableRegistry`).
- File extension + parser compatibility.
- Header normalization and duplicate header detection.
- Required field presence: `sys_updated_on` (hard fail), `sys_id` (warn only).
- Datetime parsing for `sys_updated_on` and known date/datetime columns.
- Unknown columns: warn and ignore by default.

## Safety Controls
- Dry-run required before commit.
- Explicit confirm when `sys_id` is missing in any row.
- Max upload size + max row count configurable by property.
- Chunked writes with transaction boundaries and partial-failure reporting.
- Full audit trail in import run tables (who, when, instance, table, filename, row counts).

## Properties to Add
- `imports.max_upload_mb`
- `imports.max_rows_per_file`
- `imports.require_dry_run`
- `imports.allow_missing_sys_id`
- `imports.update_if_older` (default false)
- `imports.batch_size`

## Delivery Phases
### Phase A - Foundations
- Router + page scaffold + file upload plumbing.
- Parser support for CSV/XLSX/JSON (XML optional in Phase B).

### Phase B - Validation + Dry Run
- Field mapping, mandatory field checks, issues table, dry-run counts.

### Phase C - Commit + Audit
- Upsert/insert commit path, run history, downloadable error report.

### Phase D - UX Integration
- `Import File` launch actions on table/instance contexts (open in new tab with prefilled params).

## Open Decisions
- Exact fallback key policy per table (hardcoded defaults vs per-table property UI).
- Whether XML support ships in Phase A or Phase B.
- Whether ambiguous rows can be force-inserted in first release.

## Acceptance Criteria
- User can import a file for a selected instance/table when API access is rejected or unavailable.
- Missing `sys_updated_on` causes clear rejection and guidance.
- Missing `sys_id` triggers warning + explicit confirmation path.
- Dry-run and commit summaries are accurate and auditable.
- Import page can be opened contextually from table/instance links in a new tab.
