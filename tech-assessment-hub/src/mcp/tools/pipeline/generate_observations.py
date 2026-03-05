"""MCP tool: generate_observations.

Builds deterministic baseline observations for customized artifacts and writes
them to ``ScanResult.observations`` / ``ScanResult.ai_observations``.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlmodel import Session, select
from sqlalchemy import func

from ...registry import ToolSpec
from ....models import (
    Assessment,
    GeneralRecommendation,
    OriginType,
    ReviewStatus,
    Scan,
    ScanResult,
    StructuralRelationship,
    UpdateSet,
    UpdateSetArtifactLink,
)
from ....services.assessment_phase_progress import (
    checkpoint_phase_progress,
    complete_phase_progress,
    start_phase_progress,
)
from ....services.integration_properties import load_observation_properties
from ....services.customization_sync import sync_single_result
from ..core.get_usage_count import handle as get_usage_count_handle


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment ID to generate observations for.",
        },
        "batch_size": {
            "type": "integer",
            "description": "Optional override for observation batch size.",
        },
        "include_usage_queries": {
            "type": "string",
            "enum": ["always", "auto", "never"],
            "description": "Optional override for usage-query mode.",
        },
        "max_results": {
            "type": "integer",
            "description": "Optional cap for number of customized results to process.",
        },
        "resume_from_index": {
            "type": "integer",
            "description": "Optional 0-based resume cursor for customized artifact processing.",
        },
    },
    "required": ["assessment_id"],
}


_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}


def _origin_value(result: ScanResult) -> str:
    raw = result.origin_type
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw or "")


def _is_customized(result: ScanResult) -> bool:
    return _origin_value(result) in _CUSTOMIZED_ORIGIN_VALUES


def _chunked(items: Sequence[ScanResult], size: int) -> Iterable[List[ScanResult]]:
    chunk_size = max(1, int(size or 1))
    for i in range(0, len(items), chunk_size):
        yield list(items[i : i + chunk_size])


def _compose_landscape_summary(
    *,
    assessment: Assessment,
    customized_results: Sequence[ScanResult],
) -> str:
    total = len(customized_results)
    table_counts = Counter((row.table_name or "").strip() or "unknown" for row in customized_results)
    origin_counts = Counter(_origin_value(row) or "unknown" for row in customized_results)
    top_tables = ", ".join(
        f"{table} ({count})"
        for table, count in table_counts.most_common(5)
    ) or "none"
    origin_bits = ", ".join(
        f"{origin.replace('_', ' ')}: {count}"
        for origin, count in origin_counts.items()
    ) or "none"
    return (
        f"Assessment {assessment.number} currently has {total} customized artifacts. "
        f"Top artifact tables: {top_tables}. "
        f"Customization origin mix: {origin_bits}. "
        "These observations are deterministic baselines and should be refined by AI/human review before final grouping decisions."
    )


def _upsert_landscape_summary(
    session: Session,
    *,
    assessment_id: int,
    summary_text: str,
) -> GeneralRecommendation:
    row = session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == assessment_id)
        .where(GeneralRecommendation.category == "landscape_summary")
        .order_by(GeneralRecommendation.updated_at.desc())
        .limit(1)
    ).first()
    now = datetime.utcnow()
    if row:
        row.title = "Customization Landscape Summary"
        row.description = summary_text
        row.created_by = "computed_pipeline"
        row.updated_at = now
    else:
        row = GeneralRecommendation(
            assessment_id=assessment_id,
            title="Customization Landscape Summary",
            description=summary_text,
            category="landscape_summary",
            created_by="computed_pipeline",
            created_at=now,
            updated_at=now,
        )
    session.add(row)
    session.flush()
    return row


def _usage_query_candidates(result: ScanResult) -> List[Tuple[str, str, str]]:
    candidates: List[Tuple[str, str, str]] = []
    target_table = (result.meta_target_table or "").strip()
    if target_table:
        candidates.append(
            (
                target_table,
                "active=true",
                f"Active usage in target table {target_table}",
            )
        )
    if (result.table_name or "") == "sys_dictionary" and target_table:
        candidates.append(
            (
                target_table,
                "",
                f"Total footprint in target table {target_table}",
            )
        )
    # Deduplicate while preserving order
    deduped: List[Tuple[str, str, str]] = []
    seen = set()
    for table, query, desc in candidates:
        key = (table, query)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((table, query, desc))
    return deduped


def _structural_signal_count(session: Session, result_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .where(
                (StructuralRelationship.parent_scan_result_id == result_id)
                | (StructuralRelationship.child_scan_result_id == result_id)
            )
        ).one()
        or 0
    )


def _update_set_context(
    session: Session,
    *,
    assessment_id: int,
    result_id: int,
) -> Tuple[int, Optional[str]]:
    rows = session.exec(
        select(UpdateSetArtifactLink, UpdateSet)
        .join(UpdateSet, UpdateSetArtifactLink.update_set_id == UpdateSet.id)
        .where(UpdateSetArtifactLink.assessment_id == assessment_id)
        .where(UpdateSetArtifactLink.scan_result_id == result_id)
    ).all()
    count = len(rows)
    name = rows[0][1].name if rows else None
    return count, name


def _format_observation(
    *,
    result: ScanResult,
    update_set_count: int,
    update_set_name: Optional[str],
    structural_count: int,
    usage_responses: Sequence[Dict[str, Any]],
) -> str:
    origin = _origin_value(result).replace("_", " ") or "unknown"
    segments: List[str] = [
        (
            f"This {origin} artifact `{result.name}` (`{result.table_name}`) is treated as customized "
            "and included in feature-grouping analysis."
        )
    ]

    if update_set_count > 0:
        if update_set_name:
            segments.append(
                f"It has {update_set_count} linked update-set signal(s); primary context is `{update_set_name}`."
            )
        else:
            segments.append(f"It has {update_set_count} linked update-set signal(s).")
    else:
        segments.append("No direct update-set artifact links were found for this record.")

    if structural_count > 0:
        segments.append(
            f"Structural analysis found {structural_count} related parent/child signal(s), indicating nearby dependencies."
        )

    if usage_responses:
        usage_parts = []
        for payload in usage_responses:
            usage_parts.append(
                f"{payload.get('table')}: {int(payload.get('count') or 0)} record(s)"
            )
        segments.append(
            "Usage checks within lookback window report " + ", ".join(usage_parts) + "."
        )

    segments.append(
        "Review for intent and business relevance before final grouping/recommendation decisions."
    )
    return " ".join(segments)


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    obs_props = load_observation_properties(session, instance_id=assessment.instance_id)
    batch_size = max(1, int(params.get("batch_size", obs_props.batch_size)))
    include_usage_queries = str(
        params.get("include_usage_queries", obs_props.include_usage_queries) or obs_props.include_usage_queries
    ).strip().lower()
    if include_usage_queries not in {"always", "auto", "never"}:
        include_usage_queries = obs_props.include_usage_queries
    max_results = int(params.get("max_results") or 0)
    resume_from_index = max(0, int(params.get("resume_from_index") or 0))

    rows = session.exec(
        select(ScanResult)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Scan.assessment_id == assessment_id)
        .order_by(ScanResult.id.asc())
    ).all()
    all_customized_results = [row for row in rows if _is_customized(row)]
    if max_results > 0:
        all_customized_results = all_customized_results[:max_results]
    total_customized = len(all_customized_results)
    resume_from_index = min(resume_from_index, total_customized)
    customized_results = all_customized_results[resume_from_index:]

    landscape = _compose_landscape_summary(
        assessment=assessment,
        customized_results=all_customized_results,
    )
    landscape_row = _upsert_landscape_summary(
        session,
        assessment_id=assessment_id,
        summary_text=landscape,
    )
    start_phase_progress(
        session,
        assessment_id,
        "observations",
        total_items=total_customized,
        allow_resume=True,
        checkpoint={"source": "generate_observations_tool"},
        commit=False,
    )

    processed = 0
    usage_queries_executed = 0
    usage_cache_hits = 0
    batch_count = 0

    for batch in _chunked(customized_results, batch_size):
        batch_count += 1
        for result in batch:
            usage_responses: List[Dict[str, Any]] = []
            should_query_usage = include_usage_queries == "always" or (
                include_usage_queries == "auto" and bool(_usage_query_candidates(result))
            )

            if should_query_usage and int(obs_props.max_usage_queries_per_result) > 0:
                candidates = _usage_query_candidates(result)
                for table, query, desc in candidates[: int(obs_props.max_usage_queries_per_result)]:
                    usage_payload = get_usage_count_handle(
                        {
                            "instance_id": assessment.instance_id,
                            "table": table,
                            "query": query,
                            "description": desc,
                            "use_cache": True,
                        },
                        session,
                    )
                    if usage_payload.get("success"):
                        usage_responses.append(usage_payload)
                        usage_queries_executed += 1
                        if usage_payload.get("cached"):
                            usage_cache_hits += 1

            update_set_count, update_set_name = _update_set_context(
                session,
                assessment_id=assessment_id,
                result_id=int(result.id),
            )
            structural_count = _structural_signal_count(session, int(result.id))
            observation_text = _format_observation(
                result=result,
                update_set_count=update_set_count,
                update_set_name=update_set_name,
                structural_count=structural_count,
                usage_responses=usage_responses,
            )

            result.observations = observation_text
            result.ai_observations = json.dumps(
                {
                    "generated_at": datetime.utcnow().isoformat(),
                    "generator": "deterministic_pipeline_v1",
                    "usage_responses": usage_responses,
                    "structural_signal_count": structural_count,
                    "update_set_signal_count": update_set_count,
                },
                sort_keys=True,
            )
            result.review_status = ReviewStatus.pending_review
            result.ai_pass_count = int(result.ai_pass_count or 0) + 1
            session.add(result)
            sync_single_result(session, result, commit=False)
            processed += 1

            absolute_completed = resume_from_index + processed
            checkpoint_phase_progress(
                session,
                assessment_id,
                "observations",
                completed_items=absolute_completed,
                total_items=total_customized,
                last_item_id=int(result.id) if result.id is not None else None,
                status="running",
                checkpoint={"resume_from_index": absolute_completed},
                commit=False,
            )
            session.commit()

    if processed == 0:
        session.commit()

    next_resume_index = resume_from_index + processed
    if next_resume_index >= total_customized:
        complete_phase_progress(
            session,
            assessment_id,
            "observations",
            checkpoint={"completed_items": total_customized, "resume_from_index": total_customized},
            commit=False,
        )
        session.commit()

    return {
        "success": True,
        "assessment_id": assessment_id,
        "total_customized": total_customized,
        "processed_count": processed,
        "batch_size": batch_size,
        "batches_processed": batch_count,
        "include_usage_queries": include_usage_queries,
        "usage_queries_executed": usage_queries_executed,
        "usage_cache_hits": usage_cache_hits,
        "resume_from_index": resume_from_index,
        "next_resume_index": next_resume_index,
        "remaining_customized": max(0, total_customized - next_resume_index),
        "landscape_summary": {
            "recommendation_id": landscape_row.id,
            "category": "landscape_summary",
        },
    }


TOOL_SPEC = ToolSpec(
    name="generate_observations",
    description=(
        "Generate deterministic baseline observations for customized artifacts, "
        "optionally enriched with usage-count checks, and store them on ScanResult."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
