"""MCP tool: generate_assessment_report — server-side report generation.

Produces .xlsx and/or .docx deliverables, persists them on the VM under
DATA_DIR/reports/{assessment_id}/, and returns download URLs so the user
can grab them from the web app.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session

from ...registry import ToolSpec
from ....services.report_generator import generate_reports


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to generate the report for.",
        },
        "formats": {
            "type": "array",
            "items": {"type": "string", "enum": ["xlsx", "docx"]},
            "description": "Which formats to produce. Default both.",
            "default": ["xlsx", "docx"],
        },
        "generated_by": {
            "type": "string",
            "description": "Optional — who/what triggered generation (e.g. 'report skill via Claude Desktop').",
        },
    },
    "required": ["assessment_id"],
}


def handle(session: Session, params: Dict[str, Any]) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    formats = params.get("formats") or ["xlsx", "docx"]
    generated_by = params.get("generated_by")

    reports = generate_reports(
        session=session,
        assessment_id=assessment_id,
        formats=formats,
        generated_by=generated_by,
    )

    return {
        "assessment_id": assessment_id,
        "generated_count": len(reports),
        "reports": [
            {
                "report_id": r.id,
                "filename": r.filename,
                "format": r.format,
                "file_size": r.file_size,
                "sha256": r.sha256,
                "generated_at": r.generated_at.isoformat(),
                "download_url": f"/api/reports/{r.id}/download",
                "view_in_app_url": f"/assessments/{assessment_id}",
            }
            for r in reports
        ],
        "instructions": (
            "Reports are saved on the server. Tell the user:\n"
            "- They can download via `https://136-112-232-229.nip.io/api/reports/{report_id}/download`\n"
            "- Or open the assessment page at "
            "`https://136-112-232-229.nip.io/assessments/{assessment_id}` to see all "
            "reports in the Reports panel."
        ),
    }


TOOL_SPEC = ToolSpec(
    name="generate_assessment_report",
    description=(
        "Generate Excel and/or Word report deliverables for an assessment, "
        "server-side. Files are saved on the VM, registered in the database, "
        "and exposed via the web UI's Reports panel + download URLs. "
        "Use this in the report-generation stage."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
