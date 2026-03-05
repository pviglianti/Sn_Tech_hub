# Phase 3–5 — Coordination File

> **Purpose:** Shared coordination file for Claude and Codex during implementation.
> Both agents MUST monitor this file for updates after completing development work.
> **Protocol:** See `agent_coordination_protocol.md` for communication rules.

**Phase 3/4 Plan:** `tech-assessment-hub/docs/plans/2026-03-04-reasoning-layer-phase3-ui-ai-feature-orchestration.md`
**Phase 5 Plan:** `tech-assessment-hub/docs/plans/2026-03-04-phase5-pipeline-orchestration.md`
**Addendums:** A1–A10 in `phase3_planning_chat.md`

---

## Phase 3/4 Task Assignments (COMPLETE)

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

---

## Phase 5 Task Assignments (APPROVED)

> **Status:** Both tranches complete and cross-reviewed. 328 tests passing.

| Task | Owner | Status | Depends On |
|------|-------|--------|------------|
| P5A-backend: PipelineStage enum + Assessment fields + advance-pipeline API + polling | Codex | `approved` | Phase 3/4 done |
| P5A-ui: Process flow bar HTML/CSS/JS + button wiring + polling JS | Claude | `approved` | P5A-backend contracts |
| P5B: Observation properties + get_usage_count MCP tool | Codex | `approved` | P5A |
| P5C-backend: generate_observations deterministic tool + background job | Codex | `approved` | P5B |
| P5C-prompts: Observation prompt templates (landscape + per-artifact) | Claude | `approved` | P5C-backend |
| P5D-backend: POST /api/results/{id}/review-status endpoint | Codex | `approved` | P5C |
| P5D-ui: Observation card UI + observation-review.js + review gate UI | Claude | `approved` | P5D-backend |
| P5E: Grouping + recommendation trigger buttons | Claude | `approved` | P5D |

### Accepted Addendums (A6–A10)
- **A6:** Plural route naming: `/api/assessments/...`, `/api/results/...`
- **A7:** Separate `pipeline` object in polling response (not overloading scan job)
- **A8:** Replace `usage_query_limit` with `max_usage_queries_per_result` (int, default 2)
- **A9:** P5E runs verification pass; recommendations come from orchestrator calling `upsert_feature_recommendation`
- **A10:** `generate_observations` = deterministic baseline + usage enrichment (no embedded LLM runtime)

### Checkpoint pattern
Codex posts `STATUS` with API contracts after each backend phase → Claude builds UI against them

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
