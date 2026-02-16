from datetime import datetime
from unittest.mock import patch

from src.services.sn_client import ServiceNowClient


def test_iterate_delta_keyset_builds_watermark_then_cursor_queries():
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    queries = []
    batches = [
        [
            {"sys_updated_on": "2026-02-13 10:00:00", "sys_id": "aaa"},
            {"sys_updated_on": "2026-02-13 10:00:00", "sys_id": "bbb"},
        ],
        [],
    ]

    def fake_fetch_with_retry(table, query, fields, batch_size, offset, order_by):
        queries.append(query)
        return batches.pop(0)

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch_with_retry):
        result = list(
            client.iterate_delta_keyset(
                table="sys_update_set",
                watermark=datetime(2026, 2, 13, 9, 0, 0),
                batch_size=2,
                inter_batch_delay=0,
            )
        )

    assert len(result) == 1
    assert "sys_updated_on>=2026-02-13 09:00:00" in queries[0]
    assert "ORDERBYsys_updated_on" in queries[0]
    assert "ORDERBYsys_id" in queries[0]
    assert "sys_updated_on>2026-02-13 10:00:00^ORsys_updated_on=2026-02-13 10:00:00^sys_id>bbb" in queries[1]


def test_iterate_delta_keyset_adds_required_cursor_fields():
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")
    seen_fields = []

    def fake_fetch_with_retry(table, query, fields, batch_size, offset, order_by):
        seen_fields.append(fields)
        return []

    with patch.object(client, "_fetch_with_retry", side_effect=fake_fetch_with_retry):
        list(
            client.iterate_delta_keyset(
                table="sys_update_set",
                watermark=datetime(2026, 2, 13, 9, 0, 0),
                fields=["name"],
                inter_batch_delay=0,
            )
        )

    assert seen_fields
    assert "name" in seen_fields[0]
    assert "sys_updated_on" in seen_fields[0]
    assert "sys_id" in seen_fields[0]

