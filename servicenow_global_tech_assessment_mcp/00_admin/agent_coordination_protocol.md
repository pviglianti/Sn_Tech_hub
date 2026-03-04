# Agent Coordination Protocol

> **Purpose:** Standard protocol for multi-agent collaboration. Any project phase that requires coordinated work between Claude, Codex, or other agents MUST create a phase-specific coordination file that follows this template.

---

## How to Start a Coordinated Phase

1. **Create a coordination file:** `<phase_name>_coordination.md` in this directory.
2. **Create a chat file:** `<phase_name>_chat.md` in this directory.
3. **Populate the coordination file** using the templates below.
4. **Both agents read** the coordination file before starting work.
5. **All back-and-forth messages** go in the chat file. The coordination file stays clean as the protocol reference + status tracker.

---

## Communication Protocol

### Message format
```
[YYYY-MM-DD HH:MM] [AGENT] [TAG] — message
```

### Where to post
- **Chat messages** → `<phase_name>_chat.md`
- **Task status changes** → coordination file's Task Assignments table
- **Admin updates** → `todos.md`, `context.md` (per AGENTS.md Update Protocol)

### Message types

| Tag | Meaning | Expected response |
|-----|---------|-------------------|
| `STATUS` | Progress update, no response needed | None |
| `QUESTION` | Needs answer before continuing | Answer within next check-in |
| `REVIEW_REQUEST` | Code ready for review | `REVIEW_PASS` or `REVIEW_FEEDBACK` |
| `REVIEW_PASS` | Approved, no changes needed | Owner sets status to `approved` |
| `REVIEW_FEEDBACK` | Changes needed (details follow) | Owner addresses, re-requests review |
| `BLOCKED` | Cannot proceed, needs help | Other agent investigates |
| `APPROVED` | Final sign-off on a checkpoint | — |

### Check-in cadence
- After completing each task, check the chat file for pending questions or review requests.
- After posting a `QUESTION`, expect the other agent to respond on their next check-in.
- If blocked for more than one task cycle, escalate to human via `todos.md`.

---

## Task Lifecycle

### Status values
```
not_started → in_progress → tests_passing → review_requested → approved → done
```

### Rules
- Only the **owner** moves a task from `not_started` to `in_progress`.
- Owner sets `tests_passing` when their tests pass and the full suite has no regressions.
- Owner sets `review_requested` and posts a `REVIEW_REQUEST` in chat.
- **Reviewer** (the other agent) sets `approved` after passing review, or posts `REVIEW_FEEDBACK`.
- Owner or lead sets `done` after all downstream dependencies are resolved.

---

## Review Requirements

Before marking a task `approved`, the reviewer MUST verify:

1. **Tests exist and pass** — run the task's specific test file.
2. **Follows established patterns** — matches codebase conventions (idempotency, commit behavior, return shapes, import style).
3. **No regressions** — full test suite passes (`pytest --tb=short`).
4. **Matches the plan** — or deviations are documented with rationale.

---

## Checkpoint Pattern

Checkpoints are gates that control task unblocking. Each coordinated phase should define checkpoints:

```markdown
### Checkpoint N — [Name]
- **Gate:** [What must be true]
- **Action:** [Who does what when gate is met]
- **Unblocks:** [Which tasks can now start]
```

### Final checkpoint (always required)
- **Gate:** Full test suite green, both agents post `APPROVED` in chat.
- **Action:** Update `todos.md` + `context.md` per AGENTS.md Update Protocol.

---

## Coordination File Template

```markdown
# [Phase Name] — Coordination

> **Purpose:** Shared coordination file for [agents] during [phase description].
> Both agents MUST monitor this file for updates after completing development work.

**Plan document:** `[path to plan]`

---

## Task Assignments

| Task | Owner | Status | Depends On |
|------|-------|--------|------------|
| Task 0: [description] | [agent] | `not_started` | — |
| Task 1: [description] | [agent] | `not_started` | Task 0 |

---

## Checkpoints

### Checkpoint 1 — [Name]
- **Gate:** [conditions]
- **Action:** [who does what]
- **Unblocks:** [tasks]

### Checkpoint N — Final Sign-Off
- **Gate:** Full test suite green, both agents approve.
- **Action:** Both post `APPROVED` in chat. Update `todos.md` + `context.md`.

---

## Shared Conventions

### File locations
- [List relevant paths for this phase]

### Interface contracts
- [Define shared code contracts if applicable]

### Known implementation notes
- [Per-agent notes and gotchas]

---

## Chat Log

All messages go in **`<phase_name>_chat.md`** (same directory).
```

---

## Past Coordination Phases

| Phase | Files | Status | Outcome |
|-------|-------|--------|---------|
| Phase 2 Engines | `phase2_coordination.md` / `phase2_chat.md` | Complete | 6 engines, 276 tests, both agents approved |
