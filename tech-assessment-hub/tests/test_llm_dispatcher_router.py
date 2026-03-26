"""Tests for DispatcherRouter — provider/model/effort resolution and preflight checks."""

from sqlmodel import Session, select

from src.models import AppConfig
from src.services.llm.models import LLMProvider, LLMModel, LLMAuthSlot
from src.services.llm.provider_catalog import seed_default_catalog
from src.services.llm.dispatcher_router import DispatcherRouter


def _setup_authenticated_provider(db_session: Session, kind: str = "anthropic") -> int:
    """Seed catalog, create CLI auth slot, mark as ok, set global defaults."""
    seed_default_catalog(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == kind)
    ).one()
    slot = LLMAuthSlot(
        provider_id=provider.id, slot_kind="cli", is_active=True,
        last_test_result="ok",
    )
    db_session.add(slot)
    db_session.commit()

    default_model = db_session.exec(
        select(LLMModel).where(
            LLMModel.provider_id == provider.id,
            LLMModel.is_default == True,  # noqa: E712
        )
    ).one()

    for key, val in [
        ("ai.default_provider_id", str(provider.id)),
        ("ai.default_model_id", str(default_model.id)),
        ("ai.default_effort_level", "medium"),
    ]:
        db_session.add(AppConfig(key=key, value=val))
    db_session.commit()

    return provider.id


def test_resolve_global_defaults(db_session: Session):
    _setup_authenticated_provider(db_session, "anthropic")
    router = DispatcherRouter(db_session)
    config = router.resolve("ai_analysis")

    assert config.provider_kind == "anthropic"
    assert config.model_name == "claude-sonnet-4-6"
    assert config.effort_level == "medium"


def test_resolve_per_stage_override(db_session: Session):
    _setup_authenticated_provider(db_session, "anthropic")

    google = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "google")
    ).one()
    slot = LLMAuthSlot(
        provider_id=google.id, slot_kind="cli", is_active=True,
        last_test_result="ok",
    )
    db_session.add(slot)

    google_model = db_session.exec(
        select(LLMModel).where(
            LLMModel.provider_id == google.id,
            LLMModel.is_default == True,  # noqa: E712
        )
    ).one()

    db_session.add(AppConfig(key="ai.stage.grouping.provider_id", value=str(google.id)))
    db_session.add(AppConfig(key="ai.stage.grouping.model_id", value=str(google_model.id)))
    db_session.add(AppConfig(key="ai.stage.grouping.effort_level", value="low"))
    db_session.commit()

    router = DispatcherRouter(db_session)

    config_analysis = router.resolve("ai_analysis")
    assert config_analysis.provider_kind == "anthropic"

    config_grouping = router.resolve("grouping")
    assert config_grouping.provider_kind == "google"
    assert config_grouping.effort_level == "low"


def test_preflight_check_no_provider(db_session: Session):
    seed_default_catalog(db_session)
    router = DispatcherRouter(db_session)
    errors = router.preflight_check("ai_analysis")
    assert len(errors) > 0
    assert any("no llm provider" in e.lower() for e in errors)


def test_preflight_check_ok(db_session: Session):
    _setup_authenticated_provider(db_session, "anthropic")
    router = DispatcherRouter(db_session)
    errors = router.preflight_check("ai_analysis")
    assert errors == []
