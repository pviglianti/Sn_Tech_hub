"""CSDM Table Catalog -- Known tables and priority groups.

Defines the canonical set of ServiceNow tables used by the CSDM Data
Foundations module, organized into priority groups.  Custom tables
added by users at runtime are handled separately via
SnCustomTableRequest, but they still flow through the
get_local_table_name / get_table_group helpers defined here.
"""

from typing import Dict, List

# ============================================
# TABLE GROUP DEFINITIONS
# ============================================

CSDM_TABLE_GROUPS: Dict[str, dict] = {
    "service": {
        "label": "Service Tables",
        "priority": 1,
        "tables": [
            {"name": "cmdb_ci_service", "label": "CI Service (Base)", "parent": None},
            {"name": "cmdb_ci_service_business", "label": "Business Service", "parent": "cmdb_ci_service"},
            {"name": "cmdb_ci_service_technical", "label": "Technical Service", "parent": "cmdb_ci_service"},
            {"name": "cmdb_ci_service_auto", "label": "Service Instance (CSDM 5)", "parent": "cmdb_ci_service"},
            {"name": "cmdb_ci_service_discovered", "label": "Discovered Service", "parent": "cmdb_ci_service_auto"},
            {"name": "cmdb_ci_service_tags", "label": "Tag-Based Service", "parent": "cmdb_ci_service_auto"},
            {"name": "cmdb_ci_service_calculated", "label": "Calculated Service", "parent": "cmdb_ci_service_auto"},
            {"name": "cmdb_ci_query_based_service", "label": "Query-Based Service", "parent": "cmdb_ci_service_auto"},
            {"name": "service_offering", "label": "Service Offering", "parent": None},
        ],
    },
    "foundation": {
        "label": "Foundation Tables",
        "priority": 2,
        "tables": [
            {"name": "cmn_location", "label": "Location", "parent": None},
            {"name": "cmn_department", "label": "Department", "parent": None},
            {"name": "sys_user", "label": "User", "parent": None},
            {"name": "sys_user_group", "label": "Group", "parent": None},
            {"name": "sys_user_grmember", "label": "Group Membership", "parent": None},
        ],
    },
    "process": {
        "label": "Process Tables",
        "priority": 3,
        "tables": [
            {"name": "incident", "label": "Incident", "parent": "task"},
            {"name": "change_request", "label": "Change Request", "parent": "task"},
            {"name": "wm_task", "label": "Work Management Task", "parent": "task"},
        ],
    },
    "custom": {
        "label": "Custom Tables",
        "priority": 4,
        "tables": [
            {"name": "u_work_order_assignment", "label": "Work Order Assignment (Weis)", "parent": None},
        ],
    },
}


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_all_table_names() -> List[str]:
    """Return flat list of all known table names across all groups."""
    names: List[str] = []
    for group in CSDM_TABLE_GROUPS.values():
        for t in group["tables"]:
            names.append(t["name"])
    return names


def get_table_group(table_name: str) -> str:
    """Return the group key for a table name, or 'custom' if unknown."""
    for group_key, group in CSDM_TABLE_GROUPS.items():
        for t in group["tables"]:
            if t["name"] == table_name:
                return group_key
    return "custom"


def get_local_table_name(sn_table_name: str) -> str:
    """Convert SN table name to local table name with sn_ prefix."""
    return f"sn_{sn_table_name}"


def get_tables_by_group(group_key: str) -> List[dict]:
    """Return table list for a specific group."""
    group = CSDM_TABLE_GROUPS.get(group_key)
    return group["tables"] if group else []


def get_table_label(table_name: str) -> str:
    """Return the display label for a known table, or the table name itself."""
    for group in CSDM_TABLE_GROUPS.values():
        for t in group["tables"]:
            if t["name"] == table_name:
                return t["label"]
    return table_name


def get_tables_by_priority() -> List[dict]:
    """Return all tables ordered by group priority then list order.

    Each returned dict includes the group_key alongside the table info.
    """
    result: List[dict] = []
    sorted_groups = sorted(CSDM_TABLE_GROUPS.items(), key=lambda g: g[1]["priority"])
    for group_key, group in sorted_groups:
        for t in group["tables"]:
            result.append({**t, "group_key": group_key})
    return result
