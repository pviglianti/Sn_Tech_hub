# Checkpoint Gates

Formal phase transitions. The orchestrator MUST verify all gates before proceeding.

---

## Checkpoint 0 — Plan Locked

**Gate:**
- [ ] Architect has posted plan MD with task breakdown
- [ ] PM has refined tasks with assignments, acceptance criteria, cross-test matrix
- [ ] Coordination table exists at `orchestration_run/coordination.md`
- [ ] No file ownership overlaps between tasks

**Action:** Orchestrator creates worktrees, generates per-dev prompts

**Unblocks:** Dev launch (Phase 2)

---

## Checkpoint 1 — Bootstrap ACK Complete

**Gate:**
- [ ] All worktrees created (1 per dev)
- [ ] All dev bootstrap ACKs received (`[ACK]` in plan MD)
- [ ] ACK gate script passed (`.claude/orchestration/scripts/require_bootstrap_ack.sh orchestration_run/plan.md <num_devs>`)

**Action:** Orchestrator sends execution prompts. After the first dev posts `[DONE]`, launch reviewer + one-shot watcher snapshot.

**Unblocks:** Build phase

---

## Checkpoint 2 — Implementation Complete

**Gate:**
- [ ] All devs posted `[DONE]` with passing tests
- [ ] Reviewer has reviewed ALL tasks (posted findings per task)

**Action:** Orchestrator re-launches devs as cross-testers

**Unblocks:** Cross-test phase (Phase 3)

---

## Checkpoint 3 — Cross-Test Complete

**Gate:**
- [ ] All cross-testers posted `[CROSS_TEST_PASS]`
- [ ] All sign-offs complete (author + cross-tester + reviewer per task)

**Action:** Kill workers. Reviewer writes final summary. Notify Arch+PM.

**Unblocks:** Feedback phase (Phase 4)

---

## Checkpoint 4 — Feedback Complete

**Gate:**
- [ ] Architect posted feedback/lessons-learned
- [ ] PM posted process notes and backlog updates

**Action:** Merge worktrees → run full test suite → commit to branch

**Unblocks:** Finalize phase (Phase 5)

---

## Checkpoint 5 — Session Memory Written

**Gate:**
- [ ] Architect wrote to `orchestration_run/architect_memory.md`
- [ ] PM wrote to `orchestration_run/pm_memory.md`
- [ ] Admin files updated (`servicenow_global_tech_assessment_mcp/00_admin/insights.md`, `servicenow_global_tech_assessment_mcp/00_admin/todos.md`, `servicenow_global_tech_assessment_mcp/00_admin/run_log.md`)

**Action:** Verify no orchestration process remains running. Session complete.

**Unblocks:** Next session can rehydrate from memory files

---

## Anti-Patterns

- Launching devs before Checkpoint 0 passes
- Skipping the ACK gate script before execution launch
- Launching reviewer before any dev has completed work
- Proceeding to cross-test before ALL devs are done
- Merging before ALL sign-offs are complete
- Skipping memory-write at session end
