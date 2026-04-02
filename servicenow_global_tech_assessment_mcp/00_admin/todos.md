# 00_admin/todos.md

## Now — IMMEDIATE (do these first)
- [ ] [owner:human] **Job Log cancellation validation**: run UI checklist in `03_outputs/human_ui_validation_job_log_cancellation_2026-02-16.md` (per-row cancel + cancel-all-active + filtered cancel-all behavior). ~10 min.
- [ ] [owner:human] **MCP Prompts + Resources validation**: 8 curl tests against running server. Start app, run curl commands from `03_outputs/human_ui_validation_instance_scoped_config_2026-02-15.md` (bottom section). Verifies the MCP server correctly serves methodology prompts and reference docs to AI clients. ~10 min.
- [ ] [owner:human] **Instance-scoped Integration Properties validation**: UI walkthrough from same file (top section). Verifies global vs per-instance config scope selector + override behavior. ~10 min.
- [x] [owner:human] **Credential key reconciliation**: Resolved — credentials re-entered, instances connecting successfully.

## Now — When Available
- [ ] [owner:codex] **Phase 11 unified execution (integrity + cleanup tracks)**: execute Codex-owned tracks from `03_outputs/plan_phase11_unified_feature_ownership_and_legacy_cleanup_2026-03-05.md` and coordinate status in `00_admin/phase11_coordination.md` / `00_admin/phase11_chat.md` (customized-only guard, unique feature membership protection, and assessment-scoped legacy cleanup utility with dry-run/apply).
- [ ] [owner:codex] **Orchestration runtime dry-run validation**: exercise the new `.claude/orchestration/` workflow on a small scoped task and verify streamed launch logs, coordination runtime registry, reviewer-after-first-`[DONE]` gate, model/effort overrides, and safe worktree teardown behavior before using it for larger execution.
- [ ] [owner:codex] **Phase 8A Step 0**: run full regression on combined branch state and commit runtime hardening tranche baseline (telemetry + checkpoints + AI runtime/budget properties) before human QA.
- [ ] [owner:human] **ChatGPT app + deep research validation**: expose the running app over HTTPS, connect `/mcp` from ChatGPT Developer Mode, and verify the new read-only `search`/`fetch` tools can answer TA questions and fetch cited artifact/report documents.
- [ ] [owner:human] **Connected AI analysis validation**: on a real assessment with LLM settings configured, run `ai_analysis` and verify it now processes artifacts one at a time, anchors scope to the assessment target application/tables, marks non-direct-but-related customizations as `adjacent`, writes concrete functional observations plus related-result IDs, can use the new ServiceNow web context lookup tools sparingly for target-app clarification, and blocks `observations` if full scope triage was not persisted.
- [ ] [owner:human] **Phase 11B live validation**: on a real assessment (for example Assessment 22), run `grouping -> ai_refinement -> recommendations -> report` with connected AI enabled and verify AI-owned feature creation works artifact-coverage-first: functional features first, leftover in-scope artifacts rolled into explicit buckets (`Form & Fields`, `ACL`, etc.), adjacent-only/mixed features appear in the main feature list, final naming happens after refinement, and recommendations/report block until coverage + final naming are complete.
- [x] [owner:codex] **Dependency Mapper live rerun validation**: reran Assessment 22 `engines` directly against the live DB after the engine fixes and confirmed non-zero live outputs without manual pre-clear (`structural_relationship=372`, `code_reference=4373`, `dependency_chain=8`, `dependency_cluster=70`); assessment state was then normalized to `ai_analysis` pending for the next stage.
- [ ] [owner:human] **Relationship Graph + Dependency Map validation**: verify `/relationship-graph` and `/dependency-map` launch from result detail, feature hierarchy/member rows, and table browser; confirm relationship graph keeps the broad multi-signal view while dependency map stays dependency-only, and validate click-centered progressive expansion, scope filters (`direct`/`adjacent`/`out_of_scope`/`unknown`), result-vs-artifact label toggle, artifact-type colors + per-type toggles (Business Rule, Client Script, Dictionary Entry, etc.), field/reference-qualifier linkage quality, and development-chain overlays on real assessment data. Assessment 22 should now show result-level dependency-map edges from `incident events` to Incident dictionary/dictionary-override results like `assigned_to`, `assignment_group`, `priority`, `severity`, and `incident_state`, artifact-centered views launched with `scan_id` should still show cross-scan assessment neighbors (for example `191829` -> `Category`/`Subcategory`/`location`/`u_business_service`/`cmdb_ci`, `191859` -> `assigned_to`/`assignment_group`), and exact-name references with multiple distinct real targets should show all of them instead of a single preferred artifact.
- [ ] [owner:codex] **API-Access Fallback Table Import Utility (next feature)**: implement instance+table-scoped upload/import flow for tables where API pulls are rejected/blocked (CSV/XLS/XLSX/JSON/XML) using plan `servicenow_global_tech_assessment_mcp/03_outputs/plan_api_access_fallback_table_import_utility_2026-03-05.md` (mandatory `sys_updated_on`, `sys_id` warning/fallback matching, dry-run + confirm + upsert/insert report).
- [ ] [owner:codex] **Inherited dictionary-override dependency bridging**: Structural Mapper currently joins `sys_dictionary_override` to `sys_dictionary` only on same `(name, element)`, which misses inherited-field cases like Incident overrides for Task fields. Extend override mapping to follow table ancestry so dependency map can show both the override and underlying base dictionary artifact when both are known.
- [ ] [owner:human] **Full pipeline live QA**: Run complete 10-stage pipeline on real assessment with live SN instance after credential reconciliation.
- [ ] [owner:human] **Assessment Runtime Usage validation**: run one full pipeline and verify `/integration-properties/assessment-runtime-usage` shows mode/provider/model, MCP local/SN/local-DB call counters, token totals, and estimated cost.
- [ ] [owner:human] **Resume + rehydrate validation**: interrupt an in-progress stage (`observations`, `grouping`, or `recommendations`) and confirm resume picks up from saved checkpoint/index instead of restarting completed work.
- [ ] [owner:human] **Phase 9/10 feature validation**: verify prompt-toggle behavior (`pipeline.use_registered_prompts`), assessment exports (`/api/assessments/{id}/export/xlsx`, `/api/assessments/{id}/export/docx`), process recommendations tab DataTable, and `/assessments/summary` dashboard metrics on real assessment data.
- [ ] [owner:claude] **Phase 9/10 peer review closeout**: post final `REVIEW_PASS` for prompt integration (P9A) after Codex remediation; exports/process recommendations/summary are already reviewed and marked approved.
- [ ] [owner:human] Visual QA: Data Browser page, template component changes, routed pages (instances, pulls).
- [ ] [owner:human] Visual QA deep-link flow: preflight → Job Log with preloaded conditions.
- [ ] [owner:human] Visual QA #2 Phase 2 durable status (dictionary modal, CSDM ingestion bar, scan runtime bar).
- [ ] [owner:human] Phase 3/P4D final gate: execute manual QA checklist from `phase3_planning_chat.md` (QA-1..QA-14) on real assessment data.
- [ ] [owner:codex] **Property contract hygiene sweep (code/docs/app_config parity)**: (1) replace stale doc key `observations.context_enrichment` with `ai_analysis.context_enrichment`, (2) replace legacy `observations.usage_query_limit` references with `observations.max_usage_queries_per_result` + historical-note wording, (3) explicitly document special non-Integration-Properties AppConfig keys (`mcp_bridge_config`, `mcp_runtime_config`, `mcp_admin_token`) and ownership boundaries, and (4) add an automated parity check/test that fails on unapproved unknown AppConfig keys.
- [ ] [owner:codex] **AI runtime budget wiring completion**: enforce currently loaded-but-underused runtime controls in execution path: `ai.budget.assessment_soft_limit_usd` (warning/telemetry threshold), `ai.budget.monthly_hard_limit_usd` (tenant cap), `ai.budget.max_input_tokens_per_call`, `ai.budget.max_output_tokens_per_call`, plus explicit runtime behavior contract for `ai.runtime.mode/provider/model` beyond telemetry labeling.
- [ ] [owner:claude] **Cross-review request — properties + save UX**: review Codex property-contract TODO scope and Integration Properties Save UX update (global top-right + bottom save actions, dirty-state/no-auto-save messaging) and post `REVIEW_PASS`/`REVIEW_FEEDBACK` in `phase3_planning_chat.md`.
- [ ] [owner:any] Rabbit hole priority config — modular/adjustable rules for which dependency types to follow.
- [ ] [owner:any] Catch-all label table — mapping app file class → display label (sys_dictionary → "Form Fields", etc.).
- [ ] [owner:codex] Dynamic browser artifact-table deep-link fallback: opening graph `Artifact Table` links for app-file classes like `sys_script` / `sys_script_client` currently returns “table not registered for instance” when no dynamic dictionary mirror exists. Decide whether these links should route to results/customizations browser instead, auto-register read-only table metadata, or show a graceful in-app fallback view.

## Completed (session 2026-03-06 — Integration Properties + AI Setup Wizard Hardening)
- [x] [owner:codex] Wired `ai_analysis.enable_depth_first_traversal` into the `ai_analysis` stage branch so a populated relationship graph no longer forces DFS when the property is disabled; added regression coverage for graph-present sequential fallback.
- [x] [owner:codex] Hardened instance-scoped Integration Properties save semantics so unchanged inherited values are not materialized as instance overrides (client submits changed keys only, backend deletes/avoids rows that match inherited global/default values).
- [x] [owner:codex] Finished AI Setup Wizard model selection flow: restored working model controls, added provider catalog refresh/custom-model handling, scoped the catalog API by `instance_id`, and added route/render coverage tests.

## Completed (session 2026-03-06 — Best Practice DataTable Standardization)
- [x] [owner:codex] Standardized Best Practices admin page onto explicit DataTable contracts: added `/api/best-practices/field-schema` + `/api/best-practices/records`, generated schema from `BestPractice.__table__.columns`, and exposed all DB-backed fields (including `source_url`, `created_at`, `updated_at`) through the table/column picker.
- [x] [owner:codex] Added full Best Practice record view at `/admin/best-practices/{id}` and extended shared `DataTable.js` to support extra query params plus record links for non-`sys_id` rows via `rowIdField` + `getRecordUrl`; validated with `21` Best Practice tests passing.

## Completed (session 2026-03-28 — ChatGPT / Deep Research MCP Surface)
- [x] [owner:codex] Added ChatGPT/deep-research-compatible MCP `search` + `fetch` tools over assessments/findings/features/recommendations, registered read-only tool annotations in MCP tool manifests, and updated the JSON-RPC tool-call path to pass through raw MCP `content` payloads when a tool returns standard text content.
- [x] [owner:codex] Added targeted regression coverage for MCP `search`/`fetch` protocol behavior and compatibility with existing JSON-wrapped tools; targeted MCP suite green (`22 passed`).

## Completed (session 2026-03-28 — Connected AI Scope Triage Correction)
- [x] [owner:codex] Replaced the placeholder `ai_analysis` stage path with a connected-tool dispatch path that uses configured CLI-backed LLM sessions (OpenAI/Codex or Claude local subscription/API-key mode), injects assessment methodology prompt text, and requires the model to persist scope triage + observations through `update_scan_result`.
- [x] [owner:codex] Extended `update_scan_result` to accept structured `ai_observations`, taught prompts to persist related customized result IDs, and updated deterministic/grouping/report stages to preserve AI-written observations and exclude `is_out_of_scope=true` artifacts from observations/grouping/refinement/report counts.
- [x] [owner:codex] Added regression coverage for connected `ai_analysis` dispatch branching, structured `ai_observations` writes, deterministic-observation preservation, AI relationship-driven grouping, and out-of-scope filtering; targeted + regression suites green (`55 passed` + `35 passed`).

## Completed (session 2026-04-01 — Phase 11B AI-Owned Feature Lifecycle)
- [x] [owner:codex] Reworked downstream stage orchestration so `grouping`, `ai_refinement`, and `recommendations` dispatch connected AI feature-authoring passes via `ai.feature.pass_plan_json`; added bucket taxonomy config (`ai.feature.bucket_taxonomy_json`) and a new `ai_feature_dispatch` service that handles structure/coverage/refine/final-name pass execution.
- [x] [owner:codex] Expanded the feature contract with `feature_kind`, `composition_type`, `name_status`, and `bucket_key`; added shared feature-governance helpers for one-primary-membership enforcement, composition rollups, coverage summaries, and strict manual-override readiness checks.
- [x] [owner:codex] Updated pipeline/UI gating so report/recommendations block on full feature coverage + final naming, manual override requires fully reviewed human completeness, and the feature hierarchy UI now surfaces bucket/composition/name-status badges plus pipeline feature-status messaging.
- [x] [owner:codex] Updated methodology prompts and targeted tests to reflect AI-owned grouping, bucket features, adjacent-first-class membership, and final-pass naming; verification is currently limited to `py_compile` because local `pytest` is still unavailable in this environment.

## Completed (session 2026-04-01 — Adjacency Prompt Clarification)
- [x] [owner:codex] Tightened prompt guidance so `adjacent` is reserved for table-bound in-scope artifacts outside the direct target tables/forms, while tableless artifacts such as script includes are judged by behavior as `in_scope` or `out_of_scope`; updated `artifact_analyzer`, `tech_assessment`, connected `ai_analysis` fallback guidance, and prompt-content tests. Verification: `py_compile` passed on touched files.

## Completed (session 2026-03-05 — AI Setup Wizard Flow)
- [x] [owner:codex] Added guided AI setup page at `/integration-properties/ai-setup` for non-technical runtime setup (scope selection, runtime mode/provider/model save, bridge config save/start/restart/stop, and direct pipeline stage kickoff action).
- [x] [owner:codex] Added Integration Properties entry points to the wizard: Assessment Tools card button and inline `AI Setup Wizard` link directly in the `AI / LLM Runtime` section next to AI provider/model controls.

## Backlog
- [ ] [owner:codex] **Connected AI downstream stages**: extend the same tool-enabled provider dispatch approach from `ai_analysis` into `ai_refinement`, `recommendations`, and `report` so those stages stop storing prompt/context placeholders and instead execute real model work end-to-end.
- [ ] [owner:codex] **ChatGPT citation base URL property**: add a first-class integration property for the app's public base URL so MCP `search`/`fetch` can emit absolute URLs for internal assessment/feature/report pages instead of relative fallback paths.
- [ ] [owner:codex] **Bail-out boilerplate refactor**: Extract ~25 lines of repeated bail-out logic across 11 `_pull_*` handlers into a shared helper function in `data_pull_executor.py`. Logged by Reviewer-T3 (2026-03-05 sprint).
- [ ] [owner:codex] **csdm_ingestion consolidation**: `csdm_ingestion.py` still has its own `build_delta_query()` and `fetch_batch_with_retry()` — migrate to centralized `sn_client` methods. Logged as out-of-scope debt in SN API centralization sprint.
- [ ] [owner:codex] **display_value parameter normalization**: `display_value=False` silently dropped in Task 2 consolidated modules (scan_executor, sn_dictionary). Add explicit `display_value` parameter to `get_records()` if needed by callers. Flagged by Architect (2026-03-05 sprint).
- [ ] [owner:codex] **ORDER direction dedup hardening**: Harden cross-direction `sysparm_order_by` vs encoded-query ORDER clause conflict detection. Latent risk flagged by Architect (2026-03-05 sprint).
- [ ] [owner:codex] **Bail-out telemetry dashboard**: Build observability view for the 6 new `InstanceDataPull` bail-out columns. Recommended by Architect (2026-03-05 sprint).
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

## Completed (session 2026-03-05 — Customizations Visibility Recovery)
- [x] [owner:codex] Fixed missing-customizations rendering for historical assessments by adding API-level auto-heal/backfill in `customizations` routes (`/api/assessments/{id}/customizations`, `/api/scans/{id}/customizations`, `/api/customizations/options`) to sync stale child-table rows from `scan_result` on read.
- [x] [owner:codex] Added regression coverage (`tests/test_customizations_api.py`) validating stale-child-table auto-heal behavior for assessment listing + options endpoints.
- [x] [owner:codex] Repaired backfill utility startup (`src/scripts/backfill_customizations.py` now imports `src.models_sn` registry) and executed one-time local DB backfill to restore historical rows.

## Completed (session 2026-03-05 — MCP Result Sync Hardening)
- [x] [owner:codex] Patched MCP `update_scan_result` tool to call `sync_single_result` after writes so customization child rows stay aligned when AI updates review/disposition/recommendation/observations.
- [x] [owner:codex] Added regression tests (`tests/test_update_result_tool.py`) covering both existing-customization updates and missing-customization backfill via MCP write path.

## Completed (session 2026-03-05 — AI/Engine Write-Back Sync Hardening)
- [x] [owner:codex] Upgraded `customization_sync.bulk_sync_for_scan` from insert-only to full reconciliation (insert missing, update drifted rows, delete stale rows no longer customized) and added optional transactional `commit` control for batching.
- [x] [owner:codex] Patched AI pipeline write paths to sync child rows during updates: `generate_observations` and depth-first analyzer now call `sync_single_result(..., commit=False)` before their staged commits.
- [x] [owner:codex] Expanded regression coverage for reconciliation and AI write-back consistency (`tests/test_customization_sync.py`, `tests/test_generate_observations.py`, `tests/test_depth_first_analyzer.py`).

## Completed (session 2026-03-05 — Phases 6 + 7)
- [x] [owner:claude] **Phase 6 complete**: MCP Skills/Prompts Library + Best Practice Knowledge Base. `BestPractice` model with 41 seed checks + `BestPracticeCategory` enum, admin CRUD API (`GET/POST/PUT /api/best-practices`), session-aware prompt infrastructure (`PromptSpec.handler`), 4 MCP prompts (`artifact_analyzer`, `relationship_tracer`, `technical_architect`, `report_writer`). 478 tests passing.
- [x] [owner:claude] **Phase 7 complete**: Human-in-the-Loop Pipeline Buttons + Re-run. Extended `PipelineStage` enum from 7→10 stages (`ai_analysis`, `ai_refinement`, `report`). Contextual lookup service (`src/services/contextual_lookup.py` — local-first with SN fallback, Fact caching, reference detection). `AIAnalysisProperties` frozen dataclass (batch_size, context_enrichment). Real ai_analysis handler (enriches ScanResults with local context + usage data). Real ai_refinement handler (3 sub-steps: complex features, per-artifact review, assessment-wide roll-up). Report handler (aggregates statistics/features/recommendations into GeneralRecommendation). Re-run from complete (reset to scans, preserves human edits). 10-step flow bar UI with action buttons and re-run. 91 Phase 7 tests (39 unit + 18 integration + 34 contextual lookup). **496 total tests passing**.

## Completed (session 2026-03-05 — Runtime Telemetry + Resume Hardening)
- [x] [owner:codex] Added AI runtime configuration + budget controls in Integration Properties (`ai.runtime.*`, `ai.budget.*`) with typed loader support (`load_ai_runtime_properties`) and validation tests.
- [x] [owner:codex] Added assessment runtime telemetry stack: `AssessmentRuntimeUsage` model/table, snapshot service (`assessment_runtime_usage.py`), admin DataTable page/API (`/integration-properties/assessment-runtime-usage`), and link from Integration Properties page.
- [x] [owner:codex] Added resumable phase checkpoint stack: `AssessmentPhaseProgress` model/table + service (`assessment_phase_progress.py`), stage-level resume wiring in pipeline handlers, MCP runtime router checkpoint/failure tracking, and tool-level resume progress updates for `generate_observations`, `seed_feature_groups`, `run_preprocessing_engines`, and `run_feature_reasoning`.
- [x] [owner:codex] Added/updated tests for runtime telemetry + resume behavior and reran targeted regression (`76 passed`): `test_assessment_phase_progress.py`, `test_assessment_runtime_usage.py`, `test_mcp_runtime.py`, `test_generate_observations.py`, `test_feature_grouping_pipeline_tools.py`, `test_phase7_pipeline_stages.py`, `test_integration_properties.py`.

## Completed (session 2026-03-05 — Phase 9/10 Delivery)
- [x] [owner:codex] Phase 9 prompt integration completed: added safe rollout helper + prompt extraction path for `artifact_analyzer` (`ai_analysis`), `relationship_tracer` + `technical_architect` (`ai_refinement`), and `report_writer` (`report`) behind `pipeline.use_registered_prompts`.
- [x] [owner:codex] Phase 9 exports completed: canonical export API route is `/api/assessments/{id}/export/{format}` (`xlsx`/`docx`) via `report_export` service; duplicate in-page export action block removed during peer-review cleanup.
- [x] [owner:codex] Phase 9 process recommendations UI completed: added assessment-detail Process Recommendations tab with DataTable endpoints (`/api/assessments/{id}/process-recommendations/*`) and filtering/sorting support.
- [x] [owner:codex] Phase 10 summary dashboard completed: added `/assessments/summary` page for cross-assessment pipeline stage distribution, state distribution, and runtime cost/token/MCP totals.
- [x] [owner:codex] Added targeted + full regression coverage for Phase 9/10 peer-review cycle: `test_phase9_prompt_integration.py` (ai_refinement enabled/disabled/fallback paths), `test_phase9_exports_and_process_ui.py`, `test_pipeline_prompt_integration.py`; full suite currently green (`532 passed`).

## Completed (session 2026-03-05 — Relationship Graph UX)
- [x] [owner:codex] Added graph node deep links for result/artifact/table/assessment/feature navigation and introduced center-artifact development-chain visualization (artifact record, customer update XML, update set, metadata customization, version history with grouped overflow) in relationship graph payload/UI.
- [x] [owner:codex] Added compact development-chain overlap layout in artifact mode and verified live UI rendering via Playwright screenshots on `127.0.0.1:8081` (including link rendering in Selected Node detail panel).
- [x] [owner:codex] Shifted graph toward sample-style ergonomics: expanded canvas mode (default), panel toggles (Filters/Details), directional pan controls + arrow-key panning, `Pop Out` window action, and staircase layering for development-chain cards with off-node/staggered labels for cleaner readability.

## Completed (session 2026-03-05 — Pipeline Stage Order Sync)
- [x] [owner:codex] Reconciled backend pipeline sequencing drift with active docs/UI. **Note (corrected by Claude):** Final correct order is `scans -> engines -> ai_analysis -> observations -> review -> grouping -> ai_refinement -> recommendations -> report -> complete` (engines before ai_analysis). See commits `a337742` (stage order fix) and `6cb7399` (per-assessment analysis_mode). 585 tests passing.

## Completed (session 2026-03-05 — Integration Properties Save UX)
- [x] [owner:codex] Moved save action out of card-local context and into global page actions: added top-right and bottom Save buttons wired to same handler, added explicit dirty-state/no-auto-save messaging, added unsaved-change scope-switch confirmation, browser/in-app leave confirmation (`beforeunload` + link/form confirm), and kept Reload/Reset in Admin Access card. Validation: `tests/test_integration_properties.py` (`26 passed`).

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
