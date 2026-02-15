# CSDM Data Foundations — Ingestion Module Specification

> **Date**: 2026-02-12
> **Status**: Design Complete — Ready for Implementation
> **Author**: Lead Architect (Agent Team: csdm-ingestion)

---

## Table of Contents

1. [Architecture & Sequencing Plan](#1-architecture--sequencing-plan)
2. [Database Schema](#2-database-schema)
3. [ServiceNow Ingestion Implementation Spec](#3-servicenow-ingestion-implementation-spec)
4. [Management UI Spec](#4-management-ui-spec)
5. [Implementation Notes](#5-implementation-notes)

---

## 1. Architecture & Sequencing Plan

### 1.1 Design Principles

1. **Dynamic schema** — Tables are NOT hardcoded in `models.py`. Field discovery via `sys_dictionary` drives DDL at runtime.
2. **Table-by-table execution** — One SN table ingested at a time. No bulk parallel pulls.
3. **Job-controlled** — Every ingestion is a trackable job with start/stop/cancel/resume.
4. **Instance-scoped** — All data is keyed to `instance_id`. Multi-instance supported.
5. **Checkpoint-safe** — Every batch commits a watermark. Interruption = safe resume.
6. **Existing infrastructure** — Builds on the existing `Instance`, `InstanceDataPull`, `ServiceNowClient`, and background thread patterns already in the codebase.

### 1.2 Key Architecture Decision: Inheritance Strategy

**Decision: Single table per SN table (Option 1) with shared `sys_id` as natural key.**

Rationale:
- ServiceNow Table API returns data per-table naturally. Querying `cmdb_ci_service_business` returns ALL inherited + extension fields.
- Dynamic field discovery means each local table gets exactly the columns that SN returns for that table — no sparse columns, no discrimination columns.
- Queries are straightforward — `SELECT * FROM sn_cmdb_ci_service_business WHERE instance_id = ?`.
- Parent-child relationships are captured via `sys_id` (a child row shares `sys_id` with its parent row in SN).
- If you query the parent table (`cmdb_ci_service`) in SN, you get ALL records including children (SN handles this server-side). We mirror that: our local `sn_cmdb_ci_service` table holds all service CIs, and `sn_cmdb_ci_service_business` holds the business-service-specific fields + sys_id FK back to parent.

**Why not the alternatives:**
- **Consolidated base table** (Option 2) creates a wide sparse table that's hard to manage with dynamic columns and confuses field provenance.
- **Hybrid** (Option 3) adds complexity without meaningful benefit since SN API already returns all fields per table.

**Practical implication**: When we ingest `cmdb_ci_service_business`, we get ALL columns (inherited + extension). We store them all in `sn_cmdb_ci_service_business`. To find the parent row, join on `sys_id` to `sn_cmdb_ci_service`. The parent table also contains the business service rows (SN inheritance), so no data is lost.

### 1.3 Key Architecture Decision: Dynamic vs Static Schema

**Decision: Fully dynamic tables in a `sn_` namespace.**

- All ingested SN tables live with a `sn_` prefix (e.g., `sn_cmdb_ci_service`, `sn_sys_user`, `sn_incident`).
- Columns are created dynamically from `sys_dictionary` extraction.
- A metadata registry (`csdm_table_registry`, `csdm_field_mapping`) tracks what we've created.
- These tables are NOT SQLModel models — they're created via raw DDL (`CREATE TABLE`, `ALTER TABLE`).
- The existing `models.py` only adds the registry/job/management tables (static, known schema).

### 1.4 Key Architecture Decision: Deletions

**Recommendation: Accept that deletes are NOT captured during delta pulls. Provide full-refresh as the mechanism to reconcile deletes.**

Rationale:
- `sys_audit_delete` / `sys_deleted_record` require elevated privileges and are not reliably available on all instances.
- For CMDB/CSDM tables (relatively low volume: hundreds to low thousands of records), a periodic full refresh is practical and sufficient.
- Full refresh = clear table + repull all records. The management UI exposes this as "Clear + Repull".
- For high-volume tables (incident, change_request), deletes are rare and typically irrelevant for analysis purposes.

### 1.5 Sequencing Plan (Build Order)

```
Phase 1: Foundation (build first)
├── 1a. Registry tables (csdm_table_registry, csdm_field_mapping, csdm_ingestion_state, csdm_job_log)
├── 1b. Dictionary extraction service (sys_dictionary + sys_db_object queries)
├── 1c. Dynamic DDL engine (create/alter tables from dictionary metadata)
└── 1d. Core ingestion engine (delta query + pagination + checkpoint + cancel)

Phase 2: Service Tables (highest priority data)
├── 2a. cmdb_ci_service (parent — ingest first, establishes sys_id base)
├── 2b. cmdb_ci_service_business
├── 2c. cmdb_ci_service_technical
├── 2d. cmdb_ci_service_auto (Service Instance in CSDM 5)
├── 2e. cmdb_ci_service_discovered, cmdb_ci_service_tags,
│       cmdb_ci_service_calculated, cmdb_ci_query_based_service
└── 2f. service_offering

Phase 3: Foundation/Common Tables
├── 3a. cmn_location (priority — needed for FK references)
├── 3b. cmn_department
├── 3c. sys_user
├── 3d. sys_user_group
└── 3e. sys_user_grmember (depends on sys_user + sys_user_group)

Phase 4: Process Tables
├── 4a. incident
├── 4b. change_request
└── 4c. wm_task

Phase 5: Custom Tables
├── 5a. u_work_order_assignment (Weis-specific)
└── 5b. Custom table framework (arbitrary u_/x_ tables)

Phase 6: Management UI
├── 6a. CSDM Ingestion management page
├── 6b. Job status dashboard
└── 6c. Custom table registration UI
```

**Why this order:**
- Phase 1 must be first — it's the engine everything else runs on.
- Phase 2 before Phase 3 because service tables are the primary CSDM deliverable.
- Phase 3 before Phase 4 because foundation tables provide FK targets for reference fields.
- Phase 5 after Phase 3 because u_work_order_assignment references users/groups/services.
- Phase 6 can be built incrementally alongside Phases 2-5 (start with a basic page, enhance as tables are added).

### 1.6 Integration with Existing App

The CSDM ingestion module integrates into the existing `tech-assessment-hub` app:

| New Component | Location |
|--------------|----------|
| Registry models | `src/models_csdm.py` (new file, static SQLModel tables) |
| Dictionary service | `src/services/sn_dictionary.py` (new) |
| Dynamic DDL engine | `src/services/csdm_ddl.py` (new) |
| Ingestion engine | `src/services/csdm_ingestion.py` (new) |
| Custom table service | `src/services/csdm_custom_tables.py` (new) |
| API routes | `src/web/routes/csdm.py` (new, or added to server.py initially) |
| UI templates | `src/web/templates/csdm_*.html` (new) |
| Constants/config | `src/csdm_table_catalog.py` (new — table priority groups) |

Uses existing:
- `ServiceNowClient` for all SN REST calls
- `Instance` model for connection info
- Background thread pattern from `_DataPullJob`
- `get_session` / database engine

---

## 2. Database Schema

### 2.1 Static Tables (added to models — known schema)

#### 2.1.1 `csdm_table_registry` — Tracks all ingested SN tables

```sql
CREATE TABLE csdm_table_registry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     INTEGER NOT NULL REFERENCES instance(id),
    sn_table_name   TEXT NOT NULL,           -- e.g., 'cmdb_ci_service_business'
    local_table_name TEXT NOT NULL,           -- e.g., 'sn_cmdb_ci_service_business'
    priority_group  TEXT NOT NULL DEFAULT 'custom',  -- 'service', 'foundation', 'process', 'custom'
    display_label   TEXT,                     -- human-readable label
    parent_table    TEXT,                     -- SN parent table name (from sys_db_object.super_class)
    parent_local_table TEXT,                  -- local parent table name
    is_custom       BOOLEAN NOT NULL DEFAULT 0,  -- 1 for u_/x_ tables
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    field_count     INTEGER DEFAULT 0,
    row_count       INTEGER DEFAULT 0,
    schema_version  INTEGER DEFAULT 1,       -- incremented on ALTER TABLE
    schema_hash     TEXT,                     -- hash of field definitions for change detection
    first_ingested_at DATETIME,
    last_schema_refresh_at DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instance_id, sn_table_name)
);
CREATE INDEX idx_csdm_tr_instance ON csdm_table_registry(instance_id);
CREATE INDEX idx_csdm_tr_group ON csdm_table_registry(priority_group);
```

#### 2.1.2 `csdm_field_mapping` — Column-level mapping per table

```sql
CREATE TABLE csdm_field_mapping (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    registry_id     INTEGER NOT NULL REFERENCES csdm_table_registry(id) ON DELETE CASCADE,
    sn_element      TEXT NOT NULL,            -- SN field name (e.g., 'assignment_group')
    local_column    TEXT NOT NULL,            -- DB column name (same unless collision)
    sn_internal_type TEXT,                    -- SN type: 'reference', 'string', 'integer', 'glide_date_time', etc.
    sn_max_length   INTEGER,
    sn_reference_table TEXT,                  -- target table for reference fields (e.g., 'sys_user_group')
    sn_reference_qual TEXT,                   -- reference qualifier if any
    sn_choice_table TEXT,                     -- if choice field, the choice table
    db_column_type  TEXT NOT NULL,            -- SQLite type: TEXT, INTEGER, REAL, DATETIME
    is_reference    BOOLEAN DEFAULT 0,
    is_primary_key  BOOLEAN DEFAULT 0,        -- true for sys_id
    is_indexed      BOOLEAN DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(registry_id, sn_element)
);
CREATE INDEX idx_csdm_fm_registry ON csdm_field_mapping(registry_id);
CREATE INDEX idx_csdm_fm_ref ON csdm_field_mapping(is_reference) WHERE is_reference = 1;
```

#### 2.1.3 `csdm_ingestion_state` — Per-instance, per-table checkpoint

```sql
CREATE TABLE csdm_ingestion_state (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id                 INTEGER NOT NULL REFERENCES instance(id),
    sn_table_name               TEXT NOT NULL,
    -- Delta checkpointing
    last_successful_sys_updated_on DATETIME,
    last_successful_sys_id      TEXT,          -- tie-break for same-timestamp records
    -- Refresh tracking
    last_full_refresh_at        DATETIME,
    last_delta_at               DATETIME,
    -- Run status
    last_run_status             TEXT,          -- 'success', 'failed', 'cancelled', 'in_progress'
    last_run_started_at         DATETIME,
    last_run_completed_at       DATETIME,
    last_error                  TEXT,
    -- Counters
    total_rows_in_db            INTEGER DEFAULT 0,
    last_batch_inserted         INTEGER DEFAULT 0,
    last_batch_updated          INTEGER DEFAULT 0,
    last_batch_duration_seconds REAL,
    cumulative_rows_pulled      INTEGER DEFAULT 0,
    -- Remote state
    last_remote_count           INTEGER,       -- total count from SN header
    last_remote_count_at        DATETIME,
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instance_id, sn_table_name)
);
CREATE INDEX idx_csdm_is_instance ON csdm_ingestion_state(instance_id);
CREATE INDEX idx_csdm_is_status ON csdm_ingestion_state(last_run_status);
```

#### 2.1.4 `csdm_job_log` — Per-run log entries

```sql
CREATE TABLE csdm_job_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     INTEGER NOT NULL REFERENCES instance(id),
    sn_table_name   TEXT NOT NULL,
    job_type        TEXT NOT NULL,            -- 'delta', 'full_refresh', 'schema_refresh', 'clear'
    status          TEXT NOT NULL,            -- 'started', 'in_progress', 'completed', 'failed', 'cancelled'
    started_at      DATETIME NOT NULL,
    completed_at    DATETIME,
    rows_inserted   INTEGER DEFAULT 0,
    rows_updated    INTEGER DEFAULT 0,
    rows_deleted    INTEGER DEFAULT 0,
    batches_processed INTEGER DEFAULT 0,
    error_message   TEXT,
    error_stack     TEXT,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_csdm_jl_instance ON csdm_job_log(instance_id);
CREATE INDEX idx_csdm_jl_table ON csdm_job_log(sn_table_name);
CREATE INDEX idx_csdm_jl_status ON csdm_job_log(status);
```

#### 2.1.5 `csdm_custom_table_request` — Custom table registration

```sql
CREATE TABLE csdm_custom_table_request (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     INTEGER NOT NULL REFERENCES instance(id),
    sn_table_name   TEXT NOT NULL,            -- e.g., 'u_work_order_assignment'
    display_label   TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'validated', 'schema_created', 'active', 'failed'
    validation_error TEXT,
    requested_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    validated_at    DATETIME,
    schema_created_at DATETIME,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(instance_id, sn_table_name)
);
```

### 2.2 Dynamic Tables (created at runtime from sys_dictionary)

All dynamic tables follow this pattern:

```sql
-- Template: sn_{table_name}
CREATE TABLE sn_{table_name} (
    _row_id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- local surrogate PK
    _instance_id    INTEGER NOT NULL,                   -- FK to instance.id
    sys_id          TEXT NOT NULL,                       -- SN natural key
    -- ... all fields from sys_dictionary dynamically added ...
    sys_created_on  DATETIME,
    sys_updated_on  DATETIME,
    sys_created_by  TEXT,
    sys_updated_by  TEXT,
    sys_mod_count   INTEGER,
    _ingested_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    _updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    _raw_json       TEXT,                               -- optional: full API response
    UNIQUE(_instance_id, sys_id)
);

-- Standard indexes on every dynamic table:
CREATE INDEX idx_sn_{table_name}_instance ON sn_{table_name}(_instance_id);
CREATE INDEX idx_sn_{table_name}_sysid ON sn_{table_name}(sys_id);
CREATE INDEX idx_sn_{table_name}_updated ON sn_{table_name}(sys_updated_on);
```

### 2.3 SN Type → SQLite Type Mapping

| SN Internal Type | SQLite Column Type | Notes |
|---|---|---|
| `string`, `translated_text`, `html`, `script`, `script_plain`, `url`, `email`, `phone_number_e164`, `sys_class_name`, `journal`, `journal_input`, `conditions`, `documentation_field`, `translated_html`, `xml`, `json_translations`, `composite_name`, `wiki_text` | `TEXT` | Catch-all for text |
| `integer`, `count`, `order_index`, `table_name` | `INTEGER` | |
| `boolean` | `INTEGER` | 0/1 |
| `float`, `decimal`, `currency`, `price` | `REAL` | |
| `glide_date_time`, `due_date`, `glide_date`, `glide_time`, `calendar_date_time` | `TEXT` | Store as ISO string; SQLite has no native datetime |
| `reference`, `document_id` | `TEXT` | Stores sys_id of referenced record |
| `GUID` | `TEXT` | sys_id format |
| `choice`, `multi_two_lines` | `TEXT` | Store the value, not display |
| `*` (fallback) | `TEXT` | Unknown types default to TEXT |

### 2.4 Foreign Key Strategy

**Approach: Deferred / soft FKs via indexes, not enforced constraints.**

Rationale:
- Ingestion order can't guarantee parent rows exist before children.
- SQLite FK enforcement is optional (`PRAGMA foreign_keys = ON`); we leave it OFF for dynamic tables.
- Instead, we create **indexes on all reference columns** and document the relationships in `csdm_field_mapping.sn_reference_table`.
- The management UI can show "referential integrity" status by counting orphan references.

**Index creation for reference fields:**
```sql
-- For every field where is_reference = 1 in csdm_field_mapping:
CREATE INDEX idx_sn_{table}_{column} ON sn_{table}({column});
```

**Known relationships to index:**

| Source Table | Reference Column | Target Table |
|---|---|---|
| `sn_sys_user_grmember` | `user` | `sn_sys_user` (sys_id) |
| `sn_sys_user_grmember` | `group` | `sn_sys_user_group` (sys_id) |
| `sn_cmdb_ci_service_business` | `sys_id` | `sn_cmdb_ci_service` (sys_id) |
| `sn_cmdb_ci_service_technical` | `sys_id` | `sn_cmdb_ci_service` (sys_id) |
| `sn_cmdb_ci_service_auto` | `sys_id` | `sn_cmdb_ci_service` (sys_id) |
| `sn_cmdb_ci_service_discovered` | `sys_id` | `sn_cmdb_ci_service_auto` (sys_id) |
| `sn_cmdb_ci_service_tags` | `sys_id` | `sn_cmdb_ci_service_auto` (sys_id) |
| `sn_cmdb_ci_service_calculated` | `sys_id` | `sn_cmdb_ci_service_auto` (sys_id) |
| `sn_cmdb_ci_query_based_service` | `sys_id` | `sn_cmdb_ci_service_auto` (sys_id) |
| `sn_service_offering` | `parent` (if present) | `sn_cmdb_ci_service_business` (sys_id) |
| `sn_incident` | `assignment_group` | `sn_sys_user_group` (sys_id) |
| `sn_incident` | `assigned_to` | `sn_sys_user` (sys_id) |
| `sn_incident` | `location` | `sn_cmn_location` (sys_id) |
| `sn_incident` | `cmdb_ci` | `sn_cmdb_ci_service` (sys_id) |
| `sn_change_request` | `assignment_group` | `sn_sys_user_group` (sys_id) |
| `sn_change_request` | `assigned_to` | `sn_sys_user` (sys_id) |
| `sn_u_work_order_assignment` | `u_assignment_group` | `sn_sys_user_group` (sys_id) |
| `sn_u_work_order_assignment` | (assignee field) | `sn_sys_user` (sys_id) |
| `sn_u_work_order_assignment` | (affected item) | `sn_cmdb_ci_service` (sys_id) |
| `sn_u_work_order_assignment` | (location ref) | `sn_cmn_location` (sys_id) |
| `sn_sys_user` | `department` | `sn_cmn_department` (sys_id) |
| `sn_sys_user` | `location` | `sn_cmn_location` (sys_id) |
| `sn_sys_user_group` | `parent` | `sn_sys_user_group` (sys_id) |
| `sn_cmn_location` | `parent` | `sn_cmn_location` (sys_id) |
| `sn_cmn_department` | `parent` | `sn_cmn_department` (sys_id) |

### 2.5 Service Table Inheritance Map (CSDM 5)

```
cmdb_ci_service (BASE — parent of all services)
├── cmdb_ci_service_business (Business Service)
├── cmdb_ci_service_technical (Technical/Technology Management Service)
└── cmdb_ci_service_auto (Service Instance in CSDM 5)
    ├── cmdb_ci_service_discovered (top-down / service mapping)
    ├── cmdb_ci_service_tags (tag-based population)
    ├── cmdb_ci_service_calculated (calculated population)
    └── cmdb_ci_query_based_service (query-based / dynamic CI group)

service_offering (separate table, references services via parent field)
```

In our DB:
- `sn_cmdb_ci_service` holds ALL service CIs (SN returns children too when querying parent)
- Each child table (`sn_cmdb_ci_service_business`, etc.) holds ALL fields including inherited ones
- Join parent ↔ child via `sys_id` (shared key)
- `_instance_id` scopes everything per instance

---

## 3. ServiceNow Ingestion Implementation Spec

### 3.1 API Endpoints Used

| Purpose | Endpoint | Method |
|---|---|---|
| **Table data** | `/api/now/table/{table_name}` | GET |
| **Record count** | Same + `sysparm_limit=1` | GET (reads `X-Total-Count` header) |
| **Dictionary metadata** | `/api/now/table/sys_dictionary?sysparm_query=name={table_name}` | GET |
| **Table inheritance** | `/api/now/table/sys_db_object?sysparm_query=name={table_name}` | GET |
| **Validate table exists** | `/api/now/table/sys_db_object?sysparm_query=name={table_name}&sysparm_limit=1` | GET |

### 3.2 Dictionary Extraction Steps

For each table to ingest:

```
Step 1: Validate table exists
  GET /api/now/table/sys_db_object
    ?sysparm_query=name={table_name}
    &sysparm_limit=1
    &sysparm_fields=sys_id,name,label,super_class,sys_package,extension_model,is_extendable
  → If 0 results, table doesn't exist on this instance. Abort.

Step 2: Get inheritance chain
  Follow super_class references up the chain:
  GET /api/now/table/sys_db_object
    ?sysparm_query=sys_id={super_class_sys_id}
    &sysparm_fields=sys_id,name,super_class
  → Build chain: [cmdb_ci_service_business → cmdb_ci_service → cmdb_ci → cmdb → ...]
  → Store parent_table in csdm_table_registry.

Step 3: Get dictionary fields
  GET /api/now/table/sys_dictionary
    ?sysparm_query=name={table_name}
    &sysparm_fields=element,column_label,internal_type,max_length,reference,reference_qual,choice,active,read_only,mandatory
    &sysparm_limit=500
  → This returns fields DEFINED on this table (not inherited).

Step 4: Get inherited fields (walk inheritance chain)
  For each parent in the chain:
    GET /api/now/table/sys_dictionary
      ?sysparm_query=name={parent_table}
      &sysparm_fields=element,column_label,internal_type,max_length,reference,reference_qual,choice
      &sysparm_limit=500
  → Merge: child fields override parent fields with same element name.
  → Result: complete field list for the table.

Step 5: Store field mappings
  For each field:
    - Map SN internal_type → SQLite column type (see §2.3)
    - Record in csdm_field_mapping
    - Flag reference fields (internal_type = 'reference')

Step 6: Create/alter local DB table
  - If table doesn't exist: CREATE TABLE with all columns
  - If table exists but new fields found: ALTER TABLE ADD COLUMN
  - If field type changed: log warning (SQLite can't ALTER COLUMN type)
  - Update schema_version and schema_hash in csdm_table_registry
```

**Optimization**: For the known table list (service tables, foundation tables, etc.), we can batch the dictionary calls: query `sys_dictionary` with `nameIN{table1},{table2},...` to get all fields for multiple tables in fewer API calls.

### 3.3 Delta Query Template

```
For delta pull (most common):
  GET /api/now/table/{table_name}
    ?sysparm_query=sys_updated_on>{last_checkpoint}
      ^ORsys_updated_on={last_checkpoint}^sys_id>{last_sys_id}
    &sysparm_limit={batch_size}                    -- default: 200
    &sysparm_offset=0                              -- always 0 (keyset pagination)
    &sysparm_display_value=false                    -- get sys_ids, not display values
    &sysparm_exclude_reference_link=true            -- reduce payload
    &sysparm_orderby=sys_updated_on,sys_id          -- deterministic ordering

For full refresh:
  GET /api/now/table/{table_name}
    ?sysparm_limit={batch_size}
    &sysparm_offset={offset}                        -- offset pagination for full pull
    &sysparm_display_value=false
    &sysparm_exclude_reference_link=true
    &sysparm_orderby=sys_updated_on,sys_id
```

**Why keyset pagination for deltas**: Offset-based pagination can miss or duplicate records when data changes during the pull. Keyset pagination (using `sys_updated_on > X AND sys_id > Y`) is stable because it's based on the ordering key, not a position. Each batch starts from where the last one ended.

**Why offset pagination for full refresh**: Full refresh is a one-time bulk pull with a clear table first. Offset is simpler and the table is empty so no consistency issues.

### 3.4 Pagination / Batching Rules

| Parameter | Default | Configurable | Rationale |
|---|---|---|---|
| `batch_size` | 200 | Yes (50-1000) | 200 avoids timeouts on most instances |
| `max_retries` | 3 | Yes | Per-batch retry |
| `retry_backoff` | 2s, 5s, 15s | Yes | Exponential |
| `request_timeout` | 30s | Yes | Per HTTP request |
| `inter_batch_delay` | 0.5s | Yes | Rate limiting / politeness |
| `max_batches_per_run` | None (unlimited) | Yes | Safety valve |

### 3.5 Ingestion Engine Pseudocode

```python
def ingest_table(instance_id, sn_table_name, mode='delta', cancel_event=None):
    """
    Core ingestion loop for one table on one instance.
    mode: 'delta' | 'full_refresh'
    cancel_event: threading.Event — set externally to request cancellation
    """
    # 1. Load state
    state = get_or_create_ingestion_state(instance_id, sn_table_name)
    registry = get_table_registry(instance_id, sn_table_name)

    # 2. If schema not yet created, run dictionary extraction first
    if not registry:
        extract_and_create_schema(instance_id, sn_table_name)
        registry = get_table_registry(instance_id, sn_table_name)

    # 3. Build query
    if mode == 'full_refresh':
        clear_table_data(instance_id, sn_table_name)
        state.last_successful_sys_updated_on = None
        state.last_successful_sys_id = None
        query_params = build_full_query(sn_table_name)
    else:  # delta
        query_params = build_delta_query(
            sn_table_name,
            state.last_successful_sys_updated_on,
            state.last_successful_sys_id
        )

    # 4. Start job log
    job = create_job_log(instance_id, sn_table_name, mode)
    state.last_run_status = 'in_progress'
    commit(state, job)

    # 5. Paginated fetch loop
    batch_num = 0
    try:
        while True:
            # Check cancellation
            if cancel_event and cancel_event.is_set():
                job.status = 'cancelled'
                state.last_run_status = 'cancelled'
                break

            # Fetch batch
            records = fetch_batch(instance_id, sn_table_name, query_params, batch_num)

            if not records:
                break  # No more data

            # Upsert batch
            inserted, updated = upsert_batch(instance_id, sn_table_name, records, registry)
            job.rows_inserted += inserted
            job.rows_updated += updated
            job.batches_processed += 1

            # Update checkpoint (last record in this batch)
            last_record = records[-1]
            state.last_successful_sys_updated_on = last_record['sys_updated_on']
            state.last_successful_sys_id = last_record['sys_id']
            commit(state)  # Checkpoint after every batch

            batch_num += 1
            time.sleep(inter_batch_delay)

        # 6. Finalize
        if job.status != 'cancelled':
            job.status = 'completed'
            state.last_run_status = 'success'
            if mode == 'full_refresh':
                state.last_full_refresh_at = now()
            else:
                state.last_delta_at = now()

    except Exception as e:
        job.status = 'failed'
        job.error_message = str(e)
        job.error_stack = traceback.format_exc()
        state.last_run_status = 'failed'
        state.last_error = str(e)

    finally:
        job.completed_at = now()
        state.last_run_completed_at = now()
        state.total_rows_in_db = count_rows(instance_id, sn_table_name)
        commit(state, job)
```

### 3.6 Upsert Logic

```python
def upsert_batch(instance_id, sn_table_name, records, registry):
    """INSERT or UPDATE based on (_instance_id, sys_id) uniqueness."""
    local_table = registry.local_table_name
    field_map = get_field_mappings(registry.id)

    inserted = 0
    updated = 0

    for record in records:
        # Map SN field names to local column names
        row_data = {
            '_instance_id': instance_id,
            '_updated_at': datetime.utcnow().isoformat(),
        }
        for fm in field_map:
            value = record.get(fm.sn_element)
            row_data[fm.local_column] = convert_value(value, fm.db_column_type)

        # Store raw JSON
        row_data['_raw_json'] = json.dumps(record)

        # Try INSERT, on conflict UPDATE
        # SQLite: INSERT ... ON CONFLICT(_instance_id, sys_id) DO UPDATE SET ...
        result = execute_upsert(local_table, row_data)
        if result == 'inserted':
            inserted += 1
        else:
            updated += 1

    return inserted, updated
```

### 3.7 Retry / Backoff

```python
def fetch_batch_with_retry(client, table_name, params, max_retries=3):
    delays = [2, 5, 15]
    for attempt in range(max_retries + 1):
        try:
            return client.get_table_records(table_name, params)
        except ServiceNowClientError as e:
            if attempt == max_retries:
                raise
            if '429' in str(e) or '503' in str(e) or 'timeout' in str(e).lower():
                time.sleep(delays[min(attempt, len(delays)-1)])
            else:
                raise  # Non-retryable error (401, 403, 404)
```

### 3.8 Cancellation Design

```
External:
  - Management UI sends POST /api/csdm/jobs/{instance_id}/cancel?table={table_name}
  - Server sets cancel_event.set() on the running job's threading.Event
  - Also: POST /api/csdm/jobs/{instance_id}/cancel-all (sets all cancel events)

Internal:
  - Ingestion loop checks cancel_event.is_set() before each batch
  - On cancellation:
    1. Current batch is NOT aborted mid-write (completes current batch)
    2. Checkpoint is committed for the last completed batch
    3. Job status set to 'cancelled'
    4. Next run resumes from the last checkpoint (safe)
```

---

## 4. Management UI Spec

### 4.1 Page: CSDM Ingestion (`/csdm/ingestion`)

**Access**: From main nav — new "CSDM Data" menu item.

#### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  CSDM Data Ingestion                                              │
│  Instance: [Dropdown: select instance]                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─── Service Tables (Priority 1) ──────────────────────────────┐ │
│  │ [x] cmdb_ci_service          ● Success  1,234 rows  2m ago  │ │
│  │ [x] cmdb_ci_service_business ● Success    156 rows  2m ago  │ │
│  │ [x] cmdb_ci_service_technical● Success     42 rows  2m ago  │ │
│  │ [x] cmdb_ci_service_auto     ○ Never     — rows    —        │ │
│  │ [x] cmdb_ci_service_discovered ○ Never   — rows    —        │ │
│  │ [x] cmdb_ci_service_tags     ○ Never     — rows    —        │ │
│  │ [x] cmdb_ci_service_calculated ○ Never   — rows    —        │ │
│  │ [x] cmdb_ci_query_based_svc  ○ Never     — rows    —        │ │
│  │ [x] service_offering         ○ Never     — rows    —        │ │
│  │                                                               │ │
│  │ [Start Selected] [Clear+Repull Group] [Cancel Group]         │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌─── Foundation Tables (Priority 2) ───────────────────────────┐ │
│  │ [x] cmn_location             ● Running   batch 3/? ...      │ │
│  │ [x] cmn_department           ◐ Queued    — rows    —        │ │
│  │ [x] sys_user                 ○ Never     — rows    —        │ │
│  │ [x] sys_user_group           ○ Never     — rows    —        │ │
│  │ [x] sys_user_grmember        ○ Never     — rows    —        │ │
│  │                                                               │ │
│  │ [Start Selected] [Clear+Repull Group] [Cancel Group]         │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌─── Process Tables (Priority 3) ──────────────────────────────┐ │
│  │ [x] incident                 ○ Never     — rows    —        │ │
│  │ [x] change_request           ○ Never     — rows    —        │ │
│  │ [x] wm_task                  ○ Never     — rows    —        │ │
│  │                                                               │ │
│  │ [Start Selected] [Clear+Repull Group] [Cancel Group]         │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ┌─── Custom Tables ────────────────────────────────────────────┐ │
│  │ [x] u_work_order_assignment  ● Success  8,432 rows  1h ago  │ │
│  │                                                               │ │
│  │ [Start Selected] [Clear+Repull Group]                        │ │
│  │                                                               │ │
│  │ ┌─ Add Custom Table ──────────────────────────────────────┐  │ │
│  │ │ Table name: [u_____________] [Validate & Add]           │  │ │
│  │ └────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                    │
│  ── Global Actions ──                                              │
│  [Cancel Current Job] [Cancel All Jobs]                            │
│                                                                    │
├──────────────────────────────────────────────────────────────────┤
│  Job Log (last 20 runs)                                            │
│  ┌──────────┬───────────┬────────┬──────┬──────┬──────────────┐   │
│  │ Table    │ Type      │ Status │ Rows │ Time │ Error        │   │
│  ├──────────┼───────────┼────────┼──────┼──────┼──────────────┤   │
│  │ cmn_loc  │ delta     │ ✓ done │ +24  │ 12s  │              │   │
│  │ sys_user │ full      │ ✗ fail │ 0    │ 3s   │ 403 Forbidden│   │
│  │ ...      │           │        │      │      │              │   │
│  └──────────┴───────────┴────────┴──────┴──────┴──────────────┘   │
│  [View Full Log] [Export CSV]                                      │
└──────────────────────────────────────────────────────────────────┘
```

#### 4.2 Status Indicators

| Icon | Status | Meaning |
|---|---|---|
| ● green | `success` | Last run succeeded |
| ● blue / spinner | `running` | Currently ingesting |
| ◐ yellow | `queued` | Waiting for current table to finish |
| ● red | `failed` | Last run failed (hover for error) |
| ◑ grey | `cancelled` | Last run was cancelled |
| ○ empty | `never` | Never ingested |

#### 4.3 Button Actions & API Routes

| Button | API Route | Method | Behavior |
|---|---|---|---|
| **Start Selected** | `POST /api/csdm/ingest` | POST | Body: `{instance_id, tables: [...], mode: 'delta'}`. Queues selected tables for sequential ingestion. |
| **Clear+Repull Table** | `POST /api/csdm/ingest` | POST | Body: `{instance_id, tables: ['cmn_location'], mode: 'full_refresh'}`. Clears local data, repulls everything. |
| **Clear+Repull Group** | `POST /api/csdm/ingest` | POST | Body: `{instance_id, tables: [...all in group...], mode: 'full_refresh'}`. |
| **Cancel Current** | `POST /api/csdm/jobs/{instance_id}/cancel` | POST | Cancels the currently running table job. |
| **Cancel All** | `POST /api/csdm/jobs/{instance_id}/cancel-all` | POST | Cancels current + clears queue. |
| **Validate & Add** (custom) | `POST /api/csdm/custom-tables` | POST | Body: `{instance_id, sn_table_name}`. Validates table exists, fetches dictionary, creates schema. |
| **Refresh Schema** | `POST /api/csdm/schema/refresh` | POST | Body: `{instance_id, sn_table_name}`. Re-fetches dictionary, applies ALTER TABLE if needed. |

#### 4.4 Status Polling

```
GET /api/csdm/status/{instance_id}
→ Returns JSON:
{
  "current_job": {
    "table": "cmn_location",
    "status": "running",
    "batches_processed": 3,
    "rows_so_far": 600,
    "started_at": "2026-02-12T10:30:00Z"
  },
  "queue": ["cmn_department", "sys_user"],
  "tables": [
    {
      "sn_table_name": "cmdb_ci_service",
      "status": "success",
      "row_count": 1234,
      "last_ingested_at": "2026-02-12T10:28:00Z",
      "last_checkpoint": "2026-02-12T10:28:00Z"
    },
    ...
  ]
}
```

**Polling interval**: 3 seconds while any job is running; stop polling when idle.

#### 4.5 Hover Help Text (per UI rule)

Every button has a `title` attribute:

| Button | title |
|---|---|
| Start Selected | "Run delta ingestion for checked tables. Only pulls records updated since last checkpoint." |
| Clear+Repull Table | "Delete all local data for this table and repull everything from ServiceNow." |
| Clear+Repull Group | "Delete all local data for all tables in this group and repull everything." |
| Cancel Current | "Stop the currently running table ingestion after the current batch finishes." |
| Cancel All | "Stop all running and queued ingestion jobs." |
| Validate & Add | "Check that this table exists on the ServiceNow instance, fetch its schema, and register it for ingestion." |
| Refresh Schema | "Re-fetch the table dictionary from ServiceNow and add any new columns." |

---

## 5. Implementation Notes

### 5.1 No Timeouts

- Batch size of 200 keeps each HTTP request under 10 seconds typically.
- `request_timeout=30s` per HTTP call prevents hanging.
- If a batch times out, retry with backoff (2s, 5s, 15s).
- If 3 retries fail, mark job as failed with clear error. Resume is safe from last checkpoint.
- Total ingestion time is unbounded (no global timeout) — the job runs until all records are processed or cancelled.

### 5.2 Table-by-Table Execution

- The ingestion queue processes ONE table at a time within an instance.
- Multiple instances can run in parallel (separate thread per instance).
- Queue is maintained in-memory (list of table names to process).
- If the server restarts, any `in_progress` jobs are detected on startup and reset to `failed` with a message "Server restarted during ingestion". Delta resume picks up from last checkpoint.

### 5.3 Safe Resume

- Every batch commit updates the checkpoint (`last_successful_sys_updated_on` + `last_successful_sys_id`).
- On resume, the delta query starts from the last checkpoint.
- For full refresh: if interrupted mid-pull, the table has partial data. On resume, the user should "Clear + Repull" again.
- Recommendation: track `last_run_status = 'in_progress'` → on next start, warn user "previous run was interrupted" and offer delta resume or full repull.

### 5.4 Token Efficiency (for this spec)

- This spec covers all tables and requirements in the prompt.
- No redundant sections — each topic covered once.
- The dynamic schema approach means adding new tables is just configuration, not code changes.
- The `csdm_table_catalog.py` config file defines the known tables and their priority groups:

```python
# csdm_table_catalog.py
CSDM_TABLE_GROUPS = {
    'service': {
        'label': 'Service Tables',
        'priority': 1,
        'tables': [
            {'name': 'cmdb_ci_service', 'label': 'CI Service (Base)', 'parent': None},
            {'name': 'cmdb_ci_service_business', 'label': 'Business Service', 'parent': 'cmdb_ci_service'},
            {'name': 'cmdb_ci_service_technical', 'label': 'Technical Service', 'parent': 'cmdb_ci_service'},
            {'name': 'cmdb_ci_service_auto', 'label': 'Service Instance (CSDM 5)', 'parent': 'cmdb_ci_service'},
            {'name': 'cmdb_ci_service_discovered', 'label': 'Discovered Service', 'parent': 'cmdb_ci_service_auto'},
            {'name': 'cmdb_ci_service_tags', 'label': 'Tag-Based Service', 'parent': 'cmdb_ci_service_auto'},
            {'name': 'cmdb_ci_service_calculated', 'label': 'Calculated Service', 'parent': 'cmdb_ci_service_auto'},
            {'name': 'cmdb_ci_query_based_service', 'label': 'Query-Based Service', 'parent': 'cmdb_ci_service_auto'},
            {'name': 'service_offering', 'label': 'Service Offering', 'parent': None},
        ]
    },
    'foundation': {
        'label': 'Foundation Tables',
        'priority': 2,
        'tables': [
            {'name': 'cmn_location', 'label': 'Location', 'parent': None},
            {'name': 'cmn_department', 'label': 'Department', 'parent': None},
            {'name': 'sys_user', 'label': 'User', 'parent': None},
            {'name': 'sys_user_group', 'label': 'Group', 'parent': None},
            {'name': 'sys_user_grmember', 'label': 'Group Membership', 'parent': None},
        ]
    },
    'process': {
        'label': 'Process Tables',
        'priority': 3,
        'tables': [
            {'name': 'incident', 'label': 'Incident', 'parent': 'task'},
            {'name': 'change_request', 'label': 'Change Request', 'parent': 'task'},
            {'name': 'wm_task', 'label': 'Work Management Task', 'parent': 'task'},
        ]
    },
    'custom': {
        'label': 'Custom Tables',
        'priority': 4,
        'tables': [
            # u_work_order_assignment is pre-registered here for Weis
            {'name': 'u_work_order_assignment', 'label': 'Work Order Assignment (Weis)', 'parent': None},
        ]
    },
}
```

### 5.5 Custom Table Framework

**Registration flow:**

```
1. User enters table name (e.g., "u_custom_table") in the UI
2. POST /api/csdm/custom-tables {instance_id, sn_table_name: "u_custom_table"}
3. Server:
   a. Validates table name starts with u_ or x_
   b. Calls SN: GET /api/now/table/sys_db_object?sysparm_query=name=u_custom_table&sysparm_limit=1
   c. If not found → return error "Table does not exist on this instance"
   d. Fetches dictionary (same as §3.2 Steps 3-5)
   e. Creates local table (sn_u_custom_table)
   f. Registers in csdm_table_registry with is_custom=1, priority_group='custom'
   g. Creates csdm_ingestion_state row
   h. Returns success → table appears in Custom Tables group on UI
4. User can now select it and run ingestion like any other table
```

**Schema refresh:**
```
POST /api/csdm/schema/refresh {instance_id, sn_table_name}
1. Re-fetch sys_dictionary for the table
2. Compare fields to existing csdm_field_mapping
3. For new fields: ALTER TABLE ADD COLUMN
4. For removed fields: leave column (SQLite can't DROP COLUMN easily), mark inactive in mapping
5. For type changes: log warning (manual intervention needed)
6. Update schema_version, schema_hash
```

### 5.6 Startup Detection / Recovery

On app startup:
```python
def recover_interrupted_jobs():
    """Reset any in_progress jobs from a previous server run."""
    with get_session() as session:
        stuck = session.exec(
            select(CsdmIngestionState)
            .where(CsdmIngestionState.last_run_status == 'in_progress')
        ).all()
        for state in stuck:
            state.last_run_status = 'interrupted'
            state.last_error = 'Server restarted during ingestion. Resume with delta or clear+repull.'
            # Create a job log entry
            log = CsdmJobLog(
                instance_id=state.instance_id,
                sn_table_name=state.sn_table_name,
                job_type='recovery',
                status='interrupted',
                started_at=state.last_run_started_at or datetime.utcnow(),
                completed_at=datetime.utcnow(),
                error_message='Server restart detected'
            )
            session.add(log)
        session.commit()
```

### 5.7 All Tables Checklist (Confirmation)

| # | SN Table | Local Table | Group | Notes |
|---|---|---|---|---|
| 1 | `cmdb_ci_service` | `sn_cmdb_ci_service` | service | Base parent |
| 2 | `cmdb_ci_service_business` | `sn_cmdb_ci_service_business` | service | Business Service |
| 3 | `cmdb_ci_service_technical` | `sn_cmdb_ci_service_technical` | service | Tech Mgmt Service |
| 4 | `cmdb_ci_service_auto` | `sn_cmdb_ci_service_auto` | service | Service Instance (CSDM 5) |
| 5 | `cmdb_ci_service_discovered` | `sn_cmdb_ci_service_discovered` | service | Top-down/service mapping |
| 6 | `cmdb_ci_service_tags` | `sn_cmdb_ci_service_tags` | service | Tag-based |
| 7 | `cmdb_ci_service_calculated` | `sn_cmdb_ci_service_calculated` | service | Calculated |
| 8 | `cmdb_ci_query_based_service` | `sn_cmdb_ci_query_based_service` | service | Query-based |
| 9 | `service_offering` | `sn_service_offering` | service | Service Offering |
| 10 | `cmn_location` | `sn_cmn_location` | foundation | All fields + hierarchy |
| 11 | `cmn_department` | `sn_cmn_department` | foundation | |
| 12 | `sys_user` | `sn_sys_user` | foundation | |
| 13 | `sys_user_group` | `sn_sys_user_group` | foundation | |
| 14 | `sys_user_grmember` | `sn_sys_user_grmember` | foundation | Membership M2M |
| 15 | `incident` | `sn_incident` | process | |
| 16 | `change_request` | `sn_change_request` | process | |
| 17 | `wm_task` | `sn_wm_task` | process | |
| 18 | `u_work_order_assignment` | `sn_u_work_order_assignment` | custom | Weis-specific |

**18 tables total.** All tables from the requirements are included.

---

## Appendix A: CSDM 5 Reference Notes

- **Business Service** (`cmdb_ci_service_business`): Represents a service consumed by business users. Maps to "Business Capability" in CSDM.
- **Technical Service** (`cmdb_ci_service_technical`): Renamed to "Technology Management Service" in CSDM 5. Represents the IT-managed service.
- **Service Instance** (`cmdb_ci_service_auto`): In CSDM 5, this replaces the older "Application Service" concept. It's the runtime instance of a service.
- **Application Service subtypes**: The `_discovered`, `_tags`, `_calculated`, and `_query_based` tables represent different methods for populating the service instance with CIs. They extend `cmdb_ci_service_auto`.
- **Service Offering** (`service_offering`): Represents a specific offering of a business service (e.g., "Email - Standard", "Email - Premium"). References the parent business service.

## Appendix B: Critical Structural Call-Outs

1. **`cmdb_ci_service` returns child records too**: When you query the parent table via SN Table API, it returns ALL records including child class instances (business, technical, auto, etc.). This means `sn_cmdb_ci_service` will contain a superset. The child tables contain the same rows but with additional extension fields. This is correct behavior — do NOT deduplicate.

2. **`sys_user_grmember` is a M2M table**: It has `user` (→ sys_user.sys_id) and `group` (→ sys_user_group.sys_id) as reference fields. Both must be indexed.

3. **`u_work_order_assignment` field names are unknown**: Since it's a custom table, exact field names will be discovered via dictionary extraction. The prompt mentions `u_assignment_group`, but all reference fields will be auto-detected and indexed.

4. **`cmn_location` has self-referential hierarchy**: The `parent` field references another `cmn_location` record. Same for `cmn_department` and `sys_user_group`.

5. **Process tables (`incident`, `change_request`, `wm_task`) extend `task`**: We do NOT ingest the `task` base table (too large, too generic). Each child table returns all inherited fields from `task` naturally.
