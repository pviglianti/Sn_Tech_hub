from sqlmodel import select

from src.models import Fact, Instance
from src.services.encryption import encrypt_password


def _make_instance(session):
    inst = Instance(
        name="usage-inst",
        url="https://usage.service-now.com",
        username="admin",
        password_encrypted=encrypt_password("secret"),
    )
    session.add(inst)
    session.commit()
    session.refresh(inst)
    return inst


def test_get_usage_count_queries_once_then_uses_cache(db_session, monkeypatch):
    from src.mcp.tools.core.get_usage_count import handle
    from src.services.sn_client import ServiceNowClient

    inst = _make_instance(db_session)
    calls = []

    def _fake_get_record_count(self, table, query=""):
        calls.append((table, query))
        return 17

    monkeypatch.setattr(ServiceNowClient, "get_record_count", _fake_get_record_count)

    first = handle(
        {
            "instance_id": inst.id,
            "table": "incident",
            "query": "active=true",
            "description": "Incident activity check",
        },
        db_session,
    )
    assert first["success"] is True
    assert first["count"] == 17
    assert first["cached"] is False
    assert "monthsAgo(" in first["query"]
    assert len(calls) == 1

    second = handle(
        {
            "instance_id": inst.id,
            "table": "incident",
            "query": "active=true",
            "description": "Incident activity check",
        },
        db_session,
    )
    assert second["success"] is True
    assert second["count"] == 17
    assert second["cached"] is True
    assert len(calls) == 1

    fact_rows = db_session.exec(select(Fact)).all()
    assert len(fact_rows) == 1
    assert fact_rows[0].topic_type == "usage_count"


def test_get_usage_count_use_cache_false_forces_refresh(db_session, monkeypatch):
    from src.mcp.tools.core.get_usage_count import handle
    from src.services.sn_client import ServiceNowClient

    inst = _make_instance(db_session)
    calls = {"count": 0}

    def _fake_get_record_count(self, table, query=""):
        calls["count"] += 1
        return 9

    monkeypatch.setattr(ServiceNowClient, "get_record_count", _fake_get_record_count)

    first = handle(
        {
            "instance_id": inst.id,
            "table": "task",
            "query": "active=true",
            "use_cache": True,
        },
        db_session,
    )
    assert first["success"] is True

    second = handle(
        {
            "instance_id": inst.id,
            "table": "task",
            "query": "active=true",
            "use_cache": False,
        },
        db_session,
    )
    assert second["success"] is True
    assert second["cached"] is False
    assert calls["count"] == 2
