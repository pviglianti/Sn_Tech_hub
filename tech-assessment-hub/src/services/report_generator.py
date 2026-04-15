"""Server-side report generation for an Assessment.

Produces:
  - {DATA_DIR}/reports/{assessment_id}/assessment_{number}_report_{timestamp}.xlsx
  - {DATA_DIR}/reports/{assessment_id}/assessment_{number}_report_{timestamp}.docx

Each generation creates new AssessmentReport rows so history is preserved.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from docx import Document
from docx.shared import Pt

from ..database import DATA_DIR
from ..models import (
    Assessment,
    AssessmentReport,
    Feature,
    GlobalApp,
    ScanResult,
    Scan,
)


logger = logging.getLogger(__name__)


def _reports_dir(assessment_id: int) -> Path:
    out = DATA_DIR / "reports" / str(assessment_id)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _load_json_list(raw: Optional[str]) -> List[Any]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _gather_report_data(session: Session, assessment_id: int) -> Dict[str, Any]:
    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise ValueError(f"Assessment {assessment_id} not found")

    target_app: Optional[GlobalApp] = None
    if assessment.target_app_id:
        target_app = session.get(GlobalApp, assessment.target_app_id)

    # Pull all scan results for this assessment via its scans
    scan_ids = [s.id for s in assessment.scans] if assessment.scans else []
    results: List[ScanResult] = []
    if scan_ids:
        results = list(session.exec(
            select(ScanResult).where(ScanResult.scan_id.in_(scan_ids))
        ).all())

    features = list(session.exec(
        select(Feature).where(Feature.assessment_id == assessment_id)
    ).all())
    features_by_id = {f.id: f for f in features}

    # Bucket
    in_scope: List[ScanResult] = []
    adjacent: List[ScanResult] = []
    out_of_scope: List[ScanResult] = []
    for r in results:
        if getattr(r, "is_out_of_scope", False):
            out_of_scope.append(r)
        elif getattr(r, "is_adjacent", False):
            adjacent.append(r)
        else:
            in_scope.append(r)

    customized = [r for r in results if not getattr(r, "is_out_of_scope", False)]

    return {
        "assessment": assessment,
        "target_app": target_app,
        "core_tables": _load_json_list(target_app.core_tables_json) if target_app else [],
        "explicit_target_tables": _load_json_list(assessment.target_tables_json),
        "file_classes": _load_json_list(assessment.app_file_classes_json),
        "results": results,
        "in_scope": in_scope,
        "adjacent": adjacent,
        "out_of_scope": out_of_scope,
        "customized": customized,
        "features": features,
        "features_by_id": features_by_id,
    }


# ────────────────────────────────────────────────────────────────────────
# Excel
# ────────────────────────────────────────────────────────────────────────

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")


def _autosize(ws, headers: List[str]) -> None:
    for i, h in enumerate(headers, start=1):
        col = get_column_letter(i)
        max_len = len(str(h))
        for row in ws.iter_rows(min_row=2, min_col=i, max_col=i, values_only=True):
            v = row[0]
            if v is None:
                continue
            l = len(str(v))
            if l > max_len:
                max_len = l
        ws.column_dimensions[col].width = min(max(max_len + 2, 10), 80)


def _write_header(ws, headers: List[str]) -> None:
    for i, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _build_xlsx(data: Dict[str, Any]) -> Workbook:
    wb = Workbook()

    # ─── Tab 1: Executive Summary ──────────────────────────
    ws = wb.active
    ws.title = "Executive Summary"
    a: Assessment = data["assessment"]
    target_app = data["target_app"]
    summary_rows = [
        ("Assessment ID", a.id),
        ("Number", a.number),
        ("Name", a.name),
        ("Type", str(a.assessment_type.value if hasattr(a.assessment_type, "value") else a.assessment_type)),
        ("State", str(a.state.value if hasattr(a.state, "value") else a.state)),
        ("Pipeline Stage", str(a.pipeline_stage.value if hasattr(a.pipeline_stage, "value") else a.pipeline_stage)),
        ("Target App", target_app.label if target_app else "—"),
        ("Core Tables", ", ".join(data["core_tables"]) or "—"),
        ("Scope Filter", a.scope_filter),
        ("", ""),
        ("Total Results", len(data["results"])),
        ("In Scope", len(data["in_scope"])),
        ("Adjacent", len(data["adjacent"])),
        ("Out of Scope", len(data["out_of_scope"])),
        ("Features", len(data["features"])),
    ]
    ws.cell(row=1, column=1, value="Field").font = _HEADER_FONT
    ws.cell(row=1, column=2, value="Value").font = _HEADER_FONT
    ws.cell(row=1, column=1).fill = _HEADER_FILL
    ws.cell(row=1, column=2).fill = _HEADER_FILL
    for i, (k, v) in enumerate(summary_rows, start=2):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 60

    # ─── Tab 2: Feature Inventory ──────────────────────────
    ws = wb.create_sheet("Feature Inventory")
    headers = ["Feature ID", "Name", "Description", "Artifact Count", "Risk Level", "Recommendation", "AI Summary"]
    _write_header(ws, headers)
    feat_counts: Dict[int, int] = {}
    for r in data["customized"]:
        if r.feature_id:
            feat_counts[r.feature_id] = feat_counts.get(r.feature_id, 0) + 1
    feats_sorted = sorted(data["features"], key=lambda f: -feat_counts.get(f.id, 0))
    for row_idx, f in enumerate(feats_sorted, start=2):
        ws.cell(row=row_idx, column=1, value=f.id)
        ws.cell(row=row_idx, column=2, value=f.name)
        ws.cell(row=row_idx, column=3, value=f.description)
        ws.cell(row=row_idx, column=4, value=feat_counts.get(f.id, 0))
        ws.cell(row=row_idx, column=5, value=getattr(f, "change_risk_level", None))
        ws.cell(row=row_idx, column=6, value=getattr(f, "recommendation", None))
        ws.cell(row=row_idx, column=7, value=getattr(f, "ai_summary", None))
    _autosize(ws, headers)

    # ─── Tab 3: In-Scope Customizations ───────────────────
    ws = wb.create_sheet("In-Scope Customizations")
    headers = [
        "Result ID", "Name", "Table", "sys_class_name", "Origin",
        "Scope", "Feature", "Observations", "Recommendation",
    ]
    _write_header(ws, headers)
    in_scope_plus_adjacent = [r for r in data["customized"] if not getattr(r, "is_out_of_scope", False)]
    for row_idx, r in enumerate(in_scope_plus_adjacent, start=2):
        scope = "adjacent" if getattr(r, "is_adjacent", False) else "in_scope"
        feat = data["features_by_id"].get(r.feature_id) if r.feature_id else None
        ws.cell(row=row_idx, column=1, value=r.id)
        ws.cell(row=row_idx, column=2, value=getattr(r, "name", None))
        ws.cell(row=row_idx, column=3, value=getattr(r, "table_name", None))
        ws.cell(row=row_idx, column=4, value=getattr(r, "sys_class_name", None))
        ws.cell(row=row_idx, column=5, value=str(getattr(r, "origin_type", None) or ""))
        ws.cell(row=row_idx, column=6, value=scope)
        ws.cell(row=row_idx, column=7, value=feat.name if feat else "")
        ws.cell(row=row_idx, column=8, value=getattr(r, "observations", None))
        ws.cell(row=row_idx, column=9, value=getattr(r, "recommendation", None))
    _autosize(ws, headers)

    # ─── Tab 4: Out of Scope ──────────────────────────────
    ws = wb.create_sheet("Out of Scope")
    headers = ["Result ID", "Name", "Table", "sys_class_name", "Origin", "Observations"]
    _write_header(ws, headers)
    for row_idx, r in enumerate(data["out_of_scope"], start=2):
        ws.cell(row=row_idx, column=1, value=r.id)
        ws.cell(row=row_idx, column=2, value=getattr(r, "name", None))
        ws.cell(row=row_idx, column=3, value=getattr(r, "table_name", None))
        ws.cell(row=row_idx, column=4, value=getattr(r, "sys_class_name", None))
        ws.cell(row=row_idx, column=5, value=str(getattr(r, "origin_type", None) or ""))
        ws.cell(row=row_idx, column=6, value=getattr(r, "observations", None))
    _autosize(ws, headers)

    return wb


# ────────────────────────────────────────────────────────────────────────
# Word
# ────────────────────────────────────────────────────────────────────────

def _build_docx(data: Dict[str, Any]) -> Document:
    doc = Document()
    a: Assessment = data["assessment"]
    target_app = data["target_app"]

    # Title page
    doc.add_heading(f"Technical Assessment Report — {a.name}", level=0)
    p = doc.add_paragraph()
    p.add_run(f"Assessment {a.number}").bold = True
    doc.add_paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    if target_app:
        doc.add_paragraph(f"Target Application: {target_app.label}")
        doc.add_paragraph(f"Core Tables: {', '.join(data['core_tables'])}")
    doc.add_page_break()

    # Executive Summary
    doc.add_heading("Executive Summary", level=1)
    doc.add_paragraph(
        f"This assessment evaluated {len(data['results'])} ServiceNow artifacts. "
        f"{len(data['in_scope'])} were classified as in-scope, "
        f"{len(data['adjacent'])} as adjacent (in-scope but on a related table), "
        f"and {len(data['out_of_scope'])} as out-of-scope. "
        f"In-scope and adjacent artifacts were grouped into "
        f"{len(data['features'])} business features for review."
    )

    # Feature-by-Feature Analysis
    doc.add_heading("Feature-by-Feature Analysis", level=1)
    feat_counts: Dict[int, int] = {}
    for r in data["customized"]:
        if r.feature_id:
            feat_counts[r.feature_id] = feat_counts.get(r.feature_id, 0) + 1
    for f in sorted(data["features"], key=lambda f: -feat_counts.get(f.id, 0)):
        doc.add_heading(f.name or f"Feature {f.id}", level=2)
        if getattr(f, "description", None):
            doc.add_paragraph(f.description)
        meta = doc.add_paragraph()
        meta.add_run(f"Artifacts: {feat_counts.get(f.id, 0)}").bold = True
        if getattr(f, "change_risk_level", None):
            meta.add_run(f"   |   Risk: {f.change_risk_level}")
        if getattr(f, "recommendation", None):
            doc.add_paragraph("Recommendation:", style="Intense Quote")
            doc.add_paragraph(f.recommendation)

    # Appendix — counts by table
    doc.add_heading("Appendix — Counts by Table", level=1)
    by_table: Dict[str, int] = {}
    for r in data["customized"]:
        t = getattr(r, "table_name", None) or "(no table)"
        by_table[t] = by_table.get(t, 0) + 1
    for t, n in sorted(by_table.items(), key=lambda kv: -kv[1]):
        doc.add_paragraph(f"{t}: {n}", style="List Bullet")

    return doc


# ────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────

def generate_reports(
    session: Session,
    assessment_id: int,
    formats: Optional[List[str]] = None,
    generated_by: Optional[str] = None,
) -> List[AssessmentReport]:
    """Generate one or more report formats for an assessment.

    Returns the persisted AssessmentReport rows.
    """
    formats = [f.lower() for f in (formats or ["xlsx", "docx"]) if f]
    if not formats:
        raise ValueError("At least one format must be specified (xlsx, docx)")
    for f in formats:
        if f not in ("xlsx", "docx"):
            raise ValueError(f"Unsupported format: {f}")

    data = _gather_report_data(session, assessment_id)
    a: Assessment = data["assessment"]
    out_dir = _reports_dir(assessment_id)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base = f"assessment_{a.number}_{timestamp}"

    created: List[AssessmentReport] = []

    if "xlsx" in formats:
        wb = _build_xlsx(data)
        path = out_dir / f"{base}.xlsx"
        wb.save(path)
        created.append(_persist_report(session, assessment_id, path, "xlsx", generated_by))

    if "docx" in formats:
        doc = _build_docx(data)
        path = out_dir / f"{base}.docx"
        doc.save(path)
        created.append(_persist_report(session, assessment_id, path, "docx", generated_by))

    session.commit()
    for r in created:
        session.refresh(r)
    return created


def _persist_report(
    session: Session,
    assessment_id: int,
    path: Path,
    fmt: str,
    generated_by: Optional[str],
) -> AssessmentReport:
    file_bytes = path.read_bytes()
    sha = hashlib.sha256(file_bytes).hexdigest()
    row = AssessmentReport(
        assessment_id=assessment_id,
        filename=path.name,
        format=fmt,
        file_path=str(path),
        file_size=len(file_bytes),
        sha256=sha,
        generated_by=generated_by,
    )
    session.add(row)
    session.flush()
    return row


def list_reports(session: Session, assessment_id: int) -> List[AssessmentReport]:
    return list(session.exec(
        select(AssessmentReport)
        .where(AssessmentReport.assessment_id == assessment_id)
        .order_by(AssessmentReport.generated_at.desc())
    ).all())


def get_report(session: Session, report_id: int) -> Optional[AssessmentReport]:
    return session.get(AssessmentReport, report_id)
