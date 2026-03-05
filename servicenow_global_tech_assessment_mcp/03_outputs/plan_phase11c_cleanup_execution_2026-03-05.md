# Phase 11C — Legacy Cleanup Utility Execution Plan

Date: 2026-03-05
Author: PLANNER-11C
Status: LOCKED
Source: `phase11_legacy_cleanup_dryrun_report_2026-03-05.md`
Coordination: `00_admin/phase11c_cleanup_coordination.md`
Chat: `00_admin/phase11c_cleanup_chat.md`

---

## 0. Objective

Deliver `cleanup_legacy_feature_data` as an assessment-scoped CLI utility with `--dry-run` (default, read-only report) and `--apply` (destructive cleanup with safety gates). The utility addresses three data problems documented in the dry-run report:

1. **Duplicate scan_result artifacts** — 10,258 groups, 14,374 excess rows in ASMT0000001.
2. **Non-customized feature memberships** — 25,000 legacy FSR rows linking non-customized results.
3. **Empty/orphan features** — 127 pure-legacy features with zero customized members post-cleanup.

---

## 1. Architecture

### File Layout

```
tech-assessment-hub/
  src/
    scripts/
      cleanup_legacy_feature_data.py    # [W1] Core utility module
    services/
      legacy_cleanup_service.py         # [W1] Reusable service layer
  cli.py (or __main__.py entrypoint)    # [W2] CLI wrapper + reporting
  tests/
    test_legacy_cleanup_service.py      # [W3] Unit tests for service
    test_cleanup_legacy_cli.py          # [W3] Integration/CLI tests
```

### Execution Flow

```
CLI (W2)
  |
  v
legacy_cleanup_service.py (W1)
  |-- Step 0: Pre-flight safety checks
  |-- Step 1: Deduplicate scan_result artifacts
  |-- Step 2: Remove non-customized FSR rows
  |-- Step 3: Delete empty/orphan features
  |-- Step 4: Summary report
  |
  v
stdout / JSON report (W2)
```

---

## 2. Worker Assignments

### WORKER-1: Cleanup Utility Core Implementation

**Owner:** Codex Worker 1
**Task ID:** C1
**Depends on:** C0 (this plan)

#### Files Owned

| File | Action |
|------|--------|
| `tech-assessment-hub/src/services/legacy_cleanup_service.py` | CREATE |

#### Specification

Implement `LegacyCleanupService` class with these methods:

```python
class LegacyCleanupService:
    def __init__(self, session: Session, assessment_id: str, dry_run: bool = True): ...
    def run(self) -> CleanupReport: ...
    # Internal steps:
    def _preflight_checks(self) -> PreflightResult: ...
    def _deduplicate_scan_results(self) -> DedupResult: ...
    def _remove_non_customized_memberships(self) -> MembershipResult: ...
    def _delete_empty_features(self) -> FeatureResult: ...
```

**Key requirements:**

1. **Pre-flight checks (`_preflight_checks`):**
   - Verify assessment exists and is not in an active pipeline stage (only `scans` or `complete` allowed).
   - Count human-authored FSR rows (`assignment_source = 'human'`). If > 0, **abort with error** (zero-loss guarantee).
   - Return counts for: total scan_results, duplicate groups, non-customized FSRs, features, customized features.

2. **Deduplication (`_deduplicate_scan_results`):**
   - For each `(assessment_id, table_name, sys_id)` group with count > 1:
     - Select canonical row: richest `origin_type` (`modified_ootb=3 > net_new_customer=2 > unknown_no_history=1 > NULL=0`), then highest `scan_id`, then lowest `sr.id`.
     - Re-point FSR rows from non-canonical `scan_result_id` to canonical `scan_result_id`.
     - Re-point customization child rows similarly (if applicable).
     - Delete non-canonical `scan_result` rows.
   - In `--dry-run`: compute and return counts only, no mutations.
   - In `--apply`: execute within a single transaction; rollback on any error.

3. **Non-customized membership removal (`_remove_non_customized_memberships`):**
   - Delete FSR rows where:
     - `scan_result.origin_type NOT IN ('modified_ootb', 'net_new_customer') OR origin_type IS NULL`
     - `fsr.assignment_source IS NULL OR assignment_source NOT IN ('human')`
   - Scoped to `feature.assessment_id = :assessment_id`.
   - In `--dry-run`: return count only.

4. **Empty feature deletion (`_delete_empty_features`):**
   - After membership removal, delete features with zero remaining FSR rows.
   - Scoped to `feature.assessment_id = :assessment_id`.
   - In `--dry-run`: return count only.

5. **Transaction safety:**
   - All `--apply` mutations in a single DB transaction.
   - On any exception: full rollback, return error in `CleanupReport`.
   - `--dry-run` must NEVER call `session.commit()` or `session.flush()` with pending changes.

6. **Result dataclasses:**

```python
@dataclass
class PreflightResult:
    assessment_exists: bool
    pipeline_stage: str
    safe_to_proceed: bool
    human_fsr_count: int
    total_scan_results: int
    duplicate_groups: int
    excess_rows: int
    non_customized_fsrs: int
    total_features: int
    customized_features: int
    abort_reason: str | None

@dataclass
class DedupResult:
    groups_processed: int
    rows_deleted: int
    fsrs_repointed: int
    customizations_repointed: int

@dataclass
class MembershipResult:
    fsrs_deleted: int

@dataclass
class FeatureResult:
    features_deleted: int

@dataclass
class CleanupReport:
    assessment_id: str
    dry_run: bool
    preflight: PreflightResult
    dedup: DedupResult | None
    membership: MembershipResult | None
    features: FeatureResult | None
    success: bool
    error: str | None
    elapsed_seconds: float
```

#### Test Command

```bash
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_legacy_cleanup_service.py -v
```

#### Done Criteria

- [ ] `LegacyCleanupService` passes all W3-written tests.
- [ ] `--dry-run` path makes zero DB mutations (verified by test assertion on session dirty state).
- [ ] `--apply` path runs in single transaction with rollback on error.
- [ ] Human FSR abort gate is unconditional (no override flag).
- [ ] Post in chat: `[W1] [DONE] — C1 complete, tests passing: <count>`.

---

### WORKER-2: CLI / Reporting / Docs

**Owner:** Codex Worker 2
**Task ID:** C2
**Depends on:** C0 (this plan)

#### Files Owned

| File | Action |
|------|--------|
| `tech-assessment-hub/src/scripts/cleanup_legacy_feature_data.py` | CREATE |

#### Specification

1. **CLI entrypoint** (`cleanup_legacy_feature_data.py`):
   - Invoked as: `python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001 [--apply] [--json]`
   - Default mode: `--dry-run` (report only).
   - `--apply`: requires interactive confirmation prompt (`Type 'YES' to confirm destructive cleanup:`). Bypass with `--yes` for automation.
   - `--json`: output `CleanupReport` as JSON instead of human-readable table.
   - `--assessment-id`: required, string.
   - Instantiates DB session using existing `get_session()` pattern from the app.
   - Calls `LegacyCleanupService(session, assessment_id, dry_run=not args.apply).run()`.

2. **Human-readable report format** (stdout, default):

```
=== Phase 11C Legacy Cleanup Report ===
Assessment: ASMT0000001 (weis inc)
Mode: DRY-RUN | APPLY
Pipeline Stage: scans

--- Pre-flight ---
Human memberships at risk:  0 (SAFE)
Total scan results:         29,300
Duplicate groups:           10,258
Excess duplicate rows:      14,374
Non-customized FSR rows:    25,000
Total features:             159
Features with custom members: 32

--- Deduplication ---
Groups processed:           10,258
Scan result rows removed:   14,374
FSR rows re-pointed:        14,374
Customization rows re-pointed: 0

--- Membership Cleanup ---
Non-customized FSRs removed: 25,000

--- Feature Cleanup ---
Empty features removed:     127

--- Summary ---
Status: SUCCESS
Elapsed: 2.3s
```

3. **Safety UX:**
   - If `--apply` without `--yes`, print the dry-run report first, then prompt for confirmation.
   - If pre-flight fails (human FSRs found, bad pipeline stage), print reason and exit code 1.
   - Exit codes: 0 = success, 1 = pre-flight failure, 2 = runtime error.

4. **Docs integration:**
   - Add a "Legacy Cleanup Utility" section to the dry-run report file (`phase11_legacy_cleanup_dryrun_report_2026-03-05.md`) as a new Section 8: "Running the Cleanup Utility" with CLI usage examples.

#### Test Command

```bash
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_cleanup_legacy_cli.py -v
```

#### Done Criteria

- [ ] CLI runs with `--dry-run` and `--apply` modes.
- [ ] `--apply` requires confirmation (or `--yes`).
- [ ] `--json` outputs valid JSON matching `CleanupReport`.
- [ ] Exit codes: 0/1/2 as specified.
- [ ] Section 8 added to dry-run report.
- [ ] Post in chat: `[W2] [DONE] — C2 complete, tests passing: <count>`.

---

### WORKER-3: Tests

**Owner:** Codex Worker 3
**Task ID:** C3
**Depends on:** C0 (this plan)

#### Files Owned

| File | Action |
|------|--------|
| `tech-assessment-hub/tests/test_legacy_cleanup_service.py` | CREATE |
| `tech-assessment-hub/tests/test_cleanup_legacy_cli.py` | CREATE |

#### Specification

**W3 writes tests FIRST (or in parallel with W1/W2). Tests define the contract.**

##### test_legacy_cleanup_service.py — Unit Tests

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_preflight_assessment_not_found` | Returns `safe_to_proceed=False` when assessment_id doesn't exist |
| 2 | `test_preflight_active_pipeline_blocks` | Returns `safe_to_proceed=False` when pipeline_stage not in (`scans`, `complete`) |
| 3 | `test_preflight_human_fsr_aborts` | Returns `safe_to_proceed=False, abort_reason` when human FSR count > 0 |
| 4 | `test_preflight_clean_assessment` | Returns correct counts for an assessment with known test data |
| 5 | `test_dryrun_no_mutations` | After `run()` with `dry_run=True`, session has no pending changes; row counts unchanged |
| 6 | `test_dedup_canonical_selection` | Given 3 copies with different origin_types, keeps `modified_ootb` copy |
| 7 | `test_dedup_scan_id_tiebreak` | Given 2 copies with same origin_type, keeps highest scan_id |
| 8 | `test_dedup_sr_id_tiebreak` | Given 2 copies with same origin_type and scan_id, keeps lowest sr.id |
| 9 | `test_dedup_repoints_fsr` | After dedup, FSR rows point to canonical scan_result_id |
| 10 | `test_dedup_repoints_customizations` | After dedup, customization child rows point to canonical scan_result_id |
| 11 | `test_remove_non_customized_memberships` | Deletes FSR rows with non-customized origin_type and non-human source |
| 12 | `test_preserves_customized_memberships` | FSR rows with `modified_ootb`/`net_new_customer` origin are kept |
| 13 | `test_preserves_human_authored_memberships` | FSR rows with `assignment_source='human'` are never deleted (but preflight aborts if present) |
| 14 | `test_delete_empty_features` | Features with zero FSR rows after cleanup are deleted |
| 15 | `test_preserves_features_with_members` | Features with remaining customized FSR rows survive |
| 16 | `test_apply_single_transaction_rollback` | Inject error mid-apply; verify full rollback (no partial state) |
| 17 | `test_full_cleanup_apply_end_to_end` | Seed realistic data matching dry-run report numbers (scaled down); verify final state matches expected |
| 18 | `test_report_dataclass_fields` | `CleanupReport` has all expected fields with correct types |
| 19 | `test_no_duplicates_no_op` | Clean assessment returns zero-action report |
| 20 | `test_assessment_scope_isolation` | Cleanup on assessment 1 does not affect assessment 2 data |

##### test_cleanup_legacy_cli.py — CLI Integration Tests

| # | Test Name | What It Verifies |
|---|-----------|-----------------|
| 1 | `test_cli_dryrun_default` | Running without `--apply` produces report, exit code 0, no mutations |
| 2 | `test_cli_apply_requires_confirmation` | `--apply` without `--yes` prompts for input; non-YES input exits cleanly |
| 3 | `test_cli_apply_with_yes_flag` | `--apply --yes` runs without prompting |
| 4 | `test_cli_json_output` | `--json` produces valid JSON parseable as CleanupReport |
| 5 | `test_cli_bad_assessment_exit_1` | Non-existent assessment_id exits with code 1 |
| 6 | `test_cli_missing_assessment_id` | Missing `--assessment-id` prints usage, exits with code 2 |

#### Test Commands

```bash
# Run W3's own tests against W1's service
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_legacy_cleanup_service.py -v

# Run W3's own tests against W2's CLI
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_cleanup_legacy_cli.py -v

# Combined
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_legacy_cleanup_service.py tech-assessment-hub/tests/test_cleanup_legacy_cli.py -v
```

#### Done Criteria

- [ ] All 20 service tests + 6 CLI tests written and discoverable by pytest.
- [ ] Tests use in-memory SQLite with seeded fixture data (no production DB dependency).
- [ ] Tests import from `src.services.legacy_cleanup_service` and `src.scripts.cleanup_legacy_feature_data`.
- [ ] At least `test_dryrun_no_mutations` and `test_apply_single_transaction_rollback` passing before W1 code is finalized.
- [ ] Post in chat: `[W3] [DONE] — C3 complete, test count: <count>, passing: <count>`.

---

### WORKER-4: Independent Review + Regression Verification

**Owner:** Claude Worker 4
**Task ID:** C4
**Depends on:** C1, C2, C3

#### Files Owned

None (read-only reviewer).

#### Review Checklist

| # | Check | Pass Criteria |
|---|-------|--------------|
| 1 | Read `legacy_cleanup_service.py` | Matches plan spec: 4 steps, dataclasses, transaction safety |
| 2 | Read `cleanup_legacy_feature_data.py` | CLI args, confirmation prompt, exit codes, JSON output |
| 3 | Read all tests | Coverage of all 20+6 cases, fixture quality, no production DB |
| 4 | Run service tests | `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_legacy_cleanup_service.py -v` — all green |
| 5 | Run CLI tests | `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_cleanup_legacy_cli.py -v` — all green |
| 6 | Run full regression | `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v` — no regressions from baseline (532+ passing) |
| 7 | Verify dry-run safety | Confirm `--dry-run` path has no `session.commit()`, `session.flush()`, or `session.execute(delete/update)` calls |
| 8 | Verify human FSR gate | Confirm abort is unconditional — no flag to bypass |
| 9 | Verify assessment scope | Confirm all queries filter by `assessment_id` — no cross-assessment side effects |
| 10 | Verify rollback | Confirm `--apply` wraps all mutations in try/except with rollback |

#### Test Commands

```bash
# Targeted
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_legacy_cleanup_service.py tech-assessment-hub/tests/test_cleanup_legacy_cli.py -v

# Full regression
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v
```

#### Done Criteria

- [ ] All 10 review checks passed (or feedback posted as `[REVIEW_FEEDBACK]`).
- [ ] Full regression green with no decrease from baseline.
- [ ] Post in chat: `[W4] [REVIEW_PASS]` or `[W4] [REVIEW_FEEDBACK] — <issues>`.

---

## 3. Merge Order and Conflict Ownership

| Step | Action | Conflict Owner |
|------|--------|---------------|
| 1 | W1 commits `legacy_cleanup_service.py` | W1 |
| 2 | W2 commits `cleanup_legacy_feature_data.py` + docs update | W2 |
| 3 | W3 commits both test files | W3 (resolves any import path drift from W1/W2) |
| 4 | W4 reviews all + runs regression | W4 flags issues back to W1/W2/W3 |
| 5 | Codex Lead merges into `codex/p11c-planner-20260305` branch | Codex Lead |

**Conflict resolution rules:**
- W1 owns all conflicts in `src/services/`.
- W2 owns all conflicts in `src/scripts/` and `03_outputs/`.
- W3 owns all conflicts in `tests/`.
- If W1 renames a dataclass/method, W3 adapts test imports within 1 cycle.

---

## 4. Safety and Rollback for --apply

### Pre-apply gates (all must pass)

1. Assessment must exist in DB.
2. `pipeline_stage` must be `scans` or `complete` (not mid-pipeline).
3. `human_fsr_count == 0` (unconditional abort — no override flag).
4. Interactive confirmation required (unless `--yes` flag for automation).

### Transaction model

- All mutations (`DELETE scan_result`, `DELETE feature_scan_result`, `UPDATE feature_scan_result.scan_result_id`, `DELETE feature`) occur in a **single SQLAlchemy transaction**.
- On **any** exception: `session.rollback()` is called, `CleanupReport.success = False`, error message captured.
- No partial state is possible.

### Recovery if --apply produces unexpected results

1. **DB backup before apply:** The CLI should print a warning: "Recommended: back up your database before running --apply." (W2 responsibility).
2. **Re-run dry-run after apply:** Running `--dry-run` after a successful `--apply` should show zero actions needed (idempotency verification).
3. **If rollback needed beyond transaction:** Restore from the DB backup. The utility does not maintain its own undo log.

### What --apply NEVER does

- Deletes scan_result rows for assessments other than the specified one.
- Deletes FSR rows with `assignment_source = 'human'`.
- Modifies `scan`, `assessment`, or `instance` tables.
- Runs without explicit opt-in (`--apply` flag required).

---

## 5. Definition of Done

### Per-worker

| Worker | Done When |
|--------|-----------|
| W1 | `LegacyCleanupService` passes all W3 service tests. Transaction safety verified. Chat status posted. |
| W2 | CLI runs both modes. Exit codes correct. JSON output valid. Docs section added. Chat status posted. |
| W3 | All 26 tests written, discoverable, and passing against W1+W2 code. Chat status posted. |
| W4 | All 10 review checks pass. Full regression green. `REVIEW_PASS` posted in chat. |

### Overall C5 (Codex Lead merge)

- [ ] All W1-W4 done criteria met.
- [ ] `phase11c_cleanup_chat.md` has `[REVIEW_PASS]` from W4.
- [ ] Full test suite green (532+ existing + 26 new = 558+ total).
- [ ] No files outside the owned set were modified without explicit coordination.
- [ ] Commit message: `phase11c: add legacy cleanup utility (dry-run + apply) with 26 tests`.
- [ ] Update `phase11c_cleanup_coordination.md` task table — all rows `complete`.
- [ ] Update `todos.md` — mark Phase 11C cleanup as complete.

---

## 6. Timing Expectations

| Phase | Target |
|-------|--------|
| C1 + C2 + C3 (parallel) | Single execution pass each |
| C4 (review) | Immediate after C1-C3 |
| C5 (merge) | Immediate after C4 REVIEW_PASS |

Workers start as soon as they read this plan. No waiting beyond C0 acknowledgment.
