"""Unified runtime registry and route selection for hybrid MCP."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ...models import AppConfig
from ..registry import REGISTRY


RUNTIME_CONFIG_KEY = "mcp_runtime_config"

DEFAULT_RUNTIME_CONFIG: Dict[str, Any] = {
    "default_engine": "python",
    "engine_priority": {
        "python": 100,
        "ts_sidecar": 50,
    },
    "tool_routes": {},
    "default_timeout_ms": 12000,
    "retry_policy": {
        "max_retries": 2,
        "base_delay_seconds": 1.0,
        "max_delay_seconds": 8.0,
    },
}


@dataclass
class UnifiedToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    permission: str = "read"
    route_key: Optional[str] = None
    fallback_policy: str = "graceful_degrade"


@dataclass
class ToolRoute:
    engine: str
    target: str
    timeout_ms: int
    retry_policy: Dict[str, Any]
    priority: int


@dataclass
class ToolExecutionResult:
    success: bool
    content: Dict[str, Any]
    error_code: Optional[str]
    engine_used: str
    degraded: bool
    correlation_id: str
    duration_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "error_code": self.error_code,
            "engine_used": self.engine_used,
            "degraded": self.degraded,
            "correlation_id": self.correlation_id,
            "duration_ms": self.duration_ms,
        }


def _normalize_runtime_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG))
    cfg.update(raw or {})

    engine_priority = cfg.get("engine_priority") or {}
    if not isinstance(engine_priority, dict):
        engine_priority = {}
    normalized_priority = {
        "python": int(engine_priority.get("python", DEFAULT_RUNTIME_CONFIG["engine_priority"]["python"])),
        "ts_sidecar": int(engine_priority.get("ts_sidecar", DEFAULT_RUNTIME_CONFIG["engine_priority"]["ts_sidecar"])),
    }
    cfg["engine_priority"] = normalized_priority

    routes = cfg.get("tool_routes") or {}
    if not isinstance(routes, dict):
        routes = {}
    normalized_routes: Dict[str, str] = {}
    for name, engine in routes.items():
        n = str(name).strip()
        e = str(engine).strip().lower()
        if not n:
            continue
        if e not in {"python", "ts_sidecar"}:
            continue
        normalized_routes[n] = e
    cfg["tool_routes"] = normalized_routes

    default_engine = str(cfg.get("default_engine") or "python").strip().lower()
    if default_engine not in {"python", "ts_sidecar"}:
        default_engine = "python"
    cfg["default_engine"] = default_engine

    retry_policy = cfg.get("retry_policy") or {}
    if not isinstance(retry_policy, dict):
        retry_policy = {}
    cfg["retry_policy"] = {
        "max_retries": max(0, int(retry_policy.get("max_retries", DEFAULT_RUNTIME_CONFIG["retry_policy"]["max_retries"]))),
        "base_delay_seconds": max(
            0.1, float(retry_policy.get("base_delay_seconds", DEFAULT_RUNTIME_CONFIG["retry_policy"]["base_delay_seconds"]))
        ),
        "max_delay_seconds": max(
            0.5, float(retry_policy.get("max_delay_seconds", DEFAULT_RUNTIME_CONFIG["retry_policy"]["max_delay_seconds"]))
        ),
    }

    cfg["default_timeout_ms"] = max(1000, int(cfg.get("default_timeout_ms", DEFAULT_RUNTIME_CONFIG["default_timeout_ms"])))

    return cfg


def load_runtime_config(session: Session) -> Dict[str, Any]:
    row = session.exec(select(AppConfig).where(AppConfig.key == RUNTIME_CONFIG_KEY)).first()
    if not row:
        return _normalize_runtime_config({})

    try:
        raw = json.loads(row.value or "{}")
    except Exception:
        raw = {}
    return _normalize_runtime_config(raw)


def save_runtime_config(session: Session, cfg: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_runtime_config(cfg)

    row = session.exec(select(AppConfig).where(AppConfig.key == RUNTIME_CONFIG_KEY)).first()
    now = datetime.utcnow()
    if row:
        row.value = json.dumps(normalized)
        row.updated_at = now
        row.description = "MCP runtime route and retry config"
        session.add(row)
    else:
        row = AppConfig(
            key=RUNTIME_CONFIG_KEY,
            value=json.dumps(normalized),
            description="MCP runtime route and retry config",
            created_at=now,
            updated_at=now,
        )
        session.add(row)

    session.commit()
    return normalized


def _remote_tool_to_spec(item: Dict[str, Any]) -> Optional[UnifiedToolSpec]:
    name = str(item.get("name") or "").strip()
    if not name:
        return None

    description = str(item.get("description") or "").strip()
    input_schema = item.get("inputSchema") or item.get("input_schema") or {}
    if not isinstance(input_schema, dict):
        input_schema = {}

    return UnifiedToolSpec(
        name=name,
        description=description,
        input_schema=input_schema,
        permission="read",
        route_key=name,
        fallback_policy="graceful_degrade",
    )


class UnifiedRegistry:
    """Combines local Python tool registry + remote sidecar tool manifest."""

    def list_local_specs(self) -> List[UnifiedToolSpec]:
        specs: List[UnifiedToolSpec] = []
        for spec in REGISTRY.iter_specs():
            specs.append(
                UnifiedToolSpec(
                    name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    permission=spec.permission,
                    route_key=spec.route_key or spec.name,
                    fallback_policy=spec.fallback_policy,
                )
            )
        return specs

    def list_remote_specs(self, remote_tools: List[Dict[str, Any]]) -> List[UnifiedToolSpec]:
        specs: List[UnifiedToolSpec] = []
        for item in remote_tools:
            if not isinstance(item, dict):
                continue
            spec = _remote_tool_to_spec(item)
            if spec:
                specs.append(spec)
        return specs

    def build_routes(
        self,
        session: Session,
        remote_tools: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        cfg = load_runtime_config(session)
        engine_priority = cfg["engine_priority"]
        timeout_ms = cfg["default_timeout_ms"]
        retry_policy = cfg["retry_policy"]
        route_overrides = cfg["tool_routes"]
        default_engine = cfg["default_engine"]

        local_specs = self.list_local_specs()
        remote_specs = self.list_remote_specs(remote_tools)

        tools: Dict[str, Dict[str, Any]] = {}

        for spec in local_specs:
            row = tools.setdefault(
                spec.name,
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "permission": spec.permission,
                    "fallback_policy": spec.fallback_policy,
                    "routes": [],
                },
            )
            row["routes"].append(
                ToolRoute(
                    engine="python",
                    target=spec.route_key or spec.name,
                    timeout_ms=timeout_ms,
                    retry_policy=retry_policy,
                    priority=int(engine_priority.get("python", 100)),
                )
            )

        for spec in remote_specs:
            row = tools.setdefault(
                spec.name,
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "permission": spec.permission,
                    "fallback_policy": spec.fallback_policy,
                    "routes": [],
                },
            )
            # Prefer Python description/schema if it already exists.
            if not row["description"]:
                row["description"] = spec.description
            if not row["input_schema"]:
                row["input_schema"] = spec.input_schema
            row["routes"].append(
                ToolRoute(
                    engine="ts_sidecar",
                    target=spec.route_key or spec.name,
                    timeout_ms=timeout_ms,
                    retry_policy=retry_policy,
                    priority=int(engine_priority.get("ts_sidecar", 50)),
                )
            )

        for name, row in tools.items():
            routes: List[ToolRoute] = row["routes"]
            if not routes:
                row["selected_route"] = None
                continue

            override_engine = route_overrides.get(name)
            if override_engine:
                filtered = [r for r in routes if r.engine == override_engine]
                if filtered:
                    routes = filtered

            routes = sorted(
                routes,
                key=lambda r: (
                    -int(r.priority),
                    0 if r.engine == default_engine else 1,
                    0 if r.engine == "python" else 1,
                ),
            )
            row["selected_route"] = routes[0]

        return tools


UNIFIED_REGISTRY = UnifiedRegistry()

