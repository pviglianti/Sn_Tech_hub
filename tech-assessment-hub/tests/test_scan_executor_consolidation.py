"""Consolidation tests for scan_executor.py.

Verifies that:
  1. The old _apply_since_filter() and _iterate_batches() module-level functions have been
     deleted from scan_executor.
  2. Both the metadata_index and update_xml scan paths call client._iterate_batches().
  3. The since filter is applied via client._watermark_filter(since, inclusive=True).
"""

from __future__ import annotations

import importlib
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.models import (
    Assessment,
    AssessmentType,
    Instance,
    Scan,
    ScanStatus,
    ScanType,
)
from src.services.sn_client import ServiceNowClient


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(mem_engine):
    s = Session(mem_engine)
    yield s
    s.rollback()
    s.close()


def _make_instance(session: Session) -> Instance:
    inst = Instance(
        name="test",
        url="https://example.service-now.com",
        username="admin",
        password_encrypted="enc",
    )
    session.add(inst)
    session.commit()
    session.refresh(inst)
    return inst


def _make_assessment(session: Session, instance: Instance) -> Assessment:
    a = Assessment(
        instance_id=instance.id,
        number="ASMT0001",
        name="Test",
        assessment_type=AssessmentType.global_app,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _make_scan(session: Session, assessment: Assessment, scan_type: ScanType) -> Scan:
    s = Scan(
        assessment_id=assessment.id,
        name="test scan",
        scan_type=scan_type,
        status=ScanStatus.pending,
        encoded_query="active=true",
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _make_client() -> ServiceNowClient:
    return ServiceNowClient("https://example.service-now.com", "admin", "password")


# ---------------------------------------------------------------------------
# Test 1: _apply_since_filter is NOT importable from scan_executor
# ---------------------------------------------------------------------------

def test_apply_since_filter_not_in_module():
    """_apply_since_filter() must have been deleted from scan_executor."""
    import src.services.scan_executor as mod
    assert not hasattr(mod, "_apply_since_filter"), (
        "_apply_since_filter should have been removed from scan_executor; "
        "call sites now use client._watermark_filter() directly."
    )


# ---------------------------------------------------------------------------
# Test 2: _iterate_batches is NOT importable from scan_executor
# ---------------------------------------------------------------------------

def test_iterate_batches_not_in_module():
    """The module-level _iterate_batches() must have been deleted from scan_executor."""
    import src.services.scan_executor as mod
    assert not hasattr(mod, "_iterate_batches"), (
        "_iterate_batches should have been removed from scan_executor; "
        "call sites now use client._iterate_batches() directly."
    )


# ---------------------------------------------------------------------------
# Test 3: metadata_index scan uses client._iterate_batches()
# ---------------------------------------------------------------------------

def test_metadata_scan_uses_client_iterate_batches(session):
    """execute_scan (metadata_index path) must call client._iterate_batches()."""
    from src.services.scan_executor import execute_scan

    instance = _make_instance(session)
    assessment = _make_assessment(session, instance)
    scan = _make_scan(session, assessment, ScanType.metadata_index)
    client = _make_client()

    captured_calls: list[dict] = []

    def fake_iterate_batches(**kwargs):
        captured_calls.append(dict(kwargs))
        return iter([])  # empty — no records to process

    with patch.object(client, "_iterate_batches", side_effect=fake_iterate_batches), \
         patch("src.services.scan_executor.get_scan_rules", return_value={}), \
         patch("src.services.scan_executor._is_scan_cancel_requested", return_value=False):
        execute_scan(
            session=session,
            scan=scan,
            client=client,
            instance_id=instance.id,
        )

    assert len(captured_calls) >= 1, "client._iterate_batches() was never called for metadata scan"
    first_call = captured_calls[0]
    assert first_call.get("table") == "sys_metadata"


# ---------------------------------------------------------------------------
# Test 4: update_xml scan uses client._iterate_batches()
# ---------------------------------------------------------------------------

def test_update_xml_scan_uses_client_iterate_batches(session):
    """execute_scan (update_xml path) must call client._iterate_batches()."""
    from src.services.scan_executor import execute_scan

    instance = _make_instance(session)
    assessment = _make_assessment(session, instance)
    scan = _make_scan(session, assessment, ScanType.update_xml)
    client = _make_client()

    captured_calls: list[dict] = []

    def fake_iterate_batches(**kwargs):
        captured_calls.append(dict(kwargs))
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=fake_iterate_batches), \
         patch("src.services.scan_executor.get_scan_rules", return_value={}), \
         patch("src.services.scan_executor._is_scan_cancel_requested", return_value=False):
        execute_scan(
            session=session,
            scan=scan,
            client=client,
            instance_id=instance.id,
        )

    assert len(captured_calls) >= 1, "client._iterate_batches() was never called for update_xml scan"
    first_call = captured_calls[0]
    assert first_call.get("table") == "sys_update_xml"


# ---------------------------------------------------------------------------
# Test 5: since filter is built via client._watermark_filter(inclusive=True)
# ---------------------------------------------------------------------------

def test_since_filter_uses_watermark_filter(session):
    """When `since` is provided, _watermark_filter(since, inclusive=True) is called."""
    from src.services.scan_executor import execute_scan

    instance = _make_instance(session)
    assessment = _make_assessment(session, instance)
    scan = _make_scan(session, assessment, ScanType.metadata_index)
    client = _make_client()

    since = datetime(2026, 1, 15, 0, 0, 0)
    watermark_calls: list[dict] = []
    real_watermark = client._watermark_filter

    def tracking_watermark(since_arg, inclusive=True):
        watermark_calls.append({"since": since_arg, "inclusive": inclusive})
        return real_watermark(since_arg, inclusive=inclusive)

    with patch.object(client, "_watermark_filter", side_effect=tracking_watermark), \
         patch.object(client, "_iterate_batches", return_value=iter([])), \
         patch("src.services.scan_executor.get_scan_rules", return_value={}), \
         patch("src.services.scan_executor._is_scan_cancel_requested", return_value=False):
        execute_scan(
            session=session,
            scan=scan,
            client=client,
            instance_id=instance.id,
            since=since,
        )

    assert len(watermark_calls) >= 1, "_watermark_filter() was never called"
    for call in watermark_calls:
        assert call["inclusive"] is True, (
            "_watermark_filter must be called with inclusive=True (>= semantics)"
        )
        assert call["since"] == since


# ---------------------------------------------------------------------------
# Test 6: since filter is embedded in the query passed to _iterate_batches
# ---------------------------------------------------------------------------

def test_since_filter_embedded_in_iterate_batches_query(session):
    """The watermark string is concatenated into the query sent to _iterate_batches."""
    from src.services.scan_executor import execute_scan

    instance = _make_instance(session)
    assessment = _make_assessment(session, instance)
    scan = _make_scan(session, assessment, ScanType.update_xml)
    client = _make_client()

    since = datetime(2026, 3, 1, 12, 0, 0)
    expected_wm = "sys_updated_on>=2026-03-01 12:00:00"

    captured_queries: list[str] = []

    def fake_iterate_batches(**kwargs):
        captured_queries.append(kwargs.get("query", ""))
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=fake_iterate_batches), \
         patch("src.services.scan_executor.get_scan_rules", return_value={}), \
         patch("src.services.scan_executor._is_scan_cancel_requested", return_value=False):
        execute_scan(
            session=session,
            scan=scan,
            client=client,
            instance_id=instance.id,
            since=since,
        )

    assert captured_queries, "_iterate_batches was not called"
    assert expected_wm in captured_queries[0], (
        f"Expected watermark '{expected_wm}' in query '{captured_queries[0]}'"
    )
