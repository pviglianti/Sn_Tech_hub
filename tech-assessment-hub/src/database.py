# database.py - Database connection and setup

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import text, event
from pathlib import Path
import os
from typing import Iterable

from .app_file_class_catalog import (
    default_assessment_availability_for_instance_file_type,
    default_assessment_option_availability_for_instance_file_type,
)

# Database file location
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR}/tech_assessment.db"

# Create engine with connection settings
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True to see SQL queries in console
    connect_args={"check_same_thread": False, "timeout": 30}  # Needed for SQLite with FastAPI
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    finally:
        cursor.close()


def create_db_and_tables():
    """Create all database tables from SQLModel definitions"""
    # Import all models so SQLModel registers their tables
    from . import models  # noqa: F401 — Instance, Scan, etc.
    from .models_sn import (  # noqa: F401
        SnTableRegistry, SnFieldMapping, SnIngestionState,
        SnJobLog, SnCustomTableRequest,
    )
    SQLModel.metadata.create_all(engine)
    _ensure_instance_columns()
    _ensure_app_config_instance_scope()
    _ensure_model_table_columns([
        "assessment",
        "scan",
        "scan_result",
        "feature",
        "feature_scan_result",
        "feature_context_artifact",
        "feature_grouping_run",
        "feature_recommendation",
        "update_set",
        "customer_update_xml",
        "version_history",
        "metadata_customization",
        "instance_app_file_type",
        "instance_data_pull",
        "instance_plugin",
        "plugin_view",
        "scope",
        "package",
        "application",
        "table_definition",
        # CSDM Data Foundations tables
        "csdm_table_registry",
        "csdm_field_mapping",
        "csdm_ingestion_state",
        "csdm_job_log",
        "csdm_custom_table_request",
        "job_run",
        "job_event",
        "app_config",
        "assessment_runtime_usage",
        "assessment_phase_progress",
        "code_reference",
        "update_set_overlap",
        "temporal_cluster",
        "temporal_cluster_member",
        "structural_relationship",
        "update_set_artifact_link",
        "naming_cluster",
        "table_colocation_summary",
    ])
    _ensure_assessment_pipeline_defaults()
    _ensure_instance_app_file_type_defaults()
    _ensure_indexes()
    # Create / update per-class artifact detail tables from ARTIFACT_DETAIL_DEFS.
    from .services.artifact_ddl import ensure_artifact_tables
    ensure_artifact_tables(engine)


def _ensure_instance_columns():
    """Add new Instance columns for metrics if missing (lightweight migration)"""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(instance)"))
        existing = {row[1] for row in result.fetchall()}

        columns = {
            "company": "TEXT",
            "inventory_json": "TEXT",
            "task_counts_json": "TEXT",
            "update_set_counts_json": "TEXT",
            "sys_update_xml_counts_json": "TEXT",
            "sys_update_xml_total": "INTEGER",
            "sys_metadata_customization_count": "INTEGER",
            "instance_dob": "TEXT",
            "instance_age_years": "REAL",
            "metrics_last_refreshed_at": "TEXT",
            "custom_scoped_app_count_x": "INTEGER",
            "custom_scoped_app_count_u": "INTEGER",
            "custom_table_count_u": "INTEGER",
            "custom_table_count_x": "INTEGER",
            "custom_field_count_u": "INTEGER",
            "custom_field_count_x": "INTEGER",
        }

        for name, col_type in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE instance ADD COLUMN {name} {col_type}"))

        conn.commit()


def _ensure_assessment_pipeline_defaults() -> None:
    """Backfill assessment.pipeline_stage for databases created before Phase 5."""
    with engine.connect() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='assessment'")
        ).first()
        if not table_exists:
            return

        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(assessment)")).fetchall()}
        if "pipeline_stage" not in columns:
            return

        conn.execute(
            text(
                """
                UPDATE assessment
                SET pipeline_stage = 'scans'
                WHERE pipeline_stage IS NULL OR TRIM(pipeline_stage) = ''
                """
            )
        )
        conn.commit()


def _ensure_app_config_instance_scope() -> None:
    """Migrate app_config to support optional instance-scoped overrides.

    Legacy schema used a globally-unique key. New schema stores:
    - global defaults with instance_id NULL
    - per-instance overrides with instance_id set
    """
    with engine.connect() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='app_config'")
        ).first()
        if not table_exists:
            return

        rows = conn.execute(text("PRAGMA table_info(app_config)")).fetchall()
        existing_columns = {row[1] for row in rows}

        has_legacy_unique_key = False
        index_rows = conn.execute(text("PRAGMA index_list('app_config')")).fetchall()
        for idx in index_rows:
            idx_name = idx[1]
            is_unique = bool(idx[2])
            if not is_unique:
                continue
            idx_cols = conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
            col_names = [c[2] for c in idx_cols]
            if col_names == ["key"]:
                has_legacy_unique_key = True
                break

        if "instance_id" in existing_columns and not has_legacy_unique_key:
            return

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("DROP TABLE IF EXISTS app_config_new"))
        conn.execute(text(
            """
            CREATE TABLE app_config_new (
                id INTEGER PRIMARY KEY,
                instance_id INTEGER,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                description TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(instance_id) REFERENCES instance (id)
            )
            """
        ))
        conn.execute(text(
            """
            INSERT INTO app_config_new (id, instance_id, key, value, description, created_at, updated_at)
            SELECT id, NULL as instance_id, key, value, description, created_at, updated_at
            FROM app_config
            """
        ))
        conn.execute(text("DROP TABLE app_config"))
        conn.execute(text("ALTER TABLE app_config_new RENAME TO app_config"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()


def _ensure_model_table_columns(table_names: Iterable[str]) -> None:
    """Ensure sqlite tables have all columns defined in SQLModel metadata."""
    with engine.connect() as conn:
        for table_name in table_names:
            table = SQLModel.metadata.tables.get(table_name)
            if table is None:
                continue

            result = conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result.fetchall()}
            if not existing:
                continue

            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN "{column.name}" {col_type}'))

        conn.commit()


def _ensure_indexes() -> None:
    """Create performance-critical indexes that may be missing from older DBs.

    NOTE: SQLModel/SQLAlchemy won't retroactively create indexes for tables that
    already exist, so we enforce a small set here (idempotent).
    """
    index_statements = [
        # Data Browser + status endpoint hot paths (counts + per-instance filtering).
        "CREATE INDEX IF NOT EXISTS ix_customer_update_xml_instance_id ON customer_update_xml (instance_id)",
        "CREATE INDEX IF NOT EXISTS ix_version_history_instance_id ON version_history (instance_id)",
        "CREATE INDEX IF NOT EXISTS ix_instance_app_file_type_instance_id ON instance_app_file_type (instance_id)",
        "CREATE INDEX IF NOT EXISTS ix_instance_app_file_type_instance_sys_class_name ON instance_app_file_type (instance_id, sys_class_name)",
        "CREATE INDEX IF NOT EXISTS ix_instance_app_file_type_instance_available ON instance_app_file_type (instance_id, is_available_for_assessment)",
        # Common list ordering patterns.
        "CREATE INDEX IF NOT EXISTS ix_customer_update_xml_instance_sys_updated_on ON customer_update_xml (instance_id, sys_updated_on)",
        "CREATE INDEX IF NOT EXISTS ix_version_history_instance_sys_recorded_at ON version_history (instance_id, sys_recorded_at)",
        # Unique constraints: (instance_id, sn_sys_id) — prevents duplicate SN records per instance.
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_instance_app_file_type_instance_sn_sys_id ON instance_app_file_type (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_update_set_instance_sn_sys_id ON update_set (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_update_xml_instance_sn_sys_id ON customer_update_xml (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_version_history_instance_sn_sys_id ON version_history (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_metadata_customization_instance_sn_sys_id ON metadata_customization (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_instance_plugin_instance_sn_sys_id ON instance_plugin (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_plugin_view_instance_sn_sys_id ON plugin_view (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scope_instance_sn_sys_id ON scope (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_package_instance_sn_sys_id ON package (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_application_instance_sn_sys_id ON application (instance_id, sn_sys_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_table_definition_instance_sn_sys_id ON table_definition (instance_id, sn_sys_id)",
        # Durable integration run-state tables.
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_run_run_uid ON job_run (run_uid)",
        "CREATE INDEX IF NOT EXISTS ix_job_run_instance_module_type_status ON job_run (instance_id, module, job_type, status)",
        "CREATE INDEX IF NOT EXISTS ix_job_run_instance_created_at ON job_run (instance_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_job_event_run_created_at ON job_event (run_id, created_at)",
        # Run UID back-reference on per-data-type pull rows.
        "CREATE INDEX IF NOT EXISTS ix_instance_data_pull_run_uid ON instance_data_pull (run_uid)",
        # AppConfig instance-scoped overrides.
        "CREATE INDEX IF NOT EXISTS ix_app_config_instance_id ON app_config (instance_id)",
        "CREATE INDEX IF NOT EXISTS ix_app_config_key ON app_config (key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_config_global_key ON app_config (key) WHERE instance_id IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_config_instance_key ON app_config (instance_id, key) WHERE instance_id IS NOT NULL",
    ]
    with engine.connect() as conn:
        table_info_rows = conn.execute(text("PRAGMA table_info(instance_app_file_type)")).fetchall()
        table_columns = {row[1] for row in table_info_rows}
        if "is_default_for_assessment" in table_columns:
            index_statements.append(
                "CREATE INDEX IF NOT EXISTS ix_instance_app_file_type_instance_default ON instance_app_file_type (instance_id, is_default_for_assessment)"
            )
        for stmt in index_statements:
            conn.execute(text(stmt))

        # FeatureScanResult unique pair — only if table exists and has no duplicates.
        fsr_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='feature_scan_result'")
        ).first()
        if fsr_exists:
            dup_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT feature_id, scan_result_id FROM feature_scan_result"
                    "  GROUP BY feature_id, scan_result_id HAVING COUNT(*) > 1"
                    ")"
                )
            ).scalar() or 0
            if dup_count == 0:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_feature_scan_result_feature_scan_result"
                    " ON feature_scan_result (feature_id, scan_result_id)"
                ))

        conn.commit()


def _ensure_instance_app_file_type_defaults() -> None:
    """Set availability defaults for legacy rows after schema migration."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(instance_app_file_type)"))
        existing = {row[1] for row in result.fetchall()}
        if "is_available_for_assessment" not in existing:
            return
        if "is_default_for_assessment" not in existing:
            return

        rows = conn.execute(
            text(
                """
                SELECT id, sys_class_name, label, name, is_available_for_assessment, is_default_for_assessment
                  FROM instance_app_file_type
                """
            )
        ).fetchall()
        for row in rows:
            row_id, sys_class_name, label, name, is_available, is_default = row
            available_default = 1 if default_assessment_option_availability_for_instance_file_type(
                sys_class_name=sys_class_name,
                label=label,
                name=name,
            ) else 0
            selected_default = 1 if default_assessment_availability_for_instance_file_type(
                sys_class_name=sys_class_name,
                label=label,
                name=name,
            ) else 0

            update_fields = []
            params = {"row_id": row_id}

            if is_available is None:
                update_fields.append("is_available_for_assessment = :available_value")
                params["available_value"] = available_default
                is_available = available_default

            if is_default is None:
                update_fields.append("is_default_for_assessment = :default_value")
                params["default_value"] = selected_default
                is_default = selected_default

            if bool(is_default) and not bool(is_available):
                update_fields.append("is_default_for_assessment = 0")

            if update_fields:
                conn.execute(
                    text(
                        f"""
                        UPDATE instance_app_file_type
                           SET {", ".join(update_fields)}
                         WHERE id = :row_id
                        """
                    ),
                    params,
                )
        conn.commit()


def get_session():
    """Get a database session - used as FastAPI dependency"""
    with Session(engine) as session:
        yield session


def get_db_path() -> Path:
    """Return the path to the database file"""
    return DATA_DIR / "tech_assessment.db"
