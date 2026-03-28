"""Engine 7: Dependency Mapper.

Builds a standalone dependency graph from CodeReference + StructuralRelationship,
resolves transitive chains, detects circular dependencies, computes connected-
component clusters with scoring, and persists results.

Input:  CodeReference + StructuralRelationship rows for an assessment
Output: Rows in dependency_chain and dependency_cluster tables

Only customized scan results (modified_ootb, net_new_customer) participate
in clustering and chain resolution. All artifacts appear in the graph for
visualization.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlmodel import Session, select

from ..models import (
    Assessment,
    DependencyChain,
    DependencyCluster,
    Feature,
    FeatureScanResult,
    Scan,
)
from ..services.dependency_graph import build_dependency_graph
from ..services.integration_properties import load_reasoning_engine_properties


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the dependency mapper engine for an assessment.

    Returns a summary dict with keys:
        success (bool), chains_created (int), clusters_created (int), errors (list[str])
    """
    # 1. Validate assessment exists
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "chains_created": 0,
            "clusters_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    # 2. Load configurable properties
    props = load_reasoning_engine_properties(session, instance_id=assessment.instance_id)
    max_depth = getattr(props, "dependency_max_transitive_depth", 3)
    min_cluster = getattr(props, "dependency_min_cluster_size", 2)

    # 3. Delete existing output rows for idempotency
    scan_ids = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())

    for row in list(session.exec(
        select(DependencyChain).where(
            DependencyChain.assessment_id == assessment_id
        )
    ).all()):
        session.delete(row)

    for row in list(session.exec(
        select(DependencyCluster).where(
            DependencyCluster.assessment_id == assessment_id
        )
    ).all()):
        session.delete(row)
    session.flush()

    # 4. Build dependency graph
    graph = build_dependency_graph(session, assessment_id)

    if not graph.customized_ids:
        session.commit()
        return {
            "success": True,
            "chains_created": 0,
            "clusters_created": 0,
            "errors": [],
            "message": "No customized scan results",
        }

    # Determine scan_id for output rows (use first scan)
    scan_id = scan_ids[0] if scan_ids else None
    if scan_id is None:
        session.commit()
        return {
            "success": True,
            "chains_created": 0,
            "clusters_created": 0,
            "errors": [],
        }

    errors: List[str] = []

    # 5. Resolve transitive chains and persist
    chains = graph.resolve_transitive_chains(max_depth=max_depth)
    chains_created = 0

    for chain_data in chains:
        try:
            dc = DependencyChain(
                scan_id=scan_id,
                instance_id=assessment.instance_id,
                assessment_id=assessment_id,
                source_scan_result_id=chain_data["source"],
                target_scan_result_id=chain_data["target"],
                dependency_type=chain_data["dependency_type"],
                direction=chain_data["direction"],
                hop_count=chain_data["hop_count"],
                chain_path_json=json.dumps(chain_data["chain_path"]),
                chain_weight=chain_data["chain_weight"],
                criticality=chain_data["criticality"],
            )
            session.add(dc)
            chains_created += 1
        except Exception as exc:
            errors.append(f"Error creating chain: {exc}")

    # 6. Compute clusters and persist
    cluster_results = graph.compute_clusters(min_cluster_size=min_cluster)
    clusters_created = 0

    for cl in cluster_results:
        try:
            dc = DependencyCluster(
                scan_id=scan_id,
                instance_id=assessment.instance_id,
                assessment_id=assessment_id,
                cluster_label=cl["cluster_label"],
                member_ids_json=json.dumps(cl["member_ids"]),
                member_count=cl["member_count"],
                internal_edge_count=cl["internal_edge_count"],
                coupling_score=cl["coupling_score"],
                impact_radius=cl["impact_radius"],
                change_risk_score=cl["change_risk_score"],
                change_risk_level=cl["change_risk_level"],
                circular_dependencies_json=json.dumps(cl["circular_dependencies"]),
                tables_involved_json=json.dumps(cl["tables_involved"]),
            )
            session.add(dc)
            clusters_created += 1
        except Exception as exc:
            errors.append(f"Error creating cluster '{cl['cluster_label']}': {exc}")

    # 7. Propagate change risk to features
    _propagate_risk_to_features(session, assessment_id, cluster_results)

    # 8. Commit
    session.commit()

    return {
        "success": True,
        "chains_created": chains_created,
        "clusters_created": clusters_created,
        "errors": errors,
    }


def _propagate_risk_to_features(
    session: Session,
    assessment_id: int,
    cluster_results: List[Dict[str, Any]],
) -> None:
    """Set Feature.change_risk_score/level from overlapping dependency clusters."""
    if not cluster_results:
        return

    # Build member_id -> max risk mapping
    member_risk: Dict[int, float] = {}
    member_level: Dict[int, str] = {}
    for cl in cluster_results:
        for mid in cl["member_ids"]:
            if mid not in member_risk or cl["change_risk_score"] > member_risk[mid]:
                member_risk[mid] = cl["change_risk_score"]
                member_level[mid] = cl["change_risk_level"]

    # Load features and their scan result links
    features = list(session.exec(
        select(Feature).where(Feature.assessment_id == assessment_id)
    ).all())

    for feature in features:
        links = list(session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.feature_id == feature.id
            )
        ).all())
        max_risk = 0.0
        max_level = "low"
        for link in links:
            sr_id = link.scan_result_id
            if sr_id in member_risk and member_risk[sr_id] > max_risk:
                max_risk = member_risk[sr_id]
                max_level = member_level[sr_id]

        if max_risk > 0:
            feature.change_risk_score = max_risk
            feature.change_risk_level = max_level
            session.add(feature)
