# Orchestration Config Instance — SN API Centralization

> Sprint: SN API Centralization (Audit Sections 5, 6, 10)

## Team

```yaml
num_devs: 3
cross_test_strategy: round_robin  # Dev-K tests Dev-((K % N) + 1)
```

## Sprint Goal

Implement SN API centralization from the audit document (Sections 5, 6, 10):
1. Consolidate scan_executor.py custom batch iterator + since filter → use sn_client shared infrastructure
2. Replace sn_dictionary.py 3 direct HTTP bypasses → use get_records()
3. Fix inclusive/exclusive >= vs > inconsistency across all callers
4. Add DESC ordering support to _iterate_batches() + all pull methods
5. Add upsert change detection (return bool for data changed)
6. Add dual-signal bail-out logic in data_pull_executor
7. Add new Integration Properties for bail-out control
8. Add new InstanceDataPull columns for comprehensive logging

## Models

```yaml
architect_model: opus
architect_effort: high

pm_model: sonnet
pm_effort: medium

dev_default_model: sonnet
dev_default_effort: medium

reviewer_default_model: sonnet
reviewer_default_effort: medium

watcher_model: haiku
watcher_effort: low
```

## Paths

```yaml
branch: feature/sn-api-centralization
worktree_root: .worktrees/
log_dir: orchestration_run/logs/
run_dir: orchestration_run/
shared_run_dir: orchestration_run/
admin_dir: servicenow_global_tech_assessment_mcp/00_admin
audit_doc: tech-assessment-hub/docs/plans/2026-03-05-sn-api-centralization-audit.md
```

## Tool Restrictions Per Role

```yaml
architect_tools: Read,Write,Edit,Bash,Grep,Glob
pm_tools: Read,Write,Edit,Bash,Grep,Glob
dev_tools: Read,Write,Edit,Bash,Grep,Glob
reviewer_tools: Read,Edit,Bash
crosstester_tools: Read,Edit,Bash
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
```
