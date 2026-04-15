"""MCP tool: get_grouping_signals — surface engine output for feature grouping.

The dependency-mapper engine is the most reliable signal source. Other engines
(temporal_cluster, naming_cluster) are weaker. This tool returns all of them
so the AI can lean on dependency clusters first and fall back to weaker signals
when needed — instead of grouping blind when engines miss things.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    DependencyCluster,
    NamingCluster,
    TemporalCluster,
    TemporalClusterMember,
)


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment ID to fetch grouping signals for.",
        },
        "include_temporal": {
            "type": "boolean",
            "description": "Include temporal_cluster signals (weaker). Default true.",
            "default": True,
        },
        "include_naming": {
            "type": "boolean",
            "description": "Include naming_cluster signals (medium strength). Default true.",
            "default": True,
        },
        "min_member_count": {
            "type": "integer",
            "description": "Drop clusters smaller than N members. Default 2.",
            "default": 2,
        },
    },
    "required": ["assessment_id"],
}


def _load_json_list(raw: Optional[str]) -> List[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return parsed
    return []


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = params.get("assessment_id")
    if assessment_id is None:
        raise ValueError("assessment_id is required")
    include_temporal = bool(params.get("include_temporal", True))
    include_naming = bool(params.get("include_naming", True))
    min_member_count = int(params.get("min_member_count", 2))

    # --- Dependency clusters (most reliable signal) ---
    dep_clusters_raw = list(session.exec(
        select(DependencyCluster)
        .where(DependencyCluster.assessment_id == int(assessment_id))
        .order_by(DependencyCluster.coupling_score.desc())
    ).all())

    dependency_clusters = []
    for c in dep_clusters_raw:
        if c.member_count < min_member_count:
            continue
        dependency_clusters.append({
            "cluster_id": c.id,
            "label": c.cluster_label,
            "member_result_ids": _load_json_list(c.member_ids_json),
            "member_count": c.member_count,
            "internal_edge_count": c.internal_edge_count,
            "coupling_score": c.coupling_score,
            "impact_radius": c.impact_radius,
            "change_risk_level": c.change_risk_level,
            "change_risk_score": c.change_risk_score,
            "tables_involved": _load_json_list(c.tables_involved_json),
            "circular_dependencies": _load_json_list(c.circular_dependencies_json),
        })

    # --- Naming clusters (medium signal: shared prefix/suffix) ---
    naming_clusters: List[Dict[str, Any]] = []
    if include_naming:
        try:
            nc_raw = list(session.exec(
                select(NamingCluster)
                .where(NamingCluster.assessment_id == int(assessment_id))
            ).all())
            for c in nc_raw:
                member_ids = _load_json_list(getattr(c, "member_ids_json", None))
                if len(member_ids) < min_member_count:
                    continue
                naming_clusters.append({
                    "cluster_id": c.id,
                    "label": getattr(c, "cluster_label", None) or getattr(c, "pattern", None),
                    "member_result_ids": member_ids,
                    "member_count": len(member_ids),
                })
        except Exception as exc:
            naming_clusters = [{"error": f"naming_cluster query failed: {exc}"}]

    # --- Temporal clusters (weakest signal: same author + close time) ---
    temporal_clusters: List[Dict[str, Any]] = []
    if include_temporal:
        try:
            tc_raw = list(session.exec(
                select(TemporalCluster)
                .where(TemporalCluster.assessment_id == int(assessment_id))
            ).all())
            for c in tc_raw:
                # Pull member IDs via TemporalClusterMember table
                members = list(session.exec(
                    select(TemporalClusterMember.scan_result_id)
                    .where(TemporalClusterMember.temporal_cluster_id == c.id)
                ).all())
                if len(members) < min_member_count:
                    continue
                temporal_clusters.append({
                    "cluster_id": c.id,
                    "label": getattr(c, "cluster_label", None),
                    "member_result_ids": [int(m) for m in members],
                    "member_count": len(members),
                    "author": getattr(c, "author", None),
                    "time_window": {
                        "start": str(getattr(c, "window_start", None)),
                        "end": str(getattr(c, "window_end", None)),
                    },
                })
        except Exception as exc:
            temporal_clusters = [{"error": f"temporal_cluster query failed: {exc}"}]

    return {
        "assessment_id": int(assessment_id),
        "signal_strength_guide": {
            "dependency_clusters": "STRONGEST — built from code references and structural relationships. Trust these first.",
            "naming_clusters": "MEDIUM — shared prefixes/conventions. Useful when dependency engine misses connections.",
            "temporal_clusters": "WEAKEST — same author + tight time window. Last-resort signal; combine with others.",
        },
        "dependency_clusters": dependency_clusters,
        "naming_clusters": naming_clusters,
        "temporal_clusters": temporal_clusters,
        "counts": {
            "dependency": len(dependency_clusters),
            "naming": len(naming_clusters) if include_naming else None,
            "temporal": len(temporal_clusters) if include_temporal else None,
        },
        "fallback_guidance": (
            "If dependency_clusters is empty or sparse, the dependency_mapper engine may not "
            "have run or may have missed connections. Read the resource "
            "`assessment://guide/grouping-signals` for the full signal taxonomy and clustering "
            "approach (update sets, code refs, parent/child, naming, temporal). Use those "
            "signals manually to group artifacts when engine output is insufficient."
        ),
    }


TOOL_SPEC = ToolSpec(
    name="get_grouping_signals",
    description=(
        "Get feature-grouping signals for an assessment: dependency clusters (from the "
        "dependency_mapper engine — most reliable), plus naming and temporal clusters as "
        "backup. Use this when grouping features so you don't have to guess relationships. "
        "If signals are sparse, fall back to the assessment://guide/grouping-signals "
        "resource for the full signal taxonomy."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
