# Phase 11C — Legacy Cleanup Utility Execution Coordination

> **Purpose:** Shared coordination file for planner + implementation workers to deliver P11-3 (`cleanup_legacy_feature_data`) with review, validation, and branch-ready commits.
> All agents monitor this file and `phase11c_cleanup_chat.md` for state transitions.

**Target plan:** `servicenow_global_tech_assessment_mcp/03_outputs/plan_phase11c_cleanup_execution_2026-03-05.md`
**Related references:**
- `servicenow_global_tech_assessment_mcp/03_outputs/phase11_legacy_cleanup_dryrun_report_2026-03-05.md`
- `servicenow_global_tech_assessment_mcp/00_admin/phase11_coordination.md`
- `servicenow_global_tech_assessment_mcp/00_admin/phase11_chat.md`

---

## Task Assignments

| Task | Owner | Status | Depends On | Notes |
|------|-------|--------|------------|-------|
| C0: Build execution plan with task split across available workers | Planner | `complete` | — | Plan published and locked |
| C1: Implement cleanup utility core (`--dry-run` / `--apply`) | Worker-1 | `complete` | C0 | `src/services/legacy_cleanup_service.py` delivered |
| C2: Implement safety/reporting/CLI UX + docs integration | Worker-2 | `complete` | C0 | CLI + report section 8 delivered |
| C3: Implement/expand test coverage for cleanup flows | Worker-3 | `complete` | C0 | `test_legacy_cleanup_service.py` + `test_cleanup_legacy_cli.py` delivered |
| C4: Independent code + test review, regression run, merge notes | Codex Lead | `complete` | C1, C2, C3 | Integrated review + 67-test validation pass |
| C5: Final integration in primary branch + commit/push | Codex Lead | `in_progress` | C4 | Ready to commit/push |

---

## Checkpoints

### Checkpoint 1 — Plan Locked
- **Gate:** C0 posted in chat and plan file exists.
- **Action:** Workers begin C1/C2/C3 in parallel.
- **Unblocks:** C1-C3.

### Checkpoint 2 — Implementation Complete
- **Gate:** C1-C3 artifacts present and validated.
- **Action:** Reviewer validates behavior and test outcomes.
- **Unblocks:** C4.

### Checkpoint 3 — Branch Ready
- **Gate:** C4 complete with passing suite.
- **Action:** Commit + push integration tranche.
- **Unblocks:** C5 completion.

---

## Shared Conventions

### Message format
`[YYYY-MM-DD HH:MM] [AGENT] [TAG] — message`

### Scope guardrails
- No destructive DB changes without explicit `--apply` path.
- Preserve human-authored feature memberships.
- Keep cleanup strictly assessment-scoped.

---

## Chat Log

All messages go in **`phase11c_cleanup_chat.md`**.
