"""Artifact detail table DDL — bridges artifact_detail_defs → csdm_ddl.

Reuses the dynamic DDL engine (create_mirror_table, alter_mirror_table,
upsert_batch) to manage per-class artifact tables defined in
artifact_detail_defs.py.

Each artifact table follows the same envelope as CSDM mirror tables:
    _row_id, _instance_id, sys_id, <typed columns>, _ingested_at, _updated_at, _raw_json
    UNIQUE(_instance_id, sys_id)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Engine

from ..artifact_detail_defs import (
    ARTIFACT_DETAIL_DEFS,
    COMMON_INHERITED_FIELDS,
)
from .csdm_ddl import (
    create_mirror_table,
    alter_mirror_table,
    table_exists,
    upsert_batch,
)

logger = logging.getLogger(__name__)

# py_type (from detail_defs) → SQLite column type
_PY_TYPE_TO_SQLITE: dict[str, str] = {
    "str": "TEXT",
    "text": "TEXT",
    "bool": "INTEGER",
    "int": "INTEGER",
}


def _build_field_mappings(
    fields: list[tuple[str, str, str]],
    include_common: bool = True,
) -> list[dict[str, Any]]:
    """Convert detail_defs field tuples into csdm_ddl field_mappings format.

    Args:
        fields: List of (sn_element, label, py_type) tuples.
        include_common: Whether to append COMMON_INHERITED_FIELDS.

    Returns:
        List of dicts with keys: sn_element, local_column, db_column_type.
    """
    all_fields = list(fields)
    if include_common:
        all_fields.extend(COMMON_INHERITED_FIELDS)

    mappings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sn_element, _label, py_type in all_fields:
        if sn_element in seen:
            continue
        seen.add(sn_element)
        mappings.append({
            "sn_element": sn_element,
            "local_column": sn_element,
            "db_column_type": _PY_TYPE_TO_SQLITE.get(py_type, "TEXT"),
        })
    return mappings


def ensure_artifact_tables(engine: Engine) -> list[str]:
    """Create or update all artifact detail tables defined in ARTIFACT_DETAIL_DEFS.

    For each class:
      - If the table doesn't exist → create it with all columns.
      - If it exists → add any new columns that are missing.

    Returns:
        List of table names that were created or altered.
    """
    touched: list[str] = []

    for sys_class_name, defn in ARTIFACT_DETAIL_DEFS.items():
        local_table = defn["local_table"]
        field_mappings = _build_field_mappings(defn["fields"])

        if not table_exists(engine, local_table):
            create_mirror_table(engine, local_table, field_mappings)
            touched.append(local_table)
            logger.info(
                "Created artifact table %s for %s (%d columns)",
                local_table, sys_class_name, len(field_mappings),
            )
        else:
            added = alter_mirror_table(engine, local_table, field_mappings)
            if added:
                touched.append(local_table)
                logger.info(
                    "Added %d columns to artifact table %s for %s",
                    len(added), local_table, sys_class_name,
                )

    return touched


def upsert_artifact_records(
    engine: Engine,
    sys_class_name: str,
    instance_id: int,
    records: list[dict],
) -> tuple[int, int]:
    """Upsert SN API records into the artifact detail table for a class.

    Args:
        engine: SQLAlchemy engine.
        sys_class_name: The SN class (e.g. "sys_script").
        instance_id: Instance ID to stamp on every row.
        records: Raw dicts from SN Table API.

    Returns:
        Tuple of (inserted_count, updated_count).

    Raises:
        KeyError: If sys_class_name is not in ARTIFACT_DETAIL_DEFS.
    """
    defn = ARTIFACT_DETAIL_DEFS[sys_class_name]
    local_table = defn["local_table"]
    field_mappings = _build_field_mappings(defn["fields"])

    return upsert_batch(
        engine=engine,
        local_table_name=local_table,
        instance_id=instance_id,
        records=records,
        field_mappings=field_mappings,
    )
