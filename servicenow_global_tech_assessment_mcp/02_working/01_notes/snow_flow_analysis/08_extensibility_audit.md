# 08 — Extensibility Audit (Web-Managed MCP)

> **Scope**: targeted audit against 5 required extensibility points
> **Source**: takeover continuation audit (Codex)
> **Status**: DONE (takeover batch)

---

## 1. Folder Selection Logic (Dynamic Memory Paths)

### Findings
- Current memory/config paths are derived from XDG globals in:
  - `packages/core/src/global/index.ts`
  - `packages/snowcode/src/global/index.ts`
- `Global.Path.memory` is hard-wired to `path.join(data, "memory")`.
- Session/memory modules consume `Global.Path.memory` directly (example: `packages/core/src/memory/memory.ts`).

### Injection point recommendation
- Add runtime override layer before path object is finalized:
  - `SNOW_FLOW_MEMORY_PATH`
  - `SNOW_FLOW_DATA_PATH`
  - `SNOW_FLOW_CONFIG_PATH`
  - `SNOW_FLOW_STATE_PATH`
- Preferred persistence source in our architecture: wizard-generated `settings.json` (Web App-owned).

### Implementation pattern
1. Read wizard settings at startup
2. Resolve user-selected absolute paths
3. Override `Global.Path.*` values prior to `fs.mkdir(...)` bootstrap
4. Validate create/write permissions and fallback with explicit error message

### Verdict
- **Feasible with low code churn**. Existing path-centralization makes this straightforward.

---

## 2. “Management Service” Bridge (Push Config Without Restart)

### Findings
- SnowCode Hono server already exposes management-grade endpoints:
  - `PATCH /config`
  - `POST /mcp/reload`
  - `POST /mcp/:name/restart`
  - `POST /mcp/:name/reconnect`
  - `GET /event` (SSE for all bus events)
- SSE implementation forwards `Bus.subscribeAll(...)` events and supports disconnect cleanup.
- MCP config reload can read fresh config from disk (`packages/snowcode/src/mcp/index.ts`), bypassing cached config.

### Practical answer to question
- **Yes**: configuration pushes can be applied without full app restart via `/config` + `/mcp/reload` (and selective restart/reconnect endpoints as needed).

### Caveat
- The standalone unified MCP server itself is stdio-focused; web push semantics are primarily via SnowCode server layer.

---

## 3. SQLite Tooling Pattern (`sqlite_query`)

### Findings
- SQLite appears in core code via `better-sqlite3` (notably memory/coordination modules).
- `MCPMemoryManager.query(sql, params)` exists but is a generic raw SQL executor, not safe for external app DB access.
- `ReliableMemoryManager` exists as non-SQL fallback for resilience.

### Recommended pattern for our MCP
1. Add dedicated `sqlite_query` tool as **read-only** MVP:
   - allow only `SELECT` and `WITH`
   - deny `INSERT/UPDATE/DELETE/PRAGMA/ATTACH/DETACH/ALTER/DROP`
2. Use parameterized queries only
3. Enforce table allowlist for Web App schema
4. Enforce row/page limits and timeout
5. Add query audit log (tool caller, SQL fingerprint, row count, duration)

### Replication-readiness extension
- Wrap access behind `DBReader` abstraction now:
  - today -> SQLite primary (app-owned)
  - future -> replica target switch (without tool contract break)

### Verdict
- **Best path is a new constrained tool**; do not expose generic raw query methods directly.

---

## 4. Wizard Preparation (Setup.sh / Setup.exe Touchpoints)

### Dependencies observed
- Node.js runtime (and npm)
- Bun (`packageManager: bun@1.3.0` in root)
- Git
- Go toolchain (`go 1.25.0`) for TUI build paths (optional if we skip TUI)
- Platform binaries and permission fixes handled in `scripts/postinstall.js`

### Credential/env ecosystem
- ServiceNow env patterns: `SERVICENOW_*` and `SNOW_*`
- Provider envs surfaced in auth/debug paths: `ANTHROPIC_*`, `OPENAI_*`, `GOOGLE_*`, etc.

### Setup script should touch
1. Install/runtime validation (Node/Bun; optionally Go)
2. Generate/update config files (`.mcp.json` + app settings)
3. Initialize user-selected memory/project/db paths
4. Validate ServiceNow creds and auth method
5. Validate LLM provider model config
6. Smoke test MCP connectivity
7. Persist bootstrap outputs and diagnostics report

### Verdict
- Existing scripts provide strong scaffolding patterns; adapt to wizard-driven, settings-first flow.

---

## 5. Token Efficiency Audit (Prompt + Context Awareness)

### Current state
- Large baseline prompt/context artifacts:
  - `AGENTS.md`: 31,857 bytes
  - `session/prompt/codex.txt`: 24,211 bytes
  - combined inspected prompt payloads ~100,697 bytes
- Positive: lazy tool loading and domain filtering materially reduce tool-schema token pressure.
- Gap: prompts are mostly global/provider oriented, not natively bound to per-project markdown memory roots.

### Refactor recommendations for our architecture
1. Inject only project `00_Index.md` + current stage brief into system context
2. Load additional markdown memory files on-demand (skill/tool triggered)
3. Keep skill payloads modular; avoid preloading all 53 skills
4. Add explicit token budget tracker per pipeline stage
5. Introduce compact, deterministic tool outputs (IDs + pointers, not raw dumps)

### Verdict
- Snow-flow has good tool-token controls, but we should add project-memory-aware prompt loading to match our unlimited-context file strategy.

---

## 6. Risk Register (Extensibility)

1. Static-vs-dynamic registry domain mismatch can hide tools in some deployment modes.
2. HTTP transport wrapper is incomplete for tool execution.
3. Raw SQL pathways in existing modules are not safe to expose externally.
4. Prompt payload size can grow quickly without strict staged loading.

---

## 7. Recommended Next Actions

1. Implement path override contract in our MCP bootstrap first.
2. Stand up Web App -> MCP management endpoints using config/reload/event patterns.
3. Build read-only `sqlite_query` with allowlist + timeout + paging.
4. Define wizard output schema (`settings.json`) that includes path, auth, provider, model.
5. Implement project-index-first prompt loading for stage-aware token efficiency.

---

## 8. Takeover Notes (for reconciliation)

- This file directly answers the 5 requested audit points from the interrupted prior run.
- It is the bridging artifact for subsequent implementation tasks in Phases 9B/10/11.

