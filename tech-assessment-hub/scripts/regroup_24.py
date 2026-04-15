#!/usr/bin/env python3
"""Regroup Assessment 24 into business-capability features.

Restructures from artifact-type grouping to business-capability grouping:
1. Pharmacy Incident Solution
2. Work Order Integration
3. Incident Assignment & Routing
4. Incident Form & Field Configuration
5. Incident Record Producers
6. Incident Security & Access Control
7. Adjacent Platform Integrations
8. Shared Infrastructure
"""

import json
import re
import requests

MCP_URL = "http://127.0.0.1:8081/mcp"
ASSESSMENT_ID = 24

# Work Order artifact IDs (from analysis)
WO_IDS = {
    # Business rules
    203927, 203964, 203966, 203967, 203984, 203985, 203986, 203987, 203992,
    # Client scripts
    205844, 205834, 205835, 205833, 205846,
    # Dictionary entries (WO fields)
    206747, 206752, 206753, 206745, 206734, 206744,
    # UI policies about WO/work
    205927, 205937, 206074,
    # UI actions
    206316, 206310, 206309,
    # ACLs on WO fields/tables
    210510, 210658, 210659, 210660, 210661,
    # Table definition (WO bridge)
    210235,
    # WO Bridge feature (all 3)
    204032, 204042, 205843,
    # "Check for Open Work Orders on Close"
}

# Assignment artifact IDs (from analysis)
ASSIGN_IDS = {
    # Business rules
    203957, 203926, 203917, 203924, 203918,
    # Client scripts
    205809, 205824, 205812, 205811,
    # Dictionary overrides
    210215, 210222,
    # UI policy + actions
    205995, 206067, 206070,
    # ACLs
    210529, 210679,
}


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


def remove_all_assignments():
    """Remove all current feature assignments."""
    total = 0
    while True:
        rows = sql(
            "SELECT fsr.scan_result_id, fsr.feature_id "
            "FROM feature_scan_result fsr JOIN feature f ON fsr.feature_id = f.id "
            "WHERE f.assessment_id = 24 LIMIT 200"
        )["rows"]
        if not rows:
            break
        for row in rows:
            try:
                mcp_call("remove_result_from_feature", {
                    "scan_result_id": row["scan_result_id"],
                    "feature_id": row["feature_id"],
                })
                total += 1
            except:
                pass
        print(f"    Removed batch... total: {total}")
    return total


def is_pharmacy(art):
    """Check if artifact is pharmacy-related."""
    mt = art["meta_target_table"] or ""
    name = art["name"] or ""
    obs = art["observations"] or ""
    if "pharmacy" in mt.lower():
        return True
    if "pharmacy" in name.lower():
        return True
    # Check observations for pharmacy table references
    if "u_task_pharmacy" in obs.lower():
        return True
    if "pharmacy_incident" in obs.lower():
        return True
    return False


def is_wo(art):
    """Check if artifact is Work Order related."""
    return art["id"] in WO_IDS


def is_assignment(art):
    """Check if artifact is assignment/routing related."""
    return art["id"] in ASSIGN_IDS


def is_adjacent(art):
    """Check if artifact is on an adjacent (non-incident) table."""
    mt = art["meta_target_table"] or ""
    adjacent_tables = {
        "change_request", "problem", "task", "ticket",
        "cmn_location", "sys_user", "sys_user_group", "sys_user_grmember",
        "cmdb_ci_service", "cmdb_ci_outage", "sc_task", "sc_req_item",
        "global",
    }
    return mt in adjacent_tables


def is_catalog_guide(art):
    """Check if it's a catalog order guide."""
    return art["sys_class_name"] == "sc_cat_item_guide"


def is_acl(art):
    """Check if it's a security ACL."""
    return art["sys_class_name"] == "sys_security_acl"


def is_record_producer(art):
    """Check if it's a record producer."""
    return art["sys_class_name"] == "sc_cat_item_producer"


def is_script_include(art):
    """Check if it's a script include."""
    return art["sys_class_name"] == "sys_script_include"


def is_table_def(art):
    """Check if it's a table definition."""
    return art["sys_class_name"] == "sys_db_object"


# Feature definitions: ordered by priority (first match wins)
NEW_FEATURES = [
    {
        "name": "Pharmacy Incident Solution",
        "description": (
            "Complete custom pharmacy incident subsystem: u_task_pharmacy_incident table, "
            "148 UI policies/actions, workflow (submit/close/regional manager), SSC child tasks, "
            "pharmacy-specific dictionary entries, and record producers. All net-new customer code. "
            "Largest business capability in this assessment."
        ),
        "match": is_pharmacy,
        "kind": "functional",
        "comp": "direct",
    },
    {
        "name": "Incident-to-Work-Order Integration",
        "description": (
            "All customizations managing the incident-to-work-order lifecycle: 8+ business rules "
            "creating/syncing/closing WOs, the u_dl_incident_to_work_order bridge table, WO-related "
            "dictionary entries, ACLs on WO fields, UI actions for WO creation/viewing, and client "
            "scripts controlling WO field behavior. Primary consolidation target."
        ),
        "match": is_wo,
        "kind": "functional",
        "comp": "mixed",
    },
    {
        "name": "Incident Assignment & Routing",
        "description": (
            "All customizations around assignment_group, assigned_to, and routing on the incident form: "
            "auto-assignment rules, revert-to-assigned logic, group-from-parent inheritance, "
            "assignment-related client scripts, dictionary overrides on assignment fields, "
            "UI policies enforcing assignment mandatory rules, and assignment ACLs."
        ),
        "match": is_assignment,
        "kind": "functional",
        "comp": "direct",
    },
    {
        "name": "Adjacent Platform Integrations",
        "description": (
            "Customizations on non-incident tables that interact with incident management: "
            "change request linking, problem workaround communication, task/ticket framework "
            "extensions, location/user management, CMDB/outage integration, and catalog order guides."
        ),
        "match": lambda a: is_adjacent(a) or is_catalog_guide(a),
        "kind": "functional",
        "comp": "adjacent",
    },
    {
        "name": "Incident Record Producers",
        "description": (
            "Service catalog record producers creating incidents. Covers IT hardware, equipment "
            "maintenance, gas pumps, registers, POS systems, and other intake channels. "
            "Primary rationalization candidate — 50+ producers suggest organic growth."
        ),
        "match": is_record_producer,
        "kind": "functional",
        "comp": "direct",
    },
    {
        "name": "Incident Security & Access Control",
        "description": (
            "Access control lists for incident and related table fields. Controls read/write/create/delete "
            "permissions. Includes 8 OOTB-modified ACLs requiring baseline comparison."
        ),
        "match": is_acl,
        "kind": "bucket",
        "comp": "direct",
        "bucket_key": "acl",
    },
    {
        "name": "Shared Infrastructure",
        "description": (
            "Script includes and table definitions shared across features: SAML2, RequirementsBuilder, "
            "SetChangeRisk, and custom table definitions. Dependencies for multiple features."
        ),
        "match": lambda a: is_script_include(a) or is_table_def(a),
        "kind": "bucket",
        "comp": "mixed",
        "bucket_key": "infrastructure",
    },
    {
        "name": "Incident Form & Field Configuration",
        "description": (
            "Remaining incident form customizations: UI policies, client scripts, business rules, "
            "UI actions, and dictionary entries that don't belong to the Pharmacy, Work Order, or "
            "Assignment features. Core form behavior, field schema, and data policies."
        ),
        "match": lambda a: True,  # Catch-all for remaining
        "kind": "functional",
        "comp": "direct",
    },
]


def main():
    print("=" * 60)
    print("Assessment 24 — Feature Regrouping")
    print("=" * 60)

    # Step 1: Clear all existing assignments
    print("\n[1/4] Clearing existing feature assignments...")
    removed = remove_all_assignments()
    print(f"  Removed {removed} assignments")

    # Step 2: Fetch all in-scope artifacts
    print("\n[2/4] Fetching in-scope artifacts...")
    artifacts = sql_all(
        "SELECT sr.id, sr.name, sr.sys_class_name, sr.meta_target_table, "
        "sr.observations, sr.origin_type "
        "FROM scan_result sr JOIN scan s ON sr.scan_id = s.id "
        "WHERE s.assessment_id = 24 "
        "AND sr.id IN (SELECT scan_result_id FROM customization) "
        "AND sr.is_out_of_scope = 0 "
        "ORDER BY sr.id"
    )
    print(f"  Total in-scope: {len(artifacts)}")

    # Get existing feature IDs to reuse
    existing = sql("SELECT id FROM feature WHERE assessment_id = 24 ORDER BY id")
    reuse_ids = [r["id"] for r in existing["rows"]]
    print(f"  Reusable feature IDs: {len(reuse_ids)}")

    # Step 3: Create features and assign
    print("\n[3/4] Creating features and assigning artifacts...")
    assigned = set()
    results = []

    for fdef in NEW_FEATURES:
        matches = [a for a in artifacts if a["id"] not in assigned and fdef["match"](a)]
        if not matches:
            continue

        # Create or reuse feature
        if reuse_ids:
            fid = reuse_ids.pop(0)
            mcp_call("update_feature", {
                "feature_id": fid,
                "name": fdef["name"],
                "description": fdef["description"],
                "feature_kind": fdef["kind"],
                "composition_type": fdef["comp"],
                "name_status": "final",
            })
            if "bucket_key" in fdef:
                try:
                    mcp_call("update_feature", {
                        "feature_id": fid,
                        "bucket_key": fdef["bucket_key"],
                    })
                except:
                    pass
        else:
            result = mcp_call("create_feature", {
                "assessment_id": ASSESSMENT_ID,
                "name": fdef["name"],
                "description": fdef["description"],
                "feature_kind": fdef["kind"],
                "composition_type": fdef["comp"],
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
                    print(f"    Error: {e}")

        results.append((fdef["name"], count, fid))
        print(f"  [{count:4d}] {fdef['name']} (feature #{fid})")

    # Rename unused features
    for uid in reuse_ids:
        try:
            mcp_call("update_feature", {
                "feature_id": uid,
                "name": f"(unused #{uid})",
                "description": "Empty — no artifacts assigned",
            })
        except:
            pass

    # Step 4: Verify
    print("\n[4/4] Verification...")
    orphans = [a for a in artifacts if a["id"] not in assigned]
    print(f"  Assigned: {len(assigned)}")
    print(f"  Orphaned: {len(orphans)}")
    if orphans:
        for o in orphans[:5]:
            print(f"    ORPHAN: {o['id']} {o['name'][:50]} ({o['sys_class_name']})")

    # Verify 1-to-1 (each result in exactly one feature)
    dup_check = sql(
        "SELECT fsr.scan_result_id, COUNT(*) as cnt "
        "FROM feature_scan_result fsr JOIN feature f ON fsr.feature_id = f.id "
        "WHERE f.assessment_id = 24 "
        "GROUP BY fsr.scan_result_id HAVING cnt > 1"
    )
    dups = dup_check["rows"]
    if dups:
        print(f"  ⚠ {len(dups)} artifacts in multiple features!")
    else:
        print(f"  ✓ All artifacts in exactly one feature")

    print(f"\n{'='*60}")
    print("REGROUPING SUMMARY")
    print(f"{'='*60}")
    for name, cnt, fid in sorted(results, key=lambda x: -x[1]):
        print(f"  {cnt:4d}  {name}")
    print(f"\n  Total: {len(assigned)} / {len(artifacts)}")


if __name__ == "__main__":
    main()
