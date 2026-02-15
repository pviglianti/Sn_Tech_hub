"""Artifact Detail API Routes.

Provides endpoints for browsing and viewing artifact details pulled from
ServiceNow after assessment scans.  All data lives in the per-class
asmt_* mirror tables (created by artifact_ddl.py).

Relationship: scan_result.table_name → ARTIFACT_DETAIL_DEFS[class_name]["local_table"]
              + _instance_id + sys_id = unique artifact record
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlmodel import Session, select

from ...artifact_detail_defs import (
    ARTIFACT_DETAIL_DEFS,
    COMMON_INHERITED_FIELDS,
    get_detail_def,
)
from ...database import engine, get_session
from ...models import Assessment, Instance, Scan, ScanResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
artifacts_router = APIRouter(tags=["artifacts"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_class_label(sys_class_name: str) -> str:
    """User-friendly label for an artifact class."""
    from ...app_file_class_catalog import APP_FILE_CLASS_CATALOG

    for entry in APP_FILE_CLASS_CATALOG:
        if entry["sys_class_name"] == sys_class_name:
            return entry["label"]
    defn = ARTIFACT_DETAIL_DEFS.get(sys_class_name)
    if defn:
        return defn["local_table"].replace("asmt_", "").replace("_", " ").title()
    return sys_class_name


def _field_labels(sys_class_name: str) -> Dict[str, str]:
    """Return {sn_element: display_label} for all fields in a class def."""
    defn = ARTIFACT_DETAIL_DEFS.get(sys_class_name)
    if not defn:
        return {}
    labels: Dict[str, str] = {"sys_id": "Sys ID"}
    for sn_element, label, _py_type in defn["fields"]:
        labels[sn_element] = label
    for sn_element, label, _py_type in COMMON_INHERITED_FIELDS:
        if sn_element not in labels:
            labels[sn_element] = label
    return labels


def _query_artifact_table(
    sys_class_name: str,
    instance_id: int,
    sys_ids: Optional[List[str]] = None,
    fields: Optional[List[str]] = None,
    limit: int = 500,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Query an asmt_* table by instance_id and optional sys_id filter.

    Returns (rows_as_dicts, total_count).
    """
    defn = ARTIFACT_DETAIL_DEFS.get(sys_class_name)
    if not defn:
        return [], 0
    local_table = defn["local_table"]

    # Build column list
    if fields:
        select_cols = ", ".join(f'"{f}"' for f in fields)
    else:
        select_cols = "*"

    where_parts = ["_instance_id = :instance_id"]
    params: Dict[str, Any] = {"instance_id": instance_id}

    if sys_ids:
        placeholders = ", ".join(f":sid_{i}" for i in range(len(sys_ids)))
        where_parts.append(f"sys_id IN ({placeholders})")
        for i, sid in enumerate(sys_ids):
            params[f"sid_{i}"] = sid

    where_clause = " AND ".join(where_parts)

    with engine.connect() as conn:
        # Total count
        count_sql = f'SELECT COUNT(*) FROM "{local_table}" WHERE {where_clause}'
        total = conn.execute(text(count_sql), params).scalar() or 0

        # Data query
        data_sql = (
            f'SELECT {select_cols} FROM "{local_table}" WHERE {where_clause}'
            f" ORDER BY name ASC, sys_id ASC LIMIT :lim OFFSET :off"
        )
        params["lim"] = limit
        params["off"] = offset
        rows = conn.execute(text(data_sql), params).fetchall()

        # Convert to dicts
        if rows:
            columns = rows[0]._fields if hasattr(rows[0], "_fields") else rows[0].keys()
            result = [dict(zip(columns, row)) for row in rows]
        else:
            result = []

    return result, total


# ---------------------------------------------------------------------------
# 3a. Single artifact record
# ---------------------------------------------------------------------------


@artifacts_router.get("/api/artifacts/{sys_class_name}/{sys_id}")
async def api_artifact_detail(
    sys_class_name: str,
    sys_id: str,
    instance_id: int = Query(...),
):
    """Return full field-value details for a single artifact record."""
    defn = get_detail_def(sys_class_name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown artifact class: {sys_class_name}")

    rows, _total = _query_artifact_table(
        sys_class_name=sys_class_name,
        instance_id=instance_id,
        sys_ids=[sys_id],
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Artifact not found")

    record = rows[0]
    labels = _field_labels(sys_class_name)

    # Build field_rows for display (ordered: class fields first, then common)
    field_rows = []
    ordered_fields = ["sys_id"] + [f[0] for f in defn["fields"]] + [f[0] for f in COMMON_INHERITED_FIELDS]
    seen = set()
    for field_name in ordered_fields:
        if field_name in seen:
            continue
        seen.add(field_name)
        if field_name in record:
            field_rows.append({
                "field": field_name,
                "label": labels.get(field_name, field_name),
                "value": record[field_name],
            })

    # Code fields (script, html, css, etc.)
    code_fields = defn.get("code_fields", [])
    code_contents = []
    for cf in code_fields:
        content = record.get(cf)
        if content:
            code_contents.append({
                "field": cf,
                "label": labels.get(cf, cf),
                "content": content,
            })

    # Raw JSON
    raw_json = record.get("_raw_json")

    return {
        "sys_class_name": sys_class_name,
        "sys_id": sys_id,
        "instance_id": instance_id,
        "label": _get_class_label(sys_class_name),
        "field_rows": field_rows,
        "code_fields": code_fields,
        "code_contents": code_contents,
        "raw_json": raw_json,
    }


# ---------------------------------------------------------------------------
# 3b. Assessment artifacts list
# ---------------------------------------------------------------------------


@artifacts_router.get("/api/assessments/{assessment_id}/artifacts")
async def api_assessment_artifacts(
    assessment_id: int,
    sys_class_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """Return artifacts for all scan results in an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    # Collect distinct (table_name, sys_id) from scan results
    scans = session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all()
    scan_ids = list(scans)
    if not scan_ids:
        return {"artifacts": [], "total": 0, "classes": []}

    stmt = select(ScanResult.table_name, ScanResult.sys_id).where(
        ScanResult.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
    )
    if sys_class_name:
        stmt = stmt.where(ScanResult.table_name == sys_class_name)
    result_rows = session.exec(stmt).all()

    # Group by class
    from collections import defaultdict
    targets: Dict[str, set] = defaultdict(set)
    for tbl, sid in result_rows:
        if tbl and sid and tbl in ARTIFACT_DETAIL_DEFS:
            targets[tbl].add(sid)

    # Available class filters
    classes = [
        {"sys_class_name": cn, "label": _get_class_label(cn), "count": len(sids)}
        for cn, sids in sorted(targets.items())
    ]

    # Query artifact tables and combine results
    artifacts: List[Dict[str, Any]] = []
    total = 0
    summary_fields = ["sys_id", "name", "active", "sys_scope", "sys_updated_on"]

    for class_name, sys_ids in targets.items():
        defn = ARTIFACT_DETAIL_DEFS[class_name]
        # Pick available summary fields for this class
        avail_fields = ["sys_id"] + [f[0] for f in defn["fields"]] + [f[0] for f in COMMON_INHERITED_FIELDS]
        query_fields = [f for f in summary_fields if f in avail_fields]
        if not query_fields:
            query_fields = ["sys_id"]

        rows, count = _query_artifact_table(
            sys_class_name=class_name,
            instance_id=assessment.instance_id,
            sys_ids=list(sys_ids),
            fields=query_fields,
            limit=limit,
        )
        for row in rows:
            row["sys_class_name"] = class_name
            row["class_label"] = _get_class_label(class_name)
        artifacts.extend(rows)
        total += count

    # Sort combined list by name
    artifacts.sort(key=lambda r: (r.get("name") or "").lower())

    # Apply pagination to combined list
    paginated = artifacts[offset : offset + limit]

    return {
        "artifacts": paginated,
        "total": total,
        "classes": classes,
    }


# ---------------------------------------------------------------------------
# 3c. Scan artifacts list
# ---------------------------------------------------------------------------


@artifacts_router.get("/api/scans/{scan_id}/artifacts")
async def api_scan_artifacts(
    scan_id: int,
    sys_class_name: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    """Return artifacts for a single scan's results."""
    scan = session.get(Scan, scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    assessment = session.get(Assessment, scan.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    stmt = select(ScanResult.table_name, ScanResult.sys_id).where(
        ScanResult.scan_id == scan_id
    )
    if sys_class_name:
        stmt = stmt.where(ScanResult.table_name == sys_class_name)
    result_rows = session.exec(stmt).all()

    from collections import defaultdict
    targets: Dict[str, set] = defaultdict(set)
    for tbl, sid in result_rows:
        if tbl and sid and tbl in ARTIFACT_DETAIL_DEFS:
            targets[tbl].add(sid)

    classes = [
        {"sys_class_name": cn, "label": _get_class_label(cn), "count": len(sids)}
        for cn, sids in sorted(targets.items())
    ]

    artifacts: List[Dict[str, Any]] = []
    total = 0
    summary_fields = ["sys_id", "name", "active", "sys_scope", "sys_updated_on"]

    for class_name, sys_ids in targets.items():
        defn = ARTIFACT_DETAIL_DEFS[class_name]
        avail_fields = ["sys_id"] + [f[0] for f in defn["fields"]] + [f[0] for f in COMMON_INHERITED_FIELDS]
        query_fields = [f for f in summary_fields if f in avail_fields]
        if not query_fields:
            query_fields = ["sys_id"]

        rows, count = _query_artifact_table(
            sys_class_name=class_name,
            instance_id=assessment.instance_id,
            sys_ids=list(sys_ids),
            fields=query_fields,
            limit=limit,
        )
        for row in rows:
            row["sys_class_name"] = class_name
            row["class_label"] = _get_class_label(class_name)
        artifacts.extend(rows)
        total += count

    artifacts.sort(key=lambda r: (r.get("name") or "").lower())
    paginated = artifacts[offset : offset + limit]

    return {
        "artifacts": paginated,
        "total": total,
        "classes": classes,
    }


# ---------------------------------------------------------------------------
# 3d. Code content (script, html, css, etc.) for result main tab
# ---------------------------------------------------------------------------


@artifacts_router.get("/api/artifacts/{sys_class_name}/{sys_id}/code")
async def api_artifact_code(
    sys_class_name: str,
    sys_id: str,
    instance_id: int = Query(...),
):
    """Return all code field contents for an artifact (used on result main tab)."""
    defn = get_detail_def(sys_class_name)
    if not defn:
        return {"has_code": False, "code_fields": [], "code_contents": []}

    code_fields = defn.get("code_fields", [])
    if not code_fields:
        return {"has_code": False, "code_fields": [], "code_contents": []}

    rows, _ = _query_artifact_table(
        sys_class_name=sys_class_name,
        instance_id=instance_id,
        sys_ids=[sys_id],
        fields=code_fields,
        limit=1,
    )
    if not rows:
        return {"has_code": False, "code_fields": code_fields, "code_contents": []}

    labels = _field_labels(sys_class_name)
    record = rows[0]
    code_contents = []
    for cf in code_fields:
        content = record.get(cf)
        if content:
            code_contents.append({
                "field": cf,
                "label": labels.get(cf, cf),
                "content": content,
            })

    return {
        "has_code": bool(code_contents),
        "code_fields": code_fields,
        "code_contents": code_contents,
    }


# ---------------------------------------------------------------------------
# Artifact record page (HTML)
# ---------------------------------------------------------------------------


@artifacts_router.get("/artifacts/{sys_class_name}/{sys_id}", response_class=HTMLResponse)
async def artifact_record_page(
    request: Request,
    sys_class_name: str,
    sys_id: str,
    instance_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """Render a standalone artifact record detail page."""
    defn = get_detail_def(sys_class_name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Unknown artifact class: {sys_class_name}")

    instance = session.get(Instance, instance_id)

    return templates.TemplateResponse(
        "artifact_record.html",
        {
            "request": request,
            "sys_class_name": sys_class_name,
            "sys_id": sys_id,
            "instance_id": instance_id,
            "instance": instance,
            "class_label": _get_class_label(sys_class_name),
            "code_fields": defn.get("code_fields", []),
        },
    )
