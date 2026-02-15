# Assessment Form Wireframe & Scan Mapping

> Generated 2026-02-15 — traces every form input to backend data pulls

---

## Form Layout (assessment_form.html)

```
┌─────────────────────────────────────────────────────────────────┐
│  New Assessment                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ── Basic Information ────────────────────────────────────────  │
│                                                                 │
│  Assessment Name     [_________________________________________]│
│                      e.g., Incident Management Assessment Q1    │
│                                                                 │
│  Description         [_________________________________________]│
│                      (optional)               textarea, 3 rows  │
│                                                                 │
│  ServiceNow Instance [▼ -- Select Instance --                 ] │
│                      Drives: app_file_class options,            │
│                              all subsequent SN API calls        │
│                                                                 │
│  ── Assessment Type ──────────────────────────────────────────  │
│                                                                 │
│  Type                [▼ Global Application (Incident, etc.)   ] │
│                        ├─ Global Application ──→ shows target_app_id   │
│                        ├─ Specific Tables    ──→ shows target_tables   │
│                        ├─ Plugin/Package     ──→ shows target_plugins  │
│                        └─ Platform Global    ──→ no extra field        │
│                                                                 │
│  ┌─ conditional: global_app ──────────────────────────────────┐ │
│  │ Target Application  [▼ -- Select Application --           ]│ │
│  │                     Incident | Change | Problem | Request  │ │
│  │                     Knowledge | CMDB | Asset | SLA | etc.  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ conditional: table ───────────────────────────────────────┐ │
│  │ Target Tables       [incident, change_request, problem    ]│ │
│  │                     comma-separated table names            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─ conditional: plugin ──────────────────────────────────────┐ │
│  │ Target Plugins      [com.snc.incident, com.snc.change     ]│ │
│  │                     comma-separated plugin IDs             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ── Application File Types to Scan ───────────────────────────  │
│                                                                 │
│  ┌─── Available Types ───┐  ┌──┐  ┌── Selected Types ────────┐ │
│  │ sys_report            │  │ >│  │ sys_script              │ │
│  │ sys_data_policy2      │  │>>│  │ sys_script_client       │ │
│  │ sp_widget             │  │ <│  │ sys_script_include      │ │
│  │ sp_page               │  │<<│  │ sys_ui_policy           │ │
│  │ sys_choice             │  └──┘  │ sys_ui_action           │ │
│  │ wf_workflow            │        │ sys_dictionary          │ │
│  │ (more...)             │        │ wf_workflow              │ │
│  └────────────────────────┘        └──────────────────────────┘ │
│  Populated from: InstanceAppFileType (per-instance SN pull)     │
│  Defaults: is_default_for_assessment=True rows                  │
│                                                                 │
│  ── Scope Filter ─────────────────────────────────────────────  │
│                                                                 │
│  Scope               [▼ Global Scope Only                     ] │
│                        ├─ Global Scope Only                     │
│                        └─ All Scopes                            │
│                                                                 │
│  [Create Assessment]  [Cancel]                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Input → Backend Mapping

### 1. `instance_id` (required)

| What it drives | Where |
|---|---|
| All ServiceNow API calls use this instance's credentials | `sn_client.py` |
| App file class list collector populated from this instance | `GET /api/instances/{id}/app-file-classes` |
| Preflight data cached per-instance | `instance_data_pull` table |

### 2. `assessment_type` (required)

Determines which **drivers** feed scan query construction:

| Type | Required Fields | Drivers | scan_rules.yaml ref |
|---|---|---|---|
| `global_app` | `target_app_id`, `app_file_classes` | `core_tables` + `keywords` from GlobalApp | lines 6-17 |
| `table` | `target_tables`, `app_file_classes` | user-entered table names | lines 19-29 |
| `plugin` | `target_plugins`, `app_file_classes` | plugin sys_ids | lines 31-40 |
| `platform_global` | `app_file_classes` | none (broad scan) | lines 42-50 |

### 3. `target_app_id` (conditional — global_app only)

Maps to a `GlobalApp` row which contains:
- `core_tables_json` — e.g. `["incident"]` or `["change_request", "change_task"]`
- `keywords_json` — e.g. `["incident", "inc"]`
- `plugins_json` — related plugin references

Plus `global_app_overrides` in `scan_rules.yaml:137-234` may add extra tables/keywords.

**Example**: Selecting "Incident" resolves to:
- **Tables**: `incident`, `incident_task`
- **Keywords**: `incident`, `inc`, `major incident`

### 4. `target_tables` (conditional — table type only)

Comma-separated table names entered directly. Each becomes a scan driver.

### 5. `target_plugins` (conditional — plugin type only)

Comma-separated plugin IDs. Used to scope scans to plugin-owned artifacts.

### 6. `app_file_classes` (list collector)

Each selected class generates **one or more scans** against `sys_metadata`.
The query pattern depends on the class — defined in `scan_rules.yaml:69-108`:

| File Class | Has Table Pattern? | Has Keyword Pattern? | Query Pattern |
|---|---|---|---|
| `sys_script` | Yes | No | `ref_sys_script.collectionLIKE{table}` |
| `sys_script_client` | Yes | No | `ref_sys_script_client.tableLIKE{table}` |
| `sys_ui_policy` | Yes | No | `ref_sys_ui_policy.tableLIKE{table}` |
| `sys_ui_action` | Yes | No | `ref_sys_ui_action.tableLIKE{table}` |
| `sys_ui_policy_action` | Yes | No | `ref_sys_ui_policy_action.ui_policy.tableLIKE{table}` |
| `sys_data_policy2` | Yes | No | `ref_sys_data_policy2.tableLIKE{table}` |
| `wf_workflow` | Yes | No | `ref_wf_workflow.tableLIKE{table}` |
| `sys_report` | Yes | No | `ref_sys_report.tableLIKE{table}` |
| `sys_dictionary` | Yes | No | `ref_sys_dictionary.nameSTARTSWITH{table}.` |
| `sys_choice` | Yes | No | `ref_sys_choice.nameSTARTSWITH{table}.` |
| `sys_script_include` | No | Yes | `nameLIKE{keyword} OR scriptLIKE{keyword}` |
| `sp_widget` | No | Yes | `123TEXTQUERY321={keyword}` |
| `sp_page` | No | Yes | `123TEXTQUERY321={keyword}` |

**Scan multiplication**: If you select 5 file classes and have 2 target tables, you get up to 10+ scans (table-based classes × tables, plus keyword classes × keywords).

### 7. `scope_filter`

| Value | Effect on sys_metadata query | scan_rules.yaml ref |
|---|---|---|
| `global` | Appends `sys_scope={global_scope_id}` | lines 119-122 |
| `all` | No scope filter (returns all scopes) | lines 123-125 |

---

## Scan Execution Pipeline

```
Assessment Created (state=pending)
         │
         ▼
   "Run Scans" clicked
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 1: Required Preflight Sync (blocking, 15min) │
│                                                     │
│  ┌─────────────────────┬──────────────────────────┐ │
│  │ Data Type           │ SN Table                 │ │
│  ├─────────────────────┼──────────────────────────┤ │
│  │ metadata_custom...  │ sys_metadata_custom...   │ │
│  │ app_file_types      │ sys_app_file_type        │ │
│  │ version_history*    │ sys_update_version       │ │
│  │ customer_update_xml │ sys_update_xml           │ │
│  │ update_sets         │ sys_update_set           │ │
│  └─────────────────────┴──────────────────────────┘ │
│  * version_history pulls state=current only here    │
│                                                     │
│  WHY: Classification engine needs this data locally │
│  to determine OOTB vs custom for each scan result   │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 2: Create & Execute Scans                    │
│                                                     │
│  resolve_assessment_drivers()                       │
│    ├─ global_app → GlobalApp.core_tables_json       │
│    │              + scan_rules global_app_overrides  │
│    ├─ table      → target_tables_json               │
│    ├─ plugin     → target_plugins_json              │
│    └─ platform   → (no table drivers)               │
│         │                                           │
│         ▼                                           │
│  create_scans_for_assessment()                      │
│    FOR EACH app_file_class in selected:             │
│      IF class has table pattern:                    │
│        FOR EACH target_table:                       │
│          → Create Scan(metadata_index,              │
│              query=pattern.format(table))           │
│      IF class has keyword pattern:                  │
│        FOR EACH keyword:                            │
│          → Create Scan(metadata_index,              │
│              query=keyword_pattern.format(keyword)) │
│         │                                           │
│         ▼                                           │
│  execute_scan() for each Scan:                      │
│    1. Query SN sys_metadata with encoded_query      │
│    2. For each result record:                       │
│       ├─ Check MetadataCustomization (local DB)     │
│       ├─ Lookup VersionHistory (local DB)           │
│       ├─ Lookup CustomerUpdateXML (local DB)        │
│       └─ Classify → origin_type:                    │
│           ├─ modified_ootb                           │
│           ├─ ootb_untouched                          │
│           ├─ net_new_customer                        │
│           └─ unknown                                 │
│    3. Store in ScanResult table                     │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 3: Optional Preflight (fire & forget)        │
│                                                     │
│  ┌─────────────────────┬──────────────────────────┐ │
│  │ plugins             │ sys_plugins / v_plugin   │ │
│  │ plugin_view         │ v_plugin                 │ │
│  │ scopes              │ sys_scope                │ │
│  │ packages            │ sys_package              │ │
│  │ applications        │ sys_app                  │ │
│  │ sys_db_object       │ sys_db_object            │ │
│  └─────────────────────┴──────────────────────────┘ │
│                                                     │
│  WHY: Enrichment data for results/reporting, not    │
│  needed for scan execution itself                   │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  STAGE 4: Version History Catchup                   │
│                                                     │
│  Pull full sys_update_version (all states, not      │
│  just current) for complete origin traceability     │
└─────────────────────────────────────────────────────┘
```

---

## Backend File Reference

| Concern | File | Key Lines |
|---|---|---|
| Form template | `src/web/templates/assessment_form.html` | 1-301 |
| Assessment model | `src/models.py` | 217-265 |
| GlobalApp model | `src/models.py` | 271-298 |
| InstanceAppFileType model | `src/models.py` | 330-378 (approx) |
| Scan / ScanResult models | `src/models.py` | 384-510 (approx) |
| Create assessment POST | `src/server.py` | ~3004-3069 |
| App file class options | `src/server.py` | ~1269-1335 |
| Preflight required types | `src/server.py` | 964-972 |
| Run scans background | `src/server.py` | ~1592-1666 |
| Resolve assessment drivers | `src/services/query_builder.py` | ~42-88 |
| Build metadata queries | `src/services/query_builder.py` | ~153-217 |
| Create scans for assessment | `src/services/scan_executor.py` | ~563-639 |
| Execute scan + classify | `src/services/scan_executor.py` | ~642-949 |
| Data pull specs (all types) | `src/services/data_pull_executor.py` | 1607-1833 |
| Scan rules / query patterns | `config/scan_rules.yaml` | 1-234 |
| Global app overrides | `config/scan_rules.yaml` | 137-234 |

---

## Data Flow Diagram

```
  FORM INPUTS                    BACKEND RESOLUTION              SN API QUERIES
  ──────────                    ──────────────────              ──────────────

  instance_id ──────────────────→ credentials + base URL ──────→ all API calls

  assessment_type ──┐
                    ├──→ resolve_assessment_drivers()
  target_app_id ────┤     │
  target_tables ────┤     ├─→ target_tables[]     ─┐
  target_plugins ───┘     └─→ keywords[]           │
                                                   │
  app_file_classes[] ──────→ scan_rules.yaml ──────┤
                              │                    │
                              ├─ table_pattern?  ──┤──→ Scan per (class × table)
                              └─ keyword_pattern?──┘──→ Scan per (class × keyword)
                                                         │
                                                         ▼
  scope_filter ────────────→ sys_scope condition ──→ appended to each Scan query

                                                         │
                                                         ▼
                                                   sys_metadata API call
                                                   with encoded_query
                                                         │
                                                         ▼
                                                   Classification engine
                                                   (uses local preflight cache)
                                                         │
                                                         ▼
                                                   ScanResult rows
```
