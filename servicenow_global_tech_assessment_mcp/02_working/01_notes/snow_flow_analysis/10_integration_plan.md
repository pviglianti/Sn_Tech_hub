# 10 — Snow-Flow Integration Plan (What to Take, How to Restructure, Execution Order)

> **Scope**: synthesis plan from docs 01–09
> **Source**: takeover continuation audit (Codex)
> **Status**: DONE (takeover batch)

---

## 1. Executive Decision

### Recommended architecture path
Use a **hybrid transition**:
1. Keep Snow-flow TypeScript MCP running as a sidecar first (reuse proven tools/auth quickly)
2. Keep Web App (Python/FastAPI) as control plane and DB owner
3. Gradually port only high-value tool domains to Python MCP modules when stable

### Why this path
- Maximizes immediate reuse of 382+ unified tools and proven auth/registry patterns
- Avoids a risky all-at-once TypeScript-to-Python rewrite
- Preserves your North Star: Web-managed MCP + DB evolution + file-backed context memory

---

## 2. Target End-State Alignment

### Fits `context.md` North Star
- Web App = Brain / control plane
- MCP = execution muscle (can be multi-runtime during transition)
- LLM = reasoning layer
- DB progression preserved: SQLite -> reader abstraction -> replica -> PostgreSQL

### Explicitly supported by this plan
- dynamic memory path selection (wizard)
- runtime config/auth push from management UI
- token-aware prompt/model workflow
- staged pipeline execution (ingest -> preprocess -> manifest -> deep dive -> presentation)

---

## 3. Integration Waves

## Wave 0 — Stabilize Analysis Assets (Complete)
- Completed in this takeover batch:
  - `02_core_mcp_tools.md`
  - `04_snowcode_cli_skills.md`
  - `07_ui_packages.md`
  - `08_extensibility_audit.md`
  - `09_tool_mapping_matrix.md`
  - this file

## Wave 1 — Runtime Bridge + Management Control (Next)
1. Add Snow-flow sidecar process management in FastAPI
2. Add management endpoints in Web App:
   - push config
   - trigger reload/reconnect
   - stream SSE events from MCP
3. Add wizard-generated settings contract for paths/providers/instances
4. Add read-only DB tool (`sqlite_query` with allowlist/limits)

## Wave 2 — Assessment-First Tool Cut
1. Extract/adapt `EXTRACT_NOW` domains (from doc 09)
2. Implement strict read-first policy for initial assessment pipeline
3. Add tool contracts that return summaries + references (not raw dumps)
4. Integrate skill packs for assessment domains only

## Wave 3 — Context + Token Optimization
1. Project-index-first prompt loading (`00_Index.md` first)
2. Stage-aware context packs
3. Token budget telemetry per run/stage
4. Automatic compact/checkpoint hooks aligned to AGENTS workflow

## Wave 4 — Deep Feature Expansion
1. Add selected `ADAPT_PHASE_2` domains
2. Implement replication layer for MCP-local reads
3. Expand CSDM-specific agent/skill workflows

## Wave 5 — Portability and Hardening
1. Incremental Python ports for high-maintenance TypeScript domains
2. optional enterprise proxy path
3. full production packaging (installer + diagnostics + rollback)

---

## 4. Component-Level Keep / Adapt / Defer

### Keep now
1. Unified tool metadata/executor pattern
2. Role-permission enforcement model
3. Error classification + retry wrappers
4. MCP reconnect/reload mechanisms
5. Skill discovery/injection architecture

### Adapt
1. Global path handling -> wizard path overrides
2. Auth chain -> Web App settings + managed credential lifecycle
3. Prompt loading -> project-memory-aware staged loading
4. Tool registry -> remove static/dynamic domain mismatch risk

### Defer
1. full desktop/TUI parity
2. enterprise proxy productionization
3. write-heavy mutation domains beyond assessment scope

---

## 5. Critical Risks and Mitigations

1. Static/dynamic registry mismatch may hide domains
   - Mitigation: enforce deterministic domain manifest during packaging
2. HTTP transport wrapper cannot execute tools currently
   - Mitigation: use SnowCode server management endpoints + stdio sidecar first
3. Raw SQL exposure risk if generic query tool is copied naively
   - Mitigation: read-only SQL guardrails and table allowlist
4. Prompt bloat from broad skill/system preload
   - Mitigation: stage-based selective loading from project markdown index

---

## 6. Implementation Backlog (Immediate)

1. `tech-assessment-hub/src/mcp/bridge/`:
   - sidecar lifecycle manager
   - SSE relay client
2. `tech-assessment-hub/src/mcp/tools/db_reader.py`:
   - safe `sqlite_query`
3. `tech-assessment-hub/src/server.py`:
   - management endpoints for MCP config/reload/reconnect/status
4. `tech-assessment-hub/src/config/`:
   - wizard settings schema for path + provider + instance
5. `tech-assessment-hub/src/web/templates/`:
   - management console panels (connections, runs, event stream)

---

## 7. Success Criteria for Phase 9B Entry

1. Web UI can push config updates and apply them without full app restart
2. MCP sidecar reconnect/reload works from UI actions
3. Read-only DB tool returns bounded, auditable query results
4. One complete end-to-end assessment run works with staged context loading
5. Token usage is measurable and improved versus raw-context baseline

---

## 8. Takeover Notes (for reconciliation)

- This plan is explicitly produced as continuation after prior-agent context exhaustion.
- It reconciles pending snow-flow deep-dive outputs into execution-ready integration sequencing.
- Companion artifacts:
  - `08_extensibility_audit.md`
  - `09_tool_mapping_matrix.md`

