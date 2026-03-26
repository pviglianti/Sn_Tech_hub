# models.py - Data Model for Tech Assessment Hub
# Hierarchy: Instance → Assessment → Scan → ScanResult → Feature
# Enhanced with origin_type classification, dispositions, and feature grouping

from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import Optional, List
from enum import Enum
from sqlalchemy import UniqueConstraint


# ============================================
# ENUMS (Choice fields)
# ============================================

class AuthType(str, Enum):
    """Authentication method for ServiceNow instances"""
    basic = "basic"
    oauth = "oauth"


class ConnectionStatus(str, Enum):
    connected = "connected"
    failed = "failed"
    untested = "untested"


class AssessmentState(str, Enum):
    """Assessment lifecycle states"""
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class PipelineStage(str, Enum):
    """Assessment reasoning pipeline stages after scans complete."""
    scans = "scans"
    ai_analysis = "ai_analysis"
    engines = "engines"
    observations = "observations"
    review = "review"
    grouping = "grouping"
    ai_refinement = "ai_refinement"
    recommendations = "recommendations"
    report = "report"
    complete = "complete"


class AssessmentType(str, Enum):
    """Type of assessment - determines what can be selected"""
    global_app = "global_app"          # Pick from known ITSM apps (Incident, Change, etc.)
    table = "table"                    # Pick one or more tables
    plugin = "plugin"                  # Pick plugins/packages
    platform_global = "platform_global" # Platform-wide configs not tied to specific app
    scoped_app = "scoped_app"          # Future: scoped applications


class ScanStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ScanType(str, Enum):
    """Types of scans/queries that can be run"""
    metadata = "metadata"              # Legacy metadata scan
    metadata_index = "metadata_index"  # Rules-driven sys_metadata scan
    update_xml = "update_xml"          # sys_update_xml scan
    metadata_customization = "metadata_customization"
    version_history = "version_history"
    artifact_detail = "artifact_detail"
    business_rules = "business_rules"
    script_includes = "script_includes"
    client_scripts = "client_scripts"
    ui_policies = "ui_policies"
    ui_policy_actions = "ui_policy_actions"
    ui_actions = "ui_actions"
    dictionary = "dictionary"          # sys_dictionary
    dictionary_override = "dictionary_override"
    tables = "tables"                  # sys_db_object
    update_sets = "update_sets"
    choices = "choices"                # sys_choice
    acls = "acls"                      # sys_security_acl
    notifications = "notifications"    # sysevent_email_action
    scheduled_jobs = "scheduled_jobs"  # sysauto_script
    data_policies = "data_policies"    # sys_data_policy2
    code_search = "code_search"


class OriginType(str, Enum):
    """Classification of record origin (from Assessment_Guide_Script_v3)"""
    modified_ootb = "modified_ootb"           # OOTB record that's been customized
    ootb_untouched = "ootb_untouched"         # Pristine OOTB record
    net_new_customer = "net_new_customer"     # Customer-created from scratch
    unknown_no_history = "unknown_no_history" # No tracking data available
    unknown = "unknown"
    pending_classification = "pending_classification"


class HeadOwner(str, Enum):
    """Owner of the current/head version"""
    customer = "Customer"
    store_upgrade = "Store/Upgrade"
    unknown = "Unknown"


class ReviewStatus(str, Enum):
    """Review status for scan results"""
    pending_review = "pending_review"
    review_in_progress = "review_in_progress"
    reviewed = "reviewed"


class Disposition(str, Enum):
    """Disposition/recommendation for scan results"""
    remove = "remove"
    keep_as_is = "keep_as_is"
    keep_and_refactor = "keep_and_refactor"
    needs_analysis = "needs_analysis"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingCategory(str, Enum):
    customization = "customization"
    code_quality = "code_quality"
    security = "security"
    performance = "performance"
    upgrade_risk = "upgrade_risk"
    best_practice = "best_practice"


class GroupingSignalType(str, Enum):
    """Signal types used by the feature grouping algorithm."""
    update_set = "update_set"
    table_affinity = "table_affinity"
    naming_convention = "naming_convention"
    code_reference = "code_reference"
    structural_parent_child = "structural_parent_child"
    temporal_proximity = "temporal_proximity"
    reference_field = "reference_field"
    application_package = "application_package"
    ai_judgment = "ai_judgment"


class DataPullType(str, Enum):
    """Types of data that can be pulled from an instance"""
    update_sets = "update_sets"
    customer_update_xml = "customer_update_xml"
    version_history = "version_history"
    metadata_customization = "metadata_customization"
    app_file_types = "app_file_types"
    plugins = "plugins"
    plugin_view = "plugin_view"
    scopes = "scopes"
    packages = "packages"  # sys_package - renamed from store_apps
    applications = "applications"
    sys_db_object = "sys_db_object"


class DataPullStatus(str, Enum):
    """Status of a data pull operation"""
    idle = "idle"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class JobRunStatus(str, Enum):
    """Durable status for background integration jobs."""
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


# ============================================
# TABLE: Instance (ServiceNow instances)
# ============================================

class Instance(SQLModel, table=True):
    """ServiceNow instance connection configuration"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)  # Display name: "DEV", "PROD", etc.
    url: str  # https://xxx.service-now.com
    auth_type: str = Field(default=AuthType.basic.value)  # "basic" or "oauth"
    username: str
    password_encrypted: str  # Encrypted password
    # OAuth fields (used when auth_type == "oauth")
    client_id: Optional[str] = None
    client_secret_encrypted: Optional[str] = None
    oauth_access_token_encrypted: Optional[str] = None
    oauth_refresh_token_encrypted: Optional[str] = None
    oauth_token_expires_at: Optional[datetime] = None
    is_active: bool = True
    connection_status: ConnectionStatus = ConnectionStatus.untested
    last_connected: Optional[datetime] = None
    instance_version: Optional[str] = None  # e.g., "Tokyo", "Utah", "Vancouver"
    company: Optional[str] = None
    inventory_json: Optional[str] = None
    task_counts_json: Optional[str] = None
    update_set_counts_json: Optional[str] = None
    sys_update_xml_counts_json: Optional[str] = None
    sys_update_xml_total: Optional[int] = None
    sys_metadata_customization_count: Optional[int] = None
    instance_dob: Optional[datetime] = None
    instance_age_years: Optional[float] = None
    metrics_last_refreshed_at: Optional[datetime] = None
    custom_scoped_app_count_x: Optional[int] = None
    custom_scoped_app_count_u: Optional[int] = None
    custom_table_count_u: Optional[int] = None
    custom_table_count_x: Optional[int] = None
    custom_field_count_u: Optional[int] = None
    custom_field_count_x: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    assessments: List["Assessment"] = Relationship(back_populates="instance")
    update_sets: List["UpdateSet"] = Relationship(back_populates="instance")
    plugins: List["InstancePlugin"] = Relationship(back_populates="instance")
    plugin_views: List["PluginView"] = Relationship(back_populates="instance")
    version_history: List["VersionHistory"] = Relationship(back_populates="instance")
    metadata_customizations: List["MetadataCustomization"] = Relationship(back_populates="instance")
    customer_update_xmls: List["CustomerUpdateXML"] = Relationship(back_populates="instance")
    data_pulls: List["InstanceDataPull"] = Relationship(back_populates="instance")
    app_file_types: List["InstanceAppFileType"] = Relationship(back_populates="instance")
    scopes: List["Scope"] = Relationship(back_populates="instance")
    packages: List["Package"] = Relationship(back_populates="instance")
    applications: List["Application"] = Relationship(back_populates="instance")
    table_definitions: List["TableDefinition"] = Relationship(back_populates="instance")
    facts: List["Fact"] = Relationship(back_populates="instance")
    job_runs: List["JobRun"] = Relationship(back_populates="instance")

    # ServiceNow mirror table relationships
    sn_table_registries: List["SnTableRegistry"] = Relationship(back_populates="instance")
    sn_ingestion_states: List["SnIngestionState"] = Relationship(back_populates="instance")
    sn_job_logs: List["SnJobLog"] = Relationship(back_populates="instance")
    sn_custom_table_requests: List["SnCustomTableRequest"] = Relationship(back_populates="instance")


# ============================================
# TABLE: Assessment (parent container)
# Number: ASMT0000001
# ============================================

class Assessment(SQLModel, table=True):
    """Assessment configuration - groups multiple scans together"""
    id: Optional[int] = Field(default=None, primary_key=True)
    number: str = Field(index=True, unique=True)  # ASMT0000001
    name: str = Field(index=True)
    description: Optional[str] = None

    # Instance reference
    instance_id: int = Field(foreign_key="instance.id")

    # Assessment type and state
    assessment_type: AssessmentType = AssessmentType.global_app
    state: AssessmentState = AssessmentState.pending

    # Target selection (based on assessment_type)
    # For global_app: sys_id of selected GlobalApp
    target_app_id: Optional[int] = Field(default=None, foreign_key="global_app.id")
    # For table type: JSON array of table names ["incident", "change_request"]
    target_tables_json: Optional[str] = None
    # For plugin type: JSON array of plugin sys_ids
    target_plugins_json: Optional[str] = None

    # App file classes to include in scans (JSON array)
    # e.g., ["sys_script", "sys_script_include", "sys_script_client", "sys_ui_policy"]
    app_file_classes_json: Optional[str] = None

    # Scope filter
    scope_filter: str = "global"  # global, scoped, all

    # Timestamps
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    pipeline_stage: PipelineStage = PipelineStage.scans
    pipeline_stage_updated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Created by
    created_by: Optional[str] = None

    # Relationships
    instance: Instance = Relationship(back_populates="assessments")
    target_app: Optional["GlobalApp"] = Relationship(back_populates="assessments")
    scans: List["Scan"] = Relationship(back_populates="assessment")
    features: List["Feature"] = Relationship(back_populates="assessment")
    general_recommendations: List["GeneralRecommendation"] = Relationship(back_populates="assessment")

    @property
    def records_customized(self) -> int:
        """Count total customized records across all scans."""
        return sum(scan.records_customized for scan in self.scans)

    @property
    def total_findings(self) -> int:
        """Count total findings across all scans"""
        return sum(len(scan.results) for scan in self.scans)


# ============================================
# TABLE: GlobalApp (Known ITSM Apps in Global Scope)
# ============================================

class GlobalApp(SQLModel, table=True):
    """Known global ITSM applications for assessment targeting"""
    __tablename__ = "global_app"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)  # "Incident", "Change", "Problem"
    label: str  # Display label
    description: Optional[str] = None

    # Core tables for this app (JSON array)
    # e.g., ["incident"] or ["change_request", "change_task"]
    core_tables_json: str

    # Parent table if applicable (e.g., "task" for Incident)
    parent_table: Optional[str] = None

    # Plugin/package references (JSON array of plugin sys_ids/names)
    plugins_json: Optional[str] = None

    # Keywords for 123TEXTQUERY321 search
    keywords_json: Optional[str] = None  # ["incident", "inc"]

    is_active: bool = True
    display_order: int = 0

    # Relationships
    assessments: List[Assessment] = Relationship(back_populates="target_app")


# ============================================
# TABLE: AppFileClass (Application File Classes)
# ============================================

class AppFileClass(SQLModel, table=True):
    """Application file classes that can be scanned"""
    __tablename__ = "app_file_class"

    id: Optional[int] = Field(default=None, primary_key=True)
    sys_class_name: str = Field(unique=True, index=True)  # sys_script, sys_script_include
    label: str  # "Business Rule", "Script Include"
    description: Optional[str] = None

    # The field that references the target table (from TABLE_FIELD_MAP)
    # e.g., "collection" for sys_script, "table" for sys_ui_action
    target_table_field: Optional[str] = None

    # Is this a code artifact (has script field)?
    has_script: bool = True

    # Importance for assessments
    is_important: bool = True  # User can toggle
    display_order: int = 0
    is_active: bool = True


# ============================================
# TABLE: InstanceAppFileType (sys_app_file_type cached)
# ============================================

class InstanceAppFileType(SQLModel, table=True):
    """Per-instance application file type definitions from sys_app_file_type."""
    __tablename__ = "instance_app_file_type"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_instance_app_file_type_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow identity
    sn_sys_id: str = Field(index=True)
    sys_class_name: Optional[str] = Field(default=None, index=True)  # Usually the metadata sys_class_name (e.g., sys_script)
    name: Optional[str] = None
    label: Optional[str] = None
    is_available_for_assessment: bool = Field(default=True, index=True)
    is_default_for_assessment: bool = Field(default=False, index=True)

    # Relationship fields from sys_app_file_type
    source_table: Optional[str] = None  # sys_source_table.value (sys_db_object.sys_id)
    source_table_name: Optional[str] = None  # sys_source_table.display_value (table name)
    parent_table: Optional[str] = None  # sys_parent_table.value (sys_db_object.sys_id)
    parent_table_name: Optional[str] = None  # sys_parent_table.display_value
    source_field: Optional[str] = None  # sys_source_field
    parent_field: Optional[str] = None  # sys_parent_field
    use_parent_scope: Optional[bool] = None  # sys_use_parent_scope
    type: Optional[str] = None  # sys_type
    priority: Optional[int] = None
    children_provider_class: Optional[str] = None  # sys_children_provider_class

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_mod_count: Optional[int] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="app_file_types")


# ============================================
# TABLE: Scan (individual query/scan type)
# ============================================

class Scan(SQLModel, table=True):
    """Individual scan/query execution within an assessment"""
    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    scan_type: ScanType
    name: str
    description: Optional[str] = None
    status: ScanStatus = ScanStatus.pending
    cancel_requested: bool = False
    cancel_requested_at: Optional[datetime] = None

    # Query configuration
    encoded_query: Optional[str] = None  # ServiceNow encoded query
    target_table: Optional[str] = None   # Which SN table to query
    query_params_json: Optional[str] = None  # Additional parameters as JSON

    # Results tracking
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    records_found: int = 0
    records_customized: int = 0
    records_customer_customized: int = 0
    records_ootb_modified: int = 0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    assessment: Assessment = Relationship(back_populates="scans")
    results: List["ScanResult"] = Relationship(back_populates="scan")
    customizations: List["Customization"] = Relationship(back_populates="scan")


# ============================================
# TABLE: ScanResult (findings / application files)
# Enhanced with origin_type, disposition, review status
# ============================================

class ScanResult(SQLModel, table=True):
    """Individual result/finding from a scan - represents an application file"""
    __tablename__ = "scan_result"

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_id: int = Field(foreign_key="scan.id", index=True)

    # ServiceNow artifact identification
    sys_id: str = Field(index=True)  # ServiceNow sys_id
    table_name: str  # sys_script_include, sys_script, etc.
    name: str  # Artifact name
    display_value: Optional[str] = None

    # Metadata classification (from sys_metadata)
    sys_class_name: Optional[str] = None
    sys_update_name: Optional[str] = None  # For version tracking
    sys_scope: Optional[str] = None
    sys_package: Optional[str] = None

    # Target table (for class-specific artifacts)
    meta_target_table: Optional[str] = None  # collection/table field value

    # ============================================
    # Origin/Customization Classification
    # (from Assessment_Guide_Script_v3 logic)
    # ============================================
    origin_type: Optional[OriginType] = None
    head_owner: Optional[HeadOwner] = None
    changed_baseline_now: bool = False  # From hasCustomerUpdate()

    # Version tracking
    current_version_source_table: Optional[str] = None
    current_version_source: Optional[str] = None
    current_version_sys_id: Optional[str] = None
    current_version_recorded_at: Optional[datetime] = None

    # Created by analysis (for unknown_no_history)
    created_by_in_user_table: Optional[bool] = None

    # ============================================
    # Review and Disposition
    # ============================================
    review_status: ReviewStatus = ReviewStatus.pending_review
    disposition: Optional[Disposition] = None
    recommendation: Optional[str] = None
    observations: Optional[str] = None

    # Scope flags (set by AI triage and/or human override)
    is_adjacent: bool = False  # impacts but not part of assessed app
    is_out_of_scope: bool = False  # no relation to assessed app or trivial change

    # Assigned reviewer
    assigned_to: Optional[str] = None

    # ============================================
    # References to related data
    # ============================================
    # Reference to the update set containing this change
    update_set_id: Optional[int] = Field(default=None, foreign_key="update_set.id")

    # Reference to the customer update XML record
    customer_update_xml_id: Optional[int] = Field(default=None, foreign_key="customer_update_xml.id")

    # ============================================
    # Basic metadata
    # ============================================
    is_active: bool = True
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None

    # For code artifacts
    script_length: Optional[int] = None

    # Finding/assessment info
    severity: Optional[Severity] = None
    category: Optional[FindingCategory] = None
    finding_title: Optional[str] = None
    finding_description: Optional[str] = None

    # ---- Reasoning pipeline fields ----
    ai_summary: Optional[str] = None
    ai_observations: Optional[str] = None
    ai_pass_count: int = 0
    related_result_ids_json: Optional[str] = None

    # Raw data storage
    raw_data_json: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    scan: Scan = Relationship(back_populates="results")
    update_set: Optional["UpdateSet"] = Relationship(back_populates="scan_results")
    customer_update_xml: Optional["CustomerUpdateXML"] = Relationship(back_populates="scan_results")
    feature_links: List["FeatureScanResult"] = Relationship(back_populates="scan_result")
    customization: Optional["Customization"] = Relationship(back_populates="scan_result")


# ============================================
# TABLE: Customization (child of ScanResult)
# Pre-filtered: only customized results (modified_ootb, net_new_customer)
# AI reads this table directly — no query conditions needed.
# ============================================

class Customization(SQLModel, table=True):
    """Child table of ScanResult containing only customized results.

    Denormalized projection of scan_result rows where origin_type is
    'modified_ootb' or 'net_new_customer'. MCP/AI can SELECT * without
    filtering conditions, eliminating risk of reading non-customized data.

    Sync: populated by scan_executor (bulk) and result update endpoint (per-record).
    """
    __tablename__ = "customization"

    id: Optional[int] = Field(default=None, primary_key=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True, sa_column_kwargs={"unique": True})
    scan_id: int = Field(foreign_key="scan.id", index=True)

    # Copied from parent scan_result
    sys_id: str = Field(index=True)
    table_name: str = Field(index=True)
    name: str
    origin_type: Optional[OriginType] = Field(default=None, index=True)
    head_owner: Optional[HeadOwner] = None
    sys_class_name: Optional[str] = None
    sys_scope: Optional[str] = None
    review_status: ReviewStatus = ReviewStatus.pending_review
    disposition: Optional[Disposition] = None
    recommendation: Optional[str] = None
    observations: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Scope flags (synced from parent ScanResult)
    is_adjacent: bool = False
    is_out_of_scope: bool = False

    # Relationships
    scan_result: ScanResult = Relationship(back_populates="customization")
    scan: Scan = Relationship(back_populates="customizations")


# ============================================
# TABLE: Feature (groups related scan results)
# ============================================

class Feature(SQLModel, table=True):
    """Feature/solution grouping - groups related application files"""
    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    name: str
    description: Optional[str] = None

    # Parent feature (for hierarchical grouping)
    parent_id: Optional[int] = Field(default=None, foreign_key="feature.id")

    # Common update set that groups these items
    primary_update_set_id: Optional[int] = Field(default=None, foreign_key="update_set.id")

    # Overall disposition for the feature
    disposition: Optional[Disposition] = None
    recommendation: Optional[str] = None

    # AI-generated analysis
    ai_summary: Optional[str] = None

    # ---- Reasoning pipeline fields ----
    confidence_score: Optional[float] = None
    confidence_level: Optional[str] = None
    signals_json: Optional[str] = None
    primary_table: Optional[str] = None
    primary_developer: Optional[str] = None
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None
    pass_number: Optional[int] = None

    # ---- Visual styling ----
    color_index: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    assessment: Assessment = Relationship(back_populates="features")
    parent: Optional["Feature"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "Feature.id"}
    )
    children: List["Feature"] = Relationship(back_populates="parent")
    primary_update_set: Optional["UpdateSet"] = Relationship(back_populates="features")
    scan_result_links: List["FeatureScanResult"] = Relationship(back_populates="feature")
    context_artifacts: List["FeatureContextArtifact"] = Relationship(back_populates="feature")
    recommendations: List["FeatureRecommendation"] = Relationship(back_populates="feature")


# ============================================
# TABLE: GeneralRecommendation (assessment-wide recommendations)
# ============================================

class GeneralRecommendation(SQLModel, table=True):
    """Assessment-scoped general technical recommendation.

    High-level recommendations not tied to a specific scan result or feature.
    """
    __tablename__ = "general_recommendation"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[Severity] = None
    created_by: str = "ai_agent"

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    assessment: Assessment = Relationship(back_populates="general_recommendations")


# ============================================
# TABLE: FeatureScanResult (M2M: Feature ↔ ScanResult)
# ============================================

class FeatureScanResult(SQLModel, table=True):
    """Many-to-many link between Features and ScanResults"""
    __tablename__ = "feature_scan_result"
    __table_args__ = (
        UniqueConstraint("feature_id", "scan_result_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    feature_id: int = Field(foreign_key="feature.id", index=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True)

    # Is this a primary member or secondary/related?
    is_primary: bool = True
    notes: Optional[str] = None
    membership_type: str = "primary"  # primary | supporting
    assignment_source: str = "engine"  # engine | ai | human
    assignment_confidence: Optional[float] = None
    evidence_json: Optional[str] = None
    iteration_number: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    feature: Feature = Relationship(back_populates="scan_result_links")
    scan_result: ScanResult = Relationship(back_populates="feature_links")


# ============================================
# TABLE: FeatureContextArtifact (non-member context evidence)
# ============================================

class FeatureContextArtifact(SQLModel, table=True):
    """Links non-member artifacts used as context/evidence for a feature."""
    __tablename__ = "feature_context_artifact"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    feature_id: int = Field(foreign_key="feature.id", index=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True)

    context_type: str
    confidence: float = 1.0
    evidence_json: Optional[str] = None
    iteration_number: int = 0

    created_at: datetime = Field(default_factory=datetime.utcnow)

    feature: Feature = Relationship(back_populates="context_artifacts")
    scan_result: ScanResult = Relationship()


# ============================================
# TABLE: FeatureGroupingRun (iteration/run tracking)
# ============================================

class FeatureGroupingRun(SQLModel, table=True):
    """Tracks iterative grouping/reasoning runs for an assessment."""
    __tablename__ = "feature_grouping_run"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    status: str = "pending"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    max_iterations: int = 3
    iterations_completed: int = 0
    converged: bool = False
    summary_json: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: FeatureRecommendation (feature-level OOTB recommendation)
# ============================================

class FeatureRecommendation(SQLModel, table=True):
    """Feature-level recommendation with OOTB product/SKU provenance."""
    __tablename__ = "feature_recommendation"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    feature_id: int = Field(foreign_key="feature.id", index=True)

    recommendation_type: str
    ootb_capability_name: Optional[str] = None
    product_name: Optional[str] = None
    sku_or_license: Optional[str] = None
    requires_plugins_json: Optional[str] = None
    fit_confidence: Optional[float] = None
    rationale: Optional[str] = None
    evidence_json: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    feature: Feature = Relationship(back_populates="recommendations")


# ============================================
# TABLE: CodeReference (cross-references in scripts)
# Populated by the Code Reference Parser engine
# ============================================

class CodeReference(SQLModel, table=True):
    """Cross-reference discovered by parsing script/code fields."""
    __tablename__ = "code_reference"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    # Source: scan result containing code
    source_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    source_table: str
    source_field: str
    source_name: str

    # Target: identifier referenced by source code
    reference_type: str
    target_identifier: str
    target_scan_result_id: Optional[int] = Field(default=None, foreign_key="scan_result.id")

    # Context
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    confidence: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: UpdateSetOverlap (cross-update-set record sharing)
# Populated by the Update Set Analyzer engine
# ============================================

class UpdateSetOverlap(SQLModel, table=True):
    """Records shared between two update sets."""
    __tablename__ = "update_set_overlap"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    update_set_a_id: int = Field(foreign_key="update_set.id", index=True)
    update_set_b_id: int = Field(foreign_key="update_set.id", index=True)

    shared_record_count: int
    shared_records_json: str
    overlap_score: float

    # Phase 2 addendum fields
    signal_type: str = Field(default="content")  # content | name_similarity | version_history | temporal_sequence | author_sequence
    evidence_json: Optional[str] = None  # explainability payload for this overlap

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: TemporalCluster (developer activity windows)
# Populated by the Temporal Clusterer engine
# ============================================

class TemporalCluster(SQLModel, table=True):
    """Cluster of records in close time proximity by same developer."""
    __tablename__ = "temporal_cluster"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    developer: str
    cluster_start: datetime
    cluster_end: datetime
    record_count: int
    record_ids_json: str
    avg_gap_minutes: float
    tables_involved_json: str

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: TemporalClusterMember (cluster membership links)
# Populated by the Temporal Clusterer engine
# ============================================

class TemporalClusterMember(SQLModel, table=True):
    """Junction table linking temporal clusters to scan results."""
    __tablename__ = "temporal_cluster_member"
    __table_args__ = (
        UniqueConstraint(
            "temporal_cluster_id",
            "scan_result_id",
            name="uq_temporal_cluster_member_cluster_result",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    temporal_cluster_id: int = Field(foreign_key="temporal_cluster.id", index=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: StructuralRelationship (parent/child metadata links)
# Populated by the Structural Mapper engine
# ============================================

class StructuralRelationship(SQLModel, table=True):
    """Explicit parent/child or structural relationship between artifacts."""
    __tablename__ = "structural_relationship"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    parent_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    child_scan_result_id: int = Field(foreign_key="scan_result.id", index=True)

    relationship_type: str
    parent_field: str
    confidence: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: UpdateSet (cached from ServiceNow)
# ============================================

class UpdateSet(SQLModel, table=True):
    """Update set from ServiceNow (cached for feature grouping)"""
    __tablename__ = "update_set"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_update_set_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)  # sys_id in ServiceNow
    name: str
    description: Optional[str] = None
    state: Optional[str] = None  # in progress, complete, etc.
    application: Optional[str] = None  # Reference to sys_scope sys_id
    release_date: Optional[datetime] = None

    # Additional fields from sys_update_set export (22 total)
    is_default: bool = False  # True for Default update set (DOB indicator)
    completed_on: Optional[datetime] = None
    completed_by: Optional[str] = None
    parent: Optional[str] = None  # Parent update set sys_id
    origin_sys_id: Optional[str] = None
    remote_sys_id: Optional[str] = None
    merged_to: Optional[str] = None
    install_date: Optional[datetime] = None
    installed_from: Optional[str] = None
    base_update_set: Optional[str] = None
    batch_install_plan: Optional[str] = None

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_mod_count: Optional[int] = None

    # Record count in this update set
    record_count: int = 0

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="update_sets")
    scan_results: List[ScanResult] = Relationship(back_populates="update_set")
    features: List[Feature] = Relationship(back_populates="primary_update_set")
    customer_updates: List["CustomerUpdateXML"] = Relationship(back_populates="update_set")


# ============================================
# TABLE: CustomerUpdateXML (sys_update_xml cached)
# ============================================

class CustomerUpdateXML(SQLModel, table=True):
    """Customer update XML records from ServiceNow (sys_update_xml)"""
    __tablename__ = "customer_update_xml"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_customer_update_xml_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    update_set_id: Optional[int] = Field(default=None, foreign_key="update_set.id", index=True)
    update_set_sn_sys_id: Optional[str] = None  # Store SN sys_id for later linking

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)
    name: str  # sys_update_name
    action: Optional[str] = None  # INSERT_OR_UPDATE, DELETE
    type: Optional[str] = None  # Table type
    target_name: Optional[str] = None

    # Reference to the metadata record
    target_sys_id: Optional[str] = None  # sys_id of the target record

    # Additional fields from sys_update_xml export (26 total)
    category: Optional[str] = None  # customer/blank/retrieved - KEY for origin classification
    update_guid: Optional[str] = Field(default=None, index=True)  # Critical for version linking
    update_guid_history: Optional[str] = None
    application: Optional[str] = None  # Reference to sys_scope
    comments: Optional[str] = None
    replace_on_upgrade: Optional[bool] = None
    remote_update_set: Optional[str] = None
    update_domain: Optional[str] = None
    view: Optional[str] = None
    table: Optional[str] = None  # Target table name
    sys_recorded_at: Optional[datetime] = None

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_mod_count: Optional[int] = None

    # Payload storage (optional - can be large)
    payload_hash: Optional[str] = None
    payload: Optional[str] = None  # Full XML payload if needed

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="customer_update_xmls")
    update_set: Optional[UpdateSet] = Relationship(back_populates="customer_updates")
    scan_results: List[ScanResult] = Relationship(back_populates="customer_update_xml")


# ============================================
# TABLE: VersionHistory (sys_update_version cached)
# ============================================

class VersionHistory(SQLModel, table=True):
    """Version history records from ServiceNow (sys_update_version)"""
    __tablename__ = "version_history"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_version_history_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # Reference to the metadata record by update name
    sys_update_name: str = Field(index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)
    name: str
    state: Optional[str] = None  # current, previous, etc.
    source_table: Optional[str] = None  # sys_upgrade_history, sys_store_app, sys_update_set
    source_sys_id: Optional[str] = None
    source_display: Optional[str] = None
    customer_update_sys_id: Optional[str] = Field(default=None, index=True)  # sys_customer_update.value (target config record sys_id)

    # Additional fields from sys_update_version export (23 total)
    update_guid: Optional[str] = Field(default=None, index=True)  # Critical for linking to sys_update_xml
    update_guid_history: Optional[str] = None
    record_name: Optional[str] = None  # Target record name
    action: Optional[str] = None  # INSERT/UPDATE/DELETE
    application: Optional[str] = None  # Reference to sys_scope
    file_path: Optional[str] = None
    instance_id_sn: Optional[str] = None  # SN's instance_id field (avoid conflict with our FK)
    instance_name: Optional[str] = None
    reverted_from: Optional[str] = None
    type: Optional[str] = None
    sys_tags: Optional[str] = None

    # Payload (optional - can be large)
    payload: Optional[str] = None
    payload_hash: Optional[str] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    # Audit fields
    sys_recorded_at: Optional[datetime] = None
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_mod_count: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: "Instance" = Relationship(back_populates="version_history")


# ============================================
# TABLE: MetadataCustomization (sys_metadata_customization cached)
# ============================================

class MetadataCustomization(SQLModel, table=True):
    """Metadata customization records from ServiceNow (sys_metadata_customization)
    
    This table tracks OOB records that have been modified from baseline.
    If a record exists here, it indicates the OOB record was customized.
    """
    __tablename__ = "metadata_customization"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_metadata_customization_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)  # sys_id in ServiceNow
    sys_metadata_sys_id: str = Field(index=True)  # Reference to sys_metadata.sys_id
    sys_update_name: str = Field(index=True)  # Links to sys_metadata.sys_update_name

    # Key classification field
    author_type: Optional[str] = None  # customer, servicenow, etc.

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: "Instance" = Relationship(back_populates="metadata_customizations")


# ============================================
# TABLE: InstancePlugin (plugins from instance)
# ============================================

class InstancePlugin(SQLModel, table=True):
    """Plugins/packages from a ServiceNow instance"""
    __tablename__ = "instance_plugin"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_instance_plugin_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields (from v_plugin or sys_plugins)
    sn_sys_id: str = Field(index=True)
    plugin_id: str  # The plugin ID (e.g., "com.snc.incident") - maps to 'source' field
    name: str
    version: Optional[str] = None
    state: Optional[str] = None  # active, inactive

    # Additional fields
    description: Optional[str] = None
    vendor: Optional[str] = None
    active: Optional[bool] = None  # Distinct from state
    scope: Optional[str] = None  # Reference to sys_scope
    parent: Optional[str] = None  # Parent plugin

    # Related package sys_id
    package_sys_id: Optional[str] = None

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_updated_on: Optional[datetime] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="plugins")


# ============================================
# TABLE: PluginView (v_plugin from instance)
# ============================================

class PluginView(SQLModel, table=True):
    """Plugin view records from v_plugin (version/definition info)."""
    __tablename__ = "plugin_view"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_plugin_view_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)
    plugin_id: Optional[str] = None  # v_plugin.id
    name: Optional[str] = None
    definition: Optional[str] = None
    scope: Optional[str] = None
    version: Optional[str] = None
    active: Optional[bool] = None

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_updated_on: Optional[datetime] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="plugin_views")


# ============================================
# TABLE: InstanceDataPull (tracks data pull operations)
# ============================================

class InstanceDataPull(SQLModel, table=True):
    """Tracks data pull operations per instance per data type"""
    __tablename__ = "instance_data_pull"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    data_type: DataPullType = Field(index=True)
    run_uid: Optional[str] = Field(default=None, index=True)

    # Status tracking
    status: DataPullStatus = DataPullStatus.idle
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancel_requested: bool = False
    cancel_requested_at: Optional[datetime] = None

    # Results tracking
    records_pulled: int = 0
    last_pulled_at: Optional[datetime] = None  # Last successful pull timestamp
    error_message: Optional[str] = None

    # Delta tracking - watermark for incremental pulls
    last_sys_updated_on: Optional[datetime] = None
    expected_total: Optional[int] = None
    expected_total_at: Optional[datetime] = None

    # Smart sync decision tracking
    sync_mode: Optional[str] = None  # "full", "delta", "smart", "skip"
    last_remote_count: Optional[int] = None
    last_local_count: Optional[int] = None
    sync_decision_reason: Optional[str] = None

    # Origin context — distinguishes initial connection pulls from preflight pulls.
    source_context: Optional[str] = None  # "initial_data" or "preflight"

    # State filter tracking — records when a pull used a subset filter (e.g., "current"
    # for VH). Lets catchup logic know the local count reflects a filtered pull and
    # avoids incorrectly deciding "full refresh" due to count mismatch.
    state_filter_applied: Optional[str] = None

    # Bail-out telemetry columns — all default None so SQLite ALTER TABLE ADD COLUMN works
    # without data migration scripts. Populated by data_pull_executor bail-out logic.
    local_count_pre_pull: Optional[int] = Field(default=None)
    remote_count_at_probe: Optional[int] = Field(default=None)
    delta_probe_count: Optional[int] = Field(default=None)
    bail_out_reason: Optional[str] = Field(default=None)
    bail_unchanged_at_exit: Optional[int] = Field(default=None)
    local_count_post_pull: Optional[int] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="data_pulls")


# ============================================
# TABLE: Scope (sys_scope from ServiceNow)
# ============================================

class Scope(SQLModel, table=True):
    """Application scope definitions from ServiceNow (sys_scope)"""
    __tablename__ = "scope"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_scope_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)  # sys_id in ServiceNow
    scope: str = Field(index=True)  # e.g., "global", "x_myapp_myapp"
    name: str  # Display name
    short_description: Optional[str] = None
    version: Optional[str] = None
    vendor: Optional[str] = None
    vendor_prefix: Optional[str] = None
    private: Optional[bool] = None
    licensable: Optional[bool] = None
    active: bool = True

    # Source identifier (if from store)
    source: Optional[str] = None  # ID field value

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="scopes")


# ============================================
# TABLE: Package (sys_package from ServiceNow)
# ============================================

class Package(SQLModel, table=True):
    """Package definitions from ServiceNow (sys_package).

    sys_package is the core table for package/plugin ownership mapping.
    Note: This table is NOT OOTB web-accessible - requires admin to enable
    "Allow access to this table via web services" in sys_db_object.
    """
    __tablename__ = "package"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_package_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields (from sys_package dictionary)
    sn_sys_id: str = Field(index=True)  # sys_id
    name: str  # Name (display: true)
    source: Optional[str] = Field(default=None, index=True)  # ID field - maps to plugin_id
    version: Optional[str] = None  # Version

    # Status/classification fields
    active: bool = True  # Active
    licensable: Optional[bool] = None  # Licensable
    trackable: Optional[bool] = None  # Trackable

    # Subscription/licensing fields
    enforce_license: Optional[str] = None  # Subscription requirement
    license_category: Optional[str] = None  # Subscription Category
    license_model: Optional[str] = None  # Subscription Model

    # IDE/development fields
    ide_created: Optional[str] = None  # IDE Created

    # Reference to package JSON (EcmaScript Module)
    package_json: Optional[str] = None  # Package JSON reference

    # Class name for inheritance
    sys_class_name: Optional[str] = None  # Class

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_mod_count: Optional[int] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="packages")


# ============================================
# TABLE: Application (sys_app from ServiceNow)
# ============================================

class Application(SQLModel, table=True):
    """Applications from ServiceNow (sys_app)"""
    __tablename__ = "application"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_application_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)
    name: str
    scope: Optional[str] = None
    short_description: Optional[str] = None
    version: Optional[str] = None
    vendor: Optional[str] = None
    vendor_prefix: Optional[str] = None
    active: Optional[bool] = None
    source: Optional[str] = None

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="applications")


# ============================================
# TABLE: TableDefinition (sys_db_object from ServiceNow)
# ============================================

class TableDefinition(SQLModel, table=True):
    """Table definitions from ServiceNow (sys_db_object)"""
    __tablename__ = "table_definition"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_sys_id", name="uq_table_definition_instance_sn_sys_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow fields
    sn_sys_id: str = Field(index=True)
    name: str  # Table name (e.g., incident)
    label: Optional[str] = None
    super_class: Optional[str] = None  # Reference to parent table
    sys_package: Optional[str] = None  # Reference to sys_package
    sys_scope: Optional[str] = None  # Reference to sys_scope
    access: Optional[str] = None
    extension_model: Optional[str] = None
    is_extendable: Optional[bool] = None

    # Audit fields
    sys_created_on: Optional[datetime] = None
    sys_created_by: Optional[str] = None
    sys_updated_on: Optional[datetime] = None
    sys_updated_by: Optional[str] = None
    sys_mod_count: Optional[int] = None

    # Raw payload for full field retention
    raw_data_json: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None

    # Sync tracking
    sync_batch_id: Optional[str] = None  # UUID of batch that last touched this record

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="table_definitions")


# ============================================
# TABLE: Fact (agent-discovered instance facts)
# ============================================

class Fact(SQLModel, table=True):
    """
    Instance-specific facts discovered by agents/skills or computed by the system.

    Facts are persistent knowledge about a specific instance that survives context resets.
    They are created by specialized agents during analysis and consumed by other agents
    or the orchestrator to build deliverables.

    NOT for universal knowledge (e.g., "GlideRecord in loops is bad") — that belongs
    in agent prompts/skill definitions.
    """
    __tablename__ = "fact"

    id: Optional[int] = Field(default=None, primary_key=True)

    # ALWAYS instance-scoped — facts are about a specific instance
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # Module/domain that owns this fact
    module: str = Field(index=True)  # "tech_assessment", "csdm", "upgrade_readiness", "security"

    # What this fact is about
    topic_type: str = Field(index=True)  # "global_app", "table", "ci_class", "pattern", "relationship", "process"
    topic_value: Optional[str] = Field(default=None, index=True)  # "incident", "sys_script", "cmdb_ci_service"

    # The fact itself
    fact_key: str = Field(index=True)  # "custom_br_count", "routing_mechanism", "anti_pattern_detected"
    fact_value: str  # JSON-encoded value (can be string, number, object, array)

    # Who/what created this fact
    created_by: str  # "ta_agent", "csdm_agent", "computed", "user"
    skill_name: Optional[str] = None  # "origin_classification", "code_review", "service_mapping"

    # What kind of output this supports
    output_type: Optional[str] = None  # "finding", "recommendation", "classification", "relationship", "count"
    deliverable_target: Optional[str] = None  # "ta_report", "csdm_hierarchy", "upgrade_readiness_report"

    # Confidence and validity
    confidence: float = 1.0  # 1.0 = computed/verified, <1.0 = AI-inferred
    valid_until: Optional[datetime] = None  # For time-sensitive facts (e.g., counts that may change)

    # Optional reference to source record
    source_table: Optional[str] = None  # "scan_result", "customer_update_xml", etc.
    source_sys_id: Optional[str] = None  # sys_id of the source record

    # Audit
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="facts")


# ============================================
# TABLE: JobRun (durable integration run state)
# ============================================

class JobRun(SQLModel, table=True):
    """Durable lifecycle state for integration/background runs."""
    __tablename__ = "job_run"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_uid: str = Field(index=True, unique=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    module: str = Field(index=True)   # e.g. "preflight", "csdm"
    job_type: str = Field(index=True)  # e.g. "data_pull"
    mode: Optional[str] = None  # full / delta / smart

    status: JobRunStatus = JobRunStatus.queued
    queue_total: int = 0
    queue_completed: int = 0
    current_index: Optional[int] = None
    current_data_type: Optional[str] = Field(default=None, index=True)

    progress_pct: Optional[int] = None
    estimated_remaining_seconds: Optional[float] = None
    message: Optional[str] = None
    error_message: Optional[str] = None

    requested_data_types_json: Optional[str] = None
    metadata_json: Optional[str] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    instance: Instance = Relationship(back_populates="job_runs")
    events: List["JobEvent"] = Relationship(back_populates="run")


# ============================================
# TABLE: JobEvent (durable run event log)
# ============================================

class JobEvent(SQLModel, table=True):
    """Append-only event stream for durable job runs."""
    __tablename__ = "job_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="job_run.id", index=True)
    event_type: str = Field(index=True)
    summary: Optional[str] = None
    data_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Relationships
    run: JobRun = Relationship(back_populates="events")


# ============================================
# TABLE: AssessmentRuntimeUsage (assessment AI runtime telemetry)
# ============================================

class AssessmentRuntimeUsage(SQLModel, table=True):
    """Assessment-level runtime/cost telemetry snapshot."""
    __tablename__ = "assessment_runtime_usage"
    __table_args__ = (
        UniqueConstraint("assessment_id", name="uq_assessment_runtime_usage_assessment"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    assessment_number: Optional[str] = Field(default=None, index=True)
    assessment_name: Optional[str] = Field(default=None, index=True)
    instance_name: Optional[str] = Field(default=None, index=True)
    assessment_state: Optional[str] = Field(default=None, index=True)

    llm_runtime_mode: Optional[str] = Field(default=None, index=True)
    llm_provider: Optional[str] = Field(default=None, index=True)
    llm_model: Optional[str] = Field(default=None, index=True)

    run_started_at: Optional[datetime] = None
    run_completed_at: Optional[datetime] = None
    run_duration_seconds: Optional[int] = None

    total_results: int = 0
    customized_results: int = 0
    total_features: int = 0
    total_groupings: int = 0
    total_feature_memberships: int = 0
    total_general_recommendations: int = 0
    total_feature_recommendations: int = 0
    total_technical_recommendations: int = 0

    mcp_calls_local: int = 0
    mcp_calls_servicenow: int = 0
    mcp_calls_local_db: int = 0

    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_total_tokens: int = 0
    estimated_cost_usd: float = 0.0

    last_event: Optional[str] = None
    details_json: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: AssessmentPhaseProgress (resumable phase checkpoints)
# ============================================

class AssessmentPhaseProgress(SQLModel, table=True):
    """Per-assessment, per-phase resumable checkpoint state."""
    __tablename__ = "assessment_phase_progress"
    __table_args__ = (
        UniqueConstraint("assessment_id", "phase", name="uq_assessment_phase_progress_scope"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    phase: str = Field(index=True)
    status: str = Field(default="pending", index=True)

    total_items: int = 0
    completed_items: int = 0
    resume_from_index: int = 0
    last_item_id: Optional[int] = None
    run_attempt: int = 0

    checkpoint_json: Optional[str] = None
    last_error: Optional[str] = None

    started_at: Optional[datetime] = None
    last_checkpoint_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: AppConfig (application settings)
# ============================================

class AppConfig(SQLModel, table=True):
    """Application configuration settings"""
    __tablename__ = "app_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: Optional[int] = Field(default=None, foreign_key="instance.id", index=True)
    key: str = Field(index=True)
    value: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: UpdateSetArtifactLink (US ↔ artifact provenance)
# Populated by the Update Set Analyzer engine
# ============================================

class UpdateSetArtifactLink(SQLModel, table=True):
    """Links a scan result to an update set with source provenance."""
    __tablename__ = "update_set_artifact_link"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "scan_result_id", "update_set_id", "link_source",
            name="uq_us_artifact_link_scope",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)
    scan_result_id: int = Field(foreign_key="scan_result.id", index=True)
    update_set_id: int = Field(foreign_key="update_set.id", index=True)

    link_source: str  # scan_result_current | customer_update_xml | version_history
    is_current: bool = False
    confidence: float = 1.0
    evidence_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: NamingCluster (name-prefix grouping)
# Populated by the Naming Analyzer engine
# ============================================

class NamingCluster(SQLModel, table=True):
    """Cluster of artifacts sharing a naming prefix or pattern."""
    __tablename__ = "naming_cluster"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    cluster_label: str  # extracted prefix/stem
    pattern_type: str  # prefix | suffix | contains
    member_count: int
    member_ids_json: str  # JSON array of scan_result IDs
    tables_involved_json: str  # JSON array of distinct table_names
    confidence: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: TableColocationSummary (table co-location)
# Populated by the Table Co-location engine
# ============================================

class TableColocationSummary(SQLModel, table=True):
    """Summary of artifacts co-located on the same target table."""
    __tablename__ = "table_colocation_summary"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    target_table: str  # the SN table being targeted
    record_count: int
    record_ids_json: str  # JSON array of scan_result IDs
    artifact_types_json: str  # JSON array of distinct sys_class_name values
    developers_json: str  # JSON array of distinct developers

    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================
# TABLE: NumberSequence (for ASMT numbers)
# ============================================

class NumberSequence(SQLModel, table=True):
    """Sequence generator for assessment numbers"""
    __tablename__ = "number_sequence"

    id: Optional[int] = Field(default=None, primary_key=True)
    prefix: str = Field(unique=True, index=True)  # "ASMT"
    current_value: int = 0
    padding: int = 7  # Number of digits (ASMT0000001)

    def next_number(self) -> str:
        """Generate next number in sequence"""
        self.current_value += 1
        return f"{self.prefix}{str(self.current_value).zfill(self.padding)}"


# ============================================
# ENUM: BestPracticeCategory
# ============================================

class BestPracticeCategory(str, Enum):
    """Categories for ServiceNow best practice checks."""
    technical_server = "technical_server"
    technical_client = "technical_client"
    architecture = "architecture"
    process = "process"
    security = "security"
    performance = "performance"
    upgradeability = "upgradeability"
    catalog = "catalog"
    integration = "integration"


# ============================================
# TABLE: BestPractice (admin-editable checks)
# ============================================

class BestPractice(SQLModel, table=True):
    """Admin-editable ServiceNow best practice check.

    Used by the technical_architect prompt to evaluate artifacts
    and produce assessment-wide technical findings.
    """
    __tablename__ = "best_practice"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    title: str
    category: BestPracticeCategory
    severity: str = "medium"  # Uses Severity values but stored as str for flexibility
    description: Optional[str] = None
    detection_hint: Optional[str] = None
    recommendation: Optional[str] = None
    applies_to: Optional[str] = None  # Comma-separated sys_class_name values, or null = all
    is_active: bool = Field(default=True)
    source_url: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
