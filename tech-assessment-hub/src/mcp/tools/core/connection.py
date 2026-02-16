"""MCP tool: sn_test_connection."""

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
        "url": {"type": "string"},
        "username": {"type": "string"},
        "password": {"type": "string"}
    },
    "description": "Provide instance_id or raw url/username/password."
}


def _resolve_credentials(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = params.get("instance_id")
    if instance_id is not None:
        instance = session.get(Instance, int(instance_id))
        if not instance:
            raise ValueError("Instance not found")
        return {
            "url": instance.url,
            "username": instance.username,
            "password": decrypt_password(instance.password_encrypted),
            "instance_id": instance.id,
        }

    url = params.get("url")
    username = params.get("username")
    password = params.get("password")
    if not url or not username or not password:
        raise ValueError("Provide instance_id or url/username/password")
    return {"url": url, "username": username, "password": password, "instance_id": None}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    creds = _resolve_credentials(params, session)
    client = ServiceNowClient(
        creds["url"],
        creds["username"],
        creds["password"],
        instance_id=creds.get("instance_id"),
    )
    try:
        return client.test_connection()
    except ServiceNowClientError as exc:
        return {"success": False, "message": str(exc), "version": None}


TOOL_SPEC = ToolSpec(
    name="sn_test_connection",
    description="Verify ServiceNow connection and return instance version.",
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
