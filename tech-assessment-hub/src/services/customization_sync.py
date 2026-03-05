"""Customization table sync helpers.

Keeps the customization child table in sync with scan_result.
Called from scan_executor (bulk after scan completion) and the
result update endpoint (per-record on reclassification/review changes).
"""

from typing import List, Optional

from sqlmodel import Session, select

from ..models import Customization, OriginType, ScanResult


CUSTOMIZED_ORIGIN_TYPES = {OriginType.modified_ootb, OriginType.net_new_customer}


def is_customized(origin_type: Optional[OriginType]) -> bool:
    """Return True if the origin_type counts as a customization."""
    return origin_type in CUSTOMIZED_ORIGIN_TYPES


def _build_customization_from_result(result: ScanResult) -> Customization:
    """Create a Customization row from a ScanResult."""
    return Customization(
        scan_result_id=result.id,
        scan_id=result.scan_id,
        sys_id=result.sys_id,
        table_name=result.table_name,
        name=result.name,
        origin_type=result.origin_type,
        head_owner=result.head_owner,
        sys_class_name=result.sys_class_name,
        sys_scope=result.sys_scope,
        review_status=result.review_status,
        disposition=result.disposition,
        recommendation=result.recommendation,
        observations=result.observations,
        sys_updated_on=result.sys_updated_on,
    )


def _copy_result_to_customization(row: Customization, result: ScanResult) -> bool:
    """Mirror result fields onto an existing customization row.

    Returns True when any persisted value changed.
    """
    changed = False

    updates = {
        "scan_id": result.scan_id,
        "sys_id": result.sys_id,
        "table_name": result.table_name,
        "name": result.name,
        "origin_type": result.origin_type,
        "head_owner": result.head_owner,
        "sys_class_name": result.sys_class_name,
        "sys_scope": result.sys_scope,
        "review_status": result.review_status,
        "disposition": result.disposition,
        "recommendation": result.recommendation,
        "observations": result.observations,
        "sys_updated_on": result.sys_updated_on,
    }

    for field_name, new_value in updates.items():
        if getattr(row, field_name) != new_value:
            setattr(row, field_name, new_value)
            changed = True

    return changed


def bulk_sync_for_scan(session: Session, scan_id: int, *, commit: bool = True) -> int:
    """Reconcile customization rows for all results in a scan.

    - INSERT missing rows for customized results.
    - UPDATE existing rows when mirrored fields drift.
    - DELETE stale rows for results no longer customized.

    Returns the number of inserted rows.
    """
    results = session.exec(
        select(ScanResult).where(ScanResult.scan_id == scan_id)
    ).all()
    results_by_id = {
        int(result.id): result for result in results if result.id is not None
    }

    existing_rows = session.exec(
        select(Customization).where(Customization.scan_id == scan_id)
    ).all()
    existing_by_result_id = {
        int(row.scan_result_id): row for row in existing_rows
    }

    inserted_count = 0
    updated_count = 0
    deleted_count = 0

    for result_id, result in results_by_id.items():
        if not is_customized(result.origin_type):
            continue
        existing = existing_by_result_id.get(result_id)
        if existing is None:
            session.add(_build_customization_from_result(result))
            inserted_count += 1
            continue
        if _copy_result_to_customization(existing, result):
            session.add(existing)
            updated_count += 1

    for result_id, row in existing_by_result_id.items():
        result = results_by_id.get(result_id)
        if result is None or not is_customized(result.origin_type):
            session.delete(row)
            deleted_count += 1

    if commit and (inserted_count or updated_count or deleted_count):
        session.commit()
    return inserted_count


def sync_single_result(session: Session, result: ScanResult, *, commit: bool = True) -> None:
    """Sync a single scan_result's customization row after an update.

    - If result is customized and no customization row exists -> INSERT
    - If result is customized and row exists -> UPDATE fields
    - If result is NOT customized and row exists -> DELETE
    """
    existing = session.exec(
        select(Customization)
        .where(Customization.scan_result_id == result.id)
    ).first()

    changed = False

    if is_customized(result.origin_type):
        if existing:
            changed = _copy_result_to_customization(existing, result)
            if changed:
                session.add(existing)
        else:
            session.add(_build_customization_from_result(result))
            changed = True
    elif existing:
        session.delete(existing)
        changed = True

    if commit and changed:
        session.commit()
