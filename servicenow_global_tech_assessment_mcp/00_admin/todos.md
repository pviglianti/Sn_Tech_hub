# 00_admin/todos.md

## Now — IMMEDIATE (do these first)
- [ ] [owner:human] **Job Log cancellation validation**: run UI checklist in `03_outputs/human_ui_validation_job_log_cancellation_2026-02-16.md` (per-row cancel + cancel-all-active + filtered cancel-all behavior). ~10 min.
- [ ] [owner:human] **MCP Prompts + Resources validation**: 8 curl tests against running server. Start app, run curl commands from `03_outputs/human_ui_validation_instance_scoped_config_2026-02-15.md` (bottom section). Verifies the MCP server correctly serves methodology prompts and reference docs to AI clients. ~10 min.
- [ ] [owner:human] **Instance-scoped Integration Properties validation**: UI walkthrough from same file (top section). Verifies global vs per-instance config scope selector + override behavior. ~10 min.
- [ ] [owner:human] **Credential key reconciliation (integration blocker)**: `POST /instances/{id}/test` currently returns 500 (`cryptography.fernet.InvalidToken`) for connected instances, including `testweis` (`instance_id=4`). Restore the matching `data/.encryption_key` for this DB or re-enter instance credentials, then rerun integration smoke.

## Now — When Available
- [ ] [owner:human] Visual QA: Data Browser page, template component changes, routed pages (instances, pulls).
- [ ] [owner:human] Visual QA deep-link flow: preflight → Job Log with preloaded conditions.
- [ ] [owner:human] Visual QA #2 Phase 2 durable status (dictionary modal, CSDM ingestion bar, scan runtime bar).
- [ ] [owner:human] Reasoning Phase 2 validation: run `run_preprocessing_engines` (all 6 engines) on a real assessment and spot-check generated rows in Data Browser.
- [x] [owner:both] Generalize coordination protocol: `agent_coordination_protocol.md` created, `AGENTS.md` updated.
- [x] [owner:both] **Phase 3 planning**: Engine output UI + enhanced features tab + AI reasoning loop + OOTB replacement analysis. Plan published at `tech-assessment-hub/docs/plans/2026-03-04-reasoning-layer-phase3-ui-ai-feature-orchestration.md`; chat coordination in `phase3_planning_chat.md`.
- [x] [owner:codex] Phase 3 Codex scope complete (P3A/P3B/P3D/P4A + P4C backend): data model/API/provenance, unified grouping-signal/hierarchy/evidence APIs, deterministic `seed_feature_groups`, one-pass `run_feature_reasoning`, `feature_grouping_status`, structured feature recommendation persistence surfaces, full regression green (`305 passed`).
- [x] [owner:claude] Phase 3 implementation kickoff (P3C/P4B): grouping-signal tabs + feature hierarchy UI and prompt/skill updates; align to Codex API contracts.
- [x] [owner:claude] Cross-review Codex Phase 3 backend contracts and confirm/patch any UI-required payload diffs in `phase3_planning_chat.md`.
- [ ] [owner:human] Phase 3/P4D final gate: execute manual QA checklist from `phase3_planning_chat.md` (QA-1..QA-14) on real assessment data after running `run_preprocessing_engines` → `seed_feature_groups` / `run_feature_reasoning`, then mark phase done.
- [x] [owner:codex] Phase 5 backend (P5A/P5B/P5C/P5D + P5E backend trigger wiring): pipeline stage model/API contracts, observation properties, `get_usage_count`, `generate_observations`, review-status API, and `advance-pipeline` stage execution. Full regression green (`328 passed`).
- [x] [owner:claude] Phase 5 UI scope: flow bar rendering/wiring, observation cards + review controls, review gate UI, and grouping/recommendation trigger UX using Codex backend contracts.
- [x] [owner:both] Phase 5 cross-review + end-to-end validation (backend+UI integration) and updated human QA checklist — automated validation green (`330` full regression after new dedupe tests) and live pipeline re-validation completed on `pdi` (`assessment_id=19`) through `engines → observations → review gate → grouping → recommendations → complete`.
- [x] [owner:codex] Phase 6 Task 3 UI prep: drafted `src/web/templates/admin_best_practices.html` with DataTable-based list + editor form and endpoint wiring assumptions (`GET/POST/PUT /api/best-practices`), then posted contract notes to `phase3_planning_chat.md` for Claude route wiring.
- [ ] [owner:claude] Phase 6 Task 3 backend wiring: add page route/nav + `best-practices` API routes to match Codex template contract, then request Codex cross-review + targeted test run.
- [ ] [owner:human] Reasoning Phase 1 validation: run `run_preprocessing_engines` tool on a real assessment and spot-check generated `code_reference` + `structural_relationship` rows in Data Browser.
- [ ] [owner:any] Rabbit hole priority config — modular/adjustable rules for which dependency types to follow.
- [ ] [owner:any] Catch-all label table — mapping app file class → display label (sys_dictionary → "Form Fields", etc.).

## Backlog
- [ ] [owner:claude] UI Consolidation Group 3A: Jinja macros for filter cards (deferred as low-value for now).
- [ ] [owner:any] Full-app UI modularization [H]: unify remaining results-grid behavior across global/assessment/scan into one reusable controller (audit 3.1).
- [ ] [owner:any] Full-app UI modularization [H]: create shared polling/status engine with standardized lifecycle/backoff/visibility handling (audit 3.3).
- [ ] [owner:any] Full-app UI modularization [H]: standardize API client + notifications (`api_client.js`, `ui_notifications.js`) and remove page-local fetch/alert drift (audit 3.4).
- [ ] [owner:any] Full-app UI modularization [H]: expand reusable table stack adoption + row/cell renderer hooks where still page-local (audit 3.5).
- [ ] [owner:any] Full-app UI modularization [H]: break up `instance_assessment_app_file_options.html` mega-controller into modular page components (audit 3.6).
- [ ] [owner:any] Full-app UI modularization [H]: add tenant-adjustable `ui.*` runtime properties (polling, page size, preview sizing, module visibility) (audit 3.9).
- [ ] [owner:any] Full-app UI modularization [M]: standardize modal framework and behavior across pages (audit 3.8).
- [ ] [owner:any] Full-app UI modularization [M]: split `style.css` into component/page layers to reduce regression risk (audit 3.10).
- [ ] [owner:any] Full-app UI modularization [M]: harden client-side HTML rendering paths (`innerHTML`) with centralized escaping/DOM builders (audit 3.11).
- [ ] [owner:codex] Revisit DB evolution path (replica/PostgreSQL) after core workflow maturity.
- [ ] [owner:human] Decide installer wizard release timing relative to core stabilization.
- [ ] [owner:codex] Remove `api_config_summary` + `instance_assessment_app_file_options_page` compatibility shims from `server.py` after test imports updated to router modules.
- [ ] [owner:codex] Add unit tests for `JobRun`/`JobEvent` state transitions, startup recovery, and ETA calculation (gap noted in Claude review of Phase 1).
- [ ] [owner:any] Jinja2 server-rendered dates (`.strftime()` in templates like `instances.html`, `assessments.html`) still show raw UTC — add a Jinja2 filter when prioritized.

## Completed (session 2026-03-04)
- [x] [owner:codex] Reasoning Phase 1 data model foundation: added `GroupingSignalType`, reasoning fields on `Feature`/`ScanResult`, and 4 new reasoning tables (`code_reference`, `update_set_overlap`, `temporal_cluster`, `structural_relationship`) with explicit `instance_id` + `assessment_id` references and result/update-set foreign keys.
- [x] [owner:codex] Reasoning Phase 1 addendum: added `temporal_cluster_member` junction table (`temporal_cluster` ↔ `scan_result`) for FK-level membership traceability.
- [x] [owner:codex] Implemented deterministic engine package (`src/engines`) with `code_reference_parser` (regex extraction + persistence + target resolution) and `structural_mapper` (parent/child mapping + persistence).
- [x] [owner:codex] Added MCP pipeline tool `run_preprocessing_engines` and registry wiring.
- [x] [owner:codex] Added comprehensive tests: reasoning data model, code parser, structural mapper, and run-engines tool; full suite green (`229 passed`).
- [x] [owner:claude] Reasoning Phase 2 Task 0: Data model additions — `UpdateSetArtifactLink` table, `signal_type`+`evidence_json` on `UpdateSetOverlap`, `NamingCluster` table, `TableColocationSummary` table. 15 tests in `test_reasoning_data_model.py`.
- [x] [owner:claude] Reasoning Phase 2 Task 0b: Reasoning property scaffolding — 8 configurable reasoning engine properties under "Reasoning / Engines" section in Integration Properties UI.
- [x] [owner:codex] Reasoning Phase 2 Task 1: Update Set Analyzer — base+enriched modes, `UpdateSetArtifactLink` persistence, `evidence_json` explainability, default-US downgrade policy, 5 signal types (content, name_similarity, version_history, temporal_sequence, author_sequence). `ReasoningEngineProperties` dataclass + typed property loader. 9 tests.
- [x] [owner:claude] Reasoning Phase 2 Task 2: Temporal Clusterer — groups ScanResults by developer + time proximity, reads gap/min-size from properties. 5 tests.
- [x] [owner:claude] Reasoning Phase 2 Task 3: Naming Analyzer — groups ScanResults by shared name prefixes with longest-prefix-first deduplication. 16 tests.
- [x] [owner:codex] Reasoning Phase 2 cross-review hardening: updated Tasks 2/3 engines to read reasoning properties with instance-scoped fallback (`instance_id`) and added regression tests for instance override behavior.
- [x] [owner:claude] Reasoning Phase 2 Task 4: Table Co-location — groups ScanResults by `meta_target_table` (2+ members). 8 tests.
- [x] [owner:claude] Reasoning Phase 2 Task 5: Registry wiring — all 6 engines in `run_preprocessing_engines` MCP tool.
- [x] [owner:both] Reasoning Phase 2 Task 6: Full regression — 276 tests passing, 0 failures. Claude + Codex approved.
- [x] [owner:codex] Connection-triggered pull dedupe hardening: validated live `pdi` connection pulls are upsert-only (no duplicate `(instance_id,sn_sys_id)` keys in app-file types, table definitions, version history, dictionary registry/mappings), added regression tests `tests/test_connection_pull_upsert.py`, and relabeled Job Log metric from "Rows Inserted" to "Rows/Items Processed" to reflect processed counters.

## Completed (session 2026-02-16)
- [x] [owner:claude] VH phantom event fix: `_get_or_create_vh_event()` replaced with read-only `_VH_EVENTS.get()` in preflight check + Stage 5. Prevents 1-hour hang when no proactive pull exists.
- [x] [owner:claude] VH 2M full-pull fix: propagated `version_state_filter` through `_build_assessment_preflight_plan` → `_estimate_expected_total` → `build_version_history_query`. Delta decision now compares apples-to-apples.
- [x] [owner:claude] VH concurrent with non-VH types: VH runs in separate thread (own Session + Client) during preflight.
- [x] [owner:claude] Two-phase proactive VH pull: Phase 1 = current-only (sets event), Phase 2 = all states (background backfill).
- [x] [owner:claude] VH sort order: `pull_version_history` uses `order_by="state,sys_recorded_at"` when pulling all states so current arrives first.
- [x] [owner:claude] Generic concurrent preflight: refactored to use `PREFLIGHT_CONCURRENT_TYPES` property (default: `version_history,customer_update_xml`). Each concurrent type gets its own thread. 203 tests passing.

## Completed (session 2026-02-15)
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
- [x] [owner:codex] UI Consolidation Group 1C: Promoted class label helper to shared `get_class_label()` in `artifact_detail_defs.py`; removed duplicate local implementations in `artifact_detail_puller.py` and `artifacts.py`. Tests: 98 passed.
- [x] [owner:codex] UI Consolidation Group 1D: Extracted shared `_query_artifacts_for_scans()` helper in `artifacts.py`; simplified assessment and scan artifact endpoints to call shared logic. Tests: 98 passed.
- [x] [owner:claude] UI Consolidation Group 2C: Added reusable `ResultsFilterTable.js`, loaded in `base.html`, wired into `assessment_detail.html` and `scan_detail.html`.
- [x] [owner:codex] UI Consolidation Group 2A: Added reusable `ArtifactList.js`, loaded in `base.html`, and replaced duplicated artifact list/filter logic in `assessment_detail.html` + `scan_detail.html`. Tests: 98 passed.
- [x] [owner:codex] UI Consolidation Group 2B: Added reusable `ArtifactDetail.js`, loaded in `base.html`, and replaced duplicated artifact detail/code loaders in `result_detail.html` + `artifact_record.html`. Tests: 98 passed.
- [x] [owner:codex] MCP Plan Phase 1: Added protocol support for `prompts/list`, `prompts/get`, `resources/list`, `resources/read` in JSON-RPC; added prompt/resource registries and protocol tests. Tests: 117 passed.
- [x] [owner:codex] MCP Plan Phase 5: Added 5 assessment tools (`update_scan_result`, `update_feature`, `get_feature_detail`, `get_update_set_contents`, `save_general_recommendation`) and new `GeneralRecommendation` model + registry wiring. Tests: 117 passed.
- [x] [owner:claude] MCP Plan Phase 4: Classification quality audit — fixed Gaps 1-3 (OOB+customer→modified_ootb, wired `changed_baseline_now`, unknown vs unknown_no_history). Gap 4 deferred. 22 classification tests, 119 total pass.
- [x] [owner:claude] MCP Plan Phase 2: Assessment methodology prompts — `tech_assessment_expert` (full methodology, classification, disposition, grouping, tool usage) + `tech_assessment_reviewer` (lighter review checklist). Registered in PROMPT_REGISTRY via auto-population. 12 tests.
- [x] [owner:claude] MCP Plan Phase 3: Assessment reference resources — 6 resources (classification-rules, grouping-signals, finding-patterns, app-file-types, scan-result-fields, feature-fields) at `assessment://` URIs. Registered in RESOURCE_REGISTRY. 16 tests. 147 total pass.
- [x] [owner:claude] Updated expert prompt to match PV's actual assessment flow: depth-first temporal order, rabbit holes only into customized records, catch-all buckets by app file class type. Source: `02_working/01_notes/my flow for analysis tech`. 150 total pass.
- [x] [owner:codex] #5: Implemented instance-scoped config overrides (`AppConfig.instance_id` + partial unique indexes), added DB migration for legacy global-key schema, wired instance-aware fallback resolution in integration properties/fetch config, and added scope selector in integration properties UI/API. Tests: 150 passed.
