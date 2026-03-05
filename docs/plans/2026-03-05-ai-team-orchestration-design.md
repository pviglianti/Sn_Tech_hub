# AI Team Orchestration System — Design Document

**Date:** 2026-03-05
**Status:** Draft — post-review revision (Codex review 2026-03-05)
**Scope:** Generic reusable template + project-specific instantiation
**Prior art:** `terminal_worker_orchestration_playbook_2026-03-05.md` (Codex), `phase11c_cleanup_coordination.md` (Codex)

---

## 1. Problem

Coordinating multiple AI agents (architect, PM, devs, reviewer) on a shared codebase requires:
- Structured role definitions with explicit tool/file permissions
- A communication protocol that doesn't create file conflicts
- A lifecycle that sequences planning → building → reviewing → cross-testing → commit
- An outer orchestrator (Codex) that can observe and intervene in real-time via stream logs

No existing skill or playbook covers this end-to-end.

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Outer orchestrator | Codex | Already manages terminal sessions, watches streams |
| Inner agents | Claude Code via `claude -p` | Each role is a Claude instance with scoped prompt |
| Communication | Inline in plan MD via **absolute paths** | Single source of truth; devs in worktrees use `$PROJECT_ROOT/orchestration_run/plan.md` |
| Observability | `.jsonl` stream logs per role | Codex watches via `tail -f`, reviewer reads for findings |
| Dev isolation | Git worktrees (1 per dev) | Independent workspaces, merge to branch at end |
| Shared-state access | All shared files live in ROOT `orchestration_run/` | Devs access via absolute `$PROJECT_ROOT/...` path — never worktree-local copies |
| Reviewer access | Read + Edit + Bash | Can edit designated plan MD sections + findings.md; prompt-constrained to own sections only |
| Cross-testing | Devs re-launched as testers (Read + Edit + Bash) | Can post pass/fail to Cross-Test Thread sections via Edit |
| Team size | Configurable N devs | Cross-test matrix generated from config |
| Commit target | Feature branch only, never main | Codex commits after all sign-offs |
| Arch/PM lifecycle | Fresh `-p` relaunches with memory files | Each prompt is a new `-p` call; memory files provide continuity; zero cost between prompts |
| Coordination precedence | Orchestrated runs: `.claude/orchestration/*` overrides `agent_coordination_protocol.md` | Non-orchestrated pair work still uses the chat/coordination protocol |
| Worker startup | Two-step: bootstrap ACK → execution prompt | Avoids monolithic prompts that stall (from Codex playbook) |
| Model strategy | Task-dependent model + reasoning selection | Architect stays `opus` + highest reasoning; other roles start cheap when the prompt is prescribed and escalate only if the stream shows it is necessary |
| Message format | `[YYYY-MM-DD HH:MM] [AGENT] [TAG] — message` | Standardized, parseable (from Codex coordination) |

---

## 3. Folder Structure

### Generic Template (`.claude/orchestration/`)

```
.claude/orchestration/
├── README.md                       # How to use this system
├── playbook.md                     # Step-by-step for Codex (outer orchestrator)
├── config.md                       # Configurable: num devs, branch, paths, models, tool sets
│
├── roles/
│   ├── architect.md                # Designs architecture, defines task breakdown
│   ├── project_manager.md          # Refines plan, assigns devs, sets acceptance criteria
│   ├── architect_feedback.md       # Re-prompt for architect after reviewer findings
│   ├── pm_feedback.md              # Re-prompt for PM after reviewer findings
│   ├── dev.md                      # Implements assigned task in worktree
│   ├── dev_crosstester.md          # Re-launched dev in code-read-only mode to test another dev's work
│   ├── code_reviewer.md            # Constrained reviewer, documents findings in shared review sections
│   └── _role_template.md           # Blank template for custom roles
│
├── protocols/
│   ├── plan_format.md              # How the project plan MD is structured
│   ├── communication.md            # Inline update rules: tags, sections, sign-off format
│   ├── cross_testing.md            # Cross-test assignment matrix for N devs
│   ├── checkpoints.md              # Gate/action/unblocks for phase transitions
│   └── lifecycle.md                # Full workflow: plan → build → review → test → commit → spindown
│
└── templates/
    ├── project_plan_template.md    # Blank plan MD that architect/PM fill out
    ├── coordination_template.md    # Task assignment table + checkpoint gates
    └── findings_template.md        # Reviewer findings summary template
```

### Project Instance (created per run)

```
<project>/orchestration_run/
├── plan.md                         # The project plan (from architect + PM)
├── coordination.md                 # Task table + checkpoints (from Codex pattern)
├── findings.md                     # Reviewer's accumulated findings
├── config_instance.md              # Resolved config for this run
├── architect_memory.md             # Architect's session memory (written Phase 6)
├── pm_memory.md                    # PM's session memory (written Phase 6)
└── logs/
    ├── architect_stream.jsonl
    ├── pm_stream.jsonl
    ├── dev_1_stream.jsonl
    ├── dev_N_stream.jsonl
    ├── reviewer_stream.jsonl
    └── dev_N_crosstest.jsonl
```

---

## 4. Role Definitions

### 4.0 Model / Reasoning Policy

- **Architect is fixed at the top tier:** `opus` + `--effort high` for planning, feedback, roadmap work, and architecture memory.
- **PM usually starts at:** `sonnet` + `medium`. Escalate only if the planning/refinement prompt is ambiguous or repeatedly misses acceptance criteria.
- **Dev execution is task-dependent:**
  - tightly prescribed / low-risk work can start at `haiku` + `low` or `sonnet` + `medium`
  - normal implementation defaults to `sonnet` + `medium`
  - risky refactors, migrations, ambiguous bugs, or repeated misses move to `opus` + `high`
- **Mixed overrides are valid:** For narrow but high-stakes work, Codex can choose `opus` + `medium` instead of jumping straight to `opus` + `high`.
- **Reviewer is task-dependent:** default `sonnet` + `medium`, escalate to `opus` + `high` for deep architectural, security, or repeated-failure review.
- **Cross-testers default cheap:** `haiku` + `low` for exact reruns/checklists; escalate to `sonnet` + `medium` or higher when diagnosis is required.
- **Live watcher stays cheap:** `haiku` + `low`.
- **Steer before escalate:** Because all substantive launches are streamed, Codex should first tighten scope, add exact repro steps/files, or narrow acceptance criteria before upgrading model or reasoning.
- **Record launch choices:** Model, effort, PID, and log path for each backgrounded role should be recorded in `orchestration_run/coordination.md`.

### 4.1 Architect (runs in root branch — strategic, re-launched with memory)

**Purpose:** Own the overall app architecture, roadmap, and technical scope. Design the technical approach for the current sprint and break work into independent tasks.

**Rehydration:** Each launch reads:
- Previous session memory: `orchestration_run/architect_memory.md` (if exists from prior run)
- Admin context: `00_admin/context.md`, `00_admin/insights.md` (Active Decisions)
- Current scope: `00_admin/todos.md` (to understand the full roadmap)

**Launch (streamed so Codex can observe planning):**
```bash
claude -p --verbose --model opus --effort high \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/architect.md)" > orchestration_run/logs/architect_stream.jsonl 2>&1
```

**Tools:** Full (Read, Write, Edit, Bash, Grep, Glob)
**Runs in:** Root branch (NOT a worktree)
**Owns:** Overall app architecture, technical roadmap, scope decisions
**Outputs:** Plan MD with task breakdown, architecture notes, posted to root branch
**Lifecycle:** Fresh `-p` relaunch for each prompt (planning, feedback, roadmap, memory-write). Memory files provide continuity between relaunches. Zero cost between prompts — no running process.

### 4.2 Project Manager (runs in root branch — strategic, re-launched with memory)

**Purpose:** Own the project plan, sprint scope, and delivery roadmap. Refine tasks, assign to dev slots, set acceptance criteria.

**Rehydration:** Each launch reads:
- Previous session memory: `orchestration_run/pm_memory.md` (if exists from prior run)
- Admin context: `00_admin/context.md`, `00_admin/todos.md` (full roadmap — Now/Next/Backlog)
- Active decisions: `00_admin/insights.md` (to carry forward project decisions)

**Launch (default starting tier):**
```bash
claude -p --verbose --model sonnet --effort medium \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/project_manager.md)" > orchestration_run/logs/pm_stream.jsonl 2>&1
```
**Tools:** Full
**Runs in:** Root branch (NOT a worktree)
**Owns:** Sprint scope, task assignments, acceptance criteria, delivery plan, backlog management
**Outputs:** Updated plan MD with assignments, done criteria, coordination table
**Lifecycle:** Fresh `-p` relaunch for each prompt (planning, feedback, roadmap, memory-write). Memory files provide continuity between relaunches. Zero cost between prompts — no running process.

### 4.3 Dev (Build Phase — runs in worktree)

**Purpose:** Implement assigned task in isolated worktree.

**Startup — Two-step pattern (from Codex playbook):**

Step 1 — Bootstrap (short, fast):
```bash
claude -p --verbose --model haiku --effort low \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "Role: Dev-N. Read shared plan at $PROJECT_ROOT/orchestration_run/plan.md. Read your task (Task N). Post [ACK] to the shared root plan via that absolute path. Exit." \
  > orchestration_run/logs/dev_N_bootstrap.jsonl 2>&1
```

Step 2 — Execution (streamed):
```bash
claude -p --verbose --model "$DEV_MODEL" --effort "$DEV_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat /tmp/dev_N_prompt.txt)" > orchestration_run/logs/dev_N_stream.jsonl 2>&1
```

**Default tier:** `sonnet` + `medium`
**Escalation tier:** `opus` + `high` for ambiguous/risky work
**Cheap tier:** `haiku` + `low` only for tightly prescribed, low-risk tasks with easy-to-spot failures

**Tools:** Full (Read, Write, Edit, Bash, Grep, Glob)
**Worktree:** `.worktrees/dev_N/`
**Rehydration:** NONE — devs are single-shot workers. They receive their task inline in the prompt. No session memory, no admin files.
**Outputs:** Implemented code + tests in worktree, inline status in the shared ROOT `orchestration_run/plan.md` via absolute path
**Exits after:** Implementation complete, tests passing, status posted

### 4.4 Code Reviewer (runs in root branch, constrained-write)

**Purpose:** Continuous constrained reviewer. Inspects dev work via stream logs and bash commands and writes findings only to designated shared review sections.

**Launch:**
```bash
claude -p --verbose --model "$REVIEWER_MODEL" --effort "$REVIEWER_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Edit,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat /tmp/reviewer_prompt.txt)" > orchestration_run/logs/reviewer_stream.jsonl 2>&1
```

**Tools:** Read + Edit + Bash
**Runs in:** Root branch — reads worktree files via absolute paths
**Hard constraints (prompt-enforced):**
- Explicit file allowlist (ROOT `orchestration_run/plan.md`, `coordination.md`, `findings.md`, dev worktree paths, stream logs)
- Allowed bash: `git status --short`, `git diff`, `git log`, test commands
- **No code edits** — may edit ONLY Reviewer Findings sections in the shared ROOT plan MD and `findings.md`
- Structured output: exact file path + 1-line reason per finding
**Default tier:** `sonnet` + `medium`
**Escalation tier:** `opus` + `high` for deep/risky review
**Starts:** After the first dev posts `[DONE]`
**Exits after:** All tasks reviewed, final summary posted

### 4.5 Dev (Cross-Test Phase — constrained-write)

**Purpose:** Test another dev's work. Read-only against code, constrained-write against the shared review thread.

**Launch:**
```bash
claude -p --verbose --model "$CROSSTEST_MODEL" --effort "$CROSSTEST_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Edit,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat /tmp/dev_N_crosstest_prompt.txt)" > orchestration_run/logs/dev_N_crosstest.jsonl 2>&1
```

**Tools:** Read + Edit + Bash
**Default tier:** `haiku` + `low`
**Escalation tier:** `sonnet` + `medium` or higher when diagnosis is needed
**Outputs:** Cross-test results inline in the shared ROOT plan MD under the task being tested
**Sign-off:** Posts `[CROSS_TEST_PASS]` or `[CROSS_TEST_FAIL]` with issues

---

## 5. Communication Protocol

### 5.1 Channels

| Channel | Purpose | Who writes | Who reads | How |
|---------|---------|------------|-----------|-----|
| `.jsonl` stream logs | Real-time observability | Each role (automatic) | Codex (`tail -f`), Reviewer | `tail -f orchestration_run/logs/*_stream.jsonl` |
| Plan MD (inline sections) | Structured status, findings, sign-offs | Architect, PM, Devs, Reviewer, Cross-testers (own section only) | Everyone | Edit/read the single ROOT copy via absolute path |
| Coordination MD | Task table, checkpoints, gates, runtime registry | PM (initial), Codex (status + PID/process updates) | Everyone | Edit/read the single ROOT copy via absolute path |
| findings.md | Reviewer summary for arch/PM feedback | Reviewer only | Architect, PM, Codex | Read file |

**Shared-state rule:** The authoritative orchestration docs live only in the ROOT `orchestration_run/` directory. Devs in worktrees MUST edit those files via absolute `$PROJECT_ROOT/...` paths and MUST NOT edit worktree-local copies.

### 5.2 Message Format Standard

All inline updates use:
```
[YYYY-MM-DD HH:MM] [AGENT] [TAG] — message
```

**Standard tags:**
- `[ACK]` — task acknowledged, starting work
- `[STATUS]` — progress update
- `[DONE]` — task implementation complete
- `[REVIEW_REQUEST]` — requesting code review
- `[REVIEW_PASS]` — reviewer approved
- `[REVIEW_FEEDBACK]` — reviewer found issues (list follows)
- `[CROSS_TEST_PASS]` — cross-tester verified
- `[CROSS_TEST_FAIL]` — cross-tester found issues (list follows)
- `[FIX]` — fixing issues from review/cross-test
- `[SIGN_OFF]` — final approval

### 5.3 PM Assignment Format (What Each Dev Receives)

The PM assigns each dev THREE responsibilities upfront:

```markdown
## Dev-N Assignment

### A. Build Task
- **Task:** [Task N title]
- **Files owned:** [explicit list — max 3-5 files]
- **Test command:** [single command]
- **Done criteria:** [measurable acceptance criteria]
- **Shared plan path:** `$PROJECT_ROOT/orchestration_run/plan.md`

### B. Cross-Test Assignment
- **Test:** Dev-M's Task M
- **Worktree to test:** .worktrees/dev_M
- **What to verify:** [specific test criteria from Task M's done criteria]
- **Test command:** [command to run in Dev-M's worktree]

### C. Patch Responsibility
- If Dev-M (your cross-tester) finds issues in YOUR Task N:
  - You will be re-launched to fix
  - Fix, re-run tests, post update
  - Wait for Dev-M to re-verify
  - Repeat until Dev-M signs off
```

### 5.4 Plan MD Task Format

```markdown
### Task N: [Title]
**Assigned:** Dev-N | **Status:** [Pending | In Progress | Done | Testing | Agreed | Signed Off]
**Worktree:** .worktrees/dev_N | **Branch:** dev_N/[feature]
**Stream:** orchestration_run/logs/dev_N_stream.jsonl
**Cross-tester:** Dev-M
**Files owned:** [explicit list — max 3-5 files]
**Test command:** [single command]
**Done criteria:** [from PM]

#### Dev-N Notes:
<!-- Dev writes here during build phase -->

#### Reviewer Findings:
<!-- Code reviewer writes here — read-only otherwise -->

#### Cross-Test Thread (Dev-N ↔ Dev-M):
<!-- This is a CONVERSATION. Both parties write here. Back and forth until agreed. -->

#### Sign-offs:
- [ ] Dev-N (author) — implementation complete, tests pass
- [ ] Dev-M (cross-tester) — tested, verified, agreed
- [ ] Reviewer — code quality approved
```

### 5.5 Communication Protocol — The Back-and-Forth Loop

Communication under each task is a **conversation, not a one-way post**. The protocol is:

```
1. AUTHOR posts update → sets status to signal they're waiting
2. RESPONDER reads update → posts response
3. AUTHOR reads response → posts follow-up if needed
4. REPEAT until both parties explicitly agree
5. Both parties sign off
```

**Build → Review loop (Dev ↔ Reviewer):**
```
Dev-N: [DONE] — Implementation complete, 8/8 tests passing. Ready for review.
  (Dev-N WAITS — does not start cross-testing yet)
Reviewer: [REVIEW_FEEDBACK] — Missing error handling line 42, no test for empty input.
  (Reviewer WAITS for Dev-N to fix)
Dev-N: [FIX] — Added error handling + empty input test. Now 10/10 passing.
  (Dev-N WAITS for Reviewer re-check)
Reviewer: [REVIEW_PASS] — Issues resolved. Approved.
  (Dev-N can now proceed to cross-testing)
```

**Cross-Test loop (Dev-N author ↔ Dev-M tester):**
```
Dev-M: [CROSS_TEST_START] — Running tests in Dev-N's worktree.
Dev-M: [CROSS_TEST_FAIL] — Edge case with empty list crashes. Test added, fails.
  (Dev-M WAITS for Dev-N to fix)
Dev-N: [FIX] — Fixed empty list handling. Test passing in my worktree.
  (Dev-N WAITS for Dev-M to re-verify)
Dev-M: [CROSS_TEST_PASS] — Verified fix. All tests passing. ✅
  (Dev-M signs off)
Dev-N: [SIGN_OFF] — Agreed. ✅
  (Dev-N signs off)
```

**Key rules:**
- After posting, the poster **WAITS** — does not proceed until response received
- Orchestrator watches the thread and re-launches agents when their turn comes
- A task is only `Agreed` when BOTH author and cross-tester have explicitly signed off
- Reviewer sign-off is independent of cross-test sign-off (both required)
- No one edits another party's messages — only append new messages
- All shared-thread updates go to the single ROOT `orchestration_run/plan.md` copy via absolute path

### 5.6 Section Ownership Rules

- **Devs** write ONLY to their own "Dev-N Notes" and the "Cross-Test Thread" for tasks they're involved in, and only in the ROOT shared plan
- **Reviewer** writes ONLY to "Reviewer Findings" sections and findings.md in the ROOT shared docs
- **No one** edits or overwrites another role's messages
- **Codex** updates top-level Status fields and Sign-off checkboxes based on thread state

### 5.7 Conflict Ownership (from Codex pattern)

Each task explicitly lists owned files. Conflict resolution:
- Each dev owns conflicts in their listed files
- If Dev-A renames something Dev-B imports, Dev-B adapts within 1 cycle
- Reviewer never owns conflicts (read-only)

---

## 6. Checkpoints and Gates

Formal phase transitions (from Codex coordination pattern):

### Checkpoint 0 — Plan Locked
- **Gate:** Architect + PM both posted plan, coordination table exists
- **Action:** Codex creates worktrees, generates dev prompts
- **Unblocks:** Dev launch

### Checkpoint 1 — Devs Launched
- **Gate:** All worktrees created, dev bootstrap ACKs received
- **Action:** Codex sends execution prompts. Reviewer and live watcher launch only after the first dev posts `[DONE]`.
- **Unblocks:** Build phase

### Checkpoint 2 — Implementation Complete
- **Gate:** All devs posted `[DONE]`, reviewer has reviewed all tasks
- **Action:** Codex re-launches devs as cross-testers
- **Unblocks:** Cross-test phase

### Checkpoint 3 — Cross-Test Complete
- **Gate:** All cross-testers posted `[CROSS_TEST_PASS]`, all sign-offs complete
- **Action:** Reviewer writes final summary. Codex sends feedback prompts to Architect + PM
- **Unblocks:** Finalize phase

### Checkpoint 4 — Feedback Complete
- **Gate:** Architect + PM posted lessons-learned
- **Action:** Codex merges worktrees, runs full test suite, commits to branch
- **Unblocks:** Spindown

---

## 7. Role Lifecycle — Relaunch Model

| Role | Launches When | Deliverable | Spun Down After | Re-prompted? |
|------|--------------|-------------|-----------------|--------------|
| **Architect** | Phase 1 start | Plan MD, feedback, memory | Each `-p` prompt exits after deliverable | YES — multiple prompts across session via memory files |
| **PM** | After architect posts plan | Assignments, feedback, memory | Each `-p` prompt exits after deliverable | YES — multiple prompts across session via memory files |
| **Dev-N (build)** | Checkpoint 1 | Code + tests in worktree | Deliverable posted (`[DONE]`) | New `-p` call as cross-tester or patcher |
| **Dev-N (cross-test)** | After build reviewed | Cross-test results | Deliverable posted (`[CROSS_TEST_PASS/FAIL]`) | New `-p` call if re-verify needed |
| **Dev-N (patch)** | When cross-tester finds issues | Fix in worktree | Deliverable posted (`[FIX]`) | New `-p` call if fix rejected |
| **Code Reviewer** | After first dev `[DONE]` | `findings.md` | Deliverable delivered (findings.md complete) | No — single run, exits when done |
| **Live Watcher** | With reviewer | Actionable items for orchestrator | Phase 4 (workers spindown) | No — single run |

**Pattern: deliver then die.** Every role runs as a fresh `-p` call, produces its deliverable, and exits. Architect + PM are persistent ROLES, not persistent PROCESSES: continuity lives in memory files and shared root docs, not in open terminals.

**Exception: cross-test conversations.** When Dev-N and Dev-M are in a back-and-forth (cross-test thread), the orchestrator keeps re-launching them for each exchange round:
1. Dev-M posts `[CROSS_TEST_FAIL]` → orchestrator re-launches Dev-N with fix prompt
2. Dev-N posts `[FIX]` → orchestrator re-launches Dev-M to re-verify
3. Repeat until both sign off
Each round is a fresh `-p` call, but the orchestrator mediates the conversation rapidly. Devs communicate through their shared Cross-Test Thread section in the plan MD.

**Spindown order (explicit):**
1. Phase 4 step 2: Kill devs, cross-testers, live watcher; confirm their recorded PIDs are gone before cleanup
2. Phase 4 step 5: Let Reviewer finish `findings.md`, then kill Reviewer
3. Phase 5: No worker process remains alive while Codex merges, tests, commits
4. Post-Phase 5: Codex re-launches Architect + PM for memory-write prompts if needed
5. Session end: Verify no orchestration process remains running and no worktree shell/tab is still attached

**Arch + PM persist through files, not tabs.** Their memory files and the shared run docs are the durable context between prompts.

**Orchestrator (Codex) decision: when to re-launch a dev:**
- Dev posts `[DONE]` → orchestrator waits for reviewer `[REVIEW_PASS]` → then re-launches dev as cross-tester
- Cross-tester posts `[CROSS_TEST_FAIL]` → orchestrator re-launches original dev with patch prompt
- Dev posts `[FIX]` → orchestrator re-launches cross-tester to verify
- This back-and-forth loop continues until both sign off

---

## 8. Lifecycle Phases

### Phase 1: PLAN (root branch, fresh relaunches)
1. Codex launches Architect in root → `architect_stream.jsonl`
2. Architect produces plan MD with task breakdown, then exits
3. Codex launches PM in root → `pm_stream.jsonl`
4. PM refines tasks, assigns devs, writes coordination table, then exits
5. Codex commits plan to feature branch
6. **Checkpoint 0 gate: plan exists, coordination table populated**

### Phase 2: BUILD (worktrees + root for reviewer)
1. Codex creates worktrees (1 per dev) from feature branch
2. Codex generates per-dev prompts (keep small: 1 role, 1 task ID, 3-5 files, 1 test command)
3. Codex runs bootstrap prompt for each dev (ACK only)
4. **Checkpoint 1 gate: all ACKs received**
5. Codex launches dev execution prompts in parallel → `dev_N_stream.jsonl`
6. After the first dev posts `[DONE]`, Codex launches Reviewer in root (`Read,Edit,Bash`) → `reviewer_stream.jsonl`
7. Codex launches the live watcher alongside Reviewer
8. Codex watches ALL streams via `tail -f`
9. Reviewer reads dev streams, runs `git diff` / `cat` on worktree files, and writes findings to the shared ROOT plan/finding docs via absolute path
10. Codex can intervene: kill + relaunch any dev with corrected prompt

### Phase 3: CROSS-TEST (worktrees, code read-only)
1. **Checkpoint 2 gate: all devs [DONE], reviewer has reviewed**
2. Codex re-launches each dev as cross-tester (`Read,Edit,Bash`)
3. Cross-test matrix from config (Dev-1→tests Dev-2, Dev-2→tests Dev-1, etc.)
4. Testers run tests in target worktree, post results inline in the shared ROOT plan MD
5. If `[CROSS_TEST_FAIL]`: original dev re-launched to fix → re-tested
6. Loop until author + cross-tester both sign off per task

### Phase 4: SPINDOWN WORKERS + FEEDBACK (root branch — re-prompt Architect + PM)
1. **Checkpoint 3 gate: all sign-offs complete**
2. **Codex kills ALL worker processes** — devs, cross-testers, live watcher — and verifies their PIDs are gone
3. Reviewer remains only long enough to complete the final summary
4. Reviewer writes final summary to `findings.md` (includes test output, gaps, non-sprint issues — see 11.4)
5. **Codex kills Reviewer** after findings.md is complete
6. **Codex notifies Architect + PM:** "Reviewer findings are ready at `orchestration_run/findings.md`. Review now."
7. Codex re-launches Architect: read findings.md, post architecture lessons-learned, flag systemic issues, update roadmap view
8. Codex re-launches PM: read findings.md, refine process notes, update backlog with non-sprint issues, update roadmap view
9. **Checkpoint 4 gate: both feedback posted**

### Phase 4.5: ROADMAP + NEXT-SPRINT PREP (on-demand relaunches)
1. After feedback posted, Codex sends **roadmap prompt** to Architect:
   - Re-read `00_admin/todos.md` (Now/Next/Backlog) + reviewer's non-sprint issues
   - Draft architecture notes for NEXT sprint's likely work
   - Flag any upcoming tasks that need design-first treatment
   - Post to `orchestration_run/architect_memory.md` under `## Next Sprint Prep`
2. Codex sends **roadmap prompt** to PM:
   - Re-read `00_admin/todos.md` + reviewer's cross-cutting issues
   - Prioritize backlog items, draft rough task breakdown for next sprint
   - Identify dependencies or blockers for upcoming work
   - Post to `orchestration_run/pm_memory.md` under `## Next Sprint Prep`
3. This step is **optional but recommended** — orchestrator can skip if session needs to close quickly

**Key principle:** Arch + PM are cheap to re-launch — use memory files and shared docs to resume them at any point during Phases 4-6.

### Phase 5: FINALIZE (Codex only unless a feedback re-prompt is needed)
1. Codex merges all worktrees to feature branch (NOT main)
2. Codex runs full test suite from merged branch
3. Codex commits with structured message referencing all tasks
4. Codex cleans up worktrees only after the teardown checklist passes
5. Codex archives `orchestration_run/` logs

### Phase 5.5: INTER-PHASE CLEANUP (orchestrator responsibility)

After each orchestration run completes (Phase 5 finalize), orchestrator cleans up:

**Delete (not gitignore):**
- Dev worktrees: `git worktree remove .worktrees/dev_N` only after:
  - recorded dev/cross-test PIDs are no longer running
  - no terminal or shell still has its cwd inside the worktree
  - the worktree branch is merged and the worktree is clean
  - Codex has captured any needed diff/test output
- Stream logs: `orchestration_run/logs/*.jsonl` (ephemeral, not needed after merge)
- Optionally delete merged dev branches after worktree removal: `git branch -d dev_N/<feature>`

**Keep (committed to branch):**
- `orchestration_run/plan.md` — the executed plan (historical record)
- `orchestration_run/coordination.md` — task table and checkpoints
- `orchestration_run/findings.md` — reviewer findings (input for next session)
- `orchestration_run/architect_memory.md` — carried forward by next architect
- `orchestration_run/pm_memory.md` — carried forward by next PM

**Phase-to-phase pattern:**
When starting a NEW orchestration run (next sprint/phase):
1. Orchestrator archives previous run: `mv orchestration_run/ orchestration_run_YYYY-MM-DD/`
2. Orchestrator creates fresh `orchestration_run/` from templates
3. Arch + PM rehydrate on PREVIOUS run's memory files (from archived folder)
4. Previous plan/findings become read-only reference, not active files

**Gitignore recommendations (add to `.gitignore`):**
```
# Ephemeral orchestration artifacts
orchestration_run/logs/*.jsonl
.worktrees/
```

### Phase 6: SESSION MEMORY (final prompts to Arch + PM)
1. Codex sends **memory-write prompt** to Architect:
   - Write architecture decisions to `00_admin/insights.md` (Active Decisions section)
   - Log session summary to `00_admin/run_log.md`
   - Update `00_admin/context.md` if project direction changed
   - Optionally write to role-specific memory: `orchestration_run/architect_memory.md`
2. Codex sends **memory-write prompt** to PM:
   - Update `00_admin/todos.md` with new backlog items (from reviewer's non-sprint issues)
   - Log session summary to `00_admin/run_log.md`
   - Optionally write to role-specific memory: `orchestration_run/pm_memory.md`
3. **Checkpoint 5 gate: memory files updated**
4. Codex verifies no orchestration process remains running
5. **All terminals now down — session complete**

---

## 9. Codex Playbook (Summary)

The full `playbook.md` will contain copy-paste launch commands for each step.

### Prompt Construction Rules (from Codex playbook)

Keep role prompts small and concrete:
- 1 role line
- 1 task ID
- 3-5 owned files max
- 1 test command
- 1 required status update format

Avoid in prompts:
- Broad repo exploration requests
- Cross-task ownership
- Long procedural prose
- Asking agents to "poll" or "wait forever"

### Monitoring Checklist (Codex watches)

During run:
1. `tail -f orchestration_run/logs/*_stream.jsonl` — real-time stream activity
2. `tail -f orchestration_run/findings.md` — reviewer findings as they're written
3. `ps` — verify processes exist
4. `git status --short` in each worktree — track file changes
5. Check the ROOT shared plan MD and coordination MD for new inline updates/status

**Live watch prompt for reviewer steering:**
Codex launches a separate read-only watcher (the live watch prompt pattern) that:
- Monitors the reviewer's findings MD as it's written
- Monitors the plan MD for status changes
- Can only Read + run `git status --short`
- Returns actionable items (e.g., "top 5 commit-readiness actions") with exact file paths
- Codex uses this output to decide whether to intervene with devs

```bash
# Live watch — Codex steers from this
claude -p --verbose --model haiku --effort low \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat /tmp/live_watch_prompt.txt)" > orchestration_run/logs/live_watch_stream.jsonl 2>&1
```

This creates the feedback loop: Reviewer writes findings → Codex sees them live → Codex steers devs.

If stalled:
1. Kill stale process
2. Relaunch with shorter scoped prompt
3. Preserve existing edits in worktree

### Decision Points

| Signal | Codex Action |
|--------|-------------|
| Architect stream idle, plan MD exists | Launch PM |
| PM stream idle, tasks assigned | **WAIT — do NOT launch workers until plan is committed to branch** → Checkpoint 0 |
| Checkpoint 0 passed | Create worktrees → bootstrap devs |
| All dev ACKs received | Checkpoint 1 → launch execution prompts |
| First dev posts `[DONE]` | Launch reviewer + live watcher |
| Reviewer flags critical issue in stream | Kill affected dev, relaunch with fix instructions |
| All devs `[DONE]` + reviewer reviewed | Checkpoint 2 → relaunch devs as cross-testers |
| Cross-tester flags `[CROSS_TEST_FAIL]` | **Orchestrator handles:** relaunch original dev to fix → wait for fix → relaunch cross-tester to verify → repeat until `[CROSS_TEST_PASS]` |
| All sign-offs complete | Checkpoint 3 → **kill all workers** (devs, watcher) → reviewer writes findings → **kill reviewer** → re-launch feedback prompts to arch+PM |
| Arch+PM posted lessons | Checkpoint 4 → merge → test → commit → cleanup |
| Merge + tests pass, commit done | Phase 6 → send memory-write prompts to arch+PM |
| Memory files updated | Checkpoint 5 → verify no orchestration process remains → session complete |

### Anti-Patterns (from Codex playbook + additions)

- Spinning devs before plan is locked and committed
- Launching reviewer before any dev artifacts exist
- Asking agents to wait/poll in a `-p` run
- Huge prompts mixing planning + implementation + review
- Overwriting another agent's section in plan MD
- Committing to main instead of feature branch
- Skipping cross-test phase
- Proceeding past a checkpoint without all gates met

---

## 10. Config Defaults

```yaml
# config.md
num_devs: 2
architect_model: opus
architect_effort: high
pm_model: sonnet
pm_effort: medium
dev_default_model: sonnet
dev_default_effort: medium
dev_simple_model: haiku
dev_simple_effort: low
dev_complex_model: opus
dev_complex_effort: high
reviewer_default_model: sonnet
reviewer_default_effort: medium
reviewer_deep_model: opus
reviewer_deep_effort: high
crosstester_default_model: haiku
crosstester_default_effort: low
crosstester_escalation_model: sonnet
crosstester_escalation_effort: medium
watcher_model: haiku
watcher_effort: low
ui_tester_model: sonnet
ui_tester_effort: low
bootstrap_model: haiku
bootstrap_effort: low
escalation_model: opus
escalation_effort: high
branch: feature/<name>
worktree_root: .worktrees/
log_dir: orchestration_run/logs/
shared_run_dir: orchestration_run/
commit_target: branch  # never main
use_streaming_for_all_roles: true
steer_before_escalate: true

# Tool restrictions per role
dev_tools: Read,Write,Edit,Bash,Grep,Glob
reviewer_tools: Read,Edit,Bash
crosstester_tools: Read,Edit,Bash
architect_tools: Read,Write,Edit,Bash,Grep,Glob
pm_tools: Read,Write,Edit,Bash,Grep,Glob

# Reviewer bash allowlist
reviewer_bash_allowlist:
  - git status --short
  - git diff
  - git log --oneline -20
  - python -m pytest

# Cross-test matrix (auto-generated for N devs)
# For 2 devs: Dev-1 ↔ Dev-2
# For 3 devs: Dev-1→Dev-2, Dev-2→Dev-3, Dev-3→Dev-1
# For N devs: Dev-K tests Dev-((K % N) + 1)
cross_test_strategy: round_robin
```

---

## 11. Role Knowledge — Self-Contained Role Prompts

**Key design decision:** Each role `.md` is **self-contained**. It includes everything the agent needs and explicitly tells it to ignore conflicting instructions from AGENTS.md / CLAUDE.md (rehydration, compaction, rollover, etc.) that don't apply to single-shot `-p` sessions.

**Why:** Claude `-p` sessions in the repo auto-read AGENTS.md and CLAUDE.md. Those files contain rehydration contracts, compaction triggers, and rollover rules meant for interactive sessions — not for orchestrated workers. If a dev agent follows compaction rules mid-task, it'll break. The role prompt must override this.

**Every role prompt starts with:**
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
- In orchestrated runs, follow `.claude/orchestration/*` instead of the interactive chat-polling loop from `agent_coordination_protocol.md`
```

**Orchestrator references role files explicitly:**
```bash
claude -p ... "$(cat .claude/orchestration/roles/dev.md)

TASK ASSIGNMENT:
$(cat /tmp/dev_N_task.txt)" > orchestration_run/logs/dev_N_stream.jsonl 2>&1
```

### 11.1 Architect Prompt Should Include

- **Session memory rehydration:** Read `orchestration_run/architect_memory.md` if it exists — this carries forward architecture decisions and lessons from prior sessions
- **App context rehydration:** Read `00_admin/context.md` (direction), `00_admin/insights.md` (active decisions), `00_admin/todos.md` (full roadmap)
- **Strategic ownership:** You own the overall app architecture, technical roadmap, and scope — decisions you make here carry forward
- **Engineering principles reminder:** Reuse before create, modular/single-responsibility, user-configurable over hardcoded (from AGENTS.md)
- **Known reusable components:** DataTable.js, ConditionBuilder.js, CsdmTableRegistry, condition_query_builder.py, integration_properties pattern
- **Known refactor debt:** Current items from AGENTS.md so they don't create more
- **Task decomposition rules:** Each task must be independently implementable, have max 3-5 owned files, include a single test command, and list explicit done criteria
- **Output format:** Must produce a plan MD matching `project_plan_template.md`
- **Constraint:** Design for N parallel devs in worktrees — tasks cannot share files

### 11.2 Project Manager Prompt Should Include

- **Session memory rehydration:** Read `orchestration_run/pm_memory.md` if it exists — carries forward process notes, backlog items, and delivery insights from prior sessions
- **App context rehydration:** Read `00_admin/todos.md` (full roadmap — Now/Next/Backlog), `00_admin/context.md` (direction), `00_admin/insights.md` (active decisions)
- **Strategic ownership:** You own the sprint scope, delivery plan, and backlog — items flagged by reviewer as non-sprint issues go into Backlog
- **Acceptance criteria format:** Each task needs measurable done criteria (test count, exit codes, specific behaviors)
- **Cross-test matrix:** Assign which dev tests which other dev's work
- **Conflict ownership:** Explicitly assign file ownership per task (from Codex pattern)
- **Coordination table:** Must produce task assignment table with Owner/Status/Depends On/Notes columns
- **Checkpoint definitions:** Define gate conditions for each phase transition

### 11.3 Dev Prompt Should Include

- **Owned files list:** Explicit, max 3-5 files — touch nothing else
- **Test command:** Single command to verify their work
- **Done criteria:** From PM's acceptance criteria
- **Communication rules:** Post updates only to the shared ROOT `orchestration_run/plan.md` via absolute path; never edit a worktree-local copy of shared docs
- **Engineering principles:** Reuse existing components (list them), use properties system for config values
- **TDD reminder:** Write tests first or alongside implementation

### 11.4 Code Reviewer Prompt Should Include

- **File allowlist:** Explicit list of files they can read
- **Edit allowlist:** ONLY Reviewer Findings sections in the shared ROOT `orchestration_run/plan.md` and `orchestration_run/findings.md`
- **Bash allowlist:** Explicit list of commands they can run
- **Review checklist:** Spec compliance, test coverage, no hardcoded config, reuse of existing components, transaction safety, scope isolation
- **Output format:** Exact file path + 1-line reason per finding, structured tags
- **Word/finding limits:** Keep concise (e.g., top 5 findings per task, under 140 words per review)

**Findings must include (in findings.md final summary):**

```markdown
## Findings Summary — [Date]

### Per-Task Reviews
#### Task N: [Title]
- **Code quality issues:** [list with file:line]
- **Test output:** [paste test run summary — pass/fail count, failing test names]
- **Test gaps:** [what's NOT tested — edge cases, error paths, integration scenarios]
- **Spec compliance:** [does implementation match PM's done criteria? gaps?]

### Cross-Cutting Issues
- **Issues beyond this sprint:** [tech debt discovered, pre-existing bugs touched, patterns that need refactoring]
- **Architecture concerns:** [for Architect feedback — design issues, coupling, scalability risks]
- **Process notes:** [for PM feedback — unclear specs, missing acceptance criteria, coordination gaps]

### Test Summary
- **Total tests run:** [N passed / M failed / K skipped]
- **New tests added:** [count per task]
- **Coverage gaps:** [areas with no test coverage that should have it]
```

This structured format ensures Architect and PM receive actionable feedback when they're re-prompted in Phase 4.

### 11.5 UI Tester (Optional Role)

**Purpose:** Automated visual/functional testing via Chrome MCP commands. Verifies that UI changes render correctly and are interactive.

**Launch:**
```bash
claude -p --verbose --model sonnet --effort low \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat /tmp/ui_tester_prompt.txt)" > orchestration_run/logs/ui_tester_stream.jsonl 2>&1
```

**Tools:** Read + Bash (uses Chrome MCP via the Claude in Chrome extension)
**Chrome MCP capabilities available:**
- `screenshot` — capture current page state
- `read_page` — accessibility tree of all elements
- `find` — locate elements by natural language ("login button", "data table")
- `navigate` — go to URL
- `left_click` / `form_input` — interact with elements
- `get_page_text` — extract rendered text content
- `read_console_messages` — check for JS errors
- `read_network_requests` — verify API calls

**UI Tester prompt should include:**
- URL to test (localhost + port from dev server)
- List of pages/flows to verify
- Expected elements per page (table with N rows, button labeled X, etc.)
- Screenshot comparison notes (before/after if applicable)
- Console error tolerance (zero errors expected, or known warnings to ignore)

**When to use:** After dev completes UI-facing work, before cross-test phase. Optional role — only spin up when the project involves frontend changes.

---

## 12. Orchestrator Instructions (for Codex / codex.md)

These instructions go in the orchestrator's context (codex.md or equivalent). The orchestrator is the outermost agent — it launches and manages all other roles.

```markdown
# Orchestrator Instructions

You are the **Orchestrator**. You manage the full lifecycle of an AI development team.

## Your Identity
- You launch, monitor, steer, and spin down all team roles
- You are the ONLY agent that commits to the branch
- You are the ONLY agent that creates/destroys worktrees
- You do NOT write code — you coordinate agents that do

## Rehydration (On Session Start)
Before launching any agents, read:
- Previous run memory: `orchestration_run_YYYY-MM-DD/architect_memory.md`, `pm_memory.md` (if prior run exists)
- Admin context: `00_admin/context.md`, `00_admin/todos.md`, `00_admin/insights.md`
- Previous findings: `orchestration_run_YYYY-MM-DD/findings.md` (if prior run exists)
This gives you the full project state before spinning up the team.

## Lifecycle Rules
1. NEVER launch devs or reviewer before architect + PM are done and plan is committed
2. ALWAYS create worktrees AFTER plan is committed to branch
3. ALWAYS bootstrap devs (ACK prompt) before sending execution prompts
4. ALWAYS launch reviewer only after the first dev posts `[DONE]`; launch the live watcher alongside reviewer
5. ALWAYS notify architect + PM when reviewer findings.md is ready — they review it
6. ALWAYS send feedback prompts to architect + PM AFTER reviewer posts findings
7. NEVER commit to main — only to feature branch
8. ALWAYS run full test suite before final commit
9. USE arch + PM idle time productively — send roadmap/planning prompts between phases
10. ALWAYS verify worker PIDs are gone and worktree shells/tabs are detached before `git worktree remove`
11. ALWAYS stream substantive launches to `.jsonl` logs so you can steer from live output
12. ALWAYS steer with a tighter prompt before escalating model or reasoning
13. ALWAYS spin down ALL orchestration processes after finalize phase

## Orchestrator as Event Loop (No Polling by Agents)

**You are the ONLY thing that polls.** Agents NEVER poll, wait, or check for updates — that wastes credits. Instead:
- YOU watch streams and files (`tail -f`)
- YOU decide when an agent has something to do
- YOU send the prompt/nudge to the agent at the right moment
- Agents do their work, post output, and stop

**Nudge pattern for relaunch-based strategic roles (Arch + PM):**
- These agents are re-prompted (new `-p` call with context) when their turn comes
- Between prompts they are IDLE — no running process, zero credit cost
- Orchestrator triggers them: "Reviewer findings ready → prompt Architect", "Cross-test done → prompt PM"

**Nudge pattern for workers (Devs, Reviewer):**
- Workers are launched fresh each time (new `-p` call)
- Orchestrator decides when to launch based on checkpoint gates
- Workers do their task, post status, exit
- Orchestrator monitors exit and decides next action

**Key: Never include "wait for X" or "poll for Y" in any agent prompt.** If an agent needs to react to something, the orchestrator watches for that event and re-launches the agent with the new context.

## Monitoring Loop (Orchestrator Only)
- Watch all streams via `tail -f orchestration_run/logs/*_stream.jsonl`
- Watch reviewer findings via `tail -f orchestration_run/findings.md`
- Check process health via `ps aux | grep claude`
- Check worktree changes via `git -C .worktrees/dev_N status --short`
- Check the shared ROOT docs, not worktree-local copies, for orchestration status and sign-offs

## Intervention Rules
- If reviewer flags CRITICAL issue → first tighten the dev prompt with exact files/repro/acceptance criteria; escalate model/effort only if the streamed retry still misses
- If dev is stalled (no stream output for 5+ min) → kill → relaunch with narrower prompt
- If cross-test fails → relaunch original dev to fix → relaunch cross-tester after fix
- If checkpoint gate not met → do NOT proceed to next phase

## Steering via Live Watch
- Launch the live watch prompt to monitor reviewer findings in real-time
- Use watch output to decide when to intervene
- Watch prompt returns structured actions (file path + reason)
- Act on watch output immediately — don't wait for reviewer to finish
```

---

## 13. Claude CLI Command Reference (for Orchestrator)

### Launch Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `claude -p "prompt"` | Single-shot non-interactive | Tiny one-off nudges or local dry-runs when stream capture is unnecessary |
| `claude -p --output-format stream-json --include-partial-messages "prompt" > file.jsonl 2>&1` | Streamed with log capture | Architect, PM, dev execution, reviewer, cross-tester, live watch, feedback, memory writes |
| `claude -p --tools Read,Edit,Bash "prompt"` | Restricted toolset with doc-write access | Reviewer, cross-tester |
| `claude -p --tools Read,Bash "prompt"` | Restricted read-only toolset | UI tester, live watch |
| `claude -p --model haiku --effort low "prompt"` | Cheapest tier | ACKs, watcher, exact reruns, simple cross-tests |
| `claude -p --model sonnet --effort medium "prompt"` | Balanced default | PM, most dev work, standard review |
| `claude -p --model opus --effort high "prompt"` | Highest reasoning | Architect, risky implementation, deep review, escalations |

### Common Flags

| Flag | Purpose | Always Use? |
|------|---------|-------------|
| `--verbose` | Show tool calls in output | Yes — needed for stream observability |
| `--model opus` | Best model for complex work | Architect always; other roles only when the task or stream quality warrants it |
| `--model sonnet` | Balanced default | PM, most dev work, standard review |
| `--model haiku` | Cheapest fast tier | ACKs, watcher, exact checklist reruns |
| `--effort high` | Maximum reasoning | Architect always; escalations for risky work |
| `--effort medium` | Normal reasoning | Default for most non-architect work |
| `--effort low` | Cheapest reasoning | Deterministic/repetitive prompts |
| `--dangerously-skip-permissions` | No permission prompts | Yes — agents run unattended |
| `--disable-slash-commands` | Prevent slash command injection | Yes — agents shouldn't use slash commands |
| `--output-format stream-json` | JSON stream output | When you need to capture or watch the stream |
| `--include-partial-messages` | Include in-progress tokens | Pair with stream-json for real-time visibility |
| `--tools Read,Bash` | Restrict available tools | For fully read-only roles (UI tester, live watch) |

### Monitoring Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `tail -f orchestration_run/logs/dev_N_stream.jsonl` | Watch a dev's stream live | During build phase |
| `tail -f orchestration_run/logs/reviewer_stream.jsonl` | Watch reviewer in real-time | During review phase |
| `tail -f orchestration_run/findings.md` | Watch findings as they're written | Continuous during build+review |
| `ps aux \| grep claude` | Check which agents are alive | Periodic health check |
| `git -C .worktrees/dev_N status --short` | Check dev worktree changes | After stream goes quiet |
| `git -C .worktrees/dev_N diff --stat` | Summary of what dev changed | Before merge phase |
| `wc -l orchestration_run/logs/*.jsonl` | Stream size per agent | Detect stalled agents (no growth) |
| `lsof +D .worktrees/dev_N` | Check no shell/process is still attached to a worktree | Before removal |

### Worktree Management

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `git worktree add .worktrees/dev_N -b dev_N/<feature> <feature-branch>` | Create dev worktree | After plan committed (Checkpoint 0) |
| `git worktree list` | See all active worktrees | Health check |
| `git worktree remove .worktrees/dev_N` | Clean up after merge | Finalize phase, after PID/attachment checks pass |
| `git branch -d dev_N/<feature>` | Delete merged dev branch | After worktree removal |

### Process Management

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `kill PID` | Stop a stalled or misbehaving agent | When intervention needed |
| `kill -9 PID` | Force kill unresponsive agent | Last resort |
| `pkill -f "claude.*dev_N"` | Kill by prompt pattern | When PID unknown |
| `ps -p <pid>` | Verify a recorded orchestration PID is gone | Before worktree cleanup |

### Merge and Commit

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `git diff --stat <feature-branch>...dev_N/<feature>` | See all dev changes vs the feature branch | Before merge |
| `git merge dev_N/<feature>` | Merge worktree branch | Finalize phase, after all sign-offs |
| `python -m pytest tests/ -v` | Full regression suite | After merge, before commit |
| `git add -A && git commit -m "message"` | Commit merged work | After tests pass |

---

## 14. What This System Does NOT Do

- **Does not replace Codex** — Codex is the outer orchestrator; this provides prompts, protocols, and templates
- **Does not push to main** — only commits to feature branch
- **Does not auto-merge on failure** — all sign-offs required before merge
- **Does not use worktree-local copies of shared run docs** — plan/coordination/findings live only in ROOT `orchestration_run/`
- **Does not give reviewer code write access** — reviewer can edit only designated shared review sections
- **Does not require open Architect/PM tabs between prompts** — continuity is file-based, not process-based
- **Does not launch devs before plan is locked** — Checkpoint 0 must pass first
