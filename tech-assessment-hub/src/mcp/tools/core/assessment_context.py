"""MCP tool: get_assessment_context — resolve scope context for an assessment.

Returns everything a scope-triage / observation / grouping skill needs to make
decisions WITHOUT guessing: target app, core tables, parent table, keywords,
file classes, scope filter, and a resolved `in_scope_tables` convenience list.

Replaces the need for SKILL.md files to hardcode per-app table lists.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    Assessment,
    AssessmentTypeConfig,
    GlobalApp,
)


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment ID to resolve scope context for.",
        },
    },
    "required": ["assessment_id"],
}


def _load_json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    return []


def handle(session: Session, params: Dict[str, Any]) -> Dict[str, Any]:
    assessment_id = params.get("assessment_id")
    if assessment_id is None:
        raise ValueError("assessment_id is required")

    assessment = session.get(Assessment, int(assessment_id))
    if assessment is None:
        raise ValueError(f"Assessment {assessment_id} not found")

    target_app: Optional[Dict[str, Any]] = None
    core_tables: List[str] = []
    parent_table: Optional[str] = None
    keywords: List[str] = []
    table_prefixes: List[str] = []

    if assessment.target_app_id:
        app = session.get(GlobalApp, assessment.target_app_id)
        if app:
            core_tables = _load_json_list(app.core_tables_json)
            keywords = _load_json_list(app.keywords_json)
            table_prefixes = _load_json_list(app.table_prefixes_json)
            parent_table = app.parent_table
            target_app = {
                "id": app.id,
                "name": app.name,
                "label": app.label,
                "description": app.description,
                "core_tables": core_tables,
                "parent_table": app.parent_table,
                "keywords": keywords,
                "table_prefixes": table_prefixes,
                "plugins": _load_json_list(app.plugins_json),
            }

    # Table-type assessments: target_tables_json is the source of truth
    explicit_target_tables = _load_json_list(assessment.target_tables_json)

    # Resolved in-scope tables (core + explicit target tables, deduped, preserve order)
    in_scope_tables: List[str] = []
    for t in core_tables + explicit_target_tables:
        if t and t not in in_scope_tables:
            in_scope_tables.append(t)

    file_classes = _load_json_list(assessment.app_file_classes_json)

    type_config: Optional[Dict[str, Any]] = None
    if assessment.assessment_type_config_id:
        cfg = session.get(AssessmentTypeConfig, assessment.assessment_type_config_id)
        if cfg:
            type_config = {
                "name": cfg.name,
                "label": cfg.label,
                "drivers": _load_json_list(cfg.drivers_json),
                "default_scans": _load_json_list(cfg.default_scans_json),
                "scope_options": _load_json_list(cfg.scope_options_json),
            }

    return {
        "assessment_id": assessment.id,
        "number": assessment.number,
        "name": assessment.name,
        "assessment_type": (
            assessment.assessment_type.value
            if hasattr(assessment.assessment_type, "value")
            else str(assessment.assessment_type)
        ),
        "state": (
            assessment.state.value
            if hasattr(assessment.state, "value")
            else str(assessment.state)
        ),
        "scope_filter": assessment.scope_filter,
        "pipeline_stage": (
            assessment.pipeline_stage.value
            if hasattr(assessment.pipeline_stage, "value")
            else str(assessment.pipeline_stage)
        ),
        "target_app": target_app,
        "explicit_target_tables": explicit_target_tables,
        "in_scope_tables": in_scope_tables,
        "parent_table": parent_table,
        "keywords": keywords,
        "table_prefixes": table_prefixes,
        "file_classes": file_classes,
        "assessment_type_config": type_config,
        "scope_decision_hints": {
            "in_scope": "Artifact's table is in in_scope_tables.",
            "adjacent": (
                "Artifact's table is not in in_scope_tables BUT references/queries "
                "an in-scope table (e.g., parent_table, or a related table). Still IN SCOPE."
            ),
            "out_of_scope": (
                "Artifact's table is unrelated to in_scope_tables and does not reference them. "
                "Tableless artifacts (e.g., script includes) with no in-scope table reference "
                "are out_of_scope."
            ),
        },
    }


TOOL_SPEC = ToolSpec(
    name="get_assessment_context",
    description=(
        "Resolve the scope context for an assessment: target app, core tables, "
        "parent table, keywords, file classes, scope filter, and a convenience "
        "in_scope_tables list. Call this FIRST in any scope-triage / observation / "
        "grouping skill before making classification decisions — it removes the need "
        "to guess which tables are 'target tables' for a given assessment type."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
