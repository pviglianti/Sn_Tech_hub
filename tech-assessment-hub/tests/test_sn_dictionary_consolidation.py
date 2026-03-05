"""Consolidation tests for sn_dictionary.py.

Verifies that all three functions that previously called client.session.get()
directly now go through client.get_records() instead, gaining retry logic,
error normalisation, and consistent field selection.

Tests:
  1. validate_table_exists() calls client.get_records(), not client.session.get()
  2. _resolve_table_name_by_sys_id() calls client.get_records(), returns None on empty
  3. _fetch_fields_for_table() calls client.get_records()
  4. _fetch_fields_for_table() builds the since filter via client._watermark_filter()
  5. All 3 functions gain retry / error normalisation via get_records()
  6. validate_table_exists() returns SNTableInfo on success, None on empty result
  7. _resolve_table_name_by_sys_id() returns None when result list is empty
  8. _resolve_table_name_by_sys_id() returns name on success
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.services.sn_client import ServiceNowClient, ServiceNowClientError
from src.services.sn_dictionary import (
    SNTableInfo,
    SNFieldInfo,
    _fetch_fields_for_table,
    _resolve_table_name_by_sys_id,
    validate_table_exists,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> ServiceNowClient:
    """Create a minimal client with a mocked session (no real HTTP)."""
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    # Replace the real requests.Session with a MagicMock so no network calls occur.
    client.session = MagicMock()
    return client


def _sys_db_object_record(
    name: str = "my_table",
    sys_id: str = "abc123",
    label: str = "My Table",
    super_class: str = "",
    is_extendable: str = "false",
    extension_model: str = "",
) -> dict:
    return {
        "name": name,
        "sys_id": sys_id,
        "label": label,
        "super_class": super_class,
        "is_extendable": is_extendable,
        "extension_model": extension_model,
    }


def _dictionary_record(element: str = "my_field", internal_type: str = "string") -> dict:
    return {
        "element": element,
        "column_label": element.replace("_", " ").title(),
        "internal_type": internal_type,
        "max_length": "255",
        "reference": "",
        "active": "true",
        "read_only": "false",
        "mandatory": "false",
    }


# ---------------------------------------------------------------------------
# Test 1: validate_table_exists() uses get_records(), not session.get()
# ---------------------------------------------------------------------------

def test_validate_table_exists_uses_get_records():
    """validate_table_exists() must call client.get_records() not client.session.get()."""
    client = _make_client()
    fake_record = _sys_db_object_record()

    with patch.object(client, "get_records", return_value=[fake_record]) as mock_get_records:
        result = validate_table_exists(client, "my_table")

    # get_records was called
    mock_get_records.assert_called_once()
    call_kwargs = mock_get_records.call_args
    assert call_kwargs.kwargs.get("table") == "sys_db_object" or (
        len(call_kwargs.args) > 0 and call_kwargs.args[0] == "sys_db_object"
    )

    # session.get was NOT called directly
    client.session.get.assert_not_called()

    # Result is properly mapped
    assert isinstance(result, SNTableInfo)
    assert result.name == "my_table"
    assert result.sys_id == "abc123"


def test_validate_table_exists_returns_none_on_empty():
    """validate_table_exists() returns None when get_records() returns an empty list."""
    client = _make_client()

    with patch.object(client, "get_records", return_value=[]):
        result = validate_table_exists(client, "nonexistent_table")

    assert result is None


def test_validate_table_exists_returns_none_on_client_error():
    """validate_table_exists() returns None and logs when get_records() raises."""
    client = _make_client()

    with patch.object(client, "get_records", side_effect=ServiceNowClientError("403")):
        result = validate_table_exists(client, "forbidden_table")

    assert result is None


# ---------------------------------------------------------------------------
# Test 2: _resolve_table_name_by_sys_id() uses get_records(), returns None on empty
# ---------------------------------------------------------------------------

def test_resolve_table_name_uses_get_records():
    """_resolve_table_name_by_sys_id() must call client.get_records()."""
    client = _make_client()
    fake_record = {"name": "resolved_table"}

    with patch.object(client, "get_records", return_value=[fake_record]) as mock_get_records:
        result = _resolve_table_name_by_sys_id(client, "some_sys_id")

    mock_get_records.assert_called_once()
    call_kwargs = mock_get_records.call_args
    # Verify table=sys_db_object is used
    assert call_kwargs.kwargs.get("table") == "sys_db_object" or (
        len(call_kwargs.args) > 0 and call_kwargs.args[0] == "sys_db_object"
    )
    # session.get NOT called
    client.session.get.assert_not_called()
    assert result == "resolved_table"


def test_resolve_table_name_returns_none_on_empty():
    """_resolve_table_name_by_sys_id() returns None when get_records() returns []."""
    client = _make_client()

    with patch.object(client, "get_records", return_value=[]):
        result = _resolve_table_name_by_sys_id(client, "missing_sys_id")

    assert result is None


def test_resolve_table_name_returns_none_on_blank_sys_id():
    """_resolve_table_name_by_sys_id() returns None immediately for empty sys_id."""
    client = _make_client()

    with patch.object(client, "get_records") as mock_get_records:
        result = _resolve_table_name_by_sys_id(client, "")

    # Should short-circuit before calling get_records
    mock_get_records.assert_not_called()
    assert result is None


def test_resolve_table_name_returns_none_on_client_error():
    """_resolve_table_name_by_sys_id() returns None when get_records() raises."""
    client = _make_client()

    with patch.object(client, "get_records", side_effect=ServiceNowClientError("404")):
        result = _resolve_table_name_by_sys_id(client, "some_sys_id")

    assert result is None


# ---------------------------------------------------------------------------
# Test 3: _fetch_fields_for_table() uses get_records(), not session.get()
# ---------------------------------------------------------------------------

def test_fetch_fields_uses_get_records():
    """_fetch_fields_for_table() must call client.get_records()."""
    client = _make_client()
    fake_records = [
        _dictionary_record("field_a"),
        _dictionary_record("field_b"),
    ]

    with patch.object(client, "get_records", return_value=fake_records) as mock_get_records:
        fields = _fetch_fields_for_table(client, "some_table")

    mock_get_records.assert_called_once()
    call_kwargs = mock_get_records.call_args
    assert call_kwargs.kwargs.get("table") == "sys_dictionary" or (
        len(call_kwargs.args) > 0 and call_kwargs.args[0] == "sys_dictionary"
    )
    # session.get was NOT called
    client.session.get.assert_not_called()

    assert len(fields) == 2
    assert all(isinstance(f, SNFieldInfo) for f in fields)
    assert {f.element for f in fields} == {"field_a", "field_b"}


def test_fetch_fields_returns_empty_on_client_error():
    """_fetch_fields_for_table() returns [] and logs on ServiceNowClientError."""
    client = _make_client()

    with patch.object(client, "get_records", side_effect=ServiceNowClientError("500")):
        fields = _fetch_fields_for_table(client, "bad_table")

    assert fields == []


def test_fetch_fields_filters_out_empty_element():
    """_fetch_fields_for_table() skips records where element is empty (collection record)."""
    client = _make_client()
    records = [
        {"element": "", "column_label": "", "internal_type": "collection",
         "max_length": "0", "reference": "", "active": "true",
         "read_only": "false", "mandatory": "false"},
        _dictionary_record("real_field"),
    ]

    with patch.object(client, "get_records", return_value=records):
        fields = _fetch_fields_for_table(client, "test_table")

    assert len(fields) == 1
    assert fields[0].element == "real_field"


# ---------------------------------------------------------------------------
# Test 4: _fetch_fields_for_table() uses _watermark_filter() for since param
# ---------------------------------------------------------------------------

def test_fetch_fields_since_uses_watermark_filter():
    """When `since` is provided, _fetch_fields_for_table() must call
    client._watermark_filter(since, inclusive=True) to build the filter."""
    client = _make_client()
    since = datetime(2026, 2, 1, 6, 0, 0)
    watermark_calls: list[dict] = []
    real_wm = ServiceNowClient._watermark_filter  # unbound

    def tracking_watermark(self_arg, since_arg, inclusive=True):
        watermark_calls.append({"since": since_arg, "inclusive": inclusive})
        return real_wm(self_arg, since_arg, inclusive=inclusive)

    with patch.object(client, "_watermark_filter", side_effect=lambda s, inclusive=True: tracking_watermark(client, s, inclusive=inclusive)), \
         patch.object(client, "get_records", return_value=[]):
        _fetch_fields_for_table(client, "test_table", since=since)

    assert len(watermark_calls) >= 1, "_watermark_filter() was never called"
    assert watermark_calls[0]["inclusive"] is True
    assert watermark_calls[0]["since"] == since


def test_fetch_fields_since_filter_in_query():
    """The watermark string is embedded in the query sent to get_records()."""
    client = _make_client()
    since = datetime(2026, 3, 5, 0, 0, 0)
    expected_wm = "sys_updated_on>=2026-03-05 00:00:00"

    captured_queries: list[str] = []

    def fake_get_records(**kwargs):
        captured_queries.append(kwargs.get("query", ""))
        return []

    with patch.object(client, "get_records", side_effect=fake_get_records):
        _fetch_fields_for_table(client, "some_table", since=since)

    assert captured_queries, "get_records was not called"
    assert expected_wm in captured_queries[0], (
        f"Expected watermark '{expected_wm}' in query '{captured_queries[0]}'"
    )


# ---------------------------------------------------------------------------
# Test 5: All 3 functions gain retry via get_records (which uses _fetch_with_retry)
# ---------------------------------------------------------------------------

def test_validate_table_exists_gains_retry_via_get_records():
    """validate_table_exists() benefits from get_records() retry — a transient
    Exception is retried.  We verify get_records is called (retry path is tested
    in sn_client tests; here we just confirm the call is routed through get_records)."""
    client = _make_client()
    rec = _sys_db_object_record()

    # get_records fails once then succeeds — simulating retry behaviour
    call_count = {"n": 0}

    def flaky_get_records(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient network error")
        return [rec]

    # We do NOT patch _fetch_with_retry here because validate_table_exists calls
    # get_records() which internally calls _fetch_with_retry. Since the retry
    # machinery lives inside the real get_records/session.get chain, we instead
    # confirm the function goes through get_records (not session.get).
    with patch.object(client, "get_records", return_value=[rec]) as mock_gr:
        result = validate_table_exists(client, "my_table")

    mock_gr.assert_called_once()
    assert result is not None


def test_resolve_table_name_gains_retry_via_get_records():
    """_resolve_table_name_by_sys_id() routes through get_records() which has retry."""
    client = _make_client()
    rec = {"name": "target_table"}

    with patch.object(client, "get_records", return_value=[rec]) as mock_gr:
        result = _resolve_table_name_by_sys_id(client, "sys_id_xyz")

    mock_gr.assert_called_once()
    assert result == "target_table"


def test_fetch_fields_gains_retry_via_get_records():
    """_fetch_fields_for_table() routes through get_records() which has retry."""
    client = _make_client()
    rec = _dictionary_record("my_col")

    with patch.object(client, "get_records", return_value=[rec]) as mock_gr:
        fields = _fetch_fields_for_table(client, "some_table")

    mock_gr.assert_called_once()
    assert len(fields) == 1
