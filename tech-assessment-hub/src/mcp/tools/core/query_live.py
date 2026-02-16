"""MCP tool: query_instance_live — one-off REST queries to ServiceNow.

Makes a single REST API call to a configured ServiceNow instance for ad-hoc
queries that are not worth caching locally.
"""

from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Instance
from ....services.encryption import decrypt_password
from ....services.sn_client import ServiceNowClient, ServiceNowClientError


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {
            "type": "integer",
            "description": "ID of the configured instance.",
        },
        "table": {
            "type": "string",
            "description": "ServiceNow table name (e.g. sys_user, incident).",
        },
        "encoded_query": {
            "type": "string",
            "description": "ServiceNow encoded query string.",
            "default": "",
        },
        "fields": {
            "type": "string",
            "description": "Comma-separated field names to return.",
            "default": "",
        },
        "limit": {
            "type": "integer",
            "description": "Max records to return.",
            "default": 20,
        },
    },
    "required": ["instance_id", "table"],
}


def handle_query_instance_live(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    # --- Resolve instance credentials ---
    instance_id = int(params["instance_id"])
    instance = session.get(Instance, instance_id)
    if not instance:
        return {"success": False, "error": f"Instance with id {instance_id} not found."}

    table = params["table"]
    encoded_query = params.get("encoded_query", "") or ""
    fields_str = params.get("fields", "") or ""
    limit = min(int(params.get("limit", 20)), 500)  # cap at 500

    # Parse fields into list (empty string → None → all fields)
    fields_list = [f.strip() for f in fields_str.split(",") if f.strip()] or None

    # --- Build SN client and execute query ---
    try:
        password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(
            instance.url,
            instance.username,
            password,
            instance_id=instance.id,
        )
        records = client.get_records(
            table=table,
            query=encoded_query,
            fields=fields_list,
            limit=limit,
        )
    except ServiceNowClientError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": f"Unexpected error: {str(exc)}"}

    return {
        "success": True,
        "instance_id": instance_id,
        "table": table,
        "count": len(records),
        "records": records,
    }


TOOL_SPEC = ToolSpec(
    name="query_instance_live",
    description=(
        "Make a one-off REST API query to a ServiceNow instance. "
        "Returns records from the specified table matching the encoded query. "
        "Use for ad-hoc queries not worth caching locally."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle_query_instance_live,
    permission="read",
)
