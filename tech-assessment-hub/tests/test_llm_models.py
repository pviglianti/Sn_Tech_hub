"""Tests for LLM provider, model, and auth slot SQLModel tables."""

import pytest
from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMModel, LLMAuthSlot


def test_create_provider(db_session: Session):
    provider = LLMProvider(
        provider_kind="anthropic",
        name="Anthropic (Claude)",
        cli_command="claude",
        api_base_url="https://api.anthropic.com/v1",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    assert provider.id is not None
    assert provider.provider_kind == "anthropic"
    assert provider.is_active is True


def test_create_model(db_session: Session):
    provider = LLMProvider(
        provider_kind="anthropic",
        name="Anthropic (Claude)",
        cli_command="claude",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    model = LLMModel(
        provider_id=provider.id,
        model_name="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        context_window=1_000_000,
        supports_effort=True,
        is_default=True,
        source="builtin",
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)

    assert model.id is not None
    assert model.provider_id == provider.id
    assert model.supports_effort is True


def test_create_auth_slot_cli(db_session: Session):
    provider = LLMProvider(
        provider_kind="anthropic",
        name="Anthropic (Claude)",
        cli_command="claude",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    slot = LLMAuthSlot(
        provider_id=provider.id,
        slot_kind="cli",
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    assert slot.id is not None
    assert slot.slot_kind == "cli"
    assert slot.api_key is None


def test_create_auth_slot_api_key(db_session: Session):
    provider = LLMProvider(
        provider_kind="openai",
        name="OpenAI (GPT/Codex)",
        cli_command="codex",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    slot = LLMAuthSlot(
        provider_id=provider.id,
        slot_kind="api_key",
        api_key="sk-test-12345678",
        api_key_hint="5678",
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    assert slot.api_key == "sk-test-12345678"
    assert slot.api_key_hint == "5678"


def test_provider_unique_kind(db_session: Session):
    """Only one provider per provider_kind."""
    p1 = LLMProvider(provider_kind="anthropic", name="A", cli_command="claude")
    db_session.add(p1)
    db_session.commit()

    p2 = LLMProvider(provider_kind="anthropic", name="B", cli_command="claude")
    db_session.add(p2)
    with pytest.raises(Exception):  # IntegrityError
        db_session.commit()
