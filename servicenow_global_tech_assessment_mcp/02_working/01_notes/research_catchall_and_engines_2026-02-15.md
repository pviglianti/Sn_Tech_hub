# Research: Catch-All Label Table + Deterministic Engines

Date: 2026-02-15
Owner: Claude
Status: Research complete, ready for PV review + design approval

---

## 1. Catch-All Label Table

### Problem
The expert prompt says: group ungrouped records under catch-all buckets by "app file class type" (e.g., "Form Fields" for dictionary entries). We need a mapping from `sys_class_name` → assessment-friendly bucket label.

### What Already Exists
- `APP_FILE_CLASS_CATALOG` in [app_file_class_catalog.py](tech-assessment-hub/src/app_file_class_catalog.py) — 27 class types with **ServiceNow system labels** (e.g., "Dictionary Entry", "Access Control (ACL)")
- `get_class_label()` in [artifact_detail_defs.py](tech-assessment-hub/src/artifact_detail_defs.py) — looks up class label from catalog
- `InstanceAppFileType` model — caches per-instance class types with labels

### What's Missing
PV wants **assessment-friendly bucket labels**, not SN system labels. Key differences:

| sys_class_name | SN System Label | PV's Bucket Label |
|---|---|---|
| sys_dictionary | Dictionary Entry | Form Fields |
| sys_dictionary_override | Dictionary Override | Form Fields |
| sys_choice | Choice List | Form Fields |
| sys_security_acl | Access Control (ACL) | ACLs |
| sysevent_email_action | Email Notification | Notifications |
| sys_ui_policy | UI Policy | UI Policies |
| sys_ui_policy_action | UI Policy Action | UI Policies |

Key difference: **multiple class types can map to the same bucket** (grouping, not 1:1).

### Design Proposal

**Option A: Add `catch_all_bucket` field to `APP_FILE_CLASS_CATALOG`** (Simplest)
- Add a `"bucket_label"` key to each catalog entry
- Default = the existing `label` value
- Override where PV wants a different grouping name
- Multiple classes can share the same bucket_label
- Make it user-configurable via integration properties later

**Option B: Separate mapping table in AppConfig** (More flexible)
- Store as a JSON config property (like bridge config)
- Editable from the properties page
- Independent of the class catalog

**Option C: New DB model `CatchAllBucketLabel`** (Most complex)
- Dedicated table with sys_class_name → bucket_label rows
- Full CRUD from UI
- Overkill for what is essentially a label mapping

**Recommendation**: Option A. It follows "reuse before create" — the catalog already tracks all class types. Adding one field is minimal. We can make it user-configurable later via properties if needed.

### Proposed Default Bucket Mappings

```
Business Rules        → sys_script
Script Includes       → sys_script_include
Client Scripts        → sys_script_client
UI Policies           → sys_ui_policy, sys_ui_policy_action
UI Actions            → sys_ui_action
UI Pages              → sys_ui_page, sys_ui_macro
Form Fields           → sys_dictionary, sys_dictionary_override, sys_choice
Tables                → sys_db_object
Data Policies         → sys_data_policy2
ACLs                  → sys_security_acl
Scheduled Jobs        → sysauto_script
Notifications         → sysevent_email_action, sysevent_script_action
Flows                 → sys_hub_flow
Workflows             → wf_workflow
Portal Widgets        → sp_widget, sp_page
Transform Maps        → sys_transform_map
REST APIs             → sys_web_service
Form/List Layouts     → sys_ui_form, sys_ui_list, sys_ui_related_list
Reports               → sys_report
```

---

## 2. Update Set Overlap Analysis Engine

### Problem
The strongest grouping signal (+3 weight) is "same update set." We need a deterministic engine that finds which customized records share update sets — revealing what was built together.

### Data Available Locally

| Table | Source | Key Fields |
|---|---|---|
| `update_set` | sys_update_set | name, state, is_default, sys_created_by, sys_created_on |
| `customer_update_xml` | sys_update_xml | update_set_id (FK), name (sys_update_name), table, target_sys_id, category, action |
| `version_history` | sys_update_version | sys_update_name, state ("current"), source_table, update_guid |
| `scan_result` | assessment scan | origin_type, table_name, sys_update_name, update_set_id |

### Relationships
```
UpdateSet ──1:N──> CustomerUpdateXML (update_set_id FK)
                    └── Each row = one change to one artifact in that update set

ScanResult ──FK──> UpdateSet (update_set_id, optional)
ScanResult ──FK──> CustomerUpdateXML (customer_update_xml_id, optional)

VersionHistory ──match──> CustomerUpdateXML (via update_guid or sys_update_name)
```

### Core Queries the Engine Needs

**Q1: For a given scan result, what update sets contain changes to this artifact?**
```sql
SELECT DISTINCT us.id, us.name, us.state, us.is_default,
       us.sys_created_by, us.sys_created_on
FROM customer_update_xml cux
JOIN update_set us ON cux.update_set_id = us.id
WHERE cux.name = :sys_update_name  -- artifact identifier
  AND us.instance_id = :instance_id
ORDER BY us.sys_created_on
```

**Q2: For those update sets, what OTHER customized scan results share them?**
```sql
SELECT sr.id, sr.table_name, sr.record_name, sr.origin_type,
       us.name as update_set_name, us.id as update_set_id
FROM scan_result sr
JOIN customer_update_xml cux ON sr.customer_update_xml_id = cux.id
                              OR sr.update_set_id = cux.update_set_id
JOIN update_set us ON cux.update_set_id = us.id
WHERE us.id IN (:update_set_ids)
  AND sr.origin_type IN ('modified_ootb', 'net_new_customer')
  AND sr.id != :source_scan_result_id
ORDER BY us.sys_created_on, sr.sys_updated_on
```

**Q3: Cross-update-set overlap — which update sets share artifacts?**
```sql
-- Artifacts that appear in multiple update sets (strong grouping signal)
SELECT cux.name as sys_update_name,
       COUNT(DISTINCT us.id) as update_set_count,
       GROUP_CONCAT(DISTINCT us.name) as update_set_names
FROM customer_update_xml cux
JOIN update_set us ON cux.update_set_id = us.id
WHERE us.instance_id = :instance_id
  AND cux.category = 'customer'
GROUP BY cux.name
HAVING COUNT(DISTINCT us.id) > 1
ORDER BY update_set_count DESC
```

### MCP Tool Design

**Tool name**: `analyze_update_set_overlap`

**Inputs**:
- `instance_id` (required) — which instance
- `scan_result_id` (optional) — analyze overlap for a specific record
- `update_set_id` (optional) — analyze all records in a specific update set
- `mode` (optional) — "for_record" | "for_update_set" | "full_overlap_report"

**Outputs**:
- List of overlapping records grouped by update set
- Confidence scores based on grouping signal weights
- For each overlap: the update set name, the shared artifacts, temporal proximity

### Implementation Notes
- This is a **read-only deterministic engine** — no judgment, just data aggregation
- Results feed into the AI's grouping decisions (the AI handles judgment)
- Should handle Default update set separately (lower confidence, use temporal proximity)
- Should filter to customized records only (origin_type = modified_ootb or net_new_customer)

---

## 3. Other Deterministic Engines (Brief Scoping)

### Temporal Clustering
- **Query**: ScanResult grouped by `sys_created_by` + time window on `sys_updated_on`
- **Signal weight**: +1 (weak alone, stronger with other signals)
- **Key**: Tight time windows (minutes/hours, not days)

### Reference Graph (Code Cross-References)
- **Query**: Parse `raw_data` JSON for script fields, extract patterns (`new ClassName()`, `GlideRecord('table')`, `gs.include('name')`)
- **Signal weight**: +4 direct, +2 transitive
- **Complexity**: Regex parsing of ServiceNow JavaScript — medium effort
- **Note**: This is the only engine that needs to read actual script content

### Table Co-Location
- **Query**: ScanResult grouped by `table_name` (the target table of the customization)
- **Signal weight**: +1 (medium signal, needs secondary signals to split large tables)
- **Key**: Custom tables (x_ prefix) are stronger signal than standard tables (incident, task)

---

## Recommended Priority Order

1. **Catch-all label table** — small, concrete, enables the expert prompt's catch-all bucket feature
2. **Update set overlap engine** — strongest grouping signal, most data already available
3. **Table co-location engine** — simple query, complements update set overlap
4. **Temporal clustering engine** — simple query, useful for Default update set records
5. **Reference graph engine** — most complex (script parsing), highest value per-record
