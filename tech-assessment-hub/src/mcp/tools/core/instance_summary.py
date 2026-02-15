"""MCP tool: get_instance_summary — AI orientation tool.

Returns a token-efficient overview of an instance: inventory counts,
task counts, data pull freshness, custom footprint, and instance age.
"""

from typing import Any, Dict, List, Optional
import json
from datetime import datetime

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Instance, InstanceDataPull, DataPullType, DataPullStatus


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {
            "type": "integer",
            "description": "ID of the instance to summarize.",
        },
    },
    "required": ["instance_id"],
}


def _pull_status_summary(session: Session, instance_id: int) -> Dict[str, Any]:
    """Build a summary of data pull freshness per data type."""
    pulls = session.exec(
        select(InstanceDataPull).where(
            InstanceDataPull.instance_id == instance_id
        )
    ).all()

    summary: Dict[str, Any] = {}
    for pull in pulls:
        summary[pull.data_type.value] = {
            "status": pull.status.value,
            "records_pulled": pull.records_pulled,
            "last_pulled_at": pull.last_pulled_at.isoformat() if pull.last_pulled_at else None,
        }
    return summary


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = params.get("instance_id")
    if instance_id is None:
        raise ValueError("instance_id is required")

    instance = session.get(Instance, int(instance_id))
    if not instance:
        raise ValueError(f"Instance not found: {instance_id}")

    # Parse cached JSON fields
    inventory = json.loads(instance.inventory_json) if instance.inventory_json else {}
    task_counts = json.loads(instance.task_counts_json) if instance.task_counts_json else {}
    update_set_counts = json.loads(instance.update_set_counts_json) if instance.update_set_counts_json else {}

    return {
        "success": True,
        "instance": {
            "id": instance.id,
            "url": instance.url,
            "company": instance.company,
            "version": instance.instance_version,
            "instance_dob": instance.instance_dob.isoformat() if instance.instance_dob else None,
            "instance_age_years": instance.instance_age_years,
        },
        "inventory": inventory,
        "task_counts": task_counts,
        "update_set_counts": update_set_counts,
        "custom_footprint": {
            "custom_scoped_apps_x": instance.custom_scoped_app_count_x,
            "custom_scoped_apps_u": instance.custom_scoped_app_count_u,
            "custom_tables_x": instance.custom_table_count_x,
            "custom_tables_u": instance.custom_table_count_u,
            "custom_fields_x": instance.custom_field_count_x,
            "custom_fields_u": instance.custom_field_count_u,
        },
        "data_pull_status": _pull_status_summary(session, int(instance_id)),
    }


TOOL_SPEC = ToolSpec(
    name="get_instance_summary",
    description=(
        "Get a token-efficient overview of a ServiceNow instance: "
        "inventory counts, task counts, data pull freshness, custom footprint, "
        "and instance age. Use this first for orientation before deeper queries."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
