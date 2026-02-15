"""MCP tool: get_customizations

Returns customized scan results from the customization child table.
No customized_only parameter needed -- the table IS the filter.
"""

from typing import Any, Dict

from sqlmodel import Session, func, select

from ....models import Assessment, Customization, Scan
from ...registry import ToolSpec

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment ID to retrieve customizations for.",
        },
        "origin_type": {
            "type": "string",
            "description": "Filter by origin: 'modified_ootb' or 'net_new_customer'.",
            "enum": ["modified_ootb", "net_new_customer"],
        },
        "table_name": {
            "type": "string",
            "description": "Filter by ServiceNow table (e.g., sys_script_include).",
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

    scan_ids = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == int(assessment_id))
    ).all())

    if not scan_ids:
        return {"success": True, "total": 0, "customizations": [], "assessment_name": assessment.name}

    query = select(Customization).where(Customization.scan_id.in_(scan_ids))

    origin_type = params.get("origin_type")
    if origin_type:
        query = query.where(Customization.origin_type == origin_type)

    table_name = params.get("table_name")
    if table_name:
        query = query.where(Customization.table_name == table_name)

    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    limit = min(params.get("limit", 50), 200)
    offset = params.get("offset", 0)
    query = query.order_by(Customization.name.asc()).offset(offset).limit(limit)

    rows = session.exec(query).all()

    condensed = []
    for r in rows:
        condensed.append({
            "id": r.id,
            "scan_result_id": r.scan_result_id,
            "sys_id": r.sys_id,
            "table_name": r.table_name,
            "name": r.name,
            "origin_type": r.origin_type.value if r.origin_type else None,
            "head_owner": r.head_owner.value if r.head_owner else None,
            "sys_class_name": r.sys_class_name,
            "sys_scope": r.sys_scope,
            "review_status": r.review_status.value if r.review_status else None,
            "disposition": r.disposition.value if r.disposition else None,
            "sys_updated_on": r.sys_updated_on.isoformat() if r.sys_updated_on else None,
        })

    return {
        "success": True,
        "assessment_name": assessment.name,
        "total": total,
        "offset": offset,
        "limit": limit,
        "customizations": condensed,
    }


TOOL_SPEC = ToolSpec(
    name="get_customizations",
    description=(
        "Retrieve customized scan results for an assessment from the customization "
        "child table. This table contains ONLY customized results (modified_ootb, "
        "net_new_customer) -- no filtering needed. Returns condensed fields for "
        "token efficiency. Supports pagination with limit/offset."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
