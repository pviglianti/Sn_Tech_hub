"""Web routes for assessment reports — list, generate, download."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import Session, select

from ...database import get_session
from ...models import Assessment, AssessmentReport
from ...services.report_generator import generate_reports, list_reports

logger = logging.getLogger(__name__)


_FORMAT_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


reports_router = APIRouter(tags=["reports"])


@reports_router.get("/api/assessments/{assessment_id}/reports")
def api_list_assessment_reports(
    assessment_id: int,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail=f"Assessment {assessment_id} not found")
    rows = list_reports(session, assessment_id)
    return {
        "assessment_id": assessment_id,
        "count": len(rows),
        "reports": [
            {
                "report_id": r.id,
                "filename": r.filename,
                "format": r.format,
                "file_size": r.file_size,
                "sha256": r.sha256,
                "generated_by": r.generated_by,
                "generated_at": r.generated_at.isoformat(),
                "download_url": f"/api/reports/{r.id}/download",
            }
            for r in rows
        ],
    }


@reports_router.post("/api/assessments/{assessment_id}/reports/generate")
def api_generate_assessment_report(
    assessment_id: int,
    payload: Optional[Dict[str, Any]] = None,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail=f"Assessment {assessment_id} not found")
    payload = payload or {}
    formats = payload.get("formats") or ["xlsx", "docx"]
    generated_by = payload.get("generated_by") or "web_ui"
    try:
        rows = generate_reports(
            session=session,
            assessment_id=assessment_id,
            formats=formats,
            generated_by=generated_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Report generation failed for assessment %s", assessment_id)
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")
    return {
        "assessment_id": assessment_id,
        "generated_count": len(rows),
        "reports": [
            {
                "report_id": r.id,
                "filename": r.filename,
                "format": r.format,
                "file_size": r.file_size,
                "download_url": f"/api/reports/{r.id}/download",
            }
            for r in rows
        ],
    }


@reports_router.get("/api/reports/{report_id}/download")
def api_download_report(
    report_id: int,
    session: Session = Depends(get_session),
):
    row = session.get(AssessmentReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    path = Path(row.file_path)
    if not path.exists():
        raise HTTPException(
            status_code=410,
            detail=f"File missing on disk for report {report_id} (path: {row.file_path})",
        )
    media_type = _FORMAT_MIME.get(row.format, "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        filename=row.filename,
    )
