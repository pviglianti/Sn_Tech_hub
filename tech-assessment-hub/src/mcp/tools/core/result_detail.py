"""MCP tool: get_result_detail — deep dive on a single scan result.

Returns the full ScanResult including raw_data_json, related records
(version history, update set, customer update XML), and the matching
artifact detail record (e.g., the actual business rule with script,
conditions, and configuration).
"""

from typing import Any, Dict, Optional
import json

from sqlalchemy import text
from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    ScanResult, Scan, Assessment, VersionHistory, CustomerUpdateXML, UpdateSet,
)
from ....artifact_detail_defs import ARTIFACT_DETAIL_DEFS


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "result_id": {
            "type": "integer",
            "description": "ID of the scan result to retrieve.",
        },
    },
    "required": ["result_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    result_id = params.get("result_id")
    if result_id is None:
        raise ValueError("result_id is required")

    result = session.get(ScanResult, int(result_id))
    if not result:
        raise ValueError(f"ScanResult not found: {result_id}")

    # Build full result dict
    result_dict = {
        "id": result.id,
        "sys_id": result.sys_id,
        "table_name": result.table_name,
        "name": result.name,
        "display_value": result.display_value,
        "sys_class_name": result.sys_class_name,
        "sys_update_name": result.sys_update_name,
        "sys_scope": result.sys_scope,
        "sys_package": result.sys_package,
        "meta_target_table": result.meta_target_table,
        "origin_type": result.origin_type.value if result.origin_type else None,
        "head_owner": result.head_owner.value if result.head_owner else None,
        "changed_baseline_now": result.changed_baseline_now,
        "current_version_source_table": result.current_version_source_table,
        "current_version_source": result.current_version_source,
        "review_status": result.review_status.value if result.review_status else None,
        "disposition": result.disposition.value if result.disposition else None,
        "recommendation": result.recommendation,
        "observations": result.observations,
        "is_adjacent": result.is_adjacent,
        "is_out_of_scope": result.is_out_of_scope,
        "sys_created_by": result.sys_created_by,
        "sys_created_on": result.sys_created_on.isoformat() if result.sys_created_on else None,
        "sys_updated_by": result.sys_updated_by,
        "sys_updated_on": result.sys_updated_on.isoformat() if result.sys_updated_on else None,
        "script_length": result.script_length,
        "raw_data": json.loads(result.raw_data_json) if result.raw_data_json else None,
    }

    # Related update set
    update_set_info = None
    if result.update_set_id:
        us = session.get(UpdateSet, result.update_set_id)
        if us:
            update_set_info = {
                "id": us.id,
                "name": us.name,
                "state": us.state,
                "application": us.application,
                "sys_created_on": us.sys_created_on.isoformat() if us.sys_created_on else None,
            }

    # Related customer update XML
    update_xml_info = None
    if result.customer_update_xml_id:
        xml = session.get(CustomerUpdateXML, result.customer_update_xml_id)
        if xml:
            update_xml_info = {
                "id": xml.id,
                "name": xml.name,
                "type": xml.type,
                "target_name": xml.target_name,
                "action": xml.action,
            }

    # Version history (query by sys_update_name if available)
    version_history = []
    if result.sys_update_name:
        # Get instance_id through Scan → Assessment
        scan = session.get(Scan, result.scan_id)
        assessment = session.get(Assessment, scan.assessment_id) if scan else None
        instance_id = assessment.instance_id if assessment else None
        if instance_id:
            vh_query = select(VersionHistory).where(
                VersionHistory.instance_id == instance_id,
                VersionHistory.name == result.sys_update_name,
            ).order_by(VersionHistory.sys_recorded_at.desc())  # type: ignore
            for vh in session.exec(vh_query.limit(10)).all():
                version_history.append({
                    "id": vh.id,
                    "state": vh.state,
                    "source_table": vh.source_table,
                    "source_display": vh.source_display,
                    "sys_recorded_at": vh.sys_recorded_at.isoformat() if vh.sys_recorded_at else None,
                })

    # Artifact detail record (the actual business rule, script include, etc.)
    artifact_detail = _get_artifact_detail(session, result)

    return {
        "success": True,
        "result": result_dict,
        "artifact_detail": artifact_detail,
        "update_set": update_set_info,
        "customer_update_xml": update_xml_info,
        "version_history": version_history,
    }


def _get_artifact_detail(
    session: Session, result: ScanResult
) -> Optional[Dict[str, Any]]:
    """Look up the matching artifact detail record for this scan result.

    Joins via sys_id to the appropriate asmt_* table (e.g., asmt_business_rule
    for sys_script). Returns all columns as a dict, or None if no match.
    """
    table_name = result.table_name
    if not table_name:
        return None

    defn = ARTIFACT_DETAIL_DEFS.get(table_name)
    if not defn:
        return None

    local_table = defn["local_table"]
    sys_id = result.sys_id
    if not sys_id:
        return None

    try:
        row = session.exec(
            text(f"SELECT * FROM {local_table} WHERE sys_id = :sid LIMIT 1")
            .bindparams(sid=sys_id)
        ).first()
        if not row:
            return None

        # Convert row to dict — row is a Row/RowMapping
        if hasattr(row, "_mapping"):
            return dict(row._mapping)
        if hasattr(row, "_asdict"):
            return row._asdict()
        # Fallback: use column names from the definition
        columns = ["_row_id", "_instance_id", "sys_id"] + [
            f[0] for f in defn["fields"]
        ]
        if isinstance(row, tuple):
            return dict(zip(columns[:len(row)], row))
        return None
    except Exception:
        return None


TOOL_SPEC = ToolSpec(
    name="get_result_detail",
    description=(
        "Get full details for a single scan result including the matching artifact "
        "detail record (e.g., business rule script/conditions, UI policy actions, "
        "script include code), raw ServiceNow data, and related records (version "
        "history, update set, customer update XML). "
        "This is token-expensive — use after triaging with get_assessment_results."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
