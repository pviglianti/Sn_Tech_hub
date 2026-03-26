"""Tests for LLM provider catalog — seed defaults and CRUD."""

from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMModel
from src.services.llm.provider_catalog import (
    seed_default_catalog,
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
