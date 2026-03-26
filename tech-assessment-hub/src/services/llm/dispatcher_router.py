"""Dispatcher router — resolves provider/model/effort per pipeline stage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from sqlmodel import Session, select

from src.models import AppConfig
from .models import LLMProvider, LLMModel, LLMAuthSlot
from .base_dispatcher import BaseDispatcher
from .claude_dispatcher import ClaudeDispatcher
from .gemini_dispatcher import GeminiDispatcher
from .codex_dispatcher import CodexDispatcher

logger = logging.getLogger(__name__)

_DISPATCHER_MAP = {
    "anthropic": ClaudeDispatcher,
    "google": GeminiDispatcher,
    "openai": CodexDispatcher,
}


@dataclass
class ResolvedConfig:
    """Resolved LLM configuration for a pipeline stage."""
    provider_kind: str
    provider_id: int
    model_name: str
    model_id: int
    effort_level: str
    dispatcher: BaseDispatcher
    auth_slot: LLMAuthSlot


class DispatcherRouter:
    """Resolves which LLM provider/model/effort to use for each pipeline stage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_config(self, key: str) -> Optional[str]:
        row = self._session.exec(
            select(AppConfig).where(AppConfig.key == key)
        ).first()
        return row.value if row else None

    def resolve(self, stage: str) -> ResolvedConfig:
        """Resolve provider/model/effort for a stage.

        Resolution chain:
        1. Per-stage override (ai.stage.<stage>.provider_id)
        2. Global default (ai.default_provider_id)
        """
        provider_id_str = (
            self._get_config(f"ai.stage.{stage}.provider_id")
            or self._get_config("ai.default_provider_id")
        )
        if not provider_id_str:
            raise ValueError("No LLM provider configured")

        provider_id = int(provider_id_str)
        provider = self._session.get(LLMProvider, provider_id)
        if not provider:
            raise ValueError(f"Provider {provider_id} not found")

        model_id_str = (
            self._get_config(f"ai.stage.{stage}.model_id")
            or self._get_config("ai.default_model_id")
        )
        if not model_id_str:
            default_model = self._session.exec(
                select(LLMModel).where(
                    LLMModel.provider_id == provider_id,
                    LLMModel.is_default == True,  # noqa: E712
                )
            ).first()
            if not default_model:
                raise ValueError(f"No default model for provider {provider.name}")
            model = default_model
        else:
            model = self._session.get(LLMModel, int(model_id_str))
            if not model:
                raise ValueError(f"Model {model_id_str} not found")

        effort = (
            self._get_config(f"ai.stage.{stage}.effort_level")
            or self._get_config("ai.default_effort_level")
            or "medium"
        )

        auth_slot = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()
        if not auth_slot:
            raise ValueError(f"No active auth for {provider.name}")

        dispatcher_cls = _DISPATCHER_MAP.get(provider.provider_kind)
        if not dispatcher_cls:
            raise ValueError(f"No dispatcher for {provider.provider_kind}")

        return ResolvedConfig(
            provider_kind=provider.provider_kind,
            provider_id=provider.id,
            model_name=model.model_name,
            model_id=model.id,
            effort_level=effort,
            dispatcher=dispatcher_cls(),
            auth_slot=auth_slot,
        )

    def preflight_check(self, stage: str) -> List[str]:
        """Check if a stage can be dispatched. Returns list of blocking issues."""
        errors: List[str] = []

        provider_id_str = (
            self._get_config(f"ai.stage.{stage}.provider_id")
            or self._get_config("ai.default_provider_id")
        )
        if not provider_id_str:
            errors.append("No LLM provider configured. Go to LLM Settings.")
            return errors

        provider = self._session.get(LLMProvider, int(provider_id_str))
        if not provider:
            errors.append(f"Provider ID {provider_id_str} not found.")
            return errors

        auth_slot = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider.id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()

        if not auth_slot:
            errors.append(f"No auth configured for {provider.name}. Go to LLM Settings.")
        elif auth_slot.last_test_result and auth_slot.last_test_result != "ok":
            errors.append(f"Auth for {provider.name} failed: {auth_slot.last_test_result}")

        return errors
