# Phase 11 Worker Review Chat

[2026-03-05 22:18] [CODEX] [STATUS] — Started review wave for completed workers:
- Worker A (P11-2 integrity tranche)
- Worker B (T4 read-only grouping refactor)
- Worker C (P11-3 dry-run report)

Reviewers will post `REVIEW_PASS` / `REVIEW_FEEDBACK` here, then Codex will summarize in `phase11_chat.md` for Architect A sign-off.

---

[2026-03-05 22:22] [REVIEWER_D] [REVIEW_PASS] — Worker A (P11-2 integrity tranche)

**Scope reviewed:** All Worker A diffs vs `main` — focused on P11-2 integrity changes per checklist.

### 1. DB-Level Uniqueness & Migration Safety — PASS
- `models.py:685`: `UniqueConstraint("feature_id", "scan_result_id")` on `FeatureScanResult.__table_args__` — correct.
- `database.py:296-306`: Safe migration in `_ensure_indexes()` — checks for existing duplicates before creating index; uses `CREATE UNIQUE INDEX IF NOT EXISTS`; skips if `dup_count > 0`. This is the correct approach for existing databases with legacy duplicates (Track D will clean those).

### 2. Customized-Only Guards — PASS
Guards present on all four write paths:
- `feature_membership.py:52-58` (`handle_add`): validates `origin_type in _CUSTOMIZED_ORIGINS`.
- `feature_grouping.py:59` (`_get_customized_results`): filters to `origin_type.in_(_CUSTOMIZED_ORIGINS)`.
- `feature_grouping.py:97-98` (`_create_feature`): defensive skip for non-customized.
- `seed_feature_groups.py:688-691`: defensive guard `if not _is_customized(member_row): continue`.

**Minor note (non-blocking):** `_CUSTOMIZED_ORIGINS` is defined independently in both `feature_membership.py:14` and `feature_grouping.py:20`. Values match; could be centralized later.

### 3. Human-Assignment Preservation — PASS
- `feature_grouping.py:148-151`: Reset loop only deletes links where `source in _AUTO_ASSIGNMENT_SOURCES` (`{"engine", "ai"}`).
- `seed_feature_groups.py:216-222` (`_reset_existing_seed_rows`): Same pattern.
- `seed_feature_groups.py:248-255` (`_current_human_locked_result_ids`): Explicit query for human-source links.
- `server.py:9247-9252`: Manual feature assignment stamps `assignment_source="human"`.

**Observation (non-blocking):** `remove_result_from_feature` (`feature_membership.py:120-152`) does not guard against removing human-authored links. This is acceptable for an explicit AI tool call, but a warning or confirmation field could be added later if human-authored deletion should be logged/flagged.

### 4. Regression Risk — LOW
- `feature_grouping.py:handle`: Changed from "delete all" to "delete auto-assigned only; delete feature only if empty". Strictly *less* destructive. Only risk: human features now survive re-grouping, which is the intended P11 behavior.
- `seed_feature_groups.py:_reset_existing_seed_rows`: Same selective-delete pattern. `Seed:*` features only deleted if zero remaining links.
- Autoflush behavior: `session.delete()` calls are correctly flushed before `select(func.count())` due to SQLAlchemy's default autoflush. Verified no race.

### 5. Test Quality & Coverage — GOOD
16 tests, all passing:
- `test_create_feature_tool.py` (4): basic, description, color_index, invalid assessment.
- `test_feature_membership_tools.py` (7): add customized, reject OOTB, idempotent add, remove, remove nonexistent, DB unique constraint via `IntegrityError`, registry presence.
- `test_feature_grouping_pipeline_tools.py` (5, 2 new): human-link preservation, customized-only linking, plus 3 existing.

**Test run verified:** `pytest tests/test_create_feature_tool.py tests/test_feature_membership_tools.py tests/test_feature_grouping_pipeline_tools.py -v` → 16 passed.

### Summary
Worker A P11-2 integrity tranche is solid. DB uniqueness is two-layered (model + safe migration), customized-only guards cover all write paths, human assignments are preserved in all automatic reset flows, and regression risk from the delete-behavior change is minimal. Tests verify all key invariants. **REVIEW_PASS**.

---

[2026-03-05 22:22] [REVIEWER_E] [REVIEW_PASS] — Worker B (T4 read-only grouping refactor)

**Scope reviewed:** All Worker B uncommitted diffs in `codex/p11-worker-b-20260305` — 4 files focused on T4 read-only grouping refactor per checklist.

**Files changed:**
- `src/mcp/tools/pipeline/seed_feature_groups.py` (core refactor)
- `src/mcp/registry.py` (new tool registration)
- `tests/test_feature_grouping_pipeline_tools.py` (4 new tests)
- `tests/test_phase11c_pipeline_integration.py` (2 new tests)

### 1. `get_suggested_groupings` Is Truly Read-Only — PASS
- `handle_suggestions` (line 945) calls `seed_feature_groups()` with `dry_run=True`, `commit=False`, `reset_existing=False`.
- Inside `seed_feature_groups` with `dry_run=True`:
  - `_reset_existing_seed_rows` is guarded by `if reset_existing and not dry_run:` (line 329) — skipped.
  - Early-return path guards commit with `if not dry_run and commit:` (line 334) — skipped.
  - Cluster loop: dry_run branch (line 695) builds `suggested_groups` payload and `continue`s — no `session.add()`, no `Feature`/`FeatureScanResult`/`FeatureContextArtifact` creation.
  - Final commit/flush block (line 868): `if dry_run:` adds `suggested_groups` to summary; else branch (commit/flush) is skipped.
- **Verdict:** Zero business-data writes in dry_run path. Confirmed by DB assertions in tests.

### 2. `seed_feature_groups` Write Fallback Intact for API Mode — PASS
- Default `dry_run=False` preserves the entire original write path untouched.
- `TOOL_SPEC` (line 960) still points to `handle` with `permission="write"`.
- Pipeline caller in `server.py:1902` calls `seed_feature_groups_handle(grouping_params, session)` with no `dry_run` param — defaults to `False`.
- Write-path regression test (`test_seed_feature_groups_write_mode_still_creates_records`) explicitly verifies Feature + FeatureScanResult creation.

### 3. Registry Permissions Correct — PASS
- `TOOL_SPEC`: `name="seed_feature_groups"`, `permission="write"` — unchanged.
- `SUGGESTIONS_TOOL_SPEC`: `name="get_suggested_groupings"`, `permission="read"`.
- Both registered in `registry.py:203-204`.
- Tests verify: `spec.permission == "read"` for suggestions, `spec.permission == "write"` for seed.
- **Note (non-blocking):** Router (`router.py:301`) currently hardcodes `tool_permission = "read"` for all tools ("Wave 2 scaffold"). Permission enforcement is metadata-only until Wave 2 is implemented. Worker B correctly set the field for future enforcement.

### 4. No Stage/Progress Side-Effects in Dry-Run Mode — PASS
- `handle` function (line 888): `start_phase_progress` guarded by `if not dry_run:`.
- Error path (line 912): `checkpoint_phase_progress(status="failed")` guarded by `if not dry_run:`.
- Success path (line 924): `checkpoint_phase_progress(status="completed")` guarded by `if not dry_run:`.
- `handle_suggestions` bypasses `handle` entirely — calls `seed_feature_groups` directly, no progress tracking at all.
- **Note (non-blocking):** If `get_suggested_groupings` is invoked through the MCP `RuntimeRouter`, the router's own telemetry layer (`_track_tool_start`/`_track_tool_success`) will write tracking records with phase `"tool:get_suggested_groupings"`. This is orthogonal to business-data writes and consistent with how all router-dispatched tools behave.

### 5. Test Quality and Edge Cases — GOOD
6 new tests, all passing:
- `test_seed_feature_groups_dry_run_writes_nothing`: Calls `handle` with `dry_run=True`, verifies all 3 record types absent (Feature, FeatureScanResult, FeatureContextArtifact), checks suggestion payload structure including keys and member IDs.
- `test_get_suggested_groupings_tool_is_read_only`: Calls `handle_suggestions` directly, verifies zero writes.
- `test_seed_feature_groups_write_mode_still_creates_records`: Regression — confirms default write path creates records.
- `test_dry_run_and_write_produce_same_groupings`: Key consistency test — verifies dry_run member sets match write-mode member sets.
- `test_get_suggested_groupings_registered_with_read_permission`: Registry permission check.
- `test_seed_feature_groups_has_write_permission`: Registry permission check.

**Minor cosmetic (non-blocking):** `test_phase11c_pipeline_integration.py` has a duplicate `# Test 5: depth-first telemetry recorded` section header (lines 315-316 and 343-344) caused by insertion placement.

### 6. Full Regression — PASS
`pytest tests/ --tb=short -q` → **607 passed**, 0 failures.

### Summary
Worker B T4 read-only grouping refactor is clean and well-tested. The `get_suggested_groupings` tool is genuinely read-only at the business-data level, the write fallback for api mode is untouched, registry permissions are correctly assigned, and dry-run mode produces no stage/progress side effects. The consistency test (`dry_run_and_write_produce_same_groupings`) is an excellent addition ensuring parity between modes. **REVIEW_PASS**.

---

[2026-03-05 22:22] [REVIEWER_F] [REVIEW_PASS] — Worker C (P11-3 dry-run report)

**Scope reviewed:** `phase11_legacy_cleanup_dryrun_report_2026-03-05.md` — all numerical claims spot-checked via fresh SQL against live `tech_assessment.db`. This review is read-only; no data was modified.

### 1. Primary Count Verification — ALL PASS

22 independent SQL spot checks run against the live DB. All match the report exactly.

| Claim | Expected | Live DB | Result |
|-------|----------|---------|--------|
| Total assessments | 21 | 21 | PASS |
| Assessment 1 scan_result rows | 29,300 | 29,300 | PASS |
| Duplicate groups (assessment 1) | 10,258 | 10,258 | PASS |
| Excess rows (assessment 1) | 14,374 | 14,374 | PASS |
| Max copies per artifact | 6 | 6 | PASS |
| Conflict groups (mixed origin_type) | 222 | 222 | PASS |
| Total features (assessment 1) | 159 | 159 | PASS |
| Feature naming pattern | All "Creator: <user>" | All "Creator: <user>" | PASS |
| FSR rows (assessment 1, all NULL source) | 25,444 | 25,444 | PASS |
| Non-customized FSR rows | 25,000 | 25,000 | PASS |
| Customized FSR rows (modified_ootb + net_new_customer) | 444 | 444 | PASS |
| Pure-legacy features (0 customized members) | 127 | 127 | PASS |
| Features with >=1 customized member (survive cleanup) | 32 | 32 | PASS |
| Human FSR rows at risk (assessment 1) | 0 | 0 | PASS |
| Human FSR rows at risk (globally) | 0 | 0 | PASS |
| Assessments with duplicates | 1 (ASMT0000001 only) | 1 only | PASS |
| Table dup distribution (top 8 tables) | per report | exact match | PASS |
| Assessment 19 orphan features | 2 (Invoicing, Test; 0 members) | confirmed | PASS |
| Assessment 19 seeded feature | Seed: Default, 5 members, engine | confirmed | PASS |
| Assessment 3 feature | 1 feature, 3 customized members | confirmed | PASS |
| Post-cleanup SR arithmetic | 14,926 | 29300-14374=14926 | PASS |
| Post-cleanup FSR/feature arithmetic | 444 / 32 | confirmed | PASS |

### 2. Canonical Selection Rule — ANNOTATED (non-blocking, no safety risk)

**Finding F1 — Section 1 FSR impact SQL uses MIN(sr.id) proxy, which is not the same as the true canonical rule in Section 6c.**

The Section 1 FSR impact query uses `MIN(sr.id)` to identify canonical scan_result rows. Under the TRUE canonical rule from Section 6c (richest origin_type → highest scan_id → lowest sr.id), exactly 222 customized FSR rows (218 `modified_ootb` + 4 `net_new_customer`) point to non-true-canonical scan_result rows. These are internal duplicates within the same scan where two rows were inserted for the same artifact with the same origin_type — the canonical copy is also of the same quality type. No classification downgrade occurs on re-point.

Cross-check: zero net_new_customer scan_result rows are displaced by a modified_ootb row in the same group (verified directly). All 222 are same-type internal duplicates.

**Safety conclusion:** Zero customized memberships are at risk provided the cleanup utility implements Section 6c and re-points FSR rows BEFORE deleting non-canonical scan_result rows. The Section 1 FSR impact SQL is a valid counting proxy for the dry-run report but must NOT be used as operational dedup logic.

**Required ordering for cleanup utility builder:**
1. Compute true canonical per (assessment_id, table_name, sys_id) via Section 6c (richest origin_type → highest scan_id → lowest sr.id)
2. Re-point FSR rows from non-canonical → canonical scan_result IDs
3. Delete non-canonical scan_result rows
4. Delete non-customized FSR rows (unknown_no_history + NULL, assignment_source != 'human')

Reversing steps 2 and 3 would leave 222 customized FSR rows dangling. This is not a report error — the report correctly describes the canonical rule in 6c — but the Section 4 impact matrix should carry an explicit ordering note.

### 3. Human/Customized Data Safety — PASS

- Human-authored memberships: 0 globally (confirmed). Zero-loss guarantee is unconditional.
- Customized memberships (444): Safe under correct Section 6c ordering (see F1).
- The 444 customized FSR rows are the canonical destination rows for the re-point step under the true rule — they are never deleted by any cleanup operation.
- No cross-type displacements: net_new_customer rows are not displaced by modified_ootb in any artifact group (0 such cases confirmed).

### 4. Report Sufficiency — SUFFICIENT

The report is numerically accurate, internally consistent, and contains all information needed to implement the P11-3 cleanup utility safely. Section 6 SQL snippets are correct for dry-run mode. Section 6c canonical selection rule is authoritative and must be used for the apply pass.

One annotation required in handoff to utility builder: Section 1 FSR impact SQL is a counting proxy only — Section 6c is the authoritative dedup logic, and FSR re-pointing must precede scan_result deletion.

### 5. Recommended Human Decision Defaults

| # | Decision | Recommended | Rationale |
|---|----------|-------------|-----------|
| 1 | Cleanup scope | A — Assessment 1 only | Only assessment with meaningful noise; others clean or trivially small. Correct to isolate first run. |
| 2 | Non-canonical scan_result rows | A — Hard-delete | Pure scan artifacts with no unique information; canonical copy preserves all quality data. No archival value. |
| 3 | Orphan features in assessment 19 | A — Delete Invoicing + Test | Both have zero members, zero assignment_source. No information loss. |
| 4 | Maintenance window | Confirm with pviglianti | Assessment 1 is in_progress/scans state; brief confirmation before apply run is prudent. |

### Summary

Worker C's dry-run report is numerically exact across all 22 spot-checked metrics. The canonical selection rule (Section 6c) is correct. Finding F1 is a utility-builder annotation, not a report error — the MIN(id) proxy is appropriate for a read-only counting pass. Human data loss risk is zero. Report is sufficient to proceed to implementation of the cleanup utility. **REVIEW_PASS**.

---

[2026-03-05 22:28] [REVIEWER_F2] [REVIEW_PASS] — Worker C (P11-3 dry-run report) — Fast Cleanup Audit (Task 6B)

**Scope:** 5 independent SQL spot-checks against live `tech_assessment.db`. Read-only; no data modified.

### Top 5 Count Verification

| Claim | Report | Live DB | Result |
|-------|--------|---------|--------|
| Total assessments | 21 | 21 | PASS |
| Assessment 1 scan_result rows | 29,300 | 29,300 | PASS |
| Duplicate groups (assessment 1) | 10,258 | 10,258 | PASS |
| Excess rows (assessment 1) | 14,374 | 14,374 | PASS |
| Non-customized FSR rows (assessment 1) | 25,000 | 25,000 | PASS |

Bonus check: Global human FSR rows = 0 (confirmed). Zero-loss guarantee is unconditional.

**Confidence: HIGH — all 5/5 match exactly.**

### Human Decision Defaults

| # | Decision | Recommended | Rationale |
|---|----------|-------------|-----------|
| 1 | Cleanup scope | **A — Assessment 1 only** | Only assessment with meaningful noise. Isolated first run is lower risk and verifiable. |
| 2 | Non-canonical scan_result rows | **A — Hard-delete** | No archival value; canonical copy preserves richest classification. Archive table adds complexity with no benefit. |
| 3 | Orphan features (assessment 19) | **A — Delete Invoicing + Test** | Zero members, zero assignment_source, zero information loss. Safe to remove. |
| 4 | Maintenance window | **Confirm with pviglianti** | Assessment 1 is in_progress/scans; brief confirmation before apply run is prudent. |

All recommendations align with Worker C's and Reviewer F's defaults. No dissent.

**REVIEW_PASS** — report is numerically exact, human data safety confirmed, 4 decision defaults recommended.
