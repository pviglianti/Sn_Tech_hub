"""Persistent audit events for MCP runtime routing/execution."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...database import get_db_path


_AUDIT_LOCK = threading.Lock()
_AUDIT_PATH = Path(get_db_path()).with_name("mcp_runtime_audit.jsonl")


def record_audit_event(event: Dict[str, Any]) -> None:
    """Append one runtime audit event as JSONL."""
    row = dict(event)
    row.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")

    _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(row, default=str, separators=(",", ":"))

    with _AUDIT_LOCK:
        with _AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(payload + "\n")


def tail_audit_events(limit: int = 200) -> List[Dict[str, Any]]:
    """Return latest runtime audit events (best-effort parser)."""
    limit = max(1, min(int(limit), 2000))
    if not _AUDIT_PATH.exists():
        return []

    with _AUDIT_LOCK:
        lines = _AUDIT_PATH.read_text(encoding="utf-8").splitlines()

    out: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                out.append(parsed)
        except Exception:
            continue
    return out


def build_audit_event(
    *,
    actor: str,
    tool_name: str,
    engine: str,
    success: bool,
    correlation_id: str,
    duration_ms: int,
    degraded: bool = False,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "actor": actor,
        "tool_name": tool_name,
        "engine": engine,
        "success": bool(success),
        "correlation_id": correlation_id,
        "duration_ms": int(duration_ms),
        "degraded": bool(degraded),
        "error_code": error_code,
        "error_message": error_message,
    }

