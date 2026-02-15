# seed_data.py - Seed data for lookup tables
# Run this after database initialization to populate reference data

import json
from sqlmodel import Session
from .database import engine
from .models import GlobalApp, AppFileClass, NumberSequence
from .app_file_class_catalog import app_file_class_seed_rows


def seed_global_apps(session: Session):
    """Seed the GlobalApp table with known ITSM applications"""

    apps = [
        {
            "name": "incident",
            "label": "Incident Management",
            "description": "IT Incident Management application",
            "core_tables_json": json.dumps(["incident"]),
            "parent_table": "task",
            "plugins_json": json.dumps(["com.snc.incident.mgt"]),
            "keywords_json": json.dumps(["incident", "inc"]),
            "display_order": 10,
        },
        {
            "name": "change",
            "label": "Change Management",
            "description": "IT Change Management application",
            "core_tables_json": json.dumps(["change_request", "change_task"]),
            "parent_table": "task",
            "plugins_json": json.dumps(["com.snc.change.mgt"]),
            "keywords_json": json.dumps(["change", "chg"]),
            "display_order": 20,
        },
        {
            "name": "problem",
            "label": "Problem Management",
            "description": "IT Problem Management application",
            "core_tables_json": json.dumps(["problem", "problem_task"]),
            "parent_table": "task",
            "plugins_json": json.dumps(["com.snc.problem.mgt"]),
            "keywords_json": json.dumps(["problem", "prb"]),
            "display_order": 30,
        },
        {
            "name": "request",
            "label": "Service Request / Catalog",
            "description": "Service Request and Catalog applications",
            "core_tables_json": json.dumps(["sc_request", "sc_req_item", "sc_task", "sc_cat_item"]),
            "parent_table": "task",
            "plugins_json": json.dumps(["com.snc.service_catalog"]),
            "keywords_json": json.dumps(["request", "catalog", "ritm", "req"]),
            "display_order": 40,
        },
        {
            "name": "knowledge",
            "label": "Knowledge Management",
            "description": "Knowledge Base application",
            "core_tables_json": json.dumps(["kb_knowledge", "kb_category"]),
            "parent_table": None,
            "plugins_json": json.dumps(["com.snc.knowledge"]),
            "keywords_json": json.dumps(["knowledge", "kb"]),
            "display_order": 50,
        },
        {
            "name": "cmdb",
            "label": "CMDB / Configuration Management",
            "description": "Configuration Management Database",
            "core_tables_json": json.dumps(["cmdb_ci", "cmdb_rel_ci"]),
            "parent_table": None,
            "plugins_json": json.dumps(["com.snc.cmdb"]),
            "keywords_json": json.dumps(["cmdb", "ci", "configuration"]),
            "display_order": 60,
        },
        {
            "name": "asset",
            "label": "Asset Management",
            "description": "IT Asset Management application",
            "core_tables_json": json.dumps(["alm_asset", "alm_hardware", "alm_consumable"]),
            "parent_table": None,
            "plugins_json": json.dumps(["com.snc.asset_management"]),
            "keywords_json": json.dumps(["asset", "alm"]),
            "display_order": 70,
        },
        {
            "name": "sla",
            "label": "SLA Management",
            "description": "Service Level Agreement management",
            "core_tables_json": json.dumps(["contract_sla", "task_sla"]),
            "parent_table": None,
            "plugins_json": json.dumps(["com.snc.sla"]),
            "keywords_json": json.dumps(["sla", "service level"]),
            "display_order": 80,
        },
        {
            "name": "service_portal",
            "label": "Service Portal",
            "description": "Service Portal customizations",
            "core_tables_json": json.dumps(["sp_portal", "sp_page", "sp_widget"]),
            "parent_table": None,
            "plugins_json": json.dumps(["com.glide.service-portal.core"]),
            "keywords_json": json.dumps(["portal", "widget", "sp_"]),
            "display_order": 90,
        },
        {
            "name": "hr_case",
            "label": "HR Case Management",
            "description": "HR Service Delivery - Case Management",
            "core_tables_json": json.dumps(["sn_hr_core_case", "sn_hr_core_task"]),
            "parent_table": "task",
            "plugins_json": json.dumps(["com.sn_hr_core"]),
            "keywords_json": json.dumps(["hr", "hr_case"]),
            "display_order": 100,
        },
        {
            "name": "csm_case",
            "label": "Customer Service Management",
            "description": "Customer Service Management cases",
            "core_tables_json": json.dumps(["sn_customerservice_case"]),
            "parent_table": "task",
            "plugins_json": json.dumps(["com.sn_csm"]),
            "keywords_json": json.dumps(["csm", "customer"]),
            "display_order": 110,
        },
    ]

    for app_data in apps:
        # Check if already exists
        existing = session.query(GlobalApp).filter(GlobalApp.name == app_data["name"]).first()
        if not existing:
            app = GlobalApp(**app_data)
            session.add(app)

    session.commit()
    print(f"Seeded {len(apps)} global apps")


def seed_app_file_classes(session: Session):
    """Seed the AppFileClass table with known application file types"""
    classes = app_file_class_seed_rows()

    for class_data in classes:
        existing = session.query(AppFileClass).filter(
            AppFileClass.sys_class_name == class_data["sys_class_name"]
        ).first()
        if not existing:
            file_class = AppFileClass(**class_data)
            session.add(file_class)

    session.commit()
    print(f"Seeded {len(classes)} app file classes")


def seed_number_sequences(session: Session):
    """Initialize number sequences"""

    sequences = [
        {"prefix": "ASMT", "current_value": 0, "padding": 7},  # ASMT0000001
    ]

    for seq_data in sequences:
        existing = session.query(NumberSequence).filter(
            NumberSequence.prefix == seq_data["prefix"]
        ).first()
        if not existing:
            seq = NumberSequence(**seq_data)
            session.add(seq)

    session.commit()
    print(f"Seeded {len(sequences)} number sequences")


def run_seed():
    """Run all seed operations"""
    with Session(engine) as session:
        print("Seeding database...")
        seed_global_apps(session)
        seed_app_file_classes(session)
        seed_number_sequences(session)
        print("Seed complete!")


if __name__ == "__main__":
    run_seed()
