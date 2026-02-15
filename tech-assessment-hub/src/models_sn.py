# models_sn.py - ServiceNow Mirror Table Models
# Registry/management tables for SN mirror tables and ingestion state
#
# These models track which ServiceNow tables have been mirrored locally,
# their field mappings, ingestion state (delta cursors), job logs,
# and custom table requests.
#
# NOTE: DB table names retain their original csdm_ prefix for migration safety.

from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import Optional, List
from sqlalchemy import UniqueConstraint


# ============================================
# TABLE: SnTableRegistry
# Tracks which SN tables are mirrored locally
# ============================================

class SnTableRegistry(SQLModel, table=True):
    """Registry of ServiceNow tables mirrored locally for CSDM analysis."""
    __tablename__ = "csdm_table_registry"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_table_name", name="uq_csdm_registry_instance_table"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)

    # ServiceNow table identity
    sn_table_name: str = Field(index=True)  # e.g., "cmdb_ci_service"
    local_table_name: str = Field(index=True)  # e.g., "sn_cmdb_ci_service"

    # Classification
    priority_group: str = Field(index=True)  # "service", "foundation", "process", "custom"
    display_label: Optional[str] = None
    source: str = "csdm"  # "csdm" | "preflight" | "custom"
    sn_table_label: Optional[str] = None  # Human-readable label from sys_db_object
    parent_table: Optional[str] = None  # SN parent table name
    parent_local_table: Optional[str] = None  # Local parent table name
    is_custom: bool = False
    is_active: bool = True

    # Schema tracking
    field_count: int = 0
    row_count: int = 0
    schema_version: int = 1
    schema_hash: Optional[str] = None

    # Timestamps
    first_ingested_at: Optional[datetime] = None
    last_schema_refresh_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    field_mappings: List["SnFieldMapping"] = Relationship(back_populates="registry")
    # NOTE: Instance model needs relationship added:
    #   sn_table_registries: List["SnTableRegistry"] = Relationship(back_populates="instance")
    instance: "Instance" = Relationship(back_populates="sn_table_registries")


# ============================================
# TABLE: SnFieldMapping
# Maps SN dictionary fields to local columns
# ============================================

class SnFieldMapping(SQLModel, table=True):
    """Field-level mapping from ServiceNow dictionary to local mirror table columns."""
    __tablename__ = "csdm_field_mapping"
    __table_args__ = (
        UniqueConstraint("registry_id", "sn_element", name="uq_csdm_field_registry_element"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    registry_id: int = Field(
        foreign_key="csdm_table_registry.id",
        index=True,
    )

    # ServiceNow field identity
    sn_element: str = Field(index=True)  # SN column/element name
    local_column: str  # Local SQLite column name

    # SN type metadata
    sn_internal_type: Optional[str] = None  # e.g., "string", "reference", "glide_date_time"
    sn_max_length: Optional[int] = None
    sn_reference_table: Optional[str] = None  # Target table for reference fields
    sn_reference_qual: Optional[str] = None  # Reference qualifier
    sn_choice_table: Optional[str] = None  # Choice set table
    column_label: Optional[str] = None  # Human-readable column label from sys_dictionary
    is_mandatory: bool = False
    is_read_only: bool = False
    source_table: Optional[str] = None  # Which table in the inheritance chain owns this field

    # Local DB type
    db_column_type: str = "TEXT"  # SQLite column type

    # Classification flags
    is_reference: bool = False
    is_primary_key: bool = False
    is_indexed: bool = False
    is_active: bool = True

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    registry: SnTableRegistry = Relationship(back_populates="field_mappings")


# ============================================
# TABLE: SnIngestionState
# Delta cursor and status for each table/instance
# ============================================

class SnIngestionState(SQLModel, table=True):
    """Tracks ingestion progress, delta cursors, and run status per table per instance."""
    __tablename__ = "csdm_ingestion_state"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_table_name", name="uq_csdm_ingestion_instance_table"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    sn_table_name: str = Field(index=True)

    # Delta cursor
    last_successful_sys_updated_on: Optional[datetime] = None
    last_successful_sys_id: Optional[str] = None

    # Refresh timestamps
    last_full_refresh_at: Optional[datetime] = None
    last_delta_at: Optional[datetime] = None

    # Run status
    last_run_status: Optional[str] = None  # success, failed, cancelled, in_progress, interrupted
    last_run_started_at: Optional[datetime] = None
    last_run_completed_at: Optional[datetime] = None
    last_error: Optional[str] = None

    # Counters
    total_rows_in_db: int = 0
    last_batch_inserted: int = 0
    last_batch_updated: int = 0
    last_batch_duration_seconds: Optional[float] = None
    cumulative_rows_pulled: int = 0

    # Remote table info
    last_remote_count: Optional[int] = None
    last_remote_count_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # NOTE: Instance model needs relationship added:
    #   sn_ingestion_states: List["SnIngestionState"] = Relationship(back_populates="instance")
    instance: "Instance" = Relationship(back_populates="sn_ingestion_states")


# ============================================
# TABLE: SnJobLog
# Audit log of ingestion jobs
# ============================================

class SnJobLog(SQLModel, table=True):
    """Audit log for CSDM ingestion jobs (delta, full refresh, schema refresh, etc.)."""
    __tablename__ = "csdm_job_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    sn_table_name: str = Field(index=True)

    # Job metadata
    job_type: str  # delta, full_refresh, schema_refresh, clear, recovery
    status: str = "started"  # started, in_progress, completed, failed, cancelled, interrupted

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Row counts
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_deleted: int = 0
    batches_processed: int = 0

    # Error info
    error_message: Optional[str] = None
    error_stack: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # NOTE: Instance model needs relationship added:
    #   sn_job_logs: List["SnJobLog"] = Relationship(back_populates="instance")
    instance: "Instance" = Relationship(back_populates="sn_job_logs")


# ============================================
# TABLE: SnCustomTableRequest
# User requests to add non-standard tables
# ============================================

class SnCustomTableRequest(SQLModel, table=True):
    """Tracks user requests to add custom (non-standard) ServiceNow tables to the CSDM mirror."""
    __tablename__ = "csdm_custom_table_request"
    __table_args__ = (
        UniqueConstraint("instance_id", "sn_table_name", name="uq_csdm_custom_request_instance_table"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="instance.id", index=True)
    sn_table_name: str = Field(index=True)
    display_label: Optional[str] = None

    # Lifecycle status
    status: str = "pending"  # pending, validated, schema_created, active, failed
    validation_error: Optional[str] = None

    # Timestamps
    requested_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None
    schema_created_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)

    # NOTE: Instance model needs relationship added:
    #   sn_custom_table_requests: List["SnCustomTableRequest"] = Relationship(back_populates="instance")
    instance: "Instance" = Relationship(back_populates="sn_custom_table_requests")


# Unified aliases for shared usage across CSDM, Preflight, and Custom
TableRegistry = SnTableRegistry
TableFieldRegistry = SnFieldMapping
