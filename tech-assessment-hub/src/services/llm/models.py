"""SQLModel tables for LLM providers, models, and auth slots."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class LLMProvider(SQLModel, table=True):
    """An LLM provider (Anthropic, Google, OpenAI)."""

    __tablename__ = "llm_provider"
    __table_args__ = (UniqueConstraint("provider_kind"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_kind: str = Field(index=True)  # anthropic | google | openai
    name: str  # Display name
    cli_command: Optional[str] = None  # claude | gemini | codex
    api_base_url: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LLMModel(SQLModel, table=True):
    """A model offered by an LLM provider."""

    __tablename__ = "llm_model"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="llm_provider.id", index=True)
    model_name: str  # API identifier, e.g. claude-opus-4-6
    display_name: Optional[str] = None
    context_window: Optional[int] = None
    supports_effort: bool = False
    is_default: bool = False
    source: str = "builtin"  # builtin | fetched | manual
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LLMAuthSlot(SQLModel, table=True):
    """Auth credential for an LLM provider — CLI subscription or API key."""

    __tablename__ = "llm_auth_slot"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="llm_provider.id", index=True)
    slot_kind: str  # cli | api_key
    api_key: Optional[str] = None  # Plaintext (local-only deployment)
    api_key_hint: Optional[str] = None  # Last 4 chars for display
    env_var_name: Optional[str] = None  # Read key from env var instead
    is_active: bool = True
    last_tested_at: Optional[str] = None  # ISO timestamp
    last_test_result: Optional[str] = None  # "ok" or "error: ..."
    created_at: datetime = Field(default_factory=datetime.utcnow)
