"""Anthropic Messages API adapter for the SkillDispatcher.

Sends SKILL.md as the system prompt (with prompt caching) and runs the
agentic loop. Two transport paths:

- **Option A (preferred):** native MCP connector via `mcp_servers` parameter.
  The API discovers and calls our MCP tools directly. One round-trip.
- **Option B (fallback):** manual tool-use loop. We fetch our MCP tool
  schemas, translate to Anthropic tool format, then drive the loop ourselves
  (response → tool_use → MCP call → tool_result → repeat).

The adapter tries A first and auto-falls back to B if the API rejects the
mcp-client beta header. No env var toggle needed — A vs B is purely a
transport detail; output is identical.

The SDK auto-retries 429/5xx (default `max_retries=2`).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from . import SkillRunResult


logger = logging.getLogger(__name__)


# Beta header for the MCP connector feature. If the API rejects it (your
# account isn't enrolled in the beta), we fall back to manual tool loop.
_MCP_CONNECTOR_BETA = "mcp-client-2025-04-04"

_DEFAULT_MODEL = "claude-opus-4-6"


class AnthropicAPIAdapter:
    name = "anthropic_api"

    def __init__(
        self,
        api_key: Optional[str] = None,
        prefer_mcp_connector: Optional[bool] = None,
    ) -> None:
        # Defer import so the module loads cleanly even if `anthropic` isn't installed yet
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self._anthropic = None
        else:
            self._anthropic = anthropic

        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

        # Allow forcing one path or the other for debugging; default = try A then B.
        if prefer_mcp_connector is None:
            env_pref = (os.environ.get("ANTHROPIC_PREFER_MCP_CONNECTOR") or "").strip().lower()
            self._prefer_mcp = env_pref not in ("0", "false", "no", "off")
        else:
            self._prefer_mcp = prefer_mcp_connector

        # Cache the manual-loop tool list per (mcp_server_url) — fetched once
        # and reused across runs.
        self._mcp_tools_cache: Dict[str, List[Dict[str, Any]]] = {}

    # ─────────────────────────────────────────────────────────────────
    # ProviderAdapter contract
    # ─────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return self._anthropic is not None and bool(self._api_key)

    def run(
        self,
        *,
        skill_text: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 16000,
        timeout_seconds: int = 600,
        mcp_server_url: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> SkillRunResult:
        if not self.is_available():
            return SkillRunResult(
                success=False,
                output="",
                transport=self.name,
                error="anthropic SDK not installed or ANTHROPIC_API_KEY not set",
            )
        if not mcp_server_url:
            return SkillRunResult(
                success=False,
                output="",
                transport=self.name,
                error="mcp_server_url is required for the Anthropic API adapter",
            )

        client = self._anthropic.Anthropic(api_key=self._api_key)
        model = model or _DEFAULT_MODEL
        extra = extra or {}

        started = time.monotonic()

        if self._prefer_mcp:
            try:
                return self._run_mcp_connector(
                    client=client,
                    skill_text=skill_text,
                    user_message=user_message,
                    model=model,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    mcp_server_url=mcp_server_url,
                    started=started,
                )
            except Exception as exc:  # noqa: BLE001
                # Auto-fall-back when the beta header is rejected or the
                # mcp_servers param isn't recognized for this model/account.
                msg = str(exc)
                if any(s in msg.lower() for s in ("beta", "mcp_servers", "unknown parameter", "invalid_request")):
                    logger.warning(
                        "MCP connector path failed (%s); falling back to manual tool loop",
                        msg[:200],
                    )
                else:
                    # Unknown failure — surface the error rather than silently fall back
                    return SkillRunResult(
                        success=False,
                        output="",
                        duration_seconds=time.monotonic() - started,
                        transport=self.name + ":mcp_connector",
                        error=msg[:2000],
                    )

        return self._run_manual_loop(
            client=client,
            skill_text=skill_text,
            user_message=user_message,
            model=model,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            mcp_server_url=mcp_server_url,
            started=started,
        )

    # ─────────────────────────────────────────────────────────────────
    # Option A — MCP connector
    # ─────────────────────────────────────────────────────────────────

    def _run_mcp_connector(
        self,
        *,
        client: Any,
        skill_text: str,
        user_message: str,
        model: str,
        max_tokens: int,
        timeout_seconds: int,
        mcp_server_url: str,
        started: float,
    ) -> SkillRunResult:
        # Streaming (recommended for any high max_tokens; SDK returns the
        # complete final message via get_final_message()).
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=[{
                "type": "text",
                "text": skill_text,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_message}],
            mcp_servers=[{
                "type": "url",
                "name": "tech-assessment-hub",
                "url": mcp_server_url,
            }],
            extra_headers={"anthropic-beta": _MCP_CONNECTOR_BETA},
            timeout=timeout_seconds,
        ) as stream:
            final = stream.get_final_message()

        return self._summarize(
            final=final,
            transport=self.name + ":mcp_connector",
            started=started,
            tool_call_count=self._count_tool_uses(final),
        )

    # ─────────────────────────────────────────────────────────────────
    # Option B — manual tool-use loop
    # ─────────────────────────────────────────────────────────────────

    def _run_manual_loop(
        self,
        *,
        client: Any,
        skill_text: str,
        user_message: str,
        model: str,
        max_tokens: int,
        timeout_seconds: int,
        mcp_server_url: str,
        started: float,
    ) -> SkillRunResult:
        # Discover MCP tools (cached per URL)
        try:
            anthropic_tools = self._fetch_mcp_tools_as_anthropic(mcp_server_url, timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            return SkillRunResult(
                success=False,
                output="",
                duration_seconds=time.monotonic() - started,
                transport=self.name + ":manual_loop",
                error=f"Failed to discover MCP tools: {exc}",
            )

        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": user_message},
        ]
        total_in = 0
        total_out = 0
        cache_read = 0
        cache_write = 0
        tool_call_count = 0
        loop_guard = 50
        final_message = None

        while loop_guard > 0:
            loop_guard -= 1
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": skill_text,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=anthropic_tools,
                messages=messages,
                timeout=timeout_seconds,
            )
            final_message = response

            usage = getattr(response, "usage", None)
            if usage is not None:
                total_in += getattr(usage, "input_tokens", 0) or 0
                total_out += getattr(usage, "output_tokens", 0) or 0
                cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
                cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason != "tool_use":
                break

            # Append assistant turn (preserve full content — required for tool_use_id matching)
            messages.append({"role": "assistant", "content": response.content})

            # Execute every tool_use block and gather results
            tool_results: List[Dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_call_count += 1
                try:
                    result_text = self._call_mcp_tool(
                        mcp_server_url, block.name, dict(block.input or {}), timeout_seconds
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
                except Exception as exc:  # noqa: BLE001
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Tool error: {exc}",
                        "is_error": True,
                    })

            messages.append({"role": "user", "content": tool_results})

        if final_message is None:
            return SkillRunResult(
                success=False, output="",
                duration_seconds=time.monotonic() - started,
                transport=self.name + ":manual_loop",
                error="no response produced",
            )

        # Extract the final assistant text from the last response
        output_text = ""
        for block in final_message.content:
            if getattr(block, "type", None) == "text":
                output_text += block.text

        return SkillRunResult(
            success=True,
            output=output_text,
            tool_call_count=tool_call_count,
            input_tokens=total_in,
            output_tokens=total_out,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            duration_seconds=time.monotonic() - started,
            transport=self.name + ":manual_loop",
            raw={"loop_iterations": 50 - loop_guard, "stop_reason": getattr(final_message, "stop_reason", None)},
        )

    # ─────────────────────────────────────────────────────────────────
    # MCP plumbing for Option B
    # ─────────────────────────────────────────────────────────────────

    def _fetch_mcp_tools_as_anthropic(self, mcp_server_url: str, timeout_seconds: int) -> List[Dict[str, Any]]:
        if mcp_server_url in self._mcp_tools_cache:
            return self._mcp_tools_cache[mcp_server_url]

        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        result = self._post_mcp(mcp_server_url, payload, timeout_seconds)
        tools = result.get("result", {}).get("tools", []) if isinstance(result, dict) else []
        anthropic_tools = []
        for t in tools:
            anthropic_tools.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema") or t.get("input_schema") or {"type": "object"},
            })
        self._mcp_tools_cache[mcp_server_url] = anthropic_tools
        return anthropic_tools

    def _call_mcp_tool(
        self, mcp_server_url: str, name: str, arguments: Dict[str, Any], timeout_seconds: int
    ) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        result = self._post_mcp(mcp_server_url, payload, timeout_seconds)
        # MCP tool/call result is { content: [{type: "text", text: "..."}], isError: bool }
        if isinstance(result, dict) and "error" in result and result["error"]:
            err = result["error"]
            raise RuntimeError(err.get("message") or json.dumps(err))
        body = (result or {}).get("result", {}) if isinstance(result, dict) else {}
        content = body.get("content") or []
        chunks = []
        for c in content:
            if c.get("type") == "text":
                chunks.append(c.get("text", ""))
            else:
                chunks.append(json.dumps(c))
        return "\n".join(chunks) if chunks else json.dumps(body)

    @staticmethod
    def _post_mcp(mcp_server_url: str, payload: Dict[str, Any], timeout_seconds: int) -> Dict[str, Any]:
        with httpx.Client(timeout=timeout_seconds) as http:
            r = http.post(
                mcp_server_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            r.raise_for_status()
            text = r.text
            # Server may stream SSE; pull the data: line
            if text.startswith("event:") or "\ndata: " in text or text.startswith("data: "):
                for line in text.splitlines():
                    if line.startswith("data: "):
                        return json.loads(line[len("data: "):])
                return {}
            return r.json()

    # ─────────────────────────────────────────────────────────────────
    # Shared helpers
    # ─────────────────────────────────────────────────────────────────

    def _summarize(
        self, *, final: Any, transport: str, started: float, tool_call_count: int
    ) -> SkillRunResult:
        usage = getattr(final, "usage", None)
        output_text = ""
        for block in final.content:
            if getattr(block, "type", None) == "text":
                output_text += block.text

        return SkillRunResult(
            success=True,
            output=output_text,
            tool_call_count=tool_call_count,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            duration_seconds=time.monotonic() - started,
            transport=transport,
            raw={"stop_reason": getattr(final, "stop_reason", None)},
        )

    @staticmethod
    def _count_tool_uses(message: Any) -> int:
        count = 0
        for block in getattr(message, "content", []) or []:
            if getattr(block, "type", None) in ("tool_use", "mcp_tool_use", "server_tool_use"):
                count += 1
        return count
