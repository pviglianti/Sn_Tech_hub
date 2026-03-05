# Coordination Table — [Sprint Name]

**Date:** YYYY-MM-DD
**PM:** PM Agent

## Task Assignments

| Task | Owner | Status | Worktree | Cross-Tester | Depends On |
|------|-------|--------|----------|-------------|------------|
| Task 1: [Title] | Dev-1 | Pending | .worktrees/dev_1 | Dev-2 | — |
| Task 2: [Title] | Dev-2 | Pending | .worktrees/dev_2 | Dev-1 | — |

**Status values:** Pending → In Progress → Done → Testing → Agreed → Signed Off

## File Ownership Map

| File | Owner | Task |
|------|-------|------|
| `path/to/file_a.py` | Dev-1 | Task 1 |
| `path/to/file_b.py` | Dev-1 | Task 1 |
| `path/to/file_c.py` | Dev-2 | Task 2 |
| `path/to/file_d.py` | Dev-2 | Task 2 |

**Rule:** No overlaps. If two tasks need the same file, restructure or sequence them.

## Cross-Test Matrix

| Tester | Tests | Worktree |
|--------|-------|----------|
| Dev-2 | Task 1 (Dev-1's work) | .worktrees/dev_1 |
| Dev-1 | Task 2 (Dev-2's work) | .worktrees/dev_2 |

## Runtime Registry

Record every backgrounded orchestration launch here before moving to the next step.

| Role | Model | Effort | PID | Log Path | Started At | Stopped At |
|------|-------|--------|-----|----------|------------|------------|
| Architect | opus | high | — | orchestration_run/logs/architect_stream.jsonl | — | — |
| PM | sonnet | medium | — | orchestration_run/logs/pm_stream.jsonl | — | — |
| Dev-1 | sonnet | medium | — | orchestration_run/logs/dev_1_stream.jsonl | — | — |
| Dev-2 | opus | high | — | orchestration_run/logs/dev_2_stream.jsonl | — | — |

## Checkpoint Status

| Checkpoint | Gate | Status | Passed At |
|-----------|------|--------|-----------|
| 0 — Plan Locked | Plan + coordination exist | [ ] | — |
| 1 — Bootstrap ACK Complete | All ACKs + gate script passed | [ ] | — |
| 2 — Implementation Complete | All [DONE] + reviewed | [ ] | — |
| 3 — Cross-Test Complete | All sign-offs | [ ] | — |
| 4 — Feedback Complete | Arch+PM feedback posted | [ ] | — |
| 5 — Session Memory | Memory files written | [ ] | — |
