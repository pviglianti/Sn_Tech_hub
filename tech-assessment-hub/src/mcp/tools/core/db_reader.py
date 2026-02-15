"""MCP tool: sqlite_query (safe read-only query against local cache DB)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from sqlalchemy import text
from sqlmodel import SQLModel, Session

from ...registry import ToolSpec


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": "Read-only SQL query using named parameters (e.g. :instance_id). Only SELECT/WITH allowed.",
        },
        "params": {
            "type": "object",
            "description": "Named parameter values for the query.",
            "additionalProperties": True,
            "default": {},
        },
        "max_rows": {
            "type": "integer",
            "description": "Maximum number of rows to return (1-1000).",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
        },
    },
    "required": ["sql"],
}


FORBIDDEN_KEYWORDS = [
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "replace",
    "truncate",
    "attach",
    "detach",
    "vacuum",
    "reindex",
    "pragma",
    "begin",
    "commit",
    "rollback",
]


def _normalize_sql(sql: str) -> str:
    normalized = sql.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].strip()
    return normalized


def _validate_read_only_sql(sql: str) -> None:
    lowered = sql.lower()

    if ";" in lowered:
        raise ValueError("Multiple SQL statements are not allowed")

    if not re.match(r"^(select|with)\b", lowered):
        raise ValueError("Only SELECT/WITH queries are allowed")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise ValueError(f"Forbidden SQL keyword detected: {keyword}")


def _extract_table_names(sql: str) -> Set[str]:
    # Naive but effective for common FROM/JOIN table references.
    pattern = re.compile(r"\b(?:from|join)\s+\"?([a-zA-Z_][a-zA-Z0-9_]*)\"?", re.IGNORECASE)
    return {match.group(1).lower() for match in pattern.finditer(sql)}


def _allowed_tables() -> Set[str]:
    tables = {name.lower() for name in SQLModel.metadata.tables.keys()}
    # sqlite metadata table needed for limited diagnostics/read operations.
    tables.add("sqlite_master")
    return tables


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    sql = params.get("sql")
    if not sql or not isinstance(sql, str):
        raise ValueError("sql is required")

    normalized_sql = _normalize_sql(sql)
    _validate_read_only_sql(normalized_sql)

    query_params = params.get("params") or {}
    if not isinstance(query_params, dict):
        raise ValueError("params must be an object")

    max_rows = int(params.get("max_rows", 200))
    max_rows = max(1, min(max_rows, 1000))

    tables = _extract_table_names(normalized_sql)
    allowed = _allowed_tables()
    disallowed = sorted([table for table in tables if table not in allowed])
    if disallowed:
        raise ValueError(f"Query references disallowed table(s): {', '.join(disallowed)}")

    statement = text(normalized_sql)
    result = session.connection().execute(statement, query_params)

    fetched = result.mappings().fetchmany(max_rows + 1)
    truncated = len(fetched) > max_rows
    rows: List[Dict[str, Any]] = [dict(row) for row in fetched[:max_rows]]

    return {
        "success": True,
        "row_count": len(rows),
        "truncated": truncated,
        "max_rows": max_rows,
        "columns": list(result.keys()),
        "rows": rows,
    }


TOOL_SPEC = ToolSpec(
    name="sqlite_query",
    description="Execute safe read-only SQL query against local Tech Assessment Hub SQLite cache.",
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
