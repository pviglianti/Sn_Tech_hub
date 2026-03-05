"""Assessment runtime usage telemetry page + API routes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlmodel import Session

from ...database import get_session
from ...services.assessment_runtime_usage import refresh_all_assessment_runtime_usage
from ...services.condition_query_builder import conditions_to_sql_where

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_RUNTIME_USAGE_FIELDS = [
    {"local_column": "id", "column_label": "ID", "kind": "number", "is_reference": False, "sn_reference_table": None},
    {
        "local_column": "assessment_id",
        "column_label": "Assessment ID",
        "kind": "number",
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
        "local_column": "assessment_number",
        "column_label": "Assessment",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "assessment_name",
        "column_label": "Assessment Name",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "instance_name",
        "column_label": "Instance",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "assessment_state",
        "column_label": "State",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "llm_runtime_mode",
        "column_label": "LLM Mode",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "llm_provider",
        "column_label": "LLM Provider",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "llm_model",
        "column_label": "LLM Model",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "run_started_at",
        "column_label": "Run Started",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "run_completed_at",
        "column_label": "Run Completed",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "run_duration_seconds",
        "column_label": "Run Duration (s)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_results",
        "column_label": "Total Results",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "customized_results",
        "column_label": "Customized Results",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_features",
        "column_label": "Total Features",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_groupings",
        "column_label": "Total Groupings",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_feature_memberships",
        "column_label": "Feature Memberships",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_technical_recommendations",
        "column_label": "Technical Recommendations",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_general_recommendations",
        "column_label": "General Recommendations",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "total_feature_recommendations",
        "column_label": "Feature Recommendations",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "mcp_calls_local",
        "column_label": "MCP Calls (Local)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "mcp_calls_servicenow",
        "column_label": "MCP Calls (SN)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "mcp_calls_local_db",
        "column_label": "MCP Calls (Local DB)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "llm_input_tokens",
        "column_label": "Input Tokens",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "llm_output_tokens",
        "column_label": "Output Tokens",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "llm_total_tokens",
        "column_label": "Total Tokens",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "estimated_cost_usd",
        "column_label": "Estimated Cost (USD)",
        "kind": "number",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "last_event",
        "column_label": "Last Event",
        "kind": "string",
        "is_reference": False,
        "sn_reference_table": None,
    },
    {
        "local_column": "updated_at",
        "column_label": "Updated",
        "kind": "date",
        "is_reference": False,
        "sn_reference_table": None,
    },
]

_ALLOWED_SORT_FIELDS = {field["local_column"] for field in _RUNTIME_USAGE_FIELDS}


def _bind_positional(sql_text: str, values: list[Any], params: Dict[str, Any], prefix: str) -> str:
    bound = sql_text
    for idx, value in enumerate(values):
        key = f"{prefix}_{idx}"
        bound = bound.replace("?", f":{key}", 1)
        params[key] = value
    return bound


def _row_to_json(row: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


def create_assessment_runtime_usage_router(require_mcp_admin: Callable[..., Dict[str, Any]]) -> APIRouter:
    """Create runtime telemetry router with injected admin dependency."""
    router = APIRouter(tags=["assessment-runtime-usage"])

    @router.get("/integration-properties/assessment-runtime-usage", response_class=HTMLResponse)
    async def assessment_runtime_usage_page(request: Request):
        return templates.TemplateResponse(
            "assessment_runtime_usage.html",
            {"request": request},
        )

    @router.get("/api/integration-properties/assessment-runtime-usage/field-schema")
    async def api_assessment_runtime_usage_field_schema(
        _: Dict[str, Any] = Depends(require_mcp_admin),
    ):
        return {
            "sn_table_name": "assessment_runtime_usage",
            "local_table_name": "assessment_runtime_usage",
            "sn_table_label": "Assessment Runtime Usage",
            "source": "system",
            "field_count": len(_RUNTIME_USAGE_FIELDS),
            "fields": _RUNTIME_USAGE_FIELDS,
            "available_tables": [],
        }

    @router.get("/api/integration-properties/assessment-runtime-usage/records")
    async def api_assessment_runtime_usage_records(
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
        sort_field: Optional[str] = Query(None),
        sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
        conditions: Optional[str] = Query(None, description="JSON condition tree"),
        refresh_snapshots: bool = Query(True, description="Refresh telemetry snapshots before returning rows"),
        session: Session = Depends(get_session),
        _: Dict[str, Any] = Depends(require_mcp_admin),
    ):
        if refresh_snapshots:
            refresh_all_assessment_runtime_usage(session, commit=True)

        where_parts: list[str] = ["1=1"]
        params: Dict[str, Any] = {}

        if conditions:
            try:
                parsed = json.loads(conditions)
                if parsed:
                    cond_sql, cond_params = conditions_to_sql_where(parsed, table_alias="u")
                    if cond_sql and cond_sql != "1=1":
                        bound = _bind_positional(cond_sql, cond_params, params, "_cond")
                        where_parts.append(bound)
            except (json.JSONDecodeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid conditions: {exc}")

        where_clause = " AND ".join(f"({part})" for part in where_parts)

        if sort_field and sort_field in _ALLOWED_SORT_FIELDS:
            direction = "DESC" if sort_dir == "desc" else "ASC"
            order_clause = f'u."{sort_field}" {direction}'
        else:
            order_clause = 'u."updated_at" DESC'

        columns = [field["local_column"] for field in _RUNTIME_USAGE_FIELDS]
        select_cols = ", ".join(f'u."{name}"' for name in columns)

        count_sql = (
            'SELECT COUNT(*) FROM "assessment_runtime_usage" AS u '
            f"WHERE {where_clause}"
        )
        data_sql = (
            f'SELECT {select_cols} FROM "assessment_runtime_usage" AS u '
            f"WHERE {where_clause} "
            f"ORDER BY {order_clause} "
            "LIMIT :_limit OFFSET :_offset"
        )
        query_params = dict(params)
        query_params["_limit"] = limit
        query_params["_offset"] = offset

        conn = session.connection()
        total = int(conn.execute(text(count_sql), params).scalar() or 0)
        result = conn.execute(text(data_sql), query_params)
        rows = [_row_to_json(dict(row)) for row in result.mappings().all()]

        return {
            "sn_table_name": "assessment_runtime_usage",
            "local_table_name": "assessment_runtime_usage",
            "columns": _RUNTIME_USAGE_FIELDS,
            "rows": rows,
            "total": int(total),
            "offset": offset,
            "limit": limit,
        }

    return router
