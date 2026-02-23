# 00_admin/context.md

## Rehydrate Snapshot
- Active project: `servicenow_global_tech_assessment_mcp/`
- Primary objective: stabilize and evolve `tech-assessment-hub` as an MCP-first ServiceNow assessment platform.
- Current execution focus: MCP knowledge layer complete → AI reasoning pipeline + end-to-end validation.
- Cross-agent model: Codex + Claude share state through `todos.md` and `run_log.md`.
- Rehydration default: Tier 1 only (`context:Rehydrate Snapshot` + `todos:Now`).
- Deeper continuity: Tier 2 only when needed (`insights:Active Decisions` + tail of `run_log`).
- Canonical codebase: `tech-assessment-hub/`.
- Canonical admin memory: `servicenow_global_tech_assessment_mcp/00_admin/`.
- Historical high-volume notes/logs were archived externally on 2026-02-14.
- Archive location: `/Users/pviglianti/Library/Mobile Documents/com~apple~CloudDocs/Cloud Archive/2026-02-14_rehydration_guardrails`.

## Goal
Design and build a production-ready ServiceNow assessment platform where:
- **Web app** is the full control plane (management, data collection, browsing, configuration, MCP setup wizard).
- **MCP + AI** is the reasoning plane (feature grouping, tech debt analysis, disposition recommendations, CSDM service structure). AI reads local DB (token-efficient), uses Snow-flow tools for supplemental SN data, writes findings back to app tables.
- **Snow-flow tools** are reused for AI reasoning support AND as customer-facing bonus features.
- Deterministic engines handle counts/patterns; LLMs handle judgment, reasoning, and recommendations only.

## Scope
IN SCOPE:
- Global-scope technical assessment workflows.
- Hybrid MCP runtime and tool reliability.
- Data quality, classification accuracy, and workflow UX reliability.
- CSDM data foundations integration into the same platform.

OUT OF SCOPE (current cycle):
- Multi-tenant SaaS production rollout.
- Full scoped-app assessment coverage.
- Security penetration testing.

## Constraints
- Files are durable memory; chat is transient.
- Use `ACTIVE_PROJECT.md` before any rehydration.
- Keep admin files under rollover limits (see `AGENTS.md`).
- Use explicit file paths for traceability.

## Current Status (2026-02-15)
- **Modularization sprint complete**: server.py decomposed (6 routers), DataPullSpec registry, integration properties wired, DataTable.js migration, template components, Sn* rename. 87 tests passing.
- **Dynamic Table Browser complete** (Phases 1-4): universal browse/record/index pages, DataTable.js + ConditionBuilder.js + ColumnPicker.js, backed by `SnTableRegistry` + `SnFieldMapping`.
- **Durable job tracking Phase 1 + Phase 2 complete** (Codex): `job_run` + `job_event` lifecycle persistence now covers data pulls, dictionary pulls, CSDM ingestion, and assessment scan workflows; startup recovery marks stale queued/running runs failed across all job types.
- **Display timezone property added** (Claude): `general.display_timezone` in "General" section of properties page (default EST). JS-rendered dates in DataTable.js and `formatDate()` respect configured timezone. Server-rendered Jinja2 dates still raw UTC (backlog).
- **Architectural decision documented**: Dynamic registry (`SnTableRegistry` + `SnFieldMapping` in `models_sn.py`) is the ONE canonical system for ALL SN table mirroring. No new static models.
- **Blueprint corrected**: MCP = reasoning plane (AI judgment), Web App = control plane (management). See `mcp_app_blueprint.md`.
- **MCP Tools + Classification Quality plan approved** (Claude, 2026-02-15): 5-phase plan — Phase 1: MCP Prompts + Resources protocol support, Phase 2: assessment methodology prompts, Phase 3: reference resources, Phase 4: classification quality audit (4 gaps identified in `_classify_origin`), Phase 5: 5 missing assessment write-back tools. Deliverable: `03_outputs/plan_mcp_tools_classification_quality_2026-02-15.md`.
- **MCP Plan execution update (Codex, 2026-02-15)**: Phase 1 and Phase 5 are complete. JSON-RPC now supports prompts/resources endpoints, and 5 new assessment tools are registered (`update_scan_result`, `update_feature`, `get_feature_detail`, `get_update_set_contents`, `save_general_recommendation`) with `GeneralRecommendation` model added.
- **Instance-scoped config overrides complete (Codex, 2026-02-15)**: `AppConfig` now supports optional `instance_id` scope with global fallback, legacy schema migration, and partial unique indexes (`global key`, `instance+key`). Integration properties UI/API now supports Global vs per-instance scope selection.
- **UI consolidation status**: Group 1/2 tasks are complete; Group 3A (Jinja filter-card macros) is deferred as low ROI. Remaining full-app UI modularization opportunities are now tracked as backlog tasks in `00_admin/todos.md`.
- **MCP Plan Phase 4 complete** (Claude, 2026-02-15): Classification quality audit — fixed `_classify_origin` Gaps 1-3 (OOB+customer→modified_ootb, wired `changed_baseline_now`, unknown vs unknown_no_history distinction). Gap 4 deferred (data enrichment). 22 classification tests, 119 total pass.
- **MCP Plan Phases 2+3 complete** (Claude, 2026-02-15): 2 assessment methodology prompts (`tech_assessment_expert`, `tech_assessment_reviewer`) + 6 reference resources (classification rules, grouping signals, finding patterns, app file types, scan-result schema, feature schema). All registered in `PROMPT_REGISTRY` / `RESOURCE_REGISTRY` with auto-population at module load. 28 new tests (12 prompt + 16 resource), 147 total pass.
- **ALL 5 MCP plan phases COMPLETE.** Protocol (Codex), prompts (Claude), resources (Claude), classification audit (Claude), write-back tools (Codex). 150 total tests passing.
- **Expert prompt updated to match PV's actual assessment flow** (Claude, 2026-02-15): Depth-first temporal order (oldest-first by `sys_updated_on`), rabbit holes only into other customized records (not OOTB untouched), `query_live` only for more info on customized artifacts, catch-all buckets by app file class type. Source: `02_working/01_notes/my flow for analysis tech`.
- **Architectural decisions for reasoning pipeline** (pending):
  - Deterministic engines as on-demand MCP tools first (simpler), pre-compute later if perf requires
  - Rabbit hole priorities: modular/adjustable (config-driven, not hardcoded)
  - Catch-all labels: table mapping app file class → display label (e.g., `sys_dictionary` → "Form Fields")
- **VH workflow optimization complete (Claude, 2026-02-16)**: 7 fixes — phantom VH event (read-only lookup), VH 2M full-pull bug (state filter propagation), concurrent preflight (configurable via `PREFLIGHT_CONCURRENT_TYPES`), two-phase proactive VH pull (current-first → event → backfill), sort order for VH pulls (`state,sys_recorded_at`), generic concurrent preflight worker threads. 203 tests passing.
- Next priorities: (1) End-to-end test with real assessment data using current prompts+tools, (2) deterministic pre-staging engines (update set overlap, temporal clustering, reference graph, table co-location), (3) rabbit hole priority config, (4) catch-all label table.
- Rehydration guardrails are enforced. Instruction standard is `AGENTS.md` + `CLAUDE.md` + `ACTIVE_PROJECT.md`.
