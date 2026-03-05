# Cross-Testing Protocol

## Matrix Generation

For N devs, use round-robin: Dev-K tests Dev-((K % N) + 1)

| Team Size | Matrix |
|-----------|--------|
| 2 devs | Dev-1 ↔ Dev-2 (mutual) |
| 3 devs | Dev-1→2, Dev-2→3, Dev-3→1 |
| 4 devs | Dev-1→2, Dev-2→3, Dev-3→4, Dev-4→1 |

## Cross-Test Flow

```
1. Dev-M completes build → posts [DONE]
2. Reviewer is launched (review may still be in progress)
3. Orchestrator re-launches Dev-N as cross-tester (Read+Bash only)
4. Dev-N tests in Dev-M's worktree + branch context (must be `dev_M/*`)
5a. If pass → Dev-N posts [CROSS_TEST_PASS] → both sign off → done
5b. If fail → Dev-N posts [CROSS_TEST_FAIL] with issues → loop begins
```

## Rolling Start Rule (Do Not Wait for All Devs)

Cross-testing starts as soon as there is a completed task and an available tester.

```
1. First `[DONE]` appears
2. Launch reviewer + watcher snapshot immediately
3. If another dev is idle/available, launch cross-test immediately
4. If `[CROSS_TEST_FAIL]`, launch fix + reverify immediately
5. Continue while remaining devs are still implementing
```

This avoids idle time and catches integration issues early while implementation is still active.

## Failure Loop

```
Dev-N: [CROSS_TEST_FAIL] — Issues: [list]
  (orchestrator re-launches Dev-M to fix)
Dev-M: [FIX] — Fixed issues, tests passing
  (orchestrator re-launches Dev-N to re-verify)
Dev-N: [CROSS_TEST_PASS] — Verified fix ✅
  (both sign off)
```

Each round is a fresh `claude -p` call. Orchestrator mediates — agents communicate through the Cross-Test Thread section in plan MD.

## Cross-Tester Responsibilities

1. Run ALL tests in target worktree (not just the new ones)
2. Verify acceptance criteria from PM
3. Try edge cases not covered by existing tests
4. Document issues with file:line references
5. Do NOT fix issues — only report them
6. Fail fast if not running in the assigned target worktree/branch and post `[CROSS_TEST_BLOCKED]`

## Sign-Off Requirements

A task is only `Agreed` when ALL THREE sign off:
- [ ] Dev-M (author) — implementation complete
- [ ] Dev-N (cross-tester) — tested and verified
- [ ] Reviewer — code quality approved
