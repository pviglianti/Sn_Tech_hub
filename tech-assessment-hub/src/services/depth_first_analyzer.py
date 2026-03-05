"""Depth-first relationship-driven analysis service.

When analyzing a customized artifact, if we discover it references another
customization in the assessment, we immediately analyze that one next -- following
the "rabbit hole" of related customizations. Non-customized related items provide
context (what something does/touches) but only customizations matter for
observations and feature grouping.

Features are progressively created/extended as relationships are discovered.
Feature names and descriptions evolve as more members are uncovered.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from ..models import (
    Feature,
    FeatureContextArtifact,
    FeatureScanResult,
    ScanResult,
)
from .assessment_phase_progress import checkpoint_phase_progress, start_phase_progress, complete_phase_progress
from .customization_sync import sync_single_result
from .relationship_graph import RelationshipGraph, EDGE_WEIGHTS

logger = logging.getLogger(__name__)


@dataclass
class DFSAnalysisResult:
    """Result summary from a depth-first analysis run."""
    analyzed: int = 0
    features_created: int = 0
    features_updated: int = 0
    total_customized: int = 0
    analysis_order: List[int] = field(default_factory=list)


def run_depth_first_analysis(
    session: Session,
    assessment_id: int,
    instance_id: int,
    graph: RelationshipGraph,
    *,
    max_rabbit_hole_depth: int = 10,
    max_neighbors_per_hop: int = 20,
    min_edge_weight: float = 2.0,
    context_enrichment: str = "auto",
    use_registered_prompts: bool = False,
    checkpoint_callback: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None,
) -> DFSAnalysisResult:
    """Run depth-first analysis on all customized artifacts.

    Algorithm:
    1. Build ordered work queue of all customized artifact IDs
    2. For each unvisited item in queue:
       a. Analyze the artifact (gather context, write observations)
       b. Progressive grouping: find/create/extend features
       c. Follow the rabbit hole: recurse into unvisited customized neighbors
    3. Checkpoint after each artifact for resume support

    Args:
        session: DB session
        assessment_id: Assessment being analyzed
        instance_id: ServiceNow instance ID
        graph: Pre-built relationship graph from engine outputs
        max_rabbit_hole_depth: Max DFS depth from any seed artifact
        max_neighbors_per_hop: Max customized neighbors to follow per artifact
        min_edge_weight: Minimum edge weight to follow
        context_enrichment: "auto", "always", "never"
        use_registered_prompts: Whether to call MCP prompts
        checkpoint_callback: Called after each artifact for progress tracking
        progress_callback: Called to update UI progress
    """
    result = DFSAnalysisResult(total_customized=len(graph.customized_ids))

    visited: Set[int] = set()
    feature_map: Dict[int, int] = {}  # sr_id -> feature_id (in-memory cache)

    # Resume support: check for existing checkpoint
    phase_progress = start_phase_progress(
        session,
        assessment_id,
        "ai_analysis",
        total_items=result.total_customized,
        allow_resume=True,
        checkpoint={"mode": "depth_first", "total_customized": result.total_customized},
        commit=False,
    )

    # Rebuild visited set from checkpoint
    checkpoint_data = {}
    if phase_progress.checkpoint_json:
        try:
            checkpoint_data = json.loads(phase_progress.checkpoint_json)
        except Exception:
            checkpoint_data = {}

    visited_ids_from_checkpoint = checkpoint_data.get("visited_ids", [])
    if visited_ids_from_checkpoint:
        visited = set(visited_ids_from_checkpoint)
        # Rebuild feature_map from DB
        for sr_id in visited:
            fsr = session.exec(
                select(FeatureScanResult).where(FeatureScanResult.scan_result_id == sr_id)
            ).first()
            if fsr:
                feature_map[sr_id] = fsr.feature_id
        result.analyzed = len(visited)
        logger.info(f"DFS resumed: {len(visited)} artifacts already analyzed")

    # Ordered work queue -- all customized IDs sorted by PK
    work_queue = sorted(graph.customized_ids)

    if result.total_customized == 0:
        complete_phase_progress(
            session, assessment_id, "ai_analysis",
            checkpoint={"mode": "depth_first", "completed_items": 0},
            commit=False,
        )
        return result

    if len(visited) >= result.total_customized:
        complete_phase_progress(
            session, assessment_id, "ai_analysis",
            checkpoint={"mode": "depth_first", "completed_items": result.total_customized},
            commit=False,
        )
        return result

    def _dfs_analyze(sr_id: int, depth: int) -> None:
        """Recursive DFS: analyze this artifact, then follow customized neighbors."""
        if sr_id in visited or depth > max_rabbit_hole_depth:
            return

        visited.add(sr_id)
        result.analysis_order.append(sr_id)

        sr = session.get(ScanResult, sr_id)
        if not sr:
            return

        # 1. Gather context -- both customized AND non-customized related items
        #    Non-customized items = CONTEXT (what this thing does/touches)
        #    Customized items = WORK (analyze them, group them)
        from .contextual_lookup import gather_artifact_context
        ctx = gather_artifact_context(session, instance_id, sr_id, context_enrichment)

        # Enrich with cross-reference data from the relationship graph
        all_neighbors = graph.neighbors(sr_id, min_weight=0.0)
        customized_neighbors = graph.customized_neighbors(sr_id, min_weight=0.0)

        related_customizations = []
        for nid in customized_neighbors:
            n_sr = session.get(ScanResult, nid)
            if n_sr:
                edge_types = graph.edge_types(sr_id, nid)
                related_customizations.append({
                    "id": nid,
                    "name": n_sr.name,
                    "table": n_sr.table_name,
                    "relationship_types": edge_types,
                    "weight": graph.edge_weight(sr_id, nid),
                    "already_analyzed": nid in visited,
                })

        cross_ref_summary = {
            "total_neighbors": len(all_neighbors),
            "total_related_customizations": len(customized_neighbors),
            "analyzed_customizations": sum(1 for n in customized_neighbors if n in visited),
            "unanalyzed_customizations": sum(1 for n in customized_neighbors if n not in visited),
        }

        # 2. Build analysis result JSON -> write to sr.ai_observations
        artifact_info = ctx.get("artifact") or {}
        references = ctx.get("references") or []
        human_ctx = ctx.get("human_context") or {}

        analysis_result = {
            "artifact_name": artifact_info.get("name") or sr.name,
            "artifact_table": artifact_info.get("table_name") or sr.table_name,
            "analysis_mode": "depth_first",
            "dfs_depth": depth,
            "context_enrichment_mode": context_enrichment,
            "references_found": sum(1 for r in references if r.get("resolved")),
            "has_local_data": ctx.get("has_local_table_data", False),
            "update_sets_count": len(ctx.get("update_sets") or []),
            "related_customizations": related_customizations,
            "cross_reference_summary": cross_ref_summary,
        }

        sr.ai_observations = json.dumps(analysis_result, sort_keys=True)

        # 3. Write human-visible observations
        #    Note relationships: non-customized items as context,
        #    customized items as flagged related customizations
        obs_parts = []
        obs_parts.append(f"{sr.name} ({sr.table_name})")

        us_info = ctx.get("update_sets") or []
        if us_info:
            us_names = [u.get("name", "?") for u in us_info[:3]]
            obs_parts.append(f"Update sets: {', '.join(us_names)}")

        if related_customizations:
            custom_refs = [
                f"{rc['name']} ({', '.join(rc['relationship_types'][:2])})"
                for rc in related_customizations[:5]
            ]
            obs_parts.append(f"Related customizations: {'; '.join(custom_refs)}")

        sr.observations = " | ".join(obs_parts)
        session.add(sr)
        sync_single_result(session, sr, commit=False)

        # 4. Progressive grouping: find/create/extend feature
        _progressive_group(session, assessment_id, sr, graph, visited, feature_map, result)

        # 5. Back-propagate: update previously-analyzed members' observations
        #    to note new relationship discovered
        feature_id = feature_map.get(sr_id)
        if feature_id:
            # Find other members of same feature that were already analyzed
            other_members = [
                sid for sid, fid in feature_map.items()
                if fid == feature_id and sid != sr_id and sid in visited
            ]
            for other_id in other_members[:5]:  # Cap back-propagation
                other_sr = session.get(ScanResult, other_id)
                if other_sr and other_sr.observations:
                    feat = session.get(Feature, feature_id)
                    feat_name = feat.name if feat else "Unknown"
                    # Only append if not already mentioned
                    mention = f"[Grouped: {feat_name}]"
                    if mention not in (other_sr.observations or ""):
                        other_sr.observations = f"{other_sr.observations} | {mention}"
                        session.add(other_sr)
                        sync_single_result(session, other_sr, commit=False)

        # 6. Checkpoint + commit after each artifact
        result.analyzed = len(visited)

        checkpoint_phase_progress(
            session,
            assessment_id,
            "ai_analysis",
            completed_items=len(visited),
            last_item_id=sr_id,
            status="running",
            checkpoint={
                "mode": "depth_first",
                "visited_ids": sorted(visited),
                "features_created": result.features_created,
                "total_customized": result.total_customized,
            },
            commit=False,
        )
        session.commit()

        if progress_callback:
            pct = 15 + int(len(visited) / max(result.total_customized, 1) * 80)
            progress_callback(pct, f"Analyzed {len(visited)}/{result.total_customized}: {sr.name}")

        if checkpoint_callback:
            checkpoint_callback(sr_id, len(visited), result.total_customized)

        # 7. Follow the rabbit hole: recurse into unvisited customized neighbors
        #    Sort by edge weight (strongest first), cap at max_neighbors_per_hop
        unvisited_customs = [
            (nid, graph.edge_weight(sr_id, nid))
            for nid in customized_neighbors
            if nid not in visited
        ]
        unvisited_customs.sort(key=lambda x: -x[1])  # strongest first

        for nid, weight in unvisited_customs[:max_neighbors_per_hop]:
            if weight < min_edge_weight:
                continue
            _dfs_analyze(nid, depth + 1)

    # Main loop: iterate work queue, DFS into each unvisited seed
    for seed_id in work_queue:
        if seed_id in visited:
            continue
        _dfs_analyze(seed_id, depth=0)

    # Mark complete
    complete_phase_progress(
        session,
        assessment_id,
        "ai_analysis",
        checkpoint={
            "mode": "depth_first",
            "completed_items": result.analyzed,
            "features_created": result.features_created,
            "visited_ids": sorted(visited),
        },
        commit=False,
    )
    session.commit()

    return result


def _progressive_group(
    session: Session,
    assessment_id: int,
    sr: ScanResult,
    graph: RelationshipGraph,
    visited: Set[int],
    feature_map: Dict[int, int],
    result: DFSAnalysisResult,
) -> None:
    """Find, create, or extend a feature for this artifact.

    Rules:
    1. If sr already belongs to a feature (from previous run) -> skip creation,
       potentially update feature description
    2. Look at visited neighbors that belong to features -> join strongest-edge feature
    3. If no neighbor has a feature but sr has strong edges -> create new feature
    4. Otherwise -> leave ungrouped (grouping stage handles later)
    """
    sr_id = sr.id
    if sr_id is None:
        return
    sr_id = int(sr_id)

    # Already in a feature?
    if sr_id in feature_map:
        _maybe_update_feature_description(session, feature_map[sr_id], sr, feature_map)
        return

    # Check DB for pre-existing membership (from human/previous run)
    existing_fsr = session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == sr_id)
    ).first()
    if existing_fsr:
        feature_map[sr_id] = existing_fsr.feature_id
        _maybe_update_feature_description(session, existing_fsr.feature_id, sr, feature_map)
        return

    # Look at neighbors that already have features
    customized_neighbors = graph.customized_neighbors(sr_id, min_weight=0.0)
    best_feature_id = None
    best_weight = 0.0

    for nid in customized_neighbors:
        if nid in feature_map:
            w = graph.edge_weight(sr_id, nid)
            if w > best_weight:
                best_weight = w
                best_feature_id = feature_map[nid]

    if best_feature_id is not None:
        # Join the existing feature
        _add_to_feature(session, best_feature_id, sr_id, best_weight)
        feature_map[sr_id] = best_feature_id
        _maybe_update_feature_description(session, best_feature_id, sr, feature_map)
        result.features_updated += 1
        return

    # No neighbor has a feature -- check if we have strong enough edges to create one
    # Look at ALL customized neighbors (even unvisited) for potential grouping
    strong_neighbors = [
        nid for nid in customized_neighbors
        if graph.edge_weight(sr_id, nid) >= EDGE_WEIGHTS.get("table_colocation", 1.0)
    ]

    if strong_neighbors:
        # Create a new feature
        feature = Feature(
            assessment_id=assessment_id,
            name=f"Cluster: {sr.name}",
            description=f"Customizations related to {sr.name} ({sr.table_name})",
        )
        session.add(feature)
        session.flush()  # Get the feature ID

        # Add this artifact as primary member
        _add_to_feature(session, feature.id, sr_id, 1.0)
        feature_map[sr_id] = feature.id
        result.features_created += 1

        # Add any already-visited strong neighbors that don't have a feature yet
        for nid in strong_neighbors:
            if nid in visited and nid not in feature_map:
                _add_to_feature(session, feature.id, nid, graph.edge_weight(sr_id, nid))
                feature_map[nid] = feature.id

        return

    # No strong neighbors -- leave ungrouped for now


def _add_to_feature(session: Session, feature_id: int, sr_id: int, confidence: float) -> None:
    """Add a scan result to a feature with DFS assignment source."""
    # Check if already a member
    existing = session.exec(
        select(FeatureScanResult)
        .where(FeatureScanResult.feature_id == feature_id)
        .where(FeatureScanResult.scan_result_id == sr_id)
    ).first()
    if existing:
        return

    fsr = FeatureScanResult(
        feature_id=feature_id,
        scan_result_id=sr_id,
        is_primary=True,
        membership_type="primary",
        assignment_source="ai",
        assignment_confidence=min(confidence / 3.0, 1.0),  # Normalize to 0-1
    )
    session.add(fsr)


def _maybe_update_feature_description(
    session: Session,
    feature_id: int,
    new_member_sr: ScanResult,
    feature_map: Dict[int, int],
) -> None:
    """Update a feature's description as new members are discovered."""
    feature = session.get(Feature, feature_id)
    if not feature:
        return

    member_count = sum(1 for fid in feature_map.values() if fid == feature_id)

    if member_count <= 1:
        feature.description = (
            f"Customizations related to {new_member_sr.name} ({new_member_sr.table_name})"
        )
    else:
        tables = set()
        for sid, fid in feature_map.items():
            if fid == feature_id:
                sr = session.get(ScanResult, sid)
                if sr:
                    tables.add(sr.table_name or "unknown")

        table_str = ", ".join(sorted(tables)[:4])
        feature.description = (
            f"{member_count} artifacts spanning {table_str}"
        )

    session.add(feature)
