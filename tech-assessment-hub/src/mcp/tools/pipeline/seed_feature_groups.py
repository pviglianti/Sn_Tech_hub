"""MCP tool: seed_feature_groups.

Deterministically seeds feature groups from engine outputs:
- update set overlaps / artifact links
- code references
- structural relationships
- temporal clusters
- naming clusters
- table co-location

Only customized records are persisted as feature members. Non-customized records
are stored as context artifacts when they provide supporting signal evidence.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Set, Tuple

from sqlmodel import Session, select, func

from ...registry import ToolSpec
from ....models import (
    Assessment,
    CodeReference,
    Feature,
    FeatureContextArtifact,
    FeatureScanResult,
    NamingCluster,
    OriginType,
    Scan,
    ScanResult,
    StructuralRelationship,
    TableColocationSummary,
    TemporalCluster,
    UpdateSet,
    UpdateSetArtifactLink,
    UpdateSetOverlap,
)
from ....services.assessment_phase_progress import checkpoint_phase_progress, start_phase_progress
from ....services.relationship_graph import EDGE_WEIGHTS


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to seed feature groups for.",
        },
        "min_group_size": {
            "type": "integer",
            "description": "Minimum customized records required to create a feature.",
            "default": 2,
        },
        "min_edge_weight": {
            "type": "number",
            "description": "Minimum cumulative signal weight required to connect two records.",
            "default": 2.0,
        },
        "reset_existing": {
            "type": "boolean",
            "description": "Clear prior engine/ai memberships and prior seed context before seeding.",
            "default": True,
        },
        "max_pairs_per_signal": {
            "type": "integer",
            "description": "Safety cap on pairwise links generated per signal group.",
            "default": 5000,
        },
        "iteration_number": {
            "type": "integer",
            "description": "Iteration number recorded on seeded memberships/context artifacts.",
            "default": 0,
        },
        "dry_run": {
            "type": "boolean",
            "description": "When true, compute suggested groupings and return them as JSON without writing any records.",
            "default": False,
        },
    },
    "required": ["assessment_id"],
}

_SUGGESTIONS_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to compute suggested groupings for.",
        },
        "min_group_size": {
            "type": "integer",
            "description": "Minimum customized records required to form a suggested group.",
            "default": 2,
        },
        "min_edge_weight": {
            "type": "number",
            "description": "Minimum cumulative signal weight required to connect two records.",
            "default": 2.0,
        },
        "max_pairs_per_signal": {
            "type": "integer",
            "description": "Safety cap on pairwise links generated per signal group.",
            "default": 5000,
        },
    },
    "required": ["assessment_id"],
}


_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}

_AUTO_ASSIGNMENT_SOURCES = {"engine", "ai"}


@dataclass
class _EdgeSupport:
    total_weight: float
    signals: List[Dict[str, Any]]


def _origin_value(result: ScanResult) -> Optional[str]:
    if result.origin_type is None:
        return None
    if hasattr(result.origin_type, "value"):
        return result.origin_type.value
    return str(result.origin_type)


def _is_customized(result: ScanResult) -> bool:
    return (_origin_value(result) or "") in _CUSTOMIZED_ORIGIN_VALUES


def _pair_key(a: int, b: int) -> Tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _safe_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _parse_result_id_list(value: Optional[str]) -> List[int]:
    parsed = _safe_json(value, [])
    if not isinstance(parsed, list):
        return []
    result_ids: List[int] = []
    for item in parsed:
        candidate = item
        if isinstance(item, dict):
            candidate = item.get("scan_result_id") or item.get("result_id") or item.get("id")
        try:
            if candidate is not None:
                result_ids.append(int(candidate))
        except (TypeError, ValueError):
            continue
    return result_ids


def _iter_limited_pairs(member_ids: Iterable[int], max_pairs: int) -> Iterable[Tuple[int, int]]:
    emitted = 0
    deduped = sorted({int(mid) for mid in member_ids if mid is not None})
    for a, b in combinations(deduped, 2):
        yield (a, b)
        emitted += 1
        if emitted >= max_pairs:
            return


def _add_edge(
    edge_support: Dict[Tuple[int, int], _EdgeSupport],
    *,
    a: int,
    b: int,
    signal_type: str,
    weight: float,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if a == b:
        return
    key = _pair_key(a, b)
    support = edge_support.get(key)
    signal_payload = {"type": signal_type, "weight": weight}
    if payload:
        signal_payload.update(payload)
    if support is None:
        edge_support[key] = _EdgeSupport(total_weight=weight, signals=[signal_payload])
        return
    support.total_weight += weight
    support.signals.append(signal_payload)


def _add_context_candidate(
    context_candidates: Dict[int, Dict[Tuple[int, str], Dict[str, Any]]],
    *,
    custom_result_id: int,
    context_result_id: int,
    context_type: str,
    confidence: float,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    by_custom = context_candidates.setdefault(custom_result_id, {})
    key = (context_result_id, context_type)
    existing = by_custom.get(key)
    if existing is None:
        by_custom[key] = {
            "context_result_id": context_result_id,
            "context_type": context_type,
            "confidence_total": float(confidence),
            "count": 1,
            "sources": [payload or {}],
        }
        return
    existing["confidence_total"] += float(confidence)
    existing["count"] += 1
    existing["sources"].append(payload or {})


def _resolve_confidence_level(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _reset_existing_seed_rows(session: Session, assessment_id: int) -> None:
    feature_ids = session.exec(
        select(Feature.id).where(Feature.assessment_id == assessment_id)
    ).all()
    feature_ids = [fid for fid in feature_ids if fid is not None]

    if feature_ids:
        links = session.exec(
            select(FeatureScanResult).where(FeatureScanResult.feature_id.in_(feature_ids))
        ).all()
        for link in links:
            source = (link.assignment_source or "engine").strip().lower()
            if source in _AUTO_ASSIGNMENT_SOURCES:
                session.delete(link)

    contexts = session.exec(
        select(FeatureContextArtifact).where(FeatureContextArtifact.assessment_id == assessment_id)
    ).all()
    for context in contexts:
        session.delete(context)

    seed_features = session.exec(
        select(Feature)
        .where(Feature.assessment_id == assessment_id)
        .where(Feature.name.like("Seed:%"))
    ).all()
    for feature in seed_features:
        remaining_links = int(
            session.exec(
                select(func.count()).where(FeatureScanResult.feature_id == feature.id)
            ).one()
            or 0
        )
        if remaining_links == 0:
            session.delete(feature)

    session.flush()


def _current_human_locked_result_ids(session: Session, assessment_id: int) -> Set[int]:
    rows = session.exec(
        select(FeatureScanResult.scan_result_id)
        .join(Feature, FeatureScanResult.feature_id == Feature.id)
        .where(Feature.assessment_id == assessment_id)
        .where(FeatureScanResult.assignment_source == "human")
    ).all()
    return {int(rid) for rid in rows if rid is not None}


def seed_feature_groups(
    session: Session,
    *,
    assessment_id: int,
    min_group_size: int = 2,
    min_edge_weight: float = 2.0,
    reset_existing: bool = True,
    max_pairs_per_signal: int = 5000,
    iteration_number: int = 0,
    commit: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    scan_ids = session.exec(select(Scan.id).where(Scan.assessment_id == assessment_id)).all()
    if not scan_ids:
        return {
            "success": True,
            "assessment_id": assessment_id,
            "features_created": 0,
            "cluster_count": 0,
            "grouped_count": 0,
            "ungrouped_count": 0,
            "eligible_customized_count": 0,
            "human_locked_count": 0,
            "clusters": [],
        }

    results = session.exec(
        select(ScanResult).where(ScanResult.scan_id.in_(list(scan_ids)))
    ).all()
    result_by_id = {row.id: row for row in results if row.id is not None}

    customized_ids = {rid for rid, row in result_by_id.items() if _is_customized(row)}
    non_customized_ids = set(result_by_id.keys()) - customized_ids
    human_locked_ids = _current_human_locked_result_ids(session, assessment_id)
    eligible_customized_ids = sorted(customized_ids - human_locked_ids)

    if reset_existing and not dry_run:
        _reset_existing_seed_rows(session, assessment_id)

    if not eligible_customized_ids:
        if not dry_run and commit:
            session.commit()
        return {
            "success": True,
            "dry_run": dry_run,
            "assessment_id": assessment_id,
            "features_created": 0,
            "cluster_count": 0,
            "grouped_count": 0,
            "ungrouped_count": 0,
            "eligible_customized_count": 0,
            "human_locked_count": len(human_locked_ids),
            "clusters": [],
            **({"suggested_groups": []} if dry_run else {}),
        }

    eligible_set = set(eligible_customized_ids)
    edge_support: Dict[Tuple[int, int], _EdgeSupport] = {}
    context_candidates: Dict[int, Dict[Tuple[int, str], Dict[str, Any]]] = {}
    naming_hints: DefaultDict[int, Counter] = defaultdict(Counter)
    update_set_ids_by_result: DefaultDict[int, Set[int]] = defaultdict(set)
    update_set_custom_members: DefaultDict[int, Set[int]] = defaultdict(set)
    update_set_context_members: DefaultDict[int, Set[int]] = defaultdict(set)
    update_set_name_by_id: Dict[int, str] = {}

    # Update-set artifact links (direct provenance)
    us_links = session.exec(
        select(UpdateSetArtifactLink)
        .where(UpdateSetArtifactLink.assessment_id == assessment_id)
    ).all()
    for link in us_links:
        us_id = int(link.update_set_id)
        result_id = int(link.scan_result_id)
        if result_id in eligible_set:
            update_set_custom_members[us_id].add(result_id)
            update_set_ids_by_result[result_id].add(us_id)
        elif result_id in non_customized_ids:
            update_set_context_members[us_id].add(result_id)

    if update_set_custom_members:
        update_sets = session.exec(
            select(UpdateSet).where(UpdateSet.id.in_(list(update_set_custom_members.keys())))
        ).all()
        for update_set in update_sets:
            if update_set.id is not None:
                update_set_name_by_id[update_set.id] = update_set.name

    for us_id, member_ids in update_set_custom_members.items():
        for a, b in _iter_limited_pairs(member_ids, max_pairs_per_signal):
            _add_edge(
                edge_support,
                a=a,
                b=b,
                signal_type="update_set_artifact_link",
                weight=EDGE_WEIGHTS["update_set_artifact_link"],
                payload={"update_set_id": us_id},
            )
        context_ids = sorted(update_set_context_members.get(us_id, set()))
        for custom_id in sorted(member_ids):
            for context_id in context_ids[:20]:
                _add_context_candidate(
                    context_candidates,
                    custom_result_id=custom_id,
                    context_result_id=context_id,
                    context_type="update_set_neighbor",
                    confidence=0.55,
                    payload={"update_set_id": us_id},
                )

    # Update-set overlaps (cross-update-set group cohesion)
    overlaps = session.exec(
        select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == assessment_id)
    ).all()
    for overlap in overlaps:
        member_ids = _parse_result_id_list(overlap.shared_records_json)
        if not member_ids:
            member_ids = sorted(
                update_set_custom_members.get(int(overlap.update_set_a_id), set())
                | update_set_custom_members.get(int(overlap.update_set_b_id), set())
            )
        custom_members = [rid for rid in member_ids if rid in eligible_set]
        context_members = [rid for rid in member_ids if rid in non_customized_ids]
        for a, b in _iter_limited_pairs(custom_members, max_pairs_per_signal):
            _add_edge(
                edge_support,
                a=a,
                b=b,
                signal_type="update_set_overlap",
                weight=EDGE_WEIGHTS["update_set_overlap"],
                payload={
                    "overlap_id": overlap.id,
                    "signal_type": overlap.signal_type,
                    "update_set_a_id": overlap.update_set_a_id,
                    "update_set_b_id": overlap.update_set_b_id,
                },
            )
        if context_members:
            context_confidence = max(0.0, min(1.0, float(overlap.overlap_score)))
            for custom_id in custom_members:
                for context_id in context_members[:20]:
                    _add_context_candidate(
                        context_candidates,
                        custom_result_id=custom_id,
                        context_result_id=context_id,
                        context_type="update_set_overlap_context",
                        confidence=context_confidence,
                        payload={"overlap_id": overlap.id},
                    )

    # Temporal clusters
    temporal_clusters = session.exec(
        select(TemporalCluster).where(TemporalCluster.assessment_id == assessment_id)
    ).all()
    for cluster in temporal_clusters:
        member_ids = _parse_result_id_list(cluster.record_ids_json)
        custom_members = [rid for rid in member_ids if rid in eligible_set]
        context_members = [rid for rid in member_ids if rid in non_customized_ids]
        for a, b in _iter_limited_pairs(custom_members, max_pairs_per_signal):
            _add_edge(
                edge_support,
                a=a,
                b=b,
                signal_type="temporal_cluster",
                weight=EDGE_WEIGHTS["temporal_cluster"],
                payload={"cluster_id": cluster.id, "developer": cluster.developer},
            )
        for custom_id in custom_members:
            for context_id in context_members[:20]:
                _add_context_candidate(
                    context_candidates,
                    custom_result_id=custom_id,
                    context_result_id=context_id,
                    context_type="temporal_neighbor",
                    confidence=0.6,
                    payload={"cluster_id": cluster.id},
                )

    # Naming clusters
    naming_clusters = session.exec(
        select(NamingCluster).where(NamingCluster.assessment_id == assessment_id)
    ).all()
    for cluster in naming_clusters:
        member_ids = _parse_result_id_list(cluster.member_ids_json)
        custom_members = [rid for rid in member_ids if rid in eligible_set]
        context_members = [rid for rid in member_ids if rid in non_customized_ids]
        for custom_id in custom_members:
            naming_hints[custom_id][cluster.cluster_label] += 1
        for a, b in _iter_limited_pairs(custom_members, max_pairs_per_signal):
            _add_edge(
                edge_support,
                a=a,
                b=b,
                signal_type="naming_cluster",
                weight=EDGE_WEIGHTS["naming_cluster"],
                payload={"cluster_id": cluster.id, "label": cluster.cluster_label},
            )
        for custom_id in custom_members:
            for context_id in context_members[:20]:
                _add_context_candidate(
                    context_candidates,
                    custom_result_id=custom_id,
                    context_result_id=context_id,
                    context_type="naming_neighbor",
                    confidence=max(0.0, min(1.0, float(cluster.confidence))),
                    payload={"cluster_id": cluster.id},
                )

    # Table co-location summaries
    colocation_rows = session.exec(
        select(TableColocationSummary).where(TableColocationSummary.assessment_id == assessment_id)
    ).all()
    for summary in colocation_rows:
        member_ids = _parse_result_id_list(summary.record_ids_json)
        custom_members = [rid for rid in member_ids if rid in eligible_set]
        context_members = [rid for rid in member_ids if rid in non_customized_ids]
        for a, b in _iter_limited_pairs(custom_members, max_pairs_per_signal):
            _add_edge(
                edge_support,
                a=a,
                b=b,
                signal_type="table_colocation",
                weight=EDGE_WEIGHTS["table_colocation"],
                payload={"summary_id": summary.id, "target_table": summary.target_table},
            )
        for custom_id in custom_members:
            for context_id in context_members[:20]:
                _add_context_candidate(
                    context_candidates,
                    custom_result_id=custom_id,
                    context_result_id=context_id,
                    context_type="table_colocation_neighbor",
                    confidence=0.55,
                    payload={"summary_id": summary.id, "target_table": summary.target_table},
                )

    # Code references
    code_refs = session.exec(
        select(CodeReference).where(CodeReference.assessment_id == assessment_id)
    ).all()
    for ref in code_refs:
        source_id = int(ref.source_scan_result_id)
        target_id = int(ref.target_scan_result_id) if ref.target_scan_result_id else None
        if not target_id:
            continue
        if source_id in eligible_set and target_id in eligible_set:
            _add_edge(
                edge_support,
                a=source_id,
                b=target_id,
                signal_type="code_reference",
                weight=EDGE_WEIGHTS["code_reference"],
                payload={"code_reference_id": ref.id, "reference_type": ref.reference_type},
            )
        elif source_id in eligible_set and target_id in non_customized_ids:
            _add_context_candidate(
                context_candidates,
                custom_result_id=source_id,
                context_result_id=target_id,
                context_type="code_reference_target",
                confidence=max(0.0, min(1.0, float(ref.confidence))),
                payload={"code_reference_id": ref.id, "reference_type": ref.reference_type},
            )
        elif target_id in eligible_set and source_id in non_customized_ids:
            _add_context_candidate(
                context_candidates,
                custom_result_id=target_id,
                context_result_id=source_id,
                context_type="code_reference_source",
                confidence=max(0.0, min(1.0, float(ref.confidence))),
                payload={"code_reference_id": ref.id, "reference_type": ref.reference_type},
            )

    # Structural relationships
    structural_rows = session.exec(
        select(StructuralRelationship).where(StructuralRelationship.assessment_id == assessment_id)
    ).all()
    for rel in structural_rows:
        parent_id = int(rel.parent_scan_result_id)
        child_id = int(rel.child_scan_result_id)
        if parent_id in eligible_set and child_id in eligible_set:
            _add_edge(
                edge_support,
                a=parent_id,
                b=child_id,
                signal_type="structural_relationship",
                weight=EDGE_WEIGHTS["structural_relationship"],
                payload={"relationship_id": rel.id, "relationship_type": rel.relationship_type},
            )
        elif parent_id in eligible_set and child_id in non_customized_ids:
            _add_context_candidate(
                context_candidates,
                custom_result_id=parent_id,
                context_result_id=child_id,
                context_type="structural_child_context",
                confidence=max(0.0, min(1.0, float(rel.confidence))),
                payload={"relationship_id": rel.id, "relationship_type": rel.relationship_type},
            )
        elif child_id in eligible_set and parent_id in non_customized_ids:
            _add_context_candidate(
                context_candidates,
                custom_result_id=child_id,
                context_result_id=parent_id,
                context_type="structural_parent_context",
                confidence=max(0.0, min(1.0, float(rel.confidence))),
                payload={"relationship_id": rel.id, "relationship_type": rel.relationship_type},
            )

    # Build adjacency graph from weighted edges.
    adjacency: DefaultDict[int, Set[int]] = defaultdict(set)
    for (a, b), support in edge_support.items():
        if support.total_weight < min_edge_weight:
            continue
        if a not in eligible_set or b not in eligible_set:
            continue
        adjacency[a].add(b)
        adjacency[b].add(a)

    visited: Set[int] = set()
    components: List[List[int]] = []
    for result_id in eligible_customized_ids:
        if result_id in visited:
            continue
        visited.add(result_id)
        if result_id not in adjacency:
            continue
        queue = deque([result_id])
        component: List[int] = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        if len(component) >= max(1, int(min_group_size)):
            components.append(sorted(component))

    components.sort(key=lambda c: (-len(c), min(c)))

    used_names: Counter = Counter()
    grouped_customized_ids: Set[int] = set()
    cluster_payloads: List[Dict[str, Any]] = []
    suggested_groups: List[Dict[str, Any]] = []
    features_created = 0
    context_rows_created = 0

    for component in components:
        component_set = set(component)
        grouped_customized_ids.update(component_set)

        update_counter: Counter = Counter()
        table_counter: Counter = Counter()
        developer_counter: Counter = Counter()
        naming_counter: Counter = Counter()
        dates: List[datetime] = []

        for result_id in component:
            row = result_by_id[result_id]
            for us_id in update_set_ids_by_result.get(result_id, set()):
                update_counter[us_id] += 1
            table_counter[row.table_name or "unknown"] += 1
            if row.sys_created_by:
                developer_counter[row.sys_created_by] += 1
            naming_counter.update(naming_hints.get(result_id, Counter()))
            if row.sys_updated_on:
                dates.append(row.sys_updated_on)

        primary_update_set_id = update_counter.most_common(1)[0][0] if update_counter else None
        primary_table = table_counter.most_common(1)[0][0] if table_counter else None
        primary_developer = developer_counter.most_common(1)[0][0] if developer_counter else None

        if primary_update_set_id and primary_update_set_id in update_set_name_by_id:
            base_name = f"Seed: {update_set_name_by_id[primary_update_set_id]}"
        elif naming_counter:
            base_name = f"Seed: {naming_counter.most_common(1)[0][0]}"
        else:
            base_name = f"Seed: {primary_table or 'Customization Cluster'}"
        used_names[base_name] += 1
        if used_names[base_name] > 1:
            feature_name = f"{base_name} ({used_names[base_name]})"
        else:
            feature_name = base_name

        in_component_edges: List[_EdgeSupport] = []
        signal_counts: Counter = Counter()
        for a, b in combinations(component, 2):
            support = edge_support.get(_pair_key(a, b))
            if not support:
                continue
            in_component_edges.append(support)
            for signal in support.signals:
                signal_counts[signal.get("type") or "unknown"] += 1

        if in_component_edges:
            avg_weight = sum(edge.total_weight for edge in in_component_edges) / len(in_component_edges)
            cluster_confidence = max(0.0, min(1.0, avg_weight / 5.0))
        else:
            cluster_confidence = 0.5

        # --- dry_run: build suggestion payload only, no DB writes ---
        if dry_run:
            member_details: List[Dict[str, Any]] = []
            for member_id in component:
                row = result_by_id[member_id]
                member_details.append({
                    "scan_result_id": member_id,
                    "name": row.name,
                    "table_name": row.table_name,
                })
            context_detail: List[Dict[str, Any]] = []
            for member_id in component:
                for (ctx_rid, ctx_type), candidate in context_candidates.get(member_id, {}).items():
                    if ctx_rid not in non_customized_ids:
                        continue
                    ctx_row = result_by_id.get(ctx_rid)
                    context_detail.append({
                        "scan_result_id": ctx_rid,
                        "context_type": ctx_type,
                        "name": ctx_row.name if ctx_row else None,
                    })
            suggested_groups.append({
                "suggested_feature_name": feature_name,
                "member_count": len(component),
                "member_result_ids": sorted(component),
                "members": member_details,
                "signal_counts": dict(signal_counts),
                "confidence_score": round(cluster_confidence, 3),
                "primary_update_set_id": primary_update_set_id,
                "primary_table": primary_table,
                "primary_developer": primary_developer,
                "context_artifacts": context_detail[:20],
            })
            continue

        # --- write path: persist Feature + FeatureScanResult + FeatureContextArtifact ---
        feature = Feature(
            assessment_id=assessment_id,
            name=feature_name,
            description=(
                f"Deterministic seed cluster with {len(component)} customized records "
                f"from engine signals: {', '.join(sorted(signal_counts.keys())) or 'none'}."
            ),
            primary_update_set_id=primary_update_set_id,
            ai_summary=None,
            confidence_score=round(cluster_confidence, 3),
            confidence_level=_resolve_confidence_level(cluster_confidence),
            signals_json=json.dumps(
                {
                    "seed_tool": "seed_feature_groups",
                    "signal_counts": dict(signal_counts),
                    "min_edge_weight": float(min_edge_weight),
                },
                sort_keys=True,
            ),
            primary_table=primary_table,
            primary_developer=primary_developer,
            date_range_start=min(dates) if dates else None,
            date_range_end=max(dates) if dates else None,
            pass_number=iteration_number,
        )
        session.add(feature)
        session.flush()
        features_created += 1

        for member_id in component:
            member_row = result_by_id.get(member_id)
            if member_row and not _is_customized(member_row):
                continue
            neighbor_rows = []
            member_signal_counts: Counter = Counter()
            weighted_neighbor_count = 0
            for neighbor_id in component:
                if neighbor_id == member_id:
                    continue
                support = edge_support.get(_pair_key(member_id, neighbor_id))
                if not support:
                    continue
                neighbor_rows.append((neighbor_id, support.total_weight))
                if support.total_weight >= min_edge_weight:
                    weighted_neighbor_count += 1
                for signal in support.signals:
                    member_signal_counts[signal.get("type") or "unknown"] += 1
            member_degree = weighted_neighbor_count / max(1, len(component) - 1)
            member_confidence = max(0.0, min(1.0, (cluster_confidence * 0.6) + (member_degree * 0.4)))
            member_evidence = {
                "seed_feature_groups": {
                    "member_signal_counts": dict(member_signal_counts),
                    "weighted_neighbor_count": weighted_neighbor_count,
                    "min_edge_weight": float(min_edge_weight),
                    "top_neighbor_weights": sorted(neighbor_rows, key=lambda row: -row[1])[:5],
                }
            }
            session.add(
                FeatureScanResult(
                    feature_id=feature.id,
                    scan_result_id=member_id,
                    is_primary=True,
                    membership_type="primary",
                    assignment_source="engine",
                    assignment_confidence=round(member_confidence, 3),
                    evidence_json=json.dumps(member_evidence, sort_keys=True),
                    iteration_number=iteration_number,
                )
            )

        # Add non-customized context rows gathered from component members.
        context_rollup: Dict[Tuple[int, str], Dict[str, Any]] = {}
        for member_id in component:
            for (context_result_id, context_type), candidate in context_candidates.get(member_id, {}).items():
                key = (context_result_id, context_type)
                existing = context_rollup.get(key)
                if existing is None:
                    context_rollup[key] = {
                        "confidence_total": float(candidate["confidence_total"]),
                        "count": int(candidate["count"]),
                        "supporting_member_ids": {member_id},
                        "sources": list(candidate["sources"]),
                    }
                else:
                    existing["confidence_total"] += float(candidate["confidence_total"])
                    existing["count"] += int(candidate["count"])
                    existing["supporting_member_ids"].add(member_id)
                    existing["sources"].extend(candidate["sources"])

        for (context_result_id, context_type), rolled in sorted(context_rollup.items()):
            if context_result_id not in non_customized_ids:
                continue
            average_conf = rolled["confidence_total"] / max(1, rolled["count"])
            evidence = {
                "seed_feature_groups": {
                    "supporting_member_ids": sorted(rolled["supporting_member_ids"]),
                    "source_count": rolled["count"],
                    "sources": rolled["sources"][:10],
                }
            }
            session.add(
                FeatureContextArtifact(
                    instance_id=assessment.instance_id,
                    assessment_id=assessment_id,
                    feature_id=feature.id,
                    scan_result_id=context_result_id,
                    context_type=context_type,
                    confidence=round(max(0.0, min(1.0, average_conf)), 3),
                    evidence_json=json.dumps(evidence, sort_keys=True),
                    iteration_number=iteration_number,
                )
            )
            context_rows_created += 1

        cluster_payloads.append(
            {
                "feature_id": feature.id,
                "feature_name": feature.name,
                "member_count": len(component),
                "signal_counts": dict(signal_counts),
                "confidence_score": round(cluster_confidence, 3),
                "primary_update_set_id": primary_update_set_id,
            }
        )

    ungrouped_ids = sorted(set(eligible_customized_ids) - grouped_customized_ids)
    summary: Dict[str, Any] = {
        "success": True,
        "dry_run": dry_run,
        "assessment_id": assessment_id,
        "features_created": features_created,
        "cluster_count": len(components),
        "grouped_count": len(grouped_customized_ids),
        "ungrouped_count": len(ungrouped_ids),
        "ungrouped_result_ids": ungrouped_ids,
        "eligible_customized_count": len(eligible_customized_ids),
        "human_locked_count": len(human_locked_ids),
        "context_rows_created": context_rows_created,
        "clusters": cluster_payloads,
    }

    if dry_run:
        summary["suggested_groups"] = suggested_groups
    else:
        if commit:
            session.commit()
        else:
            session.flush()

    return summary


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    min_group_size = int(params.get("min_group_size", 2))
    min_edge_weight = float(params.get("min_edge_weight", 2.0))
    reset_existing = bool(params.get("reset_existing", True))
    max_pairs_per_signal = int(params.get("max_pairs_per_signal", 5000))
    iteration_number = int(params.get("iteration_number", 0))
    dry_run = bool(params.get("dry_run", False))

    if not dry_run:
        start_phase_progress(
            session,
            assessment_id,
            "grouping",
            total_items=0,
            allow_resume=True,
            checkpoint={"source": "seed_feature_groups_tool", "iteration_number": max(0, iteration_number)},
            commit=False,
        )

    try:
        result = seed_feature_groups(
            session,
            assessment_id=assessment_id,
            min_group_size=max(1, min_group_size),
            min_edge_weight=max(0.0, min_edge_weight),
            reset_existing=reset_existing,
            max_pairs_per_signal=max(100, max_pairs_per_signal),
            iteration_number=max(0, iteration_number),
            commit=not dry_run,
            dry_run=dry_run,
        )
    except Exception as exc:
        if not dry_run:
            checkpoint_phase_progress(
                session,
                assessment_id,
                "grouping",
                status="failed",
                checkpoint={"error": str(exc)},
                error=str(exc),
                commit=True,
            )
        raise

    if not dry_run:
        grouped_count = int(result.get("grouped_count") or 0)
        eligible_count = int(result.get("eligible_customized_count") or grouped_count)
        checkpoint_phase_progress(
            session,
            assessment_id,
            "grouping",
            total_items=max(0, eligible_count),
            completed_items=max(0, grouped_count),
            status="completed",
            checkpoint={
                "features_created": int(result.get("features_created") or 0),
                "grouped_count": grouped_count,
                "eligible_customized_count": eligible_count,
                "resume_from_index": max(0, grouped_count),
            },
            commit=True,
        )
    return result


def handle_suggestions(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    """Read-only handler: returns suggested groupings without writing anything."""
    assessment_id = int(params["assessment_id"])
    return seed_feature_groups(
        session,
        assessment_id=assessment_id,
        min_group_size=max(1, int(params.get("min_group_size", 2))),
        min_edge_weight=max(0.0, float(params.get("min_edge_weight", 2.0))),
        max_pairs_per_signal=max(100, int(params.get("max_pairs_per_signal", 5000))),
        reset_existing=False,
        commit=False,
        dry_run=True,
    )


TOOL_SPEC = ToolSpec(
    name="seed_feature_groups",
    description=(
        "Deterministically seed feature groups using engine outputs "
        "(update set overlap, code refs, structural links, temporal/naming/table clusters). "
        "Only customized records are persisted as members; non-customized records are kept as context evidence. "
        "Pass dry_run=true to compute suggestions without writing."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)

SUGGESTIONS_TOOL_SPEC = ToolSpec(
    name="get_suggested_groupings",
    description=(
        "Read-only tool: compute deterministic feature grouping suggestions from engine outputs "
        "without writing any Feature, FeatureScanResult, or FeatureContextArtifact records. "
        "Returns suggested group names, member lists, signal counts, and confidence scores."
    ),
    input_schema=_SUGGESTIONS_INPUT_SCHEMA,
    handler=handle_suggestions,
    permission="read",
)
