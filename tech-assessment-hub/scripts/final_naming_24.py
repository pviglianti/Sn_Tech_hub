#!/usr/bin/env python3
"""Final Naming pass for Assessment 24.

Renames all provisional AI-authored features to final human-readable names
based on what artifacts do together, what solution they form, and what
business capability they deliver.

Does NOT override human-locked feature names or memberships.
"""

import json
import requests

MCP_URL = "http://127.0.0.1:8080/mcp"
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


# FINAL NAMING MAPPINGS
# feature_id -> (new_name, description, bucket_key_if_bucket)
FINAL_NAMES = {
    10: ("Incident Form Field Policies", "55 UI policies controlling field behavior, visibility, and state on the incident form across lifecycle stages.", None),
    11: ("Incident Client-Side Behavior", "30 client-side scripts on the incident form handling VIP highlighting, location rendering, validation, and choice manipulation.", None),
    12: ("Incident Business Rules", "29 server-side rules managing work order lifecycle, assignment logic, field synchronization, and state management.", None),
    13: ("Incident UI Actions", "19 custom buttons and actions on the incident form (58% OOTB-modified, high upgrade sensitivity).", None),
    14: ("Incident Record Producers", "56 catalog intake forms creating incidents across IT, equipment, pharmacy, and other business functions.", None),
    15: ("Pharmacy Incident Form Policies", "148 UI policies managing the complex pharmacy incident form including patient info, root cause analysis, and compliance fields.", None),
    16: ("Pharmacy Incident Workflow", "Operational workflow for pharmacy incidents with submit/close actions, days-opened tracking, and intake forms.", None),
    17: ("Pharmacy SSC Task Management", "Task lifecycle management for SSC (structured incident subtasks) within pharmacy incidents.", None),
    18: ("Incident Field Schema", "172 custom fields and dictionary overrides — the critical dependency hub referenced by all other incident features.", None),
    19: ("Incident Table Definitions", "Custom table extensions: Pharmacy Incident, Pharmacy SSC Tasks, and Incident-to-WO Map.", None),
    20: ("Incident Security ACLs", "65 field-level and record-level access control rules managing PHI, encryption, and custom field permissions.", None),
    21: ("Change-Incident Integration", "Emergency change linking, backdating, and approval automation with incident integration.", None),
    22: ("Task Framework Extensions", "Metrics, outage creation, on-call triggers, LIFT intake, and accounting code automation across all task tables.", None),
    23: ("Location & User Management", "District/region synchronization and user/group management supporting incident assignment.", None),
    24: ("CMDB & Outage Integration", "Incident work notes synced from outage records and SOX compliance information from service CI.", None),
    25: ("Service Catalog Integration", "Order guides and catalog navigation funneling service requests that may spawn incidents.", None),
    26: ("Problem-Incident Integration", "Problem record linking and incident reference tracking for problem management workflows.", None),
    27: ("Incident-to-Work-Order Bridge", "Comprehensive work order integration: auto-creation from incidents, lifecycle syncing, and queue routing.", None),
    28: ("Authentication & Integration Libraries", "Shared script includes supporting SAML2 authentication, data transformation, and utility functions.", None),
    29: ("Global UI & Admin Utilities", "System admin utilities and global UI enhancements.", None),
}


def main():
    print(f"{'='*70}")
    print(f"FINAL NAMING PASS — Assessment {ASSESSMENT_ID}")
    print(f"{'='*70}\n")

    # Rename all provisional features
    print("[1/2] Renaming provisional features...")
    renamed_count = 0
    skipped_count = 0

    for feature_id, (final_name, description, bucket_key) in FINAL_NAMES.items():
        # Get current feature details
        try:
            feature_detail = mcp_call("get_feature_detail", {"feature_id": feature_id})
        except Exception as e:
            print(f"  ⚠ Feature #{feature_id}: Could not load — {e}")
            continue

        # Check if feature is human-locked (should NOT rename)
        if feature_detail.get("name_status") == "human_locked":
            print(f"  ✓ Feature #{feature_id}: '{feature_detail.get('name')}' — HUMAN-LOCKED, skipping")
            skipped_count += 1
            continue

        # Check if feature is marked provisional
        is_provisional = feature_detail.get("name_status") == "provisional"
        current_name = feature_detail.get("name", "")

        if is_provisional or (not current_name or current_name.startswith("Feature_")):
            # Rename it
            update_args = {
                "feature_id": feature_id,
                "name": final_name,
                "description": description,
                "name_status": "final",
            }
            if bucket_key:
                update_args["bucket_key"] = bucket_key

            try:
                mcp_call("update_feature", update_args)
                print(f"  ✓ Feature #{feature_id}: renamed to '{final_name}'")
                renamed_count += 1
            except Exception as e:
                print(f"  ✗ Feature #{feature_id}: rename failed — {e}")
        else:
            print(f"  ✓ Feature #{feature_id}: '{current_name}' — already named, keeping")
            skipped_count += 1

    print(f"\n  Total renamed: {renamed_count}")
    print(f"  Skipped/locked: {skipped_count}")

    # Summary
    print(f"\n{'='*70}")
    print("FINAL NAMING COMPLETE")
    print(f"{'='*70}")
    print(f"  Features processed: {len(FINAL_NAMES)}")
    print(f"  Features renamed: {renamed_count}")
    print(f"  Features kept as-is: {skipped_count}")


if __name__ == "__main__":
    main()
