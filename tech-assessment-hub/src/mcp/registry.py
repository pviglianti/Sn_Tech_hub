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


# ── Prompt Registry ──────────────────────────────────────────────────

@dataclass
class PromptSpec:
    """MCP Prompt specification."""
    name: str
    description: str
    arguments: List[Dict[str, Any]]
    handler: Callable[..., Dict[str, Any]]


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: Dict[str, PromptSpec] = {}

    def register(self, spec: PromptSpec) -> None:
        self._prompts[spec.name] = spec

    def list_prompts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "arguments": spec.arguments,
            }
            for spec in self._prompts.values()
        ]

    def has_prompt(self, name: str) -> bool:
        return name in self._prompts

    def get_prompt(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if name not in self._prompts:
            raise KeyError(f"Prompt not found: {name}")
        handler = self._prompts[name].handler
        # Check if handler accepts session parameter
        import inspect
        sig = inspect.signature(handler)
        if "session" in sig.parameters:
            return handler(arguments or {}, session=session)
        return handler(arguments or {})


# ── Resource Registry ────────────────────────────────────────────────

@dataclass
class ResourceSpec:
    """MCP Resource specification."""
    uri: str
    name: str
    description: str
    mime_type: str
    handler: Callable[[], str]


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: Dict[str, ResourceSpec] = {}

    def register(self, spec: ResourceSpec) -> None:
        self._resources[spec.uri] = spec

    def list_resources(self) -> List[Dict[str, Any]]:
        return [
            {
                "uri": spec.uri,
                "name": spec.name,
                "description": spec.description,
                "mimeType": spec.mime_type,
            }
            for spec in self._resources.values()
        ]

    def has_resource(self, uri: str) -> bool:
        return uri in self._resources

    def read_resource(self, uri: str) -> Dict[str, Any]:
        if uri not in self._resources:
            raise KeyError(f"Resource not found: {uri}")
        spec = self._resources[uri]
        content = spec.handler()
        return {
            "contents": [
                {
                    "uri": spec.uri,
                    "mimeType": spec.mime_type,
                    "text": content,
                }
            ]
        }


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
    from .tools.core.get_usage_count import TOOL_SPEC as get_usage_count_tool

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
    registry.register(get_usage_count_tool)

    # --- Level 2 analysis tools (pipeline) ---
    from .tools.pipeline.customization_summary import TOOL_SPEC as customization_summary_tool
    from .tools.pipeline.seed_feature_groups import TOOL_SPEC as seed_feature_groups_tool
    from .tools.pipeline.seed_feature_groups import SUGGESTIONS_TOOL_SPEC as get_suggested_groupings_tool
    from .tools.pipeline.run_feature_reasoning import TOOL_SPEC as run_feature_reasoning_tool
    from .tools.pipeline.feature_grouping_status import TOOL_SPEC as feature_grouping_status_tool
    from .tools.pipeline.run_engines import TOOL_SPEC as run_engines_tool
    from .tools.pipeline.generate_observations import TOOL_SPEC as generate_observations_tool

    registry.register(customization_summary_tool)
    registry.register(seed_feature_groups_tool)
    registry.register(get_suggested_groupings_tool)
    registry.register(run_feature_reasoning_tool)
    registry.register(feature_grouping_status_tool)
    registry.register(run_engines_tool)
    registry.register(generate_observations_tool)

    # --- Level 1 write-back tools ---
    from .tools.core.update_result import TOOL_SPEC as update_result_tool
    from .tools.core.update_feature import TOOL_SPEC as update_feature_tool
    from .tools.core.create_feature import TOOL_SPEC as create_feature_tool
    from .tools.core.feature_detail import TOOL_SPEC as feature_detail_tool
    from .tools.core.feature_recommendation import TOOL_SPEC as feature_recommendation_tool
    from .tools.core.update_set_contents import TOOL_SPEC as update_set_contents_tool
    from .tools.core.general_recommendation import TOOL_SPEC as general_recommendation_tool
    from .tools.core.feature_membership import (
        ADD_TOOL_SPEC as add_result_to_feature_tool,
        REMOVE_TOOL_SPEC as remove_result_from_feature_tool,
    )

    registry.register(update_result_tool)
    registry.register(update_feature_tool)
    registry.register(create_feature_tool)
    registry.register(feature_detail_tool)
    registry.register(feature_recommendation_tool)
    registry.register(update_set_contents_tool)
    registry.register(general_recommendation_tool)
    registry.register(add_result_to_feature_tool)
    registry.register(remove_result_from_feature_tool)

    # --- AI pipeline stage runner ---
    from .tools.core.run_ai_stage import TOOL_SPEC as run_ai_stage_tool
    registry.register(run_ai_stage_tool)

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
PROMPT_REGISTRY = PromptRegistry()
RESOURCE_REGISTRY = ResourceRegistry()


def _populate_prompt_registry() -> None:
    """Register assessment methodology prompts."""
    from .prompts.tech_assessment import PROMPT_SPECS
    from .prompts.observation_prompt import PROMPT_SPECS as OBSERVATION_PROMPT_SPECS
    from .prompts.artifact_analyzer import PROMPT_SPECS as ARTIFACT_ANALYZER_SPECS
    from .prompts.relationship_tracer import PROMPT_SPECS as RELATIONSHIP_TRACER_SPECS
    from .prompts.technical_architect import PROMPT_SPECS as technical_architect_specs
    from .prompts.report_writer import PROMPT_SPECS as report_writer_specs

    for spec in PROMPT_SPECS:
        PROMPT_REGISTRY.register(spec)
    for spec in OBSERVATION_PROMPT_SPECS:
        PROMPT_REGISTRY.register(spec)
    for spec in ARTIFACT_ANALYZER_SPECS:
        PROMPT_REGISTRY.register(spec)
    for spec in RELATIONSHIP_TRACER_SPECS:
        PROMPT_REGISTRY.register(spec)
    for spec in technical_architect_specs:
        PROMPT_REGISTRY.register(spec)
    for spec in report_writer_specs:
        PROMPT_REGISTRY.register(spec)


def _populate_resource_registry() -> None:
    """Register assessment reference resources."""
    from .resources.assessment_docs import RESOURCE_SPECS

    for spec in RESOURCE_SPECS:
        RESOURCE_REGISTRY.register(spec)


_populate_prompt_registry()
_populate_resource_registry()
