"""Engine 2: Temporal Clusterer.

Groups ScanResults by same developer + close time proximity into temporal
clusters.  Records that share both the same ``sys_updated_by`` and fall within
a configurable gap threshold are placed into the same cluster.

Input: ScanResult rows (via Scan join) with sys_updated_by / sys_updated_on
Output: Rows in temporal_cluster + temporal_cluster_member tables
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from sqlmodel import Session, select

from ..models import (
    Assessment,
    Scan,
    ScanResult,
    TemporalCluster,
    TemporalClusterMember,
)
from ..services.integration_properties import (
    load_reasoning_engine_properties,
)


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the temporal clusterer engine for an assessment."""

    # ------------------------------------------------------------------
    # 1. Validate assessment
    # ------------------------------------------------------------------
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "clusters_created": 0,
            "members_created": 0,
            "records_processed": 0,
            "records_skipped": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

    # ------------------------------------------------------------------
    # 2. Load scan results
    # ------------------------------------------------------------------
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
            "members_created": 0,
            "records_processed": 0,
            "records_skipped": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # ------------------------------------------------------------------
    # 3. Idempotency: delete existing rows (members first for FK safety)
    # ------------------------------------------------------------------
    existing_members = list(
        session.exec(
            select(TemporalClusterMember).where(
                TemporalClusterMember.assessment_id == assessment_id
            )
        ).all()
    )
    for row in existing_members:
        session.delete(row)
    session.flush()

    existing_clusters = list(
        session.exec(
            select(TemporalCluster).where(
                TemporalCluster.assessment_id == assessment_id
            )
        ).all()
    )
    for row in existing_clusters:
        session.delete(row)
    session.flush()

    # ------------------------------------------------------------------
    # 4. Read configurable thresholds from instance-aware properties
    # ------------------------------------------------------------------
    props = load_reasoning_engine_properties(session, instance_id=instance_id)
    gap_threshold = props.temporal_gap_threshold_minutes
    min_cluster_size = props.temporal_min_cluster_size

    # ------------------------------------------------------------------
    # 5. Filter and group by developer
    # ------------------------------------------------------------------
    records_skipped = 0
    by_developer: Dict[str, List[ScanResult]] = defaultdict(list)

    for sr in scan_results:
        if not sr.sys_updated_by or not sr.sys_updated_on:
            records_skipped += 1
            continue
        by_developer[sr.sys_updated_by].append(sr)

    records_processed = len(scan_results) - records_skipped

    # ------------------------------------------------------------------
    # 6. Walk each developer group and form clusters
    # ------------------------------------------------------------------
    clusters_created = 0
    members_created = 0
    errors: List[str] = []

    for developer, dev_records in by_developer.items():
        # Sort by sys_updated_on ascending
        dev_records.sort(key=lambda r: r.sys_updated_on)  # type: ignore[arg-type]

        # Walk and split on gap > threshold
        current_cluster: List[ScanResult] = [dev_records[0]]

        for i in range(1, len(dev_records)):
            prev_time: datetime = dev_records[i - 1].sys_updated_on  # type: ignore[assignment]
            curr_time: datetime = dev_records[i].sys_updated_on  # type: ignore[assignment]
            gap_minutes = (curr_time - prev_time).total_seconds() / 60.0

            if gap_minutes <= gap_threshold:
                current_cluster.append(dev_records[i])
            else:
                # Emit the accumulated cluster if large enough
                if len(current_cluster) >= min_cluster_size:
                    c, m = _emit_cluster(
                        session, instance_id, assessment_id, developer, current_cluster
                    )
                    clusters_created += c
                    members_created += m
                # Start a new cluster
                current_cluster = [dev_records[i]]

        # Emit final cluster for this developer
        if len(current_cluster) >= min_cluster_size:
            c, m = _emit_cluster(
                session, instance_id, assessment_id, developer, current_cluster
            )
            clusters_created += c
            members_created += m

    # ------------------------------------------------------------------
    # 7. Commit and return summary
    # ------------------------------------------------------------------
    session.commit()

    return {
        "success": True,
        "clusters_created": clusters_created,
        "members_created": members_created,
        "records_processed": records_processed,
        "records_skipped": records_skipped,
        "errors": errors,
    }


def _emit_cluster(
    session: Session,
    instance_id: int,
    assessment_id: int,
    developer: str,
    cluster_members: List[ScanResult],
) -> tuple[int, int]:
    """Persist a single TemporalCluster and its member rows.

    Returns (clusters_created, members_created) counts.
    """
    cluster_start: datetime = cluster_members[0].sys_updated_on  # type: ignore[assignment]
    cluster_end: datetime = cluster_members[-1].sys_updated_on  # type: ignore[assignment]

    # Compute average gap between consecutive records
    if len(cluster_members) > 1:
        total_gap = 0.0
        for i in range(1, len(cluster_members)):
            t_prev: datetime = cluster_members[i - 1].sys_updated_on  # type: ignore[assignment]
            t_curr: datetime = cluster_members[i].sys_updated_on  # type: ignore[assignment]
            total_gap += (t_curr - t_prev).total_seconds() / 60.0
        avg_gap_minutes = total_gap / (len(cluster_members) - 1)
    else:
        avg_gap_minutes = 0.0

    record_ids = [sr.id for sr in cluster_members]
    tables_involved = list({sr.table_name for sr in cluster_members})

    cluster = TemporalCluster(
        instance_id=instance_id,
        assessment_id=assessment_id,
        developer=developer,
        cluster_start=cluster_start,
        cluster_end=cluster_end,
        record_count=len(cluster_members),
        record_ids_json=json.dumps(record_ids),
        avg_gap_minutes=round(avg_gap_minutes, 2),
        tables_involved_json=json.dumps(tables_involved),
    )
    session.add(cluster)
    session.flush()  # Assign cluster.id for FK

    members_created = 0
    for sr in cluster_members:
        session.add(
            TemporalClusterMember(
                instance_id=instance_id,
                assessment_id=assessment_id,
                temporal_cluster_id=cluster.id,
                scan_result_id=sr.id,
            )
        )
        members_created += 1

    return 1, members_created
