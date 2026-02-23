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

SECTION_ORDER: List[str] = [SECTION_GENERAL, SECTION_PREFLIGHT, SECTION_FETCH]

# ---------------------------------------------------------------------------
# Property keys
# ---------------------------------------------------------------------------

GENERAL_DISPLAY_TIMEZONE = "general.display_timezone"

PREFLIGHT_CONCURRENT_TYPES = "preflight.concurrent_types"

FETCH_DEFAULT_BATCH_SIZE = "integration.fetch.default_batch_size"
FETCH_INTER_BATCH_DELAY = "integration.fetch.inter_batch_delay"
FETCH_REQUEST_TIMEOUT = "integration.fetch.request_timeout"
FETCH_MAX_BATCHES = "integration.fetch.max_batches"

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

PROPERTY_DEFAULTS: Dict[str, str] = {
    PREFLIGHT_CONCURRENT_TYPES: "version_history,customer_update_xml",
    GENERAL_DISPLAY_TIMEZONE: "America/New_York",
    FETCH_DEFAULT_BATCH_SIZE: "200",
    FETCH_INTER_BATCH_DELAY: "0.5",
    FETCH_REQUEST_TIMEOUT: "60",
    FETCH_MAX_BATCHES: "5000",
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
