"""Integration property registry and typed accessors.

This module centralizes tunable integration behavior so values can be moved to
an Admin UI (via ``app_config``) without touching execution code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlmodel import Session, select

from ..models import AppConfig

PropertyType = Literal["int", "float", "select", "multiselect"]
PROPERTY_SCOPE_APPLICATION = "application_instance"

# ---------------------------------------------------------------------------
# Section ordering — controls UI grouping on the properties page
# ---------------------------------------------------------------------------

SECTION_GENERAL = "General"
SECTION_PREFLIGHT = "Assessment / Preflight"
SECTION_FETCH = "Integration / Fetch"
SECTION_REASONING = "Reasoning / Engines"
SECTION_OBSERVATIONS = "Observations"

SECTION_ORDER: List[str] = [
    SECTION_GENERAL,
    SECTION_PREFLIGHT,
    SECTION_FETCH,
    SECTION_REASONING,
    SECTION_OBSERVATIONS,
]

# ---------------------------------------------------------------------------
# Property keys
# ---------------------------------------------------------------------------

GENERAL_DISPLAY_TIMEZONE = "general.display_timezone"

PREFLIGHT_CONCURRENT_TYPES = "preflight.concurrent_types"

FETCH_DEFAULT_BATCH_SIZE = "integration.fetch.default_batch_size"
FETCH_INTER_BATCH_DELAY = "integration.fetch.inter_batch_delay"
FETCH_REQUEST_TIMEOUT = "integration.fetch.request_timeout"
FETCH_MAX_BATCHES = "integration.fetch.max_batches"

# Reasoning engine keys
REASONING_US_MIN_SHARED_RECORDS = "reasoning.us.min_shared_records"
REASONING_US_NAME_SIMILARITY_MIN_TOKENS = "reasoning.us.name_similarity_min_tokens"
REASONING_US_INCLUDE_DEFAULT_SETS = "reasoning.us.include_default_sets"
REASONING_US_DEFAULT_SIGNAL_WEIGHT = "reasoning.us.default_signal_weight"
REASONING_TEMPORAL_GAP_THRESHOLD = "reasoning.temporal.gap_threshold_minutes"
REASONING_TEMPORAL_MIN_CLUSTER_SIZE = "reasoning.temporal.min_cluster_size"
REASONING_NAMING_MIN_CLUSTER_SIZE = "reasoning.naming.min_cluster_size"
REASONING_NAMING_MIN_PREFIX_TOKENS = "reasoning.naming.min_prefix_tokens"
REASONING_FEATURE_MAX_ITERATIONS = "reasoning.feature.max_iterations"
REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD = "reasoning.feature.membership_delta_threshold"
REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE = "reasoning.feature.min_assignment_confidence"

# Observation pipeline keys
OBSERVATIONS_USAGE_LOOKBACK_MONTHS = "observations.usage_lookback_months"
OBSERVATIONS_BATCH_SIZE = "observations.batch_size"
OBSERVATIONS_INCLUDE_USAGE_QUERIES = "observations.include_usage_queries"
OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT = "observations.max_usage_queries_per_result"

# Common IANA timezone choices for the select dropdown
TIMEZONE_OPTIONS: List[Tuple[str, str]] = [
    ("America/New_York", "Eastern (ET)"),
    ("America/Chicago", "Central (CT)"),
    ("America/Denver", "Mountain (MT)"),
    ("America/Los_Angeles", "Pacific (PT)"),
    ("America/Anchorage", "Alaska (AKT)"),
    ("Pacific/Honolulu", "Hawaii (HT)"),
    ("UTC", "UTC"),
    ("Europe/London", "London (GMT/BST)"),
    ("Europe/Berlin", "Central Europe (CET)"),
    ("Asia/Tokyo", "Tokyo (JST)"),
    ("Australia/Sydney", "Sydney (AEST)"),
]


@dataclass(frozen=True)
class FetchProperties:
    """Typed fetch/pagination properties used by all integration sync paths."""
    default_batch_size: int = 200
    inter_batch_delay: float = 0.5
    request_timeout: int = 60
    max_batches: int = 5000


@dataclass(frozen=True)
class ReasoningEngineProperties:
    """Typed reasoning engine thresholds and flags loaded from app_config."""
    us_min_shared_records: int = 1
    us_name_similarity_min_tokens: int = 2
    us_include_default_sets: bool = True
    us_default_signal_weight: float = 0.3
    temporal_gap_threshold_minutes: int = 60
    temporal_min_cluster_size: int = 2
    naming_min_cluster_size: int = 2
    naming_min_prefix_tokens: int = 2
    feature_max_iterations: int = 3
    feature_membership_delta_threshold: float = 0.02
    feature_min_assignment_confidence: float = 0.6


@dataclass(frozen=True)
class ObservationProperties:
    """Typed observation-pipeline properties loaded from app_config."""
    usage_lookback_months: int = 6
    batch_size: int = 10
    include_usage_queries: str = "auto"
    max_usage_queries_per_result: int = 2


@dataclass(frozen=True)
class IntegrationPropertyDefinition:
    key: str
    label: str
    description: str
    value_type: PropertyType
    default: str
    scope: str
    applies_to: str
    section: str = SECTION_FETCH
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    max_selections: Optional[int] = None
    options: List[Tuple[str, str]] = field(default_factory=list)


PREFLIGHT_CONCURRENT_TYPE_OPTIONS: List[Tuple[str, str]] = [
    ("version_history", "Version History"),
    ("customer_update_xml", "Customer Update XML"),
    ("metadata_customization", "Metadata Customization"),
    ("update_sets", "Update Sets"),
    ("app_file_types", "App File Types"),
    ("plugins", "Plugins"),
    ("scopes", "Scopes"),
    ("packages", "Packages"),
    ("applications", "Applications"),
]

BOOL_OPTIONS: List[Tuple[str, str]] = [
    ("true", "Yes"),
    ("false", "No"),
]

PROPERTY_DEFAULTS: Dict[str, str] = {
    PREFLIGHT_CONCURRENT_TYPES: "version_history,customer_update_xml",
    GENERAL_DISPLAY_TIMEZONE: "America/New_York",
    FETCH_DEFAULT_BATCH_SIZE: "200",
    FETCH_INTER_BATCH_DELAY: "0.5",
    FETCH_REQUEST_TIMEOUT: "60",
    FETCH_MAX_BATCHES: "5000",
    # Reasoning engine defaults
    REASONING_US_MIN_SHARED_RECORDS: "1",
    REASONING_US_NAME_SIMILARITY_MIN_TOKENS: "2",
    REASONING_US_INCLUDE_DEFAULT_SETS: "true",
    REASONING_US_DEFAULT_SIGNAL_WEIGHT: "0.3",
    REASONING_TEMPORAL_GAP_THRESHOLD: "60",
    REASONING_TEMPORAL_MIN_CLUSTER_SIZE: "2",
    REASONING_NAMING_MIN_CLUSTER_SIZE: "2",
    REASONING_NAMING_MIN_PREFIX_TOKENS: "2",
    REASONING_FEATURE_MAX_ITERATIONS: "3",
    REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD: "0.02",
    REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE: "0.6",
    # Observation pipeline defaults
    OBSERVATIONS_USAGE_LOOKBACK_MONTHS: "6",
    OBSERVATIONS_BATCH_SIZE: "10",
    OBSERVATIONS_INCLUDE_USAGE_QUERIES: "auto",
    OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT: "2",
}

PROPERTY_DEFINITIONS: Dict[str, IntegrationPropertyDefinition] = {
    PREFLIGHT_CONCURRENT_TYPES: IntegrationPropertyDefinition(
        key=PREFLIGHT_CONCURRENT_TYPES,
        label="Concurrent Preflight Types",
        description=(
            "Data types pulled in parallel during assessment preflight. "
            "Each runs in its own thread. More types = faster preflight, "
            "but higher load on the ServiceNow instance."
        ),
        value_type="multiselect",
        default=PROPERTY_DEFAULTS[PREFLIGHT_CONCURRENT_TYPES],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="preflight",
        section=SECTION_PREFLIGHT,
        max_selections=5,
        options=PREFLIGHT_CONCURRENT_TYPE_OPTIONS,
    ),
    GENERAL_DISPLAY_TIMEZONE: IntegrationPropertyDefinition(
        key=GENERAL_DISPLAY_TIMEZONE,
        label="Display Timezone",
        description=(
            "Timezone used when displaying dates and times throughout the app. "
            "All data is stored in UTC internally — this only affects display."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[GENERAL_DISPLAY_TIMEZONE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="display",
        section=SECTION_GENERAL,
        options=TIMEZONE_OPTIONS,
    ),
    FETCH_DEFAULT_BATCH_SIZE: IntegrationPropertyDefinition(
        key=FETCH_DEFAULT_BATCH_SIZE,
        label="Default Batch Size",
        description=(
            "Number of records per ServiceNow API call. Higher values reduce "
            "total API calls but increase payload size. Applies to all sync paths."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[FETCH_DEFAULT_BATCH_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        min_value=10,
        max_value=1000,
    ),
    FETCH_INTER_BATCH_DELAY: IntegrationPropertyDefinition(
        key=FETCH_INTER_BATCH_DELAY,
        label="Inter-Batch Delay (sec)",
        description=(
            "Seconds to pause between successive API calls. Controls rate-limiting "
            "to avoid overloading the ServiceNow instance."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[FETCH_INTER_BATCH_DELAY],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        min_value=0.0,
        max_value=30.0,
    ),
    FETCH_REQUEST_TIMEOUT: IntegrationPropertyDefinition(
        key=FETCH_REQUEST_TIMEOUT,
        label="Request Timeout (sec)",
        description=(
            "HTTP request timeout in seconds per API call. Increase for slow "
            "instances or large tables."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[FETCH_REQUEST_TIMEOUT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        min_value=10,
        max_value=300,
    ),
    FETCH_MAX_BATCHES: IntegrationPropertyDefinition(
        key=FETCH_MAX_BATCHES,
        label="Max Batches Per Pull",
        description=(
            "Safety cap on total API calls per table pull. "
            "batch_size x max_batches = max records retrievable."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[FETCH_MAX_BATCHES],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        min_value=10,
        max_value=50000,
    ),
    # ----- Reasoning engine properties -----
    REASONING_US_MIN_SHARED_RECORDS: IntegrationPropertyDefinition(
        key=REASONING_US_MIN_SHARED_RECORDS,
        label="Min Shared Records (US Overlap)",
        description=(
            "Minimum number of shared artifact records between two update sets "
            "for a content overlap signal to be emitted."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_US_MIN_SHARED_RECORDS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=1,
        max_value=100,
    ),
    REASONING_US_NAME_SIMILARITY_MIN_TOKENS: IntegrationPropertyDefinition(
        key=REASONING_US_NAME_SIMILARITY_MIN_TOKENS,
        label="Min Name Tokens (US Similarity)",
        description=(
            "Minimum number of matching tokens in update set names "
            "for a name_similarity signal to be emitted."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_US_NAME_SIMILARITY_MIN_TOKENS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=1,
        max_value=10,
    ),
    REASONING_US_INCLUDE_DEFAULT_SETS: IntegrationPropertyDefinition(
        key=REASONING_US_INCLUDE_DEFAULT_SETS,
        label="Include Default Update Sets",
        description=(
            "Whether to include Default update set relationships in overlap analysis. "
            "When enabled, default US signals are emitted with downgraded confidence."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[REASONING_US_INCLUDE_DEFAULT_SETS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        options=BOOL_OPTIONS,
    ),
    REASONING_US_DEFAULT_SIGNAL_WEIGHT: IntegrationPropertyDefinition(
        key=REASONING_US_DEFAULT_SIGNAL_WEIGHT,
        label="Default US Signal Weight",
        description=(
            "Confidence multiplier for overlap signals involving Default update sets. "
            "Lower values reduce their influence on grouping."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[REASONING_US_DEFAULT_SIGNAL_WEIGHT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=0.0,
        max_value=1.0,
    ),
    REASONING_TEMPORAL_GAP_THRESHOLD: IntegrationPropertyDefinition(
        key=REASONING_TEMPORAL_GAP_THRESHOLD,
        label="Temporal Gap Threshold (min)",
        description=(
            "Maximum gap in minutes between consecutive records by the same developer "
            "to be considered part of the same temporal cluster."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_TEMPORAL_GAP_THRESHOLD],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=5,
        max_value=1440,
    ),
    REASONING_TEMPORAL_MIN_CLUSTER_SIZE: IntegrationPropertyDefinition(
        key=REASONING_TEMPORAL_MIN_CLUSTER_SIZE,
        label="Min Cluster Size (Temporal)",
        description="Minimum number of records to form a temporal cluster.",
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_TEMPORAL_MIN_CLUSTER_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=2,
        max_value=50,
    ),
    REASONING_NAMING_MIN_CLUSTER_SIZE: IntegrationPropertyDefinition(
        key=REASONING_NAMING_MIN_CLUSTER_SIZE,
        label="Min Cluster Size (Naming)",
        description="Minimum number of artifacts sharing a name prefix to form a naming cluster.",
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_NAMING_MIN_CLUSTER_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=2,
        max_value=50,
    ),
    REASONING_NAMING_MIN_PREFIX_TOKENS: IntegrationPropertyDefinition(
        key=REASONING_NAMING_MIN_PREFIX_TOKENS,
        label="Min Prefix Tokens (Naming)",
        description=(
            "Minimum number of tokens in a shared name prefix "
            "for the naming analyzer to consider it significant."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_NAMING_MIN_PREFIX_TOKENS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=1,
        max_value=10,
    ),
    REASONING_FEATURE_MAX_ITERATIONS: IntegrationPropertyDefinition(
        key=REASONING_FEATURE_MAX_ITERATIONS,
        label="Feature Reasoning Max Iterations",
        description=(
            "Maximum reasoning passes before the feature grouping loop stops, "
            "even if convergence has not yet been reached."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_FEATURE_MAX_ITERATIONS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=1,
        max_value=20,
    ),
    REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD: IntegrationPropertyDefinition(
        key=REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD,
        label="Feature Membership Delta Threshold",
        description=(
            "Convergence threshold for feature grouping passes. "
            "If membership change ratio falls below this value and no high-confidence "
            "changes remain, the run is considered converged."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=0.0,
        max_value=1.0,
    ),
    REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE: IntegrationPropertyDefinition(
        key=REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE,
        label="Feature Min Assignment Confidence",
        description=(
            "Minimum confidence considered high-confidence when evaluating "
            "membership-change convergence in reasoning passes."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=0.0,
        max_value=1.0,
    ),
    OBSERVATIONS_USAGE_LOOKBACK_MONTHS: IntegrationPropertyDefinition(
        key=OBSERVATIONS_USAGE_LOOKBACK_MONTHS,
        label="Usage Lookback (Months)",
        description=(
            "How far back to evaluate activity when optional usage checks are run "
            "during observation generation."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[OBSERVATIONS_USAGE_LOOKBACK_MONTHS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="observations",
        section=SECTION_OBSERVATIONS,
        min_value=1,
        max_value=24,
    ),
    OBSERVATIONS_BATCH_SIZE: IntegrationPropertyDefinition(
        key=OBSERVATIONS_BATCH_SIZE,
        label="Observation Batch Size",
        description=(
            "Number of customized scan results processed per observation batch run."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[OBSERVATIONS_BATCH_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="observations",
        section=SECTION_OBSERVATIONS,
        min_value=1,
        max_value=200,
    ),
    OBSERVATIONS_INCLUDE_USAGE_QUERIES: IntegrationPropertyDefinition(
        key=OBSERVATIONS_INCLUDE_USAGE_QUERIES,
        label="Include Usage Queries",
        description=(
            "Controls whether optional instance usage-count queries are run while "
            "generating observations."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[OBSERVATIONS_INCLUDE_USAGE_QUERIES],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="observations",
        section=SECTION_OBSERVATIONS,
        options=[
            ("always", "Always"),
            ("auto", "Auto"),
            ("never", "Never"),
        ],
    ),
    OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT: IntegrationPropertyDefinition(
        key=OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT,
        label="Max Usage Queries Per Result",
        description=(
            "Maximum usage-count queries allowed per customized artifact while "
            "building observation context."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="observations",
        section=SECTION_OBSERVATIONS,
        min_value=0,
        max_value=10,
    ),
}


def get_integration_property_definitions() -> List[IntegrationPropertyDefinition]:
    return list(PROPERTY_DEFINITIONS.values())


def _read_row_exact(session: Session, key: str, instance_id: Optional[int]) -> Optional[AppConfig]:
    stmt = select(AppConfig).where(AppConfig.key == key)
    if instance_id is None:
        stmt = stmt.where(AppConfig.instance_id.is_(None))
    else:
        stmt = stmt.where(AppConfig.instance_id == instance_id)
    return session.exec(stmt).first()


def _read_row(session: Session, key: str, instance_id: Optional[int] = None) -> Optional[AppConfig]:
    """Read property row with optional instance fallback to global."""
    if instance_id is not None:
        scoped = _read_row_exact(session, key, instance_id)
        if scoped:
            return scoped
    return _read_row_exact(session, key, None)


def _read_property(session: Session, key: str, instance_id: Optional[int] = None) -> Optional[str]:
    row = _read_row(session, key, instance_id=instance_id)
    if not row or row.value is None:
        return None
    return str(row.value).strip()


def _parse_typed(raw_value: str, definition: IntegrationPropertyDefinition) -> Any:
    if definition.value_type == "select":
        valid_keys = [opt[0] for opt in definition.options]
        if raw_value not in valid_keys:
            raise ValueError(
                f"{definition.key} must be one of: {', '.join(valid_keys)}"
            )
        return raw_value

    if definition.value_type == "multiselect":
        valid_keys = {opt[0] for opt in definition.options}
        selections = [s.strip() for s in raw_value.split(",") if s.strip()]
        invalid = [s for s in selections if s not in valid_keys]
        if invalid:
            raise ValueError(
                f"{definition.key}: invalid selections: {', '.join(invalid)}"
            )
        if definition.max_selections and len(selections) > definition.max_selections:
            raise ValueError(
                f"{definition.key}: max {definition.max_selections} selections"
            )
        return selections

    if definition.value_type == "int":
        parsed = int(raw_value)
    else:
        parsed = float(raw_value)

    if definition.min_value is not None and parsed < definition.min_value:
        raise ValueError(f"{definition.key} must be >= {definition.min_value}")
    if definition.max_value is not None and parsed > definition.max_value:
        raise ValueError(f"{definition.key} must be <= {definition.max_value}")
    return parsed


def _normalize_for_storage(value: Any, definition: IntegrationPropertyDefinition) -> str:
    if value is None:
        raise ValueError(f"{definition.key} requires a value")
    raw = str(value).strip()
    if raw == "":
        raise ValueError(f"{definition.key} requires a value")

    parsed = _parse_typed(raw, definition)
    if definition.value_type == "select":
        return str(parsed)
    if definition.value_type == "multiselect":
        return ",".join(parsed) if isinstance(parsed, list) else str(parsed)
    if definition.value_type == "int":
        return str(int(parsed))
    return f"{float(parsed):g}"


def list_integration_property_snapshots(
    session: Session,
    instance_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    snapshots: List[Dict[str, Any]] = []
    for definition in get_integration_property_definitions():
        scoped_row = _read_row_exact(session, definition.key, instance_id) if instance_id is not None else None
        global_row = _read_row_exact(session, definition.key, None)

        current_row = scoped_row if instance_id is not None else global_row
        current_value = str(current_row.value).strip() if current_row and current_row.value is not None else None

        if scoped_row and scoped_row.value not in (None, ""):
            effective_value = str(scoped_row.value).strip()
            effective_source = "instance"
        elif global_row and global_row.value not in (None, ""):
            effective_value = str(global_row.value).strip()
            effective_source = "global"
        else:
            effective_value = definition.default
            effective_source = "default"

        snap: Dict[str, Any] = {
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "value_type": definition.value_type,
            "scope": definition.scope,
            "applies_to": definition.applies_to,
            "section": definition.section,
            "default": definition.default,
            "current_value": current_value,
            "effective_value": effective_value,
            "is_default": current_value in (None, ""),
            "effective_source": effective_source,
            "instance_id": instance_id,
            "min_value": definition.min_value,
            "max_value": definition.max_value,
            "max_selections": definition.max_selections,
        }
        if definition.options:
            snap["options"] = [
                {"value": v, "label": lbl} for v, lbl in definition.options
            ]
        snapshots.append(snap)
    return snapshots


def update_integration_properties(
    session: Session,
    updates: Dict[str, Any],
    instance_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    unknown = [key for key in updates.keys() if key not in PROPERTY_DEFINITIONS]
    if unknown:
        raise ValueError(f"Unknown integration property keys: {', '.join(sorted(unknown))}")

    for key, value in updates.items():
        definition = PROPERTY_DEFINITIONS[key]
        row = _read_row_exact(session, key, instance_id)
        if value is None or str(value).strip() == "":
            if row:
                session.delete(row)
            continue

        normalized_value = _normalize_for_storage(value, definition)
        if row:
            row.value = normalized_value
            row.description = definition.description
        else:
            row = AppConfig(
                instance_id=instance_id,
                key=key,
                value=normalized_value,
                description=definition.description,
            )
        session.add(row)

    session.commit()
    return list_integration_property_snapshots(session, instance_id=instance_id)


def _get_int(session: Session, key: str, default: int, instance_id: Optional[int] = None) -> int:
    raw = _read_property(session, key, instance_id=instance_id)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_float(session: Session, key: str, default: float, instance_id: Optional[int] = None) -> float:
    raw = _read_property(session, key, instance_id=instance_id)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_fetch_properties(session: Session, instance_id: Optional[int] = None) -> FetchProperties:
    """Load typed fetch/pagination properties from app_config with safe defaults."""
    defaults = FetchProperties()
    return FetchProperties(
        default_batch_size=_get_int(session, FETCH_DEFAULT_BATCH_SIZE, defaults.default_batch_size, instance_id=instance_id),
        inter_batch_delay=_get_float(session, FETCH_INTER_BATCH_DELAY, defaults.inter_batch_delay, instance_id=instance_id),
        request_timeout=_get_int(session, FETCH_REQUEST_TIMEOUT, defaults.request_timeout, instance_id=instance_id),
        max_batches=_get_int(session, FETCH_MAX_BATCHES, defaults.max_batches, instance_id=instance_id),
    )


def load_display_timezone(session: Session, instance_id: Optional[int] = None) -> str:
    """Return the configured IANA display timezone (e.g. 'America/New_York')."""
    raw = _read_property(session, GENERAL_DISPLAY_TIMEZONE, instance_id=instance_id)
    if raw and raw.strip():
        return raw.strip()
    return PROPERTY_DEFAULTS[GENERAL_DISPLAY_TIMEZONE]


def load_preflight_concurrent_types(session: Session, instance_id: Optional[int] = None) -> List[str]:
    """Return the list of data pull types configured for concurrent preflight."""
    raw = _read_property(session, PREFLIGHT_CONCURRENT_TYPES, instance_id=instance_id)
    if not raw or not raw.strip():
        raw = PROPERTY_DEFAULTS[PREFLIGHT_CONCURRENT_TYPES]
    return [s.strip() for s in raw.split(",") if s.strip()]


def load_reasoning_engine_properties(
    session: Session,
    instance_id: Optional[int] = None,
) -> ReasoningEngineProperties:
    """Load typed reasoning-engine properties from app_config with safe defaults."""
    defaults = ReasoningEngineProperties()
    include_default_raw = (
        _read_property(session, REASONING_US_INCLUDE_DEFAULT_SETS, instance_id=instance_id)
        or PROPERTY_DEFAULTS[REASONING_US_INCLUDE_DEFAULT_SETS]
    ).strip().lower()
    include_default_sets = include_default_raw in {"1", "true", "yes", "y", "on"}

    return ReasoningEngineProperties(
        us_min_shared_records=_get_int(
            session,
            REASONING_US_MIN_SHARED_RECORDS,
            defaults.us_min_shared_records,
            instance_id=instance_id,
        ),
        us_name_similarity_min_tokens=_get_int(
            session,
            REASONING_US_NAME_SIMILARITY_MIN_TOKENS,
            defaults.us_name_similarity_min_tokens,
            instance_id=instance_id,
        ),
        us_include_default_sets=include_default_sets,
        us_default_signal_weight=_get_float(
            session,
            REASONING_US_DEFAULT_SIGNAL_WEIGHT,
            defaults.us_default_signal_weight,
            instance_id=instance_id,
        ),
        temporal_gap_threshold_minutes=_get_int(
            session,
            REASONING_TEMPORAL_GAP_THRESHOLD,
            defaults.temporal_gap_threshold_minutes,
            instance_id=instance_id,
        ),
        temporal_min_cluster_size=_get_int(
            session,
            REASONING_TEMPORAL_MIN_CLUSTER_SIZE,
            defaults.temporal_min_cluster_size,
            instance_id=instance_id,
        ),
        naming_min_cluster_size=_get_int(
            session,
            REASONING_NAMING_MIN_CLUSTER_SIZE,
            defaults.naming_min_cluster_size,
            instance_id=instance_id,
        ),
        naming_min_prefix_tokens=_get_int(
            session,
            REASONING_NAMING_MIN_PREFIX_TOKENS,
            defaults.naming_min_prefix_tokens,
            instance_id=instance_id,
        ),
        feature_max_iterations=_get_int(
            session,
            REASONING_FEATURE_MAX_ITERATIONS,
            defaults.feature_max_iterations,
            instance_id=instance_id,
        ),
        feature_membership_delta_threshold=_get_float(
            session,
            REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD,
            defaults.feature_membership_delta_threshold,
            instance_id=instance_id,
        ),
        feature_min_assignment_confidence=_get_float(
            session,
            REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE,
            defaults.feature_min_assignment_confidence,
            instance_id=instance_id,
        ),
    )


def load_observation_properties(
    session: Session,
    instance_id: Optional[int] = None,
) -> ObservationProperties:
    """Load typed observation-pipeline properties from app_config."""
    defaults = ObservationProperties()
    include_usage = (
        _read_property(session, OBSERVATIONS_INCLUDE_USAGE_QUERIES, instance_id=instance_id)
        or PROPERTY_DEFAULTS[OBSERVATIONS_INCLUDE_USAGE_QUERIES]
    ).strip().lower()
    if include_usage not in {"always", "auto", "never"}:
        include_usage = defaults.include_usage_queries

    return ObservationProperties(
        usage_lookback_months=_get_int(
            session,
            OBSERVATIONS_USAGE_LOOKBACK_MONTHS,
            defaults.usage_lookback_months,
            instance_id=instance_id,
        ),
        batch_size=_get_int(
            session,
            OBSERVATIONS_BATCH_SIZE,
            defaults.batch_size,
            instance_id=instance_id,
        ),
        include_usage_queries=include_usage,
        max_usage_queries_per_result=_get_int(
            session,
            OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT,
            defaults.max_usage_queries_per_result,
            instance_id=instance_id,
        ),
    )
