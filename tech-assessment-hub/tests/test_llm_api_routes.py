"""Tests for /api/llm/* routes."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from src.services.llm.provider_catalog import seed_default_catalog


def test_get_providers(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)
    resp = client.get("/api/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    kinds = {p["provider"]["provider_kind"] for p in data}
    assert kinds == {"anthropic", "google", "openai"}


def test_get_provider_models(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)
    providers = client.get("/api/llm/providers").json()
    anthropic = next(p for p in providers if p["provider"]["provider_kind"] == "anthropic")
    pid = anthropic["provider"]["id"]

    resp = client.get(f"/api/llm/providers/{pid}/models")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) >= 3
    names = {m["model_name"] for m in models}
    assert "claude-sonnet-4-6" in names


def test_detect_clis(client: TestClient):
    with patch("src.services.llm.auth_manager.shutil.which", return_value=None):
        resp = client.get("/api/llm/detect-clis")
    assert resp.status_code == 200
    data = resp.json()
    assert "anthropic" in data
    assert data["anthropic"]["installed"] is False


def test_create_api_key_slot(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)
    providers = client.get("/api/llm/providers").json()
    anthropic = next(p for p in providers if p["provider"]["provider_kind"] == "anthropic")
    pid = anthropic["provider"]["id"]

    resp = client.post("/api/llm/auth-slots", json={
        "provider_id": pid,
        "slot_kind": "api_key",
        "api_key": "sk-ant-test-abcd5678",
    })
    assert resp.status_code == 200
    slot = resp.json()
    assert slot["slot_kind"] == "api_key"
    assert slot["api_key_hint"] == "5678"
    assert "sk-ant" not in json.dumps(slot)


def test_get_and_update_config(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)

    resp = client.get("/api/llm/config")
    assert resp.status_code == 200

    providers = client.get("/api/llm/providers").json()
    anthropic = next(p for p in providers if p["provider"]["provider_kind"] == "anthropic")

    resp = client.put("/api/llm/config", json={
        "ai.default_provider_id": str(anthropic["provider"]["id"]),
        "ai.default_effort_level": "high",
    })
    assert resp.status_code == 200

    resp = client.get("/api/llm/config")
    config = resp.json()
    assert config.get("ai.default_effort_level") == "high"
