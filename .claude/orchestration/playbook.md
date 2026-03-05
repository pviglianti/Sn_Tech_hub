# Orchestrator Playbook — Step-by-Step

This is your copy-paste reference. Follow phases in order. Do NOT skip checkpoints.

## Key Principles

1. **Arch launches first at full power.** Architect always uses `opus` + `--effort high`.
2. **Nothing else spins up until the plan drops** (Checkpoint 0).
3. **You are the event loop.** Agents never poll — you watch streams and nudge them.
4. **Every launch should be streamable.** Default to `stream-json` logs for Architect, PM, devs, reviewer, watcher/scribe snapshots, cross-testers, feedback, and memory writes.
5. **Deliver then die.** Workers produce output and exit. Architect + PM persist through memory files and shared docs, not open tabs.
6. **Live watcher is snapshot-based.** Each watcher run is one-shot; orchestrator re-launches snapshots on triggers.
7. **Steer before you escalate.** Since the run is streamed, tighten the prompt first. Raise model/effort only when the stream shows the current tier is not enough.
8. **Arch + PM own memory.** They absorb reviewer findings, refactor their memory files to stay compact, and carry context forward. Before planning the next round, they account for all issues/findings from previous phases.
9. **Memory hygiene:** Instruct Arch + PM to continuously consolidate their memory — remove duplicates, merge similar items, keep it under ~200 lines. All key points must survive but the file must not bloat.
10. **Flexible Arch/PM usage:** Between phases, you can repurpose Architect for code review, testing assistance, or stepping in to help. They are your most capable agents — use them.
11. **Record launch decisions.** For every backgrounded role, record the chosen model, effort, PID, and log file in `orchestration_run/coordination.md` before moving on.
12. **Monitor loop is mandatory during Build/Cross-Test.** Run a persistent orchestrator heartbeat loop and treat stale heartbeat as a process failure.
13. **Orchestrator leaves an audit trail.** Course corrections, gate misses, and model/reasoning escalations are written to `orchestration_run/coordination.md`, not `findings.md`.
14. **Technical course corrections need ratification.** If orchestrator changes task boundaries, scope, or tiering assumptions, log it and trigger an Architect heartbeat snapshot.

## Model / Effort Triage

Use the cheapest tier that is likely to succeed, except Architect which is fixed at the top tier.

| Tier | Use For | Default Model / Effort | Notes |
|------|---------|------------------------|-------|
| Tier A | ACK/bootstrap, watcher/scribe snapshots, exact checklist reruns, simple cross-tests | `haiku` / low | Use when the task is tightly prescribed and failure is easy to spot in-stream |
| Tier B | PM formatting/refinement, most dev tasks, reviewer passes, UI checks | `sonnet` / medium | Default starting point for non-architect work |
| Tier C | Architect, ambiguous dev work, risky refactors, migrations, security/transaction/perf review, repeated misses | `opus` / high | Use when architecture or deep reasoning matters |

Escalation rules:
- First weak run: keep the same model, narrow the prompt, add exact files/repro/acceptance criteria.
- If the stream still shows drift: raise effort or move up one tier.
- For narrow but high-stakes work, `opus` + `medium` is a valid middle ground when model quality matters more than maximum reasoning depth.
- If reviewer/cross-test gives an exact repro and file path, the relaunch can often be cheaper than the original implementation run.

---

## Pre-Flight

```bash
# 1. Detect project
PROJECT_ROOT=$(git rev-parse --show-toplevel)
cd "$PROJECT_ROOT"

# 2. Read prior session memory (if exists)
cat orchestration_run_*/architect_memory.md 2>/dev/null
cat orchestration_run_*/pm_memory.md 2>/dev/null
cat orchestration_run_*/findings.md 2>/dev/null

# 3. Read admin context
cat servicenow_global_tech_assessment_mcp/00_admin/context.md
cat servicenow_global_tech_assessment_mcp/00_admin/todos.md
cat servicenow_global_tech_assessment_mcp/00_admin/insights.md

# 4. Create fresh run directory from templates
mkdir -p orchestration_run/logs
cp .claude/orchestration/templates/project_plan_template.md orchestration_run/plan.md
cp .claude/orchestration/templates/coordination_template.md orchestration_run/coordination.md
cp .claude/orchestration/templates/findings_template.md orchestration_run/findings.md
rm -f orchestration_run/.stop_monitor_loop

# 5. Create feature branch
git checkout -b feature/<name>

# 6. Set team size once per run (must match plan + coordination)
NUM_DEVS=2

# 7. Monitor policy
MONITOR_POLL_SECONDS=30
MONITOR_STALL_SECONDS=300
```

---

## Phase 1: PLAN (root branch — streamed relaunches)

### Step 1: Launch Architect

Streamed (recommended — you want live visibility from the start):

```bash
claude -p --verbose --model opus --effort high \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/architect.md)

SPRINT GOAL:
<paste sprint goal or feature request here>

Produce plan at $PROJECT_ROOT/orchestration_run/plan.md" \
  > orchestration_run/logs/architect_stream.jsonl 2>&1 &
```

**Wait for:** Plan MD appears at `orchestration_run/plan.md` with task breakdown.

### Step 2: Launch PM

Streamed (same relaunch pattern as every other role):

```bash
claude -p --verbose --model sonnet --effort medium \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/project_manager.md)

Architect plan is at $PROJECT_ROOT/orchestration_run/plan.md. Refine tasks, assign devs, write coordination table." \
  > orchestration_run/logs/pm_stream.jsonl 2>&1 &
```

**Wait for:** Coordination table at `orchestration_run/coordination.md` with assignments, acceptance criteria, cross-test matrix.

### Step 3: Commit plan to branch

```bash
git add orchestration_run/plan.md orchestration_run/coordination.md
git commit -m "orchestration: lock plan for $(date +%Y-%m-%d)"
```

### CHECKPOINT 0 — Plan Locked
- [ ] `orchestration_run/plan.md` exists with task breakdown
- [ ] `orchestration_run/coordination.md` exists with assignments
- [ ] No file ownership overlaps between tasks
- [ ] Plan committed to feature branch

**→ DO NOT proceed until all gates pass.**

---

## Phase 2: BUILD (worktrees + root for reviewer)

### Step 4: Create worktrees (1 per dev)

```bash
# For each dev (works for 2, 3, ... N)
for dev in $(seq 1 "$NUM_DEVS"); do
  git worktree add ".worktrees/dev_${dev}" -b "dev_${dev}/feature" feature/<name>
done
```

### Step 5: Bootstrap devs (ACK — fast, cheap)

Use `haiku` for bootstrap unless the ACK prompt itself proves too brittle:

```bash
for dev in $(seq 1 "$NUM_DEVS"); do
  claude -p --verbose --model haiku --effort low \
    --dangerously-skip-permissions --disable-slash-commands \
    --output-format stream-json --include-partial-messages \
    "Role: Dev-${dev}. Read plan at $PROJECT_ROOT/orchestration_run/plan.md. Read your task (Task ${dev}). Post [ACK] to your Dev-${dev} Notes section there. Exit." \
    > "orchestration_run/logs/dev_${dev}_bootstrap.jsonl" 2>&1
done
```

**Wait for:** `[ACK]` in each dev's notes section.

### CHECKPOINT 1 — Bootstrap ACK Complete
- [ ] All worktrees created
- [ ] All dev ACKs received

Run the hard gate script before launching Step 6:

```bash
# Usage: require_bootstrap_ack.sh <plan_path> <expected_dev_count>
$PROJECT_ROOT/.claude/orchestration/scripts/require_bootstrap_ack.sh \
  "$PROJECT_ROOT/orchestration_run/plan.md" \
  "$NUM_DEVS"
```

If the script exits non-zero, do NOT launch execution prompts yet.

### Step 6: Launch dev execution prompts (streamed, parallel)

Streamed with log capture — these run in parallel:

```bash
# Pick the lowest tier likely to succeed per task.
# Typical starting points:
# - simple/prescribed task: haiku + low or sonnet + medium
# - standard implementation: sonnet + medium
# - ambiguous/risky task: opus + high
# IMPORTANT: define model/effort for every Dev-1..Dev-N and launch every dev.
# Skipping one dev launch means that task never starts.
DEV_1_MODEL=sonnet
DEV_1_EFFORT=medium
DEV_2_MODEL=opus
DEV_2_EFFORT=high
# DEV_3_MODEL=sonnet
# DEV_3_EFFORT=medium

for dev in $(seq 1 "$NUM_DEVS"); do
  model_var="DEV_${dev}_MODEL"
  effort_var="DEV_${dev}_EFFORT"
  model="${!model_var:-sonnet}"
  effort="${!effort_var:-medium}"

  (
    cd "$PROJECT_ROOT/.worktrees/dev_${dev}"
    claude -p --verbose --model "$model" --effort "$effort" \
      --dangerously-skip-permissions --disable-slash-commands \
      --output-format stream-json --include-partial-messages \
      "$(cat $PROJECT_ROOT/.claude/orchestration/roles/dev.md)

TASK ASSIGNMENT:
Task: ${dev}
Files owned: [list from plan for Task ${dev}]
Test command: [from plan]
Done criteria: [from plan]
Plan location: $PROJECT_ROOT/orchestration_run/plan.md
Worktree: $PROJECT_ROOT/.worktrees/dev_${dev}" \
      > "$PROJECT_ROOT/orchestration_run/logs/dev_${dev}_stream.jsonl" 2>&1
  ) &
  eval "DEV_${dev}_PID=$!"
done

# Record model/effort/PID/log choices in orchestration_run/coordination.md
```

### Step 7: Launch Reviewer (streamed, after first `[DONE]`)

Wait until the first dev posts `[DONE]` in the shared plan, then choose the reviewer tier:
- default review pass: `sonnet` + `medium`
- deep/risky review or repeated misses: `opus` + `high`

```bash
REVIEWER_MODEL=sonnet
REVIEWER_EFFORT=medium
WORKTREE_LIST=$(printf ".worktrees/dev_%s, " $(seq 1 "$NUM_DEVS") | sed 's/, $//')

cd "$PROJECT_ROOT" && \
claude -p --verbose --model "$REVIEWER_MODEL" --effort "$REVIEWER_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Edit,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/code_reviewer.md)

WORKTREES: $WORKTREE_LIST
PLAN: $PROJECT_ROOT/orchestration_run/plan.md
FINDINGS OUTPUT: $PROJECT_ROOT/orchestration_run/findings.md" \
  > orchestration_run/logs/reviewer_stream.jsonl 2>&1 &
REVIEWER_PID=$!
```

### Step 8: Launch Watcher Snapshot (streamed, read-only, one-shot)

Use the same trigger as reviewer launch (after first `[DONE]`).
This run is a snapshot and exits. Re-launch on triggers in Step 9.

```bash
WATCHER_MODEL=haiku
WATCHER_EFFORT=low
WATCH_TS=$(date +%Y%m%d_%H%M%S)

claude -p --verbose --model "$WATCHER_MODEL" --effort "$WATCHER_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Bash \
  --output-format stream-json --include-partial-messages \
  "You are a read-only watcher. Monitor:
- orchestration_run/findings.md (reviewer findings as written)
- orchestration_run/plan.md (status changes)
Return top 5 commit-readiness actions with exact file paths.
Do NOT wait or poll. Exit after posting one snapshot.
Only run: git status --short, git diff --stat in worktrees." \
  > "orchestration_run/logs/live_watch_${WATCH_TS}.jsonl" 2>&1 &
WATCHER_PID=$!
```

### Step 8b: Launch Scribe Snapshot (optional, one-shot)

Use when the run has 3+ devs, long duration, or frequent handoffs.

```bash
SCRIBE_ENABLED=${SCRIBE_ENABLED:-false}
if [[ "$SCRIBE_ENABLED" == "true" ]]; then
  SCRIBE_MODEL=haiku
  SCRIBE_EFFORT=low
  SCRIBE_TS=$(date +%Y%m%d_%H%M%S)

  claude -p --verbose --model "$SCRIBE_MODEL" --effort "$SCRIBE_EFFORT" \
    --dangerously-skip-permissions --disable-slash-commands \
    --tools Read,Edit,Bash \
    --output-format stream-json --include-partial-messages \
    "$(cat .claude/orchestration/roles/scribe.md)" \
    > "orchestration_run/logs/scribe_${SCRIBE_TS}.jsonl" 2>&1 &
  SCRIBE_PID=$!
fi
```

### Step 9: Monitor (orchestrator polling loop)

```bash
# Start persistent monitor loop (mandatory during Build/Cross-Test)
MONITOR_LOOP_SCRIPT="$PROJECT_ROOT/.claude/orchestration/scripts/orchestrator_monitor_loop.sh"
"$MONITOR_LOOP_SCRIPT" \
  "$PROJECT_ROOT" \
  "$NUM_DEVS" \
  "$MONITOR_POLL_SECONDS" \
  "$MONITOR_STALL_SECONDS" \
  > "$PROJECT_ROOT/orchestration_run/logs/orchestrator_monitor_stream.log" 2>&1 &
MONITOR_PID=$!

# Watch all streams
tail -f orchestration_run/logs/*_stream.jsonl &

# Watch findings
tail -f orchestration_run/findings.md &

# Watch orchestrator heartbeat
tail -f orchestration_run/logs/orchestrator_heartbeat.log &

# Check process health
ps aux | grep claude

# Check worktree changes
for dev in $(seq 1 "$NUM_DEVS"); do
  git -C ".worktrees/dev_${dev}" status --short
done
```

Watcher re-launch policy (snapshot runs):
- Relaunch after first `[DONE]` (if not already run)
- Relaunch when reviewer updates `findings.md`
- Relaunch when stall is suspected (no stream growth, no status updates)
- Relaunch every 10 minutes while dev execution is active

Architect heartbeat triggers (one-shot snapshots):
- First reviewer finding
- First critical finding
- Dependency unblock
- Repeated dev miss after prompt tightening
- Before merge
- Before memory write

PM heartbeat triggers (one-shot snapshots):
- First `[DONE]`
- Missed gate or handoff
- Stalled task
- Cross-test fail
- Phase transition

First `[DONE]` response gate (time-boxed to 2 minutes):
- Launch reviewer (if not already running)
- Launch watcher snapshot
- Launch optional scribe snapshot (if enabled)
- Launch PM heartbeat snapshot
- If any tester is idle, launch a rolling cross-test lane immediately (do NOT wait for all devs)
- Verify `orchestration_run/logs/orchestrator_heartbeat.log` received a fresh heartbeat within 2x poll interval

**Intervention triggers:**
- Reviewer flags CRITICAL → tighten the dev prompt first; escalate model/effort only if the stream still shows misses
- Dev stalled 5+ min → kill → relaunch with narrower prompt
- Stream size not growing → check `wc -l orchestration_run/logs/*.jsonl`
- Crosstester posts `[CROSS_TEST_BLOCKED]` → relaunch crosstester from correct target worktree/branch
- Heartbeat stale (no new heartbeat for >2x poll interval) → restart monitor loop immediately, then re-check active launches

Every orchestrator intervention is appended to `coordination.md` under `## Orchestrator Intervention Log`:
- `[COURSE_CORRECT]` for prompt/flow correction
- `[MODEL_ESCALATION]` for tier/model/effort changes
- `[GATE_MISS]` for late launches or missed handoffs
- `[ARCH_RATIFY_REQUIRED]` when a technical correction needs Architect confirmation

Guardrail:
- During Build phase, do not do unrelated housekeeping updates (for example todo journaling). Stay on monitoring, gating, nudges, and checkpoint progression.

### Step 9b: Rolling Cross-Test + Patch Loop (while build is still active)

When some devs are done and at least one dev is still implementing, start validation early:

1. Task posts `[DONE]` and reviewer has begun coverage for that task
2. Pick an idle tester from the matrix
3. Launch crosstester in the target dev's worktree immediately
4. If `[CROSS_TEST_FAIL]`, relaunch original dev for fix immediately
5. Relaunch crosstester for re-verify

This runs in parallel with remaining implementation work and reduces end-of-phase pileups.

### Step 9c: Launch Heartbeat Snapshots (one-shot, orchestrator-triggered)

Do not keep Architect or PM open as polling agents. Re-launch only the snapshot whose trigger fired.

```bash
# PM heartbeat snapshot (launch when a PM trigger fires)
PM_HB_MODEL=sonnet
PM_HB_EFFORT=low
PM_HB_TS=$(date +%Y%m%d_%H%M%S)

claude -p --verbose --model "$PM_HB_MODEL" --effort "$PM_HB_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Edit,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/pm_heartbeat.md)" \
  > "orchestration_run/logs/pm_heartbeat_${PM_HB_TS}.jsonl" 2>&1 &

# Architect heartbeat snapshot (launch when an Architect trigger fires)
ARCH_HB_MODEL=opus
ARCH_HB_EFFORT=medium
ARCH_HB_TS=$(date +%Y%m%d_%H%M%S)

claude -p --verbose --model "$ARCH_HB_MODEL" --effort "$ARCH_HB_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Edit,Bash \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/architect_heartbeat.md)" \
  > "orchestration_run/logs/architect_heartbeat_${ARCH_HB_TS}.jsonl" 2>&1 &
```

### CHECKPOINT 1.5 — First `[DONE]` Response
- [ ] Reviewer launched within 2 minutes of first `[DONE]`
- [ ] Watcher snapshot launched within 2 minutes of first `[DONE]`
- [ ] Rolling cross-test lane launched when tester is idle
- [ ] Monitor heartbeat active (fresh line within 2x poll interval)

### CHECKPOINT 2 — Implementation Complete
- [ ] All devs posted `[DONE]` with passing tests
- [ ] Reviewer reviewed ALL tasks

---

## Phase 3: CROSS-TEST (worktrees, code read-only)

### Step 10: Launch Remaining Cross-Tests (if not already closed in rolling loop)

Streamed, code read-only (`Read,Edit,Bash` so the tester can append only to the shared thread):
Use one launch per tester→target pair from the round-robin matrix (examples below show a 2-dev pair).

```bash
# If rolling cross-test already closed a task, skip launching that lane again.
# Simple checklist reruns can start at haiku + low.
# If the test requires diagnosis, multi-step reasoning, or ambiguous validation, move to sonnet + medium or higher.
CROSSTEST_1_MODEL=haiku
CROSSTEST_1_EFFORT=low
CROSSTEST_2_MODEL=sonnet
CROSSTEST_2_EFFORT=medium
WORKTREE_GATE_SCRIPT="$PROJECT_ROOT/.claude/orchestration/scripts/require_worktree_context.sh"

# Dev-1 tests Dev-2's work
TARGET_DEV=2
TARGET_WORKTREE="$PROJECT_ROOT/.worktrees/dev_${TARGET_DEV}"
(
  cd "$TARGET_WORKTREE"
  "$WORKTREE_GATE_SCRIPT" "$TARGET_WORKTREE" "dev_${TARGET_DEV}/"
  claude -p --verbose --model "$CROSSTEST_1_MODEL" --effort "$CROSSTEST_1_EFFORT" \
    --dangerously-skip-permissions --disable-slash-commands \
    --tools Read,Edit,Bash \
    --output-format stream-json --include-partial-messages \
    "$(cat $PROJECT_ROOT/.claude/orchestration/roles/dev_crosstester.md)

CROSS-TEST ASSIGNMENT:
You are Dev-1. Test Dev-2's Task 2.
Worktree: .worktrees/dev_2
Test command: [from plan]
Verify: [acceptance criteria from plan]
Post results to Cross-Test Thread for Task 2 in $PROJECT_ROOT/orchestration_run/plan.md" \
    > "$PROJECT_ROOT/orchestration_run/logs/dev_1_crosstest.jsonl" 2>&1
) &
CROSSTEST_1_PID=$!

# Dev-2 tests Dev-1's work
TARGET_DEV=1
TARGET_WORKTREE="$PROJECT_ROOT/.worktrees/dev_${TARGET_DEV}"
(
  cd "$TARGET_WORKTREE"
  "$WORKTREE_GATE_SCRIPT" "$TARGET_WORKTREE" "dev_${TARGET_DEV}/"
  claude -p --verbose --model "$CROSSTEST_2_MODEL" --effort "$CROSSTEST_2_EFFORT" \
    --dangerously-skip-permissions --disable-slash-commands \
    --tools Read,Edit,Bash \
    --output-format stream-json --include-partial-messages \
    "$(cat $PROJECT_ROOT/.claude/orchestration/roles/dev_crosstester.md)

CROSS-TEST ASSIGNMENT:
You are Dev-2. Test Dev-1's Task 1.
Worktree: .worktrees/dev_1
Test command: [from plan]
Verify: [acceptance criteria from plan]
Post results to Cross-Test Thread for Task 1 in $PROJECT_ROOT/orchestration_run/plan.md" \
    > "$PROJECT_ROOT/orchestration_run/logs/dev_2_crosstest.jsonl" 2>&1
) &
CROSSTEST_2_PID=$!
```

### Step 11: Handle cross-test failures (if any)

If `[CROSS_TEST_FAIL]` posted:

```bash
# Use the exact repro from the cross-test thread. Keep the model low if the fix is tightly bounded;
# escalate only when the streamed retry still misses.
FIX_MODEL=sonnet
FIX_EFFORT=medium
VERIFY_MODEL=haiku
VERIFY_EFFORT=low
WORKTREE_GATE_SCRIPT="$PROJECT_ROOT/.claude/orchestration/scripts/require_worktree_context.sh"
TARGET_DEV=N  # replace N with the actual task owner number

# Re-launch original dev to fix (full tools, in their worktree)
cd ".worktrees/dev_${TARGET_DEV}" && \
claude -p --verbose --model "$FIX_MODEL" --effort "$FIX_EFFORT" \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat $PROJECT_ROOT/.claude/orchestration/roles/dev.md)

FIX REQUEST:
Cross-tester found issues in your Task ${TARGET_DEV}. Read the Cross-Test Thread in $PROJECT_ROOT/orchestration_run/plan.md.
Fix the issues, re-run tests, post [FIX] to your Dev-${TARGET_DEV} Notes section." \
  > "$PROJECT_ROOT/orchestration_run/logs/dev_${TARGET_DEV}_fix.jsonl" 2>&1

# After fix posted, re-launch cross-tester to verify
TARGET_WORKTREE="$PROJECT_ROOT/.worktrees/dev_${TARGET_DEV}"
(
  cd "$TARGET_WORKTREE"
  "$WORKTREE_GATE_SCRIPT" "$TARGET_WORKTREE" "dev_${TARGET_DEV}/"
  claude -p --verbose --model "$VERIFY_MODEL" --effort "$VERIFY_EFFORT" \
    --dangerously-skip-permissions --disable-slash-commands \
    --tools Read,Edit,Bash \
    --output-format stream-json --include-partial-messages \
    "Dev-${TARGET_DEV} posted [FIX]. Re-verify in .worktrees/dev_${TARGET_DEV}. Post [CROSS_TEST_PASS], [CROSS_TEST_FAIL], or [CROSS_TEST_BLOCKED] to the shared Cross-Test Thread in $PROJECT_ROOT/orchestration_run/plan.md." \
    > "$PROJECT_ROOT/orchestration_run/logs/dev_${TARGET_DEV}_reverify.jsonl" 2>&1
)
```

Repeat until both sign off.

### CHECKPOINT 3 — Cross-Test Complete
- [ ] All cross-testers posted `[CROSS_TEST_PASS]`
- [ ] All sign-offs complete (author + cross-tester + reviewer per task)

---

## Phase 4: FEEDBACK (root branch — re-prompt Arch + PM)

### Step 12: Kill workers

```bash
# Prefer recorded PIDs from orchestration_run/coordination.md or your current shell.
touch orchestration_run/.stop_monitor_loop
for dev in $(seq 1 "$NUM_DEVS"); do
  eval "kill \${DEV_${dev}_PID:-} 2>/dev/null || true"
done
for pid_var in $(compgen -A variable | grep '^CROSSTEST_.*_PID$' || true); do
  kill "${!pid_var:-}" 2>/dev/null || true
done
kill "${WATCHER_PID:-}" "${SCRIBE_PID:-}" "${MONITOR_PID:-}" 2>/dev/null || true

# Fallback only if a PID was not recorded:
pkill -f "claude.*dev_"
pkill -f "claude.*live_watch"
pkill -f "claude.*scribe"
pkill -f "orchestrator_monitor_loop.sh"
```

### Step 13: Wait for reviewer to finish findings.md

```bash
# Reviewer should be writing final summary
tail -f orchestration_run/findings.md
# Wait until reviewer exits (check ps)
```

### Step 14: Kill reviewer

```bash
pkill -f "claude.*reviewer"
```

### Step 15: Notify Arch + PM — findings ready

Re-launch Architect (streamed):

```bash
claude -p --verbose --model opus --effort high \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/architect_feedback.md)

Reviewer findings are ready at $PROJECT_ROOT/orchestration_run/findings.md. Review now." \
  > orchestration_run/logs/architect_feedback_stream.jsonl 2>&1 &
```

Re-prompt PM:

```bash
claude -p --verbose --model sonnet --effort medium \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "$(cat .claude/orchestration/roles/pm_feedback.md)

Reviewer findings are ready at $PROJECT_ROOT/orchestration_run/findings.md. Review now." \
  > orchestration_run/logs/pm_feedback_stream.jsonl 2>&1 &
```

### CHECKPOINT 4 — Feedback Complete
- [ ] Architect posted feedback/lessons-learned
- [ ] PM posted process notes and backlog updates

---

## Phase 4.5: FLEXIBLE ARCH+PM USAGE (idle time is productive time)

Arch + PM are cheap to re-launch. Choose one or more options:

### Option A: Roadmap / Next-Sprint Prep

```bash
# Architect preps next sprint
claude -p --verbose --model opus --effort high \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "You are the Architect. Re-read servicenow_global_tech_assessment_mcp/00_admin/todos.md (Next/Backlog).
Draft architecture notes for next sprint's likely work.
Flag items needing design-first. Post to orchestration_run/architect_memory.md under ## Next Sprint Prep.
IMPORTANT: After writing, re-read your memory file. Remove duplicates, merge similar items, keep under ~200 lines."
  > orchestration_run/logs/architect_roadmap_stream.jsonl 2>&1

# PM preps next sprint
claude -p --verbose --model sonnet --effort medium \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "You are the PM. Re-read servicenow_global_tech_assessment_mcp/00_admin/todos.md + reviewer cross-cutting issues.
Prioritize backlog, draft rough task breakdown for next sprint.
Post to orchestration_run/pm_memory.md under ## Next Sprint Prep.
IMPORTANT: After writing, re-read your memory file. Remove duplicates, merge similar items, keep under ~200 lines."
  > orchestration_run/logs/pm_roadmap_stream.jsonl 2>&1
```

### Option B: Repurpose Architect for Senior Review

```bash
claude -p --verbose --model opus --effort high \
  --dangerously-skip-permissions --disable-slash-commands \
  --tools Read,Bash \
  --output-format stream-json --include-partial-messages \
  "You are the Architect, temporarily acting as senior code reviewer.
Review merged code for architectural consistency.
Focus on: coupling, patterns, scalability, tech debt introduced.
Post findings to orchestration_run/plan.md under ## Architect Feedback."
  > orchestration_run/logs/architect_senior_review_stream.jsonl 2>&1
```

### Option C: Ask the Human

Orchestrator asks: "Arch + PM are idle. Prep next sprint, do a deep review, or wait for findings?"

---

## Phase 5: FINALIZE

### Step 16: Merge worktrees

```bash
# Merge each dev's worktree branch
for dev in $(seq 1 "$NUM_DEVS"); do
  git merge "dev_${dev}/feature" --no-edit
done
```

### Step 17: Run full test suite

```bash
# Adjust command for your project
python -m pytest tests/ -v
# or: npm test
# or: go test ./...
```

**If tests fail:** Debug, fix, re-run. Do NOT commit until green.

### Step 18: Commit

```bash
git add -A
git commit -m "feat: [sprint name] — tasks 1-N implemented

Tasks:
- Task 1: [title]
- Task 2: [title]

All tests passing. Cross-tested and reviewed."
```

### Step 19: Clean up worktrees

```bash
# Verify no orchestration PID is still alive and no shell/tab is attached
ps -p <dev_1_pid>
ps -p <dev_2_pid>
lsof +D .worktrees/dev_1
lsof +D .worktrees/dev_2

git worktree remove .worktrees/dev_1
git worktree remove .worktrees/dev_2
git branch -d dev_1/feature
git branch -d dev_2/feature
```

---

## Phase 5.5: CLEANUP

```bash
# Delete ephemeral logs
rm -f orchestration_run/logs/*.jsonl

# Keep: plan.md, coordination.md, findings.md, *_memory.md
```

---

## Phase 6: SESSION MEMORY

### Step 20: Architect memory write

```bash
claude -p --verbose --model opus --effort high \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "You are the Architect. Write session memory:
1. Architecture decisions → servicenow_global_tech_assessment_mcp/00_admin/insights.md (Active Decisions section)
2. Session summary → servicenow_global_tech_assessment_mcp/00_admin/run_log.md (append)
3. Update servicenow_global_tech_assessment_mcp/00_admin/context.md if direction changed
4. Write role memory → orchestration_run/architect_memory.md" \
  > orchestration_run/logs/architect_memory_stream.jsonl 2>&1
```

### Step 21: PM memory write

```bash
claude -p --verbose --model sonnet --effort medium \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "You are the PM. Write session memory:
1. New backlog items → servicenow_global_tech_assessment_mcp/00_admin/todos.md (Backlog section)
2. Session summary → servicenow_global_tech_assessment_mcp/00_admin/run_log.md (append)
3. Write role memory → orchestration_run/pm_memory.md" \
  > orchestration_run/logs/pm_memory_stream.jsonl 2>&1
```

### Step 21b: Architect final synthesis digest

Architect reconciles technical memory after PM writes process memory. PM remains source-of-truth for process/backlog meaning.

```bash
claude -p --verbose --model opus --effort medium \
  --dangerously-skip-permissions --disable-slash-commands \
  --output-format stream-json --include-partial-messages \
  "You are the Architect. Read:
1. orchestration_run/architect_memory.md
2. orchestration_run/pm_memory.md
3. orchestration_run/findings.md
4. orchestration_run/coordination.md

Write a short deduped technical digest to orchestration_run/architect_digest.md.
Include only:
- durable technical decisions
- design debt worth carrying forward
- architectural implications for next sprint

Do NOT rewrite PM's operational meaning. Keep under ~120 lines." \
  > orchestration_run/logs/architect_digest_stream.jsonl 2>&1
```

### CHECKPOINT 5 — Session Memory Written
- [ ] `orchestration_run/architect_memory.md` exists
- [ ] `orchestration_run/pm_memory.md` exists
- [ ] `orchestration_run/architect_digest.md` exists
- [ ] Admin files updated

### Step 22: Verify all orchestration processes are down

All agents done. Session complete.

```bash
ps aux | grep claude
# Archive this run for next session
# mv orchestration_run/ orchestration_run_$(date +%Y-%m-%d)/
```

---

## Quick Reference — Launch Commands

| Role | Model | Stream? | Tools | Worktree? |
|------|-------|---------|-------|-----------|
| Architect | opus | Yes (`.jsonl`) | Full | Root branch |
| PM | sonnet | Yes (`.jsonl`) | Full | Root branch |
| Dev bootstrap | haiku | Yes (`.jsonl`) | Full | Root branch |
| Dev execution | task-dependent: haiku/sonnet/opus | Yes (`.jsonl`) | Full | `.worktrees/dev_N` |
| Code Reviewer | task-dependent: sonnet/opus | Yes (`.jsonl`) | Read,Edit,Bash | Root branch |
| Architect Heartbeat | opus | Yes (`.jsonl`) | Read,Edit,Bash | Root branch |
| PM Heartbeat | sonnet | Yes (`.jsonl`) | Read,Edit,Bash | Root branch |
| Cross-tester | task-dependent: haiku/sonnet/opus | Yes (`.jsonl`) | Read,Edit,Bash | Root branch (reads worktree) |
| Live Watcher | haiku | Yes (`.jsonl`) | Read,Bash | Root branch |
| Feedback (Arch) | opus | Yes (`.jsonl`) | Full | Root branch |
| Feedback (PM) | sonnet | Yes (`.jsonl`) | Full | Root branch |
| Memory write | task-dependent: opus/sonnet | Yes (`.jsonl`) | Full | Root branch |
| Architect Digest | opus | Yes (`.jsonl`) | Full | Root branch |

Record the chosen model, effort, PID, and log path for each launch in `orchestration_run/coordination.md`.

## Quick Reference — Monitoring

```bash
tail -f orchestration_run/logs/*_stream.jsonl   # all streams
tail -f orchestration_run/findings.md            # reviewer findings
ps aux | grep claude                             # process health
git -C .worktrees/dev_N status --short          # worktree changes
wc -l orchestration_run/logs/*.jsonl            # detect stalls
```
