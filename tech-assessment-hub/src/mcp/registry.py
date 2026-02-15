"""Simple MCP tool registry."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from sqlmodel import Session


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any], Session], Dict[str, Any]]
    permission: str = "read"
    route_key: Optional[str] = None
    fallback_policy: str = "graceful_degrade"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": spec.input_schema,
            }
            for spec in self._tools.values()
        ]

    def iter_specs(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def call(self, name: str, arguments: Dict[str, Any], session: Session) -> Dict[str, Any]:
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name].handler(arguments, session)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    # --- Core tools (Level 0 — original) ---
    from .tools.core.connection import TOOL_SPEC as connection_tool
    from .tools.core.inventory import TOOL_SPEC as inventory_tool
    from .tools.core.db_reader import TOOL_SPEC as db_reader_tool
    from .tools.core.workspace import (
        SCAFFOLD_TOOL_SPEC,
        READ_FILE_TOOL_SPEC,
        UPDATE_FILE_TOOL_SPEC,
        LIST_FILES_TOOL_SPEC,
    )

    registry.register(connection_tool)
    registry.register(inventory_tool)
    registry.register(db_reader_tool)
    registry.register(SCAFFOLD_TOOL_SPEC)
    registry.register(READ_FILE_TOOL_SPEC)
    registry.register(UPDATE_FILE_TOOL_SPEC)
    registry.register(LIST_FILES_TOOL_SPEC)

    # --- Level 1 plumbing tools ---
    from .tools.core.instance_summary import TOOL_SPEC as instance_summary_tool
    from .tools.core.assessment_results import TOOL_SPEC as assessment_results_tool
    from .tools.core.result_detail import TOOL_SPEC as result_detail_tool
    from .tools.core.data_pull import TOOL_SPEC as data_pull_tool
    from .tools.core.assessment import TOOL_SPEC as assessment_tool
    from .tools.core.facts import SAVE_FACT_TOOL_SPEC, GET_FACTS_TOOL_SPEC, DELETE_FACTS_TOOL_SPEC
    from .tools.core.query_live import TOOL_SPEC as query_live_tool
    from .tools.core.customizations import TOOL_SPEC as customizations_tool

    registry.register(instance_summary_tool)
    registry.register(assessment_results_tool)
    registry.register(result_detail_tool)
    registry.register(data_pull_tool)
    registry.register(assessment_tool)
    registry.register(SAVE_FACT_TOOL_SPEC)
    registry.register(GET_FACTS_TOOL_SPEC)
    registry.register(DELETE_FACTS_TOOL_SPEC)
    registry.register(query_live_tool)
    registry.register(customizations_tool)

    # --- Level 2 analysis tools (pipeline) ---
    from .tools.pipeline.customization_summary import TOOL_SPEC as customization_summary_tool
    from .tools.pipeline.feature_grouping import TOOL_SPEC as feature_grouping_tool

    registry.register(customization_summary_tool)
    registry.register(feature_grouping_tool)

    return registry


class _LazyRegistry:
    """Lazy proxy that builds the real ToolRegistry on first access.

    This avoids circular imports when tool modules import ToolSpec from
    this module -- build_registry() is not called until the registry
    is actually used.
    """

    def __init__(self) -> None:
        self._instance: Optional[ToolRegistry] = None

    def _ensure(self) -> ToolRegistry:
        if self._instance is None:
            self._instance = build_registry()
        return self._instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure(), name)

    def register(self, spec: ToolSpec) -> None:
        self._ensure().register(spec)

    def list_tools(self) -> List[Dict[str, Any]]:
        return self._ensure().list_tools()

    def iter_specs(self) -> List[ToolSpec]:
        return self._ensure().iter_specs()

    def has_tool(self, name: str) -> bool:
        return self._ensure().has_tool(name)

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._ensure().get_spec(name)

    def call(self, name: str, arguments: Dict[str, Any], session: Session) -> Dict[str, Any]:
        return self._ensure().call(name, arguments, session)


REGISTRY = _LazyRegistry()
