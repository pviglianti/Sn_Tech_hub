"""Dynamic Table Browser -- API Routes.

Provides a universal browsing system for ANY ServiceNow table registered
in SnTableRegistry (CSDM, Preflight, Custom).  Endpoints expose field
metadata from SnFieldMapping and query mirror tables via raw SQL.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlmodel import Session, select

from ...database import engine, get_session
from ...models import Instance
from ...models_sn import SnFieldMapping, SnTableRegistry
from ...services.condition_query_builder import conditions_to_sql_where

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
dynamic_browser_router = APIRouter(tags=["dynamic-browser"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Envelope columns that exist on every mirror table (csdm_ddl.py convention)
_ENVELOPE_COLUMNS = {"_row_id", "_instance_id", "sys_id", "_ingested_at", "_updated_at", "_raw_json"}

# Columns to always show first when no preference is set
_PRIORITY_COLUMNS = ["sys_id", "name", "number", "short_description", "state", "sys_updated_on"]


def _sn_type_to_kind(sn_internal_type: Optional[str]) -> str:
    """Map a ServiceNow internal_type to a UI kind for the frontend."""
    if not sn_internal_type:
        return "string"
    t = sn_internal_type.lower()
    if t in ("integer", "count", "order_index", "longint"):
        return "number"
    if t in ("float", "decimal", "currency", "price"):
        return "number"
    if t in ("boolean",):
        return "boolean"
    if t in ("glide_date_time", "due_date", "glide_date", "glide_time", "calendar_date_time"):
        return "date"
    return "string"


def _safe_identifier(name: str) -> str:
    """Sanitize a column or table name for safe SQL interpolation."""
    clean = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    if not clean:
        raise ValueError(f"Invalid identifier: {name!r}")
    return clean


def _get_registry(session: Session, instance_id: int, sn_table_name: str) -> SnTableRegistry:
    """Look up a SnTableRegistry row or raise 404."""
    registry = session.exec(
        select(SnTableRegistry)
        .where(SnTableRegistry.instance_id == instance_id)
        .where(SnTableRegistry.sn_table_name == sn_table_name)
    ).first()
    if not registry:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{sn_table_name}' not registered for instance {instance_id}. Run dictionary pull first.",
        )
    return registry


def _get_field_mappings(session: Session, registry_id: int) -> List[SnFieldMapping]:
    """Return active field mappings for a registry, ordered by element name."""
    return list(session.exec(
        select(SnFieldMapping)
        .where(SnFieldMapping.registry_id == registry_id)
        .where(SnFieldMapping.is_active == True)  # noqa: E712
        .order_by(SnFieldMapping.sn_element)
    ).all())


def _field_to_schema(fm: SnFieldMapping) -> Dict[str, Any]:
    """Convert a SnFieldMapping row to a frontend-friendly schema dict."""
    return {
        "local_column": fm.local_column,
        "sn_element": fm.sn_element,
        "column_label": fm.column_label or fm.sn_element,
        "sn_internal_type": fm.sn_internal_type,
        "db_column_type": fm.db_column_type,
        "is_reference": fm.is_reference,
        "sn_reference_table": fm.sn_reference_table,
        "is_mandatory": fm.is_mandatory,
        "is_read_only": fm.is_read_only,
        "source_table": fm.source_table,
        "kind": _sn_type_to_kind(fm.sn_internal_type),
    }


def _serialize_value(value: Any) -> Any:
    """Convert a raw DB value to a JSON-serializable representation."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _table_exists(local_table_name: str) -> bool:
    """Check if a mirror table actually exists in the database."""
    safe_name = _safe_identifier(local_table_name)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name = :name"),
            {"name": safe_name},
        ).first()
    return row is not None


# ---------------------------------------------------------------------------
# 1A. Field Schema API
# ---------------------------------------------------------------------------

@dynamic_browser_router.get("/api/dynamic-browser/field-schema")
async def api_field_schema(
    table: str = Query(..., description="ServiceNow table name"),
    instance_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """Return rich field metadata for a registered table.

    Powers the DataTable column headers, column picker, condition builder
    field dropdown, and reference field detection.
    """
    registry = _get_registry(session, instance_id, table)
    mappings = _get_field_mappings(session, registry.id)

    fields = [_field_to_schema(fm) for fm in mappings]

    # Build set of all registered table names for this instance so the
    # frontend knows which reference targets are actually browseable.
    all_registries = session.exec(
        select(SnTableRegistry)
        .where(SnTableRegistry.instance_id == instance_id)
    ).all()
    available_tables = sorted({r.sn_table_name for r in all_registries})

    return {
        "sn_table_name": registry.sn_table_name,
        "local_table_name": registry.local_table_name,
        "sn_table_label": registry.sn_table_label or registry.display_label or registry.sn_table_name,
        "source": registry.source or "unknown",
        "field_count": len(fields),
        "fields": fields,
        "available_tables": available_tables,
    }


# ---------------------------------------------------------------------------
# 1B. Dynamic Records API
# ---------------------------------------------------------------------------

@dynamic_browser_router.get("/api/dynamic-browser/records")
async def api_dynamic_records(
    table: str = Query(..., description="ServiceNow table name"),
    instance_id: int = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort_field: Optional[str] = Query(None),
    sort_dir: str = Query("asc", regex="^(asc|desc)$"),
    conditions: Optional[str] = Query(None, description="JSON condition tree"),
    session: Session = Depends(get_session),
):
    """Query rows from a dynamic mirror table with optional filtering/sorting."""
    registry = _get_registry(session, instance_id, table)
    local_table = _safe_identifier(registry.local_table_name)

    if not _table_exists(registry.local_table_name):
        return {
            "sn_table_name": table,
            "local_table_name": registry.local_table_name,
            "columns": [],
            "rows": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
        }

    mappings = _get_field_mappings(session, registry.id)
    field_map = {fm.local_column: fm for fm in mappings}

    # Build column list: sys_id first, then dynamic columns (skip envelope internals)
    columns = ["sys_id"]
    for fm in mappings:
        if fm.local_column not in _ENVELOPE_COLUMNS and fm.local_column != "sys_id":
            columns.append(fm.local_column)

    col_list = ", ".join(f'"{_safe_identifier(c)}"' for c in columns)

    # Base WHERE
    where_clause = '"_instance_id" = :iid'
    params: Dict[str, Any] = {"iid": instance_id}

    # Apply condition builder filters
    if conditions:
        try:
            parsed = json.loads(conditions)
            if parsed:
                cond_sql, cond_params = conditions_to_sql_where(parsed)
                if cond_sql and cond_sql != "1=1":
                    where_clause += f" AND ({cond_sql})"
                    # Convert positional ? params to named params
                    for i, val in enumerate(cond_params):
                        param_name = f"_cond_{i}"
                        where_clause = where_clause.replace("?", f":{param_name}", 1)
                        params[param_name] = val
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid conditions: {exc}")

    # Count
    count_sql = f'SELECT COUNT(*) FROM "{local_table}" WHERE {where_clause}'

    # Sort
    order_clause = ""
    if sort_field and sort_field in field_map:
        safe_sort = _safe_identifier(sort_field)
        direction = "DESC" if sort_dir == "desc" else "ASC"
        order_clause = f' ORDER BY "{safe_sort}" {direction}'
    elif sort_field == "sys_id":
        direction = "DESC" if sort_dir == "desc" else "ASC"
        order_clause = f' ORDER BY "sys_id" {direction}'
    else:
        order_clause = ' ORDER BY "_row_id" DESC'

    data_sql = (
        f'SELECT {col_list} FROM "{local_table}" '
        f'WHERE {where_clause}{order_clause} '
        f'LIMIT :_limit OFFSET :_offset'
    )
    params["_limit"] = limit
    params["_offset"] = offset

    with engine.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        result = conn.execute(text(data_sql), params)
        col_names = list(result.keys())
        rows = []
        for row in result:
            row_dict = {}
            for i, col in enumerate(col_names):
                row_dict[col] = _serialize_value(row[i])
            rows.append(row_dict)

    # Build column metadata for the frontend
    columns_meta = []
    for col in columns:
        fm = field_map.get(col)
        if fm:
            columns_meta.append({
                "local_column": col,
                "column_label": fm.column_label or col,
                "kind": _sn_type_to_kind(fm.sn_internal_type),
                "is_reference": fm.is_reference,
                "sn_reference_table": fm.sn_reference_table,
            })
        elif col == "sys_id":
            columns_meta.append({
                "local_column": "sys_id",
                "column_label": "Sys ID",
                "kind": "string",
                "is_reference": False,
                "sn_reference_table": None,
            })

    return {
        "sn_table_name": table,
        "local_table_name": registry.local_table_name,
        "columns": columns_meta,
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 1C. Dynamic Record Detail API
# ---------------------------------------------------------------------------

@dynamic_browser_router.get("/api/dynamic-browser/record")
async def api_dynamic_record_detail(
    table: str = Query(..., description="ServiceNow table name"),
    instance_id: int = Query(...),
    sys_id: str = Query(..., description="ServiceNow sys_id"),
    session: Session = Depends(get_session),
):
    """Return a single record with field-by-field metadata for the detail view."""
    registry = _get_registry(session, instance_id, table)
    local_table = _safe_identifier(registry.local_table_name)

    if not _table_exists(registry.local_table_name):
        raise HTTPException(status_code=404, detail="Mirror table does not exist")

    mappings = _get_field_mappings(session, registry.id)

    # Select all columns including raw JSON
    all_cols = ["sys_id"] + [
        fm.local_column for fm in mappings
        if fm.local_column not in _ENVELOPE_COLUMNS and fm.local_column != "sys_id"
    ] + ["_raw_json"]

    col_list = ", ".join(f'"{_safe_identifier(c)}"' for c in all_cols)
    sql = (
        f'SELECT {col_list} FROM "{local_table}" '
        f'WHERE "_instance_id" = :iid AND "sys_id" = :sid LIMIT 1'
    )

    with engine.connect() as conn:
        result = conn.execute(text(sql), {"iid": instance_id, "sid": sys_id})
        row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail=f"Record {sys_id} not found")

    col_names = list(all_cols)
    field_map = {fm.local_column: fm for fm in mappings}

    # Build field rows
    field_rows = []
    raw_json = None
    for i, col in enumerate(col_names):
        value = _serialize_value(row[i])
        if col == "_raw_json":
            raw_json = value
            continue

        fm = field_map.get(col)
        field_row: Dict[str, Any] = {
            "field": col,
            "label": (fm.column_label or col) if fm else col,
            "value": value,
            "kind": _sn_type_to_kind(fm.sn_internal_type) if fm else "string",
            "is_reference": fm.is_reference if fm else False,
            "reference_table": fm.sn_reference_table if fm and fm.is_reference else None,
        }
        field_rows.append(field_row)

    # Available tables for reference link rendering
    all_registries = session.exec(
        select(SnTableRegistry)
        .where(SnTableRegistry.instance_id == instance_id)
    ).all()
    available_tables = sorted({r.sn_table_name for r in all_registries})

    return {
        "sn_table_name": table,
        "sn_table_label": registry.sn_table_label or registry.display_label or table,
        "instance_id": instance_id,
        "sys_id": sys_id,
        "field_rows": field_rows,
        "raw_json": raw_json,
        "available_tables": available_tables,
    }


# ---------------------------------------------------------------------------
# 1D. Dynamic Suggest API
# ---------------------------------------------------------------------------

@dynamic_browser_router.get("/api/dynamic-browser/suggest")
async def api_dynamic_suggest(
    table: str = Query(..., description="ServiceNow table name"),
    instance_id: int = Query(...),
    field: str = Query(..., description="Column name to search"),
    q: str = Query("", description="Search text"),
    limit: int = Query(20, ge=1, le=50),
    session: Session = Depends(get_session),
):
    """Type-ahead suggestions for a specific field in a mirror table."""
    registry = _get_registry(session, instance_id, table)
    local_table = _safe_identifier(registry.local_table_name)

    if not _table_exists(registry.local_table_name):
        return {"suggestions": []}

    # Validate field exists in mappings
    mappings = _get_field_mappings(session, registry.id)
    valid_columns = {fm.local_column for fm in mappings} | {"sys_id"}
    safe_field = _safe_identifier(field)
    if safe_field not in valid_columns:
        raise HTTPException(status_code=400, detail=f"Unknown field: {field}")

    where = '"_instance_id" = :iid'
    params: Dict[str, Any] = {"iid": instance_id, "lim": limit}

    if q.strip():
        where += f' AND "{safe_field}" LIKE :q'
        params["q"] = f"%{q.strip()}%"

    sql = (
        f'SELECT DISTINCT "{safe_field}" FROM "{local_table}" '
        f'WHERE {where} AND "{safe_field}" IS NOT NULL AND "{safe_field}" != \'\' '
        f'ORDER BY "{safe_field}" LIMIT :lim'
    )

    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        suggestions = [str(row[0]) for row in result]

    return {"suggestions": suggestions}


# ---------------------------------------------------------------------------
# HTML Pages (Phase 3)
# ---------------------------------------------------------------------------

@dynamic_browser_router.get("/browse", response_class=HTMLResponse)
async def table_index_page(
    request: Request,
    instance_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Table index: lists all registered tables grouped by source."""
    instances = list(session.exec(select(Instance)).all())

    if not instance_id and instances:
        instance_id = instances[0].id

    instance = session.get(Instance, instance_id) if instance_id else None

    # Get all registered tables for this instance
    tables = []
    if instance_id:
        registries = session.exec(
            select(SnTableRegistry)
            .where(SnTableRegistry.instance_id == instance_id)
            .where(SnTableRegistry.is_active == True)  # noqa: E712
            .order_by(SnTableRegistry.source, SnTableRegistry.sn_table_name)
        ).all()
        for reg in registries:
            tables.append({
                "sn_table_name": reg.sn_table_name,
                "local_table_name": reg.local_table_name,
                "sn_table_label": reg.sn_table_label or reg.display_label or reg.sn_table_name,
                "source": reg.source or "unknown",
                "priority_group": reg.priority_group,
                "field_count": reg.field_count,
                "row_count": reg.row_count,
            })

    # Group by source
    groups: Dict[str, List] = {}
    for t in tables:
        src = t["source"]
        groups.setdefault(src, []).append(t)

    return templates.TemplateResponse("table_index.html", {
        "request": request,
        "instances": instances,
        "instance": instance,
        "instance_id": instance_id,
        "groups": groups,
        "total_tables": len(tables),
    })


@dynamic_browser_router.get("/browse/{sn_table_name}", response_class=HTMLResponse)
async def dynamic_browse_page(
    request: Request,
    sn_table_name: str,
    instance_id: int = Query(...),
    assessment_id: Optional[int] = Query(None),
    filter_field: Optional[str] = Query(None),
    filter_value: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Universal table browser page — works for any registered table."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    registry = _get_registry(session, instance_id, sn_table_name)

    return templates.TemplateResponse("dynamic_browser.html", {
        "request": request,
        "instance": instance,
        "instance_id": instance_id,
        "sn_table_name": sn_table_name,
        "table_label": registry.sn_table_label or registry.display_label or sn_table_name,
        "source": registry.source or "unknown",
        "assessment_id": assessment_id,
        "filter_field": filter_field,
        "filter_value": filter_value,
    })


@dynamic_browser_router.get("/browse/{sn_table_name}/record/{sys_id}", response_class=HTMLResponse)
async def dynamic_record_detail_page(
    request: Request,
    sn_table_name: str,
    sys_id: str,
    instance_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """Schema-driven record detail page."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    registry = _get_registry(session, instance_id, sn_table_name)

    # Build ServiceNow link
    sn_url = None
    if instance.url:
        base = instance.url.rstrip("/")
        sn_url = f"{base}/{sn_table_name}.do?sys_id={sys_id}"

    return templates.TemplateResponse("dynamic_browser_record.html", {
        "request": request,
        "instance": instance,
        "instance_id": instance_id,
        "sn_table_name": sn_table_name,
        "table_label": registry.sn_table_label or registry.display_label or sn_table_name,
        "sys_id": sys_id,
        "sn_url": sn_url,
    })
