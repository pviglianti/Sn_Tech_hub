"""MCP tool: sn_inventory_summary."""

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
        "instance_id": {"type": "integer"},
        "scope": {
            "type": "string",
            "enum": ["global", "scoped", "all"],
            "default": "global"
        },
        "url": {"type": "string"},
        "username": {"type": "string"},
        "password": {"type": "string"}
    },
    "description": "Provide instance_id or raw url/username/password."
}


def _resolve_credentials(params: Dict[str, Any], session: Session) -> Dict[str, str]:
    instance_id = params.get("instance_id")
    if instance_id is not None:
        instance = session.get(Instance, int(instance_id))
        if not instance:
            raise ValueError("Instance not found")
        return {
            "url": instance.url,
            "username": instance.username,
            "password": decrypt_password(instance.password_encrypted)
        }

    url = params.get("url")
    username = params.get("username")
    password = params.get("password")
    if not url or not username or not password:
        raise ValueError("Provide instance_id or url/username/password")
    return {"url": url, "username": username, "password": password}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    scope = params.get("scope") or "global"
    creds = _resolve_credentials(params, session)
    client = ServiceNowClient(creds["url"], creds["username"], creds["password"])

    try:
        counts = client.scan_inventory(scope=scope)
    except ServiceNowClientError as exc:
        return {"success": False, "message": str(exc), "counts": {}, "total": 0}

    total = sum(value for value in counts.values() if isinstance(value, int) and value >= 0)
    return {"success": True, "scope": scope, "counts": counts, "total": total}


TOOL_SPEC = ToolSpec(
    name="sn_inventory_summary",
    description="Return inventory counts by artifact type for a scope.",
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
