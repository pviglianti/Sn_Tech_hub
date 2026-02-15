"""Unified job log routes.

Provides a single cross-module run log view with standardized fields,
including CSDM ingestion logs and preflight data pull runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlmodel import Session, select

from ...database import engine, get_session
from ...models import Instance
from ...services.condition_query_builder import conditions_to_sql_where

job_log_router = APIRouter(tags=["job-log"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_ALLOWED_MODULES = {"all", "csdm", "preflight", "initial_data"}
_ALLOWED_PAGE_SIZES = (25, 50, 100, 200)
_ALLOWED_SORT_FIELDS = {
    "started_at",
    "source_label",
    "source_module",
    "instance_id",
    "instance_name",
    "instance_company",
    "instance_label",
    "target_name",
    "job_type",
    "status_text",
    "status_class",
    "rows_inserted",
    "rows_updated",
    "duration_seconds",
    "error_message",
    "completed_at",
    "sort_at",
}

_JOB_LOG_FIELDS = [
    {
        "local_column": "started_at",
        "column_label": "Started",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "source_label",
        "column_label": "Module",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_label",
        "column_label": "Instance",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "target_name",
        "column_label": "Target",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "job_type",
        "column_label": "Job Type",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "status_text",
        "column_label": "Status",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "rows_inserted",
        "column_label": "Rows Inserted",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "rows_updated",
        "column_label": "Rows Updated",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "duration_seconds",
        "column_label": "Duration (s)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "error_message",
        "column_label": "Error",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "source_module",
        "column_label": "Module Key",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_id",
        "column_label": "Instance ID",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_name",
        "column_label": "Instance Name",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_company",
        "column_label": "Company",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "completed_at",
        "column_label": "Completed",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
]

_UNIFIED_JOB_SOURCE_SQL = """
SELECT
    'csdm' AS source_module,
    'CSDM' AS source_label,
    l.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    l.sn_table_name AS target_name,
    l.job_type AS job_type,
    COALESCE(l.status, 'unknown') AS status_text,
    CASE
        WHEN lower(COALESCE(l.status, '')) IN ('success', 'completed') THEN 'completed'
        WHEN lower(COALESCE(l.status, '')) IN ('in_progress', 'running') THEN 'running'
        WHEN lower(COALESCE(l.status, '')) IN ('started', 'queued', 'pending') THEN 'pending'
        WHEN lower(COALESCE(l.status, '')) IN ('failed', 'error') THEN 'failed'
        WHEN lower(COALESCE(l.status, '')) IN ('cancelled', 'canceled') THEN 'cancelled'
        WHEN lower(COALESCE(l.status, '')) IN ('idle', 'never') THEN 'idle'
        ELSE 'pending'
    END AS status_class,
    CAST(COALESCE(l.rows_inserted, 0) AS INTEGER) AS rows_inserted,
    CAST(COALESCE(l.rows_updated, 0) AS INTEGER) AS rows_updated,
    COALESCE(l.started_at, l.created_at) AS started_at,
    l.completed_at AS completed_at,
    CASE
        WHEN COALESCE(l.started_at, l.created_at) IS NULL THEN NULL
        WHEN l.completed_at IS NOT NULL THEN ROUND((julianday(l.completed_at) - julianday(COALESCE(l.started_at, l.created_at))) * 86400.0, 1)
        WHEN lower(COALESCE(l.status, '')) IN ('running', 'in_progress', 'started', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(l.started_at, l.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(l.error_message, '') AS error_message,
    COALESCE(l.completed_at, COALESCE(l.started_at, l.created_at), l.created_at) AS sort_at
FROM csdm_job_log l
JOIN instance i ON i.id = l.instance_id

UNION ALL

SELECT
    CASE WHEN COALESCE(p.source_context, '') = 'initial_data' THEN 'initial_data' ELSE 'preflight' END AS source_module,
    CASE WHEN COALESCE(p.source_context, '') = 'initial_data' THEN 'Initial Data' ELSE 'Preflight' END AS source_label,
    p.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    p.data_type AS target_name,
    COALESCE(p.sync_mode, 'data_pull') AS job_type,
    COALESCE(p.status, 'unknown') AS status_text,
    CASE
        WHEN lower(COALESCE(p.status, '')) IN ('success', 'completed') THEN 'completed'
        WHEN lower(COALESCE(p.status, '')) IN ('in_progress', 'running') THEN 'running'
        WHEN lower(COALESCE(p.status, '')) IN ('started', 'queued', 'pending') THEN 'pending'
        WHEN lower(COALESCE(p.status, '')) IN ('failed', 'error') THEN 'failed'
        WHEN lower(COALESCE(p.status, '')) IN ('cancelled', 'canceled') THEN 'cancelled'
        WHEN lower(COALESCE(p.status, '')) IN ('idle', 'never') THEN 'idle'
        ELSE 'pending'
    END AS status_class,
    CAST(COALESCE(p.records_pulled, 0) AS INTEGER) AS rows_inserted,
    CAST(0 AS INTEGER) AS rows_updated,
    COALESCE(p.started_at, p.updated_at, p.created_at) AS started_at,
    p.completed_at AS completed_at,
    CASE
        WHEN COALESCE(p.started_at, p.updated_at, p.created_at) IS NULL THEN NULL
        WHEN p.completed_at IS NOT NULL THEN ROUND((julianday(p.completed_at) - julianday(COALESCE(p.started_at, p.updated_at, p.created_at))) * 86400.0, 1)
        WHEN lower(COALESCE(p.status, '')) IN ('running', 'in_progress', 'started', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(p.started_at, p.updated_at, p.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(p.error_message, '') AS error_message,
    COALESCE(p.completed_at, COALESCE(p.started_at, p.updated_at, p.created_at), p.updated_at, p.created_at) AS sort_at
FROM instance_data_pull p
JOIN instance i ON i.id = p.instance_id
WHERE (
    p.status != 'idle'
    OR p.started_at IS NOT NULL
    OR p.completed_at IS NOT NULL
    OR p.last_pulled_at IS NOT NULL
    OR COALESCE(p.records_pulled, 0) > 0
    OR p.error_message IS NOT NULL
)

UNION ALL

SELECT
    CASE
        WHEN json_extract(r.metadata_json, '$.source') = 'initial_data' THEN 'initial_data'
        ELSE 'preflight'
    END AS source_module,
    CASE
        WHEN json_extract(r.metadata_json, '$.source') = 'initial_data' THEN 'Initial Data'
        ELSE 'Preflight'
    END AS source_label,
    r.instance_id AS instance_id,
    i.name AS instance_name,
    i.company AS instance_company,
    CASE
        WHEN i.company IS NOT NULL AND TRIM(i.company) != '' THEN i.company || ' - ' || i.name
        ELSE i.name
    END AS instance_label,
    'sys_dictionary' AS target_name,
    COALESCE(r.mode, 'full') AS job_type,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'pending'
    END AS status_text,
    CASE r.status
        WHEN 'completed' THEN 'completed'
        WHEN 'running' THEN 'running'
        WHEN 'queued' THEN 'pending'
        WHEN 'failed' THEN 'failed'
        WHEN 'cancelled' THEN 'cancelled'
        ELSE 'pending'
    END AS status_class,
    CAST(COALESCE(r.queue_completed, 0) AS INTEGER) AS rows_inserted,
    CAST(0 AS INTEGER) AS rows_updated,
    COALESCE(r.started_at, r.created_at) AS started_at,
    r.completed_at AS completed_at,
    CASE
        WHEN COALESCE(r.started_at, r.created_at) IS NULL THEN NULL
        WHEN r.completed_at IS NOT NULL THEN ROUND((julianday(r.completed_at) - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        WHEN r.status IN ('running', 'queued') THEN ROUND((julianday('now') - julianday(COALESCE(r.started_at, r.created_at))) * 86400.0, 1)
        ELSE NULL
    END AS duration_seconds,
    COALESCE(r.error_message, '') AS error_message,
    COALESCE(r.completed_at, COALESCE(r.started_at, r.created_at), r.created_at) AS sort_at
FROM job_run r
JOIN instance i ON i.id = r.instance_id
WHERE r.job_type = 'dict_pull'
"""


def _normalize_module(module: str) -> str:
    normalized = (module or "all").strip().lower()
    if normalized not in _ALLOWED_MODULES:
        raise HTTPException(status_code=400, detail="Invalid module filter")
    return normalized


def _coerce_page_size(limit: int) -> int:
    if limit in _ALLOWED_PAGE_SIZES:
        return limit
    for candidate in reversed(_ALLOWED_PAGE_SIZES):
        if limit >= candidate:
            return candidate
    return 50


def _bind_positional(sql: str, values: list[Any], params: Dict[str, Any], prefix: str) -> str:
    bound_sql = sql
    for idx, value in enumerate(values):
        key = f"{prefix}_{idx}"
        bound_sql = bound_sql.replace("?", f":{key}", 1)
        params[key] = value
    return bound_sql


def _initial_condition_tree(module: str, instance_id: Optional[int]) -> Optional[Dict[str, Any]]:
    conditions: list[Dict[str, Any]] = []

    if module in {"csdm", "preflight"}:
        conditions.append(
            {
                "field": "source_module",
                "operator": "is",
                "value": module,
            }
        )

    if instance_id is not None:
        conditions.append(
            {
                "field": "instance_id",
                "operator": "equals",
                "value": str(instance_id),
            }
        )

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"logic": "AND", "conditions": conditions}


def _row_to_json(row: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    for key in ("started_at", "completed_at", "sort_at"):
        value = data.get(key)
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data


@job_log_router.get("/job-log", response_class=HTMLResponse)
async def unified_job_log_page(
    request: Request,
    instance_id: Optional[int] = Query(default=None),
    module: str = Query(default="all"),
    limit: int = Query(default=200, ge=20, le=1000),
    session: Session = Depends(get_session),
):
    """Unified job log page across CSDM + preflight modules."""
    normalized_module = _normalize_module(module)

    instances = session.exec(select(Instance).order_by(Instance.name)).all()

    if instance_id is not None:
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

    return templates.TemplateResponse(
        "job_log.html",
        {
            "request": request,
            "instances": instances,
            "selected_instance_id": instance_id,
            "selected_module": normalized_module,
            "selected_limit": limit,
            "initial_page_size": _coerce_page_size(limit),
            "initial_conditions": _initial_condition_tree(normalized_module, instance_id),
        },
    )


@job_log_router.get("/api/job-log/field-schema")
async def api_job_log_field_schema():
    """Static schema metadata for the unified job log DataTable."""
    return {
        "sn_table_name": "job_log",
        "local_table_name": "job_log",
        "sn_table_label": "Unified Job Log",
        "source": "system",
        "field_count": len(_JOB_LOG_FIELDS),
        "fields": _JOB_LOG_FIELDS,
        "available_tables": [],
    }


@job_log_router.get("/api/job-log/records")
async def api_job_log_records(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort_field: Optional[str] = Query(None),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    conditions: Optional[str] = Query(None, description="JSON condition tree"),
    module: str = Query("all"),
    instance_id: Optional[int] = Query(default=None),
):
    """Return paged unified job log rows for the reusable DataTable component."""
    normalized_module = _normalize_module(module)

    where_parts: list[str] = []
    params: Dict[str, Any] = {}

    if normalized_module in {"csdm", "preflight"}:
        where_parts.append('j."source_module" = :_module')
        params["_module"] = normalized_module

    if instance_id is not None:
        where_parts.append('j."instance_id" = :_instance_id')
        params["_instance_id"] = instance_id

    if conditions:
        try:
            parsed = json.loads(conditions)
            if parsed:
                cond_sql, cond_params = conditions_to_sql_where(parsed, table_alias="j")
                if cond_sql and cond_sql != "1=1":
                    bound_cond_sql = _bind_positional(cond_sql, cond_params, params, "_cond")
                    where_parts.append(bound_cond_sql)
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid conditions: {exc}")

    where_clause = " AND ".join(f"({part})" for part in where_parts) if where_parts else "1=1"

    if sort_field and sort_field in _ALLOWED_SORT_FIELDS:
        direction = "DESC" if sort_dir == "desc" else "ASC"
        order_clause = f'j."{sort_field}" {direction}'
    else:
        order_clause = 'j."sort_at" DESC'

    base_sql = f"WITH unified AS ({_UNIFIED_JOB_SOURCE_SQL})"
    count_sql = f"{base_sql} SELECT COUNT(*) FROM unified AS j WHERE {where_clause}"

    selected_columns = [field["local_column"] for field in _JOB_LOG_FIELDS] + ["sort_at"]
    select_list = ", ".join(f'j."{col}"' for col in selected_columns)
    data_sql = (
        f"{base_sql} "
        f"SELECT {select_list} FROM unified AS j "
        f"WHERE {where_clause} "
        f"ORDER BY {order_clause} "
        f"LIMIT :_limit OFFSET :_offset"
    )

    query_params = dict(params)
    query_params["_limit"] = limit
    query_params["_offset"] = offset

    with engine.connect() as conn:
        total = conn.execute(text(count_sql), params).scalar() or 0
        result = conn.execute(text(data_sql), query_params)
        rows = [_row_to_json(dict(row)) for row in result.mappings().all()]

    return {
        "sn_table_name": "job_log",
        "local_table_name": "job_log",
        "columns": _JOB_LOG_FIELDS,
        "rows": rows,
        "total": int(total),
        "offset": offset,
        "limit": limit,
    }
