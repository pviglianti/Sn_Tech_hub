# Agent Coordination Protocol

> **Purpose:** Standard protocol for multi-agent collaboration. Any project phase that requires coordinated work between Claude, Codex, or other agents MUST create a phase-specific coordination file that follows this template.
>
> **Scope note:** This protocol is for interactive/shared-workspace collaboration. If a run is using the `.claude/orchestration/` event-loop system, that playbook and its role prompts take precedence over the chat-polling model described here.

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
- **Admin updates** → `todos.md`, `insights.md`, `run_log.md`, `context.md` (per AGENTS.md Update Protocol)

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

### Autonomous operation (CRITICAL)

Agents MUST operate autonomously without human prompting between tasks:

1. **On session start:** Read the active phase chat file BEFORE doing anything else. Check for pending `QUESTION`, `REVIEW_REQUEST`, or `BLOCKED` messages from the other agent and respond to them first.
2. **After completing a task:** Immediately re-read the chat file. If the other agent has posted work, review it. If they asked a question, answer it. Do not wait for the human to prompt you to check.
3. **After posting a `REVIEW_REQUEST`:** Continue to your next unblocked task. Do not idle waiting for review.
4. **After posting a `QUESTION`:** If you have other unblocked tasks, continue working on those while waiting.
5. **When all your tasks are done:** Re-read the chat file one final time. If the other agent has pending review requests, review them. If they have questions, answer them. Post a `STATUS` noting you are caught up.
6. **Cross-verification:** After the other agent completes a task that produces code, run their tests (`pytest tests/test_<name>.py -v`) and the full regression (`pytest --tb=short -q`) to verify independently. Do not assume their reported results are current.
7. **UI verification:** When tasks produce visible UI changes, Claude should use browser automation tools (Chrome extension MCP) to take screenshots and verify the UI renders correctly. Post screenshots or observations in the chat.

### Token-efficient communication

- **Chat messages:** Keep STATUS messages to 1-3 sentences. Save detail for REVIEW_REQUEST and REVIEW_FEEDBACK.
- **Code review posts:** List files reviewed + pass/fail verdict + specific issues (if any). Do not paste full code in chat.
- **Plan discussions:** Post proposed structure first (bullet outline), iterate on structure before writing prose.
- **Avoid restating what the other agent said.** Reference by message timestamp if needed.
- **Batch related updates.** If completing 3 tasks in sequence, post one combined STATUS rather than 3 separate ones.

### Quality gates

- **Before claiming a task `tests_passing`:** Actually run the tests and paste the summary line (e.g., "274 passed, 0 failures"). Do not rely on memory.
- **Before claiming UI work done:** Start the app, load the page, verify no JS console errors. Claude should screenshot via browser tools when possible.
- **Before marking a plan `approved`:** Both agents must have posted concrete feedback (not just "looks good"). Identify at least one improvement or explicitly confirm each section.
- **Addendums:** Non-blocking improvements discovered during review should be numbered (A1, A2, ...) and tracked. Owner integrates them during the relevant implementation phase.

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
5. **UI verification (for frontend tasks):** If the task changes templates, JS, or CSS, Claude should start the app and use browser tools to verify the pages render correctly (tabs load, data displays, no JS console errors). Post screenshot observations in chat.

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
- **Action:** Update `todos.md`, `insights.md`, `run_log.md`, and `context.md` per AGENTS.md Update Protocol.

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
- **Action:** Both post `APPROVED` in chat. Update `todos.md`, `insights.md`, `run_log.md`, and `context.md`.

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
| Phase 2 Engines | `archive/2026-03-05_markdown_cleanup/servicenow_global_tech_assessment_mcp/00_admin/phase2_coordination.md` / `archive/2026-03-05_markdown_cleanup/servicenow_global_tech_assessment_mcp/00_admin/phase2_chat.md` | Complete | 6 engines, 276 tests, both agents approved |
| Phase 3 UI + AI Feature Orchestration | `phase3_coordination.md` / `phase3_planning_chat.md` | Plan approved, execution pending | 8 tasks (P3A-P3D, P4A-P4D) |
