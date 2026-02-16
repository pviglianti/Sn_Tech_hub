"""Assessment reference resources for MCP (Phase 3).

These resources expose domain knowledge as URI-addressable documents the AI
can read on-demand. Content is condensed from the assessment guide v3,
grouping signals doc, and AI reasoning pipeline domain knowledge. Schema
resources are derived from the SQLModel definitions.
"""

from typing import List

from ..registry import ResourceSpec

# ── 1. Classification Rules ─────────────────────────────────────────


def _classification_rules() -> str:
    return """\
# Origin Classification Rules

## Two Detection Methods

### 1. Update Version History Method (sys_update_version)
Examines version history of each metadata record to determine ownership:

- Finds the **current** version (state="current") or latest by timestamp
- Checks `source_table` to determine origin:
  - **OOB sources**: `sys_upgrade_history`, `sys_store_app` → vendor-provided
  - **Customer sources**: `sys_update_set`, `sys_remote_update_set` → customer-modified

### 2. Baseline Comparison Method (SncAppFiles.hasCustomerUpdate)
Compares current state against ServiceNow's vendor baseline:

- Returns true if the record differs from its original baseline
- Catches modifications even when version history is incomplete

## Decision Tree

```
IF any OOB version exists (source from sys_upgrade_history or sys_store_app):
  IF any customer signals (customer versions, baseline changed, metadata customization):
    → modified_ootb
  ELSE:
    → ootb_untouched
ELSE:
  IF any customer signals (customer versions, baseline changed):
    → net_new_customer
  ELSE IF no version history at all:
    → unknown_no_history
  ELSE:
    → unknown (has history but unclassifiable — anomaly)
```

## Origin Types

| origin_type | head_owner | Meaning |
|---|---|---|
| `modified_ootb` | Store/Upgrade | OOB record with customer modifications |
| `ootb_untouched` | Store/Upgrade | Pristine OOB, no customer changes |
| `net_new_customer` | Customer | Created entirely by customer |
| `unknown` | Unknown | Version history exists but can't classify (anomaly) |
| `unknown_no_history` | Unknown | No version history — see investigation below |

## Investigating unknown_no_history Records

Records without version history may be:

- **Pre-version-tracking OOB files**: Older platforms (pre-Aspen) didn't capture \
baselines for unmodified OOB files
- **Customer files created via scripts/imports**: Bypassed normal update tracking

**Heuristic**: Check `created_by_in_user_table`:
- Creator NOT in sys_user → likely OOB (e.g., "fred.luddy", "maint", "system")
- Creator IN sys_user → likely customer-created
- Note: "admin" exists in user table but is commonly an OOB creator

## Key Fields on ScanResult

| Field | Source | Purpose |
|---|---|---|
| `origin_type` | Combined methods | Classification result |
| `head_owner` | Version history | Who owns the current version |
| `changed_baseline_now` | Baseline check | True if differs from vendor baseline |
| `current_version_source_table` | Version history | Source table of head version |
| `current_version_source` | Version history | Display value of source record |
| `created_by_in_user_table` | User lookup | For unknown_no_history investigation |
"""


# ── 2. Grouping Signals ─────────────────────────────────────────────


def _grouping_signals() -> str:
    return """\
# Feature Grouping Signals

## The Problem
Given thousands of customized records across dozens of tables, identify which \
records belong together as a "feature" delivering a specific business capability.

## Signal Categories

### 1. Update Set Cohorts (STRONG)
Records captured in the same update set were likely changed for the same purpose.
- Multiple update sets with similar names → larger feature
- Cross-update-set version history: if US1 touches records A,B,C and US66 also \
touches B,C → same feature. This is a very strong indicator.
- "Default" update set: lower confidence — use temporal proximity within it.

### 2. Table Affinity (MEDIUM)
Multiple customizations targeting the same table may be related.
- Combine with temporal proximity and naming for higher confidence.
- Large tables (incident, task) may have many unrelated customizations — need \
secondary signals to split.

### 3. Naming Conventions (MEDIUM-STRONG)
Consistent prefixes/suffixes: `u_custom_approval_*`, `ACME_*`, `Project_X_*`.
- Tokenize names, find common n-grams.
- Weight by specificity (longer prefix = stronger).

### 4. Code Cross-References (STRONG)
If code in record A calls/references record B, they're related.
- `new ClassName()` → Script include reference
- `GlideRecord('table_name')` → Table reference
- `gs.include('name')` → Script include reference
- `gs.eventQueue('event_name')` → Event reference
- Build dependency graph, limit depth to 2-3 levels.

### 5. sys_metadata Parent/Child (STRONG)
System-defined relationships:
- Table → Business rules (via `collection`), Dictionary entries (via `name`)
- UI Policy → UI Policy Actions (via `ui_policy`)
- Workflow → Activities (via `workflow_version`)

### 6. Temporal Proximity (WEAK-MEDIUM)
Same user, tight time window (minutes, not days).
- Combine with other signals for higher confidence.

### 7. Reference Field Values (MEDIUM)
Records referencing the same target (same `collection`, same script include).

### 8. Application / Package (STRONG for scoped, WEAK for global)
Scoped apps: `sys_scope` explicitly groups records.

## Confidence Scoring

| Signal | Weight |
|---|---|
| Same scoped app | +5 |
| Code reference (direct) | +4 |
| Same update set | +3 |
| Code reference (transitive) | +2 |
| Similar naming (prefix match) | +2 |
| Multiple signals align | +2 (bonus) |
| Same table target | +1 |
| Same author + close time | +1 |

**Confidence levels**: High (8+), Medium (4-7), Low (1-3)

## Clustering Algorithm (4 phases)

1. **Initial clusters**: Group by update set (exclude Default), scoped app, package
2. **Merge by strong signals**: Code references, naming patterns, similar US names
3. **Split by weak signals**: Unrelated tables, long time spans, many distinct authors
4. **Orphan assignment**: Assign ungrouped records to nearest cluster by code refs, \
table affinity, temporal proximity. Remainder → "Unclustered Customizations"
"""


# ── 3. Finding Patterns ─────────────────────────────────────────────


def _finding_patterns() -> str:
    return """\
# Common Finding Patterns

## OOTB Alternative Exists
Custom code doing what a platform feature handles declaratively:
- Client scripts making fields mandatory → use dictionary mandatory or UI policy
- Client scripts for dependent fields → use dictionary dependent values
- Scripts doing what UI policies, catalog UI policies, or action policies handle
- Custom notification logic when OOTB notification engine covers it

**Recommendation**: Replace with OOTB, remove custom code.

## Platform Maturity Gap
Feature was built when the platform was immature; ServiceNow has since added \
OOTB capability that covers this use case.

**Recommendation**: Replace with OOTB if equivalent, or refactor to leverage \
new platform capabilities.

## Bad Implementation, Good Intent
Real business need with no OOTB solution, but poor implementation:
- Deprecated APIs, bad coding patterns, over-engineering, fragile logic
- Consider scoping into an application for future-proofing

**Recommendation**: Keep and refactor. Provide specific improvement guidance.

## Dead or Broken Config
- Scripts with errors, broken references, or logic that can never execute
- Config referencing tables/fields that no longer exist
- Features abandoned (no updates in years, no evidence of use)

**Recommendation**: Remove after confirming non-use.

## Competing / Conflicting Config
- Multiple custom solutions for the same problem (different teams, different times)
- Custom solution AND OOTB solution both active on the same process
- Conflicting business rules or client scripts on the same table

**Recommendation**: Consolidate — keep the best one, remove duplicates.
"""


# ── 4. App File Types ───────────────────────────────────────────────


def _app_file_types() -> str:
    return """\
# Key Application File Types for Feature Detection

These are the building blocks of custom solutions in ServiceNow — the most \
important types for identifying features during technical assessment.

| App File Type | sys_class_name | Why It Matters |
|---|---|---|
| **Dictionary entries** | sys_dictionary | Custom fields — foundation of custom data |
| **Tables** | sys_db_object | Custom tables = custom data model |
| **Dictionary overrides** | sys_dictionary_override | Customizations to inherited fields |
| **Business rules** | sys_script | Server-side logic triggered by record operations |
| **Script includes** | sys_script_include | Reusable server-side code (often shared across features) |
| **Client scripts** | sys_script_client | Browser-side form logic |
| **UI policies** | sys_ui_policy | Declarative or scripted form behavior |
| **UI policy actions** | sys_ui_policy_action | What UI policies actually do |
| **Data policies** | sys_data_policy2 | Server-enforced data constraints |
| **Action policies** | sys_ui_action | Control available actions |
| **Record producers** | sc_cat_item_producer | User-facing request forms |
| **Catalog items** | sc_cat_item | Service catalog request forms |
| **Portal widgets** | sp_widget | Service Portal UI components |
| **Workflows** | wf_workflow | Classic workflow automation |
| **Flow Designer flows** | sys_hub_flow | Modern process automation |
| **Notifications** | sysevent_email_action | Email/notification rules |
| **Scheduled jobs** | sysauto_script | Scheduled background scripts |
| **ACLs** | sys_security_acl | Access control rules |

## What to Look For in Each

- **Business rules + Script includes**: Cross-reference each other frequently. \
A script include called by multiple business rules is likely a shared utility \
for a feature.
- **Client scripts + UI policies**: Often operate on the same form/fields. \
Check if a UI policy could replace a client script (declarative > scripted).
- **Dictionary entries + Dictionary overrides**: Define the data model. Custom \
fields (u_*) and overrides to OOTB fields are key indicators of customization.
- **Workflows / Flows**: Process automation — look for deprecated workflow \
patterns that should migrate to Flow Designer.
"""


# ── 5. Scan Result Schema ───────────────────────────────────────────


def _scan_result_schema() -> str:
    return """\
# ScanResult Model — Field Reference

The `ScanResult` model represents an individual application file/record found \
during a scan. These are the fields available for analysis and write-back.

## Identity Fields
| Field | Type | Description |
|---|---|---|
| `id` | int | Primary key |
| `scan_id` | int | FK to parent Scan |
| `sys_id` | str | ServiceNow sys_id |
| `table_name` | str | Source table (sys_script, sys_script_include, etc.) |
| `name` | str | Artifact name |
| `display_value` | str | Display value from ServiceNow |

## Metadata Fields
| Field | Type | Description |
|---|---|---|
| `sys_class_name` | str | Metadata class |
| `sys_update_name` | str | Version tracking identifier |
| `sys_scope` | str | Application scope |
| `sys_package` | str | Package/app |
| `meta_target_table` | str | Target table (e.g., collection field value) |

## Classification Fields
| Field | Type | Valid Values |
|---|---|---|
| `origin_type` | OriginType | modified_ootb, ootb_untouched, net_new_customer, unknown, unknown_no_history |
| `head_owner` | HeadOwner | Customer, Store/Upgrade, Unknown |
| `changed_baseline_now` | bool | True if differs from vendor baseline |

## Version Tracking Fields
| Field | Type | Description |
|---|---|---|
| `current_version_source_table` | str | Source table of head version |
| `current_version_source` | str | Display value of source |
| `current_version_sys_id` | str | sys_id of head version record |
| `current_version_recorded_at` | datetime | When head version was recorded |
| `created_by_in_user_table` | bool | For unknown_no_history investigation |

## Review & Disposition Fields (writable via update_scan_result)
| Field | Type | Valid Values |
|---|---|---|
| `review_status` | ReviewStatus | pending_review, review_in_progress, reviewed |
| `disposition` | Disposition | remove, keep_as_is, keep_and_refactor, needs_analysis |
| `recommendation` | str | Free-text recommendation |
| `observations` | str | Iterative observations (updated across passes) |

## Assessment Fields
| Field | Type | Description |
|---|---|---|
| `severity` | Severity | critical, high, medium, low, info |
| `category` | FindingCategory | customization, code_quality, security, performance, upgrade_risk, best_practice |
| `finding_title` | str | Short finding title |
| `finding_description` | str | Detailed finding description |

## Audit Fields
| Field | Type | Description |
|---|---|---|
| `sys_created_on` | datetime | When created in ServiceNow |
| `sys_created_by` | str | Creator in ServiceNow |
| `sys_updated_on` | datetime | Last update in ServiceNow |
| `sys_updated_by` | str | Last updater in ServiceNow |
| `script_length` | int | Length of script field (for code artifacts) |
"""


# ── 6. Feature Schema ───────────────────────────────────────────────


def _feature_schema() -> str:
    return """\
# Feature Model — Field Reference

The `Feature` model represents a logical grouping of related application \
files that together deliver a business capability. Features are created \
during the grouping phase and refined iteratively.

## Fields
| Field | Type | Description |
|---|---|---|
| `id` | int | Primary key |
| `assessment_id` | int | FK to parent Assessment |
| `name` | str | Feature name (e.g., "Custom Approval Workflow for Change") |
| `description` | str | What this group of configuration accomplishes |
| `parent_id` | int | FK to parent Feature (for hierarchical grouping) |
| `primary_update_set_id` | int | FK to the primary update set for this feature |
| `disposition` | Disposition | remove, keep_as_is, keep_and_refactor, needs_analysis |
| `recommendation` | str | Feature-level recommendation text |
| `ai_summary` | str | AI-generated analysis summary |
| `created_at` | datetime | When created |
| `updated_at` | datetime | Last modified |

## Relationships
- **assessment**: Parent Assessment
- **parent** / **children**: Hierarchical feature tree
- **primary_update_set**: The main update set for this feature
- **scan_result_links**: Many-to-many links to ScanResult records (via FeatureScanResult)

## Disposition Values
| Value | When to Use |
|---|---|
| `keep_as_is` | Valuable, well-built, serves real need, no OOTB alternative |
| `keep_and_refactor` | Good intent, needs improvement or should be scoped |
| `remove` | Dead, broken, redundant, no longer needed |
| `needs_analysis` | Insufficient information to decide — needs deeper investigation |

## Write-Back Tools
- **`update_feature`**: Update name, description, disposition, recommendation, ai_summary
- **`get_feature_detail`**: Read feature with all linked scan results
"""


# ── Resource specs (exported for registration) ──────────────────────

RESOURCE_SPECS: List[ResourceSpec] = [
    ResourceSpec(
        uri="assessment://guide/classification-rules",
        name="Classification Rules",
        description="Origin type decision tree, version history method, "
                    "baseline comparison — how records are classified.",
        mime_type="text/markdown",
        handler=_classification_rules,
    ),
    ResourceSpec(
        uri="assessment://guide/grouping-signals",
        name="Grouping Signals",
        description="8 signal categories for clustering related records "
                    "into features, with confidence scoring and algorithm.",
        mime_type="text/markdown",
        handler=_grouping_signals,
    ),
    ResourceSpec(
        uri="assessment://guide/finding-patterns",
        name="Finding Patterns",
        description="Common finding patterns: OOTB alternatives, platform "
                    "maturity gaps, bad implementation, dead config, conflicts.",
        mime_type="text/markdown",
        handler=_finding_patterns,
    ),
    ResourceSpec(
        uri="assessment://guide/app-file-types",
        name="App File Types",
        description="Key ServiceNow application file types for feature "
                    "detection — what to look for in each.",
        mime_type="text/markdown",
        handler=_app_file_types,
    ),
    ResourceSpec(
        uri="assessment://schema/scan-result-fields",
        name="ScanResult Schema",
        description="Field names, types, and valid enum values for the "
                    "ScanResult model — what data is available for analysis.",
        mime_type="text/markdown",
        handler=_scan_result_schema,
    ),
    ResourceSpec(
        uri="assessment://schema/feature-fields",
        name="Feature Schema",
        description="Field names, types, and relationships for the Feature "
                    "model — used for grouping and disposition write-back.",
        mime_type="text/markdown",
        handler=_feature_schema,
    ),
]
