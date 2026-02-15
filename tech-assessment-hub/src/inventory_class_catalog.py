from __future__ import annotations

from typing import Dict


# Central mapping of inventory class keys -> ServiceNow table names.
INVENTORY_CLASS_TABLES: Dict[str, str] = {
    "script_includes": "sys_script_include",
    "business_rules": "sys_script",
    "client_scripts": "sys_script_client",
    "ui_policies": "sys_ui_policy",
    "ui_actions": "sys_ui_action",
    "ui_pages": "sys_ui_page",
    "scheduled_jobs": "sysauto_script",
}

INVENTORY_CLASS_TABLES_WITH_UPDATE_SETS: Dict[str, str] = {
    **INVENTORY_CLASS_TABLES,
    "update_sets": "sys_update_set",
}


def inventory_class_tables(*, include_update_sets: bool = False) -> Dict[str, str]:
    if include_update_sets:
        return dict(INVENTORY_CLASS_TABLES_WITH_UPDATE_SETS)
    return dict(INVENTORY_CLASS_TABLES)
