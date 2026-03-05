# ServiceNow API Call Architecture — Centralization Audit

**Date**: 2026-03-05
**Status**: Research complete, pending implementation
**Scope**: All outbound ServiceNow REST API calls across tech-assessment-hub

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [How the Centralized Solution Works Today](#2-how-the-centralized-solution-works-today)
3. [Detailed Call Inventory](#3-detailed-call-inventory)
4. [Centralization Scorecard](#4-centralization-scorecard)
5. [What Needs to Change](#5-what-needs-to-change)
6. [The Inclusive/Exclusive Issue](#6-the-inclusiveexclusive-issue)
7. [Risk Assessment](#7-risk-assessment)
8. [UI Trigger → SN API Call Mapping](#8-ui-trigger--sn-api-call-mapping)
9. [Probe/Count Logging Gap Analysis](#9-probecount-logging-gap-analysis)
10. [Delta Ordering Optimization](#10-delta-ordering-optimization)

---

## 1. Executive Summary

**28+ outbound SN API call paths exist across the app.**

| Area | Status | Call Paths | Issues |
|------|--------|------------|--------|
| Delta decision logic | Centralized | 1 shared function | 0 |
| Query builders (per table) | Centralized | 11 in sn_client | 0 |
| Data pull methods | Centralized | 11 pull_*() in sn_client | 0 |
| Watermark/since filter | **3 duplicates** | 4 total implementations | Inconsistent >= vs > |
| Batch iteration + retry | **2 duplicates** | 3 total implementations | Missing retry/config in dupes |
| Direct HTTP bypasses | **3 bypasses** | sn_dictionary.py | No retry, no error normalization |

**data_pull_executor.py** is the gold standard — fully compliant, uses all shared infrastructure.
**scan_executor.py**, **csdm_ingestion.py**, and **sn_dictionary.py** have custom implementations that should be consolidated.

---

## 2. How the Centralized Solution Works Today

All shared SN API infrastructure lives in `src/services/sn_client.py` with delta decision logic in `src/services/integration_sync_runner.py`.

### 2.1 Core API Methods

**`get_records(table, query, fields, limit, offset, order_by, display_value)`** — Line 466
- The single abstraction for `GET /api/now/table/{table}`
- Handles parameter construction, response parsing, error normalization
- All outbound data calls should flow through this

**`get_record_count(table, query)`** — Line 236
- Count-only variant, reads `X-Total-Count` header
- Used by all probe/estimate operations

### 2.2 Retry & Batch Infrastructure

**`_fetch_with_retry(table, query, fields, batch_size, offset, order_by)`** — Line 863
- Wraps `get_records()` with retry/backoff for transient errors
- Retry count and delays from `sn_fetch_config.py` (Integration Properties)
- Non-transient errors (auth, ACL, 404) re-raised immediately

**`_iterate_batches(table, query, fields, batch_size, order_by, inter_batch_delay, max_batches)`** — Line 913
- Generator yielding record batches using offset pagination
- Calls `_fetch_with_retry()` for each batch
- **Configurable via Integration Properties**:
  - `batch_size` → `integration.fetch.default_batch_size` (default: 200)
  - `inter_batch_delay` → `integration.fetch.inter_batch_delay` (default: 0.5s)
  - `max_batches` → `integration.fetch.max_batches` (default: 5000)
- Appends `ORDERBY{order_by}` safeguard to query
- Breaks on empty batch or final batch < batch_size

### 2.3 Watermark Filter

**`_watermark_filter(since, inclusive=True)`** — Line 283
```python
def _watermark_filter(self, since: datetime, inclusive: bool = True) -> str:
    ts = since.strftime('%Y-%m-%d %H:%M:%S')
    op = ">=" if inclusive else ">"
    return f"sys_updated_on{op}{ts}"
```

**Contract**:
- `inclusive=True` (>=) for **data pulls** — include boundary records
- `inclusive=False` (>) for **probes** — count what changed after watermark

### 2.4 Query Builders

11 query builders, all following the same pattern:

| Method | Line | Table | Extra Filters |
|--------|------|-------|---------------|
| `build_update_set_query()` | 294 | sys_update_set | scope_filter (global/scoped) |
| `build_customer_update_xml_query()` | 317 | sys_update_xml | — |
| `build_version_history_query()` | 323 | sys_update_version | state_filter |
| `build_metadata_customization_query()` | 336 | sys_metadata_customization | class_names (chunked) |
| `build_app_file_types_query()` | 410 | sys_app_file_type | — |
| `build_plugins_query()` | 416 | sys_plugins | active_only |
| `build_plugin_view_query()` | 458 | v_plugin | active_only |
| `build_scopes_query()` | 424 | sys_scope | active_only |
| `build_packages_query()` | 432 | sys_package | — |
| `build_applications_query()` | 439 | sys_app | active_only |
| `build_sys_db_object_query()` | 452 | sys_db_object | — |

**Pattern**: All accept `since` and `inclusive` params, call `_watermark_filter()` internally, return encoded query string.

### 2.5 Pull Methods

11 pull methods, all following the same pattern:

| Method | Line | Table | Notes |
|--------|------|-------|-------|
| `pull_update_sets()` | 1091 | sys_update_set | scope_filter support |
| `pull_customer_update_xml()` | 1121 | sys_update_xml | include_payload option |
| `pull_version_history()` | 1160 | sys_update_version | state_filter, custom order_by |
| `pull_metadata_customizations()` | 1196 | sys_metadata_customization | multi-query chunking |
| `pull_app_file_types()` | 1224 | sys_app_file_type | — |
| `pull_plugins()` | 1252 | sys_plugins | active_only |
| `pull_scopes()` | 1283 | sys_scope | active_only |
| `pull_packages()` | 1314 | sys_package | — |
| `pull_applications()` | 1347 | sys_app | active_only |
| `pull_sys_db_object()` | 1376 | sys_db_object | — |
| `pull_plugin_view()` | 1402 | v_plugin | active_only |

**Pattern**: Build query via `build_*_query(since=since)` (inclusive=True default), yield batches via `_iterate_batches()`.

### 2.6 Delta Decision Logic

**`resolve_delta_decision()`** — `integration_sync_runner.py` line 33

Single decision point for ALL integrations. Used by data_pull_executor, csdm_ingestion, server.py preflight plan.

**Decision flow**:
1. No watermark → **full** (no sync history)
2. Local count = 0 → **full** (data was cleared)
3. Probe > 0 AND `local + probe < remote` → **full** (delta won't close gap)
4. Probe > 0 AND `local + probe >= remote` → **delta** (delta covers everything)
5. Probe = 0 AND counts mismatch → **full** (missing data, no recent changes)
6. Probe = 0 AND counts match → **skip** (nothing changed)
7. Probe unavailable → **delta** (trust watermark)

---

## 3. Detailed Call Inventory

### 3.1 data_pull_executor.py — FULLY COMPLIANT (Gold Standard)

All 11 data types use the shared stack end-to-end.

**Probe calls** (count estimates via `_estimate_expected_total()`):

| Line | Data Type | Builder | Table | inclusive |
|------|-----------|---------|-------|-----------|
| 238 | update_sets | `build_update_set_query()` | sys_update_set | param (configurable) |
| 241 | customer_update_xml | `build_customer_update_xml_query()` | sys_update_xml | param |
| 244 | version_history | `build_version_history_query()` | sys_update_version | param |
| 248 | metadata_customization | `get_metadata_customization_count()` | sys_metadata_customization | param |
| 250 | app_file_types | `build_app_file_types_query()` | sys_app_file_type | param |
| 252 | plugins | `build_plugins_query()` | sys_plugins | param |
| 255 | plugin_view | `build_plugin_view_query()` | v_plugin | param |
| 258 | scopes | `build_scopes_query()` | sys_scope | param |
| 261 | packages | `build_packages_query()` | sys_package | param |
| 264 | applications | `build_applications_query()` | sys_app | param |
| 268 | sys_db_object | `build_sys_db_object_query()` | sys_db_object | param |

**Delta probe invocation** (line 293-300):
```python
delta_probe_count = _estimate_expected_total(
    session, client, data_type,
    since=watermark, instance_id=instance_id,
    inclusive=False,  # Uses > (exclusive) for probes
)
```

**Data pull calls** (actual record fetch via `pull_*()` methods):

| Line | Data Type | Pull Method | inclusive |
|------|-----------|-------------|-----------|
| 484 | update_sets | `pull_update_sets(since=since)` | True (default) |
| 570 | customer_update_xml | `pull_customer_update_xml(since=since)` | True (default) |
| 696 | version_history | `pull_version_history(since=since, state_filter=...)` | True (default) |
| 792 | metadata_customization | `pull_metadata_customizations(since=since, class_names=...)` | True (default) |
| 865 | app_file_types | `pull_app_file_types(since=since)` | True (default) |
| 972 | plugins | `pull_plugins(since=since)` | True (default) |
| 1050 | plugin_view | `pull_plugin_view(since=since)` | True (default) |
| 1122 | scopes | `pull_scopes(since=since)` | True (default) |
| 1207 | packages | `pull_packages(since=since)` | True (default) |
| 1290 | applications | `pull_applications(since=since)` | True (default) |
| 1367 | sys_db_object | `pull_sys_db_object(since=since)` | True (default) |

**Status**: No changes needed.

---

### 3.2 scan_executor.py — CUSTOM IMPLEMENTATIONS (Needs Consolidation)

**Problem 1: Custom since filter** — `_apply_since_filter()` at line 543
```python
def _apply_since_filter(query, since, field="sys_updated_on"):
    if not since:
        return query
    stamp = since.strftime("%Y-%m-%d %H:%M:%S")
    if query:
        return f"{query}^{field}>={stamp}"
    return f"{field}>={stamp}"
```
- Duplicates `sn_client._watermark_filter()`
- Hardcoded `>=` only — no inclusive parameter
- Called at lines 718 and 903

**Problem 2: Custom batch iterator** — `_iterate_batches()` at line 552
```python
def _iterate_batches(client, table, query, fields, limit=1000, display_value=False):
    offset = 0
    while True:
        batch = client.get_records(table, query, fields, limit, offset, ...)
        if not batch:
            break
        yield batch
        if len(batch) < limit:
            break
        offset += limit
```
- Hardcoded `limit=1000` (not from Integration Properties)
- No inter_batch_delay (hammers SN instance)
- No max_batches safety cap
- No retry logic (calls `get_records()` directly, not `_fetch_with_retry()`)
- No ORDERBY safeguard
- Called at lines 723 and 905

**Problem 3: Per-record live lookups** (correct usage, no changes needed):

| Line | Function | Table | Method | Notes |
|------|----------|-------|--------|-------|
| 145 | `_lookup_version_history()` | sys_update_version | `get_records()` | Single record lookup, OK |
| 214 | `_has_metadata_customization()` | sys_metadata_customization | `get_record_count()` | Probe, OK |
| 224 | `_version_history_count()` | sys_update_version | `get_record_count()` | Probe, OK |

**UI triggers**:
- "Run Assessment" button → `POST /assessments/{id}/run` (server.py ~line 6556)
- "Refresh Scans" button → `POST /assessments/{id}/refresh-scans` (server.py ~line 8666)
- "Refresh Scans (Delta)" button → `POST /assessments/{id}/refresh-scans-delta` (server.py ~line 8690)
- "Retry Scan" button → `POST /scans/{id}/retry` (server.py ~line 8888)
- Pipeline stage auto-advance after preflight
- HTML: `assessment_detail.html` scan action buttons

---

### 3.3 csdm_ingestion.py — SEMI-CUSTOM (Intentionally Isolated)

**Custom 1: Query builder** — `build_delta_query()` at line 514
```python
def build_delta_query(last_updated_on_str):
    if last_updated_on_str:
        return f"sys_updated_on>={last_updated_on_str}^ORDERBYsys_updated_on"
    return "ORDERBYsys_updated_on"
```
- Hardcoded `>=` (inclusive) — correct for data pull, but same query used for probes
- Custom string format, not using `_watermark_filter()`

**Custom 2: Batch fetcher** — `fetch_batch_with_retry()` at line 536
```python
def fetch_batch_with_retry(client, table_name, query, batch_size, offset, batch_num):
    for attempt in range(MAX_RETRIES):
        try:
            return client.get_records(table=table_name, query=query,
                                      limit=batch_size, offset=offset,
                                      order_by="sys_updated_on", display_value="false")
        except ServiceNowClientError:
            raise  # non-transient
        except Exception as exc:
            # retry with backoff...
```
- Duplicates `sn_client._fetch_with_retry()` logic
- Different retry constants (own MAX_RETRIES, RETRY_DELAYS)
- Called inside main `ingest_table()` loop

**Correct usage** (no changes needed):
- Line 703: `client.get_record_count(sn_table_name, delta_query)` — shared method

**UI triggers**:
- Data Browser "Sync" buttons → `POST /api/data-browser/{instance_id}/sync/{data_type}`
- CSDM admin panel → various `/admin/csdm/*` routes
- Background sync jobs

---

### 3.4 sn_dictionary.py — DIRECT HTTP BYPASSES (Critical)

Three functions bypass `get_records()` entirely with raw `client.session.get()` calls:

**Bypass 1** — `validate_table_exists()` at line 79
```python
url = client._build_url("table/sys_db_object")
params = {
    "sysparm_query": f"name={table_name}",
    "sysparm_limit": 1,
    "sysparm_fields": "sys_id,name,label,super_class,is_extendable,extension_model",
    "sysparm_display_value": "false",
}
response = client.session.get(url, params=params, timeout=client._cfg['request_timeout'])
data = client._handle_response(response)
```
- Queries: sys_db_object
- Missing: retry logic, error normalization consistency

**Bypass 2** — `_resolve_table_name_by_sys_id()` at line 127
```python
url = client._build_url(f"table/sys_db_object/{sys_id}")
params = {"sysparm_fields": "name"}
response = client.session.get(url, params=params, timeout=client._cfg['request_timeout'])
```
- Queries: sys_db_object (by sys_id endpoint)
- Missing: retry logic
- Note: Uses record-by-ID endpoint (`table/{table}/{sys_id}`)

**Bypass 3** — `_fetch_fields_for_table()` at line 217
```python
url = client._build_url("table/sys_dictionary")
params = {
    "sysparm_query": "^".join(query_parts),
    "sysparm_fields": "element,column_label,...",
    "sysparm_limit": 500,
    "sysparm_display_value": "false",
}
response = client.session.get(url, params=params, timeout=client._cfg['request_timeout'])
```
- Queries: sys_dictionary
- Missing: retry logic
- Supports since_date but builds filter manually (line ~207)

**UI triggers**:
- Dictionary pull orchestrator (background job during preflight/data browser)
- Data browser table validation
- MCP tool `query_instance_live` (indirect)

---

### 3.5 Other Modules — COMPLIANT (No Changes Needed)

| Module | Line | Function | Table | Method | Status |
|--------|------|----------|-------|--------|--------|
| artifact_detail_puller.py | 106 | `_batch_pull_class()` | Dynamic (by class) | `get_records()` | OK |
| contextual_lookup.py | 191 | `lookup_reference_remote()` | Dynamic (by ref) | `get_records()` | OK |
| dictionary_pull_orchestrator.py | 800 | `_batch_pull_sys_db_object()` | sys_db_object | `get_records()` | OK |
| mcp/tools/query_live.py | ~49 | `query_instance_live()` | Dynamic (user query) | `get_records()` | OK |
| mcp/tools/connection.py | — | connection test | — | `test_connection()` | OK |
| server.py | Multiple | Various endpoints | Various | Shared methods | OK |

---

## 4. Centralization Scorecard

### What's Already Centralized (No Work Needed)

| Component | Location | Used By |
|-----------|----------|---------|
| `resolve_delta_decision()` | integration_sync_runner.py:33 | data_pull_executor, csdm_ingestion, server.py preflight |
| 11 `build_*_query()` builders | sn_client.py:294-464 | data_pull_executor (all 11 types) |
| 11 `pull_*()` methods | sn_client.py:1091-1429 | data_pull_executor (all 11 types) |
| `_iterate_batches()` | sn_client.py:913-988 | All pull_* methods |
| `_fetch_with_retry()` | sn_client.py:863-907 | _iterate_batches |
| `_watermark_filter()` | sn_client.py:283-292 | All build_*_query methods |
| `get_records()` | sn_client.py:466-506 | All modules (except sn_dictionary bypasses) |
| `get_record_count()` | sn_client.py:236-261 | All modules |

### What Needs Consolidation

| Custom Implementation | Location | Duplicates | Priority |
|----------------------|----------|------------|----------|
| `_apply_since_filter()` | scan_executor.py:543 | `_watermark_filter()` | **High** |
| `_iterate_batches()` | scan_executor.py:552 | `sn_client._iterate_batches()` | **High** |
| `build_delta_query()` | csdm_ingestion.py:514 | `_watermark_filter()` | Medium |
| `fetch_batch_with_retry()` | csdm_ingestion.py:536 | `_fetch_with_retry()` | Medium |
| `session.get()` x3 | sn_dictionary.py:79,127,217 | `get_records()` | **High** |

---

## 5. What Needs to Change

### 5.1 scan_executor.py — Replace Custom Since Filter & Batch Iterator

#### Change A: Remove `_apply_since_filter()`, use `_watermark_filter()`

**Current** (line 718, and identically at line 903):
```python
query = _apply_since_filter(scan.encoded_query or "", since, "sys_updated_on")
```

**Target**:
```python
base_query = scan.encoded_query or ""
if since:
    wm = client._watermark_filter(since, inclusive=True)
    query = f"{base_query}^{wm}" if base_query else wm
else:
    query = base_query
```

Then **delete** the `_apply_since_filter()` function (lines 543-549).

#### Change B: Remove custom `_iterate_batches()`, use `client._iterate_batches()`

**Current** (lines 723, 905):
```python
for batch in _iterate_batches(client, table=..., query=query, fields=fields, limit=1000):
```

**Target**:
```python
for batch in client._iterate_batches(table=..., query=query, fields=fields):
```

Then **delete** the custom `_iterate_batches()` function (lines 552-576).

#### Behavioral changes gained:
- Batch size now from Integration Properties (not hardcoded 1000)
- Inter-batch delay applied (configurable, prevents SN rate limiting)
- Max batches safety cap (prevents runaway scans)
- Retry logic on transient failures (currently scan fails on first transient error)
- ORDERBY safeguard appended to query

#### Risks & Mitigations:
- **Risk**: max_batches could truncate large scans
  - **Mitigation**: Default is 5000 batches × 200 records = 1M records — sufficient
- **Risk**: inter_batch_delay slows scan execution
  - **Mitigation**: Configurable per-instance via Integration Properties; set to 0 if needed
- **Risk**: Batch size change (1000 → 200 default) increases API calls
  - **Mitigation**: Tune via `integration.fetch.default_batch_size` property

---

### 5.2 csdm_ingestion.py — Consolidate Batch Fetcher (Optional)

#### Change A: Replace `fetch_batch_with_retry()` with `client._iterate_batches()`

**Current** (inside `ingest_table()` loop):
```python
batch = fetch_batch_with_retry(client, table_name, query, batch_size, offset, batch_num)
```

**Target**: Replace manual offset loop with:
```python
for batch in client._iterate_batches(table=table_name, query=query, fields=fields):
    # process batch...
```

Then **delete** `fetch_batch_with_retry()` function (lines 536-579).

#### Change B: Replace `build_delta_query()` with `_watermark_filter()`

**Current** (line 514):
```python
def build_delta_query(last_updated_on_str):
    if last_updated_on_str:
        return f"sys_updated_on>={last_updated_on_str}^ORDERBYsys_updated_on"
    return "ORDERBYsys_updated_on"
```

**Target**: Use sn_client watermark filter:
```python
if watermark:
    wm_filter = client._watermark_filter(watermark, inclusive=True)
    query = f"{wm_filter}^ORDERBYsys_updated_on"
else:
    query = "ORDERBYsys_updated_on"
```

Note: `_iterate_batches()` already appends ORDERBY, so the explicit append may become redundant.

#### Decision: Recommended but lower priority
CSDM is intentionally isolated with its own ingestion lifecycle. Consolidation improves consistency but is not critical.

---

### 5.3 sn_dictionary.py — Replace 3 Direct session.get() Calls

#### Change 1: `validate_table_exists()` (line 79)

**Current**:
```python
url = client._build_url("table/sys_db_object")
params = {"sysparm_query": f"name={table_name}", "sysparm_limit": 1, ...}
response = client.session.get(url, params=params, timeout=...)
data = client._handle_response(response)
```

**Target**:
```python
records = client.get_records(
    table="sys_db_object",
    query=f"name={table_name}",
    fields=["sys_id", "name", "label", "super_class", "is_extendable", "extension_model"],
    limit=1,
)
# Adapt return to match existing callers
```

#### Change 2: `_resolve_table_name_by_sys_id()` (line 127)

**Current**:
```python
url = client._build_url(f"table/sys_db_object/{sys_id}")
params = {"sysparm_fields": "name"}
response = client.session.get(url, params=params, timeout=...)
```

**Target**:
```python
records = client.get_records(
    table="sys_db_object",
    query=f"sys_id={sys_id}",
    fields=["name"],
    limit=1,
)
return records[0].get("name") if records else None
```

Note: Current code uses record-by-ID endpoint (`table/{table}/{sys_id}`). Replacement uses query filter. Both return same result; query approach is consistent with rest of codebase.

#### Change 3: `_fetch_fields_for_table()` (line 217)

**Current**:
```python
url = client._build_url("table/sys_dictionary")
params = {"sysparm_query": "^".join(query_parts), "sysparm_limit": 500, ...}
response = client.session.get(url, params=params, timeout=...)
data = client._handle_response(response)
```

**Target**:
```python
records = client.get_records(
    table="sys_dictionary",
    query="^".join(query_parts),
    fields=["element", "column_label", "internal_type", "max_length",
            "reference", "active", "read_only", "mandatory"],
    limit=500,
)
```

#### Gains:
- All 3 calls gain retry logic via `_fetch_with_retry()`
- Consistent error handling via `_handle_response()`
- Integration Properties config support
- Consistent logging and monitoring

---

## 6. The Inclusive/Exclusive Issue

### 6.1 The Problem

The watermark filter uses `>=` (inclusive) or `>` (exclusive) depending on the caller. The distinction matters:

- **`>=` (inclusive)**: Includes records updated AT the watermark timestamp
- **`>` (exclusive)**: Excludes records updated AT the watermark timestamp

If multiple records share the same `sys_updated_on` timestamp as the watermark, using `>` for probes will undercount them, potentially causing `resolve_delta_decision` to make wrong decisions.

### 6.2 Current State Across All Call Sites

| Caller | Context | Operator | Source |
|--------|---------|----------|--------|
| data_pull_executor (probe) | `_resolve_delta_pull_mode()` line 299 | `>` (exclusive) | explicit `inclusive=False` |
| data_pull_executor (pull) | All `pull_*()` methods | `>=` (inclusive) | default `inclusive=True` |
| server.py preflight plan (probe) | `_build_assessment_preflight_plan()` line 7043 | `>=` (inclusive) | **default — INCONSISTENT with executor** |
| scan_executor (pull) | `_apply_since_filter()` line 543 | `>=` (inclusive) | hardcoded |
| csdm_ingestion (pull + probe) | `build_delta_query()` line 514 | `>=` (inclusive) | hardcoded |
| sn_dictionary (pull) | `_fetch_fields_for_table()` line 207 | `>=` (inclusive) | hardcoded |

### 6.3 The Inconsistency

**Executor probe** (`_resolve_delta_pull_mode`, line 299):
```python
delta_probe_count = _estimate_expected_total(
    ..., since=watermark, inclusive=False  # > (exclusive)
)
```

**Plan probe** (`_build_assessment_preflight_plan`, line 7043):
```python
delta_probe_count = _estimate_expected_total(
    ..., since=watermark  # No inclusive param → defaults to True → >= (inclusive)
)
```

These two probes for the same logical operation use different operators. The plan probe overcounts (includes watermark records), the executor probe undercounts (excludes them).

### 6.4 Recommended Fix

**Option A (Simple)**: Make all probes use `>=` (inclusive)
- Change line 299: `inclusive=False` → remove parameter (use default True)
- Probe slightly overcounts (safe — delta pulls a few duplicates that get upserted)
- Consistent with plan probe behavior

**Option B (Precise)**: Make all probes use `>` (exclusive)
- Change plan probe at line 7043: add `inclusive=False`
- Undercounts at timestamp boundaries (risky — could miss records)

**Recommendation**: **Option A** — use `>=` everywhere. Overcounting is harmless (upsert deduplicates); undercounting can cause missed records or unnecessary full refreshes.

---

## 7. Risk Assessment

### 7.1 scan_executor.py Consolidation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Batch size change (1000 → 200) | More API calls, slower scans | Tune `integration.fetch.default_batch_size` |
| Inter-batch delay added | Slower scan execution | Set to 0 for scan context if needed |
| max_batches cap | Could truncate very large scans | Default 5000 × 200 = 1M records |
| Retry on transient errors | Better reliability (currently fails immediately) | Positive change |
| ORDERBY appended | Could conflict with existing query ordering | Review scan queries |

### 7.2 csdm_ingestion.py Consolidation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Loss of CSDM-specific retry config | Different retry behavior | Merge retry configs or parameterize |
| batch_size from Properties instead of CSDM config | May differ from current CSDM defaults | Align property defaults |
| Intentional isolation broken | Coupling between CSDM and main pipeline | Accept tradeoff or keep isolated |

### 7.3 sn_dictionary.py Consolidation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Record-by-ID endpoint replaced with query | Marginally different SN behavior | Query by sys_id is equivalent |
| Error handling changes | Different exception flow | Test all dictionary operations |
| Low risk overall | These are simple GET calls | Straightforward replacement |

---

## Appendix: File Reference

| File | Path | Role |
|------|------|------|
| sn_client.py | `src/services/sn_client.py` | Shared SN API client |
| integration_sync_runner.py | `src/services/integration_sync_runner.py` | Delta decision logic |
| data_pull_executor.py | `src/services/data_pull_executor.py` | Data Browser / Preflight pulls |
| scan_executor.py | `src/services/scan_executor.py` | Assessment scan execution |
| csdm_ingestion.py | `src/services/csdm_ingestion.py` | CSDM mirror sync |
| sn_dictionary.py | `src/services/sn_dictionary.py` | Dictionary operations |
| dictionary_pull_orchestrator.py | `src/services/dictionary_pull_orchestrator.py` | Dictionary pull coordination |
| artifact_detail_puller.py | `src/services/artifact_detail_puller.py` | Artifact detail fetch |
| contextual_lookup.py | `src/services/contextual_lookup.py` | Reference lookups |
| sn_fetch_config.py | `src/services/sn_fetch_config.py` | Fetch config (Integration Properties) |
| integration_properties.py | `src/services/integration_properties.py` | Property definitions |

---

## 8. UI Trigger → SN API Call Mapping

Every button, link, and automated process across the app that results in outbound ServiceNow API calls, categorized by trigger type.

### 8.1 Category Legend

| Category | Description |
|----------|-------------|
| **Initial Pull** | First-time data load after instance connection |
| **Preflight** | Assessment preflight data sync (automated or manual) |
| **Delta** | Manual delta refresh button (pull changes since watermark) |
| **Full** | Manual full refresh button (re-pull all data) |
| **Scan** | Assessment scan execution (customization/inventory scanning) |
| **CSDM** | CSDM mirror table ingestion |
| **Dictionary** | Schema/metadata lookups (sys_dictionary, sys_db_object) |
| **Probe** | Count-only queries for decision-making (no data returned) |
| **Pipeline** | Pipeline stage auto-advance operations |

### 8.2 Instance Management Screen

**URL**: `/instances` and `/instances/{instance_id}`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| "Test Connection" | `POST /instances/{id}/test` | `test_instance_connection()` | `test_connection()` | sys_user, sys_update_set, cmdb_ci_app_server | Initial Pull + Probe | InstanceDataPull (implicit) |
| Auto after test pass | (internal chain) | `start_data_pull_job()` | `pull_app_file_types()`, `pull_sys_db_object()` | sys_app_file_type, sys_db_object | Initial Pull | InstanceDataPull |
| Auto after test pass | (internal chain) | `start_dictionary_pull()` | `get_records()` | sys_dictionary | Dictionary | JobRun (dictionary) |
| Auto after test pass | (internal chain) | `start_proactive_vh_pull()` | `pull_version_history()` | sys_update_version | Initial Pull | InstanceDataPull |
| "Refresh Metrics" | `POST /instances/{id}/metrics/refresh` | `refresh_instance_metrics()` | `get_instance_metrics()` | sys_update_set, sys_documentation, cmdb_ci_* | Probe | None |

### 8.3 Pre-Flight Data Manager Screen

**URL**: `/instances/{instance_id}/data`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| "Pull Selected" (Full) | `POST /instances/{id}/data/pull` mode=full | `start_data_pull_job()` | `pull_*()` per selected type | Per data type (up to 11 tables) | Full | InstanceDataPull per type, JobRun |
| "Pull Selected" (Delta) | `POST /instances/{id}/data/pull` mode=delta | `start_data_pull_job()` | `pull_*()` with since=watermark | Per data type | Delta | InstanceDataPull per type, JobRun |
| Status polling | `GET /api/instances/{id}/data-status` | — (local query) | — | — | None | — |
| "Pre Flight Data Browser" | Navigation to `/data-browser` | — | — | — | None | — |

### 8.4 Assessment Detail Screen

**URL**: `/assessments/{assessment_id}`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| "Start Assessment" | `POST /assessments/{id}/start` | `_run_assessment_preflight_data_sync()` | `test_connection()` → `pull_*()` (preflight) | Multiple (11 types) | Preflight | InstanceDataPull per type, JobRun |
| "Run Scans" | `POST /assessments/{id}/run-scans` | `_start_assessment_scan_job(mode='full')` | `get_records()`, per-scan queries | Per scan rule config | Scan | JobRun |
| "Refresh Scans" | `POST /assessments/{id}/refresh-scans` | `_start_assessment_scan_job(mode='full')` | `get_records()`, per-scan queries | Per scan rule config | Full | JobRun |
| "Refresh Scans Delta" | `POST /assessments/{id}/refresh-scans-delta` | `_start_assessment_scan_job(mode='delta')` | `get_records()` with since filter | Per scan rule (filtered) | Delta | JobRun |
| "Rebuild Scans" | `POST /assessments/{id}/rebuild-scans` | delete → `_start_assessment_scan_job(mode='full')` | Full re-pull | Per scan rule config | Full | JobRun |
| Per-scan "Retry" | `POST /scans/{id}/retry` | `_start_assessment_scan_job()` | `get_records()` for specific scan | Per scan target table | Scan | JobRun |
| Per-scan "Delta" | `POST /scans/{id}/refresh-delta` | `_start_assessment_scan_job(mode='delta')` | `get_records()` with since | Per scan target (filtered) | Delta | JobRun |
| Advance Pipeline | `POST /api/assessments/{id}/advance-pipeline` | `_run_assessment_pipeline_stage()` | Stage-dependent (test, pull, scan) | Stage-dependent | Pipeline | JobRun, InstanceDataPull |
| Status polling | `GET /api/assessments/{id}/scan-status` | — (local query) | — | — | None | — |
| "Download XLSX" | `GET /api/assessments/{id}/export/xlsx` | — (local export) | — | — | None | — |

### 8.5 Data Browser Screen

**URL**: `/data-browser`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| Records query | `GET /api/data-browser/records` | — (local query) | — | — (cached) | None | — |
| "Sync" button | `POST /api/data-browser/pull` | `start_data_pull_job()` | `pull_*()` per selected type | Per data type | Full / Delta | InstanceDataPull, JobRun |
| Schema request | `GET /api/data-browser/schema` | — (local query) | — | — | None | — |

### 8.6 Dynamic Browser Screen

**URL**: `/browse`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| Table field schema | `GET /api/dynamic-browser/field-schema` | Dictionary lookup | `get_records()` (if not cached) | sys_dictionary | Dictionary | None |
| Records query | `GET /api/dynamic-browser/records` | Live SN query | `get_records()` | User-selected table | Probe | None |

### 8.7 CSDM Ingestion Screen

**URL**: `/ingestion`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| "Start Ingestion" (Full) | `POST /api/ingest` mode=full | `_run_ingestion_thread()` | `get_records()` + batching | User-selected CSDM tables | CSDM | SnJobLog, SnIngestionState |
| "Start Ingestion" (Delta) | `POST /api/ingest` mode=delta | `_run_ingestion_thread()` | `get_records()` with watermark | CSDM tables (filtered) | CSDM + Delta | SnJobLog, SnIngestionState |
| "Refresh Schema" | `POST /api/schema/refresh` | Dictionary refresh | `get_records()` | sys_dictionary | Dictionary | None |
| Status polling | `GET /api/status/{instance_id}` | — (local query) | — | — | None | — |

### 8.8 Artifact / Results Screens

**URL**: `/results`, `/results/{id}`, `/artifacts/{class}/{sys_id}`

| Button / Trigger | Endpoint | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|-----------------|----------|-----------------|--------------|-------------|----------|----------|
| "View Code" / Detail | `GET /api/artifacts/{class}/{sys_id}/code` | Artifact detail fetch | `get_records()` (if not cached) | sys_script_include, etc. | Dictionary | None |
| Results query | `GET /api/results/query` | — (local query) | — | — | None | — |

### 8.9 Background / Automated Processes (No UI Button)

| Process | Trigger | Service Function | SN Method(s) | SN Table(s) | Category | Log Type |
|---------|---------|-----------------|--------------|-------------|----------|----------|
| Preflight concurrent types | Auto after start-assessment | `execute_data_pull(mode=from_plan)` | `pull_version_history()`, `pull_customer_update_xml()` | sys_update_version, sys_update_xml | Preflight | InstanceDataPull, JobRun |
| Dictionary pull orchestrator | Auto after connection | `_batch_pull_sys_db_object()` | `get_records()` | sys_db_object | Dictionary | JobRun |
| Contextual lookup (enrichment) | Pipeline stage 8 | `lookup_reference_remote()` | `get_records()` | Dynamic (per reference) | Pipeline | None |
| MCP live query tool | MCP tool call | `query_instance_live()` | `get_records()` | Dynamic (user-specified) | Probe | None |

### 8.10 Summary: Which Calls Have Logging vs. Which Don't

| Category | Has Log Record? | Log Table | Gaps |
|----------|----------------|-----------|------|
| Initial Pull | ✅ Yes | InstanceDataPull | No probe count stored |
| Preflight | ✅ Yes | InstanceDataPull + JobRun | Concurrent types skip decision counts |
| Delta button | ✅ Yes | InstanceDataPull | No probe count stored |
| Full button | ✅ Yes | InstanceDataPull | No remote count at decision time |
| Scan | ✅ Partial | JobRun only | No per-scan InstanceDataPull; no SN call metrics |
| CSDM | ✅ Yes | SnJobLog + SnIngestionState | No probe count, no local-vs-remote audit |
| Dictionary | ❌ No | None | 3 direct HTTP bypasses, no logging at all |
| Probe (metrics) | ❌ No | None | Results computed then discarded |
| Pipeline (enrichment) | ❌ No | None | Contextual lookups have no audit trail |
| Dynamic Browser (live) | ❌ No | None | Live queries not logged |
| MCP live query | ❌ No | None | MCP tool calls not logged to DB |

---

## 9. Probe/Count Logging Gap Analysis

### 9.1 What's Already Tracked

**InstanceDataPull** (best coverage — `src/models.py:1244`):
- `last_local_count` — local row count at decision time
- `last_remote_count` — remote total from full-table probe
- `expected_total` — estimated records before pull starts
- `records_pulled` — actual records returned
- `sync_mode` — "full" / "delta" / "skip"
- `sync_decision_reason` — human-readable decision explanation
- `last_sys_updated_on` — watermark timestamp
- `source_context` — "initial_data" or "preflight"

**SnJobLog** (CSDM only — `src/models_sn.py:166`):
- `rows_inserted`, `rows_updated`, `rows_deleted`, `batches_processed`

**SnIngestionState** (CSDM per-table — `src/models_sn.py:117`):
- `last_remote_count`, `cumulative_rows_pulled`, batch timing

**JobRun** (all background jobs — `src/models.py:1554`):
- `queue_total`, `queue_completed`, `progress_pct`, `status`, `mode`

### 9.2 Critical Gaps

| What's Missing | Where Lost | Impact |
|----------------|-----------|--------|
| **delta_probe_count** | Computed in `_resolve_delta_pull_mode()` line 313, never stored | Can't audit probe accuracy; can't tell if probe was close to reality |
| **remote_count for full pulls** | Concurrent preflight types skip decision path → last_remote_count stays NULL | Can't audit gap between local and remote for VH/CUX |
| **API call count per pull** | Never counted anywhere | Can't measure efficiency or SN load |
| **Probe query response time** | Never measured | Can't profile slow probes |
| **Dictionary call metrics** | 3 direct HTTP bypasses → no logging | Invisible to operations |
| **Scan SN call metrics** | Custom `_iterate_batches` → no logging | Can't audit scan API usage |
| **CSDM decision context** | No probe count, no local count at decision time | Can't audit why full vs delta |
| **Watermark age** | Implicit in timestamps but never calculated | Can't alert on stale data |

### 9.3 Recommended Changes

#### Tier 1 — Add to InstanceDataPull (Low Risk, High Value)

```python
# New columns for InstanceDataPull:
delta_probe_count: Optional[int] = None       # Records changed since watermark
delta_probe_at: Optional[datetime] = None      # When probe ran
remote_count_at: Optional[datetime] = None     # When remote count was checked
watermark_age_hours: Optional[float] = None    # How stale the watermark was
```

**Where to set**: In `data_pull_executor.py → _resolve_delta_pull_mode()` after `resolve_delta_decision()` returns:
```python
# After line 313:
pull_record.delta_probe_count = decision.delta_probe_count
pull_record.delta_probe_at = datetime.utcnow()
pull_record.watermark_age_hours = (datetime.utcnow() - watermark).total_seconds() / 3600 if watermark else None
```

#### Tier 2 — Extend SnJobLog + SnIngestionState

```python
# New columns for SnJobLog:
delta_probe_count: Optional[int] = None
local_count_at_start: Optional[int] = None
remote_count_at_start: Optional[int] = None
decision_mode: Optional[str] = None            # "full" / "delta" / "skip"
decision_reason: Optional[str] = None

# New columns for SnIngestionState:
last_decision_mode: Optional[str] = None
last_decision_reason: Optional[str] = None
last_delta_probe_count: Optional[int] = None
```

#### Tier 3 — Lightweight API Call Counter (Optional)

Instead of a full `ApiCallLog` table, add a counter to the ServiceNowClient session:

```python
# In sn_client.py __init__:
self._api_call_count = 0
self._api_total_time_ms = 0

# In get_records() and get_record_count():
self._api_call_count += 1
self._api_total_time_ms += elapsed_ms

# Expose via property:
@property
def api_call_stats(self) -> dict:
    return {"calls": self._api_call_count, "total_time_ms": self._api_total_time_ms}
```

Then persist `api_call_count` and `api_total_time_ms` to `InstanceDataPull.metadata_json` or `JobRun.metadata_json` at job completion.

---

## 10. Delta Ordering Optimization

### 10.1 The Idea

**Current behavior**: Delta pulls order by `sys_updated_on ASC` (oldest changes first).
**Proposed**: Order delta pulls by `sys_updated_on DESC` (newest changes first).

**Why this matters**: When running a delta pull after a watermark has gone stale, the most important records are the *most recently changed* ones. If we process newest-first:

1. **Newest changes upsert immediately** — the freshest data lands first
2. **As we page deeper**, we hit increasingly stale records that may already exist locally
3. **Opportunity for early termination**: If N consecutive upserts result in "no change" (record already identical in local DB), we can infer the remaining records are even older and stop early

### 10.2 Current Ordering Across Modules

| Module | Pull Method | Current Order | Direction |
|--------|------------|---------------|-----------|
| sn_client `_iterate_batches()` | Default | `ORDERBYsys_updated_on` | ASC (oldest first) |
| sn_client `iterate_delta_keyset()` | Keyset pagination | `ORDERBYsys_updated_on^ORDERBYsys_id` | ASC |
| sn_client `pull_version_history()` | Explicit | `state,sys_recorded_at` or `sys_recorded_at` | ASC |
| sn_client `pull_plugins()` | Explicit | `name` | ASC alpha |
| sn_client `pull_scopes()` | Explicit | `scope` | ASC alpha |
| csdm `build_delta_query()` | Hardcoded | `ORDERBYsys_updated_on` | ASC |
| csdm `fetch_batch_with_retry()` | Explicit param | `order_by="sys_updated_on"` | ASC |
| scan_executor `_iterate_batches()` | No order | None (SN default = sys_id ASC) | Undefined |

**Key**: ServiceNow uses `ORDERBY` for ASC and `ORDERBYDESC` for DESC in encoded queries.

### 10.3 Proposed Design

**Scope**: Applies to **all** pulls — both delta and full. Even full pulls may target a table that already has local data (re-pulls, rebuilds, etc.). DESC ordering ensures freshest data lands first regardless of mode.

#### Core Concept: DESC Order + Dual-Signal Bail-Out

The bail-out requires **two conditions met together**, not just one:

1. **Count match**: `local_count >= remote_count` — we have at least as many records as remote
2. **Consecutive unchanged upserts**: The upsert layer confirms N consecutive records where nothing actually changed (record already exists locally with identical content)

**Why both signals are needed**: Count alone isn't enough. If `local_count == remote_count` but some records were *updated* on the remote side (content changed, not added), the count matches but data is stale. The upsert must confirm "I touched this record and nothing was different" for a consecutive run before we can trust that the remaining records are truly unchanged.

```
Before pull:
  local_count  = count(local table)     # e.g. 245,054
  remote_count = probe(remote table)     # e.g. 263,446

During pull (DESC — newest first):
  → Process batches newest-first via ORDERBYDESC
  → Upsert each record, track whether it changed anything
  → After each batch:
      1. Check: local_count >= remote_count?     (count gate)
      2. Check: consecutive_unchanged >= N?      (content gate)
      3. If BOTH → BAIL: we're truly caught up
  → If records_processed >= max_delta_records → BAIL (safety cap)
```

**Why this works**: Processing newest-first means the first records we see are the ones most likely to be new or recently changed. As we page deeper (older records), we increasingly hit records that already exist locally unchanged. Once the count gate is satisfied AND we've seen N consecutive "no change" upserts, we have strong confidence the remaining records are already present and identical.

#### Implementation Layer 1 — `_iterate_batches()` DESC Support

```python
def _iterate_batches(
    self, table, query="", fields=None, batch_size=None,
    order_by="sys_updated_on",
    order_desc: bool = False,        # NEW: flip to DESC
    inter_batch_delay=None, max_batches=None,
):
    # ...existing config resolution...

    # Build ORDER BY clause — ASC or DESC
    order_keyword = "ORDERBYDESC" if order_desc else "ORDERBY"
    if order_by and f"{order_keyword}{order_by}" not in effective_query:
        effective_query = (
            f"{effective_query}^{order_keyword}{order_by}"
            if effective_query
            else f"{order_keyword}{order_by}"
        )
```

#### Implementation Layer 2 — All Pull Methods Use DESC

```python
# In pull_update_sets(), pull_customer_update_xml(), etc.:
# DESC is the default for all pulls now (controlled by property)
use_desc = load_delta_order_desc()  # property, default True

for batch in self._iterate_batches(
    table=..., query=query, fields=fields,
    order_desc=use_desc,
):
```

#### Implementation Layer 3 — Upsert Returns Change Signal

The upsert function must return whether it actually changed anything:

```python
def upsert_record(session, record, model_class) -> bool:
    """Upsert a single record. Returns True if data changed, False if identical."""
    existing = session.get(model_class, record["sys_id"])
    if existing is None:
        session.add(model_class(**record))
        return True  # new insert — data changed

    changed = False
    for key, value in record.items():
        if getattr(existing, key, None) != value:
            setattr(existing, key, value)
            changed = True

    return changed  # True = updated fields, False = already identical
```

#### Implementation Layer 4 — Dual-Signal Bail-Out in Executor

```python
# In data_pull_executor.py — per-type handler:

max_pull_records = load_delta_max_records()    # property, default 5000
bail_unchanged_run = load_bail_unchanged_run() # property, default 50
records_processed = 0
consecutive_unchanged = 0

for batch in client.pull_update_sets(since=since):
    for record in batch:
        changed = upsert_record(session, record, UpdateSet)
        records_processed += 1

        if changed:
            consecutive_unchanged = 0           # reset on any real change
        else:
            consecutive_unchanged += 1

    session.flush()

    # --- DUAL-SIGNAL BAIL-OUT ---
    if remote_count is not None:
        current_local = count_local(session, UpdateSet, instance_id)
        if current_local >= remote_count and consecutive_unchanged >= bail_unchanged_run:
            logger.info(
                "Pull bail-out: local (%d) >= remote (%d), "
                "%d consecutive unchanged after %d records — synced",
                current_local, remote_count,
                consecutive_unchanged, records_processed,
            )
            break  # BOTH gates met — truly caught up

    # --- SAFETY CAP ---
    if max_pull_records > 0 and records_processed >= max_pull_records:
        logger.warning(
            "Pull safety cap: %d records processed, stopping "
            "(local=%d, remote=%d, unchanged_run=%d)",
            records_processed, current_local, remote_count,
            consecutive_unchanged,
        )
        break  # gap too big — stop
```

#### How the Three Signals Work Together

| Signal | Trigger | Meaning | Required? |
|--------|---------|---------|-----------|
| **Count gate** | `local_count >= remote_count` | We have enough records | Yes (necessary) |
| **Content gate** | `consecutive_unchanged >= N` | Recent upserts confirm no changes | Yes (necessary) |
| **Safety cap** | `records_processed >= max_records` | Too many records for one pull | Independent (guard) |

Both the count gate AND content gate must be true simultaneously for the bail-out. The safety cap fires independently as a guard rail.

**Example scenarios**:
- Count met but records still changing → **no bail-out** (updates still arriving, keep pulling)
- Unchanged run but count not met → **no bail-out** (still missing records, keep pulling)
- Count met AND long unchanged run → **bail-out** (synced — safe to stop)
- Safety cap hit → **stop regardless** (pull is too large)

### 10.4 Integration Properties

```python
# New properties:
PropertyDef(
    "integration.pull.order_desc", "true",
    "Order all pulls newest-first (ORDERBYDESC sys_updated_on). "
    "Applies to both full and delta pulls. When true, most recently "
    "changed records are processed first, enabling early bail-out "
    "when local data is already current.",
    section="fetch",
),
PropertyDef(
    "integration.pull.max_records", "5000",
    "Maximum records to process in a single pull before stopping. "
    "Acts as a safety cap for both full and delta pulls. "
    "Set to 0 to disable (no cap).",
    section="fetch",
),
PropertyDef(
    "integration.pull.bail_unchanged_run", "50",
    "Number of consecutive unchanged upserts required (in combination "
    "with local count >= remote count) before bailing out of a pull. "
    "Higher = more conservative (less risk of missing updates). "
    "Set to 0 to disable bail-out (always process full result set).",
    section="fetch",
),
```

### 10.5 Considerations

| Concern | Analysis |
|---------|----------|
| **Offset pagination + DESC** | Works fine — each page is consistent within the DESC sort |
| **Keyset pagination + DESC** | Needs cursor reversal (`sys_updated_on<{cursor}`). More complex — defer to offset pagination for now |
| **Count check cost** | One `SELECT COUNT(*)` per batch against local SQLite — negligible (<1ms) |
| **Race condition on remote_count** | Remote count is a snapshot from probe time. Records could be added between probe and pull. Mitigated by `>=` (local can exceed remote if new inserts arrive during pull) |
| **Applies to all pulls** | Both full and delta use DESC. Full re-pulls benefit equally — e.g., a "Refresh Full" on a table that already has 250K records will bail out quickly once it confirms local is caught up and content matches |
| **Updated records (content change, same count)** | The content gate handles this — even if counts match, the upsert detects field-level changes. Only bails when consecutive records are truly identical. A scattered update in old records resets the unchanged counter |
| **Impact on watermark** | With DESC, first batch has the *highest* sys_updated_on. Watermark set from `max(sys_updated_on)` across all returned records — naturally comes from the first record in DESC order |
| **Safety cap too low** | If 5000 isn't enough, operator can increase via property. If frequently hitting the cap, the delta decision logic should be catching these as "full" instead |
| **Bail threshold too low** | Default 50 means we need 50 consecutive records where nothing changed. For scattered updates this is conservative enough. Operator can increase to 100+ for extra safety |
| **SN API cost** | DESC ordering has negligible SN server impact (sys_updated_on is indexed either way) |

### 10.6 Watermark Handling with DESC

With DESC ordering, the watermark (max `sys_updated_on`) arrives in the **first batch**, not the last:

```python
# Track watermark across all batches:
max_watermark = None

for batch in client.pull_update_sets(since=since):
    for record in batch:
        ts = record.get("sys_updated_on")
        if ts and (max_watermark is None or ts > max_watermark):
            max_watermark = ts
    upsert_batch(session, batch)
    # ...bail-out checks...

# After loop, persist watermark:
pull_record.last_sys_updated_on = max_watermark
```

With DESC, `max_watermark` is typically set from the very first record and never changes. This is actually **safer** than ASC — if we bail out early, we still captured the correct watermark from the newest record we saw.

### 10.7 Expected Impact

#### Scenario 1: Full Re-Pull on Table with Existing Data

Table has 245K records locally, 245K remotely, 200 records updated since last pull.

**Current (ASC, no bail-out)**: All 245K records pulled and upserted. ~1,225 batches.
**With DESC + dual bail-out**:
1. Newest 200 updated records land in first batch — upserts detect changes
2. Next batches hit unchanged records — consecutive_unchanged climbs
3. After ~250 records (200 changed + 50 unchanged run), count gate AND content gate both met → **bail-out**
4. **Result**: ~250 records processed instead of 245K = **~99.9% fewer records**
5. **API calls**: 2 batches instead of 1,225 = **~99.8% fewer API calls**

#### Scenario 2: Delta Pull with 20-Day Stale Watermark

VH with 263K remote, 245K local, ~18K new records since watermark.

**Current (ASC, no bail-out)**: If delta chosen, all 18K+ watermarked records processed oldest-first. If full chosen (current behavior for this gap), all 263K records.
**With DESC + dual bail-out** (delta mode):
1. ~18K new records upsert (inserts) → local climbs from 245K toward 263K
2. After inserts complete, start hitting existing records — unchanged run builds
3. At ~18,050 records: count gate met (263K >= 263K) + content gate met (50 unchanged) → **bail-out**
4. **Result**: ~18,050 records instead of 263K
5. **Safety cap**: 5000 default would fire first if not bumped — operator can set to 20000+ for large tables, or let resolve_delta_decision route it as full (which now also benefits from DESC bail-out)

#### Scenario 3: Full Pull on Empty Table (First-Time Load)

No local records. 100K records remotely.

**With DESC + dual bail-out**: Count gate never met (local < remote until every record is pulled). Bail-out never fires. Safety cap at 5000 would stop early — **for first-time loads, set cap to 0 (disabled) or raise it**. Alternatively, the bail-out logic can be skipped entirely when `initial_local_count == 0` (nothing to bail against).

### 10.8 Logging Requirements

All bail-out events and pull metrics must be recorded in `InstanceDataPull` for operational visibility.

#### What's Already Captured vs. What's Missing

The probe already runs on ALL pulls (full and delta) at line 1922 of `data_pull_executor.py`:
```python
expected_total = _estimate_expected_total(session, client, data_type, since, ...)
```

For **full** pulls: probes remote count (no watermark), stored as `expected_total`.
For **delta** pulls: probes count since watermark, stored as `expected_total`.

**Current capture** (existing columns):

| Column | Full Pull | Delta Pull | Smart/Decision Pull |
|--------|-----------|------------|---------------------|
| `expected_total` | ✅ Remote count | ✅ Delta count since watermark | ✅ Delta count |
| `records_pulled` | ✅ Total pulled | ✅ Total pulled | ✅ Total pulled |
| `last_local_count` | ❌ Not set (skips decision) | ✅ Set via decision | ✅ Set via decision |
| `last_remote_count` | ❌ Not set (skips decision) | ✅ Set via decision | ✅ Set via decision |
| `sync_mode` | ✅ "full" | ✅ "delta" | ✅ Resolved mode |
| `sync_decision_reason` | ⚠️ "Explicit mode" | ✅ Decision reason | ✅ Decision reason |

**Gap**: Full pulls skip `_resolve_delta_pull_mode()` entirely (line 1901), so `last_local_count` and `last_remote_count` stay NULL. The probe DOES run (expected_total), but local count at decision time is never captured.

#### New Columns for InstanceDataPull

```python
# Counts — always set, regardless of mode:
local_count_pre_pull: Optional[int] = None      # SELECT COUNT(*) on local table BEFORE pull starts
remote_count_at_probe: Optional[int] = None     # Total remote records from probe (no watermark filter)
delta_probe_count: Optional[int] = None          # Records changed since watermark (delta/smart only)

# Bail-out tracking:
bail_out_reason: Optional[str] = None            # null | "count_and_content" | "safety_cap" | null (completed)
bail_unchanged_at_exit: Optional[int] = None     # consecutive unchanged upserts when bail triggered
local_count_post_pull: Optional[int] = None      # SELECT COUNT(*) on local table AFTER pull finishes
```

#### Where to Set Them in `execute_data_pull()`

```python
def execute_data_pull(session, instance, client, data_type, mode="full", ...):
    pull = _get_or_create_data_pull(session, instance.id, data_type)

    # --- ALWAYS capture local count before pull, regardless of mode ---
    pull.local_count_pre_pull = _get_local_cached_count(session, instance.id, data_type)

    if mode in ("delta", "smart"):
        # existing decision logic...
        ...
    else:
        since = None

    # --- ALWAYS probe remote count (no watermark) for the bail-out finish line ---
    pull.remote_count_at_probe = _estimate_expected_total(
        session, client, data_type, since=None, instance_id=instance.id,
    )

    # existing expected_total probe (with since filter for delta)...
    expected_total = _estimate_expected_total(session, client, data_type, since, ...)
    _set_expected_total(session, pull, expected_total)

    # ... pull execution with bail-out logic ...

    # --- After pull completes ---
    pull.local_count_post_pull = _get_local_cached_count(session, instance.id, data_type)
```

**Key change**: `remote_count_at_probe` always probes with `since=None` (full table count), even on delta pulls. This gives the bail-out its "finish line" number. The existing `expected_total` continues to probe with the `since` filter for progress tracking.

#### Example Log Entries

**Full re-pull with bail-out (200 records changed)**:
```
data_type=version_history, mode=full,
local_count_pre_pull=245054, remote_count_at_probe=245054, delta_probe_count=null,
expected_total=245054, records_pulled=250,
bail_out_reason=count_and_content, bail_unchanged_at_exit=50,
local_count_post_pull=245054
```

**Delta pull with bail-out (18K new records)**:
```
data_type=version_history, mode=delta,
local_count_pre_pull=245054, remote_count_at_probe=263446, delta_probe_count=18392,
expected_total=18392, records_pulled=18050,
bail_out_reason=count_and_content, bail_unchanged_at_exit=50,
local_count_post_pull=263446
```

**Delta pull hitting safety cap**:
```
data_type=customer_update_xml, mode=delta,
local_count_pre_pull=252355, remote_count_at_probe=367875, delta_probe_count=115520,
expected_total=115520, records_pulled=5000,
bail_out_reason=safety_cap, bail_unchanged_at_exit=0,
local_count_post_pull=257355
```

This gives operators the full picture for every pull: **DB before → probe → what we pulled → why we stopped → DB after**.
