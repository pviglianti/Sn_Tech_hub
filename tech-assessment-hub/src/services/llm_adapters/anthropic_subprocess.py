"""Anthropic Claude Code CLI subprocess adapter.

Pipes the SKILL.md + user message into `claude` CLI on stdin. The CLI handles
LLM auth on its own — either a subscription login stored in
~/.claude/.credentials.json or ANTHROPIC_API_KEY if set — so this adapter only
checks that the binary is present. MCP tool calls flow through the .mcp.json
served alongside the app; the final text comes back on stdout.

Requires the `claude` binary on PATH on the VM.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import SkillRunResult


class AnthropicSubprocessAdapter:
    name = "anthropic_cli"

    def __init__(self, claude_binary: str = "claude"):
        self._binary = claude_binary

    def is_available(self) -> bool:
        if shutil.which(self._binary) is None:
            return False
        # Either an API key OR a subscription credential is enough — the CLI
        # resolves auth itself, we just confirm one source exists.
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True
        creds = Path.home() / ".claude" / ".credentials.json"
        return creds.is_file()

    def run(
        self,
        *,
        skill_text: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        timeout_seconds: int = 600,
        mcp_server_url: Optional[str] = None,  # CLI uses .mcp.json instead
        extra: Optional[Dict[str, Any]] = None,
    ) -> SkillRunResult:
        # Compose what the CLI receives on stdin: SKILL is the system prompt,
        # user message is the request. The Claude Code CLI reads the prompt
        # body from stdin when invoked with --print --input-format=text.
        prompt = f"{skill_text}\n\n---\n\nUser request:\n{user_message}"

        cmd = [self._binary, "--print", "--output-format", "json"]
        if model:
            cmd.extend(["--model", model])

        # Wire up the plugin's MCP config so `mcp__tech-assessment-hub__*` tools
        # are registered for the CLI session. Without this the CLI starts with
        # NO project MCP tools and the skill can't call anything.
        mcp_config_path = (extra or {}).get("mcp_config_path")
        if mcp_config_path:
            cmd.extend(["--mcp-config", str(mcp_config_path)])

        if extra and extra.get("strict_mcp_config"):
            cmd.append("--strict-mcp-config")

        # LOCK the toolbox: headless skills must use ONLY the project's MCP
        # tools. Without this the model falls back to Bash+curl (wasteful) or
        # Read/Glob on the VM filesystem (nonsense) instead of the registered
        # mcp__tech-assessment-hub__* tools.
        #
        # Default allow-list = every mcp__tech-assessment-hub__* tool. Callers
        # can override via extra["allowed_tools"] (list[str] or str).
        default_allowed = "mcp__tech-assessment-hub"  # server-scoped pattern
        allowed_tools = (extra or {}).get("allowed_tools") or default_allowed
        if isinstance(allowed_tools, (list, tuple, set)):
            allowed_tools = ",".join(allowed_tools)
        cmd.extend(["--allowed-tools", str(allowed_tools)])

        # Non-interactive runs can't answer permission prompts. Default to
        # skipping them so MCP tool calls actually execute. Opt out by passing
        # extra={"require_permissions": True}.
        if not (extra and extra.get("require_permissions")):
            cmd.append("--dangerously-skip-permissions")

        env = os.environ.copy()
        # pass through MCP config — we keep the existing .mcp.json discovery flow
        if extra and extra.get("env"):
            env.update(extra["env"])

        started = time.monotonic()
        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return SkillRunResult(
                success=False,
                output="",
                duration_seconds=time.monotonic() - started,
                transport=self.name,
                error=f"claude CLI timed out after {timeout_seconds}s",
                raw={"timeout": True},
            )

        duration = time.monotonic() - started

        if completed.returncode != 0:
            return SkillRunResult(
                success=False,
                output=completed.stdout or "",
                duration_seconds=duration,
                transport=self.name,
                error=(completed.stderr or "claude CLI failed").strip()[:2000],
                raw={"returncode": completed.returncode},
            )

        # Parse JSON output if produced
        output_text = ""
        tool_calls = 0
        in_tokens = 0
        out_tokens = 0
        cache_read = 0
        cache_write = 0
        raw: Dict[str, Any] = {}
        try:
            payload = json.loads(completed.stdout or "{}")
            raw = payload
            output_text = payload.get("result") or payload.get("text") or ""
            usage = payload.get("usage") or {}
            in_tokens = usage.get("input_tokens", 0)
            out_tokens = usage.get("output_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            cache_write = usage.get("cache_creation_input_tokens", 0)
            tool_calls = payload.get("num_turns", 0) or len(payload.get("messages", []) or [])
        except (json.JSONDecodeError, ValueError):
            # Fallback: treat whole stdout as the result text
            output_text = completed.stdout or ""

        return SkillRunResult(
            success=True,
            output=output_text,
            tool_call_count=tool_calls,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            duration_seconds=duration,
            transport=self.name,
            raw=raw,
        )
