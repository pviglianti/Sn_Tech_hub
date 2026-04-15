"""Customization Child Table API Routes.

Provides endpoints for browsing the customization child table — a
denormalized projection of scan_result rows where origin_type is
'modified_ootb' or 'net_new_customer'.  MCP/AI can SELECT * without
filtering conditions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from ...database import engine, get_session
from ...models import Assessment, Customization, OriginType, Scan, ScanResult
from ...services.customization_sync import CUSTOMIZED_ORIGIN_TYPES, bulk_sync_for_scan

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
customizations_router = APIRouter(tags=["customizations"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_customization_payload(row: Customization) -> Dict[str, Any]:
    """Serialize a Customization row to a JSON-friendly dict."""
    return {
        "id": row.id,
        "scan_result_id": row.scan_result_id,
        "scan_id": row.scan_id,
        "sys_id": row.sys_id,
        "table_name": row.table_name,
        "name": row.name,
        "origin_type": row.origin_type.value if row.origin_type else None,
        "head_owner": row.head_owner.value if row.head_owner else None,
        "sys_class_name": row.sys_class_name,
        "sys_scope": row.sys_scope,
        "review_status": row.review_status.value if row.review_status else None,
        "disposition": row.disposition.value if row.disposition else None,
        "recommendation": row.recommendation,
        "observations": row.observations,
        "sys_updated_on": row.sys_updated_on.isoformat() if row.sys_updated_on else None,
        "is_out_of_scope": bool(row.is_out_of_scope),
    }


def _normalize_scope_state(value: Optional[str]) -> str:
    normalized = str(value or "all").strip().lower()
    if normalized in {"all", "in_scope", "out_of_scope"}:
        return normalized
    return "all"


def _apply_scope_state_filter(stmt: Any, scope_state: str) -> Any:
    if scope_state == "in_scope":
        return stmt.where(Customization.is_out_of_scope == False)  # noqa: E712
    if scope_state == "out_of_scope":
        return stmt.where(Customization.is_out_of_scope == True)  # noqa: E712
    return stmt


def _customization_class_breakdown(
    session: Session,
    scan_ids: List[int],
    *,
    origin_type: Optional[str] = None,
    scope_state: str = "all",
) -> List[Dict[str, Any]]:
    stmt = select(Customization.table_name).where(
        Customization.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
    )
    if origin_type:
        stmt = stmt.where(Customization.origin_type == origin_type)
    stmt = _apply_scope_state_filter(stmt, scope_state)

    counts: Dict[str, int] = defaultdict(int)
    for value in session.exec(stmt).all():
        key = str(value or "").strip()
        if key:
            counts[key] += 1

    return [
        {"table_name": table_name, "label": table_name, "count": count}
        for table_name, count in sorted(counts.items())
    ]


def _heal_missing_customization_rows(session: Session, scan_ids: List[int]) -> int:
    """Backfill customization rows for scans with stale/missing child-table data.

    Returns number of inserted customization rows.
    """
    if not scan_ids:
        return 0

    customized_counts_stmt = (
        select(ScanResult.scan_id, func.count(ScanResult.id))
        .where(ScanResult.scan_id.in_(scan_ids))  # type: ignore[attr-defined]
        .where(
            ScanResult.origin_type.in_(  # type: ignore[attr-defined]
                [origin.value for origin in CUSTOMIZED_ORIGIN_TYPES]
            )
        )
        .group_by(ScanResult.scan_id)
    )
    customized_counts = {
        scan_id: count for scan_id, count in session.exec(customized_counts_stmt).all()
    }

    existing_counts_stmt = (
        select(Customization.scan_id, func.count(Customization.id))
        .where(Customization.scan_id.in_(scan_ids))  # type: ignore[attr-defined]
        .group_by(Customization.scan_id)
    )
    existing_counts = {
        scan_id: count for scan_id, count in session.exec(existing_counts_stmt).all()
    }

    stale_scan_ids = [
        scan_id
        for scan_id in scan_ids
        if existing_counts.get(scan_id, 0) != customized_counts.get(scan_id, 0)
    ]
    if not stale_scan_ids:
        return 0

    inserted = 0
    for scan_id in stale_scan_ids:
        inserted += bulk_sync_for_scan(session, scan_id)

    if inserted:
        logger.info(
            "Auto-healed customization rows",
            extra={
                "scan_count": len(stale_scan_ids),
                "inserted_rows": inserted,
            },
        )
    return inserted


def _query_customizations(
    session: Session,
    scan_ids: List[int],
    origin_type: Optional[str] = None,
    table_name: Optional[str] = None,
    scope_state: str = "all",
    limit: int = 500,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Shared query logic for customization endpoints.

    Returns (rows_as_dicts, total_count).
    """
    if not scan_ids:
        return [], 0

    stmt = select(Customization).where(
        Customization.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
    )

    if origin_type:
        stmt = stmt.where(Customization.origin_type == origin_type)
    if table_name:
        stmt = stmt.where(Customization.table_name == table_name)
    stmt = _apply_scope_state_filter(stmt, scope_state)

    # Count query (same filters, no limit/offset)
    count_stmt = select(Customization.id).where(
        Customization.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
    )
    if origin_type:
        count_stmt = count_stmt.where(Customization.origin_type == origin_type)
    if table_name:
        count_stmt = count_stmt.where(Customization.table_name == table_name)
    count_stmt = _apply_scope_state_filter(count_stmt, scope_state)
    total = len(session.exec(count_stmt).all())

    # Data query with ordering and pagination
    stmt = stmt.order_by(Customization.table_name, Customization.name)  # type: ignore[arg-type]
    stmt = stmt.offset(offset).limit(limit)
    rows = session.exec(stmt).all()

    return [_build_customization_payload(row) for row in rows], total


# ---------------------------------------------------------------------------
# 1. List customizations for an assessment
# ---------------------------------------------------------------------------


@customizations_router.get("/api/assessments/{assessment_id}/customizations")
async def api_assessment_customizations(
    assessment_id: int,
    origin_type: Optional[str] = Query(default=None),
    table_name: Optional[str] = Query(default=None),
    scope_state: str = Query(default="all"),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """Return customizations for all scans in an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    scan_ids = list(
        session.exec(select(Scan.id).where(Scan.assessment_id == assessment_id)).all()
    )
    if not scan_ids:
        return {"customizations": [], "total": 0}

    _heal_missing_customization_rows(session, scan_ids)

    resolved_scope_state = _normalize_scope_state(scope_state)
    rows, total = _query_customizations(
        session, scan_ids,
        origin_type=origin_type,
        table_name=table_name,
        scope_state=resolved_scope_state,
        limit=limit,
        offset=offset,
    )
    classes = _customization_class_breakdown(
        session,
        scan_ids,
        origin_type=origin_type,
        scope_state=resolved_scope_state,
    )

    return {"customizations": rows, "total": total, "classes": classes}


# ---------------------------------------------------------------------------
# 2. List customizations for a scan
# ---------------------------------------------------------------------------


@customizations_router.get("/api/scans/{scan_id}/customizations")
async def api_scan_customizations(
    scan_id: int,
    origin_type: Optional[str] = Query(default=None),
    table_name: Optional[str] = Query(default=None),
    scope_state: str = Query(default="all"),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """Return customizations for a single scan."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    _heal_missing_customization_rows(session, [scan_id])

    resolved_scope_state = _normalize_scope_state(scope_state)
    rows, total = _query_customizations(
        session, [scan_id],
        origin_type=origin_type,
        table_name=table_name,
        scope_state=resolved_scope_state,
        limit=limit,
        offset=offset,
    )
    classes = _customization_class_breakdown(
        session,
        [scan_id],
        origin_type=origin_type,
        scope_state=resolved_scope_state,
    )

    return {"customizations": rows, "total": total, "classes": classes}


# ---------------------------------------------------------------------------
# 3. Filter options (class breakdown with counts)
# ---------------------------------------------------------------------------


@customizations_router.get("/api/customizations/options")
async def api_customization_options(
    assessment_id: Optional[int] = Query(default=None),
    scan_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
):
    """Return class breakdown with counts for filter UI.

    Provide either assessment_id or scan_id to scope the results.
    """
    scan_ids: List[int] = []

    if scan_id is not None:
        scan = session.get(Scan, scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        scan_ids = [scan_id]
    elif assessment_id is not None:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            raise HTTPException(status_code=404, detail="Assessment not found")
        scan_ids = list(
            session.exec(
                select(Scan.id).where(Scan.assessment_id == assessment_id)
            ).all()
        )

    if not scan_ids:
        return {"classes": []}

    _heal_missing_customization_rows(session, scan_ids)

    stmt = select(Customization.sys_class_name).where(
        Customization.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
    )
    class_names = session.exec(stmt).all()

    counts: Dict[str, int] = defaultdict(int)
    for cn in class_names:
        key = cn or "(none)"
        counts[key] += 1

    classes = [
        {"sys_class_name": cn, "count": ct}
        for cn, ct in sorted(counts.items())
    ]

    return {"classes": classes}
