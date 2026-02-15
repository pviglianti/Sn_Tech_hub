# csdm_ddl.py - Dynamic DDL Engine for CSDM Mirror Tables
#
# Creates, alters, and manages SQLite tables at runtime based on
# ServiceNow dictionary metadata. Each mirror table stores a local
# copy of SN table data for CSDM analysis.
#
# All tables share a standard envelope:
#   _row_id, _instance_id, sys_id, ..., _ingested_at, _updated_at, _raw_json
# with a UNIQUE constraint on (_instance_id, sys_id).

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ============================================
# ServiceNow type → SQLite column type mapping
# ============================================

SN_TYPE_MAP: dict[str, str] = {
    # Text types
    "string": "TEXT",
    "translated_text": "TEXT",
    "html": "TEXT",
    "script": "TEXT",
    "script_plain": "TEXT",
    "url": "TEXT",
    "email": "TEXT",
    "phone_number_e164": "TEXT",
    "sys_class_name": "TEXT",
    "journal": "TEXT",
    "journal_input": "TEXT",
    "conditions": "TEXT",
    "documentation_field": "TEXT",
    "translated_html": "TEXT",
    "xml": "TEXT",
    "json_translations": "TEXT",
    "composite_name": "TEXT",
    "wiki_text": "TEXT",
    "choice": "TEXT",
    "multi_two_lines": "TEXT",
    "GUID": "TEXT",
    "reference": "TEXT",
    "document_id": "TEXT",
    # Integer types
    "integer": "INTEGER",
    "count": "INTEGER",
    "order_index": "INTEGER",
    "table_name": "INTEGER",
    "boolean": "INTEGER",
    # Real types
    "float": "REAL",
    "decimal": "REAL",
    "currency": "REAL",
    "price": "REAL",
    # Date/time types (stored as TEXT in SQLite)
    "glide_date_time": "TEXT",
    "due_date": "TEXT",
    "glide_date": "TEXT",
    "glide_time": "TEXT",
    "calendar_date_time": "TEXT",
}


def sn_type_to_sqlite(sn_type: str) -> str:
    """Map a ServiceNow internal field type to its SQLite column type.

    Returns 'TEXT' for any unrecognised type (safe default for SQLite).
    """
    return SN_TYPE_MAP.get(sn_type, "TEXT")


# ============================================
# Identifier validation
# ============================================

def _validate_identifier(name: str) -> str:
    """Validate and return a safe SQL identifier.

    Only allows alphanumeric characters and underscores.
    Raises ValueError for anything else to prevent SQL injection.
    """
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


# ============================================
# Table creation
# ============================================

def create_mirror_table(
    engine: Engine,
    local_table_name: str,
    field_mappings: list[dict],
) -> None:
    """Create a new SN mirror table with dynamic columns.

    Every mirror table gets a standard envelope of columns plus
    dynamic columns derived from the ServiceNow dictionary.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Name for the local table (e.g. 'sn_cmdb_ci_service').
        field_mappings: List of dicts with keys:
            - local_column: str
            - db_column_type: str (e.g. 'TEXT', 'INTEGER')
            - is_reference: bool (optional, for auto-indexing)
    """
    table = _validate_identifier(local_table_name)

    # Build dynamic column definitions
    dynamic_cols: list[str] = []
    index_cols: list[str] = []

    for fm in field_mappings:
        col = _validate_identifier(fm["local_column"])
        col_type = fm.get("db_column_type", "TEXT")
        # Whitelist column types
        if col_type not in ("TEXT", "INTEGER", "REAL", "BLOB"):
            col_type = "TEXT"
        dynamic_cols.append(f'    "{col}" {col_type}')
        if fm.get("is_reference"):
            index_cols.append(col)

    dynamic_block = ",\n".join(dynamic_cols)
    if dynamic_block:
        dynamic_block = ",\n" + dynamic_block

    ddl = f"""
    CREATE TABLE IF NOT EXISTS "{table}" (
        _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
        _instance_id INTEGER NOT NULL,
        sys_id TEXT NOT NULL{dynamic_block},
        _ingested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        _updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        _raw_json TEXT,
        UNIQUE(_instance_id, sys_id)
    )
    """

    with engine.begin() as conn:
        conn.execute(text(ddl))

        # Standard indexes
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS "ix_{table}__instance_id" ON "{table}" (_instance_id)'
        ))
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS "ix_{table}__sys_id" ON "{table}" (sys_id)'
        ))
        # Index on sys_updated_on if present (common delta cursor field)
        has_sys_updated_on = any(
            fm["local_column"] == "sys_updated_on" for fm in field_mappings
        )
        if has_sys_updated_on:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "ix_{table}__sys_updated_on" '
                f'ON "{table}" (sys_updated_on)'
            ))

        # Index reference columns
        for col in index_cols:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "ix_{table}_{col}" ON "{table}" ("{col}")'
            ))

    logger.info("Created mirror table %s with %d columns", table, len(field_mappings))


# ============================================
# Table alteration
# ============================================

def alter_mirror_table(
    engine: Engine,
    local_table_name: str,
    new_columns: list[dict],
) -> list[str]:
    """Add new columns to an existing mirror table.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Existing table name.
        new_columns: List of dicts with keys:
            - local_column: str
            - db_column_type: str

    Returns:
        List of column names that were added.
    """
    table = _validate_identifier(local_table_name)
    added: list[str] = []

    with engine.begin() as conn:
        # Get existing columns
        result = conn.execute(text(f'PRAGMA table_info("{table}")'))
        existing = {row[1] for row in result.fetchall()}

        for col_def in new_columns:
            col = _validate_identifier(col_def["local_column"])
            if col in existing:
                continue
            col_type = col_def.get("db_column_type", "TEXT")
            if col_type not in ("TEXT", "INTEGER", "REAL", "BLOB"):
                col_type = "TEXT"
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {col_type}'))
            added.append(col)

    if added:
        logger.info("Added %d columns to %s: %s", len(added), table, added)
    return added


# ============================================
# Data operations
# ============================================

def drop_mirror_table_data(
    engine: Engine,
    local_table_name: str,
    instance_id: int,
) -> int:
    """Delete all rows for a specific instance from a mirror table.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Table to clear.
        instance_id: Instance whose rows should be deleted.

    Returns:
        Number of rows deleted.
    """
    table = _validate_identifier(local_table_name)

    with engine.begin() as conn:
        result = conn.execute(
            text(f'DELETE FROM "{table}" WHERE _instance_id = :iid'),
            {"iid": instance_id},
        )
        count = result.rowcount
    logger.info("Deleted %d rows from %s for instance %d", count, table, instance_id)
    return count


def drop_mirror_table(engine: Engine, local_table_name: str) -> None:
    """Drop an entire mirror table.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Table to drop.
    """
    table = _validate_identifier(local_table_name)
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
    logger.info("Dropped mirror table %s", table)


def get_mirror_table_row_count(
    engine: Engine,
    local_table_name: str,
    instance_id: int,
) -> int:
    """Count rows for a specific instance in a mirror table.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Table to count.
        instance_id: Instance to filter by.

    Returns:
        Number of rows.
    """
    table = _validate_identifier(local_table_name)
    with engine.connect() as conn:
        result = conn.execute(
            text(f'SELECT COUNT(*) FROM "{table}" WHERE _instance_id = :iid'),
            {"iid": instance_id},
        )
        return result.scalar() or 0


def table_exists(engine: Engine, local_table_name: str) -> bool:
    """Check whether a table exists in the database.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Table name to check.

    Returns:
        True if the table exists.
    """
    table = _validate_identifier(local_table_name)
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name = :tbl"
            ),
            {"tbl": table},
        )
        return (result.scalar() or 0) > 0


# ============================================
# Upsert (INSERT ... ON CONFLICT ... DO UPDATE)
# ============================================

def _coerce_value(value: Any, db_type: str) -> Any:
    """Coerce a raw SN API value to the appropriate Python type for SQLite.

    Handles None, empty strings, and basic type conversion.
    """
    if value is None or value == "":
        return None

    if db_type == "INTEGER":
        if isinstance(value, bool):
            return 1 if value else 0
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    if db_type == "REAL":
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    # TEXT / everything else — just stringify
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def upsert_batch(
    engine: Engine,
    local_table_name: str,
    instance_id: int,
    records: list[dict],
    field_mappings: list[dict],
) -> tuple[int, int]:
    """Upsert a batch of ServiceNow records into a mirror table.

    Uses INSERT ... ON CONFLICT(_instance_id, sys_id) DO UPDATE SET ...
    to perform an atomic upsert per row.

    Args:
        engine: SQLAlchemy engine.
        local_table_name: Target table.
        instance_id: Instance ID to stamp on every row.
        records: List of dicts from the SN API (keyed by sn_element).
        field_mappings: List of dicts with keys:
            - sn_element: str (key in the SN record)
            - local_column: str (column in local table)
            - db_column_type: str

    Returns:
        Tuple of (inserted_count, updated_count).
    """
    if not records:
        return 0, 0

    table = _validate_identifier(local_table_name)

    # Build column lists
    # Always include the envelope columns: _instance_id, sys_id, _raw_json, _updated_at
    envelope_cols = ["_instance_id", "sys_id", "_raw_json", "_updated_at"]
    dynamic_cols: list[str] = []
    sn_to_local: list[tuple[str, str, str]] = []  # (sn_element, local_column, db_type)

    for fm in field_mappings:
        local_col = _validate_identifier(fm["local_column"])
        # Skip envelope columns that we handle separately
        if local_col in ("sys_id", "_instance_id", "_raw_json", "_updated_at", "_ingested_at", "_row_id"):
            continue
        dynamic_cols.append(local_col)
        sn_to_local.append((fm["sn_element"], local_col, fm.get("db_column_type", "TEXT")))

    all_cols = envelope_cols + dynamic_cols
    placeholders = ", ".join(f":{c}" for c in all_cols)
    col_list = ", ".join(f'"{c}"' for c in all_cols)

    # ON CONFLICT update: update all dynamic columns + _updated_at + _raw_json
    update_cols = dynamic_cols + ["_raw_json", "_updated_at"]
    update_set = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)

    sql = (
        f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) '
        f"ON CONFLICT(_instance_id, sys_id) DO UPDATE SET {update_set}"
    )

    now = datetime.utcnow().isoformat()
    inserted = 0
    updated = 0

    with engine.begin() as conn:
        # Pre-fetch existing sys_ids for this instance to distinguish insert vs update
        existing_result = conn.execute(
            text(f'SELECT sys_id FROM "{table}" WHERE _instance_id = :iid'),
            {"iid": instance_id},
        )
        existing_sys_ids = {row[0] for row in existing_result.fetchall()}

        for record in records:
            # Extract sys_id from the record
            sys_id = record.get("sys_id")
            if not sys_id:
                # Try nested value format from SN API
                sys_id_obj = record.get("sys_id", {})
                if isinstance(sys_id_obj, dict):
                    sys_id = sys_id_obj.get("value") or sys_id_obj.get("display_value")
            if not sys_id:
                logger.warning("Skipping record without sys_id in table %s", table)
                continue

            # Build parameter dict
            params: dict[str, Any] = {
                "_instance_id": instance_id,
                "sys_id": str(sys_id),
                "_raw_json": json.dumps(record),
                "_updated_at": now,
            }

            for sn_element, local_col, db_type in sn_to_local:
                raw = record.get(sn_element)
                # Handle SN display/value pairs
                if isinstance(raw, dict):
                    raw = raw.get("value", raw.get("display_value"))
                params[local_col] = _coerce_value(raw, db_type)

            conn.execute(text(sql), params)

            if sys_id in existing_sys_ids:
                updated += 1
            else:
                inserted += 1
                existing_sys_ids.add(sys_id)

    logger.info(
        "Upserted %d records into %s (instance %d): %d inserted, %d updated",
        len(records), table, instance_id, inserted, updated,
    )
    return inserted, updated
