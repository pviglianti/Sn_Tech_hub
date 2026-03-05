"""MCP tool: run_preprocessing_engines.

Runs deterministic pre-processing engines for an assessment.
Must be called before AI analysis passes.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

from sqlmodel import Session

from ...registry import ToolSpec
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
                "update_set_analyzer, temporal_clusterer, naming_analyzer, table_colocation"
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

    for idx, name in enumerate(engine_names, start=1):
        module_path = _ENGINE_REGISTRY[name]
        try:
            mod = importlib.import_module(module_path)
            result = mod.run(assessment_id, session)
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
            checkpoint={"last_engine": name, "errors": list(errors)},
            commit=False,
        )
        session.commit()

    return {
        "success": len(errors) == 0,
        "assessment_id": assessment_id,
        "engines_run": engines_run,
        "errors": errors,
    }


TOOL_SPEC = ToolSpec(
    name="run_preprocessing_engines",
    description=(
        "Run deterministic pre-processing engines for an assessment. "
        "Populates structural_relationship, code_reference, update_set_overlap, "
        "update_set_artifact_link, temporal_cluster, naming_cluster, and "
        "table_colocation_summary tables."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
