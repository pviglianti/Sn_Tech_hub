import pytest

from src.models import AppConfig
from src.services.integration_properties import (
    FETCH_DEFAULT_BATCH_SIZE,
    FETCH_INTER_BATCH_DELAY,
    FETCH_MAX_BATCHES,
    FETCH_REQUEST_TIMEOUT,
    PREFLIGHT_CONCURRENT_TYPES,
    list_integration_property_snapshots,
    load_fetch_properties,
    load_preflight_concurrent_types,
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


def test_load_fetch_properties_instance_override_precedence(db_session, sample_instance):
    db_session.add(
        AppConfig(
            instance_id=None,
            key=FETCH_DEFAULT_BATCH_SIZE,
            value="300",
            description="global default",
        )
    )
    db_session.add(
        AppConfig(
            instance_id=sample_instance.id,
            key=FETCH_DEFAULT_BATCH_SIZE,
            value="700",
            description="instance override",
        )
    )
    db_session.commit()

    props_global = load_fetch_properties(db_session)
    props_instance = load_fetch_properties(db_session, instance_id=sample_instance.id)
    assert props_global.default_batch_size == 300
    assert props_instance.default_batch_size == 700


def test_load_fetch_properties_instance_falls_back_to_global(db_session, sample_instance):
    db_session.add(
        AppConfig(
            instance_id=None,
            key=FETCH_INTER_BATCH_DELAY,
            value="1.25",
            description="global default",
        )
    )
    db_session.commit()

    props_instance = load_fetch_properties(db_session, instance_id=sample_instance.id)
    assert props_instance.inter_batch_delay == 1.25


def test_update_and_snapshot_instance_scope(db_session, sample_instance):
    rows = update_integration_properties(
        db_session,
        {FETCH_REQUEST_TIMEOUT: "95"},
        instance_id=sample_instance.id,
    )
    by_key = {row["key"]: row for row in rows}
    assert by_key[FETCH_REQUEST_TIMEOUT]["current_value"] == "95"
    assert by_key[FETCH_REQUEST_TIMEOUT]["effective_value"] == "95"
    assert by_key[FETCH_REQUEST_TIMEOUT]["effective_source"] == "instance"
    assert by_key[FETCH_REQUEST_TIMEOUT]["instance_id"] == sample_instance.id


# ── Multiselect / concurrent types tests ──


def test_load_preflight_concurrent_types_defaults(db_session):
    """Without any config, returns the default concurrent types."""
    types = load_preflight_concurrent_types(db_session)
    assert "version_history" in types
    assert "customer_update_xml" in types
    assert len(types) == 2


def test_load_preflight_concurrent_types_from_config(db_session):
    """Reads comma-separated values from app_config."""
    db_session.add(
        AppConfig(
            key=PREFLIGHT_CONCURRENT_TYPES,
            value="version_history,metadata_customization,update_sets",
            description="test override",
        )
    )
    db_session.commit()

    types = load_preflight_concurrent_types(db_session)
    assert types == ["version_history", "metadata_customization", "update_sets"]


def test_update_multiselect_property(db_session):
    """Multiselect property can be saved and read back."""
    rows = update_integration_properties(
        db_session,
        {PREFLIGHT_CONCURRENT_TYPES: "version_history,plugins"},
    )
    by_key = {row["key"]: row for row in rows}
    assert by_key[PREFLIGHT_CONCURRENT_TYPES]["effective_value"] == "version_history,plugins"


def test_update_multiselect_rejects_invalid_values(db_session):
    """Multiselect rejects selections not in the options list."""
    with pytest.raises(ValueError, match="invalid selections"):
        update_integration_properties(
            db_session,
            {PREFLIGHT_CONCURRENT_TYPES: "version_history,not_a_real_type"},
        )


def test_update_multiselect_rejects_too_many_selections(db_session):
    """Multiselect enforces max_selections."""
    with pytest.raises(ValueError, match="max 5 selections"):
        update_integration_properties(
            db_session,
            {PREFLIGHT_CONCURRENT_TYPES: "version_history,customer_update_xml,metadata_customization,update_sets,app_file_types,plugins"},
        )


def test_multiselect_snapshot_includes_options_and_max(db_session):
    """Snapshot for a multiselect property includes options and max_selections."""
    rows = list_integration_property_snapshots(db_session)
    prop = next(r for r in rows if r["key"] == PREFLIGHT_CONCURRENT_TYPES)
    assert prop["value_type"] == "multiselect"
    assert prop["max_selections"] == 5
    assert any(opt["value"] == "version_history" for opt in prop["options"])
