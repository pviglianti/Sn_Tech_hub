"""Tests for LLM AuthManager — CLI detection, slot creation, testing."""

import subprocess
from unittest.mock import patch
from datetime import datetime

from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMAuthSlot, LLMModel
from src.services.llm.provider_catalog import seed_default_catalog
from src.services.llm.auth_manager import AuthManager


def _seed(db_session: Session) -> None:
    seed_default_catalog(db_session)


def test_detect_clis_all_missing(db_session: Session):
    mgr = AuthManager(db_session)
    with patch("src.services.llm.auth_manager.shutil.which", return_value=None):
        result = mgr.detect_clis()
    for kind in ("anthropic", "google", "openai"):
        assert result[kind]["installed"] is False


def test_detect_clis_claude_found(db_session: Session):
    mgr = AuthManager(db_session)

    def _which(name):
        return "/usr/bin/claude" if name == "claude" else None

    fake_version = subprocess.CompletedProcess(args=[], returncode=0, stdout="1.2.3\n", stderr="")
    with patch("src.services.llm.auth_manager.shutil.which", side_effect=_which), \
         patch("subprocess.run", return_value=fake_version):
        result = mgr.detect_clis()
    assert result["anthropic"]["installed"] is True
    assert result["anthropic"]["version"] == "1.2.3"


def test_store_api_key(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "anthropic")
    ).one()

    slot = mgr.store_api_key(provider.id, "sk-ant-test-abcd1234")
    assert slot.slot_kind == "api_key"
    assert slot.api_key == "sk-ant-test-abcd1234"
    assert slot.api_key_hint == "1234"
    assert slot.is_active is True


def test_create_cli_slot(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "google")
    ).one()

    slot = mgr.create_cli_slot(provider.id)
    assert slot.slot_kind == "cli"
    assert slot.api_key is None


def test_get_active_auth(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "openai")
    ).one()

    assert mgr.get_active_auth(provider.id) is None

    mgr.store_api_key(provider.id, "sk-test-9999")
    slot = mgr.get_active_auth(provider.id)
    assert slot is not None
    assert slot.api_key_hint == "9999"


def test_store_api_key_deactivates_previous(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "anthropic")
    ).one()

    slot1 = mgr.store_api_key(provider.id, "sk-ant-first-0001")
    slot2 = mgr.store_api_key(provider.id, "sk-ant-second-0002")

    db_session.refresh(slot1)
    assert slot1.is_active is False
    assert slot2.is_active is True


def test_refresh_provider_models_stores_fetched_rows(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "openai")
    ).one()
    mgr.store_api_key(provider.id, "sk-test-refresh-1234")

    with patch(
        "src.services.llm.auth_manager.CodexDispatcher.fetch_models",
        return_value=[
            {
                "name": "gpt-refresh-test",
                "display": "GPT Refresh Test",
                "effort": True,
            }
        ],
    ):
        models = mgr.refresh_provider_models(provider.id)

    fetched = db_session.exec(
        select(LLMModel).where(
            LLMModel.provider_id == provider.id,
            LLMModel.model_name == "gpt-refresh-test",
        )
    ).first()

    assert fetched is not None
    assert fetched.source == "fetched"
    assert any(model["model_name"] == "gpt-refresh-test" for model in models)
