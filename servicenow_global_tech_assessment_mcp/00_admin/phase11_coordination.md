# Phase 11 — Coordination

> **Purpose:** Shared coordination file for Codex + Claude during Phase 11 execution.
> Both agents MUST monitor this file and `phase11_chat.md` after each completed task.

**Unified plan:** `servicenow_global_tech_assessment_mcp/03_outputs/plan_phase11_unified_feature_ownership_and_legacy_cleanup_2026-03-05.md`
**Design reference:** `tech-assessment-hub/docs/plans/2026-03-05-phase11-ai-driven-feature-architecture-design.md`

---

## Task Assignments

| Task | Owner | Status | Depends On |
|------|-------|--------|------------|
| P11-0: Lock unified contracts (mode behavior + ownership boundaries) | Codex + Claude | `approved` | — |
| P11-1: Claude independent tranche (analysis_mode cleanup, AI authoring tools, mode wiring) | Claude | `tests_passing` | P11-0 |
| P11-2: Feature membership integrity (customized-only guard + unique pair protection) | Codex + Claude | `review_pass` | P11-0 |
| P11-3: Legacy cleanup utility (`--dry-run` / `--apply`) | Codex | `dry_run_complete` | P11-2 |
| P11-4: Cross-agent peer review (both directions) | Codex + Claude | `in_progress` | P11-1, P11-2, P11-3 |
| P11-5: Human-approved cleanup execution + validation report | Human + Codex | `not_started` | P11-3 |
| P11-6: Final regression + docs/admin sync + sign-off | Codex + Claude | `not_started` | P11-4, P11-5 |

---

## Checkpoints

### Checkpoint 1 — Contract Lock
- **Gate:** P11-0 complete and both agents post `REVIEW_PASS` in `phase11_chat.md`.
- **Action:** Keep Claude independent tranche moving; Codex starts integrity implementation once contract is locked.
- **Unblocks:** P11-2.

### Checkpoint 2 — Safety Layer Ready
- **Gate:** P11-1 + P11-2 both at `tests_passing` or higher.
- **Action:** Cross-review begins.
- **Unblocks:** P11-3, P11-4.

### Checkpoint 3 — Cleanup Ready for Human Approval
- **Gate:** P11-3 dry-run output posted and reviewed.
- **Action:** Human approves `--apply` scope/window.
- **Unblocks:** P11-5.

### Checkpoint 4 — Final Sign-Off
- **Gate:** Full regression green, both agents post `APPROVED`, human validates legacy assessment behavior.
- **Action:** Update `todos.md`, `insights.md`, `run_log.md`, and `context.md` as needed.
- **Unblocks:** Merge/release decision.

---

## Shared Conventions

### File locations
- Models/migrations: `tech-assessment-hub/src/models.py`, `tech-assessment-hub/src/database.py`
- MCP tools: `tech-assessment-hub/src/mcp/tools/core/`, `tech-assessment-hub/src/mcp/tools/pipeline/`
- Pipeline behavior: `tech-assessment-hub/src/server.py`
- Cleanup utility: `tech-assessment-hub/src/scripts/`
- Tests: `tech-assessment-hub/tests/`

### Contracts
- `local_subscription`: AI owns feature creation; deterministic grouping is read-first/suggestion-only.
- `api`: deterministic fallback remains allowed unless explicitly disabled.
- Membership writes must enforce customized-only result rows.
- Cleanup must preserve human-authored feature links.

---

## Chat Log

All messages go in **`phase11_chat.md`** (same directory).
