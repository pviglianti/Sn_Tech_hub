# 07 — UI Package Deep Dive (Console, Desktop, Web, TUI)

> **Scope**: `packages/console/`, `packages/desktop/`, `packages/web/`, `packages/tui/`
> **Source**: takeover continuation audit (Codex)
> **Status**: DONE (takeover batch)

---

## 1. UI Landscape Summary

Snow-flow is not a single frontend. It is a **multi-surface product**:
1. `console/*` (modular console stack packages)
2. `desktop` (SolidJS desktop/web app shell)
3. `web` (Astro/Starlight docs + landing + share views)
4. `tui` (Go Bubble Tea terminal UI)

### Package roots confirmed
- `packages/console`
- `packages/desktop`
- `packages/web`
- `packages/tui`

---

## 2. Console Packages (`packages/console/*`)

### Subpackages
- `packages/console/app/package.json`
- `packages/console/core/package.json`
- `packages/console/function/package.json`
- `packages/console/mail/package.json`
- `packages/console/resource/package.json`

### Pattern
- Split by capability rather than one monolith.
- Shared version line around `0.15.17`.
- Useful as reference for package boundaries, but not required for our management-console-first MVP.

---

## 3. Desktop Package (`packages/desktop`)

### Key files
- `packages/desktop/package.json`
- `packages/desktop/src/index.tsx` (1,446 bytes)
- `packages/desktop/src/pages/index.tsx` (35,396 bytes)

### Architecture notes
- SolidJS router-based shell.
- Primary UI behavior in `pages/index.tsx`:
  - session list/timeline
  - message navigation
  - prompt execution and context UI
- Heavy coupling to SnowCode session model and SDK client methods.

### Reuse value
- Interaction ideas (session navigation, progress indicators) are reusable.
- Direct code reuse is low due to model/API coupling.

---

## 4. Web Package (`packages/web`)

### Key files
- `packages/web/package.json`
- `packages/web/src/components/Lander.astro` (15,801 bytes)
- `packages/web/src/content.config.ts` (266 bytes)
- Extensive docs content under `packages/web/src/content/docs/*.mdx`

### Architecture notes
- Primarily marketing/docs site (Astro + Starlight content model).
- Not the operational control-plane UI for MCP management.
- Contains useful product messaging and feature taxonomy (e.g., 410+ MCP tools claims, multi-session narrative).

### Reuse value
- Low for our runtime app UI.
- Medium for docs/website content structure if we publish project docs.

---

## 5. TUI Package (`packages/tui`)

### Key files
- `packages/tui/go.mod` (Go `1.25.0`)
- `packages/tui/cmd/snowcode/main.go` (4,039 bytes)
- Internal modules under `packages/tui/internal/*`

### Architecture notes
- Go Bubble Tea application.
- Command-line flags include session/project/model/prompt controls.
- Strong terminal-native UX stack with dedicated theme/layout/completions modules.

### Reuse value
- Conceptual reference for operator UX.
- Not a direct path for our web-managed control plane.

---

## 6. UI-to-Core Coupling Observations

1. Desktop and TUI are tightly coupled to SnowCode session/MCP abstractions.
2. Web package is docs/landing, not execution console.
3. `console/*` modules are componentized, but still oriented to Snow-flow's internal domain model.

**Implication**: We should not attempt wholesale UI adoption; instead reuse patterns and rebuild around our FastAPI + DB + management-console requirements.

---

## 7. Integration Guidance for Our Project

### Keep (conceptual)
1. Session timeline visualization pattern
2. Event-stream-driven status updates
3. Package modularity boundaries (app/core/resource split mindset)

### Adapt
1. Progress and diagnostics UI patterns for 5-stage pipeline runs
2. Auth/connection status surfaces for multi-instance operation
3. Tool execution history UX (read-first views)

### Replace
1. Snow-flow-specific desktop/TUI interaction layer
2. Existing docs-site UI for runtime control operations

---

## 8. Takeover Notes (for reconciliation)

- This file closes the pending UI deep dive initially assigned after prior-agent context loss.
- It should be read with:
  - `03_core_infrastructure.md`
  - `08_extensibility_audit.md`
  - `10_integration_plan.md`

