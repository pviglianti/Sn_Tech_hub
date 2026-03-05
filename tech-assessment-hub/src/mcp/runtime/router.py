"""Runtime router for hybrid MCP tool execution."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from sqlmodel import Session

from ..bridge import BRIDGE_MANAGER, load_bridge_config
from ..registry import REGISTRY
from ...services.assessment_phase_progress import (
    checkpoint_phase_progress,
    fail_phase_progress,
    start_phase_progress,
)
from ...services.assessment_runtime_usage import refresh_assessment_runtime_usage
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


_TOOL_PHASE_MAP = {
    "run_preprocessing_engines": "engines",
    "generate_observations": "observations",
    "seed_feature_groups": "grouping",
    "run_feature_reasoning": "recommendations",
}


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _tool_phase(tool_name: str) -> str:
    return _TOOL_PHASE_MAP.get(tool_name, f"tool:{tool_name}")


def _extract_assessment_id(arguments: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> Optional[int]:
    for source in (arguments, payload or {}):
        if not isinstance(source, dict):
            continue
        value = _to_int(source.get("assessment_id"))
        if value is not None:
            return value
    return None


def _is_rate_limit_text(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(
        token in normalized
        for token in ("rate limit", "too many requests", "http 429", "status code 429", "quota exceeded")
    )


def _is_cost_limit_text(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(token in normalized for token in ("cost hard limit", "budget limit", "blocked_cost_limit"))


def _track_tool_start(
    session: Session,
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    correlation_id: str,
) -> Optional[Dict[str, Any]]:
    assessment_id = _extract_assessment_id(arguments)
    if assessment_id is None:
        return None
    phase = _tool_phase(tool_name)

    total_hint = 0
    if tool_name == "run_feature_reasoning":
        total_hint = max(1, int(arguments.get("max_iterations") or 0))
    elif tool_name == "run_preprocessing_engines":
        engines = arguments.get("engines")
        total_hint = len(engines) if isinstance(engines, list) and engines else 0
    elif tool_name == "generate_observations":
        total_hint = max(0, int(arguments.get("max_results") or 0))

    try:
        start_phase_progress(
            session,
            assessment_id,
            phase,
            total_items=total_hint,
            allow_resume=True,
            checkpoint={
                "source": "runtime_router",
                "tool_name": tool_name,
                "correlation_id": correlation_id,
            },
            commit=True,
        )
    except Exception:
        return None

    return {"assessment_id": assessment_id, "phase": phase}


def _track_tool_success(
    session: Session,
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    payload: Dict[str, Any],
    tracking: Optional[Dict[str, Any]],
    engine_used: str,
) -> None:
    if not tracking:
        return
    assessment_id = int(tracking["assessment_id"])
    phase = str(tracking["phase"])

    total_items = 1
    completed_items = 1
    status = "completed"
    checkpoint: Dict[str, Any] = {"tool_name": tool_name, "engine_used": engine_used}

    if tool_name == "generate_observations":
        total_items = max(0, int(payload.get("total_customized") or 0))
        completed_items = max(0, int(payload.get("next_resume_index") or payload.get("processed_count") or 0))
        if total_items > 0 and completed_items < total_items:
            status = "running"
        checkpoint.update(
            {
                "resume_from_index": completed_items,
                "processed_count": int(payload.get("processed_count") or 0),
                "usage_queries_executed": int(payload.get("usage_queries_executed") or 0),
            }
        )
    elif tool_name == "run_feature_reasoning":
        completed_items = max(
            0,
            int(payload.get("iterations_completed") or payload.get("iteration_number") or 0),
        )
        total_items = max(1, int(payload.get("max_iterations") or completed_items or 1))
        status = "running" if bool(payload.get("should_continue")) else "completed"
        checkpoint.update(
            {
                "run_id": payload.get("run_id"),
                "converged": bool(payload.get("converged")),
                "resume_from_index": completed_items,
            }
        )
    elif tool_name == "seed_feature_groups":
        total_items = max(0, int(payload.get("eligible_customized_count") or payload.get("grouped_count") or 0))
        completed_items = max(0, int(payload.get("grouped_count") or 0))
        checkpoint.update(
            {
                "features_created": int(payload.get("features_created") or 0),
                "resume_from_index": completed_items,
            }
        )
    elif tool_name == "run_preprocessing_engines":
        total_items = len(payload.get("engines_run") or [])
        completed_items = total_items
        status = "completed" if bool(payload.get("success", True)) else "failed"
        checkpoint.update({"engine_count": total_items})
    else:
        if "processed_count" in payload:
            completed_items = max(0, int(payload.get("processed_count") or 0))
            total_items = max(completed_items, int(payload.get("total") or completed_items or 1))
            status = "running" if total_items > completed_items else "completed"

    try:
        checkpoint_phase_progress(
            session,
            assessment_id,
            phase,
            total_items=max(0, int(total_items)),
            completed_items=max(0, int(completed_items)),
            status=status,
            checkpoint=checkpoint,
            commit=True,
        )
    except Exception:
        pass

    try:
        refresh_assessment_runtime_usage(
            session,
            assessment_id,
            mcp_calls_local_delta=1,
            last_event=f"tool:{tool_name}:{status}",
            details={"tool_name": tool_name, "engine_used": engine_used, "status": status},
            commit=True,
        )
    except Exception:
        pass


def _track_tool_failure(
    session: Session,
    *,
    tool_name: str,
    tracking: Optional[Dict[str, Any]],
    error_text: str,
    engine_used: str,
) -> None:
    if not tracking:
        return
    assessment_id = int(tracking["assessment_id"])
    phase = str(tracking["phase"])

    failure_status = "failed"
    if _is_cost_limit_text(error_text):
        failure_status = "blocked_cost_limit"
    elif _is_rate_limit_text(error_text):
        failure_status = "blocked_rate_limit"

    try:
        fail_phase_progress(
            session,
            assessment_id,
            phase,
            status=failure_status,
            error=error_text,
            checkpoint={"tool_name": tool_name, "engine_used": engine_used, "error": error_text},
            commit=True,
        )
    except Exception:
        pass

    try:
        refresh_assessment_runtime_usage(
            session,
            assessment_id,
            last_event=f"tool:{tool_name}:{failure_status}",
            details={"tool_name": tool_name, "engine_used": engine_used, "status": failure_status, "error": error_text},
            commit=True,
        )
    except Exception:
        pass


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
        tracking = _track_tool_start(
            session,
            tool_name=tool_name,
            arguments=arguments,
            correlation_id=correlation_id,
        )

        if route.engine == "python":
            try:
                content = REGISTRY.call(tool_name, arguments, session)
            except Exception as exc:
                _track_tool_failure(
                    session,
                    tool_name=tool_name,
                    tracking=tracking,
                    error_text=str(exc),
                    engine_used="python",
                )
                raise
            duration_ms = int((time.time() - started) * 1000)
            if isinstance(content, dict):
                _track_tool_success(
                    session,
                    tool_name=tool_name,
                    arguments=arguments,
                    payload=content,
                    tracking=tracking,
                    engine_used="python",
                )
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
            _track_tool_failure(
                session,
                tool_name=tool_name,
                tracking=tracking,
                error_text=str(payload.get("message") or "tool temporarily unavailable"),
                engine_used="ts_sidecar",
            )
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
                if isinstance(payload, dict):
                    _track_tool_success(
                        session,
                        tool_name=tool_name,
                        arguments=arguments,
                        payload=payload,
                        tracking=tracking,
                        engine_used="ts_sidecar",
                    )
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
            try:
                local_payload = REGISTRY.call(tool_name, arguments, session)
            except Exception as exc:
                _track_tool_failure(
                    session,
                    tool_name=tool_name,
                    tracking=tracking,
                    error_text=str(exc),
                    engine_used="python",
                )
                raise
            duration_ms = int((time.time() - started) * 1000)
            local_payload = dict(local_payload)
            local_payload.setdefault("runtime_notice", "Executed local Python fallback after sidecar failure.")
            _track_tool_success(
                session,
                tool_name=tool_name,
                arguments=arguments,
                payload=local_payload,
                tracking=tracking,
                engine_used="python",
            )
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
        _track_tool_failure(
            session,
            tool_name=tool_name,
            tracking=tracking,
            error_text=str(payload.get("last_error") or payload.get("message") or "tool execution failed"),
            engine_used="ts_sidecar",
        )
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
