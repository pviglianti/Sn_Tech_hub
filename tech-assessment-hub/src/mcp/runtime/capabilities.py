"""Merged capability catalog for local Python + TypeScript sidecar tools."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlmodel import Session

from ..bridge import BRIDGE_MANAGER, load_bridge_config
from .registry import UNIFIED_REGISTRY, load_runtime_config
from ..registry import _tool_annotations


def _fetch_remote_tools(session: Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cfg = load_bridge_config(session)
    result = BRIDGE_MANAGER.fetch_remote_tools(cfg)
    if not result.get("success"):
        return [], result
    tools = result.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    return tools, result


def get_capability_snapshot(session: Session, include_admin: bool = False) -> Dict[str, Any]:
    """Build merged catalog with deterministic selected engine per tool."""
    runtime_cfg = load_runtime_config(session)
    bridge_cfg = load_bridge_config(session)
    remote_tools, remote_meta = _fetch_remote_tools(session)
    merged = UNIFIED_REGISTRY.build_routes(session, remote_tools)

    user_tools: List[Dict[str, Any]] = []
    admin_tools: List[Dict[str, Any]] = []
    selected_ts: List[str] = []

    bridge_status = BRIDGE_MANAGER.status()
    sidecar_degraded = bridge_status.get("health_state") in {"degraded", "recovering", "unavailable"}

    for row in merged.values():
        selected = row.get("selected_route")
        if selected is None:
            continue

        user_tools.append(
            {
                "name": row["name"],
                "description": row["description"],
                "inputSchema": row["input_schema"],
                "annotations": _tool_annotations(row["permission"]),
            }
        )

        if selected.engine == "ts_sidecar":
            selected_ts.append(row["name"])

        if include_admin:
            admin_tools.append(
                {
                    "name": row["name"],
                    "description": row["description"],
                    "inputSchema": row["input_schema"],
                    "annotations": _tool_annotations(row["permission"]),
                    "permission": row["permission"],
                    "fallback_policy": row["fallback_policy"],
                    "selected_route": {
                        "engine": selected.engine,
                        "target": selected.target,
                        "timeout_ms": selected.timeout_ms,
                        "retry_policy": selected.retry_policy,
                        "priority": selected.priority,
                    },
                    "available_routes": [
                        {
                            "engine": r.engine,
                            "target": r.target,
                            "timeout_ms": r.timeout_ms,
                            "retry_policy": r.retry_policy,
                            "priority": r.priority,
                        }
                        for r in row["routes"]
                    ],
                }
            )

    user_tools = sorted(user_tools, key=lambda t: t["name"])
    admin_tools = sorted(admin_tools, key=lambda t: t["name"])

    degraded_capabilities = selected_ts if sidecar_degraded else []

    snapshot: Dict[str, Any] = {
        "tools": user_tools,
        "metrics": {
            "tool_count_unified": len(user_tools),
            "tool_count_sidecar_selected": len(selected_ts),
            "tool_count_remote_manifest": len(remote_tools),
        },
        "degraded_capabilities": degraded_capabilities,
        "bridge": {
            "status": bridge_status,
            "configured": bool(bridge_cfg.get("management_base_url") or bridge_cfg.get("rpc_url")),
            "remote_manifest_ok": bool(remote_meta.get("success")),
            "remote_manifest_stale": bool(remote_meta.get("stale")),
            "remote_manifest_error": remote_meta.get("error"),
            "remote_manifest_cached_at": remote_meta.get("cached_at"),
        },
    }

    if include_admin:
        snapshot["admin"] = {
            "runtime_config": runtime_cfg,
            "tools_admin": admin_tools,
            "remote_manifest": remote_meta,
        }

    return snapshot
