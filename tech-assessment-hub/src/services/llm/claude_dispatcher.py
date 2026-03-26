"""Claude Code CLI dispatcher."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base_dispatcher import BaseDispatcher, DispatchResult

logger = logging.getLogger(__name__)

_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "max": "max"}


class ClaudeDispatcher(BaseDispatcher):
    """Dispatcher for Anthropic's Claude Code CLI."""

    provider_kind = "anthropic"

    def map_effort(self, unified_level: str) -> Optional[str]:
        return _EFFORT_MAP.get(unified_level)

    def build_cli_command(
        self,
        prompt: str,
        model: str,
        effort: Optional[str],
        tools: Optional[List[str]],
    ) -> List[str]:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("Claude CLI not found on PATH")

        cmd = [
            claude_bin, "-p",
            "--output-format", "json",
            "--model", model,
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
        ]
        native_effort = self.map_effort(effort) if effort else None
        if native_effort:
            cmd.extend(["--effort", native_effort])
        if tools:
            cmd.extend(["--allowedTools", ",".join(tools)])
        return cmd

    def parse_cli_output(self, stdout: str) -> DispatchResult:
        stdout = stdout.strip()
        parsed: Optional[dict] = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                for line in reversed(stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            parsed = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                if parsed is None:
                    parsed = {"raw_output": stdout[:2000]}

        return DispatchResult(
            success=True,
            batch_index=0,
            total_batches=1,
            artifacts_processed=parsed.get("processed", 0) if parsed else 0,
            provider_kind=self.provider_kind,
            model_name="",
            llm_output=parsed,
            budget_used_usd=parsed.get("cost_usd") if parsed else None,
        )

    def test_cli_auth(self) -> tuple[bool, str]:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            return False, "Claude CLI not found on PATH"
        try:
            result = subprocess.run(
                [claude_bin, "-p", "--max-turns", "0", "respond with ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return True, "ok"
            return False, f"error: exit {result.returncode} — {result.stderr[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def test_api_key(self, api_key: str) -> tuple[bool, str]:
        try:
            import httpx
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ok"}],
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "ok"
            return False, f"error: HTTP {resp.status_code} — {resp.text[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def fetch_models(self, auth_slot: Any) -> List[Dict[str, Any]]:
        return []
