from datetime import datetime

from src.services.sn_client import ServiceNowClient


def _make_client():
    return ServiceNowClient("https://example.service-now.com", "admin", "password")


# --- _watermark_filter helper tests ---


def test_watermark_filter_inclusive_uses_gte():
    client = _make_client()
    result = client._watermark_filter(datetime(2026, 2, 13, 9, 0, 0), inclusive=True)
    assert result == "sys_updated_on>=2026-02-13 09:00:00"


def test_watermark_filter_exclusive_uses_gt():
    client = _make_client()
    result = client._watermark_filter(datetime(2026, 2, 13, 9, 0, 0), inclusive=False)
    assert result == "sys_updated_on>2026-02-13 09:00:00"


def test_watermark_filter_defaults_to_inclusive():
    client = _make_client()
    result = client._watermark_filter(datetime(2026, 2, 13, 9, 0, 0))
    assert ">=" in result


# --- build_*_query methods: default (inclusive=True) should use >= ---


def test_build_update_set_query_uses_gte_for_delta():
    client = _make_client()
    query = client.build_update_set_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_version_history_query_uses_gte_for_delta():
    client = _make_client()
    query = client.build_version_history_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_customer_update_xml_query_uses_gte_for_delta():
    client = _make_client()
    query = client.build_customer_update_xml_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_metadata_customization_queries_uses_gte_for_delta():
    client = _make_client()
    queries = client.build_metadata_customization_queries(since=datetime(2026, 2, 13, 9, 0, 0))
    assert any("sys_updated_on>=2026-02-13 09:00:00" in q for q in queries)


def test_build_app_file_types_query_uses_gte():
    client = _make_client()
    query = client.build_app_file_types_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_plugins_query_uses_gte():
    client = _make_client()
    query = client.build_plugins_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_scopes_query_uses_gte():
    client = _make_client()
    query = client.build_scopes_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_packages_query_uses_gte():
    client = _make_client()
    query = client.build_packages_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_applications_query_uses_gte():
    client = _make_client()
    query = client.build_applications_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_sys_db_object_query_uses_gte():
    client = _make_client()
    query = client.build_sys_db_object_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


def test_build_plugin_view_query_uses_gte():
    client = _make_client()
    query = client.build_plugin_view_query(since=datetime(2026, 2, 13, 9, 0, 0))
    assert "sys_updated_on>=2026-02-13 09:00:00" in query


# --- Probe path: inclusive=False should use > ---


def test_build_update_set_query_probe_uses_gt():
    """When inclusive=False (for probes), should use > not >=."""
    client = _make_client()
    query = client.build_update_set_query(since=datetime(2026, 2, 13, 9, 0, 0), inclusive=False)
    assert "sys_updated_on>2026-02-13 09:00:00" in query
    assert ">=" not in query


def test_build_version_history_query_probe_uses_gt():
    client = _make_client()
    query = client.build_version_history_query(since=datetime(2026, 2, 13, 9, 0, 0), inclusive=False)
    assert "sys_updated_on>2026-02-13 09:00:00" in query
    assert ">=" not in query
