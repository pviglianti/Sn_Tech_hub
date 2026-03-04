"""Engine: Table Co-location.

Groups ScanResults by their target table (meta_target_table) to identify
artifacts that customize the same ServiceNow table.  Tables with 2+
co-located artifacts produce a TableColocationSummary row.

Input:  ScanResult rows (via Scan -> Assessment join)
Output: Rows in table_colocation_summary table
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List

from sqlmodel import Session, select

from ..models import Assessment, Scan, ScanResult, TableColocationSummary


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the table co-location engine for an assessment."""

    # 1. Validate assessment exists
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "summaries_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

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
            "summaries_created": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # 3. Delete existing summaries for idempotency
    existing = list(
        session.exec(
            select(TableColocationSummary).where(
                TableColocationSummary.assessment_id == assessment_id
            )
        ).all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    # 4. Filter to records with a non-null, non-empty meta_target_table
    #    and group by target table
    groups: Dict[str, List[ScanResult]] = defaultdict(list)
    for sr in scan_results:
        target = sr.meta_target_table
        if target and target.strip():
            groups[target].append(sr)

    # 5. Create summaries for groups with 2+ members
    summaries_created = 0
    errors: List[str] = []

    for target_table, members in groups.items():
        if len(members) < 2:
            continue

        record_ids = [sr.id for sr in members if sr.id is not None]
        artifact_types = sorted(set(sr.table_name for sr in members))
        developers = sorted(
            set(sr.sys_updated_by for sr in members if sr.sys_updated_by)
        )

        session.add(
            TableColocationSummary(
                instance_id=instance_id,
                assessment_id=assessment_id,
                target_table=target_table,
                record_count=len(members),
                record_ids_json=json.dumps(record_ids),
                artifact_types_json=json.dumps(artifact_types),
                developers_json=json.dumps(developers),
            )
        )
        summaries_created += 1

    # 6. Commit and return
    session.commit()

    return {
        "success": True,
        "summaries_created": summaries_created,
        "errors": errors,
    }
