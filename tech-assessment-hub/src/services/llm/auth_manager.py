"""LLM auth manager — CLI detection, credential storage, testing."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from .models import LLMProvider, LLMAuthSlot
from .claude_dispatcher import ClaudeDispatcher
from .gemini_dispatcher import GeminiDispatcher
from .codex_dispatcher import CodexDispatcher

logger = logging.getLogger(__name__)

_CLI_MAP = {
    "anthropic": "claude",
    "google": "gemini",
    "openai": "codex",
}

_DISPATCHER_MAP = {
    "anthropic": ClaudeDispatcher,
    "google": GeminiDispatcher,
    "openai": CodexDispatcher,
}


class AuthManager:
    """Manages LLM provider authentication — CLI detection, login, API keys."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def detect_clis(self) -> Dict[str, Dict[str, Any]]:
        """Check which LLM CLIs are installed and their versions."""
        result = {}
        for kind, cli_name in _CLI_MAP.items():
            path = shutil.which(cli_name)
            if not path:
                result[kind] = {"installed": False, "version": None, "path": None}
                continue

            version = None
            try:
                proc = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                if proc.returncode == 0:
                    version = proc.stdout.strip().split("\n")[0].strip()
            except Exception:
                pass

            result[kind] = {"installed": True, "version": version, "path": path}
        return result

    def trigger_cli_login(self, provider_kind: str) -> None:
        """Open Terminal.app with the CLI login command (macOS)."""
        cli_name = _CLI_MAP.get(provider_kind)
        if not cli_name:
            raise ValueError(f"Unknown provider_kind: {provider_kind}")

        import platform
        if platform.system() == "Darwin":
            import subprocess as sp
            sp.Popen([
                "osascript", "-e",
                f'tell application "Terminal" to do script "{cli_name} login"',
            ])
        else:
            logger.warning("CLI login trigger only supported on macOS")

    def store_api_key(self, provider_id: int, api_key: str) -> LLMAuthSlot:
        """Create an API key auth slot. Deactivates any existing slots for this provider."""
        existing = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).all()
        for slot in existing:
            slot.is_active = False
            self._session.add(slot)

        hint = api_key[-4:] if len(api_key) >= 4 else api_key
        new_slot = LLMAuthSlot(
            provider_id=provider_id,
            slot_kind="api_key",
            api_key=api_key,
            api_key_hint=hint,
            is_active=True,
        )
        self._session.add(new_slot)
        self._session.commit()
        self._session.refresh(new_slot)
        return new_slot

    def create_cli_slot(self, provider_id: int) -> LLMAuthSlot:
        """Create a CLI auth slot. Deactivates existing slots."""
        existing = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).all()
        for slot in existing:
            slot.is_active = False
            self._session.add(slot)

        new_slot = LLMAuthSlot(
            provider_id=provider_id,
            slot_kind="cli",
            is_active=True,
        )
        self._session.add(new_slot)
        self._session.commit()
        self._session.refresh(new_slot)
        return new_slot

    def test_auth_slot(self, slot_id: int) -> tuple[bool, str]:
        """Test an auth slot by routing to the correct dispatcher's test method."""
        slot = self._session.get(LLMAuthSlot, slot_id)
        if not slot:
            return False, "Auth slot not found"

        provider = self._session.get(LLMProvider, slot.provider_id)
        if not provider:
            return False, "Provider not found"

        dispatcher_cls = _DISPATCHER_MAP.get(provider.provider_kind)
        if not dispatcher_cls:
            return False, f"No dispatcher for {provider.provider_kind}"

        dispatcher = dispatcher_cls()

        if slot.slot_kind == "cli":
            ok, msg = dispatcher.test_cli_auth()
        elif slot.slot_kind == "api_key":
            key = slot.api_key
            if slot.env_var_name:
                import os
                key = os.environ.get(slot.env_var_name, key)
            if not key:
                return False, "No API key configured"
            ok, msg = dispatcher.test_api_key(key)
        else:
            return False, f"Unknown slot_kind: {slot.slot_kind}"

        slot.last_tested_at = datetime.utcnow().isoformat()
        slot.last_test_result = "ok" if ok else msg
        self._session.add(slot)
        self._session.commit()

        return ok, msg

    def get_active_auth(self, provider_id: int) -> Optional[LLMAuthSlot]:
        """Get the active auth slot for a provider."""
        return self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()
