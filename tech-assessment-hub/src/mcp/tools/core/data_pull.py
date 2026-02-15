"""MCP tool: trigger_data_pull — kick off instance data sync.

Triggers background data pulls for specified data types. Returns immediately
with status; use get_instance_summary to check freshness afterwards.
"""

from typing import Any, Dict, List
import threading

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Instance, DataPullType
from ....services.encryption import decrypt_password
from ....services.sn_client import ServiceNowClient
from ....services.data_pull_executor import execute_data_pull
from ....database import get_session


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {
            "type": "integer",
            "description": "Instance to pull data for.",
        },
        "data_types": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [dt.value for dt in DataPullType],
            },
            "description": "Data types to pull. If omitted, pulls all types.",
        },
        "mode": {
            "type": "string",
            "enum": ["full", "delta"],
            "description": "Pull mode: full (replace all) or delta (incremental). Default: delta.",
            "default": "delta",
        },
    },
    "required": ["instance_id"],
}


def _run_pull_in_background(instance_id: int, data_types: List[DataPullType], mode: str) -> None:
    """Background thread that runs data pulls with its own session."""
    session = next(get_session())
    try:
        instance = session.get(Instance, instance_id)
        if not instance:
            return
        client = ServiceNowClient(
            instance.url,
            instance.username,
            decrypt_password(instance.password_encrypted),
        )
        for dt in data_types:
            try:
                execute_data_pull(session, instance, client, dt, mode)
            except Exception:
                pass  # Error is recorded in InstanceDataPull.error_message
    finally:
        session.close()


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = int(params["instance_id"])

    instance = session.get(Instance, instance_id)
    if not instance:
        raise ValueError(f"Instance not found: {instance_id}")

    mode = params.get("mode", "delta")
    requested_types = params.get("data_types")

    if requested_types:
        data_types = [DataPullType(dt) for dt in requested_types]
    else:
        data_types = list(DataPullType)

    # Launch background thread (same pattern as server.py)
    thread = threading.Thread(
        target=_run_pull_in_background,
        args=(instance_id, data_types, mode),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "instance_id": instance_id,
        "mode": mode,
        "data_types": [dt.value for dt in data_types],
        "status": "running",
        "message": f"Started {len(data_types)} data pull(s) in background. Use get_instance_summary to check progress.",
    }


TOOL_SPEC = ToolSpec(
    name="trigger_data_pull",
    description=(
        "Trigger background data pulls for a ServiceNow instance. "
        "Pulls ServiceNow reference data (update sets, version history, "
        "metadata customizations, plugins, scopes, etc.) into local cache. "
        "Returns immediately; use get_instance_summary to monitor progress."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
