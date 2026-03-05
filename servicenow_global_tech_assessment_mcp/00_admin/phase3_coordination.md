# Phase 3 — UI Signal Surfacing + AI Feature Orchestration — Coordination

> **Purpose:** Shared coordination file for Claude and Codex during Phase 3 implementation.
> Both agents MUST monitor this file for updates after completing development work.
> **Protocol:** See `agent_coordination_protocol.md` for communication rules.

**Plan document:** `tech-assessment-hub/docs/plans/2026-03-04-reasoning-layer-phase3-ui-ai-feature-orchestration.md`
**Addendums:** A1–A5 in `phase3_planning_chat.md` (2026-03-04 21:30 CLAUDE message)

---

## Task Assignments

| Task | Owner | Status | Depends On |
|------|-------|--------|------------|
| P3A: Data model extensions + migrations | Codex | `approved` | Phase 2 done |
| P3B: APIs for grouping signals/evidence/hierarchy | Codex | `approved` | P3A |
| P3C: UI tabs + FeatureHierarchyTree.js component | Claude | `approved` | P3B contracts |
| P3D: Deterministic seed grouping tool (replaces `group_by_feature`) | Codex | `approved` | P3A |
| P4A: AI iterative reasoning orchestration tool | Codex | `approved` | P3D |
| P4B: Prompt/skill updates for AI reasoning loop | Claude | `approved` | P4A |
| P4C: OOTB replacement recommendation persistence + rendering | Both | `approved` | P4A, P4B |
| P4D: End-to-end validation + human QA checklist | Both + Human | `review_requested` | P3C, P4C |

### Status values
`not_started` → `in_progress` → `tests_passing` → `review_requested` → `approved` → `done`

---

## Checkpoints

### Checkpoint 1 — Data Model + APIs Ready
- **Gate:** P3A + P3B complete, migrations applied, API endpoints return expected shapes, all existing tests pass.
- **Action:** Codex posts `STATUS` with endpoint contracts. Claude begins P3C.
- **Unblocks:** P3C (UI), P3D (seed tool).

### Checkpoint 2 — UI + Seed Tool Complete
- **Gate:** P3C + P3D at `tests_passing` or higher.
- **Action:** Each owner sets `review_requested`. Other agent reviews.
- **Unblocks:** P4A (AI orchestration).

### Checkpoint 3 — AI Reasoning Loop Complete
- **Gate:** P4A + P4B at `tests_passing` or higher.
- **Action:** Cross-review. Both agents test end-to-end with test data.
- **Unblocks:** P4C (OOTB recommendations).

### Checkpoint 4 — Final Sign-Off
- **Gate:** Full test suite green, both agents post `APPROVED`. Human QA checklist completed.
- **Action:** Both post `APPROVED` in chat. Update `todos.md` + `context.md`.

---

## Shared Conventions

### File locations
- **Models:** `tech-assessment-hub/src/models.py`
- **Database:** `tech-assessment-hub/src/database.py`
- **APIs:** `tech-assessment-hub/src/server.py` or extracted route modules
- **MCP tools:** `tech-assessment-hub/src/mcp/tools/pipeline/`
- **Templates:** `tech-assessment-hub/src/web/templates/`
- **JS components:** `tech-assessment-hub/src/web/static/js/`
- **Tests:** `tech-assessment-hub/tests/`
- **Prompts:** `tech-assessment-hub/src/mcp/prompts/`
- **Resources:** `tech-assessment-hub/src/mcp/resources/`

### API contract (P3B → P3C handoff)
Codex defines endpoint shapes in P3B, posts contract summary in chat. Claude implements UI against those contracts. If contracts change, Codex posts `STATUS` with diff.

### Addendums to integrate
- **A1:** `seed_feature_groups` replaces `group_by_feature` (Codex, during P3D)
- **A2:** Unified `/api/.../grouping-signals` response shape (Codex, during P3B)
- **A3:** `run_feature_reasoning` = single-pass tool, AI loops via prompt (Codex P4A + Claude P4B)
- **A4:** Grouping Signals tab = summary cards + DataTable (Claude, during P3C)
- **A5:** Feature Hierarchy includes "Ungrouped" catch-all bucket (Claude, during P3C)

---

## Chat Log

All messages go in **`phase3_planning_chat.md`** (same directory).
