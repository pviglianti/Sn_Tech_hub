"""Connected AI dispatch for feature grouping, refinement, and recommendations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..mcp.registry import PROMPT_REGISTRY
from ..models import (
    Assessment,
    Feature,
    FeatureContextArtifact,
    FeatureGroupingRun,
    FeatureRecommendation,
    FeatureScanResult,
)
from .ai_analysis_dispatch import (
    _build_assessment_scope_context,
    _extract_prompt_text,
    _run_cli_batch,
)
from .ai_stage_tool_sets import STAGE_TOOL_SETS
from .feature_governance import build_feature_assignment_summary, refresh_feature_metadata
from .integration_properties import AIFeatureProperties, AIRuntimeProperties
from .llm.dispatcher_router import DispatcherRouter, ResolvedConfig
from .llm.models import LLMAuthSlot, LLMModel, LLMProvider


_FEATURE_STAGE_TOOLSETS = {
    "grouping": "grouping",
    "ai_refinement": "ai_refinement",
    "recommendations": "recommendations",
}


@dataclass(frozen=True)
class AIFeatureStageSummary:
    stage: str
    pass_count: int
    feature_count: int
    assigned_count: int
    unassigned_count: int
    provisional_feature_count: int
    run_id: Optional[int]


def _extract_registered_prompt_text(
    session: Session,
    *,
    prompt_name: str,
    arguments: Dict[str, Any],
) -> Optional[str]:
    if not PROMPT_REGISTRY.has_prompt(prompt_name):
        return None
    try:
        prompt_result = PROMPT_REGISTRY.get_prompt(prompt_name, arguments, session=session)
    except Exception:
        return None
    text = _extract_prompt_text(prompt_result)
    return text or None


def _resolve_pass_dispatch_config(
    session: Session,
    *,
    stage: str,
    runtime_props: AIRuntimeProperties,
    pass_plan_item: Dict[str, Any],
) -> ResolvedConfig:
    base = DispatcherRouter(session).resolve(stage)
    provider_kind = str(pass_plan_item.get("provider") or base.provider_kind).strip().lower()
    model_name = str(pass_plan_item.get("model") or base.model_name).strip()
    effort_level = str(pass_plan_item.get("effort") or base.effort_level).strip().lower() or base.effort_level

    if provider_kind == base.provider_kind and model_name == base.model_name and effort_level == base.effort_level:
        return base

    provider = session.exec(
        select(LLMProvider)
        .where(LLMProvider.provider_kind == provider_kind)
        .where(LLMProvider.is_active == True)  # noqa: E712
        .order_by(LLMProvider.id.asc())
        .limit(1)
    ).first()
    if not provider:
        raise RuntimeError(f"No active provider found for feature pass override: {provider_kind}")

    model = session.exec(
        select(LLMModel)
        .where(LLMModel.provider_id == int(provider.id))
        .where(LLMModel.model_name == model_name)
        .order_by(LLMModel.id.asc())
        .limit(1)
    ).first()
    if not model:
        model = session.exec(
            select(LLMModel)
            .where(LLMModel.provider_id == int(provider.id))
            .where(LLMModel.is_default == True)  # noqa: E712
            .order_by(LLMModel.id.asc())
            .limit(1)
        ).first()
    if not model:
        raise RuntimeError(
            f"No model found for feature pass override provider={provider_kind} model={model_name or '<default>'}"
        )

    slot_kind = None
    if runtime_props.mode == "local_subscription":
        slot_kind = "cli"
    elif runtime_props.mode == "api_key":
        slot_kind = "api_key"

    auth_stmt = select(LLMAuthSlot).where(
        LLMAuthSlot.provider_id == int(provider.id),
        LLMAuthSlot.is_active == True,  # noqa: E712
    )
    if slot_kind:
        auth_stmt = auth_stmt.where(LLMAuthSlot.slot_kind == slot_kind)
    auth_slot = session.exec(auth_stmt.order_by(LLMAuthSlot.id.asc()).limit(1)).first()
    if not auth_slot:
        raise RuntimeError(
            f"No active auth slot found for feature pass override provider={provider_kind} mode={runtime_props.mode}"
        )

    return ResolvedConfig(
        provider_kind=provider.provider_kind,
        provider_id=int(provider.id),
        model_name=model.model_name,
        model_id=int(model.id),
        effort_level=effort_level,
        dispatcher=base.dispatcher,
        auth_slot=auth_slot,
    )


def _feature_bucket_taxonomy_text(bucket_taxonomy: List[Dict[str, Any]]) -> str:
    lines = ["## Bucket Taxonomy"]
    for item in bucket_taxonomy:
        lines.append(f"- `{item['key']}` => {item['label']}: {item.get('description') or ''}".rstrip())
    return "\n".join(lines)


def _feature_status_text(summary: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Current Feature Coverage",
            f"- In-scope customized artifacts: {int(summary.get('in_scope_customized_total') or 0)}",
            f"- Assigned to features: {int(summary.get('assigned_count') or 0)}",
            f"- Human standalones accepted: {int(summary.get('human_standalone_count') or 0)}",
            f"- Unassigned: {int(summary.get('unassigned_count') or 0)}",
            f"- Provisional features remaining: {int(summary.get('provisional_feature_count') or 0)}",
            f"- Bucket features: {int(summary.get('bucket_feature_count') or 0)}",
        ]
    )


def _build_feature_stage_prompt(
    session: Session,
    *,
    assessment: Assessment,
    stage: str,
    pass_plan_item: Dict[str, Any],
    feature_props: AIFeatureProperties,
    use_registered_prompts: bool,
    coverage_summary: Dict[str, Any],
) -> str:
    sections = [
        _build_assessment_scope_context(session, assessment),
        _feature_bucket_taxonomy_text(feature_props.bucket_taxonomy),
        _feature_status_text(coverage_summary),
    ]
    if use_registered_prompts:
        methodology_prompt = _extract_registered_prompt_text(
            session,
            prompt_name="tech_assessment_expert",
            arguments={"assessment_id": str(int(assessment.id))},
        )
        if methodology_prompt:
            sections.append(methodology_prompt)

    pass_key = str(pass_plan_item.get("pass_key") or "").strip().lower()
    pass_label = str(pass_plan_item.get("label") or pass_key.replace("_", " ").title()).strip()

    common_rules = """\
Use engine results and suggested groupings only as evidence, never as truth.
Adjacent artifacts are fully valid feature members.
Every in-scope customized artifact must end with exactly one primary feature assignment unless a human has already reviewed it and written observations explaining why it stays standalone.
Human-authored feature memberships or human-locked feature names are authoritative facts. Do not override them.
Create bucket features only after you have tried to place artifacts into an obvious solution feature.
Bucket features are first-class features and must stay in the normal feature list.
Final naming happens only in the dedicated final naming pass.
"""

    if stage == "grouping" and pass_key == "structure":
        pass_instructions = f"""\
## Task
You are running the `{pass_label}` pass for AI-owned feature grouping.

Use `get_customizations`, `get_result_detail`, `get_suggested_groupings`, and `feature_grouping_status` to understand the current state.
Create obvious solution features first. Group artifacts that work together into a solution, process, or capability.
When you create or update features in this pass:
- use provisional names only, such as `Working Feature 01` or a stable temporary bucket label,
- set `feature_kind` appropriately,
- set `name_status="provisional"`,
- avoid final polished naming.
Use `create_feature`, `add_result_to_feature`, `remove_result_from_feature`, and `update_feature` as needed.
"""
    elif stage == "grouping" and pass_key == "coverage":
        pass_instructions = f"""\
## Task
You are running the `{pass_label}` pass for AI-owned feature grouping.

Use `feature_grouping_status` to find every remaining unassigned in-scope artifact.
Try again to place each leftover artifact into an existing or new obvious solution feature.
If an artifact still does not clearly belong to a solution feature, place it into the best bucket feature from the configured taxonomy.
No in-scope customized artifact should remain floating after this pass.
Keep all feature names provisional in this pass.
"""
    elif stage == "ai_refinement" and pass_key == "refine":
        pass_instructions = f"""\
## Task
You are running the `{pass_label}` pass for AI-owned feature refinement.

Inspect existing features with `feature_grouping_status` and `get_feature_detail`.
Merge, split, or rebalance features when the grouped artifacts do not actually work together as one solution.
Promote artifacts out of bucket features when they clearly belong to a solution feature.
Keep names provisional in this pass unless a human has locked the name.
"""
    elif stage == "ai_refinement" and pass_key == "final_name":
        pass_instructions = f"""\
## Task
You are running the `{pass_label}` pass for AI-owned feature refinement.

All memberships should already be stable. Use this pass to finalize names and descriptions.
Rename every provisional feature based on what the artifacts do together, what solution they form, or what business capability they deliver.
Use names like `Pharmacy Incident Solution` when that is what the grouped artifacts implement.
Do not leave any AI-authored feature as `provisional` after this pass.
Bucket features may keep categorical names, but polish them if needed.
"""
    elif stage == "recommendations":
        pass_instructions = f"""\
## Task
You are running the `{pass_label}` pass for feature recommendations.

Review the finalized feature graph and use `get_feature_detail` plus ServiceNow product knowledge to decide whether each feature should be kept, refactored, replaced, or removed.
Persist one structured recommendation per feature with `upsert_feature_recommendation`.
Do not rename features or rebalance memberships in this stage.
"""
    else:
        pass_instructions = f"## Task\nExecute the `{pass_label}` pass for stage `{stage}`."

    sections.append(pass_instructions.strip())
    sections.append(common_rules.strip())
    return "\n\n---\n\n".join(section for section in sections if section)


def _reset_ai_feature_graph(session: Session, *, assessment_id: int) -> None:
    feature_rows = session.exec(
        select(Feature).where(Feature.assessment_id == int(assessment_id))
    ).all()
    feature_ids = [int(feature.id) for feature in feature_rows if feature.id is not None]

    if feature_ids:
        auto_links = session.exec(
            select(FeatureScanResult)
            .where(FeatureScanResult.feature_id.in_(feature_ids))
            .where(FeatureScanResult.assignment_source != "human")
        ).all()
        for link in auto_links:
            session.delete(link)

        context_rows = session.exec(
            select(FeatureContextArtifact).where(FeatureContextArtifact.feature_id.in_(feature_ids))
        ).all()
        for row in context_rows:
            session.delete(row)

        recommendation_rows = session.exec(
            select(FeatureRecommendation).where(FeatureRecommendation.feature_id.in_(feature_ids))
        ).all()
        for row in recommendation_rows:
            session.delete(row)

        session.flush()

        for feature in feature_rows:
            remaining_human_links = session.exec(
                select(FeatureScanResult.id)
                .where(FeatureScanResult.feature_id == int(feature.id))
                .where(FeatureScanResult.assignment_source == "human")
                .limit(1)
            ).first()
            if remaining_human_links is not None:
                continue
            if str(feature.name_status or "").strip().lower() == "human_locked":
                continue
            session.delete(feature)

    session.flush()


def _start_feature_run(
    session: Session,
    *,
    assessment: Assessment,
    stage: str,
    max_iterations: int,
) -> FeatureGroupingRun:
    run = FeatureGroupingRun(
        instance_id=int(assessment.instance_id),
        assessment_id=int(assessment.id),
        status="running",
        started_at=datetime.utcnow(),
        completed_at=None,
        max_iterations=max_iterations,
        iterations_completed=0,
        converged=False,
        summary_json=None,
    )
    session.add(run)
    session.flush()
    return run


def run_ai_feature_stage_dispatch(
    session: Session,
    *,
    assessment: Assessment,
    stage: str,
    runtime_props: AIRuntimeProperties,
    feature_props: AIFeatureProperties,
    use_registered_prompts: bool,
) -> AIFeatureStageSummary:
    if runtime_props.mode == "disabled":
        raise RuntimeError(f"{stage} requires connected AI runtime; AI runtime mode is disabled.")

    normalized_stage = _FEATURE_STAGE_TOOLSETS.get(stage)
    if normalized_stage is None:
        raise RuntimeError(f"Unsupported AI feature stage: {stage}")

    relevant_passes = [
        item for item in feature_props.pass_plan if str(item.get("stage") or "").strip().lower() == normalized_stage
    ]
    if not relevant_passes:
        if stage == "recommendations":
            relevant_passes = [
                {"stage": "recommendations", "pass_key": "recommend", "label": "Recommendations"}
            ]
        else:
            raise RuntimeError(f"No configured pass plan entries found for stage: {stage}")

    if stage == "grouping":
        _reset_ai_feature_graph(session, assessment_id=int(assessment.id))

    run = _start_feature_run(
        session,
        assessment=assessment,
        stage=stage,
        max_iterations=len(relevant_passes),
    )
    session.commit()

    try:
        DispatcherRouter(session).resolve(stage)

        full_tool_names = list(STAGE_TOOL_SETS.get(stage, []))
        for index, pass_plan_item in enumerate(relevant_passes, start=1):
            coverage_summary = build_feature_assignment_summary(session, assessment_id=int(assessment.id))
            resolved = _resolve_pass_dispatch_config(
                session,
                stage=stage,
                runtime_props=runtime_props,
                pass_plan_item=pass_plan_item,
            )
            prompt = _build_feature_stage_prompt(
                session,
                assessment=assessment,
                stage=stage,
                pass_plan_item=pass_plan_item,
                feature_props=feature_props,
                use_registered_prompts=use_registered_prompts,
                coverage_summary=coverage_summary,
            )

            _run_cli_batch(
                prompt=prompt,
                resolved=resolved,
                runtime_props=runtime_props,
                stage=stage,
                allowed_tools=full_tool_names,
                rpc_url=_resolve_rpc_url_for_stage(session),
                auth_slot=resolved.auth_slot,
            )
            session.expire_all()
            refresh_feature_metadata(session, assessment_id=int(assessment.id), commit=False)
            coverage_summary = build_feature_assignment_summary(session, assessment_id=int(assessment.id))

            run.iterations_completed = index
            run.summary_json = json.dumps(
                {
                    "stage": stage,
                    "last_pass_key": str(pass_plan_item.get("pass_key") or ""),
                    "last_pass_label": str(pass_plan_item.get("label") or ""),
                    "feature_count": int(coverage_summary.get("feature_count") or 0),
                    "assigned_count": int(coverage_summary.get("assigned_count") or 0),
                    "unassigned_count": int(coverage_summary.get("unassigned_count") or 0),
                    "provisional_feature_count": int(coverage_summary.get("provisional_feature_count") or 0),
                    "bucket_feature_count": int(coverage_summary.get("bucket_feature_count") or 0),
                    "generated_at": datetime.utcnow().isoformat(),
                },
                sort_keys=True,
            )
            session.add(run)
            session.commit()

        final_summary = build_feature_assignment_summary(session, assessment_id=int(assessment.id))
        if stage == "grouping" and int(final_summary.get("unassigned_count") or 0) > 0:
            raise RuntimeError(
                "Grouping did not assign every in-scope customized artifact. "
                f"Unassigned artifacts remaining: {int(final_summary.get('unassigned_count') or 0)}."
            )
        if stage == "ai_refinement":
            if int(final_summary.get("unassigned_count") or 0) > 0:
                raise RuntimeError(
                    "AI refinement did not resolve full feature coverage. "
                    f"Unassigned artifacts remaining: {int(final_summary.get('unassigned_count') or 0)}."
                )
            if int(final_summary.get("provisional_feature_count") or 0) > 0:
                raise RuntimeError(
                    "AI refinement final naming pass did not finalize every feature name. "
                    f"Provisional features remaining: {int(final_summary.get('provisional_feature_count') or 0)}."
                )
        run.converged = stage == "ai_refinement" and int(final_summary.get("provisional_feature_count") or 0) == 0
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        session.add(run)
        session.commit()
    except Exception:
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        session.add(run)
        session.commit()
        raise

    return AIFeatureStageSummary(
        stage=stage,
        pass_count=len(relevant_passes),
        feature_count=int(final_summary.get("feature_count") or 0),
        assigned_count=int(final_summary.get("assigned_count") or 0),
        unassigned_count=int(final_summary.get("unassigned_count") or 0),
        provisional_feature_count=int(final_summary.get("provisional_feature_count") or 0),
        run_id=int(run.id) if run.id is not None else None,
    )


def _resolve_rpc_url_for_stage(session: Session) -> str:
    # Imported lazily from ai_analysis_dispatch to keep one MCP bridge resolution path.
    from .ai_analysis_dispatch import _resolve_rpc_url

    return _resolve_rpc_url(session)
