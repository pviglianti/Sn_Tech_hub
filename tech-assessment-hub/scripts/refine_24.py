#!/usr/bin/env python3
"""Holistic refinement pass for Assessment 24.

Sets feature-level AI summaries, recommendations, composition types,
and updates key artifact observations with cross-feature context.
Does NOT set dispositions — those are human decisions.
"""

import json
import requests

MCP_URL = "http://127.0.0.1:8081/mcp"
ASSESSMENT_ID = 24


def mcp_call(tool_name, arguments):
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = requests.post(MCP_URL, json=payload, timeout=60)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")
    content = data["result"]["content"]
    for item in content:
        if item.get("type") == "json":
            return item["json"]
        if item.get("type") == "text":
            return item["text"]
    return content


def sql(query):
    return mcp_call("sqlite_query", {"sql": query})


# -----------------------------------------------------------------------
# Feature-level analysis
# -----------------------------------------------------------------------

FEATURE_ANALYSIS = {
    10: {  # Incident Form Field Policies
        "ai_summary": (
            "55 UI policies and actions (all net-new) controlling field behavior on the incident form. "
            "Covers mandatory enforcement, field visibility toggling, and read-only states across incident "
            "lifecycle stages. These policies depend on 15+ custom fields defined in the Incident Field Schema "
            "feature — any field deprecation must be validated against these policies first."
        ),
        "recommendation": (
            "Keep with review. Cross-reference each policy condition against actual field usage. "
            "Some policies may overlap with the 30 client scripts in Incident Client-Side Behavior — "
            "deduplicate where both control the same field. Validate that policy conditions use current "
            "state/category values (stale choice values cause silent policy failures)."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    11: {  # Incident Client-Side Behavior
        "ai_summary": (
            "30 client scripts (27 net-new, 3 OOTB-modified) on the incident form. "
            "Functions include VIP caller highlighting, location data rendering, gas-and-go tab toggling, "
            "choice list manipulation, and field validation. Several scripts perform actions that "
            "UI Policies can handle declaratively (setMandatory, setDisplay, setReadOnly)."
        ),
        "recommendation": (
            "REFACTOR CANDIDATE. Audit each client script against existing UI policies in Feature #10. "
            "Scripts doing only setMandatory/setDisplay/setReadOnly should migrate to UI policies — "
            "this reduces JavaScript load on the form and leverages platform-native behavior. "
            "The 3 modified OOTB scripts need baseline comparison to assess upgrade risk. "
            "Scripts using GlideAjax or complex DOM manipulation should remain as client scripts."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    12: {  # Incident Business Rules
        "ai_summary": (
            "29 business rules (27 net-new, 2 OOTB-modified) on the incident table. "
            "Major clusters: (1) Work Order lifecycle — 8+ rules creating/syncing/closing WOs, "
            "several inactive suggesting iterative replacement; (2) Assignment logic — auto-assignment, "
            "revert-to-assigned, group-from-parent; (3) Field sync — caller/on-behalf-of to watch list, "
            "affected stores from location; (4) State management — reopen, draft-inactive."
        ),
        "recommendation": (
            "REFACTOR REQUIRED. The Work Order cluster (8+ BRs) is the highest-priority consolidation "
            "target — merge into a single WO Manager Script Include called from 1-2 BRs. "
            "The inactive rules (Create Work Order, incident query, PCG_MakeDraftStateInactive) should be "
            "evaluated for retirement. Note: 'Auto-Create Work Orders from Incidents' cross-references "
            "the Incident-to-Work-Order Bridge feature (#27) — these must be reviewed together. "
            "DEPENDENCY: Multiple BRs reference fields defined in Feature #18 (Field Schema)."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    13: {  # Incident UI Actions
        "ai_summary": (
            "19 UI actions (11 OOTB-modified, 8 net-new) providing custom buttons on the incident form. "
            "Includes workflow controls (Show Workflow, Workflow Context), record operations (Copy, Resolve), "
            "WO creation, and PHI encryption actions. The high OOTB modification ratio (58%) means "
            "these are upgrade-sensitive."
        ),
        "recommendation": (
            "Keep with careful upgrade tracking. The 11 OOTB-modified UI actions are the highest "
            "upgrade risk in this assessment — each must have a baseline comparison documented. "
            "The 'Create Work Order' UI action overlaps with business rules in Feature #12 that also "
            "create WOs — verify they don't produce duplicate WOs. "
            "DEPENDENCY: UI action scripts reference 37 fields from Feature #18 (Field Schema)."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    14: {  # Incident Record Producers
        "ai_summary": (
            "56 record producers (all net-new) creating incidents from the service catalog. "
            "Covers IT hardware, equipment maintenance, gas pumps, conventional registers, POS systems, "
            "pharmacy equipment, and many other intake categories. This is an unusually high count "
            "suggesting organic growth over multiple years without consolidation."
        ),
        "recommendation": (
            "CONSOLIDATION CANDIDATE. Group the 56 producers by business function and identify overlaps "
            "(e.g., multiple equipment/hardware variants). Consider a category-based rationalization: "
            "fewer producers with dynamic variable sets can replace many single-purpose ones. "
            "Verify each producer still has an active catalog category and is actually being used — "
            "check sc_req_item counts per producer over the last 12 months."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    15: {  # Pharmacy Incident Form Policies
        "ai_summary": (
            "148 UI policies and actions (all net-new) on u_task_pharmacy_incident. "
            "This is the single largest feature cluster. Policies control complex multi-step forms "
            "covering patient information, root cause analysis, PHI fields, prevention steps, and "
            "regulatory compliance fields. 99 structural relationships link back to Field Schema."
        ),
        "recommendation": (
            "Keep — this is core to the pharmacy incident workflow. However, audit for redundancy: "
            "148 policy actions likely includes overlapping conditions (multiple policies setting the "
            "same field mandatory under different states). A policy consolidation pass could reduce "
            "this count by 20-30%. DEPENDENCY: Deeply coupled to Feature #18 (Field Schema) via "
            "99 field references — any field changes must be validated here first. "
            "Long-term: evaluate App Engine Studio scoped app migration for better lifecycle management."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    16: {  # Pharmacy Incident Workflow
        "ai_summary": (
            "5 artifacts (all net-new): UI actions for Submit/Close/Send to Regional Manager, "
            "a business rule tracking Days Opened, and a record producer for pharmacy incident intake. "
            "These are the operational backbone of the pharmacy incident process."
        ),
        "recommendation": (
            "Keep as core workflow. The 'Update Days Opened' business rule should be checked for "
            "performance — if it fires on every update, consider a scheduled job instead. "
            "DEPENDENCY: Works in conjunction with Feature #15 (form policies) and #17 (SSC tasks)."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    17: {  # Pharmacy SSC Task Management
        "ai_summary": (
            "3 artifacts (all net-new) on u_pharmacy_incident_ssc_tasks: a UI policy for read-only "
            "fields, its action for state field, and a Close Task UI action. Minimal but complete "
            "task lifecycle management for the pharmacy SSC subprocess."
        ),
        "recommendation": (
            "Keep as-is. Small, well-contained feature. Verify the Close Task action properly "
            "syncs state back to the parent pharmacy incident (Feature #16)."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    18: {  # Incident Field Schema
        "ai_summary": (
            "172 dictionary entries and overrides (160 net-new, 12 OOTB-modified). "
            "This is the CRITICAL DEPENDENCY HUB of the entire assessment. Every other incident "
            "feature references fields defined here: 99 structural links to Pharmacy Policies, "
            "46 code refs from Business Rules, 46 from Client Scripts, 37 from UI Actions, "
            "15 from Form Policies. Changing any field here cascades across all features."
        ),
        "recommendation": (
            "AUDIT REQUIRED before any other feature disposition. A field usage analysis must "
            "identify: (1) fields actually populated on records, (2) fields displayed on forms, "
            "(3) fields referenced in code. Unused fields should be deprecated. The 12 OOTB-modified "
            "entries are the highest upgrade risk — document baseline changes for each. "
            "WARNING: No feature can be safely removed until its field dependencies in this feature "
            "are resolved."
        ),
        "composition_type": "direct",
        "feature_kind": "bucket",
        "bucket_key": "form_fields",
    },
    19: {  # Incident Table Definitions
        "ai_summary": (
            "4 table definitions: Incident (OOTB-modified), Pharmacy Incident, Pharmacy SSC Tasks, "
            "and Incident-to-WO Map (all net-new custom). The 3 custom tables extend task and form "
            "the structural foundation of the pharmacy incident subsystem."
        ),
        "recommendation": (
            "Keep — these are foundational. The OOTB Incident table modification needs baseline "
            "comparison. The 3 custom tables are tightly coupled to Features #15-17 (Pharmacy) "
            "and #27 (WO Bridge). Cannot be removed without removing all dependent features."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    20: {  # Incident Security ACLs
        "ai_summary": (
            "65 ACLs (57 net-new, 8 OOTB-modified) controlling field-level and record-level access. "
            "Covers incident fields like PHI, encryption, problem candidate, and various custom fields. "
            "ACLs are evaluated in a specific order and duplicates can cause unexpected access grants."
        ),
        "recommendation": (
            "SECURITY REVIEW REQUIRED. The 8 OOTB-modified ACLs must be compared against baseline "
            "to verify they haven't weakened platform security posture. All 65 ACLs should be "
            "cross-referenced with actual role assignments to confirm intended access patterns. "
            "Check for duplicate ACL paths (same table.field.operation with different rules). "
            "DEPENDENCY: ACLs reference fields in Feature #18 — field deprecation must update ACLs."
        ),
        "composition_type": "direct",
        "feature_kind": "bucket",
        "bucket_key": "acl",
    },
    21: {  # Change-Incident Integration
        "ai_summary": (
            "6 artifacts on change_request (2 OOTB-modified, 4 net-new): scripts for emergency change "
            "linking to incidents, backdating start/end dates, scratchpad population, approval request, "
            "and a delegation record producer."
        ),
        "recommendation": (
            "Keep with review. The emergency change -> incident link is a common integration point. "
            "Verify the backdating scripts have proper audit controls. The modified OOTB scripts "
            "need baseline comparison. ADJACENT: If incident disposition changes, verify these "
            "change scripts still function correctly."
        ),
        "composition_type": "adjacent",
        "feature_kind": "functional",
    },
    22: {  # Task Framework Extensions
        "ai_summary": (
            "15 artifacts on task/ticket tables (3 OOTB-modified, 12 net-new). Includes metrics "
            "timeline, outage creation, attachment management, on-call triggers, LIFT intake automation, "
            "accounting code generation, and business service policies."
        ),
        "recommendation": (
            "Keep with careful scoping. These affect ALL task-based tables, not just incident. "
            "Any changes here impact change, problem, and other task extensions. The LIFT intake "
            "automation and accounting code scripts should be verified for current business use. "
            "RISK: Modifications to task-level artifacts have the broadest blast radius."
        ),
        "composition_type": "adjacent",
        "feature_kind": "functional",
    },
    23: {  # Location & User Management
        "ai_summary": (
            "14 artifacts (all net-new) across cmn_location, sys_user, sys_user_group: "
            "district/region field sync rules (4 pairs on location), user phone sync to PeopleSoft, "
            "group membership restrictions, and group UI policies."
        ),
        "recommendation": (
            "Keep but review PeopleSoft sync. The location district/region sync rules appear to be "
            "custom geographic hierarchy management — verify this isn't duplicated by any OOTB "
            "ServiceNow location hierarchy features. The PeopleSoft phone sync may be obsolete "
            "if PeopleSoft integration has been replaced. "
            "ADJACENT: Location and user fields flow into incident assignment logic (Feature #12)."
        ),
        "composition_type": "adjacent",
        "feature_kind": "functional",
    },
    24: {  # CMDB & Outage Integration
        "ai_summary": (
            "2 artifacts (both net-new): a business rule on cmdb_ci_outage updating incident work notes, "
            "and a client script on cmdb_ci_service for SOX information. Minimal integration footprint."
        ),
        "recommendation": (
            "Keep as-is. Small, well-contained. The outage->incident work note sync is standard ITIL. "
            "The SOX info script should be verified for current compliance requirements."
        ),
        "composition_type": "adjacent",
        "feature_kind": "functional",
    },
    25: {  # Service Catalog Integration
        "ai_summary": (
            "11 artifacts: 9 order guides for catalog navigation (Travel, Badge, Equipment, Active "
            "Directory, etc.), 1 RITM read-only client script, and 1 task->user creation BR. "
            "The order guides are adjacent — they funnel service requests that may spawn incidents."
        ),
        "recommendation": (
            "Review for current relevance. Many order guides may be superseded by newer catalog "
            "structures. The task->user creation BR is an unusual pattern that should be evaluated "
            "for security implications. ADJACENT: These feed into the intake pipeline but are not "
            "core to incident management — disposition can be independent of incident features."
        ),
        "composition_type": "adjacent",
        "feature_kind": "functional",
    },
    26: {  # Problem-Incident Integration
        "ai_summary": (
            "1 artifact (OOTB-modified): the 'Communicate Workaround' UI action on the problem table. "
            "Standard ITIL pattern for pushing problem workarounds to related incidents."
        ),
        "recommendation": (
            "Keep — this is standard ITIL practice. Compare against baseline to understand what "
            "was modified. Being a single OOTB modification, upgrade risk is manageable."
        ),
        "composition_type": "adjacent",
        "feature_kind": "functional",
    },
    27: {  # Incident-to-Work-Order Bridge
        "ai_summary": (
            "3 artifacts (all net-new): business rule copying attachments from INC to WOT, "
            "and a client script on the u_dl_incident_to_work_order bridge table. This bridge "
            "connects to the WO creation logic in Incident Business Rules (Feature #12)."
        ),
        "recommendation": (
            "Review WITH Feature #12. The WO bridge and the 8+ WO business rules in Feature #12 "
            "form a single logical system. If the WO integration is consolidated in Feature #12, "
            "this bridge feature may need corresponding updates. Cannot be dispositioned independently."
        ),
        "composition_type": "direct",
        "feature_kind": "functional",
    },
    28: {  # Shared Script Libraries
        "ai_summary": (
            "5 script includes (2 OOTB-modified, 3 net-new): SAML2, RequirementsBuilder, "
            "showOnlyActive, TimeCardQueryHelper, and SetChangeRisk. These are shared utilities "
            "that may be called from multiple features."
        ),
        "recommendation": (
            "Audit callers. Each script include may be a dependency for multiple features. "
            "SetChangeRisk is likely called from Change-Incident Integration (#21). "
            "TimeCardQueryHelper relates to time tracking (out-of-scope tables). "
            "SAML2 modifications are security-sensitive and need baseline comparison. "
            "WARNING: Cannot retire any script include without verifying all callers."
        ),
        "composition_type": "adjacent",
        "feature_kind": "bucket",
        "bucket_key": "script_include",
    },
    29: {  # Global UI Extensions
        "ai_summary": (
            "1 artifact (net-new): 'Force to Update Set' global UI action. Provides a manual "
            "mechanism to force a record into a specific update set."
        ),
        "recommendation": (
            "Review for current need. This is a developer/admin utility, not a business capability. "
            "If update set management is done through standard processes, this may be unnecessary. "
            "Low risk regardless of disposition."
        ),
        "composition_type": "adjacent",
        "feature_kind": "bucket",
        "bucket_key": "admin_utility",
    },
}


def main():
    print("=" * 60)
    print("Assessment 24 — Holistic Refinement Pass")
    print("=" * 60)

    # Step 1: Update all features with analysis
    print("\n[1/3] Setting feature-level recommendations and AI summaries...")
    updated = 0
    for fid, analysis in FEATURE_ANALYSIS.items():
        try:
            args = {"feature_id": fid}
            if "ai_summary" in analysis:
                args["ai_summary"] = analysis["ai_summary"]
            if "recommendation" in analysis:
                args["recommendation"] = analysis["recommendation"]
            if "composition_type" in analysis:
                args["composition_type"] = analysis["composition_type"]
            if "feature_kind" in analysis:
                args["feature_kind"] = analysis["feature_kind"]
            if "bucket_key" in analysis:
                args["bucket_key"] = analysis["bucket_key"]
            args["name_status"] = "final"

            mcp_call("update_feature", args)
            updated += 1
        except Exception as e:
            print(f"  Error on feature #{fid}: {e}")

    print(f"  Updated {updated} features")

    # Step 2: Update key artifact observations with cross-feature context
    print("\n[2/3] Updating artifact observations with cross-feature context...")
    cross_ref_updates = 0

    # Get artifacts that are in Work Order business rules (high-priority cross-ref)
    wo_brs = sql(
        "SELECT sr.id, sr.name, sr.observations FROM scan_result sr "
        "JOIN feature_scan_result fsr ON sr.id = fsr.scan_result_id "
        "WHERE fsr.feature_id = 12 "
        "AND (sr.observations LIKE '%Work Order%' OR sr.observations LIKE '%wm_order%' "
        "OR sr.name LIKE '%Work Order%' OR sr.name LIKE '%WO%')"
    )
    for row in wo_brs["rows"]:
        obs = row["observations"] or ""
        if "CROSS-REF" not in obs:
            new_obs = obs + " CROSS-REF: Part of the Work Order integration cluster spanning Features #12 (Business Rules) and #27 (WO Bridge). Review together for consolidation."
            mcp_call("update_scan_result", {"result_id": row["id"], "observations": new_obs})
            cross_ref_updates += 1

    # Get the OOTB-modified UI actions (upgrade risk flag)
    ootb_ui = sql(
        "SELECT sr.id, sr.observations FROM scan_result sr "
        "JOIN feature_scan_result fsr ON sr.id = fsr.scan_result_id "
        "WHERE fsr.feature_id = 13 AND sr.origin_type = 'modified_ootb'"
    )
    for row in ootb_ui["rows"]:
        obs = row["observations"] or ""
        if "UPGRADE RISK" not in obs:
            new_obs = obs + " UPGRADE RISK: OOTB-modified UI action — requires baseline comparison before upgrade. Part of highest OOTB-modification concentration in this assessment (11/19 in this feature)."
            mcp_call("update_scan_result", {"result_id": row["id"], "observations": new_obs})
            cross_ref_updates += 1

    # Get the OOTB-modified ACLs (security flag)
    ootb_acl = sql(
        "SELECT sr.id, sr.observations FROM scan_result sr "
        "JOIN feature_scan_result fsr ON sr.id = fsr.scan_result_id "
        "WHERE fsr.feature_id = 20 AND sr.origin_type = 'modified_ootb'"
    )
    for row in ootb_acl["rows"]:
        obs = row["observations"] or ""
        if "SECURITY" not in obs:
            new_obs = obs + " SECURITY: OOTB-modified ACL — verify against baseline to ensure security posture is not weakened. Part of 8 modified OOTB ACLs in this assessment."
            mcp_call("update_scan_result", {"result_id": row["id"], "observations": new_obs})
            cross_ref_updates += 1

    # Get OOTB-modified dictionary entries (schema risk)
    ootb_dict = sql(
        "SELECT sr.id, sr.observations FROM scan_result sr "
        "JOIN feature_scan_result fsr ON sr.id = fsr.scan_result_id "
        "WHERE fsr.feature_id = 18 AND sr.origin_type = 'modified_ootb'"
    )
    for row in ootb_dict["rows"]:
        obs = row["observations"] or ""
        if "SCHEMA RISK" not in obs:
            new_obs = obs + " SCHEMA RISK: OOTB-modified dictionary entry — upgrade patches may conflict. This field is referenced across multiple features; changes cascade broadly."
            mcp_call("update_scan_result", {"result_id": row["id"], "observations": new_obs})
            cross_ref_updates += 1

    # Flag the SAML2 script include
    saml = sql(
        "SELECT sr.id, sr.observations FROM scan_result sr "
        "JOIN feature_scan_result fsr ON sr.id = fsr.scan_result_id "
        "WHERE fsr.feature_id = 28 AND sr.name LIKE '%SAML%'"
    )
    for row in saml["rows"]:
        obs = row["observations"] or ""
        if "SECURITY" not in obs:
            new_obs = obs + " SECURITY: SAML2 modification is authentication-critical. Must be reviewed by security team before any disposition decision."
            mcp_call("update_scan_result", {"result_id": row["id"], "observations": new_obs})
            cross_ref_updates += 1

    print(f"  Updated {cross_ref_updates} artifacts with cross-feature context")

    # Step 3: Log dependency conflict scenarios
    print("\n[3/3] Dependency conflict analysis...")
    print()
    print("  DEPENDENCY MAP:")
    print("  ─────────────────────────────────────────────────")
    print("  Feature #18 (Field Schema) ← DEPENDED ON BY ALL:")
    print("    ├── #10 Form Policies (15 field refs)")
    print("    ├── #11 Client Scripts (46 field refs)")
    print("    ├── #12 Business Rules (46 field refs)")
    print("    ├── #13 UI Actions (37 field refs)")
    print("    ├── #15 Pharmacy Policies (99 structural links)")
    print("    └── #16 Pharmacy Workflow (4 field refs)")
    print()
    print("  Feature #12 (Business Rules) ←→ #27 (WO Bridge):")
    print("    └── Both manage Work Order lifecycle — must be reviewed together")
    print()
    print("  Feature #19 (Table Defs) ← DEPENDED ON BY:")
    print("    ├── #15-17 (Pharmacy subsystem)")
    print("    └── #27 (WO Bridge)")
    print()
    print("  CONFLICT SCENARIOS:")
    print("  ─────────────────────────────────────────────────")
    print("  ⚠ If #18 (Field Schema) fields are deprecated → must update #10,#11,#12,#13,#15")
    print("  ⚠ If #12 (Business Rules) WO BRs removed → #27 (WO Bridge) becomes orphaned")
    print("  ⚠ If #19 (Table Defs) custom tables removed → #15,#16,#17 all become invalid")
    print("  ⚠ If #28 (Script Libs) retired → must verify no callers in #12,#21,#22")
    print("  ⚠ If #11 (Client Scripts) migrated to UI policies → #10 policies may conflict")
    print()
    print("  SAFE INDEPENDENT DISPOSITIONS (no cross-dependencies):")
    print("  ─────────────────────────────────────────────────")
    print("  ✓ #14 (Record Producers) — self-contained, can consolidate independently")
    print("  ✓ #23 (Location/User Mgmt) — adjacent, independent lifecycle")
    print("  ✓ #24 (CMDB/Outage) — 2 artifacts, standalone")
    print("  ✓ #25 (Catalog Integration) — adjacent, independent")
    print("  ✓ #26 (Problem Integration) — 1 artifact, standalone")
    print("  ✓ #29 (Global UI) — 1 artifact, admin utility")

    print(f"\n{'='*60}")
    print("REFINEMENT COMPLETE")
    print(f"{'='*60}")
    print(f"  Features analyzed: {updated}")
    print(f"  Artifacts cross-referenced: {cross_ref_updates}")
    print(f"  Dependency conflicts flagged: 5 scenarios")
    print(f"  Safe independent features: 6")


if __name__ == "__main__":
    main()
