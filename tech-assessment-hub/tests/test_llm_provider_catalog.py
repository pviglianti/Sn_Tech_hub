"""Tests for LLM provider catalog — seed defaults and CRUD."""

from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMModel
from src.services.llm.provider_catalog import (
    seed_default_catalog,
    get_provider_models,
    get_providers_with_models,
    DEFAULT_CATALOG,
)


def test_seed_default_catalog(db_session: Session):
    """Seeding creates all 3 providers and their models."""
    seed_default_catalog(db_session)

    providers = db_session.exec(select(LLMProvider)).all()
    assert len(providers) == 3

    kinds = {p.provider_kind for p in providers}
    assert kinds == {"anthropic", "google", "openai"}

    models = db_session.exec(select(LLMModel)).all()
    expected_model_count = sum(
        len(p["models"]) for p in DEFAULT_CATALOG.values()
    )
    assert len(models) == expected_model_count


def test_seed_is_idempotent(db_session: Session):
    """Calling seed twice does not duplicate rows."""
    seed_default_catalog(db_session)
    seed_default_catalog(db_session)

    providers = db_session.exec(select(LLMProvider)).all()
    assert len(providers) == 3


def test_get_providers_with_models(db_session: Session):
    seed_default_catalog(db_session)
    result = get_providers_with_models(db_session)

    assert len(result) == 3
    for entry in result:
        assert "provider" in entry
        assert "models" in entry
        assert len(entry["models"]) > 0


def test_default_model_per_provider(db_session: Session):
    """Each provider has exactly one default model."""
    seed_default_catalog(db_session)
    providers = db_session.exec(select(LLMProvider)).all()
    for provider in providers:
        defaults = db_session.exec(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.is_default == True,  # noqa: E712
            )
        ).all()
        assert len(defaults) == 1, f"{provider.provider_kind} should have 1 default model"


def test_seed_updates_existing_openai_catalog_rows(db_session: Session):
    """Reseeding refreshes existing OpenAI builtin options for the settings picker."""
    provider = LLMProvider(
        provider_kind="openai",
        name="OpenAI Old",
        cli_command="old-codex",
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(LLMModel(
        provider_id=provider.id,
        model_name="gpt-4.1",
        display_name="GPT-4.1",
        is_default=True,
        source="builtin",
    ))
    db_session.commit()

    seed_default_catalog(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "openai")
    ).first()
    assert provider is not None
    assert provider.name == "OpenAI (GPT/Codex)"
    assert provider.cli_command == "codex"

    visible_names = [m.model_name for m in get_provider_models(db_session, provider)]
    assert visible_names == [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.2",
        "gpt-5.1-codex-max",
        "gpt-5.1-codex-mini",
    ]

    stale_builtin = db_session.exec(
        select(LLMModel).where(
            LLMModel.provider_id == provider.id,
            LLMModel.model_name == "gpt-4.1",
        )
    ).first()
    assert stale_builtin is not None
    assert stale_builtin.is_default is False
