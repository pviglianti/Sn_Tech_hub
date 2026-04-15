"""Integration property registry and typed accessors.

This module centralizes tunable integration behavior so values can be moved to
an Admin UI (via ``app_config``) without touching execution code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlmodel import Session, select

from ..models import AppConfig

PropertyType = Literal["int", "float", "select", "multiselect", "string"]
PROPERTY_SCOPE_APPLICATION = "application_instance"

# ---------------------------------------------------------------------------
# Section ordering — controls UI grouping on the properties page
# ---------------------------------------------------------------------------

SECTION_GENERAL = "General"
SECTION_PREFLIGHT = "Assessment / Preflight"
SECTION_FETCH = "Integration / Fetch"
SECTION_REASONING = "Reasoning / Engines"
SECTION_OBSERVATIONS = "Observations"
SECTION_AI_ANALYSIS = "AI Analysis"
SECTION_AI_RUNTIME = "AI / LLM Runtime"

SECTION_ORDER: List[str] = [
    SECTION_GENERAL,
    SECTION_PREFLIGHT,
    SECTION_FETCH,
    SECTION_REASONING,
    SECTION_OBSERVATIONS,
    SECTION_AI_ANALYSIS,
    SECTION_AI_RUNTIME,
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

# Pull optimization keys
PULL_ORDER_DESC = "integration.pull.order_desc"
PULL_MAX_RECORDS = "integration.pull.max_records"
PULL_BAIL_UNCHANGED_RUN = "integration.pull.bail_unchanged_run"

# Reasoning engine keys
REASONING_US_MIN_SHARED_RECORDS = "reasoning.us.min_shared_records"
REASONING_US_NAME_SIMILARITY_MIN_TOKENS = "reasoning.us.name_similarity_min_tokens"
REASONING_US_INCLUDE_DEFAULT_SETS = "reasoning.us.include_default_sets"
REASONING_US_DEFAULT_SIGNAL_WEIGHT = "reasoning.us.default_signal_weight"
REASONING_TEMPORAL_GAP_THRESHOLD = "reasoning.temporal.gap_threshold_minutes"
REASONING_TEMPORAL_MIN_CLUSTER_SIZE = "reasoning.temporal.min_cluster_size"
REASONING_NAMING_MIN_CLUSTER_SIZE = "reasoning.naming.min_cluster_size"
REASONING_NAMING_MIN_PREFIX_TOKENS = "reasoning.naming.min_prefix_tokens"
REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH = "reasoning.dependency.max_transitive_depth"
REASONING_DEPENDENCY_MIN_CLUSTER_SIZE = "reasoning.dependency.min_cluster_size"
REASONING_FEATURE_MAX_ITERATIONS = "reasoning.feature.max_iterations"
REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD = "reasoning.feature.membership_delta_threshold"
REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE = "reasoning.feature.min_assignment_confidence"

# Observation pipeline keys
OBSERVATIONS_USAGE_LOOKBACK_MONTHS = "observations.usage_lookback_months"
OBSERVATIONS_BATCH_SIZE = "observations.batch_size"
OBSERVATIONS_INCLUDE_USAGE_QUERIES = "observations.include_usage_queries"
OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT = "observations.max_usage_queries_per_result"

# AI Analysis pipeline keys
AI_ANALYSIS_CLI_TIMEOUT = "ai_analysis.cli_timeout_seconds"
AI_ANALYSIS_BATCH_SIZE = "ai_analysis.batch_size"
AI_ANALYSIS_ENABLE_DEPTH_FIRST = "ai_analysis.enable_depth_first_traversal"
AI_ANALYSIS_CONTEXT_ENRICHMENT = "ai_analysis.context_enrichment"
AI_ANALYSIS_MAX_RABBIT_HOLE_DEPTH = "ai_analysis.max_rabbit_hole_depth"
AI_ANALYSIS_MAX_NEIGHBORS_PER_HOP = "ai_analysis.max_neighbors_per_hop"
AI_ANALYSIS_MIN_EDGE_WEIGHT = "ai_analysis.min_edge_weight_for_traversal"
AI_FEATURE_PASS_PLAN_JSON = "ai.feature.pass_plan_json"
AI_FEATURE_BUCKET_TAXONOMY_JSON = "ai.feature.bucket_taxonomy_json"

# Pipeline prompt integration keys
PIPELINE_USE_REGISTERED_PROMPTS = "pipeline.use_registered_prompts"

# AI / LLM runtime + budget keys
AI_RUNTIME_MODE = "ai.runtime.mode"
AI_RUNTIME_PROVIDER = "ai.runtime.provider"
AI_RUNTIME_MODEL = "ai.runtime.model"
AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS = "ai.runtime.model_catalog_timeout_seconds"
AI_RUNTIME_EXECUTION_STRATEGY = "ai.runtime.execution_strategy"
AI_RUNTIME_MAX_CONCURRENT_SESSIONS = "ai.runtime.max_concurrent_sessions"
AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD = "ai.budget.assessment_soft_limit_usd"
AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD = "ai.budget.assessment_hard_limit_usd"
AI_BUDGET_MONTHLY_HARD_LIMIT_USD = "ai.budget.monthly_hard_limit_usd"
AI_BUDGET_STOP_ON_HARD_LIMIT = "ai.budget.stop_on_hard_limit"
AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL = "ai.budget.max_input_tokens_per_call"
AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL = "ai.budget.max_output_tokens_per_call"

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
    dependency_max_transitive_depth: int = 3
    dependency_min_cluster_size: int = 2
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
class AIAnalysisProperties:
    """Typed AI analysis stage properties loaded from app_config."""
    batch_size: int = 1  # Artifacts per connected AI dispatch (swarm may override)
    cli_timeout_seconds: int = 900  # Per-artifact CLI dispatch timeout
    enable_depth_first: bool = True
    context_enrichment: str = "auto"  # "auto", "always", "never"
    max_rabbit_hole_depth: int = 10
    max_neighbors_per_hop: int = 20
    min_edge_weight_for_traversal: float = 2.0


@dataclass(frozen=True)
class AIFeatureProperties:
    """Typed AI-owned feature-stage orchestration properties."""
    pass_plan: List[Dict[str, Any]] = field(default_factory=list)
    bucket_taxonomy: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AIRuntimeProperties:
    """Typed AI runtime/provider/budget properties loaded from app_config."""
    mode: str = "local_subscription"
    provider: str = "openai"
    model: str = "gpt-5-mini"
    execution_strategy: str = "single"
    max_concurrent_sessions: int = 1
    assessment_soft_limit_usd: float = 10.0
    assessment_hard_limit_usd: float = 25.0
    monthly_hard_limit_usd: float = 200.0
    stop_on_hard_limit: bool = True
    max_input_tokens_per_call: int = 200000
    max_output_tokens_per_call: int = 40000


@dataclass(frozen=True)
class PipelinePromptProperties:
    """Typed pipeline prompt integration properties loaded from app_config."""
    use_registered_prompts: bool = False


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

DEFAULT_AI_FEATURE_PASS_PLAN: List[Dict[str, Any]] = [
    {"stage": "grouping", "pass_key": "structure", "label": "Structure"},
    {"stage": "grouping", "pass_key": "coverage", "label": "Coverage"},
    {"stage": "ai_refinement", "pass_key": "refine", "label": "Refine"},
    {"stage": "ai_refinement", "pass_key": "final_name", "label": "Final Naming"},
]

DEFAULT_AI_FEATURE_BUCKET_TAXONOMY: List[Dict[str, Any]] = [
    {
        "key": "form_fields",
        "label": "Form & Fields",
        "description": (
            "Leftover in-scope fields, dictionary entries, dictionary overrides, "
            "views, UI policies, and UI policy actions that do not clearly belong "
            "to an obvious solution feature."
        ),
    },
    {
        "key": "acl",
        "label": "ACL",
        "description": (
            "Remaining in-scope ACLs, roles, and security rules that are not part "
            "of a clearer functional feature."
        ),
    },
    {
        "key": "notifications",
        "label": "Notifications",
        "description": "Email actions, notifications, and related messaging artifacts.",
    },
    {
        "key": "scheduled_jobs",
        "label": "Scheduled Jobs",
        "description": "Scheduled scripts, jobs, and recurring maintenance automations.",
    },
    {
        "key": "integration_artifacts",
        "label": "Integration Artifacts",
        "description": "REST, SOAP, import, MID, and other integration-supporting artifacts.",
    },
    {
        "key": "data_policies_validations",
        "label": "Data Policies & Validations",
        "description": "Data policies, validations, and guardrail logic left after solution grouping.",
    },
]

AI_RUNTIME_MODE_OPTIONS: List[Tuple[str, str]] = [
    ("local_subscription", "Local Subscription (Recommended)"),
    ("api_key", "API Key"),
    ("disabled", "Disabled"),
]

AI_RUNTIME_PROVIDER_OPTIONS: List[Tuple[str, str]] = [
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("google_gemini", "Google Gemini"),
    ("deepseek", "DeepSeek"),
    ("openai_compatible_custom", "OpenAI-Compatible Custom"),
]

AI_RUNTIME_EXECUTION_STRATEGY_OPTIONS: List[Tuple[str, str]] = [
    ("single", "Single Session (one artifact at a time)"),
    ("swarm", "Swarm (multi-agent coordinated sessions)"),
]

PROPERTY_DEFAULTS: Dict[str, str] = {
    PREFLIGHT_CONCURRENT_TYPES: "version_history,customer_update_xml",
    GENERAL_DISPLAY_TIMEZONE: "America/New_York",
    FETCH_DEFAULT_BATCH_SIZE: "200",
    FETCH_INTER_BATCH_DELAY: "0.5",
    FETCH_REQUEST_TIMEOUT: "60",
    FETCH_MAX_BATCHES: "5000",
    # Pull optimization defaults
    PULL_ORDER_DESC: "true",
    PULL_MAX_RECORDS: "0",
    PULL_BAIL_UNCHANGED_RUN: "50",
    # Reasoning engine defaults
    REASONING_US_MIN_SHARED_RECORDS: "1",
    REASONING_US_NAME_SIMILARITY_MIN_TOKENS: "2",
    REASONING_US_INCLUDE_DEFAULT_SETS: "true",
    REASONING_US_DEFAULT_SIGNAL_WEIGHT: "0.3",
    REASONING_TEMPORAL_GAP_THRESHOLD: "60",
    REASONING_TEMPORAL_MIN_CLUSTER_SIZE: "2",
    REASONING_NAMING_MIN_CLUSTER_SIZE: "2",
    REASONING_NAMING_MIN_PREFIX_TOKENS: "2",
    REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH: "3",
    REASONING_DEPENDENCY_MIN_CLUSTER_SIZE: "2",
    REASONING_FEATURE_MAX_ITERATIONS: "3",
    REASONING_FEATURE_MEMBERSHIP_DELTA_THRESHOLD: "0.02",
    REASONING_FEATURE_MIN_ASSIGNMENT_CONFIDENCE: "0.6",
    # Observation pipeline defaults
    OBSERVATIONS_USAGE_LOOKBACK_MONTHS: "6",
    OBSERVATIONS_BATCH_SIZE: "10",
    OBSERVATIONS_INCLUDE_USAGE_QUERIES: "auto",
    OBSERVATIONS_MAX_USAGE_QUERIES_PER_RESULT: "2",
    # AI Analysis pipeline defaults
    AI_ANALYSIS_BATCH_SIZE: "1",
    AI_ANALYSIS_CLI_TIMEOUT: "900",
    AI_ANALYSIS_ENABLE_DEPTH_FIRST: "true",
    AI_ANALYSIS_CONTEXT_ENRICHMENT: "auto",
    AI_ANALYSIS_MAX_RABBIT_HOLE_DEPTH: "10",
    AI_ANALYSIS_MAX_NEIGHBORS_PER_HOP: "20",
    AI_ANALYSIS_MIN_EDGE_WEIGHT: "2.0",
    AI_FEATURE_PASS_PLAN_JSON: json.dumps(DEFAULT_AI_FEATURE_PASS_PLAN, sort_keys=True),
    AI_FEATURE_BUCKET_TAXONOMY_JSON: json.dumps(DEFAULT_AI_FEATURE_BUCKET_TAXONOMY, sort_keys=True),
    # Pipeline prompt integration defaults
    PIPELINE_USE_REGISTERED_PROMPTS: "false",
    # AI runtime + budget defaults
    AI_RUNTIME_MODE: "local_subscription",
    AI_RUNTIME_PROVIDER: "openai",
    AI_RUNTIME_MODEL: "gpt-5-mini",
    AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS: "8",
    AI_RUNTIME_EXECUTION_STRATEGY: "single",
    AI_RUNTIME_MAX_CONCURRENT_SESSIONS: "1",
    AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD: "10",
    AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD: "25",
    AI_BUDGET_MONTHLY_HARD_LIMIT_USD: "200",
    AI_BUDGET_STOP_ON_HARD_LIMIT: "true",
    AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL: "200000",
    AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL: "40000",
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
    PULL_ORDER_DESC: IntegrationPropertyDefinition(
        key=PULL_ORDER_DESC,
        label="Pull Order: Newest First",
        description=(
            "Order all data pulls newest-first (ORDERBYDESC). "
            "Enables bail-out to stop early once local counts match remote "
            "and consecutive unchanged upserts exceed the bail threshold. "
            "Recommended for large tables on re-pull scenarios."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[PULL_ORDER_DESC],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        options=BOOL_OPTIONS,
    ),
    PULL_MAX_RECORDS: IntegrationPropertyDefinition(
        key=PULL_MAX_RECORDS,
        label="Max Records Per Pull",
        description=(
            "Maximum total records to retrieve per pull run across all batches. "
            "Acts as an independent safety cap. When reached, the pull stops "
            "regardless of count or content gates. "
            "Set to 0 for unlimited (no cap). Default is 0 — classification "
            "accuracy requires complete supporting-data pulls (metadata_customization, "
            "customer_update_xml, version_history, update_sets)."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[PULL_MAX_RECORDS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        min_value=0,
        max_value=500000,
    ),
    PULL_BAIL_UNCHANGED_RUN: IntegrationPropertyDefinition(
        key=PULL_BAIL_UNCHANGED_RUN,
        label="Bail-Out: Consecutive Unchanged Upserts",
        description=(
            "Number of consecutive unchanged upserts required (along with the "
            "count gate) to trigger early bail-out during a re-pull. "
            "A lower value exits sooner; a higher value is more thorough."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[PULL_BAIL_UNCHANGED_RUN],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="all_sync",
        section=SECTION_FETCH,
        min_value=1,
        max_value=10000,
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
    REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH: IntegrationPropertyDefinition(
        key=REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH,
        label="Max Transitive Depth (Dependency)",
        description="Maximum hops for transitive dependency chain resolution.",
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=1,
        max_value=10,
    ),
    REASONING_DEPENDENCY_MIN_CLUSTER_SIZE: IntegrationPropertyDefinition(
        key=REASONING_DEPENDENCY_MIN_CLUSTER_SIZE,
        label="Min Cluster Size (Dependency)",
        description="Minimum number of customized artifacts to form a dependency cluster.",
        value_type="int",
        default=PROPERTY_DEFAULTS[REASONING_DEPENDENCY_MIN_CLUSTER_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="reasoning",
        section=SECTION_REASONING,
        min_value=2,
        max_value=50,
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
    # ----- AI Analysis properties -----
    AI_ANALYSIS_BATCH_SIZE: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_BATCH_SIZE,
        label="AI Analysis Batch Size",
        description=(
            "Number of artifacts to process per connected AI analysis dispatch. "
            "Use 1 for strict artifact-by-artifact review; raise for broader batches "
            "(swarm mode may override this upward)."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_BATCH_SIZE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        min_value=1,
        max_value=100,
    ),
    AI_ANALYSIS_CLI_TIMEOUT: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_CLI_TIMEOUT,
        label="AI Analysis CLI Timeout (seconds)",
        description=(
            "Maximum time in seconds to wait for each CLI session "
            "(Codex or Claude). In single mode this covers one artifact; "
            "in swarm mode it covers the entire batch. Increase if "
            "dispatches time out; decrease to fail fast on stuck sessions."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_CLI_TIMEOUT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        min_value=60,
        max_value=3600,
    ),
    AI_ANALYSIS_ENABLE_DEPTH_FIRST: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_ENABLE_DEPTH_FIRST,
        label="Enable Depth-First Traversal",
        description=(
            "When enabled, AI Analysis follows relationship-graph chains between "
            "customized artifacts. Turn this off to force the simpler sequential "
            "per-artifact analysis path."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_ENABLE_DEPTH_FIRST],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        options=BOOL_OPTIONS,
    ),
    AI_ANALYSIS_CONTEXT_ENRICHMENT: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_CONTEXT_ENRICHMENT,
        label="Context Enrichment Mode",
        description=(
            "When to query ServiceNow for additional context. "
            "auto = only when references detected and not cached locally. "
            "always = query for every artifact. never = local data only."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_CONTEXT_ENRICHMENT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        options=[
            ("auto", "Auto"),
            ("always", "Always"),
            ("never", "Never"),
        ],
    ),
    AI_ANALYSIS_MAX_RABBIT_HOLE_DEPTH: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_MAX_RABBIT_HOLE_DEPTH,
        label="Max Traversal Depth",
        description=(
            "Maximum number of relationship hops to follow away from the current "
            "seed artifact when depth-first traversal is enabled."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_MAX_RABBIT_HOLE_DEPTH],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        min_value=1,
        max_value=50,
    ),
    AI_ANALYSIS_MAX_NEIGHBORS_PER_HOP: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_MAX_NEIGHBORS_PER_HOP,
        label="Max Neighbors Per Hop",
        description=(
            "Maximum number of related customized artifacts to follow from one "
            "artifact at each traversal step when depth-first traversal is enabled. "
            "This limits breadth per hop, not total depth."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_MAX_NEIGHBORS_PER_HOP],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        min_value=1,
        max_value=100,
    ),
    AI_ANALYSIS_MIN_EDGE_WEIGHT: IntegrationPropertyDefinition(
        key=AI_ANALYSIS_MIN_EDGE_WEIGHT,
        label="Min Edge Weight for Traversal",
        description=(
            "Minimum relationship strength required before a related customization "
            "is followed when depth-first traversal is enabled."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[AI_ANALYSIS_MIN_EDGE_WEIGHT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_analysis",
        section=SECTION_AI_ANALYSIS,
        min_value=0.0,
        max_value=10.0,
    ),
    AI_FEATURE_PASS_PLAN_JSON: IntegrationPropertyDefinition(
        key=AI_FEATURE_PASS_PLAN_JSON,
        label="AI Feature Pass Plan (JSON)",
        description=(
            "Ordered pass plan for AI-owned feature grouping and refinement. "
            "Each item should declare stage and pass_key, with optional provider, model, "
            "and effort overrides for staged multi-LLM execution."
        ),
        value_type="string",
        default=PROPERTY_DEFAULTS[AI_FEATURE_PASS_PLAN_JSON],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_feature_pipeline",
        section=SECTION_AI_ANALYSIS,
    ),
    AI_FEATURE_BUCKET_TAXONOMY_JSON: IntegrationPropertyDefinition(
        key=AI_FEATURE_BUCKET_TAXONOMY_JSON,
        label="AI Bucket Taxonomy (JSON)",
        description=(
            "Bucket feature definitions used only after solution-first grouping. "
            "These define leftover in-scope categories such as Form & Fields or ACL."
        ),
        value_type="string",
        default=PROPERTY_DEFAULTS[AI_FEATURE_BUCKET_TAXONOMY_JSON],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_feature_pipeline",
        section=SECTION_AI_ANALYSIS,
    ),
    # ----- Pipeline prompt integration -----
    PIPELINE_USE_REGISTERED_PROMPTS: IntegrationPropertyDefinition(
        key=PIPELINE_USE_REGISTERED_PROMPTS,
        label="Use Registered MCP Prompts",
        description=(
            "When enabled, pipeline AI handlers call registered MCP prompt "
            "handlers (artifact_analyzer, relationship_tracer, technical_architect, report_writer) "
            "to build rich context instead of storing simple JSON summaries."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[PIPELINE_USE_REGISTERED_PROMPTS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="pipeline",
        section=SECTION_AI_ANALYSIS,
        options=BOOL_OPTIONS,
    ),
    # ----- AI runtime + budget properties -----
    AI_RUNTIME_MODE: IntegrationPropertyDefinition(
        key=AI_RUNTIME_MODE,
        label="AI Runtime Mode",
        description=(
            "How AI runs are executed. local_subscription uses a local MCP-capable "
            "client session (no API key in this app). api_key uses server-side API "
            "credentials for headless automation. disabled blocks AI stage execution."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[AI_RUNTIME_MODE],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        options=AI_RUNTIME_MODE_OPTIONS,
    ),
    AI_RUNTIME_PROVIDER: IntegrationPropertyDefinition(
        key=AI_RUNTIME_PROVIDER,
        label="AI Provider",
        description=(
            "Target LLM provider used in API mode. This does not guarantee full "
            "compatibility by itself; provider adapters and tool-calling support "
            "must also exist in the app runtime."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[AI_RUNTIME_PROVIDER],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        options=AI_RUNTIME_PROVIDER_OPTIONS,
    ),
    AI_RUNTIME_MODEL: IntegrationPropertyDefinition(
        key=AI_RUNTIME_MODEL,
        label="AI Model ID",
        description=(
            "Exact model identifier used for AI runs. The AI Setup Wizard can fetch "
            "provider-specific suggestions. Saving the literal value 'custom' tells "
            "provider adapters to use their own default model."
        ),
        value_type="string",
        default=PROPERTY_DEFAULTS[AI_RUNTIME_MODEL],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
    ),
    AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS: IntegrationPropertyDefinition(
        key=AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS,
        label="AI Model Catalog Timeout (Seconds)",
        description=(
            "HTTP timeout used when the AI Setup Wizard fetches live provider model "
            "catalogs."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=2,
        max_value=60,
    ),
    AI_RUNTIME_EXECUTION_STRATEGY: IntegrationPropertyDefinition(
        key=AI_RUNTIME_EXECUTION_STRATEGY,
        label="AI Execution Strategy",
        description=(
            "How AI dispatches run. 'single' sends one artifact per CLI call. "
            "'swarm' sends a batch of artifacts and tells the CLI to use "
            "multi-agent coordination (Codex subagents / Claude agent teams)."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[AI_RUNTIME_EXECUTION_STRATEGY],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        options=AI_RUNTIME_EXECUTION_STRATEGY_OPTIONS,
    ),
    AI_RUNTIME_MAX_CONCURRENT_SESSIONS: IntegrationPropertyDefinition(
        key=AI_RUNTIME_MAX_CONCURRENT_SESSIONS,
        label="Max Concurrent AI Sessions",
        description=(
            "Max parallel workers in swarm mode. Controls how many subagents "
            "the CLI can run simultaneously. Ignored in 'single' mode. "
            "Higher values = faster but more API budget."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_RUNTIME_MAX_CONCURRENT_SESSIONS],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=1,
        max_value=10,
    ),
    AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD: IntegrationPropertyDefinition(
        key=AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD,
        label="Assessment Soft Budget (USD)",
        description=(
            "Warning threshold per assessment when using API mode. Exceeding this "
            "limit should surface warnings but does not have to stop execution."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=0.0,
        max_value=100000.0,
    ),
    AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD: IntegrationPropertyDefinition(
        key=AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD,
        label="Assessment Hard Budget (USD)",
        description=(
            "Absolute per-assessment budget cap for API mode. When stop-on-hard-limit "
            "is enabled, the app should stop AI execution once this threshold is hit."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=0.0,
        max_value=100000.0,
    ),
    AI_BUDGET_MONTHLY_HARD_LIMIT_USD: IntegrationPropertyDefinition(
        key=AI_BUDGET_MONTHLY_HARD_LIMIT_USD,
        label="Monthly Hard Budget (USD)",
        description=(
            "Monthly cross-assessment API spend cap. Use this as a tenant-level "
            "safety valve in addition to per-assessment limits."
        ),
        value_type="float",
        default=PROPERTY_DEFAULTS[AI_BUDGET_MONTHLY_HARD_LIMIT_USD],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=0.0,
        max_value=1000000.0,
    ),
    AI_BUDGET_STOP_ON_HARD_LIMIT: IntegrationPropertyDefinition(
        key=AI_BUDGET_STOP_ON_HARD_LIMIT,
        label="Stop On Hard Budget Limit",
        description=(
            "When enabled, AI runs in API mode stop immediately once hard budget "
            "limits are reached."
        ),
        value_type="select",
        default=PROPERTY_DEFAULTS[AI_BUDGET_STOP_ON_HARD_LIMIT],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        options=BOOL_OPTIONS,
    ),
    AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL: IntegrationPropertyDefinition(
        key=AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL,
        label="Max Input Tokens Per Call",
        description=(
            "Hard guardrail for prompt/input size in API mode. Prevents accidental "
            "high-cost requests caused by oversized payloads."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=1000,
        max_value=2000000,
    ),
    AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL: IntegrationPropertyDefinition(
        key=AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL,
        label="Max Output Tokens Per Call",
        description=(
            "Hard guardrail for completion/output size in API mode. Keeps long "
            "responses from driving unexpected cost spikes."
        ),
        value_type="int",
        default=PROPERTY_DEFAULTS[AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL],
        scope=PROPERTY_SCOPE_APPLICATION,
        applies_to="ai_runtime",
        section=SECTION_AI_RUNTIME,
        min_value=256,
        max_value=2000000,
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
    if definition.value_type == "string":
        return raw_value

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
    if definition.value_type == "string":
        return str(parsed)
    if definition.value_type == "select":
        return str(parsed)
    if definition.value_type == "multiselect":
        return ",".join(parsed) if isinstance(parsed, list) else str(parsed)
    if definition.value_type == "int":
        return str(int(parsed))
    return f"{float(parsed):g}"


def _inherited_value_for_instance_scope(
    session: Session,
    key: str,
    definition: IntegrationPropertyDefinition,
) -> str:
    """Return the value an instance would inherit without a local override."""
    global_row = _read_row_exact(session, key, None)
    if global_row and global_row.value not in (None, ""):
        return str(global_row.value).strip()
    return definition.default


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
        instance_override_value = (
            str(scoped_row.value).strip() if scoped_row and scoped_row.value is not None else None
        )
        global_value = str(global_row.value).strip() if global_row and global_row.value is not None else None

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
            "instance_override_value": instance_override_value,
            "global_value": global_value,
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
        if instance_id is not None:
            inherited_value = _inherited_value_for_instance_scope(session, key, definition)
            if normalized_value == inherited_value:
                if row:
                    session.delete(row)
                continue
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


def load_pull_order_desc(session: Session, instance_id: Optional[int] = None) -> bool:
    """Return True if pulls should use newest-first ordering (ORDERBYDESC).

    Defaults to True to enable bail-out optimization on re-pull scenarios.
    """
    raw = _read_property(session, PULL_ORDER_DESC, instance_id=instance_id)
    if raw is None or raw == "":
        raw = PROPERTY_DEFAULTS[PULL_ORDER_DESC]
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_pull_max_records(session: Session, instance_id: Optional[int] = None) -> int:
    """Return the maximum total records to retrieve per pull run.

    Acts as an independent safety cap, firing regardless of count or content gates.
    Defaults to 5000.
    """
    return _get_int(session, PULL_MAX_RECORDS, int(PROPERTY_DEFAULTS[PULL_MAX_RECORDS]), instance_id=instance_id)


def load_pull_bail_unchanged_run(session: Session, instance_id: Optional[int] = None) -> int:
    """Return the consecutive-unchanged upserts threshold for bail-out.

    When this many consecutive upserts produce no data change (and the count gate
    is also met), the pull exits early. Defaults to 50.
    """
    return _get_int(session, PULL_BAIL_UNCHANGED_RUN, int(PROPERTY_DEFAULTS[PULL_BAIL_UNCHANGED_RUN]), instance_id=instance_id)


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
        dependency_max_transitive_depth=_get_int(
            session,
            REASONING_DEPENDENCY_MAX_TRANSITIVE_DEPTH,
            defaults.dependency_max_transitive_depth,
            instance_id=instance_id,
        ),
        dependency_min_cluster_size=_get_int(
            session,
            REASONING_DEPENDENCY_MIN_CLUSTER_SIZE,
            defaults.dependency_min_cluster_size,
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


def load_ai_analysis_properties(
    session: Session,
    instance_id: Optional[int] = None,
) -> AIAnalysisProperties:
    """Load typed AI analysis properties from app_config."""
    defaults = AIAnalysisProperties()
    enable_depth_first = (
        _read_property(session, AI_ANALYSIS_ENABLE_DEPTH_FIRST, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_ANALYSIS_ENABLE_DEPTH_FIRST]
    ).strip().lower()
    context_enrichment = (
        _read_property(session, AI_ANALYSIS_CONTEXT_ENRICHMENT, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_ANALYSIS_CONTEXT_ENRICHMENT]
    ).strip().lower()
    if enable_depth_first not in {"1", "true", "yes", "y", "on", "0", "false", "no", "n", "off"}:
        enable_depth_first = PROPERTY_DEFAULTS[AI_ANALYSIS_ENABLE_DEPTH_FIRST]
    if context_enrichment not in {"auto", "always", "never"}:
        context_enrichment = defaults.context_enrichment

    return AIAnalysisProperties(
        batch_size=_get_int(
            session,
            AI_ANALYSIS_BATCH_SIZE,
            defaults.batch_size,
            instance_id=instance_id,
        ),
        cli_timeout_seconds=_get_int(
            session,
            AI_ANALYSIS_CLI_TIMEOUT,
            defaults.cli_timeout_seconds,
            instance_id=instance_id,
        ),
        enable_depth_first=enable_depth_first in {"1", "true", "yes", "y", "on"},
        context_enrichment=context_enrichment,
        max_rabbit_hole_depth=_get_int(
            session,
            AI_ANALYSIS_MAX_RABBIT_HOLE_DEPTH,
            defaults.max_rabbit_hole_depth,
            instance_id=instance_id,
        ),
        max_neighbors_per_hop=_get_int(
            session,
            AI_ANALYSIS_MAX_NEIGHBORS_PER_HOP,
            defaults.max_neighbors_per_hop,
            instance_id=instance_id,
        ),
        min_edge_weight_for_traversal=_get_float(
            session,
            AI_ANALYSIS_MIN_EDGE_WEIGHT,
            defaults.min_edge_weight_for_traversal,
            instance_id=instance_id,
        ),
    )


def load_ai_feature_properties(
    session: Session,
    instance_id: Optional[int] = None,
) -> AIFeatureProperties:
    """Load AI-owned feature-stage orchestration properties from app_config."""
    pass_plan_raw = (
        _read_property(session, AI_FEATURE_PASS_PLAN_JSON, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_FEATURE_PASS_PLAN_JSON]
    ).strip()
    bucket_taxonomy_raw = (
        _read_property(session, AI_FEATURE_BUCKET_TAXONOMY_JSON, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_FEATURE_BUCKET_TAXONOMY_JSON]
    ).strip()

    try:
        pass_plan = json.loads(pass_plan_raw)
        if not isinstance(pass_plan, list):
            raise ValueError("pass plan must be a list")
    except Exception:
        pass_plan = list(DEFAULT_AI_FEATURE_PASS_PLAN)

    try:
        bucket_taxonomy = json.loads(bucket_taxonomy_raw)
        if not isinstance(bucket_taxonomy, list):
            raise ValueError("bucket taxonomy must be a list")
    except Exception:
        bucket_taxonomy = list(DEFAULT_AI_FEATURE_BUCKET_TAXONOMY)

    normalized_pass_plan: List[Dict[str, Any]] = []
    for item in pass_plan:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage") or "").strip().lower()
        pass_key = str(item.get("pass_key") or "").strip().lower()
        if not stage or not pass_key:
            continue
        normalized_pass_plan.append(
            {
                "stage": stage,
                "pass_key": pass_key,
                "label": str(item.get("label") or pass_key.replace("_", " ").title()).strip(),
                "provider": str(item.get("provider") or "").strip().lower() or None,
                "model": str(item.get("model") or "").strip() or None,
                "effort": str(item.get("effort") or "").strip().lower() or None,
            }
        )
    if not normalized_pass_plan:
        normalized_pass_plan = list(DEFAULT_AI_FEATURE_PASS_PLAN)

    normalized_bucket_taxonomy: List[Dict[str, Any]] = []
    for item in bucket_taxonomy:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower()
        label = str(item.get("label") or "").strip()
        if not key or not label:
            continue
        normalized_bucket_taxonomy.append(
            {
                "key": key,
                "label": label,
                "description": str(item.get("description") or "").strip(),
            }
        )
    if not normalized_bucket_taxonomy:
        normalized_bucket_taxonomy = list(DEFAULT_AI_FEATURE_BUCKET_TAXONOMY)

    return AIFeatureProperties(
        pass_plan=normalized_pass_plan,
        bucket_taxonomy=normalized_bucket_taxonomy,
    )


def load_ai_runtime_model_catalog_timeout_seconds(
    session: Session,
    instance_id: Optional[int] = None,
) -> int:
    """Return timeout used for live provider model-catalog fetches."""
    return _get_int(
        session,
        AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS,
        int(PROPERTY_DEFAULTS[AI_RUNTIME_MODEL_CATALOG_TIMEOUT_SECONDS]),
        instance_id=instance_id,
    )


def load_pipeline_prompt_properties(
    session: Session,
    instance_id: Optional[int] = None,
) -> PipelinePromptProperties:
    """Load typed pipeline prompt integration properties from app_config."""
    raw = (
        _read_property(session, PIPELINE_USE_REGISTERED_PROMPTS, instance_id=instance_id)
        or PROPERTY_DEFAULTS[PIPELINE_USE_REGISTERED_PROMPTS]
    ).strip().lower()
    return PipelinePromptProperties(
        use_registered_prompts=raw in ("true", "1", "yes"),
    )


def load_ai_runtime_properties(
    session: Session,
    instance_id: Optional[int] = None,
) -> AIRuntimeProperties:
    """Load typed AI runtime/provider/budget properties from app_config."""
    defaults = AIRuntimeProperties()

    mode = (
        _read_property(session, AI_RUNTIME_MODE, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_RUNTIME_MODE]
    ).strip().lower()
    if mode not in {opt[0] for opt in AI_RUNTIME_MODE_OPTIONS}:
        mode = defaults.mode

    provider = (
        _read_property(session, AI_RUNTIME_PROVIDER, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_RUNTIME_PROVIDER]
    ).strip().lower()
    if provider not in {opt[0] for opt in AI_RUNTIME_PROVIDER_OPTIONS}:
        provider = defaults.provider

    model = (
        _read_property(session, AI_RUNTIME_MODEL, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_RUNTIME_MODEL]
    ).strip()
    if not model:
        model = defaults.model

    stop_on_hard_limit_raw = (
        _read_property(session, AI_BUDGET_STOP_ON_HARD_LIMIT, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_BUDGET_STOP_ON_HARD_LIMIT]
    ).strip().lower()
    stop_on_hard_limit = stop_on_hard_limit_raw in {"1", "true", "yes", "y", "on"}

    execution_strategy = (
        _read_property(session, AI_RUNTIME_EXECUTION_STRATEGY, instance_id=instance_id)
        or PROPERTY_DEFAULTS[AI_RUNTIME_EXECUTION_STRATEGY]
    ).strip().lower()
    if execution_strategy not in {opt[0] for opt in AI_RUNTIME_EXECUTION_STRATEGY_OPTIONS}:
        execution_strategy = defaults.execution_strategy

    max_concurrent_sessions = max(
        1,
        _get_int(
            session,
            AI_RUNTIME_MAX_CONCURRENT_SESSIONS,
            defaults.max_concurrent_sessions,
            instance_id=instance_id,
        ),
    )

    return AIRuntimeProperties(
        mode=mode,
        provider=provider,
        model=model,
        execution_strategy=execution_strategy,
        max_concurrent_sessions=max_concurrent_sessions,
        assessment_soft_limit_usd=max(
            0.0,
            _get_float(
                session,
                AI_BUDGET_ASSESSMENT_SOFT_LIMIT_USD,
                defaults.assessment_soft_limit_usd,
                instance_id=instance_id,
            ),
        ),
        assessment_hard_limit_usd=max(
            0.0,
            _get_float(
                session,
                AI_BUDGET_ASSESSMENT_HARD_LIMIT_USD,
                defaults.assessment_hard_limit_usd,
                instance_id=instance_id,
            ),
        ),
        monthly_hard_limit_usd=max(
            0.0,
            _get_float(
                session,
                AI_BUDGET_MONTHLY_HARD_LIMIT_USD,
                defaults.monthly_hard_limit_usd,
                instance_id=instance_id,
            ),
        ),
        stop_on_hard_limit=stop_on_hard_limit,
        max_input_tokens_per_call=max(
            1,
            _get_int(
                session,
                AI_BUDGET_MAX_INPUT_TOKENS_PER_CALL,
                defaults.max_input_tokens_per_call,
                instance_id=instance_id,
            ),
        ),
        max_output_tokens_per_call=max(
            1,
            _get_int(
                session,
                AI_BUDGET_MAX_OUTPUT_TOKENS_PER_CALL,
                defaults.max_output_tokens_per_call,
                instance_id=instance_id,
            ),
        ),
    )
