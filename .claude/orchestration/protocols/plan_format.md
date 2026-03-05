# Plan MD Format

The authoritative plan file is the ROOT shared `orchestration_run/plan.md`. Devs in worktrees must update it via absolute `$PROJECT_ROOT/...` paths, never via worktree-local copies.

The plan MD is the central document for each orchestration run. Created by Architect, refined by PM.

## Structure

```markdown
# Sprint Plan — [Feature/Sprint Name]

**Date:** YYYY-MM-DD
**Architect:** [Architect agent]
**PM:** [PM agent]
**Devs:** N

## Sprint Goal
[1-2 sentences describing what this sprint builds]

## Architecture Notes
[Architect's high-level approach, key patterns, reusable components to leverage]

---

### Task 1: [Title]
**Assigned:** Dev-1 | **Status:** Pending
**Worktree:** .worktrees/dev_1 | **Branch:** dev_1/[feature]
**Stream:** orchestration_run/logs/dev_1_stream.jsonl
**Cross-tester:** Dev-2
**Files owned:** [explicit list — max 3-5 files]
**Test command:** [single command]
**Done criteria:** [from PM — measurable]

#### Dev-1 Notes:
<!-- Dev-1 writes status updates here during build phase -->

#### Reviewer Findings:
<!-- Code reviewer writes findings here — read-only otherwise -->

#### Cross-Test Thread (Dev-1 ↔ Dev-2):
<!-- CONVERSATION. Both parties write here. Back and forth until agreed. -->

#### Sign-offs:
- [ ] Dev-1 (author) — implementation complete, tests pass
- [ ] Dev-2 (cross-tester) — tested, verified, agreed
- [ ] Reviewer — code quality approved

---

### Task 2: [Title]
<!-- Same structure as Task 1 -->

---

## Architect Feedback
<!-- Architect posts lessons-learned after reviewing findings -->

## PM Feedback
<!-- PM posts process notes and backlog updates after reviewing findings -->
```

## Rules

- Each task has exactly ONE assigned dev
- File ownership lists must NOT overlap between tasks
- Test command must be a SINGLE command
- Done criteria must be measurable (test counts, exit codes, specific behaviors)
- Status values: `Pending` → `In Progress` → `Done` → `Testing` → `Agreed` → `Signed Off`
