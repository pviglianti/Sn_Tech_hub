# API Standardization Plan (Codex) - 2026-02-13

## Summary
Standardize how delta pulls are defined, paginated, skipped, and observed across:
- CSDM mirror ingestion (`sn_*` tables + `csdm_*` state/log tables)
- Preflight/Data Browser cached pulls (`update_set`, `customer_update_xml`, etc. + `instance_data_pull`)

Goal: never miss updates, make skip decisions safe, unify visibility, and keep operator/UI behavior consistent.

## Definitions (Hard Contract)
- Primary key for dedupe/upsert: `(instance_id, sys_id)` everywhere.
- Delta watermark field: `sys_updated_on` everywhere a table supports it.
- Tie-breaker field: `sys_id` (must be included in fetch and used for deterministic pagination).
- Canonical watermark source: derived from the local DB (max stored `sys_updated_on` for that dataset/instance).
- Stored watermark: updated only on successful completion; used for UI/debug, not as truth.

## Current State (What We Have Today)
### CSDM
- Canonical watermark is DB-derived: `MAX(sys_updated_on)` from `sn_*` mirror tables (`src/services/csdm_ingestion.py:get_local_max_sys_updated_on`).
- Upsert is bulk SQLite UPSERT (`src/services/csdm_ingestion.py:317`).
- Has unsafe count-based delta skip (`local_count >= remote_count`) (`src/services/csdm_ingestion.py:653`).

### Preflight/Data Browser
- Watermark is currently stored-cursor-driven: `since = pull.last_sys_updated_on` (`src/services/data_pull_executor.py:1333`), stored in `instance_data_pull.last_sys_updated_on` (`src/models.py:894`).
- Upsert is ORM overwrite per `sn_sys_id`.
- Planning/orchestration does staleness + drift rules in `src/server.py:_build_assessment_preflight_plan`.

## Decisions (Standardization Choices)
1. Watermark source
- Use canonical watermark derived from cached data in DB for both systems.
- Continue to store last successful watermark for visibility:
  - Preflight: `instance_data_pull.last_sys_updated_on` (already exists).
  - CSDM: `csdm_ingestion_state.last_successful_sys_updated_on` (already exists).

2. Pagination strategy for delta
- Standardize on keyset (cursor) pagination for delta pulls:
  - Query is "after last seen (ts, sys_id)"
  - Sort is `sys_updated_on ASC, sys_id ASC`

3. Skip rule
- Remove/avoid count-based skips that compare total row counts.
- Replace with a delta probe:
  - Ask ServiceNow how many records match delta query.
  - If 0, skip safely; else ingest.

4. Observability fields location
- Use existing DB tables for all observability:
  - Preflight: `instance_data_pull` (already has most fields).
  - CSDM: `csdm_ingestion_state` and `csdm_job_log` (already has most fields).
- Add only minimum extra columns if needed for persisted keyset cursor.

## Explain: Offset vs Keyset (Why This Plan Chooses Keyset)
- Offset paging (`limit/offset`) risks skip/dup when records change during paging or when `sys_updated_on` ties exist.
- Keyset paging uses start-after `(ts, sys_id)` so ordering is deterministic even with identical timestamps.
- With delta pulls, correctness is prioritized over implementation convenience.

## Interfaces / Schema Changes (Explicit)
### ServiceNow query building
- Add a standard delta cursor query builder that produces encoded queries like:
  - Initial delta (no cursor): `sys_updated_on>{watermark}^ORDERBYsys_updated_on^ORDERBYsys_id`
  - Subsequent page: `sys_updated_on>{ts}^ORsys_updated_on={ts}^sys_id>{id}^ORDERBYsys_updated_on^ORDERBYsys_id`
- Requirement: all delta fetches include `sys_id` and `sys_updated_on` in the fields.

### Preflight observability storage (existing table)
- Store per-run metadata in `instance_data_pull` (`src/models.py:873`):
  - `expected_total` (already)
  - `last_remote_count` (already)
  - `last_local_count` (already)
  - `sync_mode` and `sync_decision_reason` (already)
  - `last_sys_updated_on` (already, used as last successful watermark)

Optional additions (only if persisted mid-run cursor is needed):
- `last_cursor_sys_updated_on` (datetime)
- `last_cursor_sys_id` (string)

### CSDM observability storage (existing tables)
- Per-table rolling status in `csdm_ingestion_state` (`src/models_csdm.py:109`):
  - `last_successful_sys_updated_on`, `last_successful_sys_id` (already)
  - `last_remote_count` (already)
  - `total_rows_in_db`, per-batch counters (already)

Optional addition:
- `last_delta_probe_count` (int) to display 0-new-record skip reason.

- Per-run audit in `csdm_job_log` (`src/models_csdm.py:158`):
  - rows inserted/updated/deleted, error stack (already)

Optional additions:
- `watermark_used` (string/datetime)
- `cursor_end` (string)

## Implementation Plan (Decision Complete)
1. Create a shared delta contract helper
- One module that defines:
  - watermark field (`sys_updated_on`)
  - tie-breaker field (`sys_id`)
  - keyset query builder given `(watermark, cursor)`
- Used by both CSDM ingestion and preflight pulls.

2. Add keyset iterator to `ServiceNowClient`
- New method: `iterate_keyset(table, base_query, order_fields, cursor, batch_size)`
- Always requests sorted results by `sys_updated_on, sys_id`.

3. Preflight: switch canonical watermark computation
- For each `DataPullType`:
  - compute local `MAX(sys_updated_on)` from the cached table (per instance)
  - use that as the delta watermark
  - run keyset iterator and upsert by `sn_sys_id`
- Update `instance_data_pull.last_sys_updated_on` only after success.

4. CSDM: remove count-based delta skip
- Delete/disable `local_count >= remote_count` shortcut.
- Add delta probe:
  - SN count for `sys_updated_on > watermark` (or equivalent)
  - if 0, mark completed without fetching
- Use keyset iterator for ingestion pages.

5. Standardize skip semantics and UI messaging
- skip only when delta probe is 0 or orchestration says already running/fresh.
- update state tables with reason strings for consistent UI explanations.

6. Bulk operations robustness
- Multi-table clear should be best-effort per table.
- Missing local mirror table should not fail the whole request.
- Response should include per-table `cleared` and per-table `errors`.

## Tests / Validation Scenarios
- Delta keyset query builder:
  - multiple records share identical `sys_updated_on`
  - cursor advancement yields no duplicates and no skips
- Delta probe:
  - probe=0 -> no fetch, no writes, consistent completed/skip status
  - probe>0 -> fetch+upsert occurs
- CSDM clear-selected:
  - includes one mirror table that does not exist -> others still clear; missing table returns error entry, not full HTTP failure

## Acceptance Criteria
- Delta pulls are deterministic and do not miss updates under timestamp ties.
- No count-based shortcuts that can miss updates remain in delta path.
- Watermarks in UI/logs reflect:
  - canonical (derived) watermark used at start
  - stored last successful watermark after completion
- Observability is visible via:
  - `instance_data_pull` for preflight
  - `csdm_ingestion_state` + `csdm_job_log` for CSDM
- Multi-table admin actions are robust and report partial failures clearly.

## Assumptions
- Relevant datasets expose `sys_updated_on` and `sys_id` (confirmed in current models).
- ServiceNow encoded queries support `^OR` and multiple `ORDERBY...` segments for stable sorting.
