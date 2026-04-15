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
                [claude_bin, "auth", "status"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                # Parse JSON status: {"loggedIn": true, "email": "...", ...}
                try:
                    status = json.loads(result.stdout)
                    if status.get("loggedIn"):
                        email = status.get("email", "")
                        sub = status.get("subscriptionType", "")
                        return True, f"ok — {email} ({sub})" if email else "ok"
                    return False, "Not logged in — run: claude auth login"
                except json.JSONDecodeError:
                    # Non-JSON but exit 0 means likely ok
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
        if getattr(auth_slot, "slot_kind", None) != "api_key":
            raise RuntimeError("Anthropic live model refresh currently requires an API key auth slot")

        import httpx

        api_key = self.resolve_api_key(auth_slot, fallback_env_vars=["ANTHROPIC_API_KEY"])
        resp = httpx.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("Anthropic returned an unexpected model catalog response")

        models: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_name = str(row.get("id") or "").strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            models.append({
                "name": model_name,
                "display": str(row.get("display_name") or model_name).strip(),
                "effort": True,
            })

        return sorted(models, key=lambda item: item["display"].lower())
