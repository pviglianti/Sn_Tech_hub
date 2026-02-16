"""MCP JSON-RPC request handler.

Moved from src/mcp/server.py during Wave 2 restructure.
"""

from typing import Any, Dict, Optional, Union
from sqlmodel import Session

from ..registry import PROMPT_REGISTRY, RESOURCE_REGISTRY
from ..runtime.router import MCP_RUNTIME_ROUTER
from .errors import make_error, make_result
from .schemas import PROTOCOL_VERSION, SERVER_INFO


def _handle_initialize(request_id: Optional[Union[str, int]]) -> Dict[str, Any]:
    return make_result(request_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": SERVER_INFO,
        "capabilities": {
            "tools": {},
            "prompts": {},
            "resources": {},
        }
    })


def _handle_tools_list(request_id: Optional[Union[str, int]], session: Session) -> Dict[str, Any]:
    return make_result(request_id, {
        "tools": MCP_RUNTIME_ROUTER.list_tools(session).get("tools", [])
    })


def _handle_tools_call(
    request_id: Optional[Union[str, int]],
    params: Dict[str, Any],
    session: Session,
    request_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tool_name = params.get("name") or params.get("tool") or params.get("tool_name")
    arguments = params.get("arguments") or params.get("args") or {}
    actor = str((request_context or {}).get("actor") or "unknown")

    if not tool_name:
        return make_error(request_id, -32602, "Missing tool name")

    try:
        execution = MCP_RUNTIME_ROUTER.call_tool(tool_name, arguments, session, actor=actor)
    except KeyError:
        return make_error(request_id, -32601, f"Tool not found: {tool_name}")
    except ValueError as exc:
        return make_error(request_id, -32602, str(exc))
    except Exception as exc:
        return make_error(request_id, -32000, "Tool execution failed", {"error": str(exc)})

    json_payload = execution.content if execution.success else {
        **execution.content,
        "success": False,
        "error_code": execution.error_code or "tool_execution_failed",
        "engine_used": execution.engine_used,
        "degraded": execution.degraded,
        "correlation_id": execution.correlation_id,
        "duration_ms": execution.duration_ms,
    }

    return make_result(request_id, {
        "content": [
            {
                "type": "json",
                "json": json_payload
            }
        ]
    })


def _handle_prompts_list(request_id: Optional[Union[str, int]]) -> Dict[str, Any]:
    return make_result(request_id, {
        "prompts": PROMPT_REGISTRY.list_prompts()
    })


def _handle_prompts_get(
    request_id: Optional[Union[str, int]],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    name = params.get("name")
    if not name:
        return make_error(request_id, -32602, "Missing prompt name")

    try:
        arguments = params.get("arguments") or {}
        result = PROMPT_REGISTRY.get_prompt(name, arguments)
    except KeyError:
        return make_error(request_id, -32601, f"Prompt not found: {name}")
    except Exception as exc:
        return make_error(request_id, -32000, f"Prompt retrieval failed: {exc}")

    return make_result(request_id, result)


def _handle_resources_list(request_id: Optional[Union[str, int]]) -> Dict[str, Any]:
    return make_result(request_id, {
        "resources": RESOURCE_REGISTRY.list_resources()
    })


def _handle_resources_read(
    request_id: Optional[Union[str, int]],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    uri = params.get("uri")
    if not uri:
        return make_error(request_id, -32602, "Missing resource URI")

    try:
        result = RESOURCE_REGISTRY.read_resource(uri)
    except KeyError:
        return make_error(request_id, -32601, f"Resource not found: {uri}")
    except Exception as exc:
        return make_error(request_id, -32000, f"Resource read failed: {exc}")

    return make_result(request_id, result)


def handle_request(
    payload: Dict[str, Any],
    session: Session,
    request_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request_id = payload.get("id")
    method = payload.get("method")

    if not method:
        return make_error(request_id, -32600, "Invalid Request")

    if method == "initialize":
        return _handle_initialize(request_id)

    if method == "tools/list":
        return _handle_tools_list(request_id, session)

    if method == "tools/call":
        params = payload.get("params") or {}
        return _handle_tools_call(request_id, params, session, request_context=request_context)

    if method == "prompts/list":
        return _handle_prompts_list(request_id)

    if method == "prompts/get":
        params = payload.get("params") or {}
        return _handle_prompts_get(request_id, params)

    if method == "resources/list":
        return _handle_resources_list(request_id)

    if method == "resources/read":
        params = payload.get("params") or {}
        return _handle_resources_read(request_id, params)

    return make_error(request_id, -32601, f"Method not found: {method}")
