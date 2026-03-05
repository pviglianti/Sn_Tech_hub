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
| Reviewer | sonnet | medium | — | orchestration_run/logs/reviewer_stream.jsonl | — | — |
| Architect Heartbeat | opus | medium | — | orchestration_run/logs/architect_heartbeat_*.jsonl | — | — |
| PM Heartbeat | sonnet | low | — | orchestration_run/logs/pm_heartbeat_*.jsonl | — | — |
| Watcher (snapshot) | haiku | low | — | orchestration_run/logs/live_watch_*.jsonl | — | — |
| Scribe (optional snapshot) | haiku | low | — | orchestration_run/logs/scribe_*.jsonl | — | — |
| Orchestrator Monitor Loop | shell | n/a | — | orchestration_run/logs/orchestrator_heartbeat.log | — | — |
| Architect Digest | opus | medium | — | orchestration_run/logs/architect_digest_stream.jsonl | — | — |

## Checkpoint Status

| Checkpoint | Gate | Status | Passed At |
|-----------|------|--------|-----------|
| 0 — Plan Locked | Plan + coordination exist | [ ] | — |
| 1 — Bootstrap ACK Complete | All ACKs + gate script passed | [ ] | — |
| 1.5 — First DONE Response | Reviewer+watcher launched, rolling cross-test started if tester idle | [ ] | — |
| 2 — Implementation Complete | All [DONE] + reviewed | [ ] | — |
| 3 — Cross-Test Complete | All sign-offs | [ ] | — |
| 4 — Feedback Complete | Arch+PM feedback posted | [ ] | — |
| 5 — Session Memory | Memory files written | [ ] | — |

## Orchestrator Intervention Log

Append only. Use this for launch decisions, course corrections, missed gates, model/effort escalations, and ratification requests.

<!--
[YYYY-MM-DD HH:MM] [ORCHESTRATOR] [COURSE_CORRECT] — Tightened Dev-2 prompt after reviewer found drift in scan scope.
[YYYY-MM-DD HH:MM] [ORCHESTRATOR] [ARCH_RATIFY_REQUIRED] — Temporarily narrowed Task 3 ownership to avoid overlap; Architect heartbeat must confirm.
-->

## Heartbeat Snapshots

Append only. Architect/PM heartbeat snapshots post here.

<!--
[YYYY-MM-DD HH:MM] [ARCH-HB] [STATUS] — No design drift. Task boundaries still hold. No tier change needed.
[YYYY-MM-DD HH:MM] [PM-HB] [GATE_MISS] — First [DONE] posted 6 minutes ago; reviewer not launched yet. Next action: launch reviewer now.
-->

## Ratification Queue

Use when the orchestrator made a temporary technical correction that needs Architect confirmation.

<!--
- [ ] [ARCH_RATIFY_REQUIRED] Task/file boundary change approved by Architect
- [ ] [ARCH_RATIFY_REQUIRED] Model/reasoning escalation recommendation reviewed by Architect
-->
