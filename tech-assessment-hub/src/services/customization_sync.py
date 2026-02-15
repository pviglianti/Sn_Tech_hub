"""Customization table sync helpers.

Keeps the customization child table in sync with scan_result.
Called from scan_executor (bulk after scan completion) and the
result update endpoint (per-record on reclassification/review changes).
"""

from typing import List, Optional, Set

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


def bulk_sync_for_scan(session: Session, scan_id: int) -> int:
    """Populate customization rows for all customized results in a scan.

    Typically called once after scan_executor completes a scan.
    Skips results that already have a customization row.
    Returns the number of rows inserted.
    """
    results = session.exec(
        select(ScanResult)
        .where(ScanResult.scan_id == scan_id)
        .where(ScanResult.origin_type.in_([ot.value for ot in CUSTOMIZED_ORIGIN_TYPES]))
    ).all()

    existing_result_ids: Set[int] = set(
        session.exec(
            select(Customization.scan_result_id)
            .where(Customization.scan_id == scan_id)
        ).all()
    )

    count = 0
    for result in results:
        if result.id not in existing_result_ids:
            session.add(_build_customization_from_result(result))
            count += 1

    if count:
        session.commit()
    return count


def sync_single_result(session: Session, result: ScanResult) -> None:
    """Sync a single scan_result's customization row after an update.

    - If result is customized and no customization row exists -> INSERT
    - If result is customized and row exists -> UPDATE fields
    - If result is NOT customized and row exists -> DELETE
    """
    existing = session.exec(
        select(Customization)
        .where(Customization.scan_result_id == result.id)
    ).first()

    if is_customized(result.origin_type):
        if existing:
            existing.origin_type = result.origin_type
            existing.head_owner = result.head_owner
            existing.review_status = result.review_status
            existing.disposition = result.disposition
            existing.recommendation = result.recommendation
            existing.observations = result.observations
            existing.name = result.name
            existing.sys_scope = result.sys_scope
            existing.sys_updated_on = result.sys_updated_on
            session.add(existing)
        else:
            session.add(_build_customization_from_result(result))
        session.commit()
    elif existing:
        session.delete(existing)
        session.commit()
