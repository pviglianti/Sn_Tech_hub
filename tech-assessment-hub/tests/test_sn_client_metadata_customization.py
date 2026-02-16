from datetime import datetime
from unittest.mock import patch

from src.services.sn_client import ServiceNowClient


def test_build_metadata_queries_chunks_by_length():
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    since = datetime(2026, 2, 7, 12, 0, 0)
    class_names = [f"sys_class_name_{index:03d}_extremely_long_value" for index in range(1, 80)]

    queries = client.build_metadata_customization_queries(
        since=since,
        class_names=class_names,
        max_query_length=220,
        max_classes_per_query=200,
    )

    assert len(queries) > 1
    for query in queries:
        assert "sys_updated_on>=2026-02-07 12:00:00" in query
        assert "sys_metadata.sys_class_nameIN" in query
        assert len(query) <= 220


def test_build_metadata_queries_chunks_by_class_count():
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    queries = client.build_metadata_customization_queries(
        class_names=["one", "two", "three", "four", "five"],
        max_query_length=10_000,
        max_classes_per_query=2,
    )

    assert len(queries) == 3
    assert queries[0].endswith("sys_metadata.sys_class_nameINone,two")
    assert queries[1].endswith("sys_metadata.sys_class_nameINthree,four")
    assert queries[2].endswith("sys_metadata.sys_class_nameINfive")


def test_get_metadata_customization_count_sums_all_chunks():
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    with patch.object(
        client,
        "build_metadata_customization_queries",
        return_value=["query_a", "query_b", "query_c"],
    ), patch.object(client, "get_record_count", side_effect=[3, 5, 8]):
        total = client.get_metadata_customization_count(class_names=["sys_script"])

    assert total == 16


def test_pull_metadata_customizations_iterates_all_queries():
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    seen_queries = []

    def fake_iterate(*args, **kwargs):
        query = kwargs.get("query", "")
        seen_queries.append(query)
        return iter([[{"sys_id": f"{query}-row"}]])

    with patch.object(
        client,
        "build_metadata_customization_queries",
        return_value=["query_one", "query_two"],
    ), patch.object(client, "_iterate_batches", side_effect=fake_iterate):
        batches = list(client.pull_metadata_customizations(class_names=["sys_script"]))

    assert seen_queries == ["query_one", "query_two"]
    assert len(batches) == 2
    assert batches[0][0]["sys_id"] == "query_one-row"
    assert batches[1][0]["sys_id"] == "query_two-row"
