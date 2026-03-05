# 00_admin/insights.md

## Active Decisions
- **Web App = full control plane** (management, visibility, data browsing, MCP setup wizard). **MCP = reasoning plane** (AI judgment: feature grouping, tech debt analysis, disposition recommendations, CSDM service structure). AI reads local DB, uses Snow-flow for supplemental SN data, writes findings back to app tables. See `mcp_app_blueprint.md` for full architecture.
- Canonical workspace is `servicenow_global_tech_assessment_mcp/`; legacy dated workspace is archive-only.
- Rehydration defaults to minimal context (Tier 1) to prevent token waste and context noise.
- Tier 2 is opt-in and limited to durable decisions + recent run-log tail.
- Archive policy update (2026-03-05): stale/implemented markdown plans are moved to `archive/2026-03-05_markdown_cleanup/`; `archive/` is excluded from default agent rehydration/context scans unless explicitly requested.
- `server.py` decomposition is a priority maintainability investment, not optional refactor debt.
- Test hardening (pytest fixtures + smoke coverage) is a prerequisite for safe structural refactors.
- Classification quality must follow Assessment Guide logic, including fallback linkage behavior.
- Large historical narratives belong in archive, not active admin files.
- Shared instruction baseline is now unified across agents: `AGENTS.md` is canonical, `CLAUDE.md` is extension-only, and routing starts from `ACTIVE_PROJECT.md`.
- UI consolidation Group 1 + Group 2 are complete; Group 3A (Jinja filter-card macros) is deferred to backlog as low-value relative to current roadmap.
- Remaining full-app UI modularization opportunities (outside consolidation plan scope) are tracked as backlog in `00_admin/todos.md`, sourced from `02_working/01_notes/codex_full_app_ui_modularization_audit_2026-02-15.md`.
- MCP plan status: Phase 1 protocol support and Phase 5 write-back/read tools are complete (Codex, 2026-02-15), and Phase 4 classification audit/fixes are complete (Claude, 2026-02-15); remaining work is Phase 2/3 prompt/resource content registration.
- Config architecture update: `AppConfig` now supports per-instance overrides (`instance_id`) with global fallback and partial unique indexes; global-only config consumers (MCP runtime, bridge, admin token) explicitly query `instance_id IS NULL`.
- Reasoning Layer Phase 1 baseline is now implemented in-app: deterministic preprocessing engines live in `tech-assessment-hub/src/engines/` (`code_reference_parser`, `structural_mapper`) and are invokable through MCP tool `run_preprocessing_engines`.
- New reasoning persistence tables (`code_reference`, `update_set_overlap`, `temporal_cluster`, `structural_relationship`) use explicit `instance_id` + `assessment_id` foreign keys so grouping signals remain instance-scoped and assessment-scoped.
- Temporal clustering design addendum: `temporal_cluster_member` junction table links clusters to `scan_result` rows with FKs, avoiding membership-only JSON blobs and enabling direct relational queries.
- Update Set Analyzer design decision (2026-03-04): implement artifact-centric linkage (`update_set_artifact_link`) + explainability payloads (`evidence_json`) and two execution modes (`base` deterministic, `enriched` with AI observation context). Default update set is a downgraded signal, not a hard exclusion.
- Reasoning engine config decision (2026-03-04): engines that consume reasoning thresholds must load properties with `instance_id` so per-instance overrides win over global defaults (`load_reasoning_engine_properties(..., instance_id=assessment.instance_id)`).
- Reasoning Layer Phase 2 execution status (2026-03-04): all six deterministic engines are wired into `run_preprocessing_engines`, and both agents approved full regression after cross-review.
- Reasoning Layer follow-on plan decision (2026-03-04): UI signal surfacing and feature hierarchy are now an explicit execution phase, not implicit backlog; canonical plan is `tech-assessment-hub/docs/plans/2026-03-04-reasoning-layer-phase3-ui-ai-feature-orchestration.md`.
- Feature grouping rule decision (2026-03-04): only customized records can be persisted as feature members; non-customized records may be linked as context evidence only.
- Phase 3 planning finalization (2026-03-04): Claude review addendums A1-A5 are accepted into the plan baseline (legacy `group_by_feature` replacement path, unified grouping-signals payload, one-pass `run_feature_reasoning` contract, ungrouped bucket requirement, and signals-tab UI layout).
- Phase 3 Codex implementation decision (2026-03-04): deterministic seeding now runs through `seed_feature_groups` (engine-signal graph clustering) and active MCP registration no longer includes legacy `group_by_feature`.
- Reasoning loop control decision (2026-03-04): `run_feature_reasoning` executes exactly one pass per call and persists convergence state in `feature_grouping_run`; client/prompt controls iterative looping.
- Recommendation persistence decision (2026-03-04): structured OOTB replacement guidance is persisted via `feature_recommendation` and surfaced through both MCP (`upsert_feature_recommendation`) and app APIs (`/api/features/{id}/recommendations`), then embedded in hierarchy/evidence payloads.
- Reasoning property decision (2026-03-04): feature-loop convergence controls are instance-overridable (`reasoning.feature.max_iterations`, `reasoning.feature.membership_delta_threshold`, `reasoning.feature.min_assignment_confidence`).
- UI hardening decision (2026-03-04): recommendation type labels in P4C rendering paths must be escaped before HTML insertion (`FeatureHierarchyTree.js`, `result_detail.html`) to avoid script/markup injection from malformed persisted values.
- Phase 5 addendum decision (2026-03-04): pipeline orchestration APIs use plural routes and a dedicated `pipeline` payload in `/api/assessments/{id}/scan-status` (no scan-job contract overload).
- Observation config decision (2026-03-04): observation controls are instance-overridable via `SECTION_OBSERVATIONS` and include `observations.max_usage_queries_per_result` (replacing `usage_query_limit`).
- Observation generation execution boundary (2026-03-04): `generate_observations` runs deterministic baseline synthesis + optional usage-count enrichment server-side; prompt/resources remain orchestration guidance for external MCP clients.
- Recommendation-stage semantics (2026-03-04): pipeline stage `recommendations` runs `run_feature_reasoning` verification passes; recommendation row creation remains explicit via `upsert_feature_recommendation`.
- Phase 5 cross-review status (2026-03-04): Claude UI/prompt tranche (`P5A-ui`, `P5C-prompts`, `P5D-ui`, `P5E`) is Codex-approved; automated validation remains green (`29` targeted Phase 5 tests, `328` full regression).
- Integration smoke caveat (2026-03-04): API routing/start-cancel paths are healthy, but live ServiceNow fetch paths are blocked when local credential decryption fails (`cryptography.fernet.InvalidToken` from `decrypt_password`). Treat `connection_status=connected` as stale until `/instances/{id}/test` passes with current `data/.encryption_key`.
- Job Log metric semantics (2026-03-04): unified `rows_inserted` column is a processed-count metric for preflight/dictionary/assessment runs (e.g., `records_pulled`, `queue_completed`), not guaranteed net-new row inserts. UI label updated to "Rows/Items Processed" to avoid duplicate-data false positives.
- End-to-end validation status (2026-03-04): P1–P6 validation executed with phase-grouped pytest suites (all green), full regression (`330 passed`), MCP prompt/resource/runtime suites green (`56 passed`), and live pipeline progression verified on `pdi` assessment 19 (`scans -> engines -> observations -> review -> grouping -> recommendations -> complete`) including review-gate enforcement and review-status API updates.
- Phase 6 Task 3 UI contract (2026-03-04): `admin_best_practices.html` is DataTable-based with static client schema and expects `GET /api/best-practices`, `POST /api/best-practices`, and `PUT /api/best-practices/{id}`; backend wiring should preserve this path contract to avoid page-script drift.
- QA durability decision (2026-03-05): preflight `data_pull` and `dict_pull` status surfaces now auto-finalize orphaned active durable runs when no worker thread is alive and heartbeat age exceeds grace (30s), preventing persistent "running" UI/modals and stale Job Log states.
- AI runtime control decision (2026-03-05): model execution mode/provider/model and budget guardrails are first-class integration properties (`ai.runtime.*`, `ai.budget.*`) with per-instance overrides and typed loader (`load_ai_runtime_properties`).
- Runtime telemetry decision (2026-03-05): `assessment_runtime_usage` is the canonical per-assessment cost/perf telemetry surface (results/features/recommendations counts, MCP call splits, token usage, estimated cost, runtime mode/model), exposed at `/integration-properties/assessment-runtime-usage`.
- Resume checkpoint decision (2026-03-05): `assessment_phase_progress` is the canonical resumable cursor per assessment+phase. Pipeline stages and MCP tools update `resume_from_index`/`completed_items` at chunk boundaries and use explicit failure statuses (`blocked_rate_limit`, `blocked_cost_limit`, `failed`) to support deterministic rehydrate/resume.
- Phase sequencing decision (2026-03-05): prompt integration is promoted from deferred Phase 10 work into Phase 9 scope (Option A), and will ship together with Excel/Word exports + process recommendations UI after Phase 8A stabilization/validation gate.
- Phase 9 execution decision (2026-03-05): keep existing JSON contracts in stage fields and append registered-prompt context under additive keys (`registered_prompt`, `prompt_context`, `registered_prompt_error`) so enabling prompt integration is reversible and backward compatible with existing consumers/tests.
- Phase 9 export contract decision (2026-03-05): canonical download route is `/api/assessments/{id}/export/{format}` (`xlsx`/`docx`) backed by `src/services/report_export.py`; duplicate export routes were removed during cross-agent review to avoid drift.
- Phase 10 scope decision (2026-03-05): summary dashboard delivered at `/assessments/summary` as cross-assessment operational view (pipeline stage/state distribution + cost/token/MCP aggregate telemetry) while deep per-assessment metrics remain on `/integration-properties/assessment-runtime-usage`.
- Ai-refinement durability decision (2026-03-05): phase progress checkpoints now persist after sub-step 1 (complex-feature analysis) and sub-step 2 (mode-A artifact review), so downstream errors do not discard completed intermediate work.

### ARCHITECTURE: Dynamic Registry is Canonical for ALL SN Table Mirroring
- **`SnTableRegistry` + `SnFieldMapping`** (in `models_sn.py`) is the ONE system for mirroring any ServiceNow table — CSDM, preflight, custom, or future modules. Renamed from `Csdm*` prefix on 2026-02-15.
- **All new SN tables MUST use this system.** Never create new hardcoded SQLModel classes for SN mirror data. Use `ensure_schema_exists()` → dictionary pull → dynamic DDL → `upsert_batch()`.
- **Physical mirror tables are shared across instances** (one `sn_sys_user` table for all instances). Data is partitioned by `_instance_id`. Columns are the union of all instances' fields.
- **Registry + field mappings are instance-specific.** Each instance has its own `CsdmTableRegistry` row and `CsdmFieldMapping` set per table. Display/query always scopes to the instance's mappings.
- **Schema drift between instances is handled** by `ensure_schema_exists()` calling `alter_mirror_table()` to ADD missing columns before every ingestion (even on early-return path).
- **Old static preflight models** (`update_set`, `instance_plugin`, `plugin_view`, `metadata_customization` in `models.py`) are legacy. Phase 4 migrates them to the dynamic system. Do not extend them.
- **The `source` column** distinguishes table origin: `"csdm"` | `"preflight"` | `"custom"`. UI groups by this.
- **Key files**: `src/services/csdm_ingestion.py` (registry creation, ingestion), `src/services/csdm_ddl.py` (DDL engine), `src/models_sn.py` (registry/mapping models), `src/web/routes/dynamic_browser.py` (browse API/UI).

### ARCHITECTURE: Reusable Components & User-Configurable Properties
- **Full engineering principles are in `AGENTS.md` > "Engineering Principles" section.** All agents must follow them.
- **Reusable frontend components**: `DataTable.js` (any tabular data), `ConditionBuilder.js` (any filter UI). Do NOT manually build HTML tables — use these.
- **User-configurable properties**: Follow the `integration_properties.py` pattern (define in `PROPERTY_DEFINITIONS`, store in `AppConfig` table, expose via properties UI page). Hardcoded-only for true constants.
- **Template components**: Extract shared patterns to `templates/components/` includes (modals, badges, form groups).
- **Acknowledge refactor debt**: When new work reveals existing duplication, log it in `todos.md` Backlog and mention in `run_log.md`. Never silently add tech debt.
- **Replace-then-remove**: After refactoring old code to use a new component, delete the old duplicated code. No commented-out code, no underscore renames. Deletion only after automated tests pass AND human manually tests the affected flows. `ColumnPicker.js` is now a standalone component (extracted from DataTable.js).

### ARCHITECTURE: Durable Job Tracking (Codex #2 Phase 1 + Phase 2)
- **`JobRun` + `JobEvent`** (in `models.py`) are now the durable lifecycle system for background integration workflows.
- **Covered workflows**: preflight data pulls (`data_pull`), dictionary pulls (`dict_pull`), CSDM ingestion (`csdm_ingest`), and assessment scan workflows (`assessment_scan`).
- **`InstanceDataPull.run_uid`** correlates preflight pull rows to parent runs; dictionary/CSDM/assessment workflows use `job_event` for per-step traceability.
- **Startup recovery generalized**: server startup now marks stale `queued`/`running` runs failed across all job types (not just data pulls), appending restart-interruption events.
- **Status APIs**: preflight `/api/instances/{id}/data-status`, dictionary `/api/instances/{id}/dictionary-pull-status`, CSDM `/csdm/api/status/{instance_id}`, and assessment `/api/assessments/{id}/scan-status` now read durable run state as primary or fallback status source.
- **Review finding**: Datetime serialization uses naive `.isoformat()` (no Z suffix). Our `formatDate()` handles this by detecting missing timezone info and treating as UTC. No dedicated unit tests for run lifecycle — logged as backlog gap.

### ARCHITECTURE: Display Timezone Property
- **`general.display_timezone`** in `integration_properties.py` — IANA timezone string (default `America/New_York`). Stored in `AppConfig`.
- **Properties page** now grouped by `section` field: "General" at top, "Integration / Fetch" below. `PropertyType` extended with `"select"` for dropdown rendering.
- **JS-rendered dates**: `app.js` fetches timezone once from `/api/display-timezone`, caches in `window.TAH_DISPLAY_TIMEZONE`. `formatDate()` uses `Intl.DateTimeFormat` with configured timezone. DataTable.js auto-detects `kind:"date"` columns and formats them.
- **Server-rendered dates**: Jinja2 `.strftime()` calls still show raw UTC — Jinja2 filter is a backlog item.
- **Watermarks are NOT affected**: They're `datetime` objects storing `MAX(sys_updated_on)` from local DB (UTC). Used correctly for delta pull decisions.

### ARCHITECTURE: VH Workflow Optimization (2026-02-16)
- **Concurrent preflight**: Types in `PREFLIGHT_CONCURRENT_TYPES` property (default: `version_history,customer_update_xml`) each get their own thread with own `Session(engine)` + `ServiceNowClient`. Non-concurrent types run sequentially in main thread. Configurable via integration properties UI.
- **Two-phase proactive VH pull** (on instance add/test): Phase 1 = `state=current` only (fast, sets event when done). Phase 2 = all states with `order_by=state,sys_recorded_at` (backfill, runs in background after event).
- **VH sort order**: When pulling all states, `order_by="state,sys_recorded_at"` ensures "current" records arrive before "previous" (alphabetical sort of state values).
- **VH state filter propagation**: `version_state_filter` flows through `_build_assessment_preflight_plan` → `_estimate_expected_total` → `build_version_history_query` so local/remote counts use same filter for delta decisions.
- **Read-only VH event access**: Only `_start_proactive_vh_pull` creates `_VH_EVENTS` entries. All other code uses `_VH_EVENTS.get()` (read-only) to avoid phantom events causing hangs.
- **Classification uses older VH**: `_lookup_earliest_version_history_local` queries ALL states (no filter) for fallback classification. This is intentional — the earliest version may be in any state.
- **Key files**: `src/server.py` (concurrent preflight, proactive pull, VH event handling), `src/services/data_pull_executor.py` (state filter in expected total), `src/services/sn_client.py` (sort order in `pull_version_history`).

### Known Refactor Debt (updated 2026-02-15)
- ~~`data_browser.js` duplicates DataTable.js~~ — RESOLVED (Phase 4 complete)
- ~~Templates repeat modal/badge/form-group patterns~~ — RESOLVED (Codex #10)
- ~~`sn_client.py` + `sn_dictionary.py` hardcode timeouts~~ — RESOLVED (Claude #1+#11)
- ~~JS page sizes inconsistent~~ — RESOLVED (DataTable.js selector)
- ~~Rename Csdm* prefix~~ — RESOLVED (now Sn* everywhere)
- `analytics.js` manually builds pivot tables — acceptable as-is (pivot layout incompatible with DataTable)
- `integration_properties.js` renders own table HTML — acceptable as-is (editable key-value editor)

### ARCHITECTURE: MCP Prompts + Resources for Domain Knowledge Delivery
- **MCP has three primitives**: Tools (actions, already built — 15+ registered), **Prompts** (behavioral instructions the AI loads before reasoning), **Resources** (on-demand reference documents the AI reads by URI).
- **Prompts = "how the AI abides by" methodology**: `tech_assessment_expert` prompt loads classification rules, disposition framework, multi-pass methodology, tool usage guidance. Like switchable expert modes.
- **Resources = "how the AI is aware of" documentation**: `assessment://guide/classification-rules`, `assessment://guide/grouping-signals`, etc. Token-efficient — AI pulls only when needed, not upfront.
- **Protocol gap**: Current `jsonrpc.py` only handles `initialize`, `tools/list`, `tools/call`. Adding `prompts/list`, `prompts/get`, `resources/list`, `resources/read` is Phase 1 of the MCP plan.
- **Pattern**: `PromptSpec` + `ResourceSpec` dataclasses mirroring existing `ToolSpec` pattern. Same lazy registry approach.
- **Key files**: `src/mcp/protocol/jsonrpc.py` (protocol), `src/mcp/registry.py` (registries), new `src/mcp/prompts/` and `src/mcp/resources/` directories.
- **Full plan**: `03_outputs/plan_mcp_tools_classification_quality_2026-02-15.md`

### ARCHITECTURE: Classification Quality Gaps (4 identified)
- **Gap 1 — Current-version-first bias**: `_classify_origin()` returns `ootb_untouched` if current version = Store/Upgrade, without checking if customer versions exist in history. Assessment guide says reverted-to-OOTB records with customer history → `modified_ootb`.
- **Gap 2 — metadata_customization vs customer versions**: Code uses `has_metadata_customization` as signal for modified_ootb. Guide also accepts "any customer versions exist" as alternative signal.
- **Gap 3 — `changed_baseline_now` unused**: Stored on ScanResult but not input to `_classify_origin()`. Guide uses it as a signal.
- **Gap 4 — V3 user existence check**: Guide v3 adds `created_by_in_user_table` for unknown records. Not implemented.
- **File**: `src/services/scan_executor.py:457`

### ARCHITECTURE: Phase 7 — 10-Stage Pipeline with AI Handlers + Re-run
- **PipelineStage extended to 10**: scans → ai_analysis → engines → observations → review → grouping → ai_refinement → recommendations → report → complete. 3 new AI stages added before engines and after grouping.
- **Human-Edit-as-Context principle**: AI checks for existing human content at every stage and never overwrites — only refines. AI may rewrite human content for better flow/grammar/spelling while preserving the human's core point.
- **Local-first contextual enrichment**: `src/services/contextual_lookup.py` — 6 functions: `detect_references`, `check_local_table_data`, `lookup_reference_local`, `lookup_reference_remote`, `resolve_references`, `gather_artifact_context`. Checks Fact cache → local DB (TableDefinition, ScanResult, UpdateSet) → SN via sn_client if allowed.
- **Enrichment modes controlled by property**: `observations.context_enrichment` — "auto" (default, local first + remote fallback), "always" (always remote), "never" (local only).
- **Reference detection**: Regex patterns for INC, CHG, RITM, REQ, PRB, TASK, WO, WOTASK/WOT, KB with longest-prefix-first alternation.
- **Fact caching**: `_FACT_MODULE = "tech_assessment"`, 12hr TTL, `topic_type="reference_lookup"`. Prevents redundant SN queries.
- **ai_analysis handler**: Loads `AIAnalysisProperties`, queries customized ScanResults, calls `gather_artifact_context()`, writes JSON to `sr.ai_observations`.
- **ai_refinement handler**: 3 sub-steps — (1) complex features (5+ members) get `Feature.ai_summary`, (2) Mode A per-artifact review enriches each ScanResult, (3) Mode B assessment-wide technical findings stored as `GeneralRecommendation(category="technical_findings")`.
- **Report handler**: Aggregates statistics, features, recommendations, review status into `GeneralRecommendation(category="assessment_report")`. Replaces existing report on re-run.
- **Re-run from complete**: `rerun: true` flag on advance-pipeline endpoint → resets to `scans` stage then immediately starts `ai_analysis` job. Preserves all Features, GeneralRecommendations, and human edits.
- **Auto-advance config**: `_PIPELINE_STAGE_AUTONEXT` dict defines which stages auto-advance after completion (e.g., ai_analysis→engines, ai_refinement→recommendations, report→complete).
- **Key files**: `src/server.py` (stage config + handlers), `src/services/contextual_lookup.py` (enrichment), `src/services/integration_properties.py` (AIAnalysisProperties), `src/web/templates/assessment_detail.html` (10-step flow bar).

### ARCHITECTURE: Resume + Telemetry Hardening (2026-03-05)
- **Resumable progress table**: `AssessmentPhaseProgress` (`assessment_phase_progress`) stores per-phase status, totals, `resume_from_index`, checkpoint JSON, and terminal/error state.
- **Checkpoint service**: `src/services/assessment_phase_progress.py` (`start_phase_progress`, `checkpoint_phase_progress`, `complete_phase_progress`, `fail_phase_progress`) is the single update path used by pipeline + MCP runtime.
- **Stage resume semantics**: `ai_analysis`, `observations`, and `recommendations` read prior checkpoint cursors and continue from saved index/pass counters instead of replaying already-completed work.
- **Failure-classification semantics**: stage/tool failures are normalized into `blocked_cost_limit`, `blocked_rate_limit`, or `failed`, preserving a resumable state marker for operator rehydrate.
- **Telemetry snapshot table**: `AssessmentRuntimeUsage` (`assessment_runtime_usage`) stores run metadata, pipeline/result aggregates, MCP call split (`local`, `servicenow`, `local_db`), token counters, and estimated cost.
- **Telemetry refresh service**: `src/services/assessment_runtime_usage.py` updates snapshots during stage transitions and runtime tool execution, and supports full refresh for admin table reads.
- **Admin visibility path**: integration properties page links to `/integration-properties/assessment-runtime-usage`, and records are served by `/api/integration-properties/assessment-runtime-usage/*` (DataTable schema + records endpoints).

### ARCHITECTURE: Phase 6 — MCP Skills/Prompts Library + Best Practices
- **BestPractice model**: `BestPractice` + `BestPracticeCategory` enum (14 categories covering ServiceNow domains). 41 seed checks auto-populated at DB creation.
- **Admin CRUD API**: `GET/POST/PUT /api/best-practices` + `/admin/best-practices` list page with DataTable.
- **Session-aware prompt infrastructure**: `PromptSpec.handler` callback replaces static `arguments` — enables prompts to dynamically load assessment context, scan results, and best practices at invocation time.
- **4 MCP prompts**: `artifact_analyzer` (per-artifact deep analysis), `relationship_tracer` (cross-artifact dependency tracing), `technical_architect` (dual-mode full/focused review), `report_writer` (assessment deliverable generation). All registered in `PROMPT_REGISTRY`.
- **Key files**: `src/models.py` (BestPractice), `src/mcp/prompts/` (4 prompt modules), `src/mcp/registry.py` (registration).

## Open Questions
- (none currently — all resolved this session)

### AI REASONING PIPELINE: Domain Methodology Documented
- **Full methodology**: `02_working/01_notes/ai_reasoning_pipeline_domain_knowledge.md` — how a human expert does technical assessments. Covers: iterative multi-pass process, grouping indicators (temporal proximity, update set analysis, cross-US version history, reference graphs), key app file types, common finding patterns (OOTB alternatives, platform maturity gaps, bad implementation, competing config), token efficiency strategy (engines pre-stage data, AI does judgment only), and data model implications (results, features, general technical recommendations).
- **Grouping signals**: `02_working/01_notes/grouping_signals.md` — 8 signal categories (update set cohorts, table affinity, naming conventions, code references, metadata parent/child, temporal proximity, reference field values, application/package), confidence scoring weights, 4-phase clustering algorithm (initial clusters → merge by strong signals → split by weak signals → orphan assignment), cluster output JSON schema. Restored from archive 2026-02-15.
- **Snow-flow analysis**: `02_working/01_notes/snow_flow_analysis/` — 10-part deep audit of 410+ tools across 84 domains. Tool mapping matrix (doc 09) identifies 30 EXTRACT_NOW domains / 196 tools. Integration plan (doc 10) defines 5-wave approach.
- **Key insight**: Assessment is iterative and multi-pass. Observations on individual results AND features get updated as context grows. A single app file can belong to multiple features. Update set cross-referencing is a critical grouping signal. Engines should handle deterministic pre-staging; AI handles judgment, interpretation, and recommendations.

## Durable References
- Blueprint: `servicenow_global_tech_assessment_mcp/02_working/01_notes/mcp_app_blueprint.md`
- AI reasoning methodology: `servicenow_global_tech_assessment_mcp/02_working/01_notes/ai_reasoning_pipeline_domain_knowledge.md`
- Grouping signals & clustering: `servicenow_global_tech_assessment_mcp/02_working/01_notes/grouping_signals.md`
- Assessment classification guide: `servicenow_global_tech_assessment_mcp/01_source_data/01_reference_docs/assessment_guide_and_script_v3_pv.md`
- Snow-flow analysis: `servicenow_global_tech_assessment_mcp/02_working/01_notes/snow_flow_analysis/00_index.md`
- Validation evidence: `servicenow_global_tech_assessment_mcp/02_working/01_notes/stabilization_validation.md`
- Delivery index: `servicenow_global_tech_assessment_mcp/03_outputs/00_delivery_index.md`
- MCP plan: `servicenow_global_tech_assessment_mcp/03_outputs/plan_mcp_tools_classification_quality_2026-02-15.md`
- Modularization handoff: `servicenow_global_tech_assessment_mcp/03_outputs/temporary_architecture_modularization_handoff_2026-02-15.md`

## Archive Pointer
Historical batch-by-batch narratives were archived externally on 2026-02-14:
`/Users/pviglianti/Library/Mobile Documents/com~apple~CloudDocs/Cloud Archive/2026-02-14_rehydration_guardrails/servicenow_global_tech_assessment_mcp/00_admin/insights.md`
