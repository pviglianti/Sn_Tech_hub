#!/usr/bin/env python3
"""Scope triage script for Assessment 24 (Incident Management).

Target app: Incident Management
Core tables: incident, incident_task
Parent table: task

Classifies all 977 customizations as in_scope, adjacent, or out_of_scope.
"""

import json
import sys
import time
import requests

MCP_URL = "http://127.0.0.1:8081/mcp"
ASSESSMENT_ID = 24

# --- Scope definitions ---
CORE_TABLES = {"incident", "incident_task"}
PARENT_TABLES = {"task"}
# Tables that extend task and are related to incident workflows
INCIDENT_RELATED_TABLES = {
    "u_task_pharmacy_incident",  # custom incident child table
    "u_pharmacy_incident_ssc_tasks",  # child tasks of pharmacy incident
    "u_dl_incident_to_work_order",  # incident-to-WO bridge
}
# Tables that are clearly unrelated to incident management
OOS_TABLES = {
    "sm_incidentals", "sm_order", "sm_task",  # Service Management (not incident)
    "wm_order", "wm_task",  # Work Management
    "dmn_demand",  # Demand Management
    "rm_feature", "rm_release",  # Release Management
    "pm_project",  # Project Management
    "alm_stockroom",  # Asset Management
    "time_card", "task_time_worked",  # Time tracking
    "std_change_proposal",  # Change Management
    "fruition_update_request",  # Fruition
    "business_app_request",  # App portfolio
    "sc_ic_category_request",  # Service Catalog internals
    "sn_disco_certmgmt_revoke_task",  # Discovery cert mgmt
    "u_drug_store_chain_security_act",  # Custom security table
    "u_update_set_management",  # Update set management
    "u_ad_hoc_request",  # Custom request table
    "facilities_request",  # Facilities
}
# Tables adjacent to incident (reference or interact with it)
ADJACENT_TABLES = {
    "change_request",  # Often references incident
    "problem",  # Linked to incidents
    "sc_task", "sc_req_item",  # Catalog tasks may spawn incidents
    "cmdb_ci_service", "cmdb_ci_outage",  # CI/outage links to incidents
    "sys_user", "sys_user_group", "sys_user_grmember",  # Assignment groups
    "cmn_location",  # Location fields on incident
    "sys_attachment",  # Attachments on incidents
    "ticket",  # Parent of task hierarchy
    "sc_cat_item_guide",  # Catalog guides may relate
    "global",  # Global scripts — need code check
}

# Incident-related keywords for code analysis
INCIDENT_KEYWORDS = [
    "incident", "incident_task", "u_task_pharmacy_incident",
    "inc.", "INC", "major_incident", "priority_1",
    "GlideRecord('incident", "GlideRecord(\"incident",
    "getTableName()=='incident", "getTableName()==\"incident",
    "current.incident", "current.u_incident",
]


def mcp_call(tool_name, arguments):
    """Call an MCP tool and return the result."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = requests.post(MCP_URL, json=payload, timeout=30)
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


def get_all_customizations():
    """Fetch all customizations for assessment 24."""
    all_custs = []
    offset = 0
    limit = 200
    while True:
        result = mcp_call("get_customizations", {
            "assessment_id": ASSESSMENT_ID,
            "limit": limit,
            "offset": offset,
        })
        custs = result.get("customizations", [])
        all_custs.extend(custs)
        if len(custs) < limit:
            break
        offset += limit
    return all_custs


def get_result_detail(result_id):
    """Fetch full detail for a scan result."""
    return mcp_call("get_result_detail", {"result_id": result_id})


def update_result(result_id, **kwargs):
    """Update a scan result with scope findings."""
    args = {"result_id": result_id}
    args.update(kwargs)
    return mcp_call("update_scan_result", args)


def classify_by_table(meta_table, table_name):
    """Classify an artifact based on its table. Returns (decision, rationale) or None."""
    check_table = meta_table or table_name
    if not check_table:
        return None

    if check_table in CORE_TABLES:
        return ("in_scope", f"Directly on core incident table: {check_table}")

    if check_table in INCIDENT_RELATED_TABLES:
        return ("in_scope", f"Custom incident-related table: {check_table}")

    if check_table in PARENT_TABLES:
        return ("adjacent", f"Parent table of incident hierarchy: {check_table}")

    if check_table in OOS_TABLES:
        return ("out_of_scope", f"Unrelated module table: {check_table}")

    if check_table in ADJACENT_TABLES:
        return ("adjacent", f"Table that commonly references incident: {check_table}")

    return None  # Unknown — needs code analysis


def check_code_for_incident_refs(detail_data):
    """Check artifact detail for incident references. Returns (has_refs, evidence)."""
    if not detail_data:
        return False, ""

    # Build a searchable text blob from all relevant fields
    search_text = ""
    if isinstance(detail_data, dict):
        for key in ["script", "condition", "filter_condition", "script_plain",
                     "description", "short_description", "comments",
                     "advanced_condition", "template", "xml", "payload",
                     "sys_name", "name", "collection"]:
            val = detail_data.get(key)
            if val and isinstance(val, str):
                search_text += f" {val}"

        # Check artifact_detail sub-object
        ad = detail_data.get("artifact_detail")
        if isinstance(ad, dict):
            for key in ["script", "condition", "filter_condition", "advanced",
                        "template", "description", "short_description",
                        "collection", "name", "variable_name"]:
                val = ad.get(key)
                if val and isinstance(val, str):
                    search_text += f" {val}"

    search_lower = search_text.lower()
    found = []
    for kw in INCIDENT_KEYWORDS:
        if kw.lower() in search_lower:
            found.append(kw)

    if found:
        return True, f"References found: {', '.join(found[:3])}"
    return False, ""


def triage_artifact(cust, detail=None):
    """Triage a single artifact. Returns update kwargs."""
    result_id = cust["scan_result_id"]
    meta_table = cust.get("meta_target_table") or (detail or {}).get("meta_target_table")
    table_name = cust.get("table_name", "")

    # Check existing analysis
    existing_obs = None
    if detail and isinstance(detail, dict):
        raw_ai = detail.get("ai_observations")
        if raw_ai:
            try:
                existing_obs = json.loads(raw_ai) if isinstance(raw_ai, str) else raw_ai
            except (json.JSONDecodeError, TypeError):
                pass

    # If already triaged with a scope decision, skip unless it's "needs_review"
    if existing_obs and existing_obs.get("scope_decision") in ("in_scope", "adjacent", "out_of_scope"):
        return None  # Already done

    # Step 1: Try table-based classification
    table_result = classify_by_table(meta_table, table_name)
    if table_result:
        decision, rationale = table_result
        return build_update(result_id, decision, rationale, cust)

    # Step 2: Need code analysis for null/unknown table
    if detail is None:
        return "NEED_DETAIL"  # Signal to caller to fetch detail

    has_refs, evidence = check_code_for_incident_refs(detail)
    if has_refs:
        return build_update(result_id, "adjacent",
                            f"No direct table match but code references incident. {evidence}", cust)

    # Artifact type heuristics for things without table or code refs
    sys_class = cust.get("sys_class_name", "")
    if sys_class in ("sc_cat_item_guide", "sc_cat_item_producer"):
        return build_update(result_id, "out_of_scope",
                            f"Catalog item ({sys_class}) with no incident references in code", cust)
    if sys_class == "sys_script_include":
        return build_update(result_id, "needs_review",
                            f"Script include with no clear incident references — needs manual review", cust)

    # Default: out of scope if we can't find any connection
    return build_update(result_id, "out_of_scope",
                        f"No table match and no incident references found in artifact detail", cust)


def build_update(result_id, decision, rationale, cust):
    """Build the update kwargs for a scope decision."""
    is_oos = decision == "out_of_scope"
    is_adj = decision == "adjacent"

    ai_obs = {
        "analysis_stage": "ai_analysis",
        "scope_decision": decision,
        "scope_rationale": rationale,
        "directly_related_result_ids": [],
        "directly_related_artifacts": [],
    }

    observations = rationale

    kwargs = {
        "result_id": result_id,
        "review_status": "review_in_progress",
        "is_out_of_scope": is_oos,
        "is_adjacent": is_adj,
        "observations": observations,
        "ai_observations": json.dumps(ai_obs),
    }
    return kwargs


def main():
    print("=" * 60)
    print("Assessment 24 — Incident Management Scope Triage")
    print("=" * 60)

    # Phase 1: Fetch all customizations
    print("\n[1/3] Fetching all customizations...")
    custs = get_all_customizations()
    print(f"  Total: {len(custs)}")

    # Separate into pending vs already processed
    pending = [c for c in custs if c["review_status"] == "pending_review"]
    in_progress = [c for c in custs if c["review_status"] == "review_in_progress"]
    print(f"  Pending: {len(pending)}, Already in progress: {len(in_progress)}")

    # Phase 2: Table-based triage (fast pass)
    print("\n[2/3] Table-based triage (fast pass)...")
    table_classified = 0
    need_detail = []
    updates = []

    for cust in pending:
        result = triage_artifact(cust)
        if result is None:
            continue  # Already done
        if result == "NEED_DETAIL":
            need_detail.append(cust)
            continue
        updates.append(result)
        table_classified += 1

    print(f"  Classified by table: {table_classified}")
    print(f"  Need code analysis: {len(need_detail)}")

    # Apply table-based updates
    applied = 0
    errors = 0
    for upd in updates:
        try:
            update_result(**upd)
            applied += 1
            if applied % 50 == 0:
                print(f"    Applied {applied}/{len(updates)}...")
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    Error on result {upd['result_id']}: {e}")

    print(f"  Applied: {applied}, Errors: {errors}")

    # Phase 3: Code analysis for remaining
    print(f"\n[3/3] Code analysis for {len(need_detail)} artifacts...")
    code_classified = 0
    code_errors = 0
    code_updates = []

    for i, cust in enumerate(need_detail):
        try:
            detail = get_result_detail(cust["scan_result_id"])
            result = triage_artifact(cust, detail)
            if result and result != "NEED_DETAIL":
                code_updates.append(result)
                code_classified += 1
        except Exception as e:
            code_errors += 1
            if code_errors <= 3:
                print(f"    Error fetching detail for {cust['scan_result_id']}: {e}")

        if (i + 1) % 25 == 0:
            print(f"    Analyzed {i+1}/{len(need_detail)}...")

    # Apply code-analysis updates
    applied2 = 0
    for upd in code_updates:
        try:
            update_result(**upd)
            applied2 += 1
            if applied2 % 25 == 0:
                print(f"    Applied {applied2}/{len(code_updates)}...")
        except Exception as e:
            code_errors += 1

    print(f"  Classified by code: {code_classified}")
    print(f"  Applied: {applied2}, Errors: {code_errors}")

    # Summary
    print("\n" + "=" * 60)
    print("TRIAGE SUMMARY")
    print("=" * 60)

    # Count decisions
    decisions = {"in_scope": 0, "adjacent": 0, "out_of_scope": 0, "needs_review": 0}
    for upd in updates + code_updates:
        ai = json.loads(upd["ai_observations"])
        decisions[ai["scope_decision"]] += 1

    print(f"  In scope:     {decisions['in_scope']}")
    print(f"  Adjacent:     {decisions['adjacent']}")
    print(f"  Out of scope: {decisions['out_of_scope']}")
    print(f"  Needs review: {decisions['needs_review']}")
    print(f"  Skipped:      {len(in_progress)} (already in progress)")
    print(f"  Total errors: {errors + code_errors}")


if __name__ == "__main__":
    main()
