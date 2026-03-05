"""Regression tests for connection-triggered pull upsert behavior.

These cover the pull types kicked off after a successful instance
connection test:
- app_file_types
- sys_db_object
- version_history (proactive pull path)
"""

from datetime import datetime

from sqlmodel import select

from src.models import DataPullType, InstanceAppFileType, TableDefinition, VersionHistory
from src.services import data_pull_executor as dpe


class _FakeConnectionPullClient:
    """Minimal fake SN client for connection-triggered pull tests."""

    def __init__(self) -> None:
        self._app_file_label = "Business Rule"
        self._table_label = "Incident"
        self._vh_state = "current"

    def pull_app_file_types(self, since=None, **kwargs):
        yield [
            {
                "sys_id": "aft-1",
                "name": "Business Rule",
                "label": self._app_file_label,
                "sys_source_table": {"value": "dbo-1", "display_value": "incident"},
                "sys_parent_table": {"value": "dbo-0", "display_value": "task"},
                "sys_updated_on": "2026-03-04 10:00:00",
            }
        ]

    def pull_sys_db_object(self, since=None, **kwargs):
        yield [
            {
                "sys_id": "dbo-1",
                "name": "incident",
                "label": self._table_label,
                "super_class": {"value": "dbo-0"},
                "sys_updated_on": "2026-03-04 10:00:00",
            }
        ]

    def pull_version_history(self, since=None, state_filter=None, **kwargs):
        yield [
            {
                "sys_id": "vh-1",
                "name": "incident.business_rule.test",
                "state": self._vh_state,
                "source_table": {"value": "sys_update_set"},
                "source": {"value": "src-1"},
                "source_display": {"display_value": "Test Source"},
                "sys_customer_update": {"value": "cux-1"},
                "sys_recorded_at": "2026-03-04 10:00:00",
                "sys_updated_on": "2026-03-04 10:00:00",
            }
        ]


def test_connection_triggered_reference_pulls_upsert_without_duplicates(
    db_session,
    sample_instance,
    monkeypatch,
):
    """Repeated app-file/table pulls should update existing rows, not duplicate."""
    monkeypatch.setattr(dpe, "_estimate_expected_total", lambda *args, **kwargs: None)
    client = _FakeConnectionPullClient()

    dpe.execute_data_pull(
        session=db_session,
        instance=sample_instance,
        client=client,
        data_type=DataPullType.app_file_types,
        mode="full",
    )
    dpe.execute_data_pull(
        session=db_session,
        instance=sample_instance,
        client=client,
        data_type=DataPullType.sys_db_object,
        mode="full",
    )

    initial_app_rows = db_session.exec(
        select(InstanceAppFileType).where(InstanceAppFileType.instance_id == sample_instance.id)
    ).all()
    initial_table_rows = db_session.exec(
        select(TableDefinition).where(TableDefinition.instance_id == sample_instance.id)
    ).all()
    assert len(initial_app_rows) == 1
    assert len(initial_table_rows) == 1
    assert initial_app_rows[0].label == "Business Rule"
    assert initial_table_rows[0].label == "Incident"

    # Re-run with changed source data; should update, not insert a second row.
    client._app_file_label = "Business Rule (Updated)"
    client._table_label = "Incident (Updated)"

    dpe.execute_data_pull(
        session=db_session,
        instance=sample_instance,
        client=client,
        data_type=DataPullType.app_file_types,
        mode="full",
    )
    dpe.execute_data_pull(
        session=db_session,
        instance=sample_instance,
        client=client,
        data_type=DataPullType.sys_db_object,
        mode="full",
    )

    final_app_rows = db_session.exec(
        select(InstanceAppFileType).where(InstanceAppFileType.instance_id == sample_instance.id)
    ).all()
    final_table_rows = db_session.exec(
        select(TableDefinition).where(TableDefinition.instance_id == sample_instance.id)
    ).all()
    assert len(final_app_rows) == 1
    assert len(final_table_rows) == 1
    assert final_app_rows[0].label == "Business Rule (Updated)"
    assert final_table_rows[0].label == "Incident (Updated)"


def test_proactive_vh_pull_path_upserts_without_duplicates(
    db_session,
    sample_instance,
    monkeypatch,
):
    """Repeated VH pulls should upsert by (instance_id, sn_sys_id)."""
    monkeypatch.setattr(dpe, "_estimate_expected_total", lambda *args, **kwargs: None)
    client = _FakeConnectionPullClient()

    # Simulate the proactive flow shape: current-only first, then follow-up.
    dpe.execute_data_pull(
        session=db_session,
        instance=sample_instance,
        client=client,
        data_type=DataPullType.version_history,
        mode="full",
        version_state_filter="current",
    )

    first_rows = db_session.exec(
        select(VersionHistory).where(VersionHistory.instance_id == sample_instance.id)
    ).all()
    assert len(first_rows) == 1
    assert first_rows[0].state == "current"

    # Re-run with changed state; row should be updated, not duplicated.
    client._vh_state = "previous"
    dpe.execute_data_pull(
        session=db_session,
        instance=sample_instance,
        client=client,
        data_type=DataPullType.version_history,
        mode="full",
    )

    final_rows = db_session.exec(
        select(VersionHistory).where(VersionHistory.instance_id == sample_instance.id)
    ).all()
    assert len(final_rows) == 1
    assert final_rows[0].state == "previous"
    assert isinstance(final_rows[0].last_refreshed_at, datetime)
