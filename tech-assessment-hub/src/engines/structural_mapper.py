"""Engine 4: Structural Relationship Mapper.

Maps parent/child relationships between artifacts using known reference
field patterns (e.g., UI Policy -> UI Policy Actions).

Input: Artifact detail tables
Output: Rows in structural_relationship table
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlmodel import Session, select
from sqlalchemy import text

from ..artifact_detail_defs import ARTIFACT_DETAIL_DEFS
from ..models import Assessment, Scan, ScanResult, StructuralRelationship


_RELATIONSHIP_MAPPINGS: List[Dict[str, str]] = [
    {
        "mapping_kind": "field_lookup",
        "child_sn_table": "sys_ui_policy_action",
        "child_local_table": str(ARTIFACT_DETAIL_DEFS["sys_ui_policy_action"]["local_table"]),
        "ref_field": "ui_policy",
        "ref_type": "sys_id",
        "parent_sn_table": "sys_ui_policy",
        "relationship_type": "ui_policy_action",
    },
    {
        "mapping_kind": "local_join",
        "child_sn_table": "sys_ui_policy_action",
        "child_local_table": str(ARTIFACT_DETAIL_DEFS["sys_ui_policy_action"]["local_table"]),
        "parent_local_table": str(ARTIFACT_DETAIL_DEFS["sys_dictionary"]["local_table"]),
        "join_fields": "table:name;field:element",
        "parent_sn_table": "sys_dictionary",
        "relationship_type": "ui_policy_field",
        "parent_field": "table,field",
    },
    {
        "mapping_kind": "field_lookup",
        "child_sn_table": "sys_dictionary",
        "child_local_table": str(ARTIFACT_DETAIL_DEFS["sys_dictionary"]["local_table"]),
        "ref_field": "name",
        "ref_type": "table_name",
        "parent_sn_table": "sys_db_object",
        "relationship_type": "dictionary_entry",
    },
    {
        "mapping_kind": "dictionary_override_lookup",
        "child_sn_table": "sys_dictionary_override",
        "child_local_table": str(ARTIFACT_DETAIL_DEFS["sys_dictionary_override"]["local_table"]),
        "parent_local_table": str(ARTIFACT_DETAIL_DEFS["sys_dictionary"]["local_table"]),
        "parent_sn_table": "sys_dictionary",
        "relationship_type": "dictionary_override",
        "parent_field": "name,element",
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
        mapping_kind = mapping.get("mapping_kind", "field_lookup")
        child_local = mapping["child_local_table"]
        rel_type = mapping["relationship_type"]

        if not _table_exists(session, child_local):
            continue
        parent_local = mapping.get("parent_local_table")
        if parent_local and not _table_exists(session, parent_local):
            continue

        mappings_processed += 1

        child_sn_table = mapping["child_sn_table"]

        try:
            if mapping_kind == "dictionary_override_lookup":
                rows = _load_dictionary_override_parent_rows(
                    session=session,
                    assessment_id=assessment_id,
                    instance_id=instance_id,
                    child_sn_table=child_sn_table,
                    child_local_table=child_local,
                    parent_local_table=str(parent_local),
                )
            elif mapping_kind == "local_join":
                rows = _load_local_join_rows(
                    session=session,
                    assessment_id=assessment_id,
                    child_sn_table=child_sn_table,
                    child_local_table=child_local,
                    parent_local_table=str(parent_local),
                    join_fields=str(mapping["join_fields"]),
                )
            else:
                rows = _load_field_lookup_rows(
                    session=session,
                    assessment_id=assessment_id,
                    child_sn_table=child_sn_table,
                    child_local_table=child_local,
                    ref_field=str(mapping["ref_field"]),
                )
        except Exception as exc:  # pragma: no cover - defensive branch
            errors.append(f"Error reading {child_local}: {exc}")
            continue

        for row in rows:
            values = tuple(row)
            if len(values) < 2:
                continue
            child_sr_id, parent_value = values[0], values[1]
            if child_sr_id is None or parent_value is None:
                continue

            child_sr = sr_by_id.get(int(child_sr_id))
            if not child_sr:
                continue

            if mapping_kind in {"local_join", "dictionary_override_lookup"}:
                parent_sr = sr_by_sys_id.get(str(parent_value))
                parent_field = mapping.get("parent_field", "sys_id")
            else:
                parent_sr = _resolve_parent(
                    ref_value=str(parent_value),
                    ref_type=str(mapping["ref_type"]),
                    parent_sn_table=str(mapping["parent_sn_table"]),
                    sr_by_sys_id=sr_by_sys_id,
                    sr_by_table_and_name=sr_by_table_and_name,
                    sr_by_meta_target=sr_by_meta_target,
                )
                parent_field = str(mapping["ref_field"])

            if not parent_sr or parent_sr.id is None or parent_sr.id == child_sr.id:
                continue

            session.add(
                StructuralRelationship(
                    instance_id=instance_id,
                    assessment_id=assessment_id,
                    parent_scan_result_id=parent_sr.id,
                    child_scan_result_id=child_sr.id,
                    relationship_type=rel_type,
                    parent_field=parent_field,
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


def _table_exists(session: Session, table_name: str) -> bool:
    return bool(
        session.exec(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl").bindparams(
                tbl=table_name
            )
        ).first()
    )


def _load_field_lookup_rows(
    session: Session,
    assessment_id: int,
    child_sn_table: str,
    child_local_table: str,
    ref_field: str,
):
    sql = (
        f"SELECT sr.id, art.\"{ref_field}\" "
        f"FROM scan_result sr "
        f"JOIN scan s ON s.id = sr.scan_id "
        f"JOIN assessment a ON a.id = s.assessment_id "
        f"JOIN {child_local_table} art ON art.sys_id = sr.sys_id AND art._instance_id = a.instance_id "
        f"WHERE s.assessment_id = :aid AND sr.table_name = :sn_table "
        f"AND art.\"{ref_field}\" IS NOT NULL"
    )
    return session.exec(text(sql).bindparams(aid=assessment_id, sn_table=child_sn_table)).all()


def _load_local_join_rows(
    session: Session,
    assessment_id: int,
    child_sn_table: str,
    child_local_table: str,
    parent_local_table: str,
    join_fields: str,
):
    join_pairs = [pair.split(":", 1) for pair in join_fields.split(";")]
    join_condition = " AND ".join(
        f'parent_art."{parent_field}" = child_art."{child_field}"'
        for child_field, parent_field in join_pairs
    )
    sql = (
        "SELECT DISTINCT sr.id, parent_art.\"sys_id\" "
        "FROM scan_result sr "
        "JOIN scan s ON s.id = sr.scan_id "
        "JOIN assessment a ON a.id = s.assessment_id "
        f"JOIN {child_local_table} child_art ON child_art.sys_id = sr.sys_id AND child_art._instance_id = a.instance_id "
        f"JOIN {parent_local_table} parent_art ON parent_art._instance_id = a.instance_id AND {join_condition} "
        "WHERE s.assessment_id = :aid AND sr.table_name = :sn_table "
        "AND parent_art.\"sys_id\" IS NOT NULL"
    )
    return session.exec(text(sql).bindparams(aid=assessment_id, sn_table=child_sn_table)).all()


def _load_dictionary_override_parent_rows(
    *,
    session: Session,
    assessment_id: int,
    instance_id: int,
    child_sn_table: str,
    child_local_table: str,
    parent_local_table: str,
):
    table_local = str(ARTIFACT_DETAIL_DEFS["sys_db_object"]["local_table"])
    if not _table_exists(session, table_local):
        return _load_local_join_rows(
            session=session,
            assessment_id=assessment_id,
            child_sn_table=child_sn_table,
            child_local_table=child_local_table,
            parent_local_table=parent_local_table,
            join_fields="name:name;element:element",
        )

    override_rows = session.exec(
        text(
            f"SELECT sr.id, child_art.\"name\", child_art.\"element\" "
            f"FROM scan_result sr "
            f"JOIN scan s ON s.id = sr.scan_id "
            f"JOIN assessment a ON a.id = s.assessment_id "
            f"JOIN {child_local_table} child_art ON child_art.sys_id = sr.sys_id AND child_art._instance_id = a.instance_id "
            f"WHERE s.assessment_id = :aid AND sr.table_name = :sn_table "
            f"AND child_art.\"name\" IS NOT NULL AND child_art.\"element\" IS NOT NULL"
        ).bindparams(aid=assessment_id, sn_table=child_sn_table)
    ).all()

    if not override_rows:
        return []

    table_rows = session.exec(
        text(
            f'SELECT "sys_id", "name", "super_class" '
            f'FROM {table_local} WHERE _instance_id = :inst_id'
        ).bindparams(inst_id=instance_id)
    ).all()

    table_name_by_sys_id: Dict[str, str] = {}
    parent_sys_id_by_name: Dict[str, str] = {}
    for row in table_rows:
        values = tuple(row)
        if len(values) < 3:
            continue
        sys_id = str(values[0] or "").strip()
        table_name = str(values[1] or "").strip().lower()
        super_class = str(values[2] or "").strip()
        if not table_name:
            continue
        if sys_id:
            table_name_by_sys_id[sys_id] = table_name
        if super_class:
            parent_sys_id_by_name[table_name] = super_class

    entry_rows = session.exec(
        text(
            f'SELECT "sys_id", "name", "element" '
            f'FROM {parent_local_table} WHERE _instance_id = :inst_id'
        ).bindparams(inst_id=instance_id)
    ).all()

    entry_sys_ids_by_key: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for row in entry_rows:
        values = tuple(row)
        if len(values) < 3:
            continue
        sys_id = str(values[0] or "").strip()
        table_name = str(values[1] or "").strip().lower()
        element = str(values[2] or "").strip().lower()
        if not sys_id or not table_name or not element:
            continue
        entry_sys_ids_by_key[(table_name, element)].append(sys_id)

    output_rows: List[Tuple[int, str]] = []
    seen_pairs: Set[Tuple[int, str]] = set()
    for row in override_rows:
        values = tuple(row)
        if len(values) < 3 or values[0] is None:
            continue
        child_sr_id = int(values[0])
        table_name = str(values[1] or "").strip().lower()
        element = str(values[2] or "").strip().lower()
        if not table_name or not element:
            continue
        for candidate_table_name in _table_name_lineage(
            table_name,
            parent_sys_id_by_name=parent_sys_id_by_name,
            table_name_by_sys_id=table_name_by_sys_id,
        ):
            for parent_sys_id in entry_sys_ids_by_key.get((candidate_table_name, element), []):
                key = (child_sr_id, parent_sys_id)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                output_rows.append((child_sr_id, parent_sys_id))

    return output_rows


def _table_name_lineage(
    table_name: str,
    *,
    parent_sys_id_by_name: Dict[str, str],
    table_name_by_sys_id: Dict[str, str],
) -> List[str]:
    lineage: List[str] = []
    seen: Set[str] = set()
    current = str(table_name or "").strip().lower()
    while current and current not in seen:
        lineage.append(current)
        seen.add(current)
        parent_sys_id = parent_sys_id_by_name.get(current)
        if not parent_sys_id:
            break
        current = table_name_by_sys_id.get(parent_sys_id, "").strip().lower()
    return lineage


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
