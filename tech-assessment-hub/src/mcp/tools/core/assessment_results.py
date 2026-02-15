"""MCP tool: get_assessment_results — filtered, token-efficient results retrieval.

Returns condensed scan results for an assessment with optional filtering.
Does NOT include raw_data_json by default to keep token usage low.
"""

from typing import Any, Dict
from sqlmodel import Session, select, func, col

from ...registry import ToolSpec
from ....models import ScanResult, Scan, Assessment, OriginType


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to retrieve results for.",
        },
        "origin_type": {
            "type": "string",
            "enum": ["modified_ootb", "net_new_customer", "ootb_untouched", "unknown_no_history"],
            "description": "Filter by origin classification.",
        },
        "head_owner": {
            "type": "string",
            "enum": ["customer", "store_upgrade", "unknown"],
            "description": "Filter by head owner.",
        },
        "table_name": {
            "type": "string",
            "description": "Filter by ServiceNow table (e.g., sys_script).",
        },
        "customized_only": {
            "type": "boolean",
            "description": "If true (default), exclude ootb_untouched results.",
            "default": True,
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return (default 50).",
            "default": 50,
        },
        "offset": {
            "type": "integer",
            "description": "Offset for pagination (default 0).",
            "default": 0,
        },
    },
    "required": ["assessment_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = params.get("assessment_id")
    if assessment_id is None:
        raise ValueError("assessment_id is required")

    assessment = session.get(Assessment, int(assessment_id))
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    # Build query: ScanResult joined to Scan where scan belongs to assessment
    scan_ids_q = select(Scan.id).where(Scan.assessment_id == int(assessment_id))
    scan_ids = [row for row in session.exec(scan_ids_q).all()]

    if not scan_ids:
        return {"success": True, "total": 0, "results": [], "assessment_name": assessment.name}

    query = select(ScanResult).where(col(ScanResult.scan_id).in_(scan_ids))

    # Apply filters
    customized_only = params.get("customized_only", True)
    if customized_only:
        query = query.where(ScanResult.origin_type != OriginType.ootb_untouched)

    origin_type = params.get("origin_type")
    if origin_type:
        query = query.where(ScanResult.origin_type == origin_type)

    head_owner = params.get("head_owner")
    if head_owner:
        query = query.where(ScanResult.head_owner == head_owner)

    table_name = params.get("table_name")
    if table_name:
        query = query.where(ScanResult.table_name == table_name)

    # Count total before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    # Apply pagination
    limit = min(params.get("limit", 50), 200)
    offset = params.get("offset", 0)
    query = query.offset(offset).limit(limit)

    results = session.exec(query).all()

    # Return condensed fields (no raw_data_json)
    condensed = []
    for r in results:
        condensed.append({
            "id": r.id,
            "sys_id": r.sys_id,
            "table_name": r.table_name,
            "name": r.name,
            "display_value": r.display_value,
            "sys_class_name": r.sys_class_name,
            "origin_type": r.origin_type.value if r.origin_type else None,
            "head_owner": r.head_owner.value if r.head_owner else None,
            "review_status": r.review_status.value if r.review_status else None,
            "disposition": r.disposition.value if r.disposition else None,
            "sys_scope": r.sys_scope,
            "sys_created_by": r.sys_created_by,
            "sys_updated_on": r.sys_updated_on.isoformat() if r.sys_updated_on else None,
        })

    return {
        "success": True,
        "assessment_name": assessment.name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": condensed,
    }


TOOL_SPEC = ToolSpec(
    name="get_assessment_results",
    description=(
        "Retrieve filtered scan results for an assessment. Returns condensed fields "
        "(no raw data) for token efficiency. Use customized_only=true (default) to "
        "skip OOTB untouched records. Supports pagination with limit/offset."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
