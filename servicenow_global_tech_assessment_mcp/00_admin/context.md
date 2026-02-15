# 00_admin/context.md

## Rehydrate Snapshot
- Active project: `servicenow_global_tech_assessment_mcp/`
- Primary objective: stabilize and evolve `tech-assessment-hub` as an MCP-first ServiceNow assessment platform.
- Current execution focus: Phase A stabilization, Phase B test hardening, Phase E server decomposition.
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
- Next priorities: Execute MCP plan phases 1-5, then AI reasoning pipeline (feature grouping, tech debt analysis, disposition engine).
- Rehydration guardrails are enforced. Instruction standard is `AGENTS.md` + `CLAUDE.md` + `ACTIVE_PROJECT.md`.
