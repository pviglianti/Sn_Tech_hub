# Lifecycle Protocol

Full workflow from start to finish.

## Phase Summary

```
Phase 1: PLAN        → Architect + PM produce plan (root branch)
Phase 2: BUILD       → Devs implement in worktrees, reviewer+watcher start after first [DONE], rolling cross-test/fix lanes may start immediately
Phase 3: CROSS-TEST  → Complete remaining cross-tests/sign-offs not closed during rolling lanes
Phase 4: FEEDBACK    → Kill workers, reviewer summary, Arch+PM re-launched for findings review
Phase 4.5: ROADMAP   → Arch+PM prep for next sprint (optional)
Phase 5: FINALIZE    → Merge worktrees, full test suite, commit
Phase 5.5: CLEANUP   → Archive run, delete ephemeral artifacts
Phase 6: MEMORY      → Arch+PM write session memory, verify all orchestration processes are down
```

## Terminal Lifecycle

| Role | Launches | Deliverable | Spun Down After | Re-prompted? |
|------|----------|-------------|-----------------|--------------|
| Architect | Phase 1 | Plan, feedback, memory | Each prompt exits after deliverable | YES — multiple times via memory files |
| PM | Phase 1 | Assignments, feedback, memory | Each prompt exits after deliverable | YES — multiple times via memory files |
| Dev (build) | Checkpoint 1 | Code + tests | `[DONE]` posted | New `-p` as cross-tester/patcher |
| Dev (cross-test) | As soon as target task is `[DONE]` and a tester is available | Test results | `[CROSS_TEST_PASS/CROSS_TEST_FAIL/CROSS_TEST_BLOCKED]` | New `-p` if re-verify needed |
| Dev (patch) | When issues found | Fix in worktree | `[FIX]` posted | New `-p` if fix rejected |
| Code Reviewer | After first `[DONE]` | `findings.md` | Findings delivered | No — single run |
| Live Watcher | After first `[DONE]` and on monitor triggers | Snapshot of actionable items | Each snapshot exits immediately | YES — one-shot relaunches by orchestrator |
| Scribe (optional) | After first `[DONE]` and periodic checkpoints | Compact status digest in coordination docs | Each snapshot exits immediately | YES — one-shot relaunches by orchestrator |
| Orchestrator Monitor Loop | Start of Build phase | Heartbeat + alerts log | Stopped in Phase 4 worker spindown | YES — restart if stale |

## Deliver Then Die

Every role runs as a fresh `claude -p` call, produces its deliverable, and exits. Architect + PM persist through memory files and shared docs, not open tabs.

**Exception:** Cross-test back-and-forth: orchestrator rapidly re-launches devs for each exchange round

## Spindown Order

1. Phase 4 step 2: Stop monitor loop, then kill devs and cross-testers; if watcher/scribe snapshots are still running, kill them too. Verify recorded PIDs are gone.
2. Phase 4 step 5: Kill Reviewer after findings.md complete
3. Phase 5: No worker process remains alive while orchestrator merges/tests/commits
4. Phase 6: Arch + PM re-launch for memory writes if needed
5. Session end: ALL orchestration processes down

## Orchestrator as Event Loop

The orchestrator is the ONLY thing that polls. Agents NEVER poll or wait.

**Pattern:**
- Orchestrator watches streams (`tail -f`)
- Orchestrator runs a persistent heartbeat loop and treats stale heartbeat as failure
- Orchestrator re-launches watcher snapshots when trigger conditions are hit
- Orchestrator detects when an agent should act
- Orchestrator sends prompt/nudge to that agent
- Agent does work, posts output, stops
- Orchestrator moves to next action

**Never include in any agent prompt:** "wait for X", "poll for Y", "check periodically"

## Inter-Phase Cleanup

After each run:

**Delete:** Worktrees (`git worktree remove` only after PID/shell-detach checks), stream logs (`.jsonl`)

**Keep (committed):** `plan.md`, `coordination.md`, `findings.md`, `architect_memory.md`, `pm_memory.md`

**Next run:** Archive previous run → create fresh from templates → Arch+PM rehydrate from archived memory

## Worktree Rules

- 1 worktree per dev, created AFTER plan is committed
- Devs work ONLY in their worktree
- Reviewer, Arch, PM, Orchestrator run in root branch
- Worktrees merged to feature branch after all sign-offs
- Worktrees deleted only after successful merge, clean status, and no attached shell/process
