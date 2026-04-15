#!/usr/bin/env python3
"""Feature grouping for Assessment 24 (Incident Management).

Groups 644 in-scope artifacts into business capability features.
Uses correct MCP parameter names (scan_result_id, not result_id).
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


def sql_all(query):
    all_rows = []
    page = 0
    while True:
        result = sql(f"{query} LIMIT 200 OFFSET {page * 200}")
        rows = result["rows"]
        all_rows.extend(rows)
        if len(rows) < 200:
            break
        page += 1
    return all_rows


# Feature definitions: name -> (description, match function)
FEATURES = [
    # --- Core Incident ---
    ("Incident Form Field Policies",
     "UI policies and actions controlling field visibility, mandatory state, and read-only behavior on the incident form.",
     lambda r: r["mt"] == "incident" and r["sc"] in ("sys_ui_policy", "sys_ui_policy_action")),

    ("Incident Client-Side Behavior",
     "Client scripts on the incident form: field highlighting, location rendering, tab toggling, choice manipulation.",
     lambda r: r["mt"] == "incident" and r["sc"] == "sys_script_client"),

    ("Incident Business Rules",
     "Server-side business rules: auto-assignment, state management, field defaults, workflow triggers, WO creation.",
     lambda r: r["mt"] == "incident" and r["sc"] == "sys_script"),

    ("Incident UI Actions",
     "Custom buttons/links on incident form: workflow, copy, resolve, create work order, PHI actions.",
     lambda r: r["mt"] == "incident" and r["sc"] == "sys_ui_action"),

    ("Incident Record Producers",
     "Service catalog record producers creating incidents: hardware, equipment, gas pump, register issues.",
     lambda r: r["mt"] == "incident" and r["sc"] == "sc_cat_item_producer"),

    # --- Pharmacy Incident ---
    ("Pharmacy Incident Form Policies",
     "UI policies and actions on u_task_pharmacy_incident: field rules for root cause, patient info, PHI.",
     lambda r: r["mt"] == "u_task_pharmacy_incident" and r["sc"] in ("sys_ui_policy", "sys_ui_policy_action")),

    ("Pharmacy Incident Workflow",
     "UI actions, business rules, and record producers for pharmacy incident: submit, close, regional manager, days tracking.",
     lambda r: r["mt"] == "u_task_pharmacy_incident" and r["sc"] in ("sys_ui_action", "sys_script", "sc_cat_item_producer")),

    ("Pharmacy SSC Task Management",
     "UI policies, actions, and rules on pharmacy incident SSC tasks child table.",
     lambda r: r["mt"] == "u_pharmacy_incident_ssc_tasks"),

    # --- Incident Data Model ---
    ("Incident Field Schema",
     "Custom dictionary entries and overrides defining the incident field schema. Includes custom fields on incident and related tables.",
     lambda r: r["sc"] in ("sys_dictionary", "sys_dictionary_override") and not r["mt"]),

    ("Incident Table Definitions",
     "Custom table definitions (sys_db_object) for incident-related tables.",
     lambda r: r["sc"] == "sys_db_object"),

    # --- Security ---
    ("Incident Security ACLs",
     "Access control lists for incident and related fields: read/write/create/delete permissions.",
     lambda r: r["sc"] == "sys_security_acl"),

    # --- Adjacent Integrations ---
    ("Change-Incident Integration",
     "Customizations on change_request referencing incidents: emergency change linking, backdating, approvals.",
     lambda r: r["mt"] == "change_request"),

    ("Task Framework Extensions",
     "Customizations on task/ticket parent tables: metrics, outage creation, attachments, on-call, business service policies.",
     lambda r: r["mt"] in ("task", "ticket")),

    ("Location & User Management",
     "cmn_location, sys_user, sys_user_group customizations: district/region sync, phone sync, group rules.",
     lambda r: r["mt"] in ("cmn_location", "sys_user", "sys_user_group", "sys_user_grmember")),

    ("CMDB & Outage Integration",
     "CMDB CI service and outage customizations interacting with incident management.",
     lambda r: r["mt"] in ("cmdb_ci_service", "cmdb_ci_outage")),

    ("Service Catalog Integration",
     "Order guides, catalog task customizations, and RITM scripts feeding into incident process.",
     lambda r: r["mt"] in ("sc_task", "sc_req_item") or r["sc"] == "sc_cat_item_guide"),

    ("Problem-Incident Integration",
     "Problem table customizations communicating workarounds to incident management.",
     lambda r: r["mt"] == "problem"),

    ("Incident-to-Work-Order Bridge",
     "u_dl_incident_to_work_order and attachment copy customizations bridging incidents to work orders.",
     lambda r: r["mt"] in ("u_dl_incident_to_work_order", "sys_attachment")),

    # --- Shared Infrastructure ---
    ("Shared Script Libraries",
     "Script includes used across incident and related processes: SAML, requirements, time card, change risk.",
     lambda r: r["sc"] == "sys_script_include" and not r["mt"]),

    ("Global UI Extensions",
     "Global-scope UI actions affecting the platform broadly.",
     lambda r: r["mt"] in ("global", "")),
]


def main():
    print("=" * 60)
    print("Assessment 24 — Feature Grouping")
    print("=" * 60)

    # Fetch all in-scope artifacts
    print("\nFetching in-scope artifacts...")
    raw = sql_all(
        "SELECT sr.id, sr.name, sr.sys_class_name, sr.meta_target_table, sr.observations "
        "FROM scan_result sr JOIN scan s ON sr.scan_id = s.id "
        "WHERE s.assessment_id = 24 "
        "AND sr.id IN (SELECT scan_result_id FROM customization) "
        "AND sr.is_out_of_scope = 0 "
        "ORDER BY sr.id"
    )
    # Normalize for matching
    artifacts = []
    for r in raw:
        artifacts.append({
            "id": r["id"],
            "name": r["name"],
            "sc": r["sys_class_name"] or "",
            "mt": r["meta_target_table"] or "",
            "obs": r["observations"] or "",
        })
    print(f"Total in-scope: {len(artifacts)}")

    # Get existing empty features we can reuse
    existing = sql("SELECT id, name FROM feature WHERE assessment_id = 24 ORDER BY id")
    reuse_ids = [r["id"] for r in existing["rows"]]
    print(f"Reusable feature IDs: {len(reuse_ids)}")

    assigned = set()
    summary = []

    for i, (fname, fdesc, matcher) in enumerate(FEATURES):
        # Find matching artifacts
        matches = [a for a in artifacts if a["id"] not in assigned and matcher(a)]
        if not matches:
            continue

        # Create or reuse feature
        if reuse_ids:
            fid = reuse_ids.pop(0)
            # Rename reused feature
            mcp_call("update_feature", {
                "feature_id": fid,
                "name": fname,
                "description": fdesc,
            })
        else:
            result = mcp_call("create_feature", {
                "assessment_id": ASSESSMENT_ID,
                "name": fname,
                "description": fdesc,
                "name_status": "final",
            })
            fid = result.get("feature_id") or result.get("id")

        # Assign artifacts
        count = 0
        errors = 0
        for a in matches:
            try:
                mcp_call("add_result_to_feature", {
                    "scan_result_id": a["id"],
                    "feature_id": fid,
                })
                assigned.add(a["id"])
                count += 1
            except Exception as e:
                errors += 1
                if errors <= 2:
                    print(f"    Error assigning {a['id']}: {e}")

        print(f"  [{count:3d}] {fname} (feature #{fid})")
        summary.append((fname, count, fid))

    # Handle orphans
    orphans = [a for a in artifacts if a["id"] not in assigned]
    if orphans:
        if reuse_ids:
            fid = reuse_ids.pop(0)
            mcp_call("update_feature", {
                "feature_id": fid,
                "name": "Miscellaneous Incident Customizations",
                "description": "Remaining customizations related to incident process without a specific feature group.",
            })
        else:
            result = mcp_call("create_feature", {
                "assessment_id": ASSESSMENT_ID,
                "name": "Miscellaneous Incident Customizations",
                "description": "Remaining customizations related to incident process without a specific feature group.",
                "feature_kind": "bucket",
                "name_status": "final",
            })
            fid = result.get("feature_id") or result.get("id")

        misc_count = 0
        for a in orphans:
            try:
                mcp_call("add_result_to_feature", {
                    "scan_result_id": a["id"],
                    "feature_id": fid,
                })
                assigned.add(a["id"])
                misc_count += 1
            except:
                pass

        print(f"  [{misc_count:3d}] Miscellaneous Incident Customizations (feature #{fid})")
        summary.append(("Miscellaneous Incident Customizations", misc_count, fid))

    # Clean up unused reuse features
    for unused_id in reuse_ids:
        try:
            mcp_call("update_feature", {
                "feature_id": unused_id,
                "name": f"(empty - unused #{unused_id})",
                "description": "Placeholder - no artifacts assigned",
            })
        except:
            pass

    # Print summary
    print(f"\n{'='*60}")
    print("FEATURE GROUPING SUMMARY")
    print(f"{'='*60}")
    print(f"  Total in-scope:      {len(artifacts)}")
    print(f"  Assigned to features: {len(assigned)}")
    print(f"  Features with members: {len(summary)}")
    print()
    for fname, cnt, fid in sorted(summary, key=lambda x: -x[1]):
        print(f"  {cnt:4d}  {fname}")


if __name__ == "__main__":
    main()
