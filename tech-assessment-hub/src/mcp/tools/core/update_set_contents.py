"""MCP tool: get_update_set_contents — see what's in an update set.

Returns all customer_update_xml records for an update set.
Critical for feature grouping analysis - the AI needs to see what
artifacts are bundled together in an update set.
"""

from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import CustomerUpdateXML, UpdateSet


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "update_set_id": {
            "type": "integer",
            "description": "Database ID of the update set.",
        },
        "update_set_name": {
            "type": "string",
            "description": "Name of the update set (alternative to ID).",
        },
        "instance_id": {
            "type": "integer",
            "description": "Instance ID (required when using update_set_name).",
        },
        "limit": {
            "type": "integer",
            "description": "Max records to return (default 200).",
            "default": 200,
        },
    },
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    update_set_id = params.get("update_set_id")
    update_set_name = params.get("update_set_name")
    instance_id = params.get("instance_id")
    limit = min(int(params.get("limit", 200)), 1000)

    update_set = None

    if update_set_id:
        update_set = session.get(UpdateSet, int(update_set_id))
    elif update_set_name and instance_id:
        update_set = session.exec(
            select(UpdateSet).where(
                UpdateSet.name == update_set_name,
                UpdateSet.instance_id == int(instance_id),
            )
        ).first()
    else:
        raise ValueError("Provide either update_set_id or both update_set_name and instance_id.")

    if not update_set:
        raise ValueError("Update set not found.")

    xml_records = session.exec(
        select(CustomerUpdateXML)
        .where(CustomerUpdateXML.update_set_id == update_set.id)
        .limit(limit)
    ).all()

    contents = []
    for xml in xml_records:
        contents.append({
            "id": xml.id,
            "name": xml.name,
            "type": xml.type,
            "target_name": xml.target_name,
            "table": xml.table,
            "action": xml.action,
            "sys_created_on": xml.sys_created_on.isoformat() if xml.sys_created_on else None,
            "sys_created_by": xml.sys_created_by,
        })

    return {
        "success": True,
        "update_set": {
            "id": update_set.id,
            "name": update_set.name,
            "state": update_set.state,
            "application": update_set.application,
            "sys_created_on": update_set.sys_created_on.isoformat() if update_set.sys_created_on else None,
        },
        "contents": contents,
        "count": len(contents),
    }


TOOL_SPEC = ToolSpec(
    name="get_update_set_contents",
    description=(
        "Get all customer_update_xml records in an update set. "
        "Look up by ID or by name+instance_id. Critical for understanding "
        "what artifacts are grouped together for feature analysis."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
