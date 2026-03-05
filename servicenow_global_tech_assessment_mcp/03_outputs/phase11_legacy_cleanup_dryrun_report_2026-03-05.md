# Phase 11 Legacy Cleanup — Dry-Run Report

Date: 2026-03-05
Analyst: Claude (Worker C, Read-Only Pass)
DB: `tech-assessment-hub/data/tech_assessment.db`
Status: DRY-RUN ONLY — no data was modified.

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Assessments analyzed | 21 |
| Assessments with duplicates | 1 (ASMT0000001) |
| Assessments with features | 3 (ASMT0000001, 3, 19) |
| Assessments with non-customized memberships | 1 (ASMT0000001) |
| **Recommended first cleanup target** | **ASMT0000001 — "weis inc"** |

Assessment 1 concentrates all legacy data problems: massive duplicate scan artifacts from multi-run accumulation, and a legacy feature grouping layer where 98% of memberships link to non-customized results. All other assessments are clean or trivially small.

---

## Section 1 — Duplicate Scan Result Artifacts

### SQL Used

```sql
-- Find duplicate (assessment_id, table_name, sys_id) groups
SELECT
    sc.assessment_id,
    sr.table_name,
    sr.sys_id,
    COUNT(*) as dup_count
FROM scan_result sr
JOIN scan sc ON sr.scan_id = sc.id
GROUP BY sc.assessment_id, sr.table_name, sr.sys_id
HAVING COUNT(*) > 1
ORDER BY sc.assessment_id, dup_count DESC;

-- Summarize per assessment
SELECT
    assessment_id,
    COUNT(*) as duplicate_group_count,
    SUM(dup_count - 1) as excess_rows,
    MAX(dup_count) as max_copies
FROM (
    SELECT sc.assessment_id, sr.table_name, sr.sys_id, COUNT(*) as dup_count
    FROM scan_result sr
    JOIN scan sc ON sr.scan_id = sc.id
    GROUP BY sc.assessment_id, sr.table_name, sr.sys_id
    HAVING COUNT(*) > 1
) sub
GROUP BY assessment_id;
```

### Results

| Assessment | Dup Groups | Excess Rows | Max Copies |
|------------|-----------|-------------|------------|
| ASMT0000001 (weis inc) | 10,258 | 14,374 | 6 |
| All others | 0 | 0 | — |

### Root Cause

All duplicates are in `scan_type = metadata_index`. Assessment 1 was run multiple times across overlapping scan configurations (scans 47–52 and beyond), and each run inserted new `scan_result` rows for the same ServiceNow artifact without deduplication.

**Table distribution of duplicate (table_name, sys_id) groups:**

| Table | Groups with Dups |
|-------|-----------------|
| sys_ui_policy | 3,870 |
| sys_script_client | 3,770 |
| sys_dictionary | 1,228 |
| sys_script | 1,011 |
| sys_ui_policy_action | 165 |
| sys_ui_action | 55 |
| sys_script_include | 33 |
| sysevent_email_action | 31 |
| (others) | 95 |

### Conflict Cases

Of the 10,258 duplicate groups:
- **10,036 groups** have a uniform origin_type across all copies.
- **222 groups** have conflicting origin_types (an earlier scan classified the artifact as `unknown_no_history`; a later scan correctly classified it as `modified_ootb`).

Conflicting example:
```
sys_script_client  |  000d7eab...  |  scan 47 → unknown_no_history
sys_script_client  |  000d7eab...  |  scan 48 → modified_ootb
sys_script_client  |  000d7eab...  |  scan 48 → modified_ootb  (internal dup within scan 48)
```

### Canonical Selection Rule

For each `(assessment_id, table_name, sys_id)` group, retain exactly one canonical row:

1. **Primary:** prefer richest `origin_type` (`modified_ootb` > `net_new_customer` > `unknown_no_history` > NULL).
2. **Secondary:** prefer highest `scan_id` (most recent scan run).
3. **Tiebreaker:** prefer lowest `scan_result.id`.

This rule upgrades classifications for the 222 conflicting groups, preserving accuracy.

### FSR Impact

```sql
-- Count feature_scan_result rows pointing to non-canonical scan_result rows
SELECT COUNT(*) as fsr_linked_to_non_canonical
FROM feature_scan_result fsr
WHERE fsr.scan_result_id NOT IN (
    SELECT MIN(sr.id) as canonical_id
    FROM scan_result sr
    JOIN scan sc ON sr.scan_id = sc.id
    WHERE sc.assessment_id = 1
    GROUP BY sc.assessment_id, sr.table_name, sr.sys_id
)
AND fsr.scan_result_id IN (
    SELECT sr.id FROM scan_result sr JOIN scan sc ON sr.scan_id = sc.id
    WHERE sc.assessment_id = 1
);
-- Result: 14,374
```

All 14,374 excess scan_result rows have corresponding FSR rows. The cleanup utility must re-point or delete these FSR links before (or together with) deleting the non-canonical scan_result rows.

---

## Section 2 — Non-Customized Feature Memberships

### SQL Used

```sql
-- Non-customized memberships (excl. human-authored)
SELECT COUNT(*) as non_customized_memberships_to_remove
FROM feature_scan_result fsr
JOIN scan_result sr ON fsr.scan_result_id = sr.id
JOIN feature f ON fsr.feature_id = f.id
WHERE f.assessment_id = 1
AND (sr.origin_type NOT IN ('modified_ootb', 'net_new_customer') OR sr.origin_type IS NULL)
AND (fsr.assignment_source IS NULL OR fsr.assignment_source != 'human');

-- Membership origin_type breakdown for assessment 1
SELECT sr.origin_type, fsr.assignment_source, COUNT(*) as count
FROM feature_scan_result fsr
JOIN scan_result sr ON fsr.scan_result_id = sr.id
JOIN feature f ON fsr.feature_id = f.id
WHERE f.assessment_id = 1
GROUP BY sr.origin_type, fsr.assignment_source;
```

### Results

| Assessment | Non-Customized Memberships | Customized Memberships | Human-Authored |
|------------|---------------------------|----------------------|----------------|
| ASMT0000001 | 25,000 | 444 | 0 |
| ASMT0000003 | 0 | 3 | 0 |
| ASMT0000019 | 0 | 5 | 0 |

**Assessment 1 detail:**

| origin_type | assignment_source | Count |
|-------------|-------------------|-------|
| unknown_no_history | NULL | 25,000 |
| modified_ootb | NULL | 436 |
| net_new_customer | NULL | 8 |

All 25,444 memberships have `assignment_source = NULL` — these were created before the `assignment_source` column was introduced. None are human-authored. The 444 customized memberships (modified_ootb + net_new_customer) must be preserved.

---

## Section 3 — Engine-Assigned / Legacy Feature Groupings

### SQL Used

```sql
-- Features per assessment, with source breakdown
SELECT
    f.assessment_id,
    COUNT(DISTINCT f.id) as feature_count,
    SUM(CASE WHEN fsr.assignment_source = 'human' THEN 1 ELSE 0 END) as human,
    SUM(CASE WHEN fsr.assignment_source = 'ai' THEN 1 ELSE 0 END) as ai,
    SUM(CASE WHEN fsr.assignment_source = 'engine' THEN 1 ELSE 0 END) as engine,
    SUM(CASE WHEN (fsr.assignment_source IS NULL OR fsr.assignment_source = '') THEN 1 ELSE 0 END) as legacy_null
FROM feature f
LEFT JOIN feature_scan_result fsr ON fsr.feature_id = f.id
GROUP BY f.assessment_id;

-- Features in assessment 1 with zero customized members
WITH customized_features AS (
    SELECT DISTINCT fsr.feature_id
    FROM feature_scan_result fsr
    JOIN scan_result sr ON fsr.scan_result_id = sr.id
    WHERE sr.origin_type IN ('modified_ootb', 'net_new_customer')
    AND (fsr.assignment_source IS NULL OR fsr.assignment_source != 'human')
)
SELECT COUNT(*) FROM feature
WHERE assessment_id = 1
AND id NOT IN (SELECT feature_id FROM customized_features);
```

### Results

**Assessment 1 (weis inc):**

| Metric | Count |
|--------|-------|
| Total features | 159 |
| All memberships with NULL source (legacy) | 25,444 |
| Features with any customized member | 32 |
| Features with zero customized members (pure legacy noise) | 127 |
| Orphan features (zero members of any kind) | 0 |

**Assessment 1 feature naming pattern:** All 159 features are named `Creator: <username>` (e.g., `Creator: admin`, `Creator: pviglianti`). These were auto-generated by an early engine grouping pass using sys_created_by as the grouping signal — a known pre-P11 legacy pattern.

**Assessment 19 (Inc — only completed assessment):**

| Feature | Members | Assignment Source | Customized? |
|---------|---------|-------------------|-------------|
| Invoicing | 0 | — | — (orphan) |
| Test | 0 | — | — (orphan) |
| Seed: Default | 5 | engine | Yes (all modified_ootb / net_new_customer) |

The 2 orphan features (Invoicing, Test) were created manually but never populated. The seeded feature has 5 valid customized members.

**Assessment 3 (Incident Mgmt):**
1 feature, 3 customized members, NULL source. Small, clean.

---

## Section 4 — Cleanup Impact Matrix

### For Assessment 1 (recommended first pass)

| Operation | Rows Affected | Preservation Guarantee |
|-----------|--------------|----------------------|
| Remove non-customized FSR rows (unknown_no_history, NULL source) | 25,000 | 0 human rows — safe |
| Delete pure-legacy features (127 features with no customized members post-cleanup) | 127 features | No human-authored links — safe |
| Preserve customized FSR rows | 444 | All preserved |
| Preserve features with customized members | 32 | Preserved with their 444 memberships |
| Deduplicate scan_result artifacts (remove 14,374 excess rows, canonical selection) | 14,374 rows | Richest classification preserved |
| Re-point FSR rows from deleted duplicate sr to canonical sr | Up to 14,374 FSR rows | Handled during dedup step |
| Human-authored memberships at risk | 0 | Zero loss confirmed |

**Post-cleanup expected state for Assessment 1:**
- scan_result rows: 29,300 − 14,374 = **~14,926** (unique artifacts only)
- feature_scan_result rows: 25,444 − 25,000 = **444** (customized-only)
- features: 159 − 127 = **32** (those with customized members)

### For Assessments 3 and 19 (low priority)

| Operation | Rows | Notes |
|-----------|------|-------|
| Delete 2 orphan features in assessment 19 | 2 | Human-created manual features with no members |
| Leave assessment 3 alone | — | 3 customized memberships, no noise |

Human decision required before deleting the 2 orphan features in assessment 19 — they were manually created and may be intentional placeholders.

---

## Section 5 — Open Human Decisions Required

These must be resolved before the `--apply` run. Codex's P11-3 utility should gate on these.

| # | Decision | Options |
|---|----------|---------|
| 1 | **Cleanup scope** | (A) Assessment 1 only for first run — **recommended** / (B) All flagged assessments in one pass |
| 2 | **Non-canonical scan_result rows** | (A) Hard-delete — simpler / (B) Move to `scan_result_archive` table first |
| 3 | **Orphan features in assessment 19** | (A) Delete Invoicing + Test (no members) / (B) Leave as-is |
| 4 | **Maintenance window** | Confirm no active assessment edits are in flight during apply run |

**Claude's recommendation:** Option A for all four — assessment 1 only, hard-delete, delete assessment 19 orphans, pick a low-traffic window.

---

## Section 6 — SQL Snippets for Cleanup Utility Reference

These are the core queries the P11-3 `--dry-run` mode should execute and report on. The `--apply` mode runs the corresponding DELETE/UPDATE statements.

### 6a. Count non-customized memberships (dry-run check)
```sql
SELECT f.assessment_id, COUNT(*) as non_customized_memberships
FROM feature_scan_result fsr
JOIN scan_result sr ON fsr.scan_result_id = sr.id
JOIN feature f ON fsr.feature_id = f.id
WHERE f.assessment_id = :assessment_id
AND (sr.origin_type NOT IN ('modified_ootb', 'net_new_customer') OR sr.origin_type IS NULL)
AND (fsr.assignment_source IS NULL OR fsr.assignment_source NOT IN ('human'))
GROUP BY f.assessment_id;
```

### 6b. Count features that become empty post-cleanup (dry-run check)
```sql
WITH customized_features AS (
    SELECT DISTINCT fsr.feature_id
    FROM feature_scan_result fsr
    JOIN scan_result sr ON fsr.scan_result_id = sr.id
    JOIN feature f ON fsr.feature_id = f.id
    WHERE f.assessment_id = :assessment_id
    AND sr.origin_type IN ('modified_ootb', 'net_new_customer')
)
SELECT COUNT(*) as features_to_delete
FROM feature
WHERE assessment_id = :assessment_id
AND id NOT IN (SELECT feature_id FROM customized_features);
```

### 6c. Identify canonical scan_result per (assessment_id, table_name, sys_id)
```sql
-- Canonical = richest origin_type, then highest scan_id, then lowest sr.id
-- origin_type priority: modified_ootb=3, net_new_customer=2, unknown_no_history=1, NULL=0
SELECT
    MIN(sr.id) KEEP (
        DENSE_RANK FIRST ORDER BY
            CASE sr.origin_type
                WHEN 'modified_ootb' THEN 3
                WHEN 'net_new_customer' THEN 2
                WHEN 'unknown_no_history' THEN 1
                ELSE 0
            END DESC,
            sc.id DESC,
            sr.id ASC
    ) as canonical_sr_id,
    sc.assessment_id,
    sr.table_name,
    sr.sys_id
FROM scan_result sr
JOIN scan sc ON sr.scan_id = sc.id
WHERE sc.assessment_id = :assessment_id
GROUP BY sc.assessment_id, sr.table_name, sr.sys_id
HAVING COUNT(*) > 1;
```

Note: SQLite does not support `KEEP (DENSE_RANK ...)`. Equivalent SQLite-compatible version:
```sql
-- Step 1: build priority-ordered subquery per group
SELECT sr.id as sr_id, sr.table_name, sr.sys_id, sc.assessment_id,
    CASE sr.origin_type
        WHEN 'modified_ootb' THEN 3
        WHEN 'net_new_customer' THEN 2
        WHEN 'unknown_no_history' THEN 1
        ELSE 0
    END as type_rank,
    sc.id as scan_id_val
FROM scan_result sr
JOIN scan sc ON sr.scan_id = sc.id
WHERE sc.assessment_id = :assessment_id;

-- Step 2: select canonical row per group (use in cleanup utility logic)
-- In Python: group by (assessment_id, table_name, sys_id),
-- sort by (type_rank DESC, scan_id DESC, sr_id ASC), keep first.
```

### 6d. Count duplicate excess rows (dry-run check)
```sql
SELECT COUNT(*) as dup_group_count, SUM(dup_count - 1) as excess_rows
FROM (
    SELECT sc.assessment_id, sr.table_name, sr.sys_id, COUNT(*) as dup_count
    FROM scan_result sr
    JOIN scan sc ON sr.scan_id = sc.id
    WHERE sc.assessment_id = :assessment_id
    GROUP BY sc.assessment_id, sr.table_name, sr.sys_id
    HAVING COUNT(*) > 1
) sub;
```

### 6e. Human membership zero-loss pre-flight check
```sql
SELECT COUNT(*) as human_memberships_at_risk
FROM feature_scan_result fsr
JOIN feature f ON fsr.feature_id = f.id
WHERE f.assessment_id = :assessment_id
AND fsr.assignment_source = 'human';
-- Must return 0 before proceeding with apply
```

---

## Section 7 — Candidate Assessment Summary

| Assessment | Name | State | Pipeline Stage | Scan Results | Features | Dup Groups | Excess Rows | Non-Cust FSRs | Human FSRs | Cleanup Priority |
|------------|------|-------|----------------|-------------|---------|-----------|-------------|--------------|-----------|-----------------|
| ASMT0000001 | weis inc | in_progress | scans | 29,300 | 159 | 10,258 | 14,374 | 25,000 | 0 | **HIGH — First target** |
| ASMT0000003 | Incident Mgmt | in_progress | scans | 3,838 | 1 | 0 | 0 | 0 | 0 | Low — no action needed |
| ASMT0000019 | Inc | in_progress | complete | 2,114 | 3 | 0 | 0 | 0 | 0 | Low — 2 orphan features only |
| ASMT0000002,4-18,20-21 | (various) | in_progress | scans | varies | 0 | 0 | 0 | 0 | 0 | None — no features or duplicates |

---

## Section 8 — Running the Cleanup Utility

### Prerequisites

- Python virtual environment activated (`tech-assessment-hub/venv`)
- Working directory: `tech-assessment-hub/`

### Basic Usage

```bash
# Dry-run (default, read-only) — shows what would be cleaned
./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001

# Dry-run with JSON output (for programmatic consumption)
./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001 --json
```

### Applying Cleanup

```bash
# Interactive apply — shows dry-run report first, then prompts for confirmation
./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001 --apply

# Automated apply — skips confirmation prompt (for scripting)
./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001 --apply --yes
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (dry-run report generated, apply completed, or user declined apply confirmation) |
| 1 | Pre-flight failure (assessment not found, active pipeline, human FSRs detected) |
| 2 | Runtime error |

### Safety Gates

1. **Dry-run default** — no destructive action without explicit `--apply`.
2. **Pre-flight checks** — aborts if assessment is mid-pipeline or has human-authored memberships.
3. **Confirmation prompt** — `--apply` requires typing `YES` (bypass with `--yes` for automation).
4. **Single transaction** — all mutations are atomic; any error triggers full rollback.

### Post-Apply Verification

After running `--apply`, re-run in dry-run mode to confirm idempotency:

```bash
./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001
```

A successful cleanup should show zero duplicate groups, zero non-customized FSRs, and zero empty features.

---

## Appendix: Raw Counts Reference

```
Total assessments:         21
Total scan_result rows:    ~160,000+ (across all assessments)
Assessment 1 scan_results: 29,300
Assessment 1 unique (table, sys_id) pairs: 14,926 after dedup
Assessment 7 scan_results: 77,191 (no features, no duplicates)
Assessment 21 scan_results: 23,616 (no features, no duplicates)

Feature table total rows:  163
  - Assessment 1: 159 features (all legacy Creator: <user> named)
  - Assessment 19: 3 features (2 orphan, 1 seeded)
  - Assessment 3: 1 feature

feature_scan_result total:     25,452
  - assignment_source = NULL:  25,447
  - assignment_source = engine: 5
  - assignment_source = human: 0
  - assignment_source = ai:    0

Customization table rows: 674
  - Assessment 1: 444 (matches customized FSR count)
```
