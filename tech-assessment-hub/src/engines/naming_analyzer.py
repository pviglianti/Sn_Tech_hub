"""Engine 3: Naming Analyzer.

Groups ScanResults by shared naming prefixes/patterns into naming clusters.
Deterministic, code-only analysis of artifact name conventions.

Input:  ScanResult rows for an assessment
Output: Rows in naming_cluster table
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from sqlmodel import Session, select

from ..models import Assessment, Scan, ScanResult, NamingCluster
from ..services.integration_properties import (
    load_reasoning_engine_properties,
)


def _tokenize(name: str) -> List[str]:
    """Split an artifact name into tokens on common delimiters.

    Handles spaces, hyphens, underscores, dots, and the ServiceNow
    convention of " - " as a separator.  Empty strings are filtered out.
    """
    tokens = re.split(r"[\s\-_\.]+", name)
    return [t for t in tokens if t]


def _build_prefix_clusters(
    scan_results: List[ScanResult],
    min_prefix_tokens: int,
    min_cluster_size: int,
) -> List[Dict[str, Any]]:
    """Build prefix-based naming clusters from scan results.

    Algorithm:
    1. Tokenize every scan result name.
    2. For each prefix length from min_prefix_tokens up to len(tokens)-1,
       group scan results that share the same prefix token sequence.
    3. Only keep groups with member_count >= min_cluster_size.
    4. Deduplicate overlapping prefixes: prefer the MOST SPECIFIC (longest)
       prefix that still meets min_cluster_size.
    """
    # Map: prefix tuple -> set of scan_result ids
    prefix_groups: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    # Also track table names and full scan result info per prefix
    prefix_tables: Dict[Tuple[str, ...], set] = defaultdict(set)

    for sr in scan_results:
        if not sr.name or sr.id is None:
            continue
        tokens = _tokenize(sr.name)
        if len(tokens) < min_prefix_tokens + 1:
            # Need at least min_prefix_tokens for the prefix PLUS at least one
            # additional token so that the prefix is a true prefix, not the
            # entire name.  However, when two items share a full-length prefix
            # that is still meaningful grouping.  We require the prefix length
            # to be < len(tokens) only during generation; the cluster itself
            # is valid if it has enough members.
            pass

        # Generate all prefixes from min_prefix_tokens up to len(tokens)-1
        max_prefix_len = len(tokens) - 1
        for plen in range(min_prefix_tokens, max_prefix_len + 1):
            prefix = tuple(tokens[:plen])
            prefix_groups[prefix].append(sr.id)
            prefix_tables[prefix].add(sr.table_name)

    # Filter to qualifying clusters (>= min_cluster_size)
    qualifying: Dict[Tuple[str, ...], List[int]] = {
        prefix: ids
        for prefix, ids in prefix_groups.items()
        if len(ids) >= min_cluster_size
    }

    if not qualifying:
        return []

    # Deduplicate: for each set of members, keep only the longest prefix.
    # A shorter prefix is redundant if a longer prefix exists that covers
    # the same (or subset of) members AND still meets min_cluster_size.
    #
    # Strategy: sort prefixes longest-first.  For each scan_result_id, track
    # the longest prefix cluster it has been assigned to.  A shorter prefix
    # only keeps members NOT already claimed by a longer prefix.

    sorted_prefixes = sorted(qualifying.keys(), key=len, reverse=True)
    claimed: Dict[int, Tuple[str, ...]] = {}  # sr_id -> longest prefix assigned
    final_clusters: Dict[Tuple[str, ...], List[int]] = {}

    for prefix in sorted_prefixes:
        # Members not yet claimed by a longer prefix
        unclaimed = [sid for sid in qualifying[prefix] if sid not in claimed]
        if len(unclaimed) >= min_cluster_size:
            final_clusters[prefix] = unclaimed
            for sid in unclaimed:
                claimed[sid] = prefix

    # Build output dicts
    results: List[Dict[str, Any]] = []
    for prefix, member_ids in final_clusters.items():
        label = " ".join(prefix)
        tables = sorted(prefix_tables[prefix])
        results.append({
            "cluster_label": label,
            "pattern_type": "prefix",
            "member_count": len(member_ids),
            "member_ids": sorted(member_ids),
            "tables_involved": tables,
            "confidence": 1.0,
        })

    return results


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the naming analyzer engine for an assessment.

    Returns a summary dict with keys:
        success (bool), clusters_created (int), errors (list[str])
    """
    # 1. Validate assessment exists
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "clusters_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    # 2. Load scan results via join
    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "clusters_created": 0,
            "errors": [],
            "message": "No scan results",
        }

    # 3. Delete existing NamingCluster rows for idempotency
    existing = list(
        session.exec(
            select(NamingCluster).where(
                NamingCluster.assessment_id == assessment_id
            )
        ).all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    # Read configurable properties with instance override support
    props = load_reasoning_engine_properties(session, instance_id=assessment.instance_id)
    min_cluster_size = props.naming_min_cluster_size
    min_prefix_tokens = props.naming_min_prefix_tokens

    # 4. Process: build prefix clusters
    clusters = _build_prefix_clusters(
        scan_results,
        min_prefix_tokens=min_prefix_tokens,
        min_cluster_size=min_cluster_size,
    )

    # 5. Insert NamingCluster rows
    errors: List[str] = []
    clusters_created = 0

    for cluster_data in clusters:
        try:
            nc = NamingCluster(
                instance_id=assessment.instance_id,
                assessment_id=assessment_id,
                cluster_label=cluster_data["cluster_label"],
                pattern_type=cluster_data["pattern_type"],
                member_count=cluster_data["member_count"],
                member_ids_json=json.dumps(cluster_data["member_ids"]),
                tables_involved_json=json.dumps(cluster_data["tables_involved"]),
                confidence=cluster_data["confidence"],
            )
            session.add(nc)
            clusters_created += 1
        except Exception as exc:
            errors.append(f"Error creating cluster '{cluster_data['cluster_label']}': {exc}")

    # 6. Commit
    session.commit()

    return {
        "success": True,
        "clusters_created": clusters_created,
        "errors": errors,
    }
