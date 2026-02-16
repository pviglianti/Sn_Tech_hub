# Version History Optimization + Parallel Pulls Design

**Date**: 2026-02-16
**Owner**: Claude
**Status**: Draft — awaiting approval

---

## Problem Statement

The assessment scan workflow is bottlenecked by the version history (VH) catchup stage (Stage 6). Two root causes:

1. **VH catchup re-downloads everything**: Stage 2 pulls VH with `state=current` filter (~50K records). Stage 6's `_determine_smart_mode_for_type` compares local count (50K) against total remote count (500K+), sees a massive gap, and decides "full refresh" — re-pulling all 500K including the 50K it already has.

2. **No re-classification after full VH**: Classification happens during scans (Stage 3) using only current-state VH data. Functions like `_baseline_changed_from_version_history_local` and `_lookup_earliest_version_history_local` query ALL VH states but only current records exist. Results are partially inaccurate, and no re-classification runs after full VH arrives.

3. **VH pull happens too late**: Full VH is only pulled at the end of the workflow. If it were available proactively (started when the instance is added), the assessment workflow could use it immediately.

4. **No per-item progress visibility**: During preflight, users see items flip between pending/running/complete but have no insight into how many records have been pulled or how long remains.

---

## Design: 4 Connected Improvements

### Item 1: Fix VH Catchup Bug

**Problem**: `_run_assessment_version_history_postscan_catchup` → `_determine_smart_mode_for_type` → `resolve_delta_decision` sees `local(50K) << remote(500K)` → decides "full". It doesn't know the gap is from the intentional `state=current` filter.

**Fix**: Replace the catchup function's mode decision with a VH-aware approach:
- Use **delta mode from the Stage 2 watermark** — the watermark (`last_sys_updated_on`) from the current-only pull is valid for ALL states, not just current. Records with `sys_updated_on > watermark` haven't been seen yet (recently modified). But this misses old non-current records.
- Better: **Always use full mode BUT with upsert** — the pull handler should `INSERT OR IGNORE` / upsert rows. Records already present from Stage 2 are skipped or updated cheaply. No duplicate data, no "restart from scratch" appearance.
- Best: **Track the filter in the pull record** — add `version_state_filter` to `InstanceDataPull` so the delta decision knows that the local count reflects a filtered pull. The catchup can then use `state!=current` as a SN query filter to fetch only the missing states, or the delta decision can factor in the filter when comparing counts.

**Recommended approach**: Option 3 (track filter). This is the most correct — it tells the system exactly what it has vs what it's missing. The catchup queries SN for `state!=current` or for all states using delta from the watermark, depending on which is cheaper.

**Files affected**:
- `server.py`: `_run_assessment_version_history_postscan_catchup` — pass state filter or use delta
- `models.py`: `InstanceDataPull` — add optional `state_filter_applied` field
- `data_pull_executor.py`: `execute_data_pull` — record the state filter used
- `integration_sync_runner.py`: `resolve_delta_decision` — accept optional filter context

### Item 2: Proactive VH Pull on Instance Add/Test

**Concept**: When an instance is added or its connection is tested successfully, start a background thread that pulls full VH (all states). By the time the user creates and runs their first assessment, VH data is already present or mostly complete.

**Trigger points**:
- `POST /instances` (create instance) — after successful connection test
- `POST /instances/{id}/test` — after successful connection test
- Only if no VH pull is currently running for this instance

**Implementation**:
- New function `_start_proactive_vh_pull(instance_id)` that spawns a background thread
- Thread creates its own `Session(engine)` + `ServiceNowClient`
- Uses `run_data_pulls_for_instance` with `DataPullType.version_history` in full mode
- Tracked via `InstanceDataPull` with `status=running`, visible in Data Browser
- If VH is already running (from a previous trigger), skip

**Workflow integration**:
- In `_run_assessment_preflight_data_sync` (Stage 2): check if a proactive VH pull is already running. If so, use `wait_for_running=True` to wait for it instead of starting a new pull.
- In Stage 6 (catchup): if proactive pull already completed full VH, `_determine_smart_mode_for_type` should see local ≈ remote and decide "skip" or "delta".

**Files affected**:
- `server.py`: instance creation/test endpoints — add proactive trigger
- `server.py`: new `_start_proactive_vh_pull()` function
- No model changes needed — uses existing `InstanceDataPull` tracking

### Item 3: Re-Classification After Full VH

**Concept**: After full VH data is available, re-run classification on all scan results to correct any inaccuracies from the initial partial-VH classification.

**New Stage 7** in the assessment workflow:
```
Stage 6: VH catchup (or already done via proactive pull)
Stage 7: Re-classify scan results with full VH data ← NEW
→ Workflow "completed"
```

**Implementation**:
- New function `_reclassify_assessment_results(session, assessment, instance_id)`:
  - Query all `ScanResult` records for the assessment
  - For each result, re-run `_classify_origin` using local VH/metadata/customer_xml data (now with full VH)
  - Compare new classification vs existing. If different, update `origin_type`, `head_owner`, `changed_baseline_now`
  - Track count of reclassified results in the job state message
- This is a **local-only operation** — no SN API calls, just DB reads + writes
- Expected to be fast (seconds, not minutes) since it's just local lookups

**Stage state**:
```python
_set_assessment_scan_job_state(
    assessment_id,
    stage="reclassification",
    status="running",
    message="Re-classifying results with full version history...",
)
```

**Files affected**:
- `server.py`: new `_reclassify_assessment_results()` function, add Stage 7 to workflow
- `scan_executor.py`: extract classification logic into a reusable function (currently inline in `_process_and_classify_records`)

### Item 4: Per-Item Progress + ETA

**Concept**: Each preflight item shows its own pull progress (X of Y records, ETA). The overall progress bar shows aggregate completion percentage and overall ETA.

**Data already available**: `_assessment_data_sync_summary` already returns per-item `records_pulled`, `expected_total`, `local_count`. The polling endpoint includes this in `data_sync.details`.

**Per-item display** (in the preflight card):
```
✓ Metadata Customization (12,450 / 12,450) - Complete
↻ Version History (34,200 / 150,000) - Running ~2 min
— Update Sets - Pending
```

Each running item shows:
- Record count: `(pulled / expected)`
- ETA: calculated from pull rate (records/sec × remaining)

**Overall progress bar**:
- Percentage: `sum(pulled across all items) / sum(expected across all items) × 100`
- ETA: `max(per-item ETA)` — the longest remaining item determines overall ETA

**ETA calculation**:
- Track `started_at` for each pull (already in `InstanceDataPull`)
- On each poll: `rate = records_pulled / elapsed_seconds`
- `remaining_seconds = (expected_total - records_pulled) / rate`
- Smooth with a rolling average to avoid jitter

**Backend changes**:
- `_assessment_data_sync_summary` already returns the needed fields — no changes needed
- Add `started_at` to the `data_sync.details` response (already on `InstanceDataPull`)

**Frontend changes** (in `assessment_detail.html`):
- `applyPreflightStatus`: render `(pulled / expected)` in the count element
- New `_calculateETA(startedAt, pulled, expected)` helper
- Render per-item ETA text next to running items
- Aggregate overall ETA in the progress bar text
- Format as "~X min" or "~X sec" for readability

**Files affected**:
- `server.py`: `_assessment_data_sync_summary` — add `started_at` to detail rows
- `assessment_detail.html`: `applyPreflightStatus` — render progress + ETA
- `style.css`: minor styling for ETA text (muted, smaller font)

---

## Revised Workflow (after all 4 items)

```
Instance Added / Tested:
  └─ Proactive VH pull starts in background thread (Item 2)

Assessment Scan Workflow:
  Stage 1: Validate instance
  Stage 2: Preflight required sync
           └─ If proactive VH already running → wait for it
           └─ Otherwise pull VH current-only + others
           └─ Per-item progress + ETA visible (Item 4)
  Stage 3: Run scans (initial classification with available VH)
  Stage 4: Artifact detail pull (postflight)
  Stage 5: Optional types sync
  Stage 6: VH catchup — now uses delta/filtered mode (Item 1)
           └─ If proactive pull already completed full VH → skip
  Stage 7: Re-classify results with full VH data (Item 3)
  → Workflow "completed"
```

**Best case** (proactive pull finished before assessment):
- Stage 2: VH already complete → skip, other required types only (seconds)
- Stage 6: VH already complete → skip
- Stage 7: Re-classify (fast, local-only)
- Net effect: VH is invisible to the workflow — massively faster

**Typical case** (proactive pull still running):
- Stage 2: Wait for proactive VH to finish (or join existing pull)
- Stage 6: Already done → skip
- Stage 7: Re-classify

---

## Configuration

**New integration property**: `preflight.concurrent_types`
- Section: "Preflight"
- Type: `multiselect` (new widget type — dual-list / slush bucket collector)
- Options: all `DataPullType` values with human-friendly labels
- Default: `version_history,customer_update_xml`
- Max selections: 5
- Description: "Data types that pull concurrently during preflight sync. Reduces wall-clock time for large datasets. If empty, all types pull sequentially. Max 5."
- Scope: Global application level, compatible with instance-scoped overrides

**New widget type** (`multiselect`) added to the integration property system:
- `IntegrationPropertyDefinition`: add `max_selections` field
- JS `renderInputForProp`: render dual-list collector for `value_type === "multiselect"`
- Storage: comma-separated values
- Validation: check each value against allowed options, enforce max_selections

---

## Implementation Priority

1. **Item 1 (VH catchup fix)** — highest impact, fixes the immediate pain. Small, focused change.
2. **Item 3 (re-classification)** — correctness fix. Depends on Item 1 (needs full VH before re-classify).
3. **Item 2 (proactive VH pull)** — best UX win. Can be implemented independently.
4. **Item 4 (per-item progress + ETA)** — polish. Can be implemented independently.

Items 1+3 are tightly coupled. Items 2 and 4 are independent.

---

## Testing Strategy

- **Item 1**: Unit test `_determine_smart_mode_for_type` with filtered local data (local << remote but with state filter). Verify delta/skip instead of full.
- **Item 2**: Integration test: create instance → verify background VH pull starts. Create assessment → verify Stage 2 waits for/skips existing pull.
- **Item 3**: Unit test `_reclassify_assessment_results` with known VH data that changes classification outcomes.
- **Item 4**: Manual visual QA — run assessment, verify per-item counts update, ETA displays and converges.
