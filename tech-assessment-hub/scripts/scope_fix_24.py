#!/usr/bin/env python3
"""Fix scope classifications for assessment 24.

The first pass didn't have meta_target_table from customization records.
This script corrects classifications using scan_result.meta_target_table.
"""

import json
import requests

MCP_URL = "http://127.0.0.1:8081/mcp"


def mcp_call(tool_name, arguments):
    payload = {
        "jsonrpc": "2.0", "id": 1,
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
    return content


def sql(query):
    return mcp_call("sqlite_query", {"sql": query})


def update(result_id, **kwargs):
    args = {"result_id": result_id}
    args.update(kwargs)
    return mcp_call("update_scan_result", args)


CORE_TABLES = {"incident", "incident_task"}
INCIDENT_RELATED = {
    "u_task_pharmacy_incident",
    "u_pharmacy_incident_ssc_tasks",
    "u_dl_incident_to_work_order",
}
PARENT_TABLES = {"task"}
ADJACENT_TABLES = {
    "change_request", "problem", "sc_task", "sc_req_item",
    "cmdb_ci_service", "cmdb_ci_outage", "sys_user", "sys_user_group",
    "sys_user_grmember", "cmn_location", "sys_attachment", "ticket",
}
OOS_TABLES = {
    "sm_incidentals", "sm_order", "sm_task", "wm_order", "wm_task",
    "dmn_demand", "rm_feature", "rm_release", "pm_project",
    "alm_stockroom", "time_card", "task_time_worked",
    "std_change_proposal", "fruition_update_request",
    "business_app_request", "sc_ic_category_request",
    "sn_disco_certmgmt_revoke_task", "u_drug_store_chain_security_act",
    "u_update_set_management", "u_ad_hoc_request", "facilities_request",
}


def determine_scope(meta_table):
    """Return (decision, rationale) based on meta_target_table."""
    if not meta_table:
        return None
    if meta_table in CORE_TABLES:
        return ("in_scope", f"Directly on core incident table: {meta_table}")
    if meta_table in INCIDENT_RELATED:
        return ("in_scope", f"Custom incident-related table: {meta_table}")
    if meta_table in PARENT_TABLES:
        return ("adjacent", f"Parent table of incident hierarchy: {meta_table}")
    if meta_table in ADJACENT_TABLES:
        return ("adjacent", f"Table commonly references incident: {meta_table}")
    if meta_table in OOS_TABLES:
        return ("out_of_scope", f"Unrelated module table: {meta_table}")
    return None


def main():
    print("Fetching all assessment 24 scan results with meta_target_table...")

    # Fetch in pages since sqlite_query has a 200 row max
    all_rows = []
    page = 0
    while True:
        result = sql(
            "SELECT sr.id, sr.meta_target_table, sr.ai_observations "
            "FROM scan_result sr JOIN scan s ON sr.scan_id = s.id "
            "WHERE s.assessment_id = 24 "
            "AND sr.id IN (SELECT scan_result_id FROM customization) "
            f"ORDER BY sr.id LIMIT 200 OFFSET {page * 200}"
        )
        rows = result["rows"]
        all_rows.extend(rows)
        if len(rows) < 200:
            break
        page += 1

    rows = all_rows
    print(f"Total results: {len(rows)}")

    # Count current state
    corrections = {"to_in_scope": 0, "to_adjacent": 0, "to_oos": 0, "unchanged": 0}

    for i, row in enumerate(rows):
        rid = row["id"]
        meta = row["meta_target_table"]
        scope = determine_scope(meta)

        if scope is None:
            corrections["unchanged"] += 1
            continue

        decision, rationale = scope

        # Check current ai_observations
        current_ai = None
        if row["ai_observations"]:
            try:
                current_ai = json.loads(row["ai_observations"])
            except (json.JSONDecodeError, TypeError):
                pass

        current_decision = current_ai.get("scope_decision") if current_ai else None

        if current_decision == decision:
            corrections["unchanged"] += 1
            continue

        # Need to fix
        ai_obs = {
            "analysis_stage": "ai_analysis",
            "scope_decision": decision,
            "scope_rationale": rationale,
            "directly_related_result_ids": [],
            "directly_related_artifacts": [],
        }

        is_oos = decision == "out_of_scope"
        is_adj = decision == "adjacent"

        try:
            update(rid,
                   review_status="review_in_progress",
                   is_out_of_scope=is_oos,
                   is_adjacent=is_adj,
                   observations=rationale,
                   ai_observations=json.dumps(ai_obs))

            if decision == "in_scope":
                corrections["to_in_scope"] += 1
            elif decision == "adjacent":
                corrections["to_adjacent"] += 1
            else:
                corrections["to_oos"] += 1
        except Exception as e:
            print(f"  Error updating {rid}: {e}")

        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(rows)}...")

    print(f"\nCorrections applied:")
    print(f"  Corrected to in_scope:  {corrections['to_in_scope']}")
    print(f"  Corrected to adjacent:  {corrections['to_adjacent']}")
    print(f"  Corrected to OOS:       {corrections['to_oos']}")
    print(f"  Unchanged:              {corrections['unchanged']}")

    # Final stats
    print("\nFinal scope breakdown:")
    final = sql(
        "SELECT json_extract(sr.ai_observations, '$.scope_decision') as decision, COUNT(*) as cnt "
        "FROM scan_result sr JOIN scan s ON sr.scan_id = s.id "
        "WHERE s.assessment_id = 24 "
        "AND sr.id IN (SELECT scan_result_id FROM customization) "
        "AND sr.ai_observations IS NOT NULL "
        "GROUP BY json_extract(sr.ai_observations, '$.scope_decision')"
    )
    for row in final["rows"]:
        print(f"  {row['decision']}: {row['cnt']}")


if __name__ == "__main__":
    main()
