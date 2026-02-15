import asyncio
from unittest.mock import patch

from src.inventory_class_catalog import inventory_class_tables
from src.server import api_config_summary
from src.services.sn_client import ServiceNowClient


# --- Catalog unit tests (no DB needed) ---

def test_inventory_class_tables_excludes_update_sets_by_default():
    tables = inventory_class_tables()
    assert "update_sets" not in tables
    assert "script_includes" in tables
    assert "scheduled_jobs" in tables


def test_inventory_class_tables_can_include_update_sets():
    base = inventory_class_tables()
    with_update_sets = inventory_class_tables(include_update_sets=True)

    assert "update_sets" in with_update_sets
    for key, value in base.items():
        assert with_update_sets[key] == value


# --- Catalog wiring tests (need DB + mocks) ---

def test_scan_inventory_uses_shared_inventory_table_catalog(db_session):
    client = ServiceNowClient("https://example.service-now.com", "admin", "password")

    with patch(
        "src.services.sn_client.inventory_class_tables",
        return_value={"custom_key": "x_custom_table"},
    ) as catalog_patch, patch.object(client, "get_record_count", return_value=17) as count_patch:
        result = client.scan_inventory(scope="all")

    catalog_patch.assert_called_once_with(include_update_sets=True)
    count_patch.assert_called_once_with("x_custom_table", "")
    assert result == {"custom_key": 17}


def test_api_config_summary_uses_shared_inventory_table_catalog(db_session):
    with patch(
        "src.server.inventory_class_tables",
        return_value={"custom_key": "x_custom_table"},
    ) as catalog_patch:
        payload = asyncio.run(api_config_summary(session=db_session))

    catalog_patch.assert_called_once_with(include_update_sets=False)
    assert payload["series"] == {}
