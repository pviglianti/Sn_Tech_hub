# 00_admin/context.md

## Rehydrate Snapshot
- Active project: `servicenow_global_tech_assessment_mcp/`
- Primary objective: stabilize and evolve `tech-assessment-hub` as an MCP-first ServiceNow assessment platform.
- Current execution focus: Phase 11 unified execution planning is active (`03_outputs/plan_phase11_unified_feature_ownership_and_legacy_cleanup_2026-03-05.md`) with dedicated cross-agent trackers (`00_admin/phase11_coordination.md`, `00_admin/phase11_chat.md`) while legacy post-Phase-7/Phase-9/10 hardening remains in validation/closeout.
- Cross-agent model: Codex + Claude share state through `todos.md` and `run_log.md`.
- Rehydration default: Tier 1 only (`context:Rehydrate Snapshot` + `todos:Now`).
- Deeper continuity: Tier 2 only when needed (`insights:Active Decisions` + tail of `run_log`).
- Canonical codebase: `tech-assessment-hub/`.
- Canonical admin memory: `servicenow_global_tech_assessment_mcp/00_admin/`.
- Local markdown archive (2026-03-05): `archive/2026-03-05_markdown_cleanup/` for stale/implemented plans; excluded from default rehydration unless explicitly requested.
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

## Current Status (2026-03-05)
- **SN API centralization sprint complete** (Orchestrator, 2026-03-05): Multi-agent orchestrated sprint — 3 tasks (core infrastructure, consolidation, bail-out logic), 3 devs, 3 reviewers (all APPROVED), 3 cross-testers (all PASS). 12 files changed (2,760 ins / 206 del). **713 total tests passing** (217 new above 496 baseline). Commit `967161a` on `feature/sn-api-centralization`. Refactor debt logged: bail-out boilerplate (~25 lines × 11 handlers), `csdm_ingestion.py` future consolidation, `display_value=False` silent drop in Task 2 modules.
- **Phase 11 unified plan established** (Codex, 2026-03-05): consolidated Codex+Claude architecture/sequence for AI-owned feature writes + legacy cleanup in `03_outputs/plan_phase11_unified_feature_ownership_and_legacy_cleanup_2026-03-05.md`; created dedicated coordination/chat files (`00_admin/phase11_coordination.md`, `00_admin/phase11_chat.md`) per protocol.
- **Phase 7 complete** (Claude, 2026-03-05): Human-in-the-Loop Pipeline Buttons + Re-run. Extended pipeline from 7 to 10 stages (`ai_analysis`, `ai_refinement`, `report`). Added contextual lookup service (local-first, SN fallback), real AI stage handlers with context enrichment, re-run from complete, 10-step flow bar UI. 91 Phase 7 tests, **496 total tests passing**.
- **Phase 6 complete** (Claude, 2026-03-05): MCP Skills/Prompts Library + Best Practice Knowledge Base. Added `BestPractice` model with 41 seed checks, admin CRUD API, 4 MCP prompts (`artifact_analyzer`, `relationship_tracer`, `technical_architect`, `report_writer`) with session-aware prompt infrastructure. 478 tests at completion.
- **Phases 1-5 complete** (Codex + Claude, 2026-03-04): Reasoning Layer (6 engines, grouping signals, feature hierarchy), Pipeline Orchestration (7-stage flow bar, observation generation, review gates), MCP protocol/tools/prompts/resources, classification quality audit, durable job tracking, modularization sprint, dynamic table browser, VH workflow optimization. 330 tests at Phase 5 completion.
- **Post-Phase-7 hardening complete** (Codex, 2026-03-05): added `AssessmentRuntimeUsage` telemetry table/service/page, `AssessmentPhaseProgress` resumable checkpoint table/service, AI runtime mode/provider/model + budget properties, and stage/tool wiring to persist progress + classify `blocked_rate_limit` / `blocked_cost_limit` failure states for resumable recovery.
- **Phase 9/10 implementation complete** (Codex + Claude, 2026-03-05): wired registered MCP prompts into pipeline handlers behind `pipeline.use_registered_prompts`, standardized report exports on `/api/assessments/{id}/export/{format}` (`xlsx`/`docx`), added assessment-detail Process Recommendations tab (`/api/assessments/{id}/process-recommendations/*`), and added cross-assessment summary dashboard at `/assessments/summary`.
- **Relationship graph visualization expanded** (Codex, 2026-03-05): added per-node deep links (result/artifact/table/assessment/graph/data-record), center-artifact development-chain nodes (artifact record, customer update XML, update set, metadata customization, version history with grouped overflow), sample-style graph ergonomics (expanded canvas default, Filters/Details panel toggles, directional pan buttons + arrow-key panning, pop-out window action), staircase dev-chain layering with staggered off-node labels for improved readability, and new-tab launch behavior from result/table/feature hyperlinks.
- **Hardening regression status**: targeted suites green (`76 passed`, 2026-03-05): `test_mcp_runtime.py`, `test_generate_observations.py`, `test_feature_grouping_pipeline_tools.py`, `test_phase7_pipeline_stages.py`, `test_assessment_phase_progress.py`, `test_assessment_runtime_usage.py`, `test_integration_properties.py`.
- **Phase 8A/9 planning lock** (Codex + Claude, 2026-03-05): cross-agent plan approved in `phase3_planning_chat.md`. Phase 8A executes stabilization + live validation first; Phase 9 scope is now explicitly: (1) pipeline prompt integration (pulled forward), (2) Excel/Word exports, (3) process recommendations UI.
- **Regression status**: full suite green (`532 passed`, 2026-03-05) after peer-review remediation (ai_refinement prompt-path tests + sub-step checkpoint commits).
- **Branch**: `3_5_2026_TA_PostP6andMCPskills` — 10 Phase 7 commits + Phase 6 commits on top of main.
- Next priorities: (1) close remaining cross-agent `REVIEW_PASS`/`APPROVED` checkpoints in `phase3_planning_chat.md`, (2) human live QA of pipeline end-to-end with real assessment data, (3) runtime telemetry + assessment summary/dashboard validation on live runs, (4) resume/recovery validation by interrupting mid-stage and confirming checkpoint rehydrate, (5) human validation of export files and process-recommendations tab behavior.
- Next planned feature definition: API-access fallback table import utility plan created at `03_outputs/plan_api_access_fallback_table_import_utility_2026-03-05.md` and linked from `todos.md` (instance/table-scoped upload when API pulls are rejected/blocked).
- Rehydration guardrails are enforced. Instruction standard is `AGENTS.md` + `CLAUDE.md` + `ACTIVE_PROJECT.md`.
