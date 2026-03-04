"""Engine 4: Structural Relationship Mapper.

Maps parent/child relationships between artifacts using known reference
field patterns (e.g., UI Policy -> UI Policy Actions).

Input: Artifact detail tables
Output: Rows in structural_relationship table
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select
from sqlalchemy import text

from ..models import Assessment, Scan, ScanResult, StructuralRelationship


_RELATIONSHIP_MAPPINGS: List[Dict[str, str]] = [
    {
        "child_sn_table": "sys_ui_policy_action",
        "child_local_table": "asmt_ui_policy_action",
        "ref_field": "ui_policy",
        "ref_type": "sys_id",
        "parent_sn_table": "sys_ui_policy",
        "relationship_type": "ui_policy_action",
    },
    {
        "child_sn_table": "sys_dictionary",
        "child_local_table": "asmt_dictionary",
        "ref_field": "collection_name",
        "ref_type": "table_name",
        "parent_sn_table": "sys_db_object",
        "relationship_type": "dictionary_entry",
    },
    {
        "child_sn_table": "sys_dictionary_override",
        "child_local_table": "asmt_dictionary_override",
        "ref_field": "collection_name",
        "ref_type": "table_name",
        "parent_sn_table": "sys_dictionary",
        "relationship_type": "dictionary_override",
    },
]


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the structural mapper engine for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "relationships_created": 0,
            "mappings_processed": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

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
            "relationships_created": 0,
            "mappings_processed": 0,
            "errors": [],
            "message": "No scan results",
        }

    # Make reruns idempotent per assessment.
    existing = list(
        session.exec(select(StructuralRelationship).where(StructuralRelationship.assessment_id == assessment_id)).all()
    )
    for row in existing:
        session.delete(row)
    session.flush()

    sr_by_sys_id: Dict[str, ScanResult] = {}
    sr_by_id: Dict[int, ScanResult] = {}
    sr_by_table_and_name: Dict[Tuple[str, str], ScanResult] = {}
    sr_by_meta_target: Dict[str, List[ScanResult]] = {}

    for sr in scan_results:
        if sr.id is not None:
            sr_by_id[sr.id] = sr
        sr_by_sys_id[sr.sys_id] = sr
        sr_by_table_and_name[(sr.table_name, sr.name)] = sr
        if sr.meta_target_table:
            sr_by_meta_target.setdefault(sr.meta_target_table, []).append(sr)

    relationships_created = 0
    mappings_processed = 0
    errors: List[str] = []

    for mapping in _RELATIONSHIP_MAPPINGS:
        child_local = mapping["child_local_table"]
        ref_field = mapping["ref_field"]
        ref_type = mapping["ref_type"]
        parent_sn_table = mapping["parent_sn_table"]
        rel_type = mapping["relationship_type"]

        exists = session.exec(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl").bindparams(
                tbl=child_local
            )
        ).first()
        if not exists:
            continue

        mappings_processed += 1

        sql = (
            f"SELECT scan_result_id, \"{ref_field}\" "
            f"FROM {child_local} "
            f"WHERE scan_result_id IS NOT NULL AND \"{ref_field}\" IS NOT NULL"
        )

        try:
            rows = session.exec(text(sql)).all()
        except Exception as exc:  # pragma: no cover - defensive branch
            errors.append(f"Error reading {child_local}: {exc}")
            continue

        for row in rows:
            values = tuple(row)
            if len(values) < 2:
                continue
            child_sr_id, ref_value = values[0], values[1]
            if child_sr_id is None or ref_value is None:
                continue

            child_sr = sr_by_id.get(int(child_sr_id))
            if not child_sr:
                continue

            parent_sr = _resolve_parent(
                ref_value=str(ref_value),
                ref_type=ref_type,
                parent_sn_table=parent_sn_table,
                sr_by_sys_id=sr_by_sys_id,
                sr_by_table_and_name=sr_by_table_and_name,
                sr_by_meta_target=sr_by_meta_target,
            )

            if not parent_sr or parent_sr.id is None or parent_sr.id == child_sr.id:
                continue

            session.add(
                StructuralRelationship(
                    instance_id=instance_id,
                    assessment_id=assessment_id,
                    parent_scan_result_id=parent_sr.id,
                    child_scan_result_id=child_sr.id,
                    relationship_type=rel_type,
                    parent_field=ref_field,
                    confidence=1.0,
                )
            )
            relationships_created += 1

    session.commit()

    return {
        "success": True,
        "relationships_created": relationships_created,
        "mappings_processed": mappings_processed,
        "errors": errors,
    }


def _resolve_parent(
    ref_value: str,
    ref_type: str,
    parent_sn_table: str,
    sr_by_sys_id: Dict[str, ScanResult],
    sr_by_table_and_name: Dict[Tuple[str, str], ScanResult],
    sr_by_meta_target: Dict[str, List[ScanResult]],
) -> Optional[ScanResult]:
    """Resolve a reference field value to a parent ScanResult."""
    if ref_type == "sys_id":
        return sr_by_sys_id.get(ref_value)

    if ref_type == "table_name":
        candidates = sr_by_meta_target.get(ref_value, [])
        for candidate in candidates:
            if candidate.table_name == parent_sn_table:
                return candidate
        return sr_by_table_and_name.get((parent_sn_table, ref_value))

    if ref_type == "name":
        return sr_by_table_and_name.get((parent_sn_table, ref_value))

    return None
