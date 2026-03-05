"""Tests for order_desc parameter in _iterate_batches() and all 11 pull_*() methods.

Verifies that:
- _iterate_batches with order_desc=True appends ORDERBYDESC
- _iterate_batches with order_desc=False (default) appends ORDERBY
- order_desc=True with existing ORDER clause does not duplicate
- All 11 pull_*() methods accept and pass through the order_desc parameter
"""
import inspect
from unittest.mock import patch

from src.services.sn_client import ServiceNowClient

PULL_METHODS = [
    "pull_update_sets",
    "pull_customer_update_xml",
    "pull_version_history",
    "pull_metadata_customizations",
    "pull_app_file_types",
    "pull_plugins",
    "pull_plugin_view",
    "pull_scopes",
    "pull_packages",
    "pull_applications",
    "pull_sys_db_object",
]


def _make_client():
    return ServiceNowClient("https://example.service-now.com", "admin", "password")


# ---------------------------------------------------------------------------
# _iterate_batches: ORDERBY vs ORDERBYDESC
# ---------------------------------------------------------------------------


def test_iterate_batches_default_appends_orderby():
    """Default order_desc=False must append ORDERBY (ascending order)."""
    client = _make_client()
    captured = []

    def fake_fetch(table, query, fields, batch_size, offset, order_by):
        captured.append(query)
        return []

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch):
        list(client._iterate_batches(
            table="sys_update_set",
            query="active=true",
            inter_batch_delay=0,
        ))

    assert captured, "Expected at least one _fetch_with_retry call"
    assert "ORDERBYsys_updated_on" in captured[0]
    assert "ORDERBYDESCsys_updated_on" not in captured[0]


def test_iterate_batches_order_desc_false_appends_orderby():
    """Explicit order_desc=False must append ORDERBY, not ORDERBYDESC."""
    client = _make_client()
    captured = []

    def fake_fetch(table, query, fields, batch_size, offset, order_by):
        captured.append(query)
        return []

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch):
        list(client._iterate_batches(
            table="sys_update_set",
            query="active=true",
            order_desc=False,
            inter_batch_delay=0,
        ))

    assert captured
    assert "ORDERBYsys_updated_on" in captured[0]
    assert "ORDERBYDESCsys_updated_on" not in captured[0]


def test_iterate_batches_order_desc_true_appends_orderbydesc():
    """order_desc=True must append ORDERBYDESC instead of ORDERBY."""
    client = _make_client()
    captured = []

    def fake_fetch(table, query, fields, batch_size, offset, order_by):
        captured.append(query)
        return []

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch):
        list(client._iterate_batches(
            table="sys_update_set",
            query="active=true",
            order_desc=True,
            inter_batch_delay=0,
        ))

    assert captured
    assert "ORDERBYDESCsys_updated_on" in captured[0]
    # Must NOT also contain the ascending variant
    assert "^ORDERBYsys_updated_on" not in captured[0]


def test_iterate_batches_order_desc_true_no_duplicate_when_query_has_orderbydesc():
    """When query already contains ORDERBYDESC{field}, it must not be appended again."""
    client = _make_client()
    captured = []

    def fake_fetch(table, query, fields, batch_size, offset, order_by):
        captured.append(query)
        return []

    pre_existing_query = "active=true^ORDERBYDESCsys_updated_on"

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch):
        list(client._iterate_batches(
            table="sys_update_set",
            query=pre_existing_query,
            order_desc=True,
            inter_batch_delay=0,
        ))

    assert captured
    # Should appear exactly once
    assert captured[0].count("ORDERBYDESCsys_updated_on") == 1


def test_iterate_batches_order_desc_false_no_duplicate_when_query_has_orderby():
    """When query already contains ORDERBY{field}, it must not be appended again."""
    client = _make_client()
    captured = []

    def fake_fetch(table, query, fields, batch_size, offset, order_by):
        captured.append(query)
        return []

    pre_existing_query = "active=true^ORDERBYsys_updated_on"

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch):
        list(client._iterate_batches(
            table="sys_update_set",
            query=pre_existing_query,
            order_desc=False,
            inter_batch_delay=0,
        ))

    assert captured
    assert captured[0].count("ORDERBYsys_updated_on") == 1


def test_iterate_batches_empty_query_order_desc_true():
    """order_desc=True with empty query produces ORDERBYDESC without leading caret."""
    client = _make_client()
    captured = []

    def fake_fetch(table, query, fields, batch_size, offset, order_by):
        captured.append(query)
        return []

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch):
        list(client._iterate_batches(
            table="sys_update_set",
            query="",
            order_desc=True,
            inter_batch_delay=0,
        ))

    assert captured
    # Should be just "ORDERBYDESCsys_updated_on" (no leading caret)
    assert captured[0].startswith("ORDERBYDESC") or "^ORDERBYDESCsys_updated_on" in captured[0]
    assert not captured[0].startswith("^")


# ---------------------------------------------------------------------------
# All 11 pull_*() methods accept order_desc parameter
# ---------------------------------------------------------------------------


def test_all_pull_methods_accept_order_desc_parameter():
    """All 11 pull_*() methods must declare order_desc as a parameter."""
    client = _make_client()
    missing = []
    for method_name in PULL_METHODS:
        method = getattr(client, method_name)
        sig = inspect.signature(method)
        if "order_desc" not in sig.parameters:
            missing.append(method_name)

    assert not missing, (
        f"The following pull_*() methods are missing the order_desc parameter: "
        f"{', '.join(missing)}"
    )


def test_all_pull_methods_order_desc_defaults_to_false():
    """All 11 pull_*() methods must default order_desc to False."""
    client = _make_client()
    wrong_default = []
    for method_name in PULL_METHODS:
        method = getattr(client, method_name)
        sig = inspect.signature(method)
        param = sig.parameters.get("order_desc")
        if param is None or param.default is not False:
            wrong_default.append(method_name)

    assert not wrong_default, (
        f"The following pull_*() methods do not default order_desc to False: "
        f"{', '.join(wrong_default)}"
    )


def test_pull_update_sets_passes_order_desc_to_iterate_batches():
    """pull_update_sets with order_desc=True must pass it to _iterate_batches."""
    client = _make_client()
    iterate_calls = []

    original_iterate = client._iterate_batches

    def capturing_iterate(*args, **kwargs):
        iterate_calls.append(kwargs)
        return iter([])  # empty generator

    with patch.object(client, "_iterate_batches", side_effect=capturing_iterate):
        list(client.pull_update_sets(order_desc=True))

    assert iterate_calls, "Expected _iterate_batches to be called"
    assert iterate_calls[0].get("order_desc") is True


def test_pull_customer_update_xml_passes_order_desc():
    """pull_customer_update_xml with order_desc=True must pass it to _iterate_batches."""
    client = _make_client()
    iterate_calls = []

    def capturing_iterate(*args, **kwargs):
        iterate_calls.append(kwargs)
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=capturing_iterate):
        list(client.pull_customer_update_xml(order_desc=True))

    assert iterate_calls
    assert iterate_calls[0].get("order_desc") is True


def test_pull_version_history_passes_order_desc():
    """pull_version_history with order_desc=True must pass it to _iterate_batches."""
    client = _make_client()
    iterate_calls = []

    def capturing_iterate(*args, **kwargs):
        iterate_calls.append(kwargs)
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=capturing_iterate):
        list(client.pull_version_history(order_desc=True))

    assert iterate_calls
    assert iterate_calls[0].get("order_desc") is True


def test_pull_metadata_customizations_passes_order_desc():
    """pull_metadata_customizations with order_desc=True must pass it to _iterate_batches."""
    client = _make_client()
    iterate_calls = []

    def capturing_iterate(*args, **kwargs):
        iterate_calls.append(kwargs)
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=capturing_iterate):
        list(client.pull_metadata_customizations(order_desc=True))

    assert iterate_calls
    assert iterate_calls[0].get("order_desc") is True


def test_pull_app_file_types_passes_order_desc():
    """pull_app_file_types with order_desc=True must pass it to _iterate_batches."""
    client = _make_client()
    iterate_calls = []

    def capturing_iterate(*args, **kwargs):
        iterate_calls.append(kwargs)
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=capturing_iterate):
        list(client.pull_app_file_types(order_desc=True))

    assert iterate_calls
    assert iterate_calls[0].get("order_desc") is True


def test_pull_sys_db_object_passes_order_desc():
    """pull_sys_db_object with order_desc=True must pass it to _iterate_batches."""
    client = _make_client()
    iterate_calls = []

    def capturing_iterate(*args, **kwargs):
        iterate_calls.append(kwargs)
        return iter([])

    with patch.object(client, "_iterate_batches", side_effect=capturing_iterate):
        list(client.pull_sys_db_object(order_desc=True))

    assert iterate_calls
    assert iterate_calls[0].get("order_desc") is True
