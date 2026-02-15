from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple


# Central source-of-truth for app file class metadata and default assessment behavior.
APP_FILE_CLASS_CATALOG: List[Dict[str, Any]] = [
    {
        "sys_class_name": "sys_script",
        "label": "Business Rule",
        "description": "Server-side business logic triggered on table operations",
        "target_table_field": "collection",
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 10,
    },
    {
        "sys_class_name": "sys_script_include",
        "label": "Script Include",
        "description": "Reusable server-side JavaScript classes and functions",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 20,
    },
    {
        "sys_class_name": "sys_script_client",
        "label": "Client Script",
        "description": "Client-side JavaScript for form interactions",
        "target_table_field": "table",
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 30,
    },
    {
        "sys_class_name": "sys_ui_policy",
        "label": "UI Policy",
        "description": "Dynamic form behavior rules",
        "target_table_field": "table",
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 40,
    },
    {
        "sys_class_name": "sys_ui_policy_action",
        "label": "UI Policy Action",
        "description": "Actions within UI policies",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 41,
    },
    {
        "sys_class_name": "sys_ui_action",
        "label": "UI Action",
        "description": "Buttons, links, and context menu items",
        "target_table_field": "table",
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 50,
    },
    {
        "sys_class_name": "sys_ui_page",
        "label": "UI Page",
        "description": "Custom Jelly/HTML pages",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 60,
    },
    {
        "sys_class_name": "sys_ui_macro",
        "label": "UI Macro",
        "description": "Reusable Jelly components",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": False,
        "display_order": 61,
    },
    {
        "sys_class_name": "sys_dictionary",
        "label": "Dictionary Entry",
        "description": "Table and column definitions",
        "target_table_field": "name",
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 70,
    },
    {
        "sys_class_name": "sys_dictionary_override",
        "label": "Dictionary Override",
        "description": "Overrides to inherited dictionary attributes",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 71,
    },
    {
        "sys_class_name": "sys_choice",
        "label": "Choice List",
        "description": "Dropdown choice values",
        "target_table_field": "name",
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 75,
    },
    {
        "sys_class_name": "sys_db_object",
        "label": "Table",
        "description": "Table definitions",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 80,
    },
    {
        "sys_class_name": "sys_data_policy2",
        "label": "Data Policy",
        "description": "Server-side data validation rules",
        "target_table_field": "table",
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 90,
    },
    {
        "sys_class_name": "sys_security_acl",
        "label": "Access Control (ACL)",
        "description": "Security access control rules",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 100,
    },
    {
        "sys_class_name": "sysauto_script",
        "label": "Scheduled Job",
        "description": "Scheduled script execution",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 110,
    },
    {
        "sys_class_name": "sysevent_email_action",
        "label": "Email Notification",
        "description": "Email notifications and templates",
        "target_table_field": "sysevent_email_action",
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 120,
    },
    {
        "sys_class_name": "sysevent_script_action",
        "label": "Event Script",
        "description": "Script actions triggered by events",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 125,
    },
    {
        "sys_class_name": "sys_hub_flow",
        "label": "Flow",
        "description": "Flow Designer flows",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 130,
    },
    {
        "sys_class_name": "wf_workflow",
        "label": "Workflow",
        "description": "Legacy workflow definitions",
        "target_table_field": "table",
        "has_script": False,
        "default_assessment_enabled": True,
        "display_order": 140,
    },
    {
        "sys_class_name": "sp_widget",
        "label": "Service Portal Widget",
        "description": "Portal widget components",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 150,
    },
    {
        "sys_class_name": "sp_page",
        "label": "Service Portal Page",
        "description": "Portal page definitions",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": False,
        "display_order": 151,
    },
    {
        "sys_class_name": "sys_transform_map",
        "label": "Transform Map",
        "description": "Data import transform mappings",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": False,
        "display_order": 160,
    },
    {
        "sys_class_name": "sys_web_service",
        "label": "Scripted REST API",
        "description": "Custom REST API endpoints",
        "target_table_field": None,
        "has_script": True,
        "default_assessment_enabled": True,
        "display_order": 170,
    },
    {
        "sys_class_name": "sys_ui_form",
        "label": "Form Layout",
        "description": "Form layout definitions",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": False,
        "display_order": 180,
    },
    {
        "sys_class_name": "sys_ui_list",
        "label": "List Layout",
        "description": "List view layout definitions",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": False,
        "display_order": 181,
    },
    {
        "sys_class_name": "sys_ui_related_list",
        "label": "Related List",
        "description": "Related list configurations",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": False,
        "display_order": 182,
    },
    {
        "sys_class_name": "sys_report",
        "label": "Report",
        "description": "Report definitions",
        "target_table_field": "table",
        "has_script": False,
        "default_assessment_enabled": False,
        "display_order": 190,
    },
    {
        "sys_class_name": "sys_update_set",
        "label": "Update Set",
        "description": "Update set containers",
        "target_table_field": None,
        "has_script": False,
        "default_assessment_enabled": False,
        "display_order": 200,
    },
]

# Global display-name exclusions across all instances.
DEFAULT_ASSESSMENT_DISABLED_DISPLAY_NAME_SUBSTRINGS: Tuple[str, ...] = ("kmf",)

DEFAULT_ASSESSMENT_ENABLED_SYS_CLASS_NAMES: Set[str] = {
    str(row["sys_class_name"])
    for row in APP_FILE_CLASS_CATALOG
    if bool(row.get("default_assessment_enabled"))
}


def app_file_class_seed_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in APP_FILE_CLASS_CATALOG:
        item = dict(row)
        item["is_important"] = bool(item.pop("default_assessment_enabled", False))
        rows.append(item)
    return rows


def default_assessment_option_availability_for_instance_file_type(
    sys_class_name: Optional[str],
    label: Optional[str],
    name: Optional[str],
) -> bool:
    display_name = (label or name or "").strip().lower()
    if any(pattern in display_name for pattern in DEFAULT_ASSESSMENT_DISABLED_DISPLAY_NAME_SUBSTRINGS):
        return False

    normalized_class_name = (sys_class_name or "").strip()
    if not normalized_class_name:
        return False

    return True


def default_assessment_availability_for_instance_file_type(
    sys_class_name: Optional[str],
    label: Optional[str],
    name: Optional[str],
) -> bool:
    if not default_assessment_option_availability_for_instance_file_type(
        sys_class_name=sys_class_name,
        label=label,
        name=name,
    ):
        return False

    normalized_class_name = (sys_class_name or "").strip()
    return normalized_class_name in DEFAULT_ASSESSMENT_ENABLED_SYS_CLASS_NAMES
