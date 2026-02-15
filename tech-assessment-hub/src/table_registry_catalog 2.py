"""Unified Table Registry Catalog.

Merges CSDM tables (from csdm_table_catalog) with Preflight tables into
a single catalog.  Provides helpers to determine the source of any table
and to enumerate all tables relevant to an instance (defaults + custom).
"""

from typing import Dict, List, Optional

from sqlmodel import Session, select

from .csdm_table_catalog import get_all_table_names as get_csdm_table_names
from .models_sn import SnCustomTableRequest


# ============================================
# PREFLIGHT TABLE MAP
# Maps local data-pull type names to SN table API names.
# ============================================

PREFLIGHT_SN_TABLE_MAP: Dict[str, str] = {
    "update_sets": "sys_update_set",
    "customer_update_xml": "sys_update_xml",
    "version_history": "sys_update_version",
    "metadata_customization": "sys_metadata_customization",
    "app_file_types": "sys_app_file_type",
    "plugins": "sys_plugins",
    "scopes": "sys_scope",
    "packages": "sys_package",
    "applications": "sys_app",
    "sys_db_object": "sys_db_object",
}


def _get_preflight_sn_tables() -> List[str]:
    """Return the flat list of SN table names used by preflight pulls."""
    return list(PREFLIGHT_SN_TABLE_MAP.values())


def get_all_default_sn_tables() -> List[str]:
    """Return combined list of all default SN table names (CSDM + Preflight).

    Duplicates are removed, order is CSDM first then preflight additions.
    """
    csdm = get_csdm_table_names()
    preflight = _get_preflight_sn_tables()
    seen = set(csdm)
    combined = list(csdm)
    for t in preflight:
        if t not in seen:
            combined.append(t)
            seen.add(t)
    return combined


def get_table_source(sn_table_name: str) -> str:
    """Determine the source category for a given SN table name.

    Returns:
        "csdm" if the table is in the CSDM catalog,
        "preflight" if it is in the preflight map,
        "custom" otherwise.
    """
    if sn_table_name in get_csdm_table_names():
        return "csdm"
    if sn_table_name in _get_preflight_sn_tables():
        return "preflight"
    return "custom"


def get_all_tables_for_instance(
    session: Session, instance_id: int,
) -> List[str]:
    """Return the full list of SN tables relevant to an instance.

    Combines default tables (CSDM + Preflight) with any custom tables
    that have been requested and validated for this instance.
    """
    tables = get_all_default_sn_tables()
    seen = set(tables)

    # Add validated custom tables for this instance.
    custom_requests = session.exec(
        select(SnCustomTableRequest)
        .where(SnCustomTableRequest.instance_id == instance_id)
        .where(SnCustomTableRequest.status.in_(["validated", "schema_created", "active"]))
    ).all()

    for req in custom_requests:
        if req.sn_table_name not in seen:
            tables.append(req.sn_table_name)
            seen.add(req.sn_table_name)

    return tables
