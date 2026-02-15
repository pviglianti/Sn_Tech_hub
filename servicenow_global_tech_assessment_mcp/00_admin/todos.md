# 00_admin/todos.md

## Now
- [ ] [owner:human] Visual QA: Data Browser page (`/data-browser`), all pages with Codex template component changes, and new routed pages (instances, pulls).
- [ ] [owner:human] Review Codex live smoke-check evidence for extracted instances + pulls routes and sign off.
- [x] [owner:human] Visual QA durable pull run-state: confirm Pre Flight pages show live queue progress/ETA (`Pulling N of X`, current type, pulled/expected, in DB, overall %) without manual refresh.
- [ ] [owner:human] Visual QA deep-link flow: from preflight pages click `Pre Flight Job Log` and confirm `ConditionBuilder` preloads `module=preflight` (+ `instance_id` when present) on `/job-log`.
- [ ] [owner:human] Visual QA #2 Phase 2 durable status: confirm dictionary modal progress, CSDM `/csdm/ingestion` job status bar, and assessment detail scan runtime bar continue to update correctly after the durable-run migration.

## Next
- [ ] [owner:claude] MCP Plan Phase 1: Add `prompts/list`, `prompts/get`, `resources/list`, `resources/read` to JSON-RPC protocol handler. See `03_outputs/plan_mcp_tools_classification_quality_2026-02-15.md`.
- [ ] [owner:claude] MCP Plan Phase 2: Create `tech_assessment_expert` prompt (methodology, classification rules, disposition framework, tool usage guidance).
- [ ] [owner:claude] MCP Plan Phase 3: Create assessment reference Resources (classification guide, grouping signals, schema docs).
- [ ] [owner:claude] MCP Plan Phase 4: Audit `_classify_origin()` against assessment guide decision tree. 4 known gaps identified.
- [ ] [owner:any] MCP Plan Phase 5: Add 5 missing assessment tools (`update_scan_result`, `update_feature`, `get_update_set_contents`, `get_feature_detail`, `save_general_recommendation`).
- [ ] [owner:codex] #5: Add instance-scoped config overrides (AppConfig + instance_id FK + partial unique indexes).

## Backlog
- [ ] [owner:codex] Revisit DB evolution path (replica/PostgreSQL) after core workflow maturity.
- [ ] [owner:human] Decide installer wizard release timing relative to core stabilization.
- [ ] [owner:codex] Remove `api_config_summary` + `instance_assessment_app_file_options_page` compatibility shims from `server.py` after test imports updated to router modules.
- [ ] [owner:codex] Add unit tests for `JobRun`/`JobEvent` state transitions, startup recovery, and ETA calculation (gap noted in Claude review of Phase 1).
- [ ] [owner:any] Jinja2 server-rendered dates (`.strftime()` in templates like `instances.html`, `assessments.html`) still show raw UTC — add a Jinja2 filter when prioritized.

## Completed (this session — 2026-02-15)
- [x] [owner:claude] #1+#11: Wired `integration_properties` into runtime. Replaced all hardcoded `timeout=30`.
- [x] [owner:claude] #4: Consolidated duplicate `PREFLIGHT_SN_TABLE_MAP`.
- [x] [owner:claude] #7 (Phase 4): Migrated preflight Data Browser to DataTable.js + ConditionBuilder.js + ColumnPicker.js.
- [x] [owner:codex] #3: DataPullSpec registry — replaced 12-branch dispatch + 5 duplicated maps.
- [x] [owner:codex] #6 (COMPLETE): Extracted ALL 6 routers — analytics, mcp_admin, preferences, data_browser, instances, pulls. 87 tests pass.
- [x] [owner:codex] #10: 4 shared Jinja components, 9 templates updated.
- [x] [owner:both] Post-restart validation — 87 tests pass, all pages 200, API endpoints verified.
- [x] [owner:codex] Live smoke check (restarted app): extracted instances + pulls routes verified on `127.0.0.1:8081` (`/instances`, `/instances/add`, `/api/instances`, expected 404s for invalid `instance_id` on scoped endpoints, OpenAPI includes all extracted route paths).
- [x] [owner:codex] Added unified top-nav `Job Log` page (`/job-log`) with standardized fields across CSDM + preflight runs (module, instance, target, job type, status, rows inserted/updated, duration, error), including module/instance filters.
- [x] [owner:codex] Upgraded `/job-log` to reusable `DataTable.js` + `ConditionBuilder.js` + `ColumnPicker.js`, and made incoming deep-link filters visible/editable in the condition builder instead of query-param-only filtering.
- [x] [owner:codex] #2 Phase 1: Implemented durable data-pull run tracking (`job_run` + `job_event`), startup interruption recovery, run correlation on `InstanceDataPull.run_uid`, API run snapshots in `/api/instances/{id}/data-status` (`active_run`/`latest_run`), and live queue progress/ETA rendering on preflight pages.
- [x] [owner:codex] #2 Phase 2: Migrated dictionary pulls (`dict_pull`), CSDM ingestion (`csdm_ingest`), and assessment scan workflows (`assessment_scan`) to durable `job_run` + `job_event` lifecycle tracking; generalized startup stale-run recovery to all queued/running job types.
- [x] [owner:claude] Rename: `CsdmTableRegistry`→`SnTableRegistry`, `CsdmFieldMapping`→`SnFieldMapping`, all 5 Csdm* classes → Sn*, `models_csdm.py`→`models_sn.py`. DB table names unchanged. 11 files, 87 tests pass.
- [x] [owner:claude] #8/#9 analysis: DataTable.js migration NOT warranted for analytics.js (pivot tables) or integration_properties.js (editable key-value). Page sizes already resolved by DataTable.js selector. Documented as intentional non-action.
- [x] [owner:claude] Display timezone property: Added `general.display_timezone` (default EST) to integration properties with "General" section at top. Properties page now grouped by section. `formatDate()` in `app.js` uses configured TZ. DataTable.js auto-formats `kind:"date"` columns. New `/api/display-timezone` endpoint. 87 tests pass.
- [x] [owner:claude] Reviewed Codex #2 Phase 1 (durable job tracking): `JobRun` + `JobEvent` models, `run_uid` correlation, startup recovery, API run snapshots, live progress/ETA. Clean design, no conflicts with timezone changes. Noted: datetime serialization uses naive `.isoformat()` (no Z suffix) — our `formatDate()` handles this. Noted: no dedicated unit tests for run lifecycle.
