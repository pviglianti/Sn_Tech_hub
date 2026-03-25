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


def test_api_best_practice_field_schema_includes_all_model_columns(client: TestClient):
    resp = client.get("/api/best-practices/field-schema")
    assert resp.status_code == 200
    data = resp.json()

    field_names = {field["local_column"] for field in data["fields"]}
    model_columns = {column.name for column in BestPractice.__table__.columns}

    assert field_names == model_columns
    assert "source_url" in field_names
    assert "created_at" in field_names
    assert "updated_at" in field_names


def test_api_best_practice_records_returns_full_row_shape(
    client: TestClient,
    seeded_bps,
    db_session: Session,
):
    seeded_bps[0].source_url = "https://example.com/best-practice"
    db_session.add(seeded_bps[0])
    db_session.commit()

    resp = client.get("/api/best-practices/records?offset=0&limit=50")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 3
    assert data["count"] == 3
    row = data["rows"][0]
    assert "id" in row
    assert "source_url" in row
    assert "created_at" in row
    assert "updated_at" in row


def test_api_best_practice_records_supports_standard_filters(
    client: TestClient,
    seeded_bps,
    db_session: Session,
):
    seeded_bps[1].is_active = False
    db_session.add(seeded_bps[1])
    db_session.commit()

    resp = client.get("/api/best-practices/records?category=technical_server&is_active=true")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 1
    assert data["rows"][0]["code"] == "TEST_SRV_001"


def test_api_best_practice_record_returns_field_rows(client: TestClient, seeded_bps):
    bp_id = seeded_bps[0].id
    resp = client.get(f"/api/best-practices/{bp_id}/record")
    assert resp.status_code == 200
    data = resp.json()

    fields = {row["field"] for row in data["field_rows"]}
    assert "source_url" in fields
    assert "created_at" in fields
    assert "updated_at" in fields


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


def test_admin_best_practice_record_page_route(client: TestClient, seeded_bps):
    resp = client.get(f"/admin/best-practices/{seeded_bps[0].id}")
    assert resp.status_code == 200
    assert seeded_bps[0].code in resp.text
    assert seeded_bps[0].title in resp.text
