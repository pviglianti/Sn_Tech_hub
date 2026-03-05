# Workspace Agent Instructions (Generic)

These rules apply to all AI agents in this workspace.
This file is the single shared standard for Claude, Codex, and other tools.

## Instruction Discovery Order
1. Tool-specific file (`CLAUDE.md`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`)
2. `AGENTS.md` (this file)
3. Active project admin files from `ACTIVE_PROJECT.md`

## Active Project Routing (Required)
- Read `ACTIVE_PROJECT.md` before any rehydration.
- Do not guess the active job by scanning folders.

## Rehydration Contract (Hard Limits)
### Tier 0
- Read `ACTIVE_PROJECT.md` only.
- Budget target: <=150 words.

### Tier 1 (default)
- Read only:
  - `00_admin/context.md` section `## Rehydrate Snapshot`
  - `00_admin/todos.md` section `## Now`
- Budget target: <=900 words total.
- Fallback: first 120 lines of each file if section missing.

### Tier 2 (only when required)
- Read only:
  - `00_admin/insights.md` section `## Active Decisions`
  - last 80 lines of `00_admin/run_log.md`
- Budget target: <=1,800 words total.

### Tier 3
- Read only explicitly referenced files from `02_working/` or `03_outputs/`.
- Never bulk-read folders.

## Context Exclusions (Required)
- Never include `archive/` in default rehydration or exploratory scans.
- Read files under `archive/` only when the user explicitly asks for archived material.
- Treat files moved into `archive/` as historical/old docs and ignore them for active implementation decisions.
- For this workspace, also exclude these paths from default rehydration/exploratory scans unless explicitly referenced by the active task or requested by the user:
  - `docs/`
  - `Templates/`
  - `snow-flow_pv/`
  - `tech-assessment-hub/docs/plans/`
- For phase coordination/chat files in `00_admin/`, read only the files tied to the current active phase in `todos.md`/`ACTIVE_PROJECT.md`; treat other phase files as historical context unless explicitly requested.

## Core Memory File Shapes
- `context.md`: includes `## Rehydrate Snapshot` (8-12 bullets max).
- `todos.md`: only 3 sections: `## Now`, `## Next`, `## Backlog`.
- `insights.md`: durable content in `## Active Decisions`.
- `run_log.md`: append-only rows with format:
  - `event_id | date | actor | summary | files_changed | next_action`

## Auto-Rollover Rules
- `context.md` > 300 lines: compress snapshot and archive historical sections.
- `todos.md` > 220 lines: archive old completed items.
- `insights.md` > 600 lines: archive non-active sections.
- `run_log.md` > 1,000 lines: split to dated archive and keep recent window.

## Update Protocol
After meaningful work:
1. Update `todos.md`
2. Update `insights.md`
3. Update `run_log.md`
4. Update `context.md` if direction/scope changed

## Engineering Principles (Mandatory)

All agents MUST follow these when writing or modifying code:

### 1. Reuse Before Create
- Before building any new component, check if a reusable one already exists.
- **Frontend**: `DataTable.js` for any tabular data display. `ConditionBuilder.js` for any filter UI. Never manually construct `<table>/<tr>/<td>` HTML when DataTable.js exists.
- **Backend**: `CsdmTableRegistry` + `CsdmFieldMapping` for ALL ServiceNow table mirroring. `condition_query_builder.py` for any JSON→SQL/SN-query translation. Never create new static SQLModel classes for SN mirror data.
- **Templates**: Use shared includes (`components/`) for modals, status badges, form groups, data tables. Do not duplicate markup across templates.

### 2. User-Configurable Over Hardcoded
- Any value that an end-user or instance admin might want to tune (batch sizes, page sizes, timeouts, limits, retry counts, polling intervals) MUST be stored in the properties system (`integration_properties.py` pattern → `AppConfig` table) and exposed via a UI page.
- Hardcode ONLY true constants (HTTP status codes, SQL keywords, structural identifiers).
- When adding a new configurable value: define it in `PROPERTY_DEFINITIONS`, add a default, expose it in the properties UI.

### 3. Modular / Single Responsibility
- Each file should do one thing. Route files handle HTTP. Service files handle business logic. JS components handle rendering.
- Prefer small, composable functions over large monolithic ones.
- When a file grows beyond its original scope, extract the new concern into its own module.

### 4. Acknowledge Refactor Debt
- When building something new that exposes existing duplication or hardcoding, log it as a refactor opportunity in `todos.md` (Backlog) and mention it in the run_log.
- Examples: "data_browser.js duplicates DataTable.js rendering — backlog item to consolidate." Do not silently add to tech debt.

### 5. Replace-Then-Remove (No Dead Code)
- When a refactor replaces old code with a new modular component, the old duplicated code MUST be deleted — not commented out, not renamed with underscores, not kept "just in case."
- If the file still has non-duplicated logic, keep the file but remove only the replaced portions.
- **Deletion gate**: Old code is only removed after (1) the new component is verified working by automated tests AND (2) a human has manually tested the affected flows. Never delete before human sign-off.
- Dead code is tech debt. Keeping both old and new paths creates maintenance burden and confusion.

### Known Refactor Debt (current)
- `data_browser.js` duplicates `DataTable.js` table rendering — migrate to DataTable component
- `analytics.js` builds pivot tables manually — extract or reuse DataTable
- `integration_properties.js` renders its own table — reuse DataTable or shared renderer
- Templates repeat modal/badge/form patterns — extract to `templates/components/`
- `sn_client.py` and `sn_dictionary.py` have hardcoded timeouts (30s) not using integration_properties
- JS page sizes inconsistent (50 vs 200) — centralize via config endpoint or properties

## Cross-Agent Collaboration
- Use owner tags in todos: `[owner:codex]`, `[owner:claude]`, `[owner:human]`.
- Keep next action explicit in each run-log row.
- If information is not in active project files or referenced artifacts, treat it as unknown.
- **For coordinated multi-agent work:** Follow `00_admin/agent_coordination_protocol.md`. Create a phase-specific coordination + chat file pair for each collaborative effort. Use the standard message tags, status lifecycle, review requirements, and checkpoint pattern defined there.
- **Exception — orchestrated runs:** When the workspace is using the `.claude/orchestration/` system, the orchestration playbook and role prompts override the interactive chat/polling workflow. In that mode Codex is the event-loop coordinator, workers do not poll, and any shared orchestration files are the explicit source of truth for that run.
