"""Dependency Graph service — builds a dependency-only graph from
CodeReference + StructuralRelationship tables.

All scan results appear as nodes (for visualization), but only customized
ones (modified_ootb, net_new_customer) participate in chain resolution,
clustering, and scoring.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from ..models import CodeReference, OriginType, Scan, ScanResult, StructuralRelationship

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}

_DEPENDENCY_WEIGHTS: Dict[str, float] = {
    "code_reference": 3.0,
    "structural": 2.5,
    "shared_dependency": 2.0,
}

_HOP_WEIGHTS: Dict[int, float] = {1: 3.0, 2: 2.0, 3: 1.0}

_ARTIFACT_TYPE_RISK: Dict[str, float] = {
    "sys_security_acl": 15.0,
    "sys_db_object": 10.0,
    "wf_workflow": 8.0,
    "sys_script": 6.0,
    "sys_script_include": 6.0,
    "sys_ui_policy": 4.0,
    "sys_script_client": 4.0,
    "sys_dictionary": 3.0,
}
_DEFAULT_ARTIFACT_RISK = 3.0


# ---------------------------------------------------------------------------
# Criticality helpers
# ---------------------------------------------------------------------------

def _code_ref_criticality(reference_type: str) -> str:
    if reference_type == "script_include":
        return "high"
    if reference_type in ("table_query", "event", "rest_message"):
        return "medium"
    return "low"


def _structural_criticality(relationship_type: str) -> str:
    if relationship_type in ("ui_policy_action", "ui_policy_field", "dictionary_entry"):
        return "high"
    if relationship_type == "dictionary_override":
        return "low"
    return "medium"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DependencyEdge:
    target_id: int
    dependency_type: str  # code_reference, structural, shared_dependency
    direction: str  # outbound, inbound, bidirectional
    weight: float
    criticality: str  # high, medium, low
    shared_via: Optional[str] = None


@dataclass
class DependencyGraph:
    adjacency: Dict[int, List[DependencyEdge]] = field(default_factory=dict)
    customized_ids: Set[int] = field(default_factory=set)
    all_ids: Set[int] = field(default_factory=set)
    _table_names: Dict[int, str] = field(default_factory=dict)

    # -- traversal -----------------------------------------------------------

    def outbound(self, node_id: int) -> List[int]:
        """IDs this node depends on (direction == 'outbound')."""
        seen: Set[int] = set()
        result: List[int] = []
        for e in self.adjacency.get(node_id, []):
            if e.direction == "outbound" and e.target_id not in seen:
                seen.add(e.target_id)
                result.append(e.target_id)
        return result

    def inbound(self, node_id: int) -> List[int]:
        """IDs that depend on this node (direction == 'inbound')."""
        seen: Set[int] = set()
        result: List[int] = []
        for e in self.adjacency.get(node_id, []):
            if e.direction == "inbound" and e.target_id not in seen:
                seen.add(e.target_id)
                result.append(e.target_id)
        return result

    def all_neighbors(self, node_id: int) -> List[int]:
        """All connected IDs regardless of direction."""
        seen: Set[int] = set()
        result: List[int] = []
        for e in self.adjacency.get(node_id, []):
            if e.target_id not in seen:
                seen.add(e.target_id)
                result.append(e.target_id)
        return result

    def edges_between(self, a: int, b: int) -> List[DependencyEdge]:
        """All edges from a to b."""
        return [e for e in self.adjacency.get(a, []) if e.target_id == b]

    # -- chain resolution ----------------------------------------------------

    def resolve_transitive_chains(self, max_depth: int = 3) -> List[Dict]:
        """BFS from each customized node following outbound edges to other
        customized nodes. Direct edges (hop 1) use original type/weight 3.0.
        Transitive edges (hop 2+) use type 'transitive' with diminishing weights.
        """
        chains: List[Dict] = []

        for source in self.customized_ids:
            # BFS: queue items are (current_node, path_so_far)
            queue: deque = deque()
            queue.append((source, [source]))
            visited: Set[int] = {source}

            while queue:
                current, path = queue.popleft()
                hop = len(path)  # hop count from source is len(path)-1 for next step

                if hop > max_depth:
                    continue

                for edge in self.adjacency.get(current, []):
                    if edge.direction != "outbound":
                        continue
                    nxt = edge.target_id
                    if nxt in visited:
                        continue
                    if nxt not in self.customized_ids:
                        continue

                    new_path = path + [nxt]
                    hop_count = len(new_path) - 1

                    if hop_count > max_depth:
                        continue

                    if hop_count == 1:
                        dep_type = edge.dependency_type
                        chain_weight = _HOP_WEIGHTS.get(1, 3.0)
                        crit = edge.criticality
                    else:
                        dep_type = "transitive"
                        chain_weight = _HOP_WEIGHTS.get(hop_count, 1.0)
                        crit = edge.criticality

                    chains.append({
                        "source": source,
                        "target": nxt,
                        "dependency_type": dep_type,
                        "direction": "outbound",
                        "hop_count": hop_count,
                        "chain_path": list(new_path),
                        "chain_weight": chain_weight,
                        "criticality": crit,
                    })

                    visited.add(nxt)
                    queue.append((nxt, new_path))

        return chains

    # -- circular detection --------------------------------------------------

    def detect_circular_dependencies(self) -> List[List[int]]:
        """DFS three-color algorithm on customized nodes, outbound edges only.
        Returns cycle paths like [[A, B, C, A]].
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[int, int] = {n: WHITE for n in self.customized_ids}
        parent_path: Dict[int, List[int]] = {}
        cycles: List[List[int]] = []

        def _dfs(node: int, path: List[int]) -> None:
            color[node] = GRAY
            parent_path[node] = path

            for edge in self.adjacency.get(node, []):
                if edge.direction != "outbound":
                    continue
                nxt = edge.target_id
                if nxt not in self.customized_ids:
                    continue

                if color.get(nxt) == GRAY:
                    # Found cycle — extract from nxt's position in path
                    cycle_start = parent_path[nxt]
                    idx = cycle_start.index(nxt) if nxt in cycle_start else -1
                    if idx >= 0:
                        cycle = cycle_start[idx:] + [nxt]
                    else:
                        cycle = path + [nxt]
                    cycles.append(cycle)
                elif color.get(nxt) == WHITE:
                    _dfs(nxt, path + [nxt])

            color[node] = BLACK

        for node in self.customized_ids:
            if color.get(node) == WHITE:
                _dfs(node, [node])

        return cycles

    # -- clustering ----------------------------------------------------------

    def compute_clusters(self, min_cluster_size: int = 2) -> List[Dict]:
        """Connected components via BFS on undirected view, customized nodes only."""
        visited: Set[int] = set()
        components: List[Set[int]] = []

        for node in self.customized_ids:
            if node in visited:
                continue
            component: Set[int] = set()
            queue: deque = deque([node])
            while queue:
                cur = queue.popleft()
                if cur in visited or cur not in self.customized_ids:
                    continue
                visited.add(cur)
                component.add(cur)
                for edge in self.adjacency.get(cur, []):
                    if edge.target_id in self.customized_ids and edge.target_id not in visited:
                        queue.append(edge.target_id)
            if len(component) >= min_cluster_size:
                components.append(component)

        clusters: List[Dict] = []
        for comp in components:
            member_ids = sorted(comp)
            internal_edges = self._count_internal_edges(comp)
            coupling = self._cluster_coupling_score(comp)
            impact = self._cluster_impact_radius(comp)
            circular = self._cluster_circular_deps(comp)
            tables = sorted({self._table_names.get(m, "unknown") for m in comp})
            risk_score, risk_level = self._cluster_change_risk(
                comp, circular, internal_edges, tables
            )

            # Auto-label: most common table_name + cluster info
            table_counts: Dict[str, int] = defaultdict(int)
            for m in comp:
                table_counts[self._table_names.get(m, "unknown")] += 1
            most_common_table = max(table_counts, key=table_counts.get)  # type: ignore[arg-type]

            clusters.append({
                "cluster_label": f"{most_common_table} cluster ({len(comp)} artifacts)",
                "member_ids": member_ids,
                "member_count": len(comp),
                "internal_edge_count": internal_edges,
                "coupling_score": coupling,
                "impact_radius": impact,
                "change_risk_score": risk_score,
                "change_risk_level": risk_level,
                "circular_dependencies": circular,
                "tables_involved": tables,
            })

        return clusters

    # -- scoring -------------------------------------------------------------

    def coupling_score(self, node_id: int) -> float:
        """Sum of edge weights for a node."""
        return sum(e.weight for e in self.adjacency.get(node_id, []))

    def impact_radius(self, node_id: int) -> str:
        """outbound*2 + inbound*3 + structural_children → thresholds."""
        outbound_count = len(self.outbound(node_id))
        inbound_count = len(self.inbound(node_id))
        structural_children = sum(
            1 for e in self.adjacency.get(node_id, [])
            if e.dependency_type == "structural" and e.direction == "outbound"
        )
        score = outbound_count * 2 + inbound_count * 3 + structural_children

        if score > 50:
            return "very_high"
        if score > 25:
            return "high"
        if score > 10:
            return "medium"
        return "low"

    # -- private scoring helpers ---------------------------------------------

    def _count_internal_edges(self, members: Set[int]) -> int:
        count = 0
        for m in members:
            for e in self.adjacency.get(m, []):
                if e.target_id in members:
                    count += 1
        return count

    def _cluster_coupling_score(self, members: Set[int]) -> float:
        if not members:
            return 0.0
        return sum(self.coupling_score(m) for m in members) / len(members)

    def _cluster_impact_radius(self, members: Set[int]) -> str:
        """Count EXTERNAL edges (to nodes outside cluster)."""
        outbound_ext = 0
        inbound_ext = 0
        structural_children = 0

        for m in members:
            for e in self.adjacency.get(m, []):
                if e.target_id in members:
                    continue
                if e.direction == "outbound":
                    outbound_ext += 1
                elif e.direction == "inbound":
                    inbound_ext += 1
                if e.dependency_type == "structural" and e.direction == "outbound":
                    structural_children += 1

        score = outbound_ext * 2 + inbound_ext * 3 + structural_children
        if score > 50:
            return "very_high"
        if score > 25:
            return "high"
        if score > 10:
            return "medium"
        return "low"

    def _cluster_circular_deps(self, members: Set[int]) -> List[List[int]]:
        """Detect cycles within the cluster subset."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[int, int] = {n: WHITE for n in members}
        parent_path: Dict[int, List[int]] = {}
        cycles: List[List[int]] = []

        def _dfs(node: int, path: List[int]) -> None:
            color[node] = GRAY
            parent_path[node] = path
            for edge in self.adjacency.get(node, []):
                if edge.direction != "outbound":
                    continue
                nxt = edge.target_id
                if nxt not in members:
                    continue
                if color[nxt] == GRAY:
                    idx = path.index(nxt) if nxt in path else -1
                    if idx >= 0:
                        cycles.append(path[idx:] + [nxt])
                    else:
                        cycles.append(path + [nxt])
                elif color[nxt] == WHITE:
                    _dfs(nxt, path + [nxt])
            color[node] = BLACK

        for node in members:
            if color[node] == WHITE:
                _dfs(node, [node])

        return cycles

    def _cluster_change_risk(
        self,
        members: Set[int],
        circular_deps: List[List[int]],
        internal_edge_count: int,
        tables: List[str],
    ) -> Tuple[float, str]:
        coupling = self._cluster_coupling_score(members)
        risk = coupling * 10
        risk += len(circular_deps) * 15

        # Count high-criticality edges within cluster
        critical_edge_count = 0
        for m in members:
            for e in self.adjacency.get(m, []):
                if e.target_id in members and e.criticality == "high":
                    critical_edge_count += 1
        risk += critical_edge_count * 20
        risk += len(members) * 2

        # Average artifact type risk
        if tables:
            avg_type_risk = sum(
                _ARTIFACT_TYPE_RISK.get(t, _DEFAULT_ARTIFACT_RISK) for t in tables
            ) / len(tables)
            risk += avg_type_risk

        risk = min(risk, 100)

        if risk >= 70:
            level = "critical"
        elif risk >= 50:
            level = "high"
        elif risk >= 30:
            level = "medium"
        else:
            level = "low"

        return round(risk, 2), level


# ---------------------------------------------------------------------------
# Edge helper
# ---------------------------------------------------------------------------

def _add_edge(
    graph: DependencyGraph,
    source: int,
    target: int,
    dependency_type: str,
    weight: float,
    direction: str,
    criticality: str,
    shared_via: Optional[str] = None,
) -> None:
    """Add edge to source. If outbound, also add reverse inbound to target.
    If bidirectional, add bidirectional to both.
    """
    if source not in graph.adjacency:
        graph.adjacency[source] = []
    graph.adjacency[source].append(DependencyEdge(
        target_id=target,
        dependency_type=dependency_type,
        direction=direction,
        weight=weight,
        criticality=criticality,
        shared_via=shared_via,
    ))

    if direction == "outbound":
        if target not in graph.adjacency:
            graph.adjacency[target] = []
        graph.adjacency[target].append(DependencyEdge(
            target_id=source,
            dependency_type=dependency_type,
            direction="inbound",
            weight=weight,
            criticality=criticality,
            shared_via=shared_via,
        ))
    elif direction == "bidirectional":
        if target not in graph.adjacency:
            graph.adjacency[target] = []
        graph.adjacency[target].append(DependencyEdge(
            target_id=source,
            dependency_type=dependency_type,
            direction="bidirectional",
            weight=weight,
            criticality=criticality,
            shared_via=shared_via,
        ))


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_dependency_graph(
    session: Session, assessment_id: int
) -> DependencyGraph:
    """Build a DependencyGraph from CodeReference + StructuralRelationship
    tables for the given assessment.
    """
    graph = DependencyGraph()

    # 1. Load all scan results for the assessment, classify
    scan_ids = session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all()
    if not scan_ids:
        return graph

    all_results = session.exec(
        select(ScanResult).where(ScanResult.scan_id.in_(scan_ids))  # type: ignore[attr-defined]
    ).all()

    for sr in all_results:
        graph.all_ids.add(sr.id)
        graph._table_names[sr.id] = sr.table_name
        if sr.origin_type and sr.origin_type.value in _CUSTOMIZED_ORIGIN_VALUES:
            graph.customized_ids.add(sr.id)

    if not all_results:
        return graph

    sr_id_set = graph.all_ids

    # 2. Load CodeReference rows → outbound edges
    code_refs = session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == assessment_id,
            CodeReference.target_scan_result_id.isnot(None),  # type: ignore[union-attr]
        )
    ).all()

    # Track customized→non-customized refs for shared_dependency detection
    # key: target_identifier, value: list of customized source IDs
    shared_dep_tracker: Dict[str, List[int]] = defaultdict(list)

    for cr in code_refs:
        src = cr.source_scan_result_id
        tgt = cr.target_scan_result_id
        if src not in sr_id_set or tgt not in sr_id_set:
            continue

        criticality = _code_ref_criticality(cr.reference_type)
        _add_edge(
            graph, src, tgt,
            dependency_type="code_reference",
            weight=_DEPENDENCY_WEIGHTS["code_reference"],
            direction="outbound",
            criticality=criticality,
        )

        # Track for shared_dependency: customized source → non-customized target
        if src in graph.customized_ids and tgt not in graph.customized_ids:
            shared_dep_tracker[cr.target_identifier].append(src)

    # 3. Detect shared dependencies
    for target_ident, sources in shared_dep_tracker.items():
        if len(sources) < 2:
            continue
        unique_sources = sorted(set(sources))
        for i in range(len(unique_sources)):
            for j in range(i + 1, len(unique_sources)):
                _add_edge(
                    graph, unique_sources[i], unique_sources[j],
                    dependency_type="shared_dependency",
                    weight=_DEPENDENCY_WEIGHTS["shared_dependency"],
                    direction="bidirectional",
                    criticality="medium",
                    shared_via=target_ident,
                )

    # 4. Load StructuralRelationship rows → bidirectional edges
    struct_rels = session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == assessment_id
        )
    ).all()

    for sr in struct_rels:
        parent = sr.parent_scan_result_id
        child = sr.child_scan_result_id
        if parent not in sr_id_set or child not in sr_id_set:
            continue

        criticality = _structural_criticality(sr.relationship_type)
        _add_edge(
            graph, parent, child,
            dependency_type="structural",
            weight=_DEPENDENCY_WEIGHTS["structural"],
            direction="bidirectional",
            criticality=criticality,
        )

    return graph
