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
        if getattr(auth_slot, "slot_kind", None) != "api_key":
            raise RuntimeError("Gemini live model refresh currently requires an API key auth slot")

        import httpx

        api_key = self.resolve_api_key(
            auth_slot,
            fallback_env_vars=["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        )

        models: List[Dict[str, Any]] = []
        seen: set[str] = set()
        page_token: Optional[str] = None

        while True:
            params: Dict[str, Any] = {"key": api_key, "pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            resp = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("models") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise RuntimeError("Gemini returned an unexpected model catalog response")

            for row in rows:
                if not isinstance(row, dict):
                    continue
                methods = row.get("supportedGenerationMethods") or []
                if isinstance(methods, list) and methods and "generateContent" not in methods:
                    continue
                raw_name = str(row.get("name") or "").strip()
                if not raw_name:
                    continue
                model_name = raw_name.split("/", 1)[-1]
                if model_name in seen:
                    continue
                seen.add(model_name)
                models.append({
                    "name": model_name,
                    "display": str(row.get("displayName") or model_name).strip(),
                    "effort": False,
                })

            page_token = str(payload.get("nextPageToken") or "").strip() if isinstance(payload, dict) else ""
            if not page_token:
                break

        return sorted(models, key=lambda item: item["display"].lower())
