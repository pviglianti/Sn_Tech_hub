#!/usr/bin/env python3
"""Regroup Assessment 24 v2 — deeper business-capability split.

Splits the large catch-all features into pointed sub-features:
- Store Equipment & Facilities (equipment functional, gas, register, scales)
- Caller & Contact Management (VIP caller, on-behalf-of, caller not found)
- PHI & Encryption (encrypted fields, PHI info)
- Incident Severity & Escalation (Sev 3 auto-populate, major incident)
"""

import json
import re
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


def remove_all():
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
        print(f"    Cleared {total}...")
    return total


# -----------------------------------------------------------------------
# Artifact classification helpers
# -----------------------------------------------------------------------

def _text(art):
    """Build searchable text from artifact."""
    return " ".join([
        art.get("name") or "",
        art.get("observations") or "",
        art.get("meta_target_table") or "",
    ]).lower()


# Pharmacy: anything on pharmacy tables or referencing them
def is_pharmacy(a):
    mt = (a.get("meta_target_table") or "").lower()
    if "pharmacy" in mt:
        return True
    t = _text(a)
    if "u_task_pharmacy" in t or "pharmacy_incident" in t:
        return True
    # Pharmacy dict entries and policies
    name = (a.get("name") or "").lower()
    if "pharmacy" in name:
        return True
    return False


# Work Order IDs (identified in analysis)
WO_RESULT_IDS = {
    203927, 203964, 203966, 203967, 203984, 203985, 203986, 203987, 203992,
    205844, 205834, 205835, 205833, 205846,
    206747, 206752, 206753, 206745, 206734, 206744,
    205927, 205937, 206074,
    206316, 206310, 206309,
    210510, 210658, 210659, 210660, 210661,
    210235,
    204032, 204042, 205843,
}


def is_wo(a):
    if a["id"] in WO_RESULT_IDS:
        return True
    t = _text(a)
    if "work order" in t or "wm_order" in t or "work_order" in t:
        return True
    name = (a.get("name") or "")
    if "WO" in name and ("Create" in name or "Map" in name or "Push" in name or "Generate" in name or "Sync" in name):
        return True
    return False


# Assignment IDs
ASSIGN_IDS = {
    203957, 203926, 203917, 203924, 203918,
    205809, 205824, 205812, 205811,
    210215, 210222,
    205995, 206067, 206070,
    210529, 210679,
}


def is_assignment(a):
    if a["id"] in ASSIGN_IDS:
        return True
    t = _text(a)
    if "assignment_group" in t or "assigned_to" in t:
        name = (a.get("name") or "").lower()
        # Only catch if the artifact is ABOUT assignment, not just referencing it
        if any(kw in name for kw in ["assign", "routing", "revert"]):
            return True
    return False


# Store Equipment & Facilities
def is_equipment(a):
    t = _text(a)
    keywords = [
        "equipment", "gas pump", "gas-and-go", "register issue",
        "register scale", "self checkout", "department scale",
        "weights & measures", "weights and measures",
        "building maintenance", "refrigeration",
        "jolt", "affected stores", "affected_stores",
        "is_equipment_functional", "is equipment functional",
        "store number", "store_number", "u_store",
        "fuel", "aptaris",
    ]
    for kw in keywords:
        if kw in t:
            return True
    name = (a.get("name") or "")
    if "Store" in name and ("number" in name.lower() or "portal" in name.lower()):
        return True
    return False


# Caller & Contact Management
def is_caller(a):
    t = _text(a)
    keywords = [
        "caller", "on behalf of", "on_behalf_of", "u_on_behalf_of",
        "vip", "caller_not_found", "caller not found",
        "u_caller", "caller_id", "caller_name",
        "watchlist", "watch_list", "watch list",
        "pwi watchlist",
    ]
    for kw in keywords:
        if kw in t:
            return True
    return False


# PHI & Encryption
def is_phi(a):
    t = _text(a)
    keywords = [
        "phi", "encrypt", "encryption", "encrypted",
        "hipaa", "protected health",
    ]
    for kw in keywords:
        if kw in t:
            return True
    return False


# Adjacent (non-incident tables)
def is_adjacent(a):
    mt = (a.get("meta_target_table") or "")
    adjacent_tables = {
        "change_request", "problem", "task", "ticket",
        "cmn_location", "sys_user", "sys_user_group", "sys_user_grmember",
        "cmdb_ci_service", "cmdb_ci_outage", "sc_task", "sc_req_item",
        "global",
    }
    if mt in adjacent_tables:
        return True
    if a.get("sys_class_name") == "sc_cat_item_guide":
        return True
    return False


# Record producer (remaining)
def is_rp(a):
    return a.get("sys_class_name") == "sc_cat_item_producer"


# ACL
def is_acl(a):
    return a.get("sys_class_name") == "sys_security_acl"


# Script include or table def
def is_infra(a):
    return a.get("sys_class_name") in ("sys_script_include", "sys_db_object")


# -----------------------------------------------------------------------
# Feature definitions (ordered by priority — first match wins)
# -----------------------------------------------------------------------

FEATURES = [
    ("Pharmacy Incident Solution",
     "Complete custom pharmacy incident subsystem: u_task_pharmacy_incident table, "
     "UI policies/actions for complex multi-step forms, workflow (submit/close/regional manager), "
     "SSC child tasks, pharmacy-specific fields, and record producers. All net-new. "
     "Largest business capability — 200+ artifacts.",
     is_pharmacy, "functional", "direct"),

    ("Incident-to-Work-Order Integration",
     "All WO lifecycle customizations: business rules creating/syncing/closing work orders, "
     "u_dl_incident_to_work_order bridge table, WO-related fields and ACLs, "
     "WO creation UI actions, and work-type client scripts. Primary consolidation target.",
     is_wo, "functional", "mixed"),

    ("Incident Assignment & Routing",
     "Assignment group, assigned_to, and routing logic: auto-assignment rules, "
     "revert-to-assigned, group inheritance, assignment client scripts, "
     "dictionary overrides on assignment fields, and related ACLs.",
     is_assignment, "functional", "direct"),

    ("Store Equipment & Facilities",
     "Store-level equipment management: 'Is Equipment Functional' field and policy, "
     "gas pump/register/scale/self-checkout record producers, affected stores tracking, "
     "gas-and-go tab, Jolt integration, building maintenance, and refrigeration vendor list. "
     "Represents the retail/store operations intake channel.",
     is_equipment, "functional", "direct"),

    ("Caller & Contact Management",
     "Caller identification and contact handling: VIP caller highlighting, "
     "caller-not-found workflow, on-behalf-of field management, caller-to-watchlist sync, "
     "PWI watchlist notification group, and related UI policies/actions.",
     is_caller, "functional", "direct"),

    ("PHI & Data Encryption",
     "Protected Health Information handling: PHI field, encrypted text fields, "
     "encryption context management, encrypted-by tracking, PHI button messaging, "
     "and read-only enforcement for encrypted fields. Compliance-critical.",
     is_phi, "functional", "direct"),

    ("Adjacent Platform Integrations",
     "Customizations on non-incident tables: change request linking, problem workaround "
     "communication, task/ticket framework, location/user management, CMDB/outage, "
     "and catalog order guides.",
     is_adjacent, "functional", "adjacent"),

    ("Incident Record Producers",
     "Remaining service catalog record producers: IT hardware, software issues, "
     "password reset, PeopleSoft, online shopping, badge issues, general intake. "
     "Rationalization candidate.",
     is_rp, "functional", "direct"),

    ("Incident Security & Access Control",
     "Remaining ACLs for incident fields. Controls read/write permissions. "
     "Includes OOTB-modified ACLs requiring baseline comparison.",
     is_acl, "bucket", "direct"),

    ("Shared Infrastructure",
     "Script includes and table definitions shared across features.",
     is_infra, "bucket", "mixed"),

    ("Incident State & Lifecycle Management",
     "State transitions, reopening, closing restrictions, resolve actions, "
     "on-hold enforcement, draft state management, and read-only field policies "
     "tied to incident lifecycle stages.",
     lambda a: _text(a) and any(kw in _text(a) for kw in [
         "reopen", "resolve", "close", "cancel", "on.hold", "on_hold",
         "draft", "inactive", "read.only incident", "read-only incident",
         "state", "restrict", "mandatory field",
     ]) and (a.get("sys_class_name") or "") != "sys_dictionary",
     "functional", "direct"),

    ("Incident Cross-Record Creation",
     "UI actions for creating related records from an incident: "
     "Create Emergency Change, Normal Change, Standard Change, Problem, "
     "Outage, Feature, Request. Enables ITIL cross-process workflows.",
     lambda a: (a.get("name") or "").startswith("Create ") and a.get("sys_class_name") == "sys_ui_action",
     "functional", "direct"),

    ("Incident Categorization & Triage",
     "Category, subcategory, priority, urgency, list level, duplicate detection, "
     "lane/terminal ID, and related clear-on-change policies. Controls how incidents "
     "are classified and prioritized at intake.",
     lambda a: any(kw in _text(a) for kw in [
         "category", "subcategory", "priority", "urgency", "duplicate",
         "list level", "list_level", "lane", "terminal_id",
         "triage", "classification",
     ]) and (a.get("sys_class_name") or "") != "sys_dictionary",
     "functional", "direct"),

    ("Incident Field Schema",
     "Custom dictionary entries and overrides defining the incident field data model. "
     "Foundation layer referenced by all other features.",
     lambda a: a.get("sys_class_name") in ("sys_dictionary", "sys_dictionary_override"),
     "bucket", "direct"),

    ("Incident Form Behavior",
     "Remaining incident form customizations: client scripts for location rendering, "
     "form redirects, field toggling, and miscellaneous UI actions (Copy, Workflow, Next). "
     "General form UX behavior.",
     lambda a: True,  # final catch-all
     "functional", "direct"),
]


def main():
    print("=" * 60)
    print("Assessment 24 — Feature Regrouping v2")
    print("=" * 60)

    # Clear
    print("\n[1/3] Clearing assignments...")
    removed = remove_all()
    print(f"  Cleared {removed}")

    # Fetch
    print("\n[2/3] Fetching artifacts...")
    artifacts = sql_all(
        "SELECT sr.id, sr.name, sr.sys_class_name, sr.meta_target_table, "
        "sr.observations, sr.origin_type "
        "FROM scan_result sr JOIN scan s ON sr.scan_id = s.id "
        "WHERE s.assessment_id = 24 "
        "AND sr.id IN (SELECT scan_result_id FROM customization) "
        "AND sr.is_out_of_scope = 0 "
        "ORDER BY sr.id"
    )
    print(f"  Total: {len(artifacts)}")

    existing = sql("SELECT id FROM feature WHERE assessment_id = 24 ORDER BY id")
    reuse_ids = [r["id"] for r in existing["rows"]]

    # Assign
    print("\n[3/3] Creating features...")
    assigned = set()
    results = []

    for fname, fdesc, matcher, fkind, fcomp in FEATURES:
        matches = [a for a in artifacts if a["id"] not in assigned and matcher(a)]
        if not matches:
            continue

        if reuse_ids:
            fid = reuse_ids.pop(0)
            mcp_call("update_feature", {
                "feature_id": fid,
                "name": fname,
                "description": fdesc,
                "feature_kind": fkind,
                "composition_type": fcomp,
                "name_status": "final",
            })
        else:
            result = mcp_call("create_feature", {
                "assessment_id": ASSESSMENT_ID,
                "name": fname,
                "description": fdesc,
                "feature_kind": fkind,
                "composition_type": fcomp,
                "name_status": "final",
            })
            fid = result.get("feature_id") or result.get("id")

        count = 0
        for a in matches:
            try:
                mcp_call("add_result_to_feature", {
                    "scan_result_id": a["id"],
                    "feature_id": fid,
                })
                assigned.add(a["id"])
                count += 1
            except:
                pass

        results.append((fname, count, fid))
        print(f"  [{count:4d}] {fname} (#{fid})")

    # Clean unused
    for uid in reuse_ids:
        try:
            mcp_call("update_feature", {
                "feature_id": uid,
                "name": f"(unused #{uid})",
                "description": "Empty",
            })
        except:
            pass

    # Verify
    orphans = len(artifacts) - len(assigned)
    dup_check = sql(
        "SELECT fsr.scan_result_id, COUNT(*) as cnt "
        "FROM feature_scan_result fsr JOIN feature f ON fsr.feature_id = f.id "
        "WHERE f.assessment_id = 24 "
        "GROUP BY fsr.scan_result_id HAVING cnt > 1"
    )
    dups = dup_check["rows"]

    print(f"\n{'='*60}")
    print("REGROUPING v2 SUMMARY")
    print(f"{'='*60}")
    for name, cnt, fid in sorted(results, key=lambda x: -x[1]):
        print(f"  {cnt:4d}  {name}")
    print(f"\n  Assigned: {len(assigned)} / {len(artifacts)}")
    print(f"  Orphans:  {orphans}")
    print(f"  Dupes:    {len(dups)}")
    if dups:
        print(f"  ⚠ Duplicate assignments detected!")
    else:
        print(f"  ✓ Each artifact in exactly one feature")


if __name__ == "__main__":
    main()
