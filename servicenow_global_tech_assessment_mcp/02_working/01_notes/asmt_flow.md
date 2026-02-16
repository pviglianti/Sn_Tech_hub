# Assessment Workflow — Revised Design

**Date**: 2026-02-16
**Status**: Draft — awaiting approval

---

## Overview

The assessment workflow is restructured around three key changes:
1. **Proactive VH pull** — version history starts pulling as early as possible (instance add/test)
2. **Scans skip classification** — scans fetch records/metadata only; classification is a separate post-VH step
3. **Event-driven VH completion** — workflow waits for VH via `threading.Event`, not by re-pulling

---

## Trigger: Instance Add / Test Connection

When an instance is added or its connection is tested successfully:
- Start a **background thread** pulling full VH (all states)
- Thread creates its own `Session(engine)` + `ServiceNowClient` (neither is thread-safe)
- Tracked via `InstanceDataPull` with `status=running`, visible in Data Browser
- If a VH pull is already running for this instance → skip (don't duplicate)
- Mode decision: use existing `resolve_delta_decision` logic (new instance = full, existing = delta from watermark)
- **No workflow dependency** — this is fire-and-forget background work

### Deduplication Safety
All pull tables have `UniqueConstraint("instance_id", "sn_sys_id")` which SQLite enforces via an automatic **unique index** on that column pair. The VH pull handler uses upsert logic (check existing by `sn_sys_id`, update or create). No duplicate records possible, even if the same VH data is pulled by both a proactive pull and a preflight pull. The unique index also ensures these lookups are fast (indexed, not full table scans).

---

## Step 1: Start Assessment

Single **"Start Assessment"** button replaces the current two-step "Create Assessment" → "Run Scans" flow. Pressing it kicks off the full pipeline.

---

## Step 2: Preflight Data Sync

Pull required data types for the assessment. Two categories:

### Concurrent pulls (configurable)
- **Default**: `version_history`, `customer_update_xml`
- Configured via new integration property `preflight.concurrent_types` (multiselect / slush bucket collector, max 5)
- Each concurrent type runs in its own thread with its own `Session(engine)` + `ServiceNowClient`
- **VH handling**: If a proactive VH pull is already running (from instance add/test), the preflight detects it via `InstanceDataPull.status == 'running'` and **joins that pull** (sets a `threading.Event` to be notified on completion) rather than starting a new one. No stop-and-restart needed.
- If no proactive pull is running, preflight starts VH as a concurrent pull normally

### Sequential pulls (everything else)
- All types NOT in the concurrent list pull one-at-a-time in the main thread
- `metadata_customization`, `app_file_types`, `update_sets`, etc.

### Error handling for concurrent pulls
- If a concurrent pull fails → **retry once immediately** in the same thread
- Other concurrent pulls continue unaffected
- After all sequential pulls complete, retry any still-failed concurrent pulls **one more time**
- If still failing after second retry → mark assessment with error or whatever approrpiate state is for it.. (if no appropriate assessmet state exists add it) user must resolve and rany open pulls/calls/integration jobs running should be cancelled.  Show the integration job/pull that errored in a pop-up modal after the assessment is marked as error/appropriate state. Modal should just say the pull/table that failed and type (prelfight - customer update - Error:XXXXXX) or something like that example. modal should have a X button only to close (x or ok button )

### VH does NOT block preflight completion
- VH continues pulling in the background after all other preflight types finish
- Preflight completes and advances to scans while VH is still running

### Per-item progress + ETA (UI)
Each preflight item shows:
```
✓ Metadata Customization (12,450 / 12,450) — Complete
↻ Version History (34,200 / 150,000) — Running ~2 min
— Update Sets — Pending
```
- Record count: `(pulled / expected)` from existing `_assessment_data_sync_summary` data
- ETA: `rate = records_pulled / elapsed_seconds`, `remaining = (expected - pulled) / rate`
- Smoothed with rolling average to avoid jitter
- Overall progress bar: `sum(pulled) / sum(expected) × 100%`, ETA = max of per-item ETAs

---

## Step 3: Run Scans

Scans begin immediately after preflight (minus VH) completes.

**Key change**: Scans fetch records aka metadata **WITHOUT classification**. The `_process_and_classify_records` function runs with `skip_classification=True` — it still creates `ScanResult` rows with metadata, but `origin_type` is left as `unknown` (or a new `pending_classification` sentinel).

VH continues pulling in its background thread concurrently with scans.

---

## Step 4: Artifact Detail Pull

After scans complete, pull full artifact details for each file type found in scan results.

- This does NOT need classification — artifact relationships are based on the scan result record existing, not on whether it's custom
- VH still running in background concurrently or could be completed with event fired and pendig next step.

---

## Step 5: Wait for VH Completion

After artifact pulls complete the workflow **pauses and waits** for the VH background thread to signal completion via `threading.Event`.
or if already completed during the scans or artifcat pull, the event is qued and the wait skips to the next step.

```python
vh_complete_event = threading.Event()
# ... set by VH pull thread when done ...
vh_complete_event.wait(timeout=3600)  # 1hr max, configurable
```

If VH already completed (event already set) → immediate continue.
If VH times out → mark assessment with warning, proceed with partial classification.
    - need way to reinitiate the vh pull and classification IF this happens. If action created, only show it during this unique timeout case. Otherwise it should be hiddden

### VH Catchup Fix (Bug Fix)
The current `_determine_smart_mode_for_type` compares local count (filtered, current-only ~50K) vs remote total (~500K) and incorrectly decides "full refresh" — re-downloading everything.

**Fix**: Track the state filter in the pull record. Add `state_filter_applied` field to `InstanceDataPull`. The delta decision logic then knows the local count reflects a filtered pull and uses either:
- `state!=current` SN filter to fetch only missing non-current states, OR
- Delta from watermark (`sys_updated_on > last_pull_watermark`) for recently changed records

This fix applies when VH catchup IS needed (no proactive pull, or proactive pull was only partial).

---

## Step 6: Classification

**New standalone stage**. With full VH data now available:

1. Query all `ScanResult` records for this assessment
2. For each result, run `_classify_origin` using full VH + metadata + customer_xml data
3. Set `origin_type`, `head_owner`, `changed_baseline_now` on each result
4. Track count of classified/reclassified results in job state message

This is a **local-only operation** — no SN API calls, just DB reads + writes. Expected to be fast (seconds, not minutes).

### Why separate from scans?
- Classification functions (`_baseline_changed_from_version_history_local`, `_lookup_earliest_version_history_local`) query ALL VH states for accuracy
- With current-only VH, classification produces partial/inaccurate results
- By separating, we guarantee classification always runs with complete data

---

## Step 7: Complete

Assessment workflow marks as complete. Results are fully classified.

Relationships between scan results, artifacts, and features are already established during Steps 3-4 (they don't depend on classification). The classification step enriches the existing records with origin/ownership data.

---

## Revised Workflow Summary

```
Instance Added / Tested:
  └─ Proactive VH pull starts in background thread

Assessment Started (single button):
  Stage 1: Validate instance
  Stage 2: Preflight data sync
           ├─ Concurrent: VH (joins proactive if running) + customer_update_xml + ...
           ├─ Sequential: metadata, app_file_types, update_sets, ...
           └─ VH does NOT block — continues in background
           └─ Per-item progress + ETA visible in UI
  Stage 3: Run scans (NO classification — records + metadata only)
           └─ VH still running in background
  Stage 4: Artifact detail pull
           └─ VH still running in background
  Stage 5: Wait for VH completion (threading.Event)
           └─ If needed, VH catchup uses fixed delta logic (not full re-pull)
  Stage 6: Classification (standalone, full VH available)
  → Workflow "completed"
```

**Best case** (proactive VH finished before assessment started):
- Stage 2: VH already done → skip, other types only
- Stage 5: VH event already set → instant continue
- Stage 6: Classify with full data
- Net: VH is invisible to the workflow — massively faster

**Typical case** (proactive VH still running):
- Stage 2: Joins proactive VH pull, concurrent with other types
- Stages 3-4: VH finishes during scans/artifacts
- Stage 5: Instant continue (VH already done)
- Stage 6: Classify

**Late case** (no proactive pull, VH started in preflight):
- Stage 2: VH starts as concurrent pull
- Stages 3-4: VH still running
- Stage 5: Wait for VH to finish
- Stage 6: Classify

---

## Configuration

### New integration property: `preflight.concurrent_types`
- **Section**: "Preflight"
- **Type**: `multiselect` (new widget type — slush bucket / dual-list collector)
- **Options**: all `DataPullType` values with human-friendly labels
- **Default**: `version_history,customer_update_xml`
- **Max selections**: 5
- **Description**: "Data types that pull concurrently during preflight sync. If empty, all types pull sequentially. Max 5."
- **Scope**: Global application level, compatible with instance-scoped overrides
- **Note**: If the list is empty/cleared, ALL preflight types revert to sequential (1 at a time) pulling

### New widget type: `multiselect`
- `IntegrationPropertyDefinition`: add `max_selections` field
- JS `renderInputForProp`: render dual-list collector for `value_type === "multiselect"`
- Storage: comma-separated values
- Validation: each value against allowed options, enforce `max_selections`

---

## Item 6: Delta Watermark Operator Fix (`>` → `>=`)

### Problem
All delta data pulls use `sys_updated_on>{watermark}` (strictly after). If a batch of records share the exact same `sys_updated_on` timestamp and the pull is interrupted mid-batch, the watermark is saved at that timestamp. On resume, `>` skips all records AT that timestamp — including the ones that weren't pulled yet.

### Fix
Centralize the watermark filter in a single helper on `ServiceNowClient`:
```python
def _watermark_filter(self, since: datetime, inclusive: bool = True) -> str:
    ts = since.strftime('%Y-%m-%d %H:%M:%S')
    op = ">=" if inclusive else ">"
    return f"sys_updated_on{op}{ts}"
```

- **Delta data pulls** (actual record fetching): call with `inclusive=True` → `>=`. The upsert logic + unique index on every pull table guarantees no duplicates from the overlap.
- **Delta probes** (count estimation for mode decision): call with `inclusive=False` → `>`. A slight undercount is conservative — biases toward full refresh, which is the safe default.

### Sites to change (14 data-pull sites across 4 files)

| File | Lines | Count | Notes |
|------|-------|-------|-------|
| `sn_client.py` | 288, 306, 316, 338, 396, 402, 410, 419, 429, 437, 443 | 11 | `build_*_query` methods → use `_watermark_filter(since)` |
| `sn_client.py` | 1022 | 1 | `iterate_delta_keyset` initial watermark → `_watermark_filter(since)` |
| `csdm_ingestion.py` | 523 | 1 | `build_delta_query` → use `>=` |
| `sn_dictionary.py` | 207 | 1 | Dictionary schema delta → use `>=` |

### Sites NOT changed (already correct or different purpose)
- `sn_client.py:1019` — keyset cursor already handles ties via `sys_id` tiebreaker. No change.
- `scan_executor.py:548` — `_apply_since_filter` already uses `>=`. No change.
- `analytics.py:395` — date-range filter for charts, not a delta pull. No change.
- Delta probes called via `_estimate_expected_total` — these build queries using the same `build_*_query` methods but are **called separately** with `since=watermark`. After centralization, probes will call `_watermark_filter(since, inclusive=False)` to keep `>` for counts.

### Probe vs Pull separation
Currently, `_estimate_expected_total` calls the same `build_*_query` methods as the actual pulls. After this change, the `build_*_query` methods need to accept a parameter indicating probe vs pull context, OR the probe path constructs its own query with `inclusive=False`. Recommended: add `inclusive: bool = True` parameter to each `build_*_query` method (simple, no architectural change).

---

## Files Affected

### Item 1: VH Catchup Fix
- `models.py`: `InstanceDataPull` — add `state_filter_applied` field
- `data_pull_executor.py`: `execute_data_pull` — record the state filter used
- `integration_sync_runner.py`: `resolve_delta_decision` — accept optional filter context
- `server.py`: `_run_assessment_version_history_postscan_catchup` — use delta/filtered mode

### Item 2: Proactive VH Pull + Event Signaling
- `server.py`: instance creation/test endpoints — add proactive trigger
- `server.py`: new `_start_proactive_vh_pull()` + `threading.Event` registry
- `server.py`: `_run_assessment_preflight_data_sync` — detect/join existing VH pull
- `server.py`: Stage 5 wait logic in `_run_scans_background`

### Item 3: Separated Classification
- `server.py`: `_run_scans_background` — add Stage 6 classification, remove classification from Stage 3
- `scan_executor.py`: add `skip_classification` parameter to `_process_and_classify_records`
- `scan_executor.py`: extract classification into reusable `classify_scan_results(session, assessment_id)`
- `server.py`: new `_classify_assessment_results()` function for Stage 6

### Item 4: Per-Item Progress + ETA
- `server.py`: `_assessment_data_sync_summary` — add `started_at` to detail rows
- `assessment_detail.html`: `applyPreflightStatus` — render `(pulled / expected)` + ETA
- `style.css`: minor styling for ETA text (muted, smaller font)

### Item 5: Configuration
- `integration_properties.py`: add `preflight.concurrent_types` definition + `multiselect` type
- `integration_properties.js`: render dual-list collector widget
- `server.py`: `_run_assessment_preflight_data_sync` — read concurrent types from config

### Item 6: Delta Watermark Operator Fix
- `sn_client.py`: add `_watermark_filter()` helper, refactor 11 `build_*_query` methods + `iterate_delta_keyset` initial watermark to use it. Add `inclusive` parameter for probe vs pull distinction.
- `csdm_ingestion.py`: `build_delta_query` — switch `>` to `>=`
- `sn_dictionary.py`: dictionary delta query — switch `>` to `>=`
- `data_pull_executor.py`: `_estimate_expected_total` — pass `inclusive=False` when building probe queries

---

## Implementation Priority

1. **Item 6 (delta watermark fix)** — smallest, most self-contained. Zero risk (upsert handles overlaps). Foundation fix that benefits all subsequent items. Do first.
2. **Item 1 (VH catchup fix)** — highest impact on VH specifically. Small, focused change.
3. **Item 3 (separated classification)** — correctness fix. Decouples scan from VH dependency.
4. **Item 2 (proactive VH pull + event signaling)** — best UX win. Requires threading infrastructure.
5. **Item 4 (per-item progress + ETA)** — UI polish. Can be implemented independently.
6. **Item 5 (configuration)** — enables Items 2+4 to be user-configurable.

Items 1+3 are tightly coupled (both change the VH/classification relationship).
Items 2, 4, 5, and 6 are independent of each other.

---

## Testing Strategy

- **Item 6**: Unit test `_watermark_filter` helper. Verify `build_*_query(since=X)` produces `>=` for pulls and `>` for probes. Verify existing delta pull tests still pass with `>=` (upsert handles overlap).
- **Item 1**: Unit test `resolve_delta_decision` with `state_filter_applied` context. Verify delta/skip instead of full re-pull.
- **Item 2**: Integration test: create instance → verify background VH pull starts. Create assessment → verify preflight joins existing pull via event.
- **Item 3**: Unit test `classify_scan_results` with known VH data. Verify scans produce `pending_classification` results, classification stage enriches them.
- **Item 4**: Manual visual QA — run assessment, verify per-item counts update, ETA displays and converges.
- **Item 5**: Unit test multiselect property parsing + validation. Visual QA for slush bucket widget.
