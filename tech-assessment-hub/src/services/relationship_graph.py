"""Shared relationship graph builder for cross-artifact analysis.

Constructs a weighted adjacency graph from engine outputs (CodeReference,
StructuralRelationship, UpdateSetOverlap, etc.) for use by both the
depth-first analyzer and seed_feature_groups.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from ..models import (
    Assessment,
    CodeReference,
    NamingCluster,
    OriginType,
    Scan,
    ScanResult,
    StructuralRelationship,
    TableColocationSummary,
    TemporalCluster,
    UpdateSetArtifactLink,
    UpdateSetOverlap,
)

# Shared edge weight constants — used by both graph builder and seed_feature_groups
EDGE_WEIGHTS: Dict[str, float] = {
    "dependency_cluster": 3.5,
    "ai_relationship": 3.5,
    "update_set_overlap": 3.0,
    "update_set_artifact_link": 2.5,
    "code_reference": 3.0,
    "structural_relationship": 2.5,
    "temporal_cluster": 1.8,
    "naming_cluster": 2.0,
    "table_colocation": 1.2,
}

_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}


@dataclass
class RelationshipEdge:
    """A weighted edge in the relationship graph."""
    target_id: int
    signal_type: str  # "code_reference", "structural_relationship", etc.
    weight: float
    direction: str  # "outgoing", "incoming", "bidirectional"


@dataclass
class RelationshipGraph:
    """Weighted adjacency graph of scan result relationships."""
    adjacency: Dict[int, List[RelationshipEdge]] = field(default_factory=dict)
    customized_ids: Set[int] = field(default_factory=set)

    def neighbors(self, sr_id: int, min_weight: float = 0.0) -> List[int]:
        """Return all neighbor IDs with edge weight >= min_weight."""
        edges = self.adjacency.get(sr_id, [])
        seen: Set[int] = set()
        result: List[int] = []
        for e in edges:
            if e.weight >= min_weight and e.target_id not in seen:
                seen.add(e.target_id)
                result.append(e.target_id)
        return result

    def customized_neighbors(self, sr_id: int, min_weight: float = 0.0) -> List[int]:
        """Return only customized neighbor IDs with edge weight >= min_weight."""
        return [n for n in self.neighbors(sr_id, min_weight) if n in self.customized_ids]

    def edge_weight(self, a: int, b: int) -> float:
        """Return max edge weight between two nodes (0.0 if no edge)."""
        max_w = 0.0
        for e in self.adjacency.get(a, []):
            if e.target_id == b and e.weight > max_w:
                max_w = e.weight
        return max_w

    def edge_types(self, a: int, b: int) -> List[str]:
        """Return all signal types connecting a and b."""
        return [e.signal_type for e in self.adjacency.get(a, []) if e.target_id == b]


def _add_edge(
    graph: RelationshipGraph,
    source: int,
    target: int,
    signal_type: str,
    weight: float,
    direction: str = "bidirectional",
) -> None:
    """Add an edge (and reverse if bidirectional) to the graph."""
    if source not in graph.adjacency:
        graph.adjacency[source] = []
    graph.adjacency[source].append(
        RelationshipEdge(
            target_id=target,
            signal_type=signal_type,
            weight=weight,
            direction=direction,
        )
    )

    if direction == "bidirectional":
        if target not in graph.adjacency:
            graph.adjacency[target] = []
        graph.adjacency[target].append(
            RelationshipEdge(
                target_id=source,
                signal_type=signal_type,
                weight=weight,
                direction=direction,
            )
        )
    elif direction == "incoming":
        if target not in graph.adjacency:
            graph.adjacency[target] = []
        graph.adjacency[target].append(
            RelationshipEdge(
                target_id=source,
                signal_type=signal_type,
                weight=weight,
                direction="outgoing",
            )
        )


def _safe_json_list(value: Optional[str]) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _parse_result_ids(value: Optional[str]) -> List[int]:
    parsed = _safe_json_list(value)
    ids: List[int] = []
    for item in parsed:
        candidate = item
        if isinstance(item, dict):
            candidate = (
                item.get("scan_result_id")
                or item.get("result_id")
                or item.get("id")
            )
        try:
            if candidate is not None:
                ids.append(int(candidate))
        except (TypeError, ValueError):
            continue
    return ids


def build_relationship_graph(
    session: Session, assessment_id: int
) -> RelationshipGraph:
    """Build a relationship graph from all engine outputs for an assessment.

    Queries: CodeReference, StructuralRelationship, UpdateSetArtifactLink,
    UpdateSetOverlap, TemporalCluster, NamingCluster, TableColocationSummary.

    Returns a RelationshipGraph with adjacency lists and the set of customized IDs.
    """
    graph = RelationshipGraph()

    # Get all scan result IDs and determine which are customized
    scan_ids = session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all()
    if not scan_ids:
        return graph

    results = session.exec(
        select(ScanResult.id, ScanResult.origin_type)
        .where(ScanResult.scan_id.in_(list(scan_ids)))  # type: ignore[attr-defined]
    ).all()

    all_result_ids: Set[int] = set()
    for row in results:
        rid = row[0] if isinstance(row, tuple) else row.id
        origin = row[1] if isinstance(row, tuple) else row.origin_type
        if rid is not None:
            all_result_ids.add(int(rid))
            origin_val = (
                origin.value if hasattr(origin, "value") else str(origin) if origin else ""
            )
            if origin_val in _CUSTOMIZED_ORIGIN_VALUES:
                graph.customized_ids.add(int(rid))

    # --- Code References ---
    code_refs = session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == assessment_id
        )
    ).all()
    for ref in code_refs:
        src = ref.source_scan_result_id
        tgt = ref.target_scan_result_id
        if src is not None and tgt is not None:
            _add_edge(
                graph,
                int(src),
                int(tgt),
                "code_reference",
                EDGE_WEIGHTS["code_reference"],
                "outgoing",
            )

    # --- Structural Relationships ---
    struct_rels = session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == assessment_id
        )
    ).all()
    for rel in struct_rels:
        parent = rel.parent_scan_result_id
        child = rel.child_scan_result_id
        if parent is not None and child is not None:
            _add_edge(
                graph,
                int(parent),
                int(child),
                "structural_relationship",
                EDGE_WEIGHTS["structural_relationship"],
                "bidirectional",
            )

    # --- Update Set Artifact Links ---
    us_links = session.exec(
        select(UpdateSetArtifactLink).where(
            UpdateSetArtifactLink.assessment_id == assessment_id
        )
    ).all()
    # Group by update set to create edges between co-members
    us_members: Dict[int, List[int]] = {}
    for link in us_links:
        us_id = int(link.update_set_id)
        sr_id = int(link.scan_result_id)
        us_members.setdefault(us_id, []).append(sr_id)

    for _us_id, members in us_members.items():
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                _add_edge(
                    graph,
                    a,
                    b,
                    "update_set_artifact_link",
                    EDGE_WEIGHTS["update_set_artifact_link"],
                    "bidirectional",
                )

    # --- Update Set Overlaps ---
    overlaps = session.exec(
        select(UpdateSetOverlap).where(
            UpdateSetOverlap.assessment_id == assessment_id
        )
    ).all()
    for overlap in overlaps:
        member_ids = _parse_result_ids(
            getattr(overlap, "shared_records_json", None)
            or getattr(overlap, "member_ids_json", None)
        )
        for i, a in enumerate(member_ids):
            for b in member_ids[i + 1 :]:
                _add_edge(
                    graph,
                    a,
                    b,
                    "update_set_overlap",
                    EDGE_WEIGHTS["update_set_overlap"],
                    "bidirectional",
                )

    # --- Temporal Clusters ---
    temp_clusters = session.exec(
        select(TemporalCluster).where(
            TemporalCluster.assessment_id == assessment_id
        )
    ).all()
    for cluster in temp_clusters:
        member_ids = _parse_result_ids(
            getattr(cluster, "record_ids_json", None)
        )
        for i, a in enumerate(member_ids):
            for b in member_ids[i + 1 :]:
                _add_edge(
                    graph,
                    a,
                    b,
                    "temporal_cluster",
                    EDGE_WEIGHTS["temporal_cluster"],
                    "bidirectional",
                )

    # --- Naming Clusters ---
    naming_clusters = session.exec(
        select(NamingCluster).where(
            NamingCluster.assessment_id == assessment_id
        )
    ).all()
    for cluster in naming_clusters:
        member_ids = _parse_result_ids(
            getattr(cluster, "member_ids_json", None)
        )
        for i, a in enumerate(member_ids):
            for b in member_ids[i + 1 :]:
                _add_edge(
                    graph,
                    a,
                    b,
                    "naming_cluster",
                    EDGE_WEIGHTS["naming_cluster"],
                    "bidirectional",
                )

    # --- Table Colocation ---
    colocations = session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == assessment_id
        )
    ).all()
    for coloc in colocations:
        member_ids = _parse_result_ids(
            getattr(coloc, "record_ids_json", None)
        )
        for i, a in enumerate(member_ids):
            for b in member_ids[i + 1 :]:
                _add_edge(
                    graph,
                    a,
                    b,
                    "table_colocation",
                    EDGE_WEIGHTS["table_colocation"],
                    "bidirectional",
                )

    return graph
