"""Provider-native swarm orchestration helpers for connected AI stages."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .integration_properties import AIRuntimeProperties


def swarm_enabled(runtime_props: AIRuntimeProperties) -> bool:
    return str(runtime_props.execution_strategy or "").strip().lower() == "swarm"


def swarm_width(runtime_props: AIRuntimeProperties) -> int:
    return max(1, int(getattr(runtime_props, "max_concurrent_sessions", 1) or 1))


def effective_ai_analysis_batch_size(
    runtime_props: AIRuntimeProperties,
    configured_batch_size: int,
) -> int:
    batch_size = max(1, int(configured_batch_size or 1))
    if swarm_enabled(runtime_props):
        batch_size = max(batch_size, swarm_width(runtime_props))
    return batch_size


def build_ai_analysis_swarm_prompt(
    *,
    provider_kind: str,
    max_workers: int,
) -> str:
    provider_label = "Codex subagents" if provider_kind == "openai" else "Claude agent team"
    return f"""\
## Swarm Mode
This run is executing in `swarm` mode using {provider_label}. Use subagents only
because swarm is explicitly enabled for this assessment.

Execution rules:
- Create a short coordinator plan for the artifacts in this batch.
- Delegate up to {max_workers} artifact-scoped workers at a time.
- Each worker must own explicit artifact IDs and must not touch artifacts owned
  by another worker.
- Workers MAY call `update_scan_result`, but only for their assigned artifact IDs.
- The coordinator must wait for all workers, verify every artifact in the batch
  was updated successfully, and personally finish any missed artifact before the
  run ends.

Worker guidance:
- Use `get_result_detail` first for each assigned artifact.
- Use `get_customizations` only when cross-artifact context is genuinely needed.
- Persist scope triage with `update_scan_result`.
- Keep findings concise and evidence-based.
"""


def build_feature_stage_swarm_prompt(
    *,
    provider_kind: str,
    stage: str,
    pass_key: str,
    max_workers: int,
) -> str:
    provider_label = "Codex subagents" if provider_kind == "openai" else "Claude agent team"
    common = f"""\
## Swarm Mode
This run is executing in `swarm` mode using {provider_label}. Use subagents only
because swarm is explicitly enabled for this assessment.

Execution rules:
- Use a coordinator plus up to {max_workers} analysis workers in parallel.
- Workers should inspect scoped subsets, compare evidence, and return concrete
  proposals to the coordinator.
- For feature stages, the coordinator is the only agent allowed to mutate the
  feature graph or recommendation rows. Workers are analysis-only unless the
  prompt explicitly narrows a write-safe ownership slice.
- The coordinator must consolidate worker findings, resolve conflicts, and then
  apply the final MCP write operations itself.
"""
    key = f"{stage}:{pass_key}"
    task_specific = {
        "grouping:structure": """\
Use workers to inspect clusters of related artifacts and propose:
- which artifacts belong together as one solution feature,
- when a new provisional feature should exist,
- when a bucket feature is the only defensible fit.
The coordinator should create/update features only after comparing worker proposals.""",
        "grouping:coverage": """\
Use workers to review the remaining unassigned artifacts in parallel and propose
the best destination feature or bucket for each one. The coordinator should then
apply the final assignments centrally so no artifact is left unassigned.""",
        "ai_refinement:refine": """\
Use workers to challenge the current feature graph: look for merges, splits,
misplaced artifacts, and bucket escape opportunities. The coordinator should
apply only the changes that still hold up after cross-checking the proposals.""",
        "ai_refinement:final_name": """\
Use workers to propose final names/descriptions for scoped feature sets. The
coordinator should choose the final names, enforce consistency, and then write
them back in one controlled pass.""",
        "recommendations:recommend": """\
Use workers to evaluate distinct features in parallel and propose keep/refactor/
replace/remove recommendations with rationale. The coordinator should normalize
the recommendations and persist the final structured records.""",
    }.get(
        key,
        "Use workers for scoped analysis and keep final mutations centralized in the coordinator.",
    )
    return "\n\n".join([common, task_specific])


def build_codex_swarm_config_overrides(runtime_props: AIRuntimeProperties) -> list[str]:
    return [
        "features.multi_agent=true",
        f"agents.max_threads={swarm_width(runtime_props)}",
        "agents.max_depth=1",
    ]


def build_claude_swarm_append_system_prompt(
    *,
    stage: str,
    pass_key: Optional[str],
    max_workers: int,
) -> str:
    if stage == "ai_analysis":
        mutation_rule = (
            "Artifact workers may write `update_scan_result` only for their assigned artifact IDs."
        )
    else:
        mutation_rule = (
            "Only the coordinator may write feature graph or recommendation mutations; workers are analysis-only."
        )
    label = f"{stage}:{pass_key}" if pass_key else stage
    return (
        f"Swarm mode is enabled for stage `{label}`. "
        f"Use agent teams/subagents deliberately, with at most {max_workers} active workers. "
        f"{mutation_rule} Wait for all workers, reconcile their findings, and ensure the coordinator delivers the final state."
    )


def build_claude_swarm_agents(
    *,
    stage: str,
    pass_key: Optional[str],
) -> str:
    if stage == "ai_analysis":
        agents: Dict[str, Dict[str, str]] = {
            "artifact_scope_analyst": {
                "description": "Scopes one or more assigned assessment artifacts and writes update_scan_result only for those artifact IDs.",
                "prompt": (
                    "You are an artifact scope analyst. Only work on the artifact IDs explicitly assigned to you by the coordinator. "
                    "Use get_result_detail first, use get_customizations only when cross-artifact evidence is needed, "
                    "and persist concise scope triage with update_scan_result. Never touch artifact IDs you were not assigned."
                ),
            },
            "artifact_context_researcher": {
                "description": "Read-heavy specialist for cross-artifact context and ServiceNow evidence gathering.",
                "prompt": (
                    "You are a read-heavy context researcher. Investigate relationships, neighboring artifacts, or ServiceNow evidence for the coordinator. "
                    "Prefer read/search tools. Do not write unless the coordinator explicitly narrows ownership to you."
                ),
            },
        }
    else:
        pass_name = pass_key or stage
        agents = {
            "feature_cluster_analyst": {
                "description": "Analyzes artifact clusters and feature boundaries for grouping/refinement work.",
                "prompt": (
                    f"You are a feature cluster analyst for `{stage}` / `{pass_name}`. "
                    "Inspect the assigned artifacts/features, find the strongest grouping logic, and return concrete proposals. "
                    "Do not mutate the feature graph yourself."
                ),
            },
            "feature_coverage_reviewer": {
                "description": "Finds gaps, leftovers, and bucket-placement issues in the feature graph.",
                "prompt": (
                    f"You are a coverage reviewer for `{stage}` / `{pass_name}`. "
                    "Focus on unassigned items, weak assignments, and bucket-fit questions. Return a concise proposal set. "
                    "Do not mutate the feature graph yourself."
                ),
            },
            "feature_naming_reviewer": {
                "description": "Specialist for final naming and recommendation wording.",
                "prompt": (
                    f"You are a naming/recommendation specialist for `{stage}` / `{pass_name}`. "
                    "Propose final names, descriptions, or recommendation language based on the assigned feature set. "
                    "Do not write the final records yourself."
                ),
            },
        }
    return json.dumps(agents, sort_keys=True)
