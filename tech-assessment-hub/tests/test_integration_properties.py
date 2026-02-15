from src.models import AppConfig
from src.services.integration_properties import (
    FETCH_DEFAULT_BATCH_SIZE,
    FETCH_INTER_BATCH_DELAY,
    FETCH_MAX_BATCHES,
    FETCH_REQUEST_TIMEOUT,
    list_integration_property_snapshots,
    load_fetch_properties,
    update_integration_properties,
)


def test_load_fetch_properties_defaults(db_session):
    props = load_fetch_properties(db_session)
    assert props.default_batch_size == 200
    assert props.inter_batch_delay == 0.5
    assert props.request_timeout == 60
    assert props.max_batches == 5000


def test_load_fetch_properties_uses_app_config_values(db_session):
    db_session.add(
        AppConfig(
            key=FETCH_DEFAULT_BATCH_SIZE,
            value="500",
            description="test override",
        )
    )
    db_session.add(
        AppConfig(
            key=FETCH_INTER_BATCH_DELAY,
            value="1.0",
            description="test override",
        )
    )
    db_session.commit()

    props = load_fetch_properties(db_session)
    assert props.default_batch_size == 500
    assert props.inter_batch_delay == 1.0


def test_load_fetch_properties_invalid_values_fall_back(db_session):
    db_session.add(
        AppConfig(
            key=FETCH_DEFAULT_BATCH_SIZE,
            value="not-an-int",
            description="bad override",
        )
    )
    db_session.commit()

    props = load_fetch_properties(db_session)
    assert props.default_batch_size == 200


def test_update_integration_properties_persists_and_lists(db_session):
    rows = update_integration_properties(
        db_session,
        {
            FETCH_DEFAULT_BATCH_SIZE: "500",
            FETCH_INTER_BATCH_DELAY: "1.5",
        },
    )
    by_key = {row["key"]: row for row in rows}
    assert by_key[FETCH_DEFAULT_BATCH_SIZE]["effective_value"] == "500"
    assert by_key[FETCH_INTER_BATCH_DELAY]["effective_value"] == "1.5"


def test_update_integration_properties_empty_resets_to_default(db_session):
    update_integration_properties(
        db_session,
        {FETCH_REQUEST_TIMEOUT: "120"},
    )
    rows = update_integration_properties(
        db_session,
        {FETCH_REQUEST_TIMEOUT: ""},
    )
    by_key = {row["key"]: row for row in rows}
    assert by_key[FETCH_REQUEST_TIMEOUT]["effective_value"] == "60"
    assert by_key[FETCH_REQUEST_TIMEOUT]["is_default"] is True


def test_list_integration_property_snapshots_contains_catalog(db_session):
    rows = list_integration_property_snapshots(db_session)
    keys = {row["key"] for row in rows}
    assert FETCH_DEFAULT_BATCH_SIZE in keys
    assert FETCH_INTER_BATCH_DELAY in keys
    assert FETCH_REQUEST_TIMEOUT in keys
    assert FETCH_MAX_BATCHES in keys


def test_update_integration_properties_rejects_unknown_key(db_session):
    try:
        update_integration_properties(db_session, {"integration.sync.unknown": "1"})
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "Unknown integration property keys" in str(exc)
