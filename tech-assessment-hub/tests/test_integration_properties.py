import pytest

from src.models import AppConfig
from src.services.integration_properties import (
    AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD,
    AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD,
    AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL,
    AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL,
    AI_BUDGET_MONTHLY_HARD_LIMIT_USD,
    AI_BUDGET_STOP_ON_HARD_LIMIT,
    AI_RUNTIME_MODE,
    AI_RUNTIME_MODEL,
    AI_RUNTIME_PROVIDER,
    FETCH_DEFAULT_BATCH_SIZE,
    FETCH_INTER_BATCH_DELAY,
    FETCH_MAX_BATCHES,
    FETCH_REQUEST_TIMEOUT,
    OBSERVATIONS_BATCH_SIZE,
    OBSERVATIONS_INCLUDE_USAGE_QUERIES,
    OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT,
    OBSERVATIONS_USAGE_LOOKBACK_MONTHS,
    PIPELINE_USE_REGISTERED_PROMPTS,
    PREFLIGHT_CONCURRENT_TYPES,
    PULL_ORDER_DESC,
    PULL_MAX_RECORDS,
    PULL_BAIL_UNCHANGED_RUN,
    REASONING_FEATURE_MAX_ITERATIONS,
    REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD,
    REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE,
    PipelinePromptProperties,
    list_integration_property_snapshots,
    load_fetch_properties,
    load_ai_runtime_properties,
    load_observation_properties,
    load_pipeline_prompt_properties,
    load_preflight_concurrent_types,
    load_pull_order_desc,
    load_pull_max_records,
    load_pull_bail_unchanged_run,
    load_reasoning_engine_properties,
    update_integration_properties,
    PROPERTY_DEFINITIONS,
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


def test_load_reasoning_properties_feature_defaults(db_session):
    props = load_reasoning_engine_properties(db_session)
    assert props.feature_max_iterations == 3
    assert props.feature_membership_delta_threshold == 0.02
    assert props.feature_min_assignment_confidence == 0.6


def test_load_reasoning_properties_feature_overrides(db_session, sample_instance):
    update_integration_properties(
        db_session,
        {
            REASONING_FEATURE_MAX_ITERATIONS: "7",
            REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD: "0.15",
            REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE: "0.85",
        },
        instance_id=sample_instance.id,
    )

    props = load_reasoning_engine_properties(db_session, instance_id=sample_instance.id)
    assert props.feature_max_iterations == 7
    assert props.feature_membership_delta_threshold == 0.15
    assert props.feature_min_assignment_confidence == 0.85


def test_load_observation_properties_defaults(db_session):
    props = load_observation_properties(db_session)
    assert props.usage_lookback_months == 6
    assert props.batch_size == 10
    assert props.include_usage_queries == "auto"
    assert props.max_usage_queries_per_result == 2


def test_load_observation_properties_overrides(db_session, sample_instance):
    update_integration_properties(
        db_session,
        {
            OBSERVATIONS_USAGE_LOOKBACK_MONTHS: "12",
            OBSERVATIONS_BATCH_SIZE: "25",
            OBSERVATIONS_INCLUDE_USAGE_QUERIES: "always",
            OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT: "4",
        },
        instance_id=sample_instance.id,
    )
    props = load_observation_properties(db_session, instance_id=sample_instance.id)
    assert props.usage_lookback_months == 12
    assert props.batch_size == 25
    assert props.include_usage_queries == "always"
    assert props.max_usage_queries_per_result == 4


def test_pipeline_prompt_property_present_in_snapshot(db_session):
    rows = list_integration_property_snapshots(db_session)
    by_key = {row["key"]: row for row in rows}
    assert PIPELINE_USE_REGISTERED_PROMPTS in by_key
    assert by_key[PIPELINE_USE_REGISTERED_PROMPTS]["default"] == "false"


def test_load_pipeline_prompt_properties_defaults(db_session):
    props = load_pipeline_prompt_properties(db_session)
    assert isinstance(props, PipelinePromptProperties)
    assert props.use_registered_prompts is False


def test_load_pipeline_prompt_properties_override(db_session, sample_instance):
    update_integration_properties(
        db_session,
        {
            PIPELINE_USE_REGISTERED_PROMPTS: "true",
        },
        instance_id=sample_instance.id,
    )
    props = load_pipeline_prompt_properties(db_session, instance_id=sample_instance.id)
    assert props.use_registered_prompts is True


def test_ai_runtime_properties_present_in_snapshot(db_session):
    rows = list_integration_property_snapshots(db_session)
    by_key = {row["key"]: row for row in rows}
    assert AI_RUNTIME_MODE in by_key
    assert AI_RUNTIME_PROVIDER in by_key
    assert AI_RUNTIME_MODEL in by_key
    assert AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD in by_key
    assert AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD in by_key
    assert AI_BUDGET_MONTHLY_HARD_LIMIT_USD in by_key
    assert AI_BUDGET_STOP_ON_HARD_LIMIT in by_key
    assert AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL in by_key
    assert AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL in by_key


def test_load_ai_runtime_properties_defaults(db_session):
    props = load_ai_runtime_properties(db_session)
    assert props.mode == "local_subscription"
    assert props.provider == "openai"
    assert props.model == "gpt-5-mini"
    assert props.assessment_soft_limit_usd == 10.0
    assert props.assessment_hard_limit_usd == 25.0
    assert props.monthly_hard_limit_usd == 200.0
    assert props.stop_on_hard_limit is True
    assert props.max_input_tokens_per_call == 200000
    assert props.max_output_tokens_per_call == 40000


def test_load_ai_runtime_properties_overrides(db_session, sample_instance):
    update_integration_properties(
        db_session,
        {
            AI_RUNTIME_MODE: "api_key",
            AI_RUNTIME_PROVIDER: "anthropic",
            AI_RUNTIME_MODEL: "claude-sonnet-4-5",
            AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD: "15.5",
            AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD: "35",
            AI_BUDGET_MONTHLY_HARD_LIMIT_USD: "500",
            AI_BUDGET_STOP_ON_HARD_LIMIT: "false",
            AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL: "180000",
            AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL: "12000",
        },
        instance_id=sample_instance.id,
    )

    props = load_ai_runtime_properties(db_session, instance_id=sample_instance.id)
    assert props.mode == "api_key"
    assert props.provider == "anthropic"
    assert props.model == "claude-sonnet-4-5"
    assert props.assessment_soft_limit_usd == 15.5
    assert props.assessment_hard_limit_usd == 35.0
    assert props.monthly_hard_limit_usd == 500.0
    assert props.stop_on_hard_limit is False
    assert props.max_input_tokens_per_call == 180000
    assert props.max_output_tokens_per_call == 12000


# ---------------------------------------------------------------------------
# New pull optimization property tests
# ---------------------------------------------------------------------------


def test_load_pull_order_desc_returns_true_by_default(db_session):
    """load_pull_order_desc() must return True when no override is set (default 'true')."""
    result = load_pull_order_desc(db_session)
    assert result is True


def test_load_pull_order_desc_false_when_set_to_false(db_session):
    """load_pull_order_desc() must return False when property is set to 'false'."""
    db_session.add(AppConfig(key=PULL_ORDER_DESC, value="false", description="test"))
    db_session.commit()
    result = load_pull_order_desc(db_session)
    assert result is False


def test_load_pull_order_desc_true_when_set_to_true(db_session):
    """load_pull_order_desc() must return True when property is explicitly set to 'true'."""
    db_session.add(AppConfig(key=PULL_ORDER_DESC, value="true", description="test"))
    db_session.commit()
    result = load_pull_order_desc(db_session)
    assert result is True


def test_load_pull_max_records_returns_5000_by_default(db_session):
    """load_pull_max_records() must return 5000 when no override is set."""
    result = load_pull_max_records(db_session)
    assert result == 5000


def test_load_pull_max_records_uses_override(db_session):
    """load_pull_max_records() must return the overridden value when set."""
    db_session.add(AppConfig(key=PULL_MAX_RECORDS, value="10000", description="test"))
    db_session.commit()
    result = load_pull_max_records(db_session)
    assert result == 10000


def test_load_pull_max_records_falls_back_on_invalid(db_session):
    """load_pull_max_records() must fall back to 5000 on invalid (non-int) value."""
    db_session.add(AppConfig(key=PULL_MAX_RECORDS, value="not-a-number", description="test"))
    db_session.commit()
    result = load_pull_max_records(db_session)
    assert result == 5000


def test_load_pull_bail_unchanged_run_returns_50_by_default(db_session):
    """load_pull_bail_unchanged_run() must return 50 when no override is set."""
    result = load_pull_bail_unchanged_run(db_session)
    assert result == 50


def test_load_pull_bail_unchanged_run_uses_override(db_session):
    """load_pull_bail_unchanged_run() must return the overridden value when set."""
    db_session.add(AppConfig(key=PULL_BAIL_UNCHANGED_RUN, value="100", description="test"))
    db_session.commit()
    result = load_pull_bail_unchanged_run(db_session)
    assert result == 100


def test_load_pull_bail_unchanged_run_falls_back_on_invalid(db_session):
    """load_pull_bail_unchanged_run() must fall back to 50 on invalid value."""
    db_session.add(AppConfig(key=PULL_BAIL_UNCHANGED_RUN, value="bad-value", description="test"))
    db_session.commit()
    result = load_pull_bail_unchanged_run(db_session)
    assert result == 50


def test_new_pull_properties_exist_in_property_definitions():
    """All 3 new pull optimization keys must be registered in PROPERTY_DEFINITIONS."""
    assert PULL_ORDER_DESC in PROPERTY_DEFINITIONS, (
        f"PULL_ORDER_DESC ({PULL_ORDER_DESC!r}) not found in PROPERTY_DEFINITIONS"
    )
    assert PULL_MAX_RECORDS in PROPERTY_DEFINITIONS, (
        f"PULL_MAX_RECORDS ({PULL_MAX_RECORDS!r}) not found in PROPERTY_DEFINITIONS"
    )
    assert PULL_BAIL_UNCHANGED_RUN in PROPERTY_DEFINITIONS, (
        f"PULL_BAIL_UNCHANGED_RUN ({PULL_BAIL_UNCHANGED_RUN!r}) not found in PROPERTY_DEFINITIONS"
    )


def test_pull_order_desc_property_definition_is_select_type():
    """PULL_ORDER_DESC PropertyDef must be select type with true/false options."""
    defn = PROPERTY_DEFINITIONS[PULL_ORDER_DESC]
    assert defn.value_type == "select"
    option_keys = [opt[0] for opt in defn.options]
    assert "true" in option_keys
    assert "false" in option_keys


def test_pull_max_records_property_definition_is_int_type():
    """PULL_MAX_RECORDS PropertyDef must be int type with sensible min/max."""
    defn = PROPERTY_DEFINITIONS[PULL_MAX_RECORDS]
    assert defn.value_type == "int"
    assert defn.default == "5000"
    assert defn.min_value is not None and defn.min_value >= 1
    assert defn.max_value is not None and defn.max_value >= 5000


def test_pull_bail_unchanged_run_property_definition_is_int_type():
    """PULL_BAIL_UNCHANGED_RUN PropertyDef must be int type with sensible min/max."""
    defn = PROPERTY_DEFINITIONS[PULL_BAIL_UNCHANGED_RUN]
    assert defn.value_type == "int"
    assert defn.default == "50"
    assert defn.min_value is not None and defn.min_value >= 1
