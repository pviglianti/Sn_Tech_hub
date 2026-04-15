"""OpenAI Codex CLI dispatcher."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base_dispatcher import BaseDispatcher, DispatchResult

logger = logging.getLogger(__name__)

_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "max": "high"}


class CodexDispatcher(BaseDispatcher):
    """Dispatcher for OpenAI's Codex CLI."""

    provider_kind = "openai"

    def map_effort(self, unified_level: str) -> Optional[str]:
        return _EFFORT_MAP.get(unified_level)

    def build_cli_command(self, prompt, model, effort, tools):
        codex_bin = shutil.which("codex")
        if not codex_bin:
            raise RuntimeError("Codex CLI not found on PATH")
        return [codex_bin, "exec", "--model", model, "--json", "--dangerously-bypass-approvals-and-sandbox"]

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
        codex_bin = shutil.which("codex")
        if not codex_bin:
            return False, "Codex CLI not found on PATH"
        try:
            result = subprocess.run([codex_bin, "login", "status"], capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                return True, "ok"
            return False, f"error: exit {result.returncode} — {result.stderr[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def test_api_key(self, api_key):
        try:
            import httpx
            resp = httpx.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
            if resp.status_code == 200:
                return True, "ok"
            return False, f"error: HTTP {resp.status_code} — {resp.text[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def fetch_models(self, auth_slot):
        if getattr(auth_slot, "slot_kind", None) != "api_key":
            raise RuntimeError("OpenAI live model refresh currently requires an API key auth slot")

        import httpx

        api_key = self.resolve_api_key(auth_slot, fallback_env_vars=["OPENAI_API_KEY"])
        resp = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("OpenAI returned an unexpected model catalog response")

        excluded_fragments = (
            "audio",
            "realtime",
            "search",
            "transcribe",
            "tts",
            "embedding",
            "moderation",
            "image",
            "whisper",
            "omni",
            "chatgpt",
        )

        models: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_name = str(row.get("id") or "").strip()
            if not model_name or model_name in seen:
                continue
            if not (model_name.startswith("gpt-") or model_name.startswith("o")):
                continue
            lowered = model_name.lower()
            if any(fragment in lowered for fragment in excluded_fragments):
                continue
            seen.add(model_name)
            models.append({
                "name": model_name,
                "display": model_name,
                "effort": True,
            })

        return sorted(models, key=lambda item: item["name"].lower())
