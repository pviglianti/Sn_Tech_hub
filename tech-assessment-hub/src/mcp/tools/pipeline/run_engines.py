"""MCP tool: run_preprocessing_engines.

Runs deterministic pre-processing engines for an assessment.
Must be called before AI analysis passes.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

from sqlalchemy import text
from sqlmodel import Session

from ...registry import ToolSpec
from ....artifact_detail_defs import ARTIFACT_DETAIL_DEFS
from ....services.assessment_phase_progress import checkpoint_phase_progress, start_phase_progress


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to run engines for.",
        },
        "engines": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional list of engine names to run. "
                "Default: all available engines. "
                "Options: structural_mapper, code_reference_parser, "
                "update_set_analyzer, temporal_clusterer, naming_analyzer, "
                "table_colocation, dependency_mapper"
            ),
        },
    },
    "required": ["assessment_id"],
}


_ENGINE_REGISTRY: Dict[str, str] = {
    # Phase 1 engines
    "structural_mapper": "src.engines.structural_mapper",
    "code_reference_parser": "src.engines.code_reference_parser",
    # Phase 2 engines
    "update_set_analyzer": "src.engines.update_set_analyzer",
    "temporal_clusterer": "src.engines.temporal_clusterer",
    "naming_analyzer": "src.engines.naming_analyzer",
    "table_colocation": "src.engines.table_colocation",
    # Phase 3 engines (depends on Phase 1 outputs)
    "dependency_mapper": "src.engines.dependency_mapper",
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    requested = params.get("engines")

    if requested:
        engine_names = [name for name in requested if name in _ENGINE_REGISTRY]
    else:
        engine_names = list(_ENGINE_REGISTRY.keys())

    start_phase_progress(
        session,
        assessment_id,
        "engines",
        total_items=len(engine_names),
        allow_resume=True,
        checkpoint={"source": "run_preprocessing_engines_tool", "engine_names": engine_names},
        commit=False,
    )

    engines_run: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []

    for idx, name in enumerate(engine_names, start=1):
        module_path = _ENGINE_REGISTRY[name]
        try:
            mod = importlib.import_module(module_path)
            result = dict(mod.run(assessment_id, session) or {})
            raw_errors = _normalize_messages(result.get("errors"))
            if result.get("success") is False and not raw_errors:
                raw_errors = ["engine reported success=false"]
            engine_warnings = _detect_engine_warnings(name, assessment_id, result, session)
            errors.extend(f"{name}: {msg}" for msg in raw_errors)
            warnings.extend(f"{name}: {msg}" for msg in engine_warnings)
            result["errors"] = raw_errors
            if engine_warnings:
                result["warnings"] = engine_warnings
            result["success"] = not raw_errors and bool(result.get("success", True))
            engines_run.append({"engine": name, **result})
        except Exception as exc:  # pragma: no cover - defensive branch
            errors.append(f"{name}: {exc}")
            engines_run.append({"engine": name, "success": False, "error": str(exc)})

        checkpoint_phase_progress(
            session,
            assessment_id,
            "engines",
            completed_items=idx,
            total_items=len(engine_names),
            status="running" if idx < len(engine_names) else ("failed" if errors else "completed"),
            checkpoint={"last_engine": name, "errors": list(errors), "warnings": list(warnings)},
            commit=False,
        )
        session.commit()

    return {
        "success": len(errors) == 0,
        "assessment_id": assessment_id,
        "engines_run": engines_run,
        "errors": errors,
        "warnings": warnings,
    }


def _normalize_messages(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text_value = str(value).strip()
    return [text_value] if text_value else []


def _detect_engine_warnings(
    engine_name: str,
    assessment_id: int,
    result: Dict[str, Any],
    session: Session,
) -> List[str]:
    warnings: List[str] = []

    if engine_name == "structural_mapper":
        source_count = _count_scan_results_for_tables(
            session,
            assessment_id,
            [
                "sys_ui_policy_action",
                "sys_dictionary",
                "sys_dictionary_override",
            ],
        )
        relationships_created = int(result.get("relationships_created") or 0)
        if source_count > 0 and relationships_created == 0:
            warnings.append(
                f"processed {source_count} candidate structural artifacts but created 0 relationships"
            )

    elif engine_name == "code_reference_parser":
        code_tables = [
            table_name
            for table_name, definition in ARTIFACT_DETAIL_DEFS.items()
            if list(definition.get("code_fields", []))
        ]
        source_count = _count_scan_results_for_tables(session, assessment_id, code_tables)
        tables_processed = int(result.get("tables_processed") or 0)
        references_created = int(result.get("references_created") or 0)
        if source_count > 0 and tables_processed > 0 and references_created == 0:
            warnings.append(
                f"processed {tables_processed} code-bearing tables across {source_count} artifacts but created 0 references"
            )

    elif engine_name == "dependency_mapper":
        upstream_edges = _count_table_rows(session, "code_reference", assessment_id) + _count_table_rows(
            session, "structural_relationship", assessment_id
        )
        customized_results = _count_customized_results(session, assessment_id)
        chains_created = int(result.get("chains_created") or 0)
        clusters_created = int(result.get("clusters_created") or 0)
        if customized_results > 0 and upstream_edges > 0 and chains_created == 0 and clusters_created == 0:
            warnings.append(
                f"saw {upstream_edges} upstream dependency edges across {customized_results} customized artifacts but created 0 chains/clusters"
            )

    return warnings


def _count_scan_results_for_tables(session: Session, assessment_id: int, table_names: List[str]) -> int:
    unique_names = sorted({name for name in table_names if name})
    if not unique_names:
        return 0
    params: Dict[str, Any] = {"aid": assessment_id}
    placeholders: List[str] = []
    for idx, table_name in enumerate(unique_names):
        key = f"table_{idx}"
        params[key] = table_name
        placeholders.append(f":{key}")
    sql = (
        "SELECT COUNT(*) "
        "FROM scan_result sr "
        "JOIN scan s ON s.id = sr.scan_id "
        f"WHERE s.assessment_id = :aid AND sr.table_name IN ({', '.join(placeholders)})"
    )
    return _scalar_count(session, text(sql).bindparams(**params))


def _count_customized_results(session: Session, assessment_id: int) -> int:
    return _scalar_count(
        session,
        text(
            "SELECT COUNT(*) "
            "FROM scan_result sr "
            "JOIN scan s ON s.id = sr.scan_id "
            "WHERE s.assessment_id = :aid "
            "AND sr.origin_type IN ('modified_ootb', 'net_new_customer')"
        ).bindparams(aid=assessment_id),
    )


def _count_table_rows(session: Session, table_name: str, assessment_id: int) -> int:
    return _scalar_count(
        session,
        text(f"SELECT COUNT(*) FROM {table_name} WHERE assessment_id = :aid").bindparams(aid=assessment_id),
    )


def _scalar_count(session: Session, statement) -> int:
    row = session.exec(statement).first()
    if row is None:
        return 0
    if isinstance(row, (tuple, list)):
        return int(row[0] or 0)
    if hasattr(row, "__iter__") and not isinstance(row, (str, bytes, int, float)):
        values = tuple(row)
        if values:
            return int(values[0] or 0)
    return int(row or 0)


TOOL_SPEC = ToolSpec(
    name="run_preprocessing_engines",
    description=(
        "Run deterministic pre-processing engines for an assessment. "
        "Populates structural_relationship, code_reference, update_set_overlap, "
        "update_set_artifact_link, temporal_cluster, naming_cluster, and "
        "table_colocation_summary, dependency_chain, and dependency_cluster tables."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
