"""MCP bridge manager for sidecar lifecycle and management operations.

Extracted from the original src/mcp/bridge.py during Wave 2 restructure.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, Generator, List, Optional

import requests

from .config_store import normalize_bridge_config


def _extract_json_rpc_tools(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    result = payload.get("result")
    if isinstance(result, dict):
        tools = result.get("tools")
        if isinstance(tools, list):
            return [t for t in tools if isinstance(t, dict)]

    tools = payload.get("tools")
    if isinstance(tools, list):
        return [t for t in tools if isinstance(t, dict)]
    return []


class MCPBridgeManager:
    """Manage MCP sidecar process, health state, and bridge operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen[str]] = None
        self._started_at: Optional[datetime] = None
        self._last_exit_code: Optional[int] = None
        self._last_error: Optional[str] = None
        self._logs: Deque[Dict[str, Any]] = deque(maxlen=1000)
        self._events: Deque[Dict[str, Any]] = deque(maxlen=1000)

        self._health_state: str = "unavailable"
        self._consecutive_failures: int = 0
        self._last_success_at: Optional[datetime] = None
        self._last_failure_at: Optional[datetime] = None
        self._next_retry_at: Optional[datetime] = None
        self._last_restart_attempt_at: Optional[datetime] = None
        self._auto_restart_count: int = 0
        self._remote_tools_cache: List[Dict[str, Any]] = []
        self._remote_tools_cached_at: Optional[datetime] = None

    def _emit(self, event_type: str, properties: Dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "properties": properties,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self._events.append(event)

    def _append_log(self, stream: str, line: str) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stream": stream,
            "line": line.rstrip("\n"),
        }
        self._logs.append(entry)

    def _drain_pipe(self, pipe, stream: str) -> None:
        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    break
                self._append_log(stream, line)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _resolve_rpc_url(self, cfg: Dict[str, Any]) -> str:
        cfg = normalize_bridge_config(cfg)
        rpc_url = cfg.get("rpc_url") or ""
        if rpc_url:
            return rpc_url

        base = cfg.get("management_base_url") or ""
        if not base:
            return ""
        return f"{base}/mcp"

    def _rpc_request(self, cfg: Dict[str, Any], payload: Dict[str, Any], timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        cfg = normalize_bridge_config(cfg)
        rpc_url = self._resolve_rpc_url(cfg)
        if not rpc_url:
            return {"success": False, "error": "rpc_url (or management_base_url) is not configured"}

        timeout = max(1.0, float((timeout_ms or cfg.get("tool_timeout_ms") or 12000) / 1000.0))
        try:
            response = requests.post(rpc_url, json=payload, timeout=timeout)
            try:
                body: Any = response.json()
            except Exception:
                body = {"raw": response.text}

            if not response.ok:
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "url": rpc_url,
                    "error": f"HTTP {response.status_code}",
                    "payload": body,
                }
            return {
                "success": True,
                "status_code": response.status_code,
                "url": rpc_url,
                "payload": body,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "url": rpc_url}

    def record_tool_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._last_success_at = datetime.utcnow()
            self._next_retry_at = None
            self._health_state = "healthy"
            self._last_error = None
        self._emit("bridge.health", {"state": "healthy"})

    def record_tool_failure(self, error: str) -> None:
        with self._lock:
            self._consecutive_failures += 1
            self._last_failure_at = datetime.utcnow()
            self._last_error = str(error)

            if self._consecutive_failures <= 1:
                self._health_state = "degraded"
            elif self._consecutive_failures == 2:
                self._health_state = "recovering"
            else:
                self._health_state = "unavailable"

            backoff_seconds = min(60, 2 ** max(0, self._consecutive_failures - 1))
            self._next_retry_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
            state = self._health_state
            failures = self._consecutive_failures
            retry_at = self._next_retry_at.isoformat() + "Z"

        self._emit(
            "bridge.tool_failure",
            {
                "error": str(error),
                "health_state": state,
                "consecutive_failures": failures,
                "next_retry_at": retry_at,
            },
        )

    def can_attempt_tool_call(self) -> bool:
        with self._lock:
            if self._next_retry_at is None:
                return True
            return datetime.utcnow() >= self._next_retry_at

    def maybe_auto_restart(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        cfg = normalize_bridge_config(cfg)
        now = datetime.utcnow()
        cooldown = float(cfg.get("restart_cooldown_seconds", 30.0))

        with self._lock:
            if self._last_restart_attempt_at and (now - self._last_restart_attempt_at).total_seconds() < cooldown:
                return {
                    "success": False,
                    "error": "restart_cooldown_active",
                    "next_allowed_at": (
                        self._last_restart_attempt_at + timedelta(seconds=cooldown)
                    ).isoformat()
                    + "Z",
                }
            self._last_restart_attempt_at = now

        result = self.restart(cfg)
        if result.get("success"):
            with self._lock:
                self._auto_restart_count += 1
                self._health_state = "recovering"
            self._emit("bridge.auto_restarted", {"count": self._auto_restart_count})
        return result

    def start(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        cfg = normalize_bridge_config(cfg)

        with self._lock:
            if self._is_running():
                return {
                    "success": True,
                    "message": "MCP bridge sidecar is already running",
                    "status": self.status(),
                }

            command = cfg.get("command", "")
            if not command:
                return {"success": False, "error": "Bridge command is not configured"}

            cmd = [command] + list(cfg.get("args", []))
            env = os.environ.copy()
            env.update(cfg.get("env", {}))

            cwd = cfg.get("cwd") or None
            if cwd and not os.path.isdir(cwd):
                return {"success": False, "error": f"Configured cwd does not exist: {cwd}"}

            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=cwd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except Exception as exc:
                self._last_error = str(exc)
                self._health_state = "unavailable"
                self._emit("bridge.start_failed", {"error": str(exc), "cmd": cmd})
                return {"success": False, "error": str(exc)}

            self._started_at = datetime.utcnow()
            self._last_exit_code = None
            self._last_error = None
            self._health_state = "recovering"
            self._emit("bridge.started", {"pid": self._process.pid, "cmd": cmd})

            if self._process.stdout is not None:
                threading.Thread(target=self._drain_pipe, args=(self._process.stdout, "stdout"), daemon=True).start()
            if self._process.stderr is not None:
                threading.Thread(target=self._drain_pipe, args=(self._process.stderr, "stderr"), daemon=True).start()

            return {
                "success": True,
                "message": "MCP bridge sidecar started",
                "pid": self._process.pid,
            }

    def stop(self, timeout_seconds: float = 8.0) -> Dict[str, Any]:
        with self._lock:
            if not self._is_running():
                self._process = None
                self._started_at = None
                self._health_state = "unavailable"
                return {"success": True, "message": "MCP bridge sidecar is not running"}

            proc = self._process
            assert proc is not None

            proc.terminate()
            try:
                proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

            self._last_exit_code = proc.returncode
            self._process = None
            self._started_at = None
            self._health_state = "unavailable"
            self._emit("bridge.stopped", {"exit_code": self._last_exit_code})

            return {
                "success": True,
                "message": "MCP bridge sidecar stopped",
                "exit_code": self._last_exit_code,
            }

    def restart(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        stop_result = self.stop()
        start_result = self.start(cfg)
        return {
            "success": bool(start_result.get("success")),
            "stop": stop_result,
            "start": start_result,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            running = self._is_running()
            pid = self._process.pid if running and self._process is not None else None
            uptime_seconds: Optional[int] = None
            if running and self._started_at:
                uptime_seconds = int((datetime.utcnow() - self._started_at).total_seconds())

            return {
                "running": running,
                "pid": pid,
                "started_at": self._started_at.isoformat() + "Z" if self._started_at else None,
                "uptime_seconds": uptime_seconds,
                "last_exit_code": self._last_exit_code,
                "last_error": self._last_error,
                "health_state": self._health_state,
                "consecutive_failures": self._consecutive_failures,
                "last_success_at": self._last_success_at.isoformat() + "Z" if self._last_success_at else None,
                "last_failure_at": self._last_failure_at.isoformat() + "Z" if self._last_failure_at else None,
                "next_retry_at": self._next_retry_at.isoformat() + "Z" if self._next_retry_at else None,
                "auto_restart_count": self._auto_restart_count,
            }

    def tail_logs(self, limit: int = 200) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        return list(self._logs)[-limit:]

    def iter_local_events(self, poll_interval: float = 1.0) -> Generator[Dict[str, Any], None, None]:
        cursor = len(self._events)
        while True:
            events = list(self._events)
            while cursor < len(events):
                yield events[cursor]
                cursor += 1

            # Sidecar crash detection
            with self._lock:
                if self._process is not None and self._process.poll() is not None:
                    code = self._process.returncode
                    self._last_exit_code = code
                    self._process = None
                    self._started_at = None
                    self._health_state = "unavailable"
                    self._emit("bridge.exited", {"exit_code": code})

            yield {"type": "bridge.heartbeat", "properties": {}, "timestamp": datetime.utcnow().isoformat() + "Z"}
            time.sleep(poll_interval)

    def _management_request(
        self,
        cfg: Dict[str, Any],
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        cfg = normalize_bridge_config(cfg)
        base_url = cfg.get("management_base_url", "")
        if not base_url:
            return {"success": False, "error": "management_base_url is not configured"}

        url = f"{base_url}{path}"
        try:
            response = requests.request(method=method, url=url, json=payload, timeout=10)
            body: Any
            try:
                body = response.json()
            except Exception:
                body = response.text

            return {
                "success": response.ok,
                "status_code": response.status_code,
                "url": url,
                "body": body,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "url": url}

    def trigger_reload(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return self._management_request(cfg, "POST", "/mcp/reload")

    def trigger_reconnect_all(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return self._management_request(cfg, "POST", "/mcp/reconnect-all")

    def trigger_reconnect(self, cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
        if not name.strip():
            return {"success": False, "error": "Server name is required"}
        return self._management_request(cfg, "POST", f"/mcp/{name}/reconnect")

    def fetch_state(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return self._management_request(cfg, "GET", "/mcp/state")

    def fetch_remote_tools(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        request_payload = {
            "jsonrpc": "2.0",
            "id": "bridge-tools-list",
            "method": "tools/list",
            "params": {},
        }
        result = self._rpc_request(cfg, request_payload)
        if not result.get("success"):
            if self._remote_tools_cache:
                return {
                    "success": True,
                    "tools": list(self._remote_tools_cache),
                    "stale": True,
                    "error": result.get("error"),
                    "cached_at": self._remote_tools_cached_at.isoformat() + "Z" if self._remote_tools_cached_at else None,
                }
            return result

        payload = result.get("payload")
        tools = _extract_json_rpc_tools(payload)
        if not tools:
            if self._remote_tools_cache:
                return {
                    "success": True,
                    "tools": list(self._remote_tools_cache),
                    "stale": True,
                    "error": "No tools found in sidecar response",
                    "payload": payload,
                    "cached_at": self._remote_tools_cached_at.isoformat() + "Z" if self._remote_tools_cached_at else None,
                }
            return {
                "success": False,
                "error": "No tools found in sidecar response",
                "payload": payload,
                "url": result.get("url"),
            }
        self._remote_tools_cache = list(tools)
        self._remote_tools_cached_at = datetime.utcnow()
        return {
            "success": True,
            "tools": tools,
            "url": result.get("url"),
            "status_code": result.get("status_code"),
            "payload": payload,
            "stale": False,
            "cached_at": self._remote_tools_cached_at.isoformat() + "Z",
        }

    def call_remote_tool(
        self,
        cfg: Dict[str, Any],
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        timeout_ms: int = 12000,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id or f"bridge-call-{tool_name}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }
        return self._rpc_request(cfg, payload, timeout_ms=timeout_ms)

    def remote_event_stream(self, cfg: Dict[str, Any]) -> Generator[str, None, None]:
        cfg = normalize_bridge_config(cfg)
        event_url = cfg.get("event_url") or ""
        if not event_url:
            raise ValueError("event_url is not configured")

        with requests.get(event_url, stream=True, timeout=(5, 300)) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                if line.startswith("data:"):
                    yield line[5:].strip()


BRIDGE_MANAGER = MCPBridgeManager()
