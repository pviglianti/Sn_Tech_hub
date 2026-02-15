"""ServiceNow Dictionary Extraction Service.

Pulls table metadata (fields, types, references) from sys_dictionary
and inheritance info from sys_db_object.  Used to dynamically create
local DB tables that mirror ServiceNow tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from .sn_client import ServiceNowClient, ServiceNowClientError

logger = logging.getLogger(__name__)

# Well-known root tables where we stop the inheritance walk.
# These are either actual roots (no super_class) or tables so far
# up the chain that continuing adds no useful fields.
INHERITANCE_STOP_TABLES = frozenset({
    "sys_metadata",
    "sys_metadata_delete",
})


# ============================================
# DATA CLASSES
# ============================================

@dataclass
class SNFieldInfo:
    """Represents a single field from sys_dictionary."""

    element: str = ""
    column_label: str = ""
    internal_type: str = ""
    max_length: int = 0
    reference_table: str = ""
    is_reference: bool = False
    is_active: bool = True
    is_mandatory: bool = False
    is_read_only: bool = False
    source_table: str = ""  # Which table in the inheritance chain owns this field


@dataclass
class SNTableInfo:
    """Represents table metadata from sys_db_object."""

    name: str = ""
    label: str = ""
    sys_id: str = ""
    super_class_sys_id: str = ""
    super_class_name: str = ""
    is_extendable: bool = False
    extension_model: str = ""


# ============================================
# TABLE VALIDATION
# ============================================

def validate_table_exists(client: ServiceNowClient, table_name: str) -> Optional[SNTableInfo]:
    """Check if a table exists on the SN instance.

    Returns:
        SNTableInfo if the table exists, None otherwise.
    """
    url = client._build_url("table/sys_db_object")
    params = {
        "sysparm_query": f"name={table_name}",
        "sysparm_limit": 1,
        "sysparm_fields": "sys_id,name,label,super_class,is_extendable,extension_model",
        "sysparm_display_value": "false",
    }

    try:
        response = client.session.get(url, params=params, timeout=client._cfg['request_timeout'])
        data = client._handle_response(response)
    except ServiceNowClientError:
        logger.warning("Failed to validate table %s", table_name)
        return None

    results = data.get("result", [])
    if not results:
        return None

    rec = results[0]
    super_class_raw = rec.get("super_class", "")
    # super_class is a reference field returned as a sys_id string
    # (display_value=false), or potentially a dict if the API config differs.
    if isinstance(super_class_raw, dict):
        super_class_sys_id = super_class_raw.get("value", "")
    else:
        super_class_sys_id = str(super_class_raw) if super_class_raw else ""

    is_ext = rec.get("is_extendable", "false")
    if isinstance(is_ext, str):
        is_ext = is_ext.lower() in ("true", "1", "yes")

    return SNTableInfo(
        name=rec.get("name", ""),
        label=rec.get("label", ""),
        sys_id=rec.get("sys_id", ""),
        super_class_sys_id=super_class_sys_id,
        super_class_name="",  # Resolved by caller if needed.
        is_extendable=bool(is_ext),
        extension_model=rec.get("extension_model", "") or "",
    )


# ============================================
# TABLE NAME LOOKUP BY SYS_ID
# ============================================

def _resolve_table_name_by_sys_id(client: ServiceNowClient, sys_id: str) -> Optional[str]:
    """Resolve a sys_db_object sys_id to a table name."""
    if not sys_id:
        return None

    url = client._build_url(f"table/sys_db_object/{sys_id}")
    params = {
        "sysparm_fields": "name",
    }
    try:
        response = client.session.get(url, params=params, timeout=client._cfg['request_timeout'])
        if response.status_code == 404:
            return None
        data = client._handle_response(response)
        result = data.get("result")
        if result:
            return result.get("name") or None
    except ServiceNowClientError:
        return None
    return None


# ============================================
# INHERITANCE CHAIN
# ============================================

def get_table_inheritance_chain(client: ServiceNowClient, table_name: str) -> List[str]:
    """Walk super_class references to build the inheritance chain.

    Returns:
        List starting with the given table and walking up to the root,
        e.g. ``['cmdb_ci_service_business', 'cmdb_ci_service', 'cmdb_ci', 'cmdb']``.
        Stop at root (no super_class) or at well-known stop tables.
    """
    chain: List[str] = []
    visited: set[str] = set()
    current_name = table_name

    while current_name:
        if current_name in visited:
            logger.warning("Cycle detected in inheritance chain at %s", current_name)
            break
        if current_name in INHERITANCE_STOP_TABLES:
            break

        visited.add(current_name)
        chain.append(current_name)

        # Look up the table to find its super_class sys_id.
        info = validate_table_exists(client, current_name)
        if not info or not info.super_class_sys_id:
            break

        # Resolve the sys_id to a table name.
        parent_name = _resolve_table_name_by_sys_id(client, info.super_class_sys_id)
        if not parent_name:
            break
        current_name = parent_name

    return chain


# ============================================
# FIELD EXTRACTION
# ============================================

def _fetch_fields_for_table(
    client: ServiceNowClient,
    table_name: str,
    since: Optional[datetime] = None,
) -> List[SNFieldInfo]:
    """Fetch fields for a single table (no inheritance) from sys_dictionary.

    Filters out the special collection record where element is empty.
    Includes sys_ fields.

    Args:
        client: ServiceNow client
        table_name: Table name to query
        since: Optional datetime watermark for delta queries (sys_updated_on > since)
    """
    from datetime import datetime as dt_class

    url = client._build_url("table/sys_dictionary")

    # Build query with optional delta filter
    query_parts = [f"name={table_name}", "active=true"]
    if since:
        # Format datetime for ServiceNow query (UTC, ServiceNow format)
        since_str = since.strftime("%Y-%m-%d %H:%M:%S")
        query_parts.append(f"sys_updated_on>{since_str}")

    params = {
        "sysparm_query": "^".join(query_parts),
        "sysparm_fields": "element,column_label,internal_type,max_length,reference,active,read_only,mandatory",
        "sysparm_limit": 500,
        "sysparm_display_value": "false",
    }

    try:
        response = client.session.get(url, params=params, timeout=client._cfg['request_timeout'])
        data = client._handle_response(response)
    except ServiceNowClientError as exc:
        logger.error("Failed to fetch dictionary for %s: %s", table_name, exc)
        return []

    fields: List[SNFieldInfo] = []
    for rec in data.get("result", []):
        element = rec.get("element", "") or ""

        # Filter out the collection record (element is empty).
        if not element.strip():
            continue

        ref_table = rec.get("reference", "") or ""
        # reference field is a string containing the target table name,
        # or it can be a dict if display_value was returned.
        if isinstance(ref_table, dict):
            ref_table = ref_table.get("value", "") or ref_table.get("display_value", "") or ""

        is_active = rec.get("active", "true")
        if isinstance(is_active, str):
            is_active = is_active.lower() in ("true", "1", "yes")

        is_mandatory = rec.get("mandatory", "false")
        if isinstance(is_mandatory, str):
            is_mandatory = is_mandatory.lower() in ("true", "1", "yes")

        is_read_only = rec.get("read_only", "false")
        if isinstance(is_read_only, str):
            is_read_only = is_read_only.lower() in ("true", "1", "yes")

        max_length = rec.get("max_length", 0)
        try:
            max_length = int(max_length) if max_length else 0
        except (TypeError, ValueError):
            max_length = 0

        internal_type = rec.get("internal_type", "") or ""
        # internal_type can be a reference dict on some instances.
        if isinstance(internal_type, dict):
            internal_type = internal_type.get("value", "") or internal_type.get("display_value", "") or ""

        fields.append(SNFieldInfo(
            element=element,
            column_label=rec.get("column_label", "") or "",
            internal_type=internal_type,
            max_length=max_length,
            reference_table=ref_table,
            is_reference=bool(ref_table),
            is_active=bool(is_active),
            is_mandatory=bool(is_mandatory),
            is_read_only=bool(is_read_only),
            source_table=table_name,
        ))

    return fields


def get_table_fields(
    client: ServiceNowClient,
    table_name: str,
    include_inherited: bool = True,
    since: Optional[datetime] = None,
) -> List[SNFieldInfo]:
    """Get all fields for a table from sys_dictionary.

    If ``include_inherited`` is True, walks the inheritance chain and merges
    fields from parent tables.  Child fields override parent fields
    (i.e., if both parent and child define 'state', the child definition wins).

    Args:
        client: ServiceNow client
        table_name: Table name to query
        include_inherited: Include fields from parent tables
        since: Optional datetime watermark for delta queries

    Returns:
        List of SNFieldInfo, deduplicated by element name (child wins).
    """
    if include_inherited:
        chain = get_table_inheritance_chain(client, table_name)
    else:
        chain = [table_name]

    # Walk the chain bottom-up (child first). Child fields take precedence.
    fields_by_element: Dict[str, SNFieldInfo] = {}

    for tbl in chain:
        tbl_fields = _fetch_fields_for_table(client, tbl, since=since)
        for f in tbl_fields:
            # Only add if not already defined by a child table.
            if f.element not in fields_by_element:
                fields_by_element[f.element] = f

    return list(fields_by_element.values())


# ============================================
# FULL DICTIONARY EXTRACTION
# ============================================

def extract_full_dictionary(
    client: ServiceNowClient,
    table_name: str,
    since: Optional[datetime] = None,
) -> Optional[dict]:
    """Full extraction: validates table, gets inheritance, gets all fields.

    Args:
        client: ServiceNow client
        table_name: Table name to extract dictionary for
        since: Optional datetime watermark for delta queries (sys_updated_on > since)

    Returns:
        Dictionary with keys:
            - ``table_info`` (SNTableInfo)
            - ``inheritance_chain`` (list[str])
            - ``fields`` (list[SNFieldInfo])
            - ``parent_table`` (str or None)

        Returns None if the table does not exist on the instance.
    """
    # Step 1: Validate the table exists.
    table_info = validate_table_exists(client, table_name)
    if not table_info:
        logger.warning("Table %s does not exist on the instance", table_name)
        return None

    # Step 2: Resolve the parent table name from super_class sys_id.
    parent_table: Optional[str] = None
    if table_info.super_class_sys_id:
        parent_table = _resolve_table_name_by_sys_id(client, table_info.super_class_sys_id)
        table_info.super_class_name = parent_table or ""

    # Step 3: Get the full inheritance chain.
    inheritance_chain = get_table_inheritance_chain(client, table_name)

    # Step 4: Get all fields (inherited + own), optionally filtered by watermark.
    fields = get_table_fields(client, table_name, include_inherited=True, since=since)

    logger.info(
        "Dictionary extraction for %s: %d fields, chain=%s",
        table_name,
        len(fields),
        " -> ".join(inheritance_chain),
    )

    return {
        "table_info": table_info,
        "inheritance_chain": inheritance_chain,
        "fields": fields,
        "parent_table": parent_table,
    }
