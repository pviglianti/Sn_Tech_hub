"""MCP tool: get_customization_summary — token-saving aggregation.

Pure SQL aggregation on ScanResult that produces a structured overview
of an instance or assessment's customization landscape. Returns ~200 tokens
instead of the 50K+ needed to load all individual results.
"""

from typing import Any, Dict, List
from datetime import datetime, timedelta

from sqlmodel import Session, select, func, col, text

from ...registry import ToolSpec
from ....models import ScanResult, Scan, Assessment, OriginType, HeadOwner, Instance


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Summarize results for a specific assessment.",
        },
        "instance_id": {
            "type": "integer",
            "description": "Summarize results across all assessments for an instance.",
        },
    },
    "description": "Provide assessment_id or instance_id (at least one required).",
}


def _count_by_field(session: Session, scan_ids: List[int], field: Any) -> Dict[str, int]:
    """Group-count ScanResults by a given column."""
    query = (
        select(field, func.count())
        .where(col(ScanResult.scan_id).in_(scan_ids))
        .group_by(field)
    )
    return {str(k) if k else "null": v for k, v in session.exec(query).all()}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = params.get("assessment_id")
    instance_id = params.get("instance_id")

    if assessment_id is None and instance_id is None:
        raise ValueError("Provide assessment_id or instance_id")

    # Resolve scan IDs
    scan_query = select(Scan.id)
    assessment_info = None

    if assessment_id is not None:
        assessment = session.get(Assessment, int(assessment_id))
        if not assessment:
            raise ValueError(f"Assessment not found: {assessment_id}")
        scan_query = scan_query.where(Scan.assessment_id == int(assessment_id))
        assessment_info = {
            "name": assessment.name,
            "type": assessment.assessment_type.value if assessment.assessment_type else None,
            "state": assessment.state.value if assessment.state else None,
            "scope_filter": assessment.scope_filter,
        }
    elif instance_id is not None:
        # Scan doesn't have instance_id directly — join through Assessment
        assessment_ids = list(session.exec(
            select(Assessment.id).where(Assessment.instance_id == int(instance_id))
        ).all())
        if not assessment_ids:
            return {
                "success": True,
                "total_results": 0,
                "assessment": None,
                "message": f"No assessments found for instance {instance_id}.",
            }
        scan_query = scan_query.where(col(Scan.assessment_id).in_(assessment_ids))

    scan_ids = list(session.exec(scan_query).all())

    if not scan_ids:
        return {
            "success": True,
            "total_results": 0,
            "assessment": assessment_info,
            "message": "No scans found.",
        }

    # Total count
    total = session.exec(
        select(func.count()).where(col(ScanResult.scan_id).in_(scan_ids))
    ).one()

    # Aggregations
    by_origin = _count_by_field(session, scan_ids, ScanResult.origin_type)
    by_head_owner = _count_by_field(session, scan_ids, ScanResult.head_owner)
    by_table = _count_by_field(session, scan_ids, ScanResult.table_name)
    by_scope = _count_by_field(session, scan_ids, ScanResult.sys_scope)

    # Top creators (limit 10)
    creator_query = (
        select(ScanResult.sys_created_by, func.count())
        .where(col(ScanResult.scan_id).in_(scan_ids))
        .where(ScanResult.sys_created_by.isnot(None))  # type: ignore
        .group_by(ScanResult.sys_created_by)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_creators = [
        {"user": user, "count": count}
        for user, count in session.exec(creator_query).all()
    ]

    # Recent activity breakdown
    now = datetime.utcnow()
    recent_30d = session.exec(
        select(func.count())
        .where(col(ScanResult.scan_id).in_(scan_ids))
        .where(ScanResult.sys_updated_on >= now - timedelta(days=30))
    ).one()
    recent_90d = session.exec(
        select(func.count())
        .where(col(ScanResult.scan_id).in_(scan_ids))
        .where(ScanResult.sys_updated_on >= now - timedelta(days=90))
    ).one()

    return {
        "success": True,
        "total_results": total,
        "assessment": assessment_info,
        "by_origin": by_origin,
        "by_head_owner": by_head_owner,
        "by_table": by_table,
        "by_scope": by_scope,
        "top_creators": top_creators,
        "recent_activity": {
            "last_30d": recent_30d,
            "last_90d": recent_90d,
            "older": total - recent_90d,
        },
    }


TOOL_SPEC = ToolSpec(
    name="get_customization_summary",
    description=(
        "Get a token-efficient aggregated summary of customizations: counts by origin type, "
        "head owner, table, scope, top creators, and recent activity. Returns ~200 tokens "
        "instead of 50K+ for raw results. Use for orientation before detailed analysis."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
