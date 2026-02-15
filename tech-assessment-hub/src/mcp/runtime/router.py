"""Runtime router for hybrid MCP tool execution."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from sqlmodel import Session

from ..bridge import BRIDGE_MANAGER, load_bridge_config
from ..registry import REGISTRY
from .audit import build_audit_event, record_audit_event
from .capabilities import get_capability_snapshot
from .permissions import check_permission, PermissionDeniedError
from .registry import ToolExecutionResult, ToolRoute


def _extract_remote_tool_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        # Direct tool JSON payload
        if "success" in raw or "result" in raw or "error_code" in raw:
            return raw

        # JSON-RPC wrapper payload
        result = raw.get("result")
        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "json" and isinstance(item.get("json"), dict):
                        return item["json"]
            if isinstance(result.get("json"), dict):
                return result["json"]
            return result
    return {"success": False, "message": "Invalid remote tool payload"}


class RuntimeRouter:
    def list_tools(self, session: Session) -> Dict[str, Any]:
        snapshot = get_capability_snapshot(session, include_admin=False)
        return {"tools": snapshot["tools"]}

    def _selected_route_for_tool(self, session: Session, tool_name: str) -> Optional[ToolRoute]:
        snapshot = get_capability_snapshot(session, include_admin=True)
        admin = snapshot.get("admin") or {}
        tools_admin = admin.get("tools_admin") or []
        for row in tools_admin:
            if row.get("name") != tool_name:
                continue
            selected = row.get("selected_route") or {}
            return ToolRoute(
                engine=str(selected.get("engine") or ""),
                target=str(selected.get("target") or tool_name),
                timeout_ms=int(selected.get("timeout_ms") or 12000),
                retry_policy=selected.get("retry_policy") or {},
                priority=int(selected.get("priority") or 0),
            )
        return None

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        session: Session,
        *,
        actor: str = "unknown",
    ) -> ToolExecutionResult:
        route = self._selected_route_for_tool(session, tool_name)
        if route is None:
            raise KeyError(f"Tool not found: {tool_name}")

        # Permission check (Wave 2 scaffold -- permissive default)
        tool_permission = "read"  # default; future: look up from tool spec
        if not check_permission(tool_name, tool_permission, None):
            raise PermissionDeniedError(tool_name, tool_permission)

        correlation_id = str(uuid.uuid4())
        started = time.time()

        if route.engine == "python":
            content = REGISTRY.call(tool_name, arguments, session)
            duration_ms = int((time.time() - started) * 1000)
            event = build_audit_event(
                actor=actor,
                tool_name=tool_name,
                engine="python",
                success=True,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
            )
            record_audit_event(event)
            return ToolExecutionResult(
                success=True,
                content=content,
                error_code=None,
                engine_used="python",
                degraded=False,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
            )

        # TypeScript sidecar path
        bridge_cfg = load_bridge_config(session)
        if not BRIDGE_MANAGER.can_attempt_tool_call():
            BRIDGE_MANAGER.maybe_auto_restart(bridge_cfg)
            duration_ms = int((time.time() - started) * 1000)
            payload = {
                "success": False,
                "error_code": "tool_temporarily_unavailable",
                "message": "TypeScript MCP sidecar is currently recovering. Try again shortly.",
                "correlation_id": correlation_id,
                "degraded": True,
                "fallback_suggestion": "Use Python-native tools or retry after recovery.",
            }
            event = build_audit_event(
                actor=actor,
                tool_name=tool_name,
                engine="ts_sidecar",
                success=False,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                degraded=True,
                error_code="tool_temporarily_unavailable",
                error_message="sidecar recovering",
            )
            record_audit_event(event)
            return ToolExecutionResult(
                success=False,
                content=payload,
                error_code="tool_temporarily_unavailable",
                engine_used="ts_sidecar",
                degraded=True,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
            )

        retry_policy = route.retry_policy or {}
        max_retries = max(0, int(retry_policy.get("max_retries", 2)))
        base_delay = max(0.1, float(retry_policy.get("base_delay_seconds", 1.0)))
        max_delay = max(0.5, float(retry_policy.get("max_delay_seconds", 8.0)))

        last_error: Optional[str] = None
        for attempt in range(max_retries + 1):
            remote_result = BRIDGE_MANAGER.call_remote_tool(
                bridge_cfg,
                tool_name,
                arguments,
                timeout_ms=route.timeout_ms,
                request_id=correlation_id,
            )
            if remote_result.get("success"):
                BRIDGE_MANAGER.record_tool_success()
                payload = _extract_remote_tool_payload(remote_result.get("payload"))
                duration_ms = int((time.time() - started) * 1000)
                event = build_audit_event(
                    actor=actor,
                    tool_name=tool_name,
                    engine="ts_sidecar",
                    success=True,
                    correlation_id=correlation_id,
                    duration_ms=duration_ms,
                )
                record_audit_event(event)
                return ToolExecutionResult(
                    success=True,
                    content=payload,
                    error_code=None,
                    engine_used="ts_sidecar",
                    degraded=False,
                    correlation_id=correlation_id,
                    duration_ms=duration_ms,
                )

            last_error = str(remote_result.get("error") or "unknown sidecar error")
            BRIDGE_MANAGER.record_tool_failure(last_error)
            if attempt < max_retries:
                sleep_for = min(max_delay, base_delay * (2 ** attempt))
                time.sleep(sleep_for)

        BRIDGE_MANAGER.maybe_auto_restart(bridge_cfg)
        # If a local tool exists with the same name, degrade to Python fallback.
        if REGISTRY.has_tool(tool_name):
            local_payload = REGISTRY.call(tool_name, arguments, session)
            duration_ms = int((time.time() - started) * 1000)
            local_payload = dict(local_payload)
            local_payload.setdefault("runtime_notice", "Executed local Python fallback after sidecar failure.")
            event = build_audit_event(
                actor=actor,
                tool_name=tool_name,
                engine="python",
                success=True,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                degraded=True,
                error_code="sidecar_fallback_to_python",
                error_message=last_error,
            )
            record_audit_event(event)
            return ToolExecutionResult(
                success=True,
                content=local_payload,
                error_code=None,
                engine_used="python",
                degraded=True,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
            )

        duration_ms = int((time.time() - started) * 1000)
        payload = {
            "success": False,
            "error_code": "tool_temporarily_unavailable",
            "message": "TypeScript MCP sidecar call failed after retries.",
            "correlation_id": correlation_id,
            "degraded": True,
            "fallback_suggestion": "Retry soon or use Python-native tools while sidecar recovers.",
            "last_error": last_error,
        }
        event = build_audit_event(
            actor=actor,
            tool_name=tool_name,
            engine="ts_sidecar",
            success=False,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
            degraded=True,
            error_code="tool_temporarily_unavailable",
            error_message=last_error,
        )
        record_audit_event(event)
        return ToolExecutionResult(
            success=False,
            content=payload,
            error_code="tool_temporarily_unavailable",
            engine_used="ts_sidecar",
            degraded=True,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
        )


MCP_RUNTIME_ROUTER = RuntimeRouter()
