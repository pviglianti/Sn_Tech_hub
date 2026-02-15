#!/usr/bin/env python3
"""One-time script: Pull sys_dictionary entries for all app file class tables.

Connects to instance 5 (BVP 3) and fetches the field definitions for each
SN table referenced by the app file class catalog. Output is written to
a JSON file for reference when building detail_fields in the catalog.

Usage:
    cd tech-assessment-hub
    ./venv/bin/python scripts/pull_artifact_dictionary.py
"""

import json
import sys
from pathlib import Path

# Add project root to path so 'src' package imports work
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlmodel import Session, select
from src.database import engine
from src.models import Instance
import src.models_sn  # noqa: F401 — needed to resolve SQLModel relationships
from src.services.encryption import decrypt_password
from src.services.sn_client import ServiceNowClient

INSTANCE_ID = 5  # BVP 3

# All app file class SN table names we want dictionary data for
TARGET_TABLES = [
    "sys_script",              # Business Rule
    "sys_script_include",      # Script Include
    "sys_script_client",       # Client Script
    "sys_ui_policy",           # UI Policy
    "sys_ui_policy_action",    # UI Policy Action
    "sys_ui_action",           # UI Action
    "sys_ui_page",             # UI Page
    "sys_ui_macro",            # UI Macro
    "sys_dictionary",          # Dictionary Entry
    "sys_choice",              # Choice List
    "sys_db_object",           # Table
    "sys_data_policy2",        # Data Policy
    "sys_security_acl",        # ACL
    "sysauto_script",          # Scheduled Job
    "sysevent_email_action",   # Email Notification
    "sysevent_script_action",  # Event Script
    "sys_hub_flow",            # Flow
    "wf_workflow",             # Workflow
    "sp_widget",               # Service Portal Widget
    "sp_page",                 # Service Portal Page
    "sys_transform_map",       # Transform Map
    "sys_web_service",         # Scripted REST API
    "sys_report",              # Report
]

# Fields to pull from sys_dictionary for each table
DICT_FIELDS = [
    "name",                # column name
    "element",             # field name on the table
    "column_label",        # display label
    "internal_type",       # string, boolean, integer, script, etc.
    "max_length",
    "mandatory",
    "read_only",
    "active",
    "reference",           # reference table if it's a reference field
    "default_value",
    "choice",              # choice list type
]


def main():
    with Session(engine) as session:
        instance = session.get(Instance, INSTANCE_ID)
        if not instance:
            print(f"Instance {INSTANCE_ID} not found")
            sys.exit(1)

        password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(instance.url, instance.username, password)

        test = client.test_connection()
        if not test.get("success"):
            print(f"Connection failed: {test.get('message')}")
            sys.exit(1)

        print(f"Connected to {instance.name} ({instance.url})")
        print(f"Pulling dictionary for {len(TARGET_TABLES)} tables...\n")

        results = {}

        for table_name in TARGET_TABLES:
            print(f"  {table_name}...", end=" ", flush=True)

            try:
                # Query sys_dictionary for this table's fields
                query = f"name={table_name}^internal_type!=collection^active=true"
                records = client.get_records(
                    table="sys_dictionary",
                    query=query,
                    fields=DICT_FIELDS,
                    limit=500,
                    order_by="element",
                )

                # Filter to actual fields (element not empty)
                fields = []
                for rec in records:
                    element = rec.get("element", "").strip()
                    if not element:
                        continue
                    fields.append({
                        "element": element,
                        "label": rec.get("column_label", ""),
                        "type": rec.get("internal_type", ""),
                        "max_length": rec.get("max_length", ""),
                        "mandatory": rec.get("mandatory", ""),
                        "read_only": rec.get("read_only", ""),
                        "reference": rec.get("reference", ""),
                        "default_value": rec.get("default_value", ""),
                        "choice": rec.get("choice", ""),
                    })

                results[table_name] = {
                    "field_count": len(fields),
                    "fields": sorted(fields, key=lambda f: f["element"]),
                }
                print(f"{len(fields)} fields")

            except Exception as exc:
                print(f"ERROR: {exc}")
                results[table_name] = {"error": str(exc), "fields": []}

        # Write output
        output_path = Path(__file__).resolve().parent.parent / "data" / "artifact_dictionary_reference.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, sort_keys=False)

        print(f"\nDone. Output written to: {output_path}")

        # Also print a summary of interesting fields per table
        print("\n" + "=" * 80)
        print("SUMMARY: Key fields per artifact type")
        print("=" * 80)

        # Highlight script/code fields and boolean/choice fields
        for table_name, data in results.items():
            if data.get("error"):
                continue
            script_fields = [
                f for f in data["fields"]
                if f["type"] in ("script", "script_plain", "script_server", "xml", "html", "css")
                or "script" in f["element"].lower()
            ]
            bool_fields = [f for f in data["fields"] if f["type"] == "boolean"]
            choice_fields = [f for f in data["fields"] if f.get("choice") and f["choice"] != "0"]

            print(f"\n--- {table_name} ({data['field_count']} fields) ---")
            if script_fields:
                print(f"  Code fields: {', '.join(f['element'] for f in script_fields)}")
            if bool_fields:
                print(f"  Booleans:    {', '.join(f['element'] for f in bool_fields)}")
            if choice_fields:
                print(f"  Choices:     {', '.join(f['element'] + '(' + f['label'] + ')' for f in choice_fields)}")


if __name__ == "__main__":
    main()
