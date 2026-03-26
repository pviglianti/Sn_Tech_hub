"""Gemini CLI dispatcher."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base_dispatcher import BaseDispatcher, DispatchResult

logger = logging.getLogger(__name__)


class GeminiDispatcher(BaseDispatcher):
    """Dispatcher for Google's Gemini CLI."""

    provider_kind = "google"

    def map_effort(self, unified_level: str) -> Optional[str]:
        return None

    def build_cli_command(self, prompt, model, effort, tools):
        gemini_bin = shutil.which("gemini")
        if not gemini_bin:
            raise RuntimeError("Gemini CLI not found on PATH")
        return [gemini_bin, "-p", "--model", model, "--approval-mode", "yolo", "--output-format", "stream-json"]

    def parse_cli_output(self, stdout):
        stdout = stdout.strip()
        parsed = None
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
            success=True, batch_index=0, total_batches=1,
            artifacts_processed=parsed.get("processed", 0) if parsed else 0,
            provider_kind=self.provider_kind, model_name="", llm_output=parsed,
        )

    def test_cli_auth(self):
        gemini_bin = shutil.which("gemini")
        if not gemini_bin:
            return False, "Gemini CLI not found on PATH"
        try:
            result = subprocess.run([gemini_bin, "--prompt", "respond with just ok"], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return True, "ok"
            return False, f"error: exit {result.returncode} — {result.stderr[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def test_api_key(self, api_key):
        try:
            import httpx
            resp = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}", timeout=15)
            if resp.status_code == 200:
                return True, "ok"
            return False, f"error: HTTP {resp.status_code} — {resp.text[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def fetch_models(self, auth_slot):
        return []
