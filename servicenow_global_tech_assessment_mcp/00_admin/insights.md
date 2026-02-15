# 00_admin/insights.md

## Active Decisions
- **Web App = full control plane** (management, visibility, data browsing, MCP setup wizard). **MCP = reasoning plane** (AI judgment: feature grouping, tech debt analysis, disposition recommendations, CSDM service structure). AI reads local DB, uses Snow-flow for supplemental SN data, writes findings back to app tables. See `mcp_app_blueprint.md` for full architecture.
- Canonical workspace is `servicenow_global_tech_assessment_mcp/`; legacy dated workspace is archive-only.
- Rehydration defaults to minimal context (Tier 1) to prevent token waste and context noise.
- Tier 2 is opt-in and limited to durable decisions + recent run-log tail.
- `server.py` decomposition is a priority maintainability investment, not optional refactor debt.
- Test hardening (pytest fixtures + smoke coverage) is a prerequisite for safe structural refactors.
- Classification quality must follow Assessment Guide logic, including fallback linkage behavior.
- Large historical narratives belong in archive, not active admin files.
- Shared instruction baseline is now unified across agents: `AGENTS.md` is canonical, `CLAUDE.md` is extension-only, and routing starts from `ACTIVE_PROJECT.md`.

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
