"""AppConfig-backed bridge configuration load/save.

Extracted from the original src/mcp/bridge.py during Wave 2 restructure.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from sqlmodel import Session, select

from ...models import AppConfig


CONFIG_KEY = "mcp_bridge_config"


def default_bridge_config() -> Dict[str, Any]:
    return {
        "enabled": False,
        "command": "",
        "args": [],
        "cwd": "",
        "env": {},
        "management_base_url": "",
        "event_url": "",
        "health_url": "",
        "rpc_url": "",
        "tool_timeout_ms": 12000,
        "max_retries": 2,
        "retry_base_delay_seconds": 1.0,
        "retry_max_delay_seconds": 8.0,
        "restart_cooldown_seconds": 30.0,
    }


def normalize_bridge_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    cfg = default_bridge_config()
    cfg.update(raw or {})

    cfg["enabled"] = bool(cfg.get("enabled", False))
    cfg["command"] = str(cfg.get("command") or "").strip()

    args = cfg.get("args") or []
    if not isinstance(args, list):
        args = []
    cfg["args"] = [str(item) for item in args if str(item).strip()]

    cfg["cwd"] = str(cfg.get("cwd") or "").strip()

    env = cfg.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    cfg["env"] = {str(k): str(v) for k, v in env.items()}

    cfg["management_base_url"] = str(cfg.get("management_base_url") or "").strip().rstrip("/")
    cfg["event_url"] = str(cfg.get("event_url") or "").strip()
    cfg["health_url"] = str(cfg.get("health_url") or "").strip()
    cfg["rpc_url"] = str(cfg.get("rpc_url") or "").strip()

    cfg["tool_timeout_ms"] = max(1000, int(cfg.get("tool_timeout_ms") or 12000))
    cfg["max_retries"] = max(0, int(cfg.get("max_retries") or 2))
    cfg["retry_base_delay_seconds"] = max(0.1, float(cfg.get("retry_base_delay_seconds") or 1.0))
    cfg["retry_max_delay_seconds"] = max(
        cfg["retry_base_delay_seconds"], float(cfg.get("retry_max_delay_seconds") or 8.0)
    )
    cfg["restart_cooldown_seconds"] = max(1.0, float(cfg.get("restart_cooldown_seconds") or 30.0))

    return cfg


# Keep private alias for internal callers that used the old name
_normalize_bridge_config = normalize_bridge_config


def load_bridge_config(session: Session) -> Dict[str, Any]:
    row = session.exec(select(AppConfig).where(AppConfig.key == CONFIG_KEY)).first()
    if not row:
        return default_bridge_config()

    try:
        data = json.loads(row.value or "{}")
    except Exception:
        data = {}
    return normalize_bridge_config(data)


def save_bridge_config(session: Session, cfg: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_bridge_config(cfg)

    row = session.exec(select(AppConfig).where(AppConfig.key == CONFIG_KEY)).first()
    now = datetime.utcnow()
    if row:
        row.value = json.dumps(normalized)
        row.updated_at = now
        row.description = "MCP sidecar bridge settings"
        session.add(row)
    else:
        row = AppConfig(
            key=CONFIG_KEY,
            value=json.dumps(normalized),
            description="MCP sidecar bridge settings",
            created_at=now,
            updated_at=now,
        )
        session.add(row)

    session.commit()
    return normalized
