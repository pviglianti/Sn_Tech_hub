# Communication Protocol

## Message Format

All inline updates in plan MD use:
```
[YYYY-MM-DD HH:MM] [AGENT] [TAG] — message
```

## Standard Tags

| Tag | Meaning | Who Uses |
|-----|---------|----------|
| `[ACK]` | Task acknowledged, starting work | Devs |
| `[STATUS]` | Progress update | Anyone |
| `[DONE]` | Implementation complete | Devs |
| `[REVIEW_REQUEST]` | Requesting code review | Devs |
| `[REVIEW_PASS]` | Reviewer approved | Reviewer |
| `[REVIEW_FEEDBACK]` | Reviewer found issues | Reviewer |
| `[CROSS_TEST_START]` | Starting cross-test | Cross-testers |
| `[CROSS_TEST_PASS]` | Cross-test verified | Cross-testers |
| `[CROSS_TEST_FAIL]` | Cross-test found issues | Cross-testers |
| `[CROSS_TEST_BLOCKED]` | Cross-test could not start due to wrong worktree/branch or missing prereq | Cross-testers |
| `[FIX]` | Fixing issues from review/cross-test | Devs |
| `[SIGN_OFF]` | Final approval | Anyone signing off |
| `[FEEDBACK]` | Post-review feedback | Architect, PM |
| `[ORCH_HEARTBEAT]` | Orchestrator monitor-loop heartbeat line | Orchestrator monitor loop |
| `[COURSE_CORRECT]` | Orchestrator changed prompts/flow to recover the run | Orchestrator |
| `[MODEL_ESCALATION]` | Orchestrator raised model or effort tier | Orchestrator |
| `[GATE_MISS]` | Required launch/checkpoint/handoff was missed | Orchestrator, PM heartbeat |
| `[ARCH_RATIFY_REQUIRED]` | Technical course correction needs Architect confirmation | Orchestrator, Architect heartbeat |
| `[DELIVERY_NOTE]` | Delivery/process note from orchestrator or PM heartbeat | Orchestrator, PM heartbeat |

## Channels

| Channel | Purpose | Who Writes | Who Reads |
|---------|---------|------------|-----------|
| `.jsonl` stream logs | Real-time observability | Each role (auto) | Orchestrator (`tail -f`), Reviewer |
| Plan MD (inline sections) | Status, findings, sign-offs | Architect, PM, Devs, Reviewer, Cross-testers (own section only) | Everyone |
| Coordination MD | Task table, checkpoints, runtime registry, orchestrator intervention log, heartbeat snapshots, ratification queue | PM (initial), Orchestrator (updates), heartbeat snapshots | Everyone |
| `findings.md` | Reviewer summary | Reviewer only | Architect, PM, Orchestrator |

## Shared Root Rule

The authoritative orchestration docs live only in the ROOT `orchestration_run/` directory.
Devs in worktrees must edit those files via absolute `$PROJECT_ROOT/...` paths and must NOT use worktree-local copies.

## Section Ownership

- **Devs** write ONLY to their `Dev-N Notes` and `Cross-Test Thread` sections in the ROOT shared plan
- **Reviewer** writes ONLY to `Reviewer Findings` sections and `findings.md` in the ROOT shared docs
- **Heartbeat snapshots** write ONLY to `Heartbeat Snapshots` and `Ratification Queue` sections in ROOT `coordination.md`
- **No one** edits or overwrites another role's messages — append only
- **Orchestrator** updates top-level Status fields, Sign-off checkboxes, and the `Orchestrator Intervention Log` in ROOT `coordination.md`

## Back-and-Forth Protocol

Communication is a **conversation, not a one-way post**:

1. AUTHOR posts update → signals they're waiting
2. RESPONDER reads → posts response
3. AUTHOR reads response → posts follow-up if needed
4. REPEAT until both parties explicitly agree
5. Both parties sign off

**Key:** After posting, the poster WAITS. Orchestrator watches the thread and re-launches agents when their turn comes.

## Conflict Ownership

Each task explicitly lists owned files:
- Each dev owns conflicts in their listed files
- If Dev-A renames something Dev-B imports, Dev-B adapts within 1 cycle
- Reviewer never owns conflicts (read-only)
