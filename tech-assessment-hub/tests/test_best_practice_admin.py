"""Tests for BestPractice admin API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from src.models import BestPractice, BestPracticeCategory


@pytest.fixture
def seeded_bps(db_session: Session):
    """Create a few best practices for testing."""
    bps = []
    for i, (code, cat) in enumerate([
        ("TEST_SRV_001", BestPracticeCategory.technical_server),
        ("TEST_CLI_001", BestPracticeCategory.technical_client),
        ("TEST_ARCH_001", BestPracticeCategory.architecture),
    ]):
        bp = BestPractice(
            code=code,
            title=f"Test BP {i}",
            category=cat,
            severity="medium",
            description=f"Description {i}",
            detection_hint=f"Hint {i}",
            recommendation=f"Rec {i}",
            is_active=True,
        )
        db_session.add(bp)
        bps.append(bp)
    db_session.commit()
    for bp in bps:
        db_session.refresh(bp)
    return bps


def test_api_list_best_practices(client: TestClient, seeded_bps):
    resp = client.get("/api/best-practices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["best_practices"]) == 3


def test_api_list_best_practices_filter_category(client: TestClient, seeded_bps):
    resp = client.get("/api/best-practices?category=technical_server")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["best_practices"]) == 1
    assert data["best_practices"][0]["code"] == "TEST_SRV_001"


def test_api_update_best_practice(client: TestClient, seeded_bps):
    bp_id = seeded_bps[0].id
    resp = client.put(f"/api/best-practices/{bp_id}", json={
        "title": "Updated Title",
        "severity": "critical",
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"
    assert resp.json()["severity"] == "critical"


def test_api_toggle_best_practice_active(client: TestClient, seeded_bps):
    bp_id = seeded_bps[0].id
    resp = client.put(f"/api/best-practices/{bp_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_create_best_practice(client: TestClient, db_session):
    resp = client.post("/api/best-practices", json={
        "code": "NEW_001",
        "title": "Brand New Check",
        "category": "process",
        "severity": "high",
        "description": "A new check",
    })
    assert resp.status_code == 201
    assert resp.json()["code"] == "NEW_001"


def test_admin_best_practices_page_route(client: TestClient):
    resp = client.get("/admin/best-practices")
    assert resp.status_code == 200
    assert "Best Practices" in resp.text
