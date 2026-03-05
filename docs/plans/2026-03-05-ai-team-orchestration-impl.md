# AI Team Orchestration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build all files in `.claude/orchestration/` — role prompts, protocols, templates, playbook, config, and README.

**Architecture:** Flat markdown files organized in `roles/`, `protocols/`, `templates/` subdirectories. Each role prompt is self-contained with an Override Notice header. The playbook is the orchestrator's step-by-step reference. Templates are blank fill-in documents for each orchestration run.

**Tech Stack:** Markdown only. No code, no tests. Verification = file exists + content matches design spec.

**Design doc:** `docs/plans/2026-03-05-ai-team-orchestration-design.md` — READ THIS FIRST for all specs.

---

## Parallelization Map

```
Task 1 (foundation) ──→ Tasks 2-9 (roles, all parallel) ──→ Task 12 (playbook)
                    ╰──→ Task 10 (protocols, parallel)   ──╯     │
                    ╰──→ Task 11 (templates, parallel)    ──╯     ▼
                                                              Task 13 (gitignore + verify)
```

Tasks 2-11 are fully independent and can be dispatched in parallel.

---

### Task 1: Directory Structure + config.md + README.md

**Files:**
- Create: `.claude/orchestration/README.md`
- Create: `.claude/orchestration/config.md`
- Create directories: `roles/`, `protocols/`, `templates/`

**Step 1: Create directory structure**

```bash
mkdir -p .claude/orchestration/roles
mkdir -p .claude/orchestration/protocols
mkdir -p .claude/orchestration/templates
```

**Step 2: Write config.md**

Create `.claude/orchestration/config.md`:

```markdown
# Orchestration Config

> Configurable values for each orchestration run. Copy this to `orchestration_run/config_instance.md` and fill in project-specific values.

## Team

```yaml
num_devs: 2
cross_test_strategy: round_robin  # Dev-K tests Dev-((K % N) + 1)
```

## Models

```yaml
architect_model: opus
pm_model: opus
dev_model: opus
reviewer_model: opus
crosstester_model: opus
bootstrap_model: sonnet  # cheaper for ACK prompts
effort: high
```

## Paths

```yaml
branch: feature/<name>
worktree_root: .worktrees/
log_dir: orchestration_run/logs/
run_dir: orchestration_run/
```

## Tool Restrictions Per Role

```yaml
architect_tools: Read,Write,Edit,Bash,Grep,Glob
pm_tools: Read,Write,Edit,Bash,Grep,Glob
dev_tools: Read,Write,Edit,Bash,Grep,Glob
reviewer_tools: Read,Bash
crosstester_tools: Read,Bash
ui_tester_tools: Read,Bash
```

## Reviewer Bash Allowlist

```yaml
reviewer_bash_allowlist:
  - git status --short
  - git diff
  - git log --oneline -20
  - python -m pytest
  - cat <file>
```

## Commit

```yaml
commit_target: branch  # NEVER main
```
```

**Step 3: Write README.md**

Create `.claude/orchestration/README.md`:

```markdown
# AI Team Orchestration System

A reusable framework for coordinating multiple Claude Code agents via an outer orchestrator (Codex).

## Quick Start

1. Read `playbook.md` — the orchestrator's step-by-step guide
2. Copy `config.md` to `orchestration_run/config_instance.md` and fill in values
3. Follow the playbook phases: PLAN → BUILD → CROSS-TEST → FEEDBACK → FINALIZE

## Folder Structure

```
.claude/orchestration/
├── README.md           ← you are here
├── playbook.md         ← orchestrator step-by-step
├── config.md           ← configurable values (copy per run)
├── roles/              ← self-contained agent prompts
├── protocols/          ← communication + lifecycle rules
└── templates/          ← blank fill-in documents for each run
```

## Key Concepts

- **Orchestrator (Codex)** is the event loop. It launches, monitors, nudges, and spins down agents.
- **Agents never poll.** The orchestrator decides when each agent has work and sends the prompt.
- **Deliver then die.** Workers run, produce deliverable, exit. Arch + PM persist for the session.
- **Worktrees** isolate dev work. Reviewer, PM, Architect, Orchestrator all work at root branch.
- **findings.md** is the reviewer's deliverable — includes test output, gaps, non-sprint issues.
- **Session memory** — Arch + PM write memory files (Phase 6) that carry forward to next session.

## Design Doc

Full specification: `docs/plans/2026-03-05-ai-team-orchestration-design.md`
```

**Step 4: Commit**

```bash
git add .claude/orchestration/README.md .claude/orchestration/config.md
git commit -m "orchestration: add directory structure, config, and README"
```

---

### Task 2: Role Template (_role_template.md)

**Files:**
- Create: `.claude/orchestration/roles/_role_template.md`

**Step 1: Write the template**

Create `.claude/orchestration/roles/_role_template.md`:

```markdown
# Override Notice
You are running as an orchestrated agent in `-p` mode.
IGNORE the following from AGENTS.md / CLAUDE.md:
- Rehydration contract (Tiers 0-3)
- Compaction behavior
- Auto-rollover rules
- Update protocol (todos/insights/run_log)
- Active project routing

FOLLOW these from AGENTS.md:
- Engineering Principles (Section: "Engineering Principles (Mandatory)")
- Cross-Agent Collaboration conventions (message tags, owner tags)

---

# Role: [ROLE NAME]

## Purpose
[What this agent does — 1-2 sentences]

## Rehydration
[What files to read on launch, or NONE for workers]

## Tools
[Full | Read,Bash | etc.]

## Owned Files
[Explicit list of files this agent may write to]

## Communication
- Post updates to: [specific section in plan MD]
- Message format: `[YYYY-MM-DD HH:MM] [AGENT-NAME] [TAG] — message`
- Standard tags: ACK, STATUS, DONE, REVIEW_REQUEST, REVIEW_PASS, REVIEW_FEEDBACK, CROSS_TEST_PASS, CROSS_TEST_FAIL, FIX, SIGN_OFF

## Deliverable
[What this agent produces before exiting]

## Constraints
[Hard limits — what NOT to do]

---

## Task Assignment
<!-- Orchestrator fills this section at launch time -->
```

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/_role_template.md
git commit -m "orchestration: add role template"
```

---

### Task 3: Architect Role Prompt

**Files:**
- Create: `.claude/orchestration/roles/architect.md`

**Step 1: Write architect.md**

Create `.claude/orchestration/roles/architect.md`. This is the full self-contained prompt. Key specs from design doc Section 4.1 and 11.1:

- Override Notice header (from _role_template.md pattern)
- Rehydrates on: `orchestration_run/architect_memory.md`, `00_admin/context.md`, `00_admin/insights.md`, `00_admin/todos.md`
- Strategic ownership: overall app architecture, technical roadmap, scope
- Engineering principles: reuse before create, modular/single-responsibility, user-configurable over hardcoded
- Known reusable components: DataTable.js, ConditionBuilder.js, CsdmTableRegistry, condition_query_builder.py, integration_properties pattern
- Known refactor debt: from AGENTS.md "Known Refactor Debt" section
- Task decomposition rules: independently implementable, max 3-5 owned files, single test command, explicit done criteria
- Output: plan MD matching `project_plan_template.md`
- Constraint: design for N parallel devs in worktrees — tasks cannot share files
- Tools: Full
- Deliverable: Plan MD with task breakdown + architecture notes
- After plan: stays idle, awaits feedback prompt

Full content: see file write below. The prompt should be ~80-100 lines of focused instructions.

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/architect.md
git commit -m "orchestration: add architect role prompt"
```

---

### Task 4: Project Manager Role Prompt

**Files:**
- Create: `.claude/orchestration/roles/project_manager.md`

**Step 1: Write project_manager.md**

Key specs from design doc Section 4.2 and 11.2:

- Override Notice header
- Rehydrates on: `orchestration_run/pm_memory.md`, `00_admin/context.md`, `00_admin/todos.md`, `00_admin/insights.md`
- Strategic ownership: sprint scope, delivery plan, backlog
- Acceptance criteria format: measurable done criteria per task
- Cross-test matrix: assign which dev tests which other dev
- Conflict ownership: explicit file ownership per task
- Coordination table: Owner/Status/Depends On/Notes columns
- PM Assignment Format: build task + cross-test + patch responsibility (Section 5.3)
- Plan MD Task Format: follow Section 5.4 format exactly
- Tools: Full
- Deliverable: Updated plan MD with assignments + coordination table

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/project_manager.md
git commit -m "orchestration: add project manager role prompt"
```

---

### Task 5: Dev Role Prompt

**Files:**
- Create: `.claude/orchestration/roles/dev.md`

**Step 1: Write dev.md**

Key specs from design doc Section 4.3 and 11.3:

- Override Notice header
- Rehydration: NONE — single-shot worker
- Owned files: from task assignment (max 3-5 — touch nothing else)
- Test command: from task assignment
- Done criteria: from PM's acceptance criteria
- Communication: post ONLY to "Dev-N Notes" section in plan MD
- Engineering principles: reuse existing components (list them), properties system for config
- TDD reminder: write tests first or alongside implementation
- Tools: Full
- Deliverable: implemented code + tests + `[DONE]` status posted
- Back-and-forth: if reviewer posts `[REVIEW_FEEDBACK]`, orchestrator re-launches with fix prompt

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/dev.md
git commit -m "orchestration: add dev role prompt"
```

---

### Task 6: Dev Cross-Tester Role Prompt

**Files:**
- Create: `.claude/orchestration/roles/dev_crosstester.md`

**Step 1: Write dev_crosstester.md**

Key specs from design doc Section 4.5:

- Override Notice header
- Rehydration: NONE
- Tools: Read + Bash ONLY — cannot edit code
- Purpose: test another dev's work in their worktree
- Read plan MD for the task being tested (done criteria, test commands)
- Run tests in target worktree via absolute paths
- Post results to "Cross-Test Thread" section
- Sign-off: `[CROSS_TEST_PASS]` or `[CROSS_TEST_FAIL]` with specific issues
- If FAIL: list exact file:line + issue. Wait for author to fix (orchestrator handles re-launch)
- Deliverable: cross-test results + sign-off tag

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/dev_crosstester.md
git commit -m "orchestration: add dev cross-tester role prompt"
```

---

### Task 7: Code Reviewer Role Prompt

**Files:**
- Create: `.claude/orchestration/roles/code_reviewer.md`

**Step 1: Write code_reviewer.md**

Key specs from design doc Section 4.4 and 11.4:

- Override Notice header
- Tools: Read + Bash ONLY
- File allowlist: plan MD, coordination MD, dev worktree paths (via absolute paths), stream logs
- Bash allowlist: `git status --short`, `git diff`, `git log`, `python -m pytest`, `cat`
- No edits — writes ONLY to "Reviewer Findings" sections in plan MD + `findings.md`
- Review checklist: spec compliance, test coverage, no hardcoded config, reuse of existing components, transaction safety, scope isolation
- Output format: exact file path + 1-line reason per finding
- Word limits: top 5 findings per task, under 140 words per review
- Findings.md final summary format (from design Section 11.4):
  - Per-Task Reviews: code quality, test output, test gaps, spec compliance
  - Cross-Cutting Issues: non-sprint issues, architecture concerns, process notes
  - Test Summary: total pass/fail/skip, new tests added, coverage gaps
- Deliverable: `findings.md` complete with structured summary

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/code_reviewer.md
git commit -m "orchestration: add code reviewer role prompt"
```

---

### Task 8: Feedback Re-Prompts (Architect + PM)

**Files:**
- Create: `.claude/orchestration/roles/architect_feedback.md`
- Create: `.claude/orchestration/roles/pm_feedback.md`

**Step 1: Write architect_feedback.md**

This is a short re-prompt sent to the already-alive Architect after reviewer posts findings. Specs from design Phase 4:

- Read `orchestration_run/findings.md`
- Post architecture lessons-learned to plan MD
- Flag systemic issues (coupling, scalability risks)
- Update roadmap view based on reviewer's non-sprint issues
- Optionally draft notes for next sprint in `architect_memory.md` under `## Next Sprint Prep`

**Step 2: Write pm_feedback.md**

Same pattern for PM:

- Read `orchestration_run/findings.md`
- Refine process notes
- Update backlog with non-sprint issues from reviewer
- Prioritize backlog items, draft rough task breakdown for next sprint
- Optionally write to `pm_memory.md` under `## Next Sprint Prep`

**Step 3: Commit**

```bash
git add .claude/orchestration/roles/architect_feedback.md .claude/orchestration/roles/pm_feedback.md
git commit -m "orchestration: add architect and PM feedback re-prompts"
```

---

### Task 9: UI Tester Role Prompt (Optional)

**Files:**
- Create: `.claude/orchestration/roles/ui_tester.md`

**Step 1: Write ui_tester.md**

Key specs from design Section 11.5:

- Override Notice header
- Tools: Read + Bash (Chrome MCP via extension)
- Chrome MCP capabilities: screenshot, read_page, find, navigate, left_click, form_input, get_page_text, read_console_messages, read_network_requests
- Prompt must include: URL to test, pages/flows to verify, expected elements, console error tolerance
- Deliverable: UI test results posted to plan MD + findings if issues found
- Optional role — only launched when project involves frontend changes

**Step 2: Commit**

```bash
git add .claude/orchestration/roles/ui_tester.md
git commit -m "orchestration: add UI tester role prompt"
```

---

### Task 10: Protocols (5 files)

**Files:**
- Create: `.claude/orchestration/protocols/communication.md`
- Create: `.claude/orchestration/protocols/plan_format.md`
- Create: `.claude/orchestration/protocols/cross_testing.md`
- Create: `.claude/orchestration/protocols/checkpoints.md`
- Create: `.claude/orchestration/protocols/lifecycle.md`

**Step 1: Write communication.md**

Extract from design Section 5: channels table, message format, standard tags, section ownership rules, conflict ownership, back-and-forth loop protocol.

**Step 2: Write plan_format.md**

Extract from design Section 5.3 + 5.4: PM assignment format (build + cross-test + patch per dev), plan MD task format (task header + dev notes + reviewer findings + cross-test thread + sign-offs).

**Step 3: Write cross_testing.md**

Extract from design Section 5.5 (cross-test loop) + config cross_test_strategy: round-robin matrix for N devs, cross-test procedure, PASS/FAIL protocol, patch re-launch loop.

**Step 4: Write checkpoints.md**

Extract from design Section 6: Checkpoints 0-5 with gate/action/unblocks for each.

**Step 5: Write lifecycle.md**

Extract from design Section 8: Phase 1 (PLAN) through Phase 6 (SESSION MEMORY) + Phase 5.5 (INTER-PHASE CLEANUP). Include the full spindown order. Include deliver-then-die pattern and orchestrator-as-event-loop principle.

**Step 6: Commit**

```bash
git add .claude/orchestration/protocols/
git commit -m "orchestration: add all protocol documents"
```

---

### Task 11: Templates (3 files)

**Files:**
- Create: `.claude/orchestration/templates/project_plan_template.md`
- Create: `.claude/orchestration/templates/coordination_template.md`
- Create: `.claude/orchestration/templates/findings_template.md`

**Step 1: Write project_plan_template.md**

Blank fill-in plan MD that architect + PM populate. Follows Section 5.4 format:

```markdown
# [Project Name] — Sprint Plan

**Date:** YYYY-MM-DD
**Branch:** feature/<name>
**Devs:** N
**Orchestration run:** orchestration_run/

---

## Architecture Notes
<!-- Architect fills this -->

## Task Breakdown

### Task 1: [Title]
**Assigned:** Dev-1 | **Status:** Pending
**Worktree:** .worktrees/dev_1 | **Branch:** dev_1/[feature]
**Stream:** logs/dev_1_stream.jsonl
**Cross-tester:** Dev-2
**Files owned:** [max 3-5]
**Test command:** [single command]
**Done criteria:** [from PM]

#### Dev-1 Notes:

#### Reviewer Findings:

#### Cross-Test Thread (Dev-1 ↔ Dev-2):

#### Sign-offs:
- [ ] Dev-1 (author)
- [ ] Dev-2 (cross-tester)
- [ ] Reviewer

<!-- Repeat for Task 2..N -->
```

**Step 2: Write coordination_template.md**

Task assignment table + checkpoint gates. From design Section 6 + Codex coordination pattern:

```markdown
# [Project Name] — Coordination

## Task Assignments

| Task | Owner | Status | Depends On | Notes |
|------|-------|--------|------------|-------|
| C0: Plan locked | Architect + PM | pending | — | |
| C1: Dev-1 build | Dev-1 | pending | C0 | |
| C2: Dev-2 build | Dev-2 | pending | C0 | |
| C3: Code review | Reviewer | pending | C1, C2 | |
| C4: Cross-test | Dev-1↔Dev-2 | pending | C3 | |
| C5: Feedback | Arch + PM | pending | C4 | |
| C6: Merge + commit | Orchestrator | pending | C5 | |

## Checkpoints
<!-- From protocols/checkpoints.md — fill in gate conditions per phase -->
```

**Step 3: Write findings_template.md**

From design Section 11.4 findings format:

```markdown
# Reviewer Findings — [Date]

## Per-Task Reviews

### Task 1: [Title]
- **Code quality issues:**
- **Test output:**
- **Test gaps:**
- **Spec compliance:**

### Task 2: [Title]
- **Code quality issues:**
- **Test output:**
- **Test gaps:**
- **Spec compliance:**

## Cross-Cutting Issues
- **Issues beyond this sprint:**
- **Architecture concerns:**
- **Process notes:**

## Test Summary
- **Total tests run:**
- **New tests added:**
- **Coverage gaps:**
```

**Step 4: Commit**

```bash
git add .claude/orchestration/templates/
git commit -m "orchestration: add project plan, coordination, and findings templates"
```

---

### Task 12: Playbook (Orchestrator Step-by-Step)

**Files:**
- Create: `.claude/orchestration/playbook.md`

**Depends on:** Tasks 1-11 (references all role files, protocols, templates)

**Step 1: Write playbook.md**

This is the orchestrator's (Codex) complete reference. Combines:

- Design Section 9 (Codex Playbook): prompt construction rules, monitoring checklist, decision points, anti-patterns
- Design Section 12 (Orchestrator Instructions): identity, rehydration, lifecycle rules, event loop, intervention rules, steering via live watch
- Design Section 13 (CLI Command Reference): launch commands, flags, monitoring, worktree management, process management, merge/commit
- Design Section 8 (Lifecycle Phases): Phase 1-6 + Phase 5.5 step-by-step with exact commands
- Design Section 7 (Terminal Lifecycle): deliver-then-die table, spindown order

Structure the playbook as:

```markdown
# Orchestration Playbook

> Step-by-step guide for the Orchestrator (Codex).

## Pre-Flight
1. Rehydrate on prior run memory + admin files
2. Copy config.md → orchestration_run/config_instance.md
3. Fill in project-specific values
4. Create orchestration_run/logs/ directory

## Phase 1: PLAN
[exact launch commands for architect, PM]
[checkpoint 0 gate]

## Phase 2: BUILD
[worktree creation commands]
[bootstrap + execution launch commands]
[reviewer + live watcher launch commands]
[monitoring commands]

## Phase 3: CROSS-TEST
[checkpoint 2 gate]
[cross-tester launch commands]
[back-and-forth mediation pattern]

## Phase 4: SPINDOWN + FEEDBACK
[explicit kill order]
[notification to arch+PM]
[feedback prompt commands]

## Phase 4.5: ROADMAP PREP (optional)
[roadmap prompts for arch+PM]

## Phase 5: FINALIZE
[merge commands]
[test commands]
[commit commands]

## Phase 5.5: CLEANUP
[worktree removal]
[log cleanup]
[archive previous run]

## Phase 6: SESSION MEMORY
[memory-write prompts]
[close terminals]

## CLI Quick Reference
[tables from design Section 13]

## Decision Points
[table from design Section 9]

## Anti-Patterns
[list from design Section 9]
```

**Step 2: Commit**

```bash
git add .claude/orchestration/playbook.md
git commit -m "orchestration: add orchestrator playbook with full lifecycle commands"
```

---

### Task 13: Gitignore + Final Verification

**Files:**
- Modify: `.gitignore`

**Step 1: Add gitignore entries**

Append to `.gitignore`:

```
# Ephemeral orchestration artifacts
orchestration_run/logs/*.jsonl
.worktrees/
```

**Step 2: Verify all files exist**

```bash
find .claude/orchestration -type f | sort
```

Expected output (20 files):
```
.claude/orchestration/README.md
.claude/orchestration/config.md
.claude/orchestration/playbook.md
.claude/orchestration/protocols/checkpoints.md
.claude/orchestration/protocols/communication.md
.claude/orchestration/protocols/cross_testing.md
.claude/orchestration/protocols/lifecycle.md
.claude/orchestration/protocols/plan_format.md
.claude/orchestration/roles/_role_template.md
.claude/orchestration/roles/architect.md
.claude/orchestration/roles/architect_feedback.md
.claude/orchestration/roles/code_reviewer.md
.claude/orchestration/roles/dev.md
.claude/orchestration/roles/dev_crosstester.md
.claude/orchestration/roles/pm_feedback.md
.claude/orchestration/roles/project_manager.md
.claude/orchestration/roles/ui_tester.md
.claude/orchestration/templates/coordination_template.md
.claude/orchestration/templates/findings_template.md
.claude/orchestration/templates/project_plan_template.md
```

**Step 3: Commit**

```bash
git add .gitignore
git commit -m "orchestration: add gitignore for ephemeral orchestration artifacts"
```

**Step 4: Final commit with all files**

```bash
git add .claude/orchestration/
git status
git commit -m "orchestration: complete AI team orchestration system — all roles, protocols, templates, and playbook"
```
