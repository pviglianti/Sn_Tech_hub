# database.py - Database connection and setup

from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import text, event
from sqlalchemy.pool import NullPool
from pathlib import Path
import logging
import os
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

from .app_file_class_catalog import (
    default_assessment_availability_for_instance_file_type,
    default_assessment_option_availability_for_instance_file_type,
)

# Database file location
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR}/tech_assessment.db"

# Create engine with connection settings.
# NullPool prevents connection reuse across threads, avoiding SQLite lock
# contention when pipeline stages run concurrently in background threads.
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set to True to see SQL queries in console
    poolclass=NullPool,
    connect_args={"check_same_thread": False, "timeout": 30}  # Needed for SQLite with FastAPI
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA wal_autocheckpoint=1000;")
        # Performance tuning for the 22GB+ production DB on VM.
        # cache_size is negative = KB of RAM per connection (64MB).
        cursor.execute("PRAGMA cache_size=-65536;")
        # Memory-map up to 2.5GB of the DB — big win for random reads since
        # hot pages end up in OS page cache + skip syscall overhead.
        cursor.execute("PRAGMA mmap_size=2684354560;")
        # Temp tables + indices in RAM, not disk.
        cursor.execute("PRAGMA temp_store=MEMORY;")
        # Cap WAL growth; app-level checkpoint logic already runs periodically.
        cursor.execute("PRAGMA journal_size_limit=67108864;")
    except Exception:
        # On network mounts, WAL/pragma calls may fail — continue with defaults.
        pass
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
    from .services.llm import models as llm_models  # noqa: F401
    SQLModel.metadata.create_all(engine)
    engine.dispose()
    _ensure_instance_columns()
    engine.dispose()
    _ensure_app_config_instance_scope()
    engine.dispose()
    _ensure_model_table_columns([
        "instance",
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
        "llm_provider",
        "llm_model",
        "llm_auth_slot",
        # Scan configuration admin tables
        "global_app",
        "app_file_class",
        "app_file_class_query",
        "assessment_type_config",
        "assessment_type_file_class",
    ])
    _ensure_assessment_pipeline_defaults()
    _ensure_instance_app_file_type_defaults()
    _backfill_instance_app_file_class_ids()
    _ensure_indexes()
    # Create / update per-class artifact detail tables from ARTIFACT_DETAIL_DEFS.
    from .services.artifact_ddl import ensure_artifact_tables
    ensure_artifact_tables(engine)
    _startup_vacuum_check()


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
            is_partial = bool(idx[4]) if len(idx) > 4 else False
            if not is_unique:
                continue
            idx_cols = conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
            col_names = [c[2] for c in idx_cols]
            # Only treat a non-partial unique index on key as the legacy schema.
            # The migrated schema intentionally keeps a partial unique index on key
            # for global defaults where instance_id IS NULL.
            if col_names == ["key"] and not is_partial:
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


def _backfill_instance_app_file_class_ids() -> None:
    """Backfill app_file_class_id on InstanceAppFileType where sys_class_name matches."""
    with engine.connect() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='instance_app_file_type'")
        ).first()
        if not table_exists:
            return
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(instance_app_file_type)")).fetchall()}
        if "app_file_class_id" not in cols:
            return
    # Use the service-layer helper for proper logic
    from sqlmodel import Session as _Session
    from .services.app_file_class_sync import backfill_app_file_class_ids
    with _Session(engine) as session:
        updated = backfill_app_file_class_ids(session)
        if updated:
            import logging
            logging.getLogger(__name__).info("Backfilled app_file_class_id on %d instance_app_file_type rows", updated)


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
        # Classification hot-path: per-record lookups during classify_scan_results.
        "CREATE INDEX IF NOT EXISTS ix_customer_update_xml_instance_update_guid ON customer_update_xml (instance_id, update_guid)",
        "CREATE INDEX IF NOT EXISTS ix_customer_update_xml_instance_name ON customer_update_xml (instance_id, name)",
        "CREATE INDEX IF NOT EXISTS ix_version_history_instance_state_sys_update_name ON version_history (instance_id, state, sys_update_name)",
        "CREATE INDEX IF NOT EXISTS ix_version_history_instance_customer_update_sys_id ON version_history (instance_id, customer_update_sys_id)",
        # Covering indexes for classify_scan_results ORDER BY patterns — without
        # these SQLite picks the wrong index and does full scans.
        "CREATE INDEX IF NOT EXISTS ix_vh_classify_by_name ON version_history (instance_id, state, sys_update_name, sys_recorded_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_vh_classify_by_custsysid ON version_history (instance_id, customer_update_sys_id, sys_recorded_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_vh_earliest_by_name ON version_history (instance_id, sys_update_name, sys_recorded_at ASC, id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_vh_earliest_by_custsysid ON version_history (instance_id, customer_update_sys_id, sys_recorded_at ASC, id ASC)",
        "CREATE INDEX IF NOT EXISTS ix_metadata_customization_instance_sys_metadata ON metadata_customization (instance_id, sys_metadata_sys_id)",
        "CREATE INDEX IF NOT EXISTS ix_metadata_customization_instance_sys_update_name ON metadata_customization (instance_id, sys_update_name)",
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


# ---------------------------------------------------------------------------
# Database health: freelist monitoring + incremental vacuum
# ---------------------------------------------------------------------------

# Reclaim free pages when the freelist exceeds this fraction of total pages.
_VACUUM_FREELIST_THRESHOLD = 0.10  # 10%
# Max pages to reclaim per incremental vacuum call (keeps startup fast).
_INCREMENTAL_VACUUM_PAGES = 50_000  # ~200 MB at 4 KB page size


def get_db_health() -> Dict[str, Any]:
    """Return database size, page stats, freelist metrics, and WAL info."""
    db_path = DATA_DIR / "tech_assessment.db"
    wal_path = DATA_DIR / "tech_assessment.db-wal"
    file_size = db_path.stat().st_size if db_path.exists() else 0
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    with engine.connect() as conn:
        page_size = conn.execute(text("PRAGMA page_size")).scalar() or 4096
        page_count = conn.execute(text("PRAGMA page_count")).scalar() or 0
        freelist_count = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
        auto_vacuum = conn.execute(text("PRAGMA auto_vacuum")).scalar() or 0
        wal_autocheckpoint = conn.execute(text("PRAGMA wal_autocheckpoint")).scalar() or 0
    freelist_pct = (freelist_count / page_count * 100) if page_count else 0.0
    return {
        "file_size_bytes": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 1),
        "wal_size_bytes": wal_size,
        "wal_size_mb": round(wal_size / (1024 * 1024), 1),
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "freelist_pct": round(freelist_pct, 1),
        "auto_vacuum_mode": {0: "none", 1: "full", 2: "incremental"}.get(auto_vacuum, str(auto_vacuum)),
        "wal_autocheckpoint": wal_autocheckpoint,
    }


def run_incremental_vacuum(max_pages: Optional[int] = None) -> Dict[str, Any]:
    """Reclaim freelist pages via incremental vacuum.  Returns before/after stats."""
    pages = max_pages or _INCREMENTAL_VACUUM_PAGES
    with engine.connect() as conn:
        before = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
        conn.execute(text(f"PRAGMA incremental_vacuum({pages})"))
        conn.commit()
        after = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
    reclaimed = before - after
    page_size = 4096
    logger.info("Incremental vacuum reclaimed %d pages (~%.1f MB), freelist: %d -> %d",
                reclaimed, reclaimed * page_size / (1024 * 1024), before, after)
    return {"before": before, "after": after, "reclaimed": reclaimed}


_WAL_CHECKPOINT_THRESHOLD_MB = 50  # Attempt WAL checkpoint if WAL exceeds this size


def _startup_vacuum_check() -> None:
    """Run at startup: log DB health, checkpoint WAL if large, reclaim freelist."""
    try:
        health = get_db_health()
        logger.info(
            "DB health: %.1f MB on disk, WAL %.1f MB, freelist %.1f%% (%d pages), auto_vacuum=%s",
            health["file_size_mb"], health["wal_size_mb"], health["freelist_pct"],
            health["freelist_count"], health["auto_vacuum_mode"],
        )

        # Checkpoint WAL if it's grown too large.
        if health["wal_size_mb"] > _WAL_CHECKPOINT_THRESHOLD_MB:
            logger.warning(
                "WAL is %.1f MB (threshold %d MB) — attempting TRUNCATE checkpoint...",
                health["wal_size_mb"], _WAL_CHECKPOINT_THRESHOLD_MB,
            )
            wal_result = run_wal_checkpoint()
            logger.info("WAL checkpoint result: %s", wal_result)

        if health["freelist_pct"] > _VACUUM_FREELIST_THRESHOLD * 100:
            logger.warning(
                "Freelist at %.1f%% — running incremental vacuum (up to %d pages)...",
                health["freelist_pct"], _INCREMENTAL_VACUUM_PAGES,
            )
            result = run_incremental_vacuum()
            logger.info("Startup vacuum done: reclaimed %d pages", result["reclaimed"])
    except Exception:
        logger.exception("Startup vacuum check failed (non-fatal)")


def run_wal_checkpoint() -> Dict[str, Any]:
    """Attempt a TRUNCATE WAL checkpoint to merge WAL back into the main DB.

    Returns checkpoint result and before/after WAL sizes.
    A busy result (mode=1) is non-fatal — the next startup will retry.
    """
    wal_path = DATA_DIR / "tech_assessment.db-wal"
    before_size = wal_path.stat().st_size if wal_path.exists() else 0
    with engine.connect() as conn:
        row = conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
        mode, pages_written, pages_checkpointed = row if row else (-1, -1, -1)
    after_size = wal_path.stat().st_size if wal_path.exists() else 0
    status = "ok" if mode == 0 else "busy" if mode == 1 else "error"
    result = {
        "status": status,
        "mode": mode,
        "pages_written": pages_written,
        "pages_checkpointed": pages_checkpointed,
        "before_wal_mb": round(before_size / (1024 * 1024), 1),
        "after_wal_mb": round(after_size / (1024 * 1024), 1),
    }
    if mode != 0:
        logger.warning("WAL checkpoint returned %s (mode=%d) — will retry next startup", status, mode)
    return result


def get_session():
    """Get a database session - used as FastAPI dependency"""
    with Session(engine) as session:
        yield session


def get_db_path() -> Path:
    """Return the path to the database file"""
    return DATA_DIR / "tech_assessment.db"
