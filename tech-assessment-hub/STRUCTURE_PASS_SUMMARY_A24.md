# Structure Pass Summary — Assessment 24 (Incident Management)

**Date**: 2026-04-06  
**Assessment**: Global Incident Management (incident)  
**Status**: ✅ Complete  

---

## Overview

The Structure pass has created 8 provisional features and assigned **all 346 in-scope customized artifacts** to them. These features represent the major business capabilities implemented in the Incident Management assessment.

---

## Feature Framework

| # | Feature Name | Kind | Artifacts | Description |
|---|---|---|---|---|
| 1 | **Pharmacy Incidents** | Functional | 156 | Pharmacy-specific incident types, workflows, and task tracking for pharmacy-related incidents and operations |
| 2 | **Incident Intake & Categorization** | Functional | 33 | Request forms and intake mechanisms for various incident categories through catalog item producers |
| 3 | **Work Order Integration** | Functional | 33 | Automated creation and synchronization of work orders from incidents (incident ↔ work order sync) |
| 4 | **Form & Field Behavior** | Functional | 21 | Form-level customizations including client scripts and dynamic field behavior |
| 5 | **Encrypted PHI Handling** | Functional | 20 | Secure handling and encryption of protected health information (HIPAA-related) in incidents |
| 6 | **Incident State & Workflow** | Functional | 13 | State transitions, workflow automation, and lifecycle management (draft, restrict, revert, close/reopen) |
| 7 | **Incident Auto-Assignment** | Functional | 7 | Automatic routing and assignment of incidents to appropriate groups and users |
| 8 | **Form Fields & UI** | Bucket | 63 | Miscellaneous UI policies and actions that don't fit other feature categories |

**Total**: 346 artifacts assigned | 100% coverage

---

## Grouping Decisions & Rationale

### 1. Pharmacy Incidents (156 artifacts) — Primary Solution
The largest feature reflects the assessment scope: pharmacy-focused incident management. Includes:
- All artifacts targeting custom table `u_task_pharmacy_incident` (153 artifacts)
- Pharmacy-related incident categories (Pharmacy Issue, Department Scale, Self Checkout, Conventional Register, Equipment Maintenance)
- Pharmacy workflow customizations
- **Confidence**: Very high — strong table affinity + naming consistency

### 2. Incident Intake & Categorization (33 artifacts)
All 57 catalog item producers belong here (request forms for incident creation). Divided into:
- Pure intake forms (Ask a Question, Badge Issues, Building Maintenance, IT Hardware, etc.)
- Pharmacy-specific forms (included in Pharmacy Incidents feature instead)
- Copy variants (suggesting versioning/maintenance)
- **Confidence**: Definitive — all `sc_cat_item_producer` artifacts are intake mechanisms by definition

### 3. Work Order Integration (33 artifacts)
Clear functional grouping based on artifact naming:
- Scripts: "Auto-Create Work Orders", "Create Work Order", "Generate Work Order", "Check for Open Work Orders", "Map INC fields to WO", "Push assignment group to WO"
- Related UI policies and actions for work order fields
- **Pattern**: These artifacts work together to sync incident state with work order creation/updates
- **Confidence**: Very high — explicit naming + functional dependency signals

### 4. Form & Field Behavior (21 artifacts)
Client-side form logic and form-specific customizations:
- Client scripts for form interactions
- UI policies for form-level behavior (mandatory fields, hide/show logic, field interactions)
- **Rationale**: Separated from bucket because these are clearly form-behavior focused, not miscellaneous
- **Confidence**: High — table type signal (`sys_script_client`) + naming

### 5. Encrypted PHI Handling (20 artifacts)
Security/compliance-focused customizations:
- Scripts with "Encryption", "PHI", "Secure", or healthcare-related naming
- UI policies/actions for sensitive data fields
- **Business Context**: Pharmacy system handling patient health info requires HIPAA compliance
- **Confidence**: High — explicit security domain keywords in naming

### 6. Incident State & Workflow (13 artifacts)
Lifecycle and state management:
- Scripts with keywords: Draft, Restrict, Revert, Close, Reopen, State, Inactive, Callback
- Examples: "PCG_MakeDraftStateInactive", "PCG_RestrictCloseAndCancelByRole", "PCG_RevertToAssigned", "Reset Assignment Group On Reopen"
- **Rationale**: These customize the incident lifecycle, not just form appearance or assignment
- **Confidence**: High — state management domain is distinct from assignment/integration

### 7. Incident Auto-Assignment (7 artifacts)
Routing and assignment logic:
- Scripts: "Auto Assignment: Jolt", "Set Assigned", "Set Assignment Group from Parent", "Auto Populate Sev 3 Participants"
- Related UI policies for assignment fields
- **Rationale**: Distinct from state management — focused on WHO handles incidents, not WHEN/HOW transitions happen
- **Confidence**: High — narrow, focused group with clear business meaning

### 8. Form Fields & UI (Bucket, 63 artifacts)
Remaining UI policies and actions:
- 143 `sys_ui_policy_action` artifacts (high volume, diverse purposes)
- 62 `sys_ui_policy` artifacts (form behavior definitions)
- **Rationale**: These don't fit cleanly into specific solutions and need human review for grouping
- **Type**: Bucket feature — placeholder for future refinement, not a business solution
- **Note**: Will be revisited in naming/refinement passes when human context improves understanding

---

## Artifact Composition

### By Artifact Type
- **sys_ui_policy_action**: 143 (form actions/behaviors)
- **sys_ui_policy**: 62 (form policies)
- **sc_cat_item_producer**: 57 (request forms)
- **sys_script_client**: 31 (browser-side logic)
- **sys_script**: 30 (server-side business rules)
- **sys_ui_action**: 23 (UI actions)

### By Target Table
- **incident**: 189 (primary target)
- **u_task_pharmacy_incident**: 153 (pharmacy custom table)
- **u_pharmacy_incident_ssc_tasks**: 3
- **u_dl_incident_to_work_order**: 1

### By Origin
- **modified_ootb**: (vendor code with customer modifications)
- **net_new_customer**: (customer-created)
- **All customized**: Only modified_ootb and net_new_customer included

---

## Next Steps

### For Refinement Pass
1. Deep-dive analyze **Form Fields & UI bucket** (63 artifacts) to break into coherent sub-solutions
2. Verify Pharmacy Incidents boundary — ensure custom table artifacts are correctly scoped
3. Review Incident State & Workflow for possible split (draft management vs. close/reopen logic)
4. Check for cross-feature dependencies (especially between Work Order Integration and State/Assignment)

### For Naming Pass
1. Replace provisional names with final, human-readable feature names
2. Set `name_status` to "final" after human review
3. Stabilize bucket key for Form Fields & UI if it remains as bucket

### For Recommendation Pass
1. Evaluate each feature for platform OOTB alternatives
2. Assess feature quality (e.g., Is Pharmacy Incidents over-broad? Does it need splitting?)
3. Suggest dispositions (keep, refactor, replace, retire)

---

## Key Insights

1. **Pharmacy domain dominance**: 156 of 346 (45%) artifacts are pharmacy-specific, confirming the system is a domain-specialized incident management solution.

2. **Heavy form customization**: 205 of 346 (59%) are form-level artifacts (UI policies, policy actions). This suggests the incident form itself has been heavily customized for pharmacy operations.

3. **Integration-centric**: Work Order Integration (33 artifacts) is a major feature, indicating deep integration with work order management workflows.

4. **Form-heavy over logic-heavy**: Only 30 business rules vs. 143 UI policy actions. The system prioritizes form behavior over business logic automation.

5. **Low update set signal quality**: 1007 update sets with only 5.7 artifacts per set suggests update sets are not a reliable grouping signal here. AI pattern-based grouping was more effective.

---

## Coverage Verification

✅ **Total in-scope customized artifacts**: 346  
✅ **Total assigned to features**: 346  
✅ **Coverage**: 100%  
✅ **Orphans**: 0  

Every in-scope artifact has exactly one primary feature assignment.
