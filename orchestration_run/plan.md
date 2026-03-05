# Sprint Plan — SN API Centralization & DESC Bail-Out

**Date:** 2026-03-05
**Architect:** Architect Agent
**PM:** PM Agent
**Devs:** 3

## Sprint Goal

Eliminate all duplicate SN API call paths (scan_executor custom batching, sn_dictionary HTTP bypasses), add DESC-ordering support to `_iterate_batches()`, introduce 3 new Integration Properties for pull optimization, add 6 new `InstanceDataPull` columns for bail-out telemetry, and implement dual-signal bail-out logic in `data_pull_executor.py` — reducing unnecessary API calls by up to 99% on re-pull scenarios.

## Architecture Notes

### Patterns to Follow
- **Property system**: All tunable values use `PropertyDef` in `integration_properties.py` with frozen dataclass, `PROPERTY_DEFINITIONS` list, and `load_*_properties()` helpers. Never hardcode numeric thresholds.
- **Batch iteration**: `sn_client._iterate_batches()` is the single authoritative batch loop. It resolves config from Integration Properties at runtime. All callers must use it — no custom offset loops.
- **Watermark filter**: `sn_client._watermark_filter(since, inclusive)` is the single authoritative since-filter builder. `>=` for data pulls, `>` for probes (though we are normalizing to `>=` everywhere per audit recommendation Option A).
- **DB migrations**: New columns on SQLModel classes use `Optional[T] = None` default so SQLite `ALTER TABLE ADD COLUMN` works without data migration scripts.
- **Gold standard**: `data_pull_executor.py` is the reference implementation for all SN integration patterns. New logic follows its conventions.

### Reuse Points
- `sn_client._iterate_batches()` already supports configurable `batch_size`, `inter_batch_delay`, `max_batches`, and `order_by`. Task 1 adds `order_desc` parameter only — minimal change.
- `sn_client.get_records()` already handles retry via `_fetch_with_retry()`, error normalization, field selection, and display_value. Task 2 replaces raw HTTP calls with this.
- `resolve_delta_decision()` in `integration_sync_runner.py` is untouched — bail-out logic sits *above* it in the executor layer.

### Key Concerns
1. **File overlap prevention**: Task 1 owns `sn_client.py`, Task 2 owns `scan_executor.py` + `sn_dictionary.py`, Task 3 owns `data_pull_executor.py`. No file is touched by two tasks. `models.py` and `integration_properties.py` are owned by Task 1 — Task 3 reads from them but does not modify them.
2. **Dependency chain**: Task 3 depends on Task 1 (needs new DB columns + properties to exist). Tasks 1 and 2 are fully independent. Plan: start Tasks 1 & 2 in parallel; Task 3 starts after Task 1 merges.
3. **Inclusive/exclusive normalization**: The audit recommends Option A (use `>=` everywhere). The fix in `server.py` (Task 2) makes plan probes consistent with executor probes. Since we are normalizing to `>=`, the change is to keep the default (already `>=`) and remove the `inclusive=False` override in `data_pull_executor.py` (Task 3 scope).
4. **CSDM ingestion is OUT OF SCOPE**: The audit marks csdm_ingestion.py consolidation as "lower priority, intentionally isolated." We exclude it from this sprint to keep scope tight.
5. **Existing test count**: 496 passing. All tasks must maintain this baseline. No existing test may be deleted — only added or adapted.

### Refactor Debt Acknowledged
- `csdm_ingestion.py` still has its own `build_delta_query()` and `fetch_batch_with_retry()` — logged as future consolidation work.
- `scan_executor._iterate_batches()` had no inter-batch delay or max_batches — test coverage for these edge cases did not exist. New tests must cover these paths.
- Dictionary operations (`sn_dictionary.py`) had zero logging. After Task 2, they gain retry and error normalization through `get_records()`, but dedicated dictionary call logging remains a gap (Tier 3 from audit).

---

### Task 1: Core Infrastructure — DESC Ordering + Properties + DB Columns

**Assigned:** Dev-1 | **Status:** Pending
**Worktree:** .worktrees/dev_1 | **Branch:** dev_1/sn-api-core-infra
**Stream:** orchestration_run/logs/dev_1_stream.jsonl
**Cross-tester:** Dev-2
**Files owned:**
1. `tech-assessment-hub/src/services/sn_client.py` — add `order_desc` param to `_iterate_batches()`
2. `tech-assessment-hub/src/services/integration_properties.py` — add 3 new PropertyDef entries
3. `tech-assessment-hub/src/models.py` — add 6 new `InstanceDataPull` columns
4. `tech-assessment-hub/tests/test_sn_client_desc_ordering.py` — NEW test file for DESC ordering
5. `tech-assessment-hub/tests/test_integration_properties.py` — extend existing tests for new properties

**Test command:** `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short -x`

**Done criteria:**
1. `_iterate_batches()` accepts `order_desc: bool = False` parameter. When `True`, appends `ORDERBYDESC{order_by}` instead of `ORDERBY{order_by}` to the effective query. When query already contains the appropriate ORDER clause, it is not duplicated.
2. Three new `PropertyDef` entries exist in `PROPERTY_DEFINITIONS`:
   - `integration.pull.order_desc` (select: "true"/"false", default "true", section SECTION_FETCH)
   - `integration.pull.max_records` (int, default "5000", section SECTION_FETCH)
   - `integration.pull.bail_unchanged_run` (int, default "50", section SECTION_FETCH)
3. Three corresponding `load_*` helper functions exist and are importable:
   - `load_pull_order_desc(session) -> bool`
   - `load_pull_max_records(session) -> int`
   - `load_pull_bail_unchanged_run(session) -> int`
4. Six new `Optional` columns on `InstanceDataPull` (all default `None`):
   - `local_count_pre_pull: Optional[int]`
   - `remote_count_at_probe: Optional[int]`
   - `delta_probe_count: Optional[int]`
   - `bail_out_reason: Optional[str]`
   - `bail_unchanged_at_exit: Optional[int]`
   - `local_count_post_pull: Optional[int]`
5. All 496+ existing tests pass. At least 6 new tests:
   - `_iterate_batches` with `order_desc=True` appends `ORDERBYDESC`
   - `_iterate_batches` with `order_desc=False` (default) appends `ORDERBY` (existing behavior preserved)
   - `_iterate_batches` with `order_desc=True` when query already contains ORDER clause does not duplicate
   - `load_pull_order_desc()` returns `True` by default
   - `load_pull_max_records()` returns `5000` by default
   - `load_pull_bail_unchanged_run()` returns `50` by default
   - `InstanceDataPull` new columns default to `None` and accept values

#### Dev-1 Notes:
<!-- Dev-1 writes status updates here during build phase -->

#### Reviewer Findings:
<!-- Code reviewer writes findings here — read-only otherwise -->

#### Cross-Test Thread (Dev-1 ↔ Dev-2):
<!-- CONVERSATION. Both parties write here. Back and forth until agreed. -->

#### Sign-offs:
- [ ] Dev-1 (author) — implementation complete, tests pass
- [ ] Dev-2 (cross-tester) — tested, verified, agreed
- [ ] Reviewer — code quality approved

---

### Task 2: Consolidation — scan_executor + sn_dictionary + Server Preflight Fix

**Assigned:** Dev-2 | **Status:** Pending
**Worktree:** .worktrees/dev_2 | **Branch:** dev_2/sn-api-consolidation
**Stream:** orchestration_run/logs/dev_2_stream.jsonl
**Cross-tester:** Dev-3
**Files owned:**
1. `tech-assessment-hub/src/services/scan_executor.py` — replace `_apply_since_filter()` and `_iterate_batches()` with shared sn_client equivalents
2. `tech-assessment-hub/src/services/sn_dictionary.py` — replace 3 `session.get()` bypasses with `client.get_records()`
3. `tech-assessment-hub/src/server.py` — fix inclusive/exclusive inconsistency in preflight plan probe (~line 7043)
4. `tech-assessment-hub/tests/test_scan_executor_consolidation.py` — NEW test file
5. `tech-assessment-hub/tests/test_sn_dictionary_consolidation.py` — NEW test file

**Test command:** `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short -x`

**Done criteria:**
1. `scan_executor._apply_since_filter()` function DELETED. Both call sites (metadata scan at ~line 718, update_xml scan at ~line 903) replaced with `client._watermark_filter(since, inclusive=True)` + string concatenation pattern.
2. `scan_executor._iterate_batches()` function DELETED. Both call sites replaced with `client._iterate_batches(table=..., query=..., fields=...)`. Scans now inherit all shared infrastructure: configurable batch size, inter_batch_delay, max_batches safety cap, retry logic, ORDERBY safeguard.
3. `sn_dictionary.validate_table_exists()` (~line 79): `client.session.get()` replaced with `client.get_records(table="sys_db_object", query=f"name={table_name}", fields=[...], limit=1)`. Return value parsing adapted to match existing callers.
4. `sn_dictionary._resolve_table_name_by_sys_id()` (~line 127): `client.session.get()` replaced with `client.get_records(table="sys_db_object", query=f"sys_id={sys_id}", fields=["name"], limit=1)`. 404 handling preserved.
5. `sn_dictionary._fetch_fields_for_table()` (~line 217): `client.session.get()` replaced with `client.get_records(table="sys_dictionary", query=..., fields=[...], limit=500)`. Manual since-filter building replaced with `client._watermark_filter()`.
6. `server.py` preflight plan probe at ~line 7043: Add `inclusive=False` to the `_estimate_expected_total()` call so plan probes match executor probes (both use `>` exclusive for delta probes). **Note**: This is the conservative fix per audit section 6.4 Option B for probes. The pull-side remains `>=` inclusive by default.
   - **ARCHITECT CLARIFICATION**: Re-reading the audit, Option A recommends `>=` everywhere (inclusive). Since the plan probe feeds `resolve_delta_decision()` which compares `delta_probe_count` to `local + probe`, slight overcounting is safe. The simplest fix that makes plan and executor consistent is: **remove `inclusive=False` from data_pull_executor line 299** (Task 3 scope, since that file is owned by Task 3). For Task 2, the server.py probe already defaults to `inclusive=True` which is correct under Option A. **No change needed in server.py for the inclusive/exclusive issue.** Task 2 only touches server.py if there is another bug there. Removing this from Task 2 scope.
   - **REVISED**: server.py is removed from Task 2 file ownership. The inclusive fix lives in Task 3 (data_pull_executor.py line 299: remove `inclusive=False`).
7. All 496+ existing tests pass. At least 8 new tests:
   - scan_executor: metadata scan path uses `client._iterate_batches()` (mock verifies call)
   - scan_executor: update_xml scan path uses `client._iterate_batches()` (mock verifies call)
   - scan_executor: since filter applied via `_watermark_filter()` (mock verifies inclusive=True)
   - scan_executor: `_apply_since_filter` and `_iterate_batches` no longer importable from module
   - sn_dictionary: `validate_table_exists()` calls `client.get_records()` not `session.get()`
   - sn_dictionary: `_resolve_table_name_by_sys_id()` calls `client.get_records()`, returns None on empty result
   - sn_dictionary: `_fetch_fields_for_table()` calls `client.get_records()`, since filter uses `_watermark_filter()`
   - sn_dictionary: all 3 functions gain retry logic (verify through `get_records` mock that `_fetch_with_retry` path is exercised)

**REVISED Files owned:**
1. `tech-assessment-hub/src/services/scan_executor.py`
2. `tech-assessment-hub/src/services/sn_dictionary.py`
3. `tech-assessment-hub/tests/test_scan_executor_consolidation.py` — NEW
4. `tech-assessment-hub/tests/test_sn_dictionary_consolidation.py` — NEW

#### Dev-2 Notes:
<!-- Dev-2 writes status updates here during build phase -->

#### Reviewer Findings:
<!-- Code reviewer writes findings here — read-only otherwise -->

#### Cross-Test Thread (Dev-2 ↔ Dev-3):
<!-- CONVERSATION. Both parties write here. Back and forth until agreed. -->

#### Sign-offs:
- [ ] Dev-2 (author) — implementation complete, tests pass
- [ ] Dev-3 (cross-tester) — tested, verified, agreed
- [ ] Reviewer — code quality approved

---

### Task 3: Bail-Out Logic — Upsert Change Detection + Dual-Signal Bail-Out

**Assigned:** Dev-3 | **Status:** Blocked (on Task 1)
**Worktree:** .worktrees/dev_3 | **Branch:** dev_3/sn-api-bailout
**Stream:** orchestration_run/logs/dev_3_stream.jsonl
**Cross-tester:** Dev-1
**DEPENDS ON:** Task 1 must merge first (needs new InstanceDataPull columns + new Integration Properties)
**Files owned:**
1. `tech-assessment-hub/src/services/data_pull_executor.py` — add bail-out logic to per-type handlers, populate new columns, wire DESC ordering, fix inclusive=False at line 299
2. `tech-assessment-hub/src/server.py` — fix inclusive/exclusive inconsistency at preflight probe (~line 7043, add `inclusive=False`) — **see architect note below**
3. `tech-assessment-hub/tests/test_data_pull_bailout.py` — NEW test file for bail-out logic
4. `tech-assessment-hub/tests/test_data_pull_desc_ordering.py` — NEW test file for DESC wiring

**Test command:** `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short -x`

**Architect implementation notes for Dev-3:**

**A. Inclusive/Exclusive Normalization (Audit Section 6.4, Option A)**
- In `data_pull_executor.py` line 299: REMOVE `inclusive=False` so the probe defaults to `inclusive=True` (`>=`). This makes the executor probe consistent with the plan probe in server.py (both now use `>=`).
- Rationale: `>=` slightly overcounts (safe — upsert deduplicates). `>` undercounts (risky — can miss records at timestamp boundaries).

**B. DESC Ordering Wiring**
- All 11 `pull_*()` call sites in `data_pull_executor.py` currently call `client.pull_*()` methods in `sn_client.py`. The `pull_*()` methods internally call `client._iterate_batches()`. To wire DESC ordering:
  - Option 1 (preferred): Modify each `pull_*()` method in `sn_client.py` to accept `order_desc` and pass it through to `_iterate_batches()`. But `sn_client.py` is owned by Task 1.
  - Option 2 (deferred): Since Task 1 adds `order_desc` to `_iterate_batches()` but does NOT wire it into `pull_*()` methods, Task 3 can wire it at the executor level by calling `client._iterate_batches()` directly instead of `pull_*()`. But this bypasses the query-builder layer.
  - **DECISION**: Task 1 should also add `order_desc` as a pass-through parameter to all 11 `pull_*()` methods (defaulting to `False` to preserve existing behavior). Task 3 then passes `order_desc=load_pull_order_desc(session)` at each call site. This keeps the clean abstraction.
  - **UPDATE FOR Task 1**: Dev-1 must add `order_desc: bool = False` parameter to all 11 `pull_*()` methods and pass it to `_iterate_batches()`. This is added to Task 1 done criteria.

**C. Upsert Change Detection**
- Each per-type handler in `data_pull_executor.py` has its own upsert logic (e.g., lines 484-560 for update_sets). The upsert loops must be modified to track whether each record actually changed.
- Pattern: Compare incoming record fields against existing DB row. If all fields match, return `changed=False`. If any field differs or record is new, return `changed=True`.
- The simplest approach: extract a helper `_upsert_record(session, model_class, record, key_fields) -> bool` that returns whether data changed. Apply to all 11 per-type handlers.
- **CAUTION**: Each handler has slightly different upsert logic (different key fields, different field mappings). The helper must be flexible enough to handle all 11 types, or each handler does its own change tracking with a simple `changed` boolean.

**D. Dual-Signal Bail-Out**
- After each batch is upserted, check two gates:
  1. **Count gate**: `current_local_count >= remote_count_at_probe`
  2. **Content gate**: `consecutive_unchanged >= bail_unchanged_run` (from property)
- Both must be true simultaneously for bail-out.
- Independent safety cap: `records_processed >= max_records` (from property) — fires regardless.
- When bail fires, set `pull_record.bail_out_reason` ("count_and_content" or "safety_cap").
- When bail fires, set `pull_record.bail_unchanged_at_exit` to current consecutive_unchanged count.
- Skip bail-out entirely when `local_count_pre_pull == 0` (first-time load — nothing to bail against).

**E. New Column Population**
- `local_count_pre_pull`: Set BEFORE pull starts, always (full/delta/smart).
- `remote_count_at_probe`: Always probe with `since=None` (unfiltered count). This is the bail-out "finish line."
- `delta_probe_count`: Set from the existing delta probe (now with `inclusive=True`).
- `bail_out_reason`: Set when bail fires (or stays None if pull completes normally).
- `bail_unchanged_at_exit`: Set when bail fires.
- `local_count_post_pull`: Set AFTER pull completes, always.

**F. server.py Preflight Probe**
- At ~line 7043: the `_estimate_expected_total()` call for `delta_probe_count` currently omits `inclusive` parameter, defaulting to `True` (`>=`). Under Option A normalization, this is now correct. **No change needed in server.py.** Remove server.py from Task 3 file ownership.

**REVISED Files owned:**
1. `tech-assessment-hub/src/services/data_pull_executor.py`
2. `tech-assessment-hub/tests/test_data_pull_bailout.py` — NEW
3. `tech-assessment-hub/tests/test_data_pull_desc_ordering.py` — NEW

**Done criteria:**
1. `inclusive=False` removed from `data_pull_executor.py` line 299. Delta probe now uses `>=` (inclusive), consistent with plan probe in server.py.
2. All 11 per-type handlers in `data_pull_executor.py` pass `order_desc=load_pull_order_desc(session)` to their respective `pull_*()` calls.
3. Upsert change detection implemented: each per-type handler tracks per-record `changed` boolean. A `consecutive_unchanged` counter resets on any `changed=True` and increments on `changed=False`.
4. Dual-signal bail-out implemented after each batch:
   - Count gate: `current_local_count >= pull_record.remote_count_at_probe`
   - Content gate: `consecutive_unchanged >= load_pull_bail_unchanged_run(session)`
   - Both must be true to bail.
   - Safety cap: `records_processed >= load_pull_max_records(session)` — independent.
   - Bail skipped entirely when `pull_record.local_count_pre_pull == 0`.
5. All 6 new `InstanceDataPull` columns populated correctly:
   - `local_count_pre_pull` set before pull starts (all modes)
   - `remote_count_at_probe` set from unfiltered probe (all modes)
   - `delta_probe_count` set from delta probe (delta/smart modes only)
   - `bail_out_reason` set on bail ("count_and_content" or "safety_cap") or stays None
   - `bail_unchanged_at_exit` set on bail or stays None
   - `local_count_post_pull` set after pull completes (all modes)
6. Watermark handling preserved: `max(sys_updated_on)` tracked across all batches, persisted to `pull_record.last_sys_updated_on` after loop. With DESC, this naturally comes from the first batch.
7. All 496+ existing tests pass. At least 10 new tests:
   - Bail-out fires when both count gate AND content gate are met
   - Bail-out does NOT fire when only count gate is met (content still changing)
   - Bail-out does NOT fire when only content gate is met (count not met)
   - Safety cap fires independently of count/content gates
   - Bail-out skipped when `local_count_pre_pull == 0`
   - `bail_out_reason` set correctly for count_and_content vs safety_cap
   - `consecutive_unchanged` resets on any changed record
   - `local_count_pre_pull` and `local_count_post_pull` populated on every pull
   - `remote_count_at_probe` populated from unfiltered probe
   - `order_desc` passed through to pull methods

#### Dev-3 Notes:
<!-- Dev-3 writes status updates here during build phase -->

#### Reviewer Findings:
<!-- Code reviewer writes findings here — read-only otherwise -->

#### Cross-Test Thread (Dev-3 ↔ Dev-1):
<!-- CONVERSATION. Both parties write here. Back and forth until agreed. -->

#### Sign-offs:
- [ ] Dev-3 (author) — implementation complete, tests pass
- [ ] Dev-1 (cross-tester) — tested, verified, agreed
- [ ] Reviewer — code quality approved

---

## UPDATED Task 1 Done Criteria Addendum

**Item 8 (added for Task 3 dependency):** All 11 `pull_*()` methods in `sn_client.py` accept an `order_desc: bool = False` parameter and pass it through to `_iterate_batches()`. Existing callers are unaffected (default is `False`). Methods affected:
- `pull_update_sets()`
- `pull_customer_update_xml()`
- `pull_version_history()`
- `pull_metadata_customizations()`
- `pull_app_file_types()`
- `pull_plugins()`
- `pull_plugin_view()`
- `pull_scopes()`
- `pull_packages()`
- `pull_applications()`
- `pull_sys_db_object()`

---

## Execution Order

```
Timeline:
  T+0h  ──► Task 1 (Dev-1) starts     Task 2 (Dev-2) starts
             │                           │
  T+3h  ──► Task 1 complete ──────────► Task 3 (Dev-3) starts
             │                           │
  T+4h  ──►                             Task 2 complete
             │                           │
  T+6h  ──►                             Task 3 complete
             │
  T+7h  ──► Cross-testing + review
```

Tasks 1 and 2 are fully independent and run in parallel. Task 3 is blocked on Task 1 only.

---

## Architect Feedback
<!-- Architect posts lessons-learned after reviewing findings.md -->

## PM Feedback
<!-- PM posts process notes and backlog updates after reviewing findings.md -->
