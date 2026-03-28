# Reference Trace Enrichment — Design Spec

**Date:** 2026-03-28
**Purpose:** Add a new `enrichment` pipeline stage that traces code references from scanned artifacts to discover related customizations on out-of-scope tables, queries ServiceNow to pull those artifacts, and inserts them as adjacent scan results for the engines to process.

---

## 1. Motivation

When an assessment targets specific tables (incident, incident_task, etc.), the initial scan only captures artifacts directly on those tables. But customizations frequently reference other tables — a business rule on `incident` might query `contract_sla`, which itself has customized business rules, UI policies, and ACLs. Without tracing those references, the assessment misses related artifacts that should be grouped together or flagged as dependencies.

Snow-flow's `snow_table_schema_discovery` tool demonstrates this pattern: given a table, discover everything attached to it (fields, relationships, ACLs, business rules, UI policies). We adapt this for our assessment pipeline — but driven by code references rather than manual table selection.

## 2. Scope

- New pipeline stage: `enrichment` between `scans` and `engines`
- Lightweight regex parsing of code fields in scan results to extract table/script/event/REST references
- SN instance queries to pull customized artifacts from discovered out-of-scope tables
- New enrichment scan with discovered artifacts flagged as `is_adjacent=True`
- Configurable exclusion list, depth limit, and per-table artifact cap
- No new database models — uses existing Scan, ScanResult, and properties system

## 3. Pipeline Integration

New stage order (11 stages):
```
scans → enrichment → engines → ai_analysis → observations → review → grouping → ai_refinement → recommendations → report → complete
```

- Stage advances manually (like all other stages)
- User sees summary: "Enrichment: Discovered 12 adjacent artifacts across 4 tables"
- If no out-of-scope references found, completes instantly: "No additional artifacts discovered"
- Requires SN credentials (same authenticated client pattern as scan executor)
- Idempotent: re-running deletes previous enrichment scan + results for this assessment

## 4. Discovery Logic

### Step 1: Collect in-scope tables

Load all scan results for the assessment. Collect distinct `table_name` values — these are the "in-scope tables" (implicitly defined by what was scanned).

### Step 2: Parse references from scan results

Lightweight regex scan of code fields across ALL scan results (not just customized — an OOTB artifact might reference a table where customizations live).

Code fields to parse from `raw_data_json`:
- `script`
- `code_body`
- `meta_code_body`
- `condition`
- `client_script`
- `server_script`
- `template`
- `css` (unlikely but included for completeness)

Reference patterns:

| Pattern | Reference Type | Extracts |
|---------|---------------|----------|
| `new GlideRecord\(['"](\w+)['"]\)` | table_query | table name |
| `GlideAggregate\(['"](\w+)['"]\)` | table_query | table name |
| `new (\w+)\(` where starts with uppercase | script_include | class name |
| `gs\.include\(['"]([^'"]+)['"]\)` | script_include | script name |
| `gs\.eventQueue\(['"]([^'"]+)['"]` | event | event name |
| `new sn_ws\.RESTMessageV2\(['"]([^'"]+)['"]` | rest_message | REST message name |
| `GlideAjax\(['"]([^'"]+)['"]\)` | script_include | AJAX script name |
| Dot-walk fields: `current\.(\w+)\.(\w+)` | field_reference | intermediate table (lookup from raw_data_json field definitions or sys_dictionary if available locally) |

### Step 3: Determine out-of-scope tables

- Collect all table names extracted from references
- For script_include references: resolve to the table the script include operates on (if detectable from `collection` field in scan data), otherwise skip — script includes themselves are typically already scanned
- For event references: resolve to the table the event is registered on (if detectable), otherwise skip
- For rest_message references: skip — REST messages don't map to SN tables
- Subtract `in_scope_tables` (already represented in scan results)
- Subtract `excluded_tables` (configurable, see defaults below)
- Result = `tables_to_trace`

### Step 4: Query SN for artifacts on discovered tables

For each table in `tables_to_trace`, execute up to 6 queries:

| Query | SN API Endpoint | Query Filter | What it finds |
|-------|----------------|--------------|---------------|
| Business rules | `GET /api/now/table/sys_script` | `collection={table}` | Server-side scripts |
| Client scripts | `GET /api/now/table/sys_script_client` | `table={table}` | Form client scripts |
| UI policies | `GET /api/now/table/sys_ui_policy` | `table={table}` | Display/behavior policies |
| UI actions | `GET /api/now/table/sys_ui_action` | `table={table}` | Buttons, links, menu items |
| ACLs | `GET /api/now/table/sys_security_acl` | `nameLIKE{table}` | Access control rules |
| Dictionary overrides | `GET /api/now/table/sys_dictionary_override` | `name={table}` | Field customizations |

Each query:
- `sysparm_limit` = `max_artifacts_per_table` (default 50)
- `sysparm_fields` = standard fields needed for ScanResult creation (sys_id, name, sys_class_name, sys_update_name, sys_scope, sys_package, active, etc.)
- Pull ALL artifacts (not just customized) — let existing origin classification sort them during engines stage

### Step 5: Create enrichment scan and insert artifacts

- Create a new `Scan` row with `scan_type` = `enrichment`, linked to the same assessment
- For each discovered artifact, create a `ScanResult` row:
  - `scan_id` = enrichment scan ID
  - `is_adjacent` = `True`
  - `sys_id`, `table_name`, `name`, `display_value` from SN response
  - `origin_type` = `None` (classification happens during engines stage)
  - `raw_data_json` = full SN response for the artifact (for code parsing by engines)
- Deduplicate: skip artifacts whose `sys_id` + `table_name` already exist in any scan for this assessment

### Step 6: Return summary

```python
{
    "success": True,
    "tables_in_scope": 5,
    "references_found": 23,
    "tables_to_trace": ["contract_sla", "cmn_schedule", "sys_email"],
    "tables_excluded": ["sys_user", "task"],
    "artifacts_discovered": 12,
    "enrichment_scan_id": 42,
    "errors": []
}
```

## 5. Error Handling

- If SN credentials are missing/invalid: fail the stage with clear error message
- If a query for a specific table fails: log the error, continue with remaining tables, include in `errors` list
- If ALL queries fail: stage fails but preserves any partially-created enrichment scan
- Partial discovery is better than none — never roll back successful queries because a later one failed

## 6. Configuration

Via the existing properties system (`integration_properties.py`):

| Property Key | Default | Description |
|-------------|---------|-------------|
| `enrichment.enabled` | `true` | Enable/disable enrichment stage |
| `enrichment.max_trace_depth` | `1` | Hops to trace (1 = direct references only) |
| `enrichment.max_artifacts_per_table` | `50` | Maximum artifacts to pull per discovered table |
| `enrichment.excluded_tables` | JSON list (see below) | Tables to never trace into |

**Default exclusion list:**
```json
[
    "sys_user", "sys_user_group", "task", "sys_dictionary",
    "sys_db_object", "sys_choice", "sys_metadata", "sys_update_xml",
    "sys_glide_object", "sys_properties", "sys_number",
    "sys_documentation", "sys_translated_text"
]
```

These are ubiquitous platform tables referenced by nearly everything — tracing into them would explode scope without useful signal.

## 7. Pipeline Stage Handler

New file: `src/mcp/tools/pipeline/run_enrichment.py`

Follows the same pattern as `run_engines.py`:
- `handle(params, session)` function
- `TOOL_SPEC` with input schema (`assessment_id` required)
- Progress tracking via `start_phase_progress` / `checkpoint_phase_progress`
- Authenticated SN client from instance credentials

The handler orchestrates:
1. Load scan results and collect in-scope tables
2. Parse references (lightweight regex, internal helper functions)
3. Filter to out-of-scope tables
4. Query SN (using instance credentials from the assessment's linked Instance)
5. Create enrichment scan + results
6. Commit and return summary

## 8. ScanType Extension

Add `enrichment` to the `ScanType` enum in `models.py`:
```python
class ScanType(str, Enum):
    metadata = "metadata"
    # ... existing types ...
    enrichment = "enrichment"
```

## 9. Testing Strategy

- Unit tests for regex reference parsing (each pattern type with positive/negative cases)
- Unit tests for table filtering logic (in-scope removal, exclusion list, deduplication)
- Integration test: mock SN responses, verify enrichment scan + scan results created correctly
- Integration test: idempotency (re-run deletes old enrichment, creates new)
- Integration test: partial failure (one table query fails, others succeed)
- Edge cases: no code references found, all references to in-scope tables, all references to excluded tables, empty scan results
- Test that `is_adjacent=True` is set on all discovered artifacts
- Test deduplication (artifact already exists in original scan)
