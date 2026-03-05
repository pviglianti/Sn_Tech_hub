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
