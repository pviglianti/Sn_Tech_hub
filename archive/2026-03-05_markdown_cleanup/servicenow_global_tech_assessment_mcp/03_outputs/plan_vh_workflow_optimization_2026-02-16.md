# VH Workflow Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Optimize the assessment workflow by fixing the delta watermark operator, fixing VH catchup re-pull bug, separating classification from scans, adding proactive VH pulls, per-item progress/ETA, and configurable concurrent preflight types.

**Architecture:** 6 items implemented in priority order. Item 6 (delta watermark) is a foundation fix touching `sn_client.py`, `csdm_ingestion.py`, `sn_dictionary.py`. Items 1+3 restructure the VH/classification pipeline. Item 2 adds threading infrastructure. Items 4+5 are independent UI/config.

**Tech Stack:** Python 3 / FastAPI / SQLModel / SQLite WAL / Jinja2 / vanilla JS

**Design doc:** `servicenow_global_tech_assessment_mcp/02_working/01_notes/asmt_flow.md`

**Test runner:** `./venv/bin/python -m pytest tests/ -v` from `tech-assessment-hub/`

---

## Task 1: Delta Watermark Helper — Failing Tests

**Files:**
- Create: `tests/test_sn_client_watermark.py`
- Modify (later): `src/services/sn_client.py:277` (after `_build_query`)

**Step 1: Write failing tests for `_watermark_filter` helper**

```python
# tests/test_sn_client_watermark.py
from datetime import datetime
from src.services.sn_client import ServiceNowClient


def _make_client():
    return ServiceNowClient("https://example.service-now.com", "admin", "password")


def test_watermark_filter_inclusive_uses_gte():
    client = _make_client()
    result = client._watermark_filter(datetime(2026, 2, 13, 9, 0, 0), inclusive=True)
    assert result == "sys_updated_on>=2026-02-13 09:00:00"


def test_watermark_filter_exclusive_uses_gt():
    client = _make_client()
    result = client._watermark_filter(datetime(2026, 2, 13, 9, 0, 0), inclusive=False)
    assert result == "sys_updated_on>2026-02-13 09:00:00"


def test_watermark_filter_defaults_to_inclusive():
    client = _make_client()
    result = client._watermark_filter(datetime(2026, 2, 13, 9, 0, 0))
    assert ">=" in result
```

**Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_sn_client_watermark.py -v`
Expected: FAIL with `AttributeError: 'ServiceNowClient' object has no attribute '_watermark_filter'`

---

## Task 2: Delta Watermark Helper — Implementation

**Files:**
- Modify: `src/services/sn_client.py:277-279` (add method after `_build_query`)

**Step 3: Add `_watermark_filter` method to `ServiceNowClient`**

Insert after the `_build_query` method (line 279):

```python
def _watermark_filter(self, since: datetime, inclusive: bool = True) -> str:
    """Build sys_updated_on filter for delta queries.

    Args:
        since: Watermark datetime.
        inclusive: True for data pulls (>=), False for probes (>).
    """
    ts = since.strftime('%Y-%m-%d %H:%M:%S')
    op = ">=" if inclusive else ">"
    return f"sys_updated_on{op}{ts}"
```

**Step 4: Run tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_sn_client_watermark.py -v`
Expected: 3 PASS

---

## Task 3: Refactor `build_*_query` Methods — Tests

**Files:**
- Modify: `tests/test_sn_client_watermark.py` (add tests)

**Step 5: Add tests verifying `build_*_query` methods use `>=` by default**

Append to `tests/test_sn_client_watermark.py`:

```python
def test_build_update_set_query_uses_gte_for_delta():
    client = _make_client()
    query = client.build_update_set_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_version_history_query_uses_gte_for_delta():
    client = _make_client()
    query = client.build_version_history_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_customer_update_xml_query_uses_gte_for_delta():
    client = _make_client()
    query = client.build_customer_update_xml_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_metadata_customization_queries_uses_gte_for_delta():
    client = _make_client()
    queries = client.build_metadata_customization_queries(since=datetime(2026, 2, 13, 9, 0, 0))
    assert any("sys_updated_on>=2026-02-13 09:00:00" in q for q in queries)


def test_build_app_file_types_query_uses_gte():
    client = _make_client()
    query = client.build_app_file_types_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_plugins_query_uses_gte():
    client = _make_client()
    query = client.build_plugins_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_scopes_query_uses_gte():
    client = _make_client()
    query = client.build_scopes_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_packages_query_uses_gte():
    client = _make_client()
    query = client.build_packages_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_applications_query_uses_gte():
    client = _make_client()
    query = client.build_applications_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_sys_db_object_query_uses_gte():
    client = _make_client()
    query = client.build_sys_db_object_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_plugin_view_query_uses_gte():
    client = _make_client()
    query = client.build_plugin_view_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_update_set_query_probe_uses_gt():
    """When inclusive=False (for probes), should use > not >=."""
    client = _make_client()
    query = client.build_update_set_query(since=datetime(2026, 2, 13, 9, 0, 0), inclusive=False)
    assert "sys_updated_on>2026-02-13 09:00:00" in query
    assert ">=" not in query
```

**Step 6: Run to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_sn_client_watermark.py -v`
Expected: 12 new tests FAIL (still using `>` not `>=`, and `inclusive` param doesn't exist yet)

---

## Task 4: Refactor `build_*_query` Methods — Implementation

**Files:**
- Modify: `src/services/sn_client.py` — all 11 `build_*_query` methods (lines 281-446)

**Step 7: Refactor all `build_*_query` methods**

For each of these 11 methods, make two changes:
1. Add `inclusive: bool = True` parameter
2. Replace `f"sys_updated_on>{since.strftime(...)}"` with `self._watermark_filter(since, inclusive=inclusive)`

Example for `build_update_set_query` (line 281):

```python
def build_update_set_query(
    self,
    since: Optional[datetime] = None,
    scope_filter: Optional[str] = None,
    inclusive: bool = True,
) -> str:
    query_parts = []
    if since:
        query_parts.append(self._watermark_filter(since, inclusive=inclusive))
    # ... rest unchanged ...
```

Apply the same pattern to all 11 methods:
- `build_update_set_query` (line 281) — add `inclusive: bool = True`
- `build_customer_update_xml_query` (line 303) — add `inclusive: bool = True`
- `build_version_history_query` (line 309) — add `inclusive: bool = True`
- `build_metadata_customization_queries` (line 329) — add `inclusive: bool = True`
- `build_metadata_customization_query` (line 321) — pass through to `queries` call
- `build_app_file_types_query` (line 393) — add `inclusive: bool = True`
- `build_plugins_query` (line 399) — add `inclusive: bool = True`
- `build_scopes_query` (line 407) — add `inclusive: bool = True`
- `build_packages_query` (line 415) — add `inclusive: bool = True`
- `build_applications_query` (line 422) — add `inclusive: bool = True`
- `build_sys_db_object_query` (line 434) — add `inclusive: bool = True`
- `build_plugin_view_query` (line 440) — add `inclusive: bool = True`

Also update `get_metadata_customization_count` (line 264) to pass through `inclusive`:

```python
def get_metadata_customization_count(
    self,
    since: Optional[datetime] = None,
    class_names: Optional[List[str]] = None,
    inclusive: bool = True,
) -> int:
    total = 0
    for query in self.build_metadata_customization_queries(
        since=since,
        class_names=class_names,
        inclusive=inclusive,
    ):
        total += self.get_record_count("sys_metadata_customization", query)
    return total
```

**Step 8: Run watermark tests**

Run: `./venv/bin/python -m pytest tests/test_sn_client_watermark.py -v`
Expected: ALL PASS (15 tests)

**Step 9: Run full test suite to verify no regressions**

Run: `./venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS. The existing `test_sn_client_delta_keyset.py:33` asserts `"sys_updated_on>2026-02-13 09:00:00"` — this test will need updating in Task 5.

---

## Task 5: Refactor `iterate_delta_keyset` Initial Watermark

**Files:**
- Modify: `src/services/sn_client.py:1021-1022` (initial watermark in keyset iterator)
- Modify: `tests/test_sn_client_delta_keyset.py:33` (update assertion)

**Step 10: Update `iterate_delta_keyset` initial watermark to use `>=`**

In `iterate_delta_keyset` (line 1021-1022), change:

```python
# Before:
elif watermark_str:
    query_parts.append(f"sys_updated_on>{watermark_str}")

# After:
elif watermark_str:
    query_parts.append(f"sys_updated_on>={watermark_str}")
```

Note: The cursor-based filter on line 1019 (`sys_updated_on>{cursor}^ORsys_updated_on={cursor}^sys_id>{sys_id}`) stays as-is — it already handles timestamp ties via `sys_id` tiebreaker.

**Step 11: Update keyset test assertion**

In `tests/test_sn_client_delta_keyset.py` line 33, change:

```python
# Before:
assert "sys_updated_on>2026-02-13 09:00:00" in queries[0]

# After:
assert "sys_updated_on>=2026-02-13 09:00:00" in queries[0]
```

**Step 12: Run keyset tests**

Run: `./venv/bin/python -m pytest tests/test_sn_client_delta_keyset.py tests/test_sn_client_watermark.py -v`
Expected: ALL PASS

---

## Task 6: Refactor `csdm_ingestion.py` and `sn_dictionary.py`

**Files:**
- Modify: `src/services/csdm_ingestion.py:523`
- Modify: `src/services/sn_dictionary.py:207`

**Step 13: Update `csdm_ingestion.py` `build_delta_query`**

```python
# Before (line 523):
return f"sys_updated_on>{last_updated_on_str}^ORDERBYsys_updated_on"

# After:
return f"sys_updated_on>={last_updated_on_str}^ORDERBYsys_updated_on"
```

**Step 14: Update `sn_dictionary.py` dictionary delta**

```python
# Before (line 207):
query_parts.append(f"sys_updated_on>{since_str}")

# After:
query_parts.append(f"sys_updated_on>={since_str}")
```

**Step 15: Run full test suite**

Run: `./venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

---

## Task 7: Wire Probe Path to Use `inclusive=False`

**Files:**
- Modify: `src/services/data_pull_executor.py:227-271` (`_estimate_expected_total`)

**Step 16: Add `inclusive` parameter to `_estimate_expected_total`**

```python
def _estimate_expected_total(
    session: Session,
    client: ServiceNowClient,
    data_type: DataPullType,
    since: Optional[datetime],
    instance_id: Optional[int] = None,
    inclusive: bool = True,
) -> Optional[int]:
```

Then update every `build_*_query` call inside to pass `inclusive=inclusive`:

```python
# Example for update_sets:
query = client.build_update_set_query(since=since, inclusive=inclusive)

# Example for customer_update_xml:
query = client.build_customer_update_xml_query(since=since, inclusive=inclusive)

# Example for version_history:
query = client.build_version_history_query(since=since, inclusive=inclusive)

# Example for metadata_customization:
return client.get_metadata_customization_count(since=since, class_names=class_names, inclusive=inclusive)

# ... same for all other types
```

**Step 17: Update `_resolve_delta_pull_mode` to pass `inclusive=False` for probe**

In `_resolve_delta_pull_mode` (line 274), the probe call (line 291) should use `inclusive=False`:

```python
# remote_total (total count, no watermark) — inclusive doesn't matter since since=None
remote_total = _estimate_expected_total(
    session, client, data_type, since=None, instance_id=instance_id,
)
# delta_probe (count since watermark) — use > (exclusive) for conservative count
delta_probe_count = _estimate_expected_total(
    session, client, data_type, since=watermark, instance_id=instance_id,
    inclusive=False,
)
```

**Step 18: Run full test suite**

Run: `./venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS

**Step 19: Commit**

```bash
git add tests/test_sn_client_watermark.py \
  src/services/sn_client.py \
  src/services/csdm_ingestion.py \
  src/services/sn_dictionary.py \
  src/services/data_pull_executor.py \
  tests/test_sn_client_delta_keyset.py
git commit -m "fix: delta watermark operator > to >= for data pulls, > for probes

Centralizes watermark filter in _watermark_filter() helper on ServiceNowClient.
Data pulls use >= to prevent missed records on interrupted mid-batch pulls
where multiple records share the same sys_updated_on timestamp.
Probes keep > for conservative counting (biases toward full refresh).
Upsert logic + unique indexes prevent duplicates from overlap.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Task 8–13: Item 1 — VH Catchup Fix (outline)

> Detail these tasks when starting Item 1 implementation.

**Task 8:** Add `state_filter_applied` field to `InstanceDataPull` model (`models.py:1003`). Optional[str], default None.

**Task 9:** Record the state filter in `data_pull_executor.py` when `version_state_filter` is used during VH pulls.

**Task 10:** Update `_run_assessment_version_history_postscan_catchup` in `server.py` to check `state_filter_applied` on the existing VH pull record and use `state!=current` filter or delta-from-watermark instead of full re-pull.

**Task 11:** Write tests for the VH catchup fix — unit test `resolve_delta_decision` with filter context, test that catchup uses delta when `state_filter_applied="current"`.

**Task 12:** Run full test suite, verify no regressions.

**Task 13:** Commit Item 1.

---

## Task 14–20: Item 3 — Separated Classification (outline)

> Detail these tasks when starting Item 3 implementation.

**Task 14:** Add `skip_classification: bool = False` parameter to `_process_and_classify_records` in `scan_executor.py`. When True, set `origin_type="pending_classification"` instead of running classification.

**Task 15:** Extract classification logic from `_process_and_classify_records` into standalone `classify_scan_results(session, assessment_id)` function in `scan_executor.py`.

**Task 16:** Add new Stage 6 `_classify_assessment_results()` in `server.py` that calls `classify_scan_results`. Wire into `_run_scans_background` after VH wait.

**Task 17:** Update `_run_scans_background` Stage 3 to pass `skip_classification=True`.

**Task 18:** Write tests for separated classification (pending_classification sentinel, classify_scan_results with full VH data).

**Task 19:** Run full test suite, verify no regressions.

**Task 20:** Commit Item 3.

---

## Task 21–28: Item 2 — Proactive VH Pull + Event Signaling (outline)

> Detail these tasks when starting Item 2 implementation.

**Task 21:** Create `_start_proactive_vh_pull(instance_id)` in `server.py` — spawns background thread with own `Session(engine)` + `ServiceNowClient`, tracks via `InstanceDataPull`.

**Task 22:** Create `_vh_event_registry` (dict of `instance_id → threading.Event`) for cross-thread completion signaling.

**Task 23:** Wire proactive trigger into instance creation/test endpoints (after successful connection test).

**Task 24:** Update `_run_assessment_preflight_data_sync` to detect running VH pull and join via event instead of starting a new one.

**Task 25:** Add Stage 5 wait logic in `_run_scans_background` — `vh_complete_event.wait(timeout=3600)` with configurable timeout.

**Task 26:** Add VH timeout handling — assessment warning state, re-initiation action (hidden unless timeout occurred).

**Task 27:** Write integration tests for proactive VH pull lifecycle.

**Task 28:** Commit Item 2.

---

## Task 29–33: Item 4 — Per-Item Progress + ETA (outline)

> Detail these tasks when starting Item 4 implementation.

**Task 29:** Add `started_at` to `_assessment_data_sync_summary` detail rows in `server.py`.

**Task 30:** Update `applyPreflightStatus` in `assessment_detail.html` to render `(pulled / expected)` counts per item.

**Task 31:** Add `_calculateETA(startedAt, pulled, expected)` JS helper. Render per-item ETA next to running items. Aggregate overall ETA in progress bar.

**Task 32:** Add minor CSS for ETA text (muted, smaller font) in `style.css`.

**Task 33:** Commit Item 4.

---

## Task 34–38: Item 5 — Configuration (outline)

> Detail these tasks when starting Item 5 implementation.

**Task 34:** Add `multiselect` value type to `IntegrationPropertyDefinition` with `max_selections` field in `integration_properties.py`.

**Task 35:** Add `preflight.concurrent_types` property definition with "Preflight" section, slush bucket widget, max 5 selections.

**Task 36:** Implement dual-list collector widget in `integration_properties.js` for `value_type === "multiselect"`.

**Task 37:** Wire `_run_assessment_preflight_data_sync` to read concurrent types from config.

**Task 38:** Commit Item 5.

---

## Dependency Map

```
Item 6 (watermark fix) ─── standalone, do first
Item 1 (VH catchup)    ─── depends on Item 6 (uses fixed watermark)
Item 3 (classification) ── tightly coupled with Item 1
Item 2 (proactive VH)  ─── depends on Items 1+3 (uses new VH pipeline)
Item 4 (progress/ETA)  ─── independent, can parallel with Item 2
Item 5 (configuration) ─── independent, can parallel with Item 2
```
