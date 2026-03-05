# Orchestration Config

> Copy this to `orchestration_run/config_instance.md` and fill in project-specific values before each run.

## Team

```yaml
num_devs: 2
cross_test_strategy: round_robin  # Dev-K tests Dev-((K % N) + 1)
```

## Models

```yaml
architect_model: opus
architect_effort: high  # always highest reasoning for architecture work

# Default starting points for non-architect roles.
# Codex can override per task and escalate mid-run.
pm_model: sonnet
pm_effort: medium

architect_heartbeat_model: opus
architect_heartbeat_effort: medium
architect_heartbeat_mode: one_shot
architect_heartbeat_triggers:
  - first_reviewer_finding
  - critical_finding
  - dependency_unblock
  - repeated_dev_miss
  - before_merge
  - before_memory_write

pm_heartbeat_model: sonnet
pm_heartbeat_effort: low
pm_heartbeat_mode: one_shot
pm_heartbeat_triggers:
  - first_done
  - gate_miss
  - stalled_task
  - cross_test_fail
  - phase_transition

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
watcher_mode: one_shot
watcher_snapshot_interval_minutes: 10
watcher_relaunch_triggers:
  - first_done
  - findings_updated
  - suspected_stall

monitor_loop_script: .claude/orchestration/scripts/orchestrator_monitor_loop.sh
monitor_poll_seconds: 30
monitor_stall_seconds: 300
monitor_heartbeat_log: orchestration_run/logs/orchestrator_heartbeat.log

scribe_enabled_default: false
scribe_model: haiku
scribe_effort: low
scribe_mode: one_shot
scribe_snapshot_interval_minutes: 15
scribe_relaunch_triggers:
  - first_done
  - checkpoint_change

cross_test_start_policy: rolling_when_tester_idle
cross_test_target_context_required: true
worktree_context_gate_script: .claude/orchestration/scripts/require_worktree_context.sh
ui_tester_model: sonnet
ui_tester_effort: low
bootstrap_model: haiku
bootstrap_effort: low
bootstrap_ack_gate_script: .claude/orchestration/scripts/require_bootstrap_ack.sh

escalation_model: opus
escalation_effort: high

architect_reconciliation_owner: technical
pm_reconciliation_owner: delivery_process
architect_final_digest_file: orchestration_run/architect_digest.md
```

## Paths

```yaml
branch: feature/<name>
worktree_root: .worktrees/
log_dir: orchestration_run/logs/
run_dir: orchestration_run/
shared_run_dir: orchestration_run/
admin_dir: servicenow_global_tech_assessment_mcp/00_admin
```

## Tool Restrictions Per Role

```yaml
architect_tools: Read,Write,Edit,Bash,Grep,Glob
pm_tools: Read,Write,Edit,Bash,Grep,Glob
dev_tools: Read,Write,Edit,Bash,Grep,Glob
reviewer_tools: Read,Edit,Bash
crosstester_tools: Read,Edit,Bash
ui_tester_tools: Read,Bash
```

## Reviewer Bash Allowlist

```yaml
reviewer_bash_allowlist:
  - git status --short
  - git diff
  - git log --oneline -20
  - python -m pytest
  - npm test
```

## Common CLI Flags

```yaml
always_flags: --verbose --dangerously-skip-permissions --disable-slash-commands
stream_flags: --output-format stream-json --include-partial-messages
```

## Cost / Escalation Policy

```yaml
use_streaming_for_all_roles: true
steer_before_escalate: true

# Tier guidance:
# - deterministic / ACK / watcher / exact checklist rerun -> haiku + low
# - prescribed implementation / PM formatting / reviewer pass -> sonnet + medium
# - ambiguous architecture / risky refactor / repeated miss -> opus + high
# - narrow but sensitive fix / exact but high-stakes change -> opus + medium is a valid override
#
# Architect is the hard exception: always opus + high.
```
