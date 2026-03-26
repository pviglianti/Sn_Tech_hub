"""CSDM Ingestion Engine.

Provides table-by-table data ingestion from ServiceNow instances
with delta checkpointing, cancellation, and safe resume.

Usage::

    queue = start_ingestion_queue(
        instance_id=1,
        tables=["cmdb_ci_service_business", "cmdb_ci_service_technical"],
        mode="delta",
    )
    # ... later ...
    status = get_queue_status(instance_id=1)
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import traceback
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Session, select
from sqlalchemy import text

from ..database import engine, get_session
from ..models import Instance
from ..services.sn_client import ServiceNowClient, ServiceNowClientError
from ..services.sn_client_factory import create_client_for_instance
from ..services.sn_fetch_config import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCHES,
    INTER_BATCH_DELAY,
    MAX_RETRIES,
    RETRY_DELAYS,
    REQUEST_TIMEOUT,
    get_effective_config,
)
from ..services.integration_sync_runner import resolve_delta_decision
from ..services.sn_dictionary import extract_full_dictionary, validate_table_exists
from ..csdm_table_catalog import get_local_table_name, get_table_group, get_table_label
from ..models_sn import (
    SnTableRegistry,
    SnFieldMapping,
    SnIngestionState,
    SnJobLog,
    SnCustomTableRequest,
)

logger = logging.getLogger(__name__)

# Configuration imported from sn_fetch_config (shared with preflight pulls).

# ============================================
# SN Type -> SQLite Type Mapping
# ============================================

_SN_TYPE_MAP: Dict[str, str] = {
    "string": "TEXT",
    "glide_date_time": "TEXT",
    "glide_date": "TEXT",
    "glide_time": "TEXT",
    "integer": "INTEGER",
    "float": "REAL",
    "decimal": "REAL",
    "boolean": "INTEGER",
    "reference": "TEXT",
    "journal": "TEXT",
    "journal_input": "TEXT",
    "journal_list": "TEXT",
    "translated_text": "TEXT",
    "html": "TEXT",
    "url": "TEXT",
    "email": "TEXT",
    "phone_number_e164": "TEXT",
    "currency": "TEXT",
    "price": "TEXT",
    "sys_class_name": "TEXT",
    "guid": "TEXT",
    "GUID": "TEXT",
    "char": "TEXT",
    "choice": "TEXT",
    "conditions": "TEXT",
    "document_id": "TEXT",
    "domain_id": "TEXT",
    "ip_addr": "TEXT",
    "multi_two_lines": "TEXT",
    "script": "TEXT",
    "script_plain": "TEXT",
    "script_server": "TEXT",
    "template_value": "TEXT",
    "translated_field": "TEXT",
    "user_image": "TEXT",
    "compressed": "TEXT",
    "wiki_text": "TEXT",
    "workflow": "TEXT",
    "xml": "TEXT",
}


def sn_type_to_sqlite(sn_type: str) -> str:
    """Map a ServiceNow internal_type to a SQLite column type."""
    return _SN_TYPE_MAP.get(sn_type, "TEXT")


# ============================================
# In-Memory Queue Management
# ============================================

class CsdmIngestionJob:
    """Manages a single table ingestion job."""

    def __init__(
        self,
        instance_id: int,
        sn_table_name: str,
        mode: str = "delta",
        cancel_event: Optional[threading.Event] = None,
    ):
        self.instance_id = instance_id
        self.sn_table_name = sn_table_name
        self.mode = mode  # 'delta' or 'full_refresh'
        self.cancel_event = cancel_event or threading.Event()


class CsdmIngestionQueue:
    """Manages a sequential queue of table ingestion jobs per instance."""

    def __init__(self, instance_id: int):
        self.instance_id = instance_id
        self.queue: List[CsdmIngestionJob] = []
        self.current_job: Optional[CsdmIngestionJob] = None
        self.cancel_all_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.started_at: Optional[datetime] = None
        self.completed_tables: List[str] = []
        self.failed_tables: List[str] = []


# Global registry of active queues: instance_id -> CsdmIngestionQueue
_active_queues: Dict[int, CsdmIngestionQueue] = {}
_queues_lock = threading.Lock()


# ============================================
# DDL Helpers (SQLite mirror table management)
# ============================================

def _compute_schema_hash(fields: List[SnFieldMapping]) -> str:
    """Deterministic hash of field names + types for change detection."""
    parts = sorted(f"{f.sn_element}:{f.db_column_type}" for f in fields)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def table_exists(local_table_name: str) -> bool:
    """Check if a SQLite table exists."""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl"),
            {"tbl": local_table_name},
        )
        return result.fetchone() is not None


def create_mirror_table(
    local_table_name: str,
    field_mappings: List[SnFieldMapping],
) -> None:
    """Create a SQLite mirror table from a list of field mappings.

    The table always includes ``_sn_sys_id`` (TEXT, PRIMARY KEY),
    ``_instance_id`` (INTEGER), ``_ingested_at`` (TEXT), and
    ``_raw_json`` (TEXT) as management columns.
    """
    col_defs = [
        '"_sn_sys_id" TEXT NOT NULL',
        '"_instance_id" INTEGER NOT NULL',
        '"_ingested_at" TEXT',
        '"_raw_json" TEXT',
    ]
    for fm in field_mappings:
        col_name = fm.local_column
        col_type = fm.db_column_type or "TEXT"
        col_defs.append(f'"{col_name}" {col_type}')

    col_defs.append('PRIMARY KEY ("_sn_sys_id", "_instance_id")')
    ddl = f'CREATE TABLE IF NOT EXISTS "{local_table_name}" ({", ".join(col_defs)})'

    with engine.connect() as conn:
        conn.execute(text(ddl))
        # Create index on _instance_id for per-instance queries.
        conn.execute(text(
            f'CREATE INDEX IF NOT EXISTS "ix_{local_table_name}_instance" '
            f'ON "{local_table_name}" ("_instance_id")'
        ))
        conn.commit()

    logger.info("Created mirror table %s with %d columns", local_table_name, len(field_mappings))


def alter_mirror_table(
    local_table_name: str,
    new_fields: List[SnFieldMapping],
) -> int:
    """Add new columns to an existing mirror table.

    Returns the number of columns added.
    """
    added = 0
    with engine.connect() as conn:
        result = conn.execute(text(f'PRAGMA table_info("{local_table_name}")'))
        existing_cols = {row[1] for row in result.fetchall()}

        for fm in new_fields:
            if fm.local_column not in existing_cols:
                col_type = fm.db_column_type or "TEXT"
                conn.execute(text(
                    f'ALTER TABLE "{local_table_name}" ADD COLUMN "{fm.local_column}" {col_type}'
                ))
                added += 1

        conn.commit()

    if added:
        logger.info("Added %d new columns to %s", added, local_table_name)
    return added


def drop_mirror_table_data(local_table_name: str, instance_id: int) -> int:
    """Delete all rows for an instance from a mirror table. Returns count deleted."""
    if not table_exists(local_table_name):
        logger.info(
            "Skip clear for missing mirror table %s (instance=%s)",
            local_table_name,
            instance_id,
        )
        return 0

    with engine.connect() as conn:
        result = conn.execute(
            text(f'DELETE FROM "{local_table_name}" WHERE "_instance_id" = :iid'),
            {"iid": instance_id},
        )
        conn.commit()
        return result.rowcount if hasattr(result, "rowcount") else 0


def get_mirror_table_row_count(local_table_name: str, instance_id: int) -> int:
    """Count rows for a given instance in a mirror table."""
    if not table_exists(local_table_name):
        return 0
    with engine.connect() as conn:
        result = conn.execute(
            text(f'SELECT COUNT(*) FROM "{local_table_name}" WHERE "_instance_id" = :iid'),
            {"iid": instance_id},
        )
        row = result.fetchone()
        return row[0] if row else 0


def get_local_max_sys_updated_on(local_table_name: str, instance_id: int) -> Optional[str]:
    """Return the MAX(sys_updated_on) value from the local mirror table.

    This is the authoritative delta watermark — more reliable than a stored
    checkpoint because it always reflects what's actually in the DB.
    Returns an SN-formatted datetime string or None if the table is empty.
    """
    if not table_exists(local_table_name):
        return None
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f'SELECT MAX("sys_updated_on") FROM "{local_table_name}" '
                f'WHERE "_instance_id" = :iid'
            ),
            {"iid": instance_id},
        )
        row = result.fetchone()
        return row[0] if row and row[0] else None


def get_sn_remote_count(
    client: ServiceNowClient, sn_table_name: str,
) -> int:
    """Query ServiceNow for the total record count in a table (no filter)."""
    try:
        return client.get_record_count(sn_table_name)
    except Exception as exc:
        logger.warning("Failed to get remote count for %s: %s", sn_table_name, exc)
        return 0


def upsert_batch(
    local_table_name: str,
    instance_id: int,
    records: List[dict],
    field_mappings: List[SnFieldMapping],
) -> tuple[int, int]:
    """Upsert a batch of records into the mirror table.

    Returns:
        (inserted_count, updated_count)
    """
    if not records:
        return 0, 0

    # Build column list.
    mgmt_cols = ["_sn_sys_id", "_instance_id", "_ingested_at", "_raw_json"]
    data_cols = [fm.local_column for fm in field_mappings]
    all_cols = mgmt_cols + data_cols

    col_list = ", ".join(f'"{c}"' for c in all_cols)
    placeholders = ", ".join(f":{c}" for c in all_cols)
    update_set = ", ".join(
        f'"{c}" = excluded."{c}"'
        for c in all_cols
        if c not in ("_sn_sys_id", "_instance_id")
    )

    sql = (
        f'INSERT INTO "{local_table_name}" ({col_list}) VALUES ({placeholders}) '
        f"ON CONFLICT (\"_sn_sys_id\", \"_instance_id\") DO UPDATE SET {update_set}"
    )

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    element_to_col = {fm.sn_element: fm.local_column for fm in field_mappings}

    rows = []
    for rec in records:
        sys_id = rec.get("sys_id", "")
        if not sys_id:
            continue

        row: dict = {
            "_sn_sys_id": sys_id,
            "_instance_id": instance_id,
            "_ingested_at": now_str,
            "_raw_json": json.dumps(rec),
        }

        for sn_el, local_col in element_to_col.items():
            value = rec.get(sn_el)
            # Normalize reference dicts to their value.
            if isinstance(value, dict):
                value = value.get("value", "")
            row[local_col] = value

        rows.append(row)

    if not rows:
        return 0, 0

    with engine.connect() as conn:
        conn.execute(text(sql), rows)
        conn.commit()

    # SQLite UPSERT doesn't easily distinguish inserts from updates,
    # so we report all as "inserted" for simplicity.
    return len(rows), 0


# ============================================
# Client Factory
# ============================================

def _get_client_for_instance(instance_id: int) -> tuple[ServiceNowClient, Instance]:
    """Create a ServiceNowClient from stored instance credentials."""
    with Session(engine) as session:
        instance = session.exec(select(Instance).where(Instance.id == instance_id)).first()
        if not instance:
            raise ValueError(f"Instance {instance_id} not found")
        client = create_client_for_instance(instance)
        return client, instance


# ============================================
# Schema Management
# ============================================

def ensure_schema_exists(
    instance_id: int,
    sn_table_name: str,
    client: ServiceNowClient,
) -> SnTableRegistry:
    """Ensure the local DB table exists for the given SN table.

    Creates it from dictionary if not present. Returns registry entry.
    """
    local_name = get_local_table_name(sn_table_name)

    with Session(engine) as session:
        # Check if already registered.
        registry = session.exec(
            select(SnTableRegistry)
            .where(SnTableRegistry.instance_id == instance_id)
            .where(SnTableRegistry.sn_table_name == sn_table_name)
        ).first()

        if registry and table_exists(local_name):
            # Table exists but may be missing columns added by a different
            # instance's dictionary.  Ensure every mapped column exists.
            existing_mappings = session.exec(
                select(SnFieldMapping)
                .where(SnFieldMapping.registry_id == registry.id)
                .where(SnFieldMapping.is_active == True)  # noqa: E712
            ).all()
            if existing_mappings:
                alter_mirror_table(local_name, list(existing_mappings))
            return registry

        # Extract dictionary from ServiceNow.
        dict_data = extract_full_dictionary(client, sn_table_name)
        if not dict_data:
            raise ServiceNowClientError(
                f"Table '{sn_table_name}' does not exist on the instance or dictionary extraction failed."
            )

        fields = dict_data["fields"]
        table_info = dict_data.get("table_info")
        parent_table = dict_data.get("parent_table")

        # Build field mappings.
        mappings: List[SnFieldMapping] = []
        for f_info in fields:
            local_col = f_info.element  # Use SN element name as local column name.
            db_type = sn_type_to_sqlite(f_info.internal_type)
            fm = SnFieldMapping(
                sn_element=f_info.element,
                local_column=local_col,
                sn_internal_type=f_info.internal_type,
                sn_max_length=f_info.max_length,
                sn_reference_table=f_info.reference_table if f_info.is_reference else None,
                db_column_type=db_type,
                is_reference=f_info.is_reference,
                is_primary_key=(f_info.element == "sys_id"),
                is_active=f_info.is_active,
                column_label=f_info.column_label,
                is_mandatory=f_info.is_mandatory,
                is_read_only=f_info.is_read_only,
                source_table=f_info.source_table,
            )
            mappings.append(fm)

        # Create or update registry.
        if not registry:
            registry = SnTableRegistry(
                instance_id=instance_id,
                sn_table_name=sn_table_name,
                local_table_name=local_name,
                priority_group=get_table_group(sn_table_name),
                display_label=get_table_label(sn_table_name),
                source="csdm",
                sn_table_label=table_info.label if table_info else None,
                parent_table=parent_table,
                parent_local_table=get_local_table_name(parent_table) if parent_table else None,
                is_custom=(get_table_group(sn_table_name) == "custom"),
                field_count=len(mappings),
                schema_version=1,
            )
            session.add(registry)
            session.flush()
        else:
            registry.field_count = len(mappings)
            registry.source = "csdm"
            registry.sn_table_label = table_info.label if table_info else None
            registry.parent_table = parent_table
            registry.parent_local_table = get_local_table_name(parent_table) if parent_table else None
            registry.updated_at = datetime.utcnow()
            session.add(registry)
            session.flush()

        # Persist field mappings (replace existing).
        existing_mappings = session.exec(
            select(SnFieldMapping).where(SnFieldMapping.registry_id == registry.id)
        ).all()
        for em in existing_mappings:
            session.delete(em)
        session.flush()

        for fm in mappings:
            fm.registry_id = registry.id
            session.add(fm)

        registry.schema_hash = _compute_schema_hash(mappings)
        registry.last_schema_refresh_at = datetime.utcnow()
        session.add(registry)
        session.commit()

        # Create/alter the physical SQLite table.
        if table_exists(local_name):
            alter_mirror_table(local_name, mappings)
        else:
            create_mirror_table(local_name, mappings)

        session.refresh(registry)
        return registry


# ============================================
# Query Building
# ============================================

def build_delta_query(last_updated_on_str: Optional[str]) -> str:
    """Return an SN encoded query string for delta pull.

    Includes ``ORDERBYsys_updated_on`` directly in the query string
    (ServiceNow encoded-query format) so records come back oldest-first.
    This ensures offset pagination works reliably and delta watermarks
    are correct.
    """
    if last_updated_on_str:
        return f"sys_updated_on>={last_updated_on_str}^ORDERBYsys_updated_on"
    return "ORDERBYsys_updated_on"


def build_full_query() -> str:
    """Return an SN encoded query for full refresh (no filter, oldest first)."""
    return "ORDERBYsys_updated_on"


# ============================================
# Batch Fetching with Retry
# ============================================

def fetch_batch_with_retry(
    client: ServiceNowClient,
    table_name: str,
    query: str,
    batch_size: int,
    offset: int,
    batch_num: int,
) -> List[dict]:
    """Fetch a batch using client.get_records() with retry/backoff.

    Uses the proven ``client.get_records()`` pattern (same as
    ``_iterate_batches``) which sends ``sysparm_order_by`` as a
    separate HTTP parameter — ensuring a stable sort for offset
    pagination.
    """
    for attempt in range(MAX_RETRIES):
        try:
            # ORDER BY is in the query string AND as sysparm_order_by.
            # Both say the same thing; SN uses whichever it prefers.
            return client.get_records(
                table=table_name,
                query=query,
                limit=batch_size,
                offset=offset,
                order_by="sys_updated_on",
                display_value="false",
            )
        except ServiceNowClientError:
            # Non-transient (auth, ACL, 404) -- don't retry.
            raise
        except Exception as exc:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                logger.warning(
                    "Batch %d attempt %d failed (%s), retrying in %ds",
                    batch_num, attempt + 1, exc, delay,
                )
                time.sleep(delay)
            else:
                raise ServiceNowClientError(
                    f"Failed to fetch batch {batch_num} after {MAX_RETRIES} retries: {exc}"
                ) from exc

    return []  # Unreachable, but satisfies type checker.


# ============================================
# Core Ingestion Function
# ============================================

def ingest_table(
    instance_id: int,
    sn_table_name: str,
    mode: str = "delta",
    cancel_event: Optional[threading.Event] = None,
) -> SnJobLog:
    """Core ingestion function for one table.

    Args:
        instance_id: Database ID of the Instance.
        sn_table_name: ServiceNow table API name.
        mode: ``'delta'`` for incremental or ``'full_refresh'`` for complete reload.
        cancel_event: Set to request cancellation after current batch.

    Returns:
        SnJobLog with the outcome.
    """
    cancel_event = cancel_event or threading.Event()

    # -- Create job log entry --
    with Session(engine) as session:
        job_log = SnJobLog(
            instance_id=instance_id,
            sn_table_name=sn_table_name,
            job_type=mode,
            status="started",
            started_at=datetime.utcnow(),
        )
        session.add(job_log)
        session.commit()
        session.refresh(job_log)
        job_log_id = job_log.id

    # Initialized before try so the except handler can always reference them.
    state_id: Optional[int] = None
    registry_id: Optional[int] = None

    try:
        # Step 1: Get ServiceNowClient.
        client, instance = _get_client_for_instance(instance_id)

        # Step 2: Ensure schema exists (dictionary extraction + DDL).
        registry = ensure_schema_exists(instance_id, sn_table_name, client)
        local_name = registry.local_table_name

        # Step 3: Get or create ingestion state.
        with Session(engine) as session:
            state = session.exec(
                select(SnIngestionState)
                .where(SnIngestionState.instance_id == instance_id)
                .where(SnIngestionState.sn_table_name == sn_table_name)
            ).first()

            if not state:
                state = SnIngestionState(
                    instance_id=instance_id,
                    sn_table_name=sn_table_name,
                )
                session.add(state)
                session.commit()
                session.refresh(state)

            state_id = state.id
            last_run_completed_at = state.last_run_completed_at

            # Load field mappings for upsert.
            mappings = session.exec(
                select(SnFieldMapping)
                .where(SnFieldMapping.registry_id == registry.id)
                .where(SnFieldMapping.is_active == True)  # noqa: E712
            ).all()
            mappings = list(mappings)

        # Step 3b: Fetch remote count (pre-flight) so UI can show SN Total.
        remote_count = get_sn_remote_count(client, sn_table_name)
        with Session(engine) as session:
            st = session.get(SnIngestionState, state_id)
            if st:
                st.last_remote_count = remote_count
                st.last_remote_count_at = datetime.utcnow()
                st.last_run_status = "in_progress"
                st.last_run_started_at = datetime.utcnow()
                st.updated_at = datetime.utcnow()
                session.add(st)
                session.commit()

        # Step 4: Build query string (filter only — ORDER BY is handled
        # by fetch_batch_with_retry via sysparm_order_by parameter).
        is_full_refresh_run = mode == "full_refresh"
        if is_full_refresh_run:
            # Drop existing data for full refresh.
            drop_mirror_table_data(local_name, instance_id)
            query = build_full_query()
        else:
            # Delta: use count + delta-probe strategy.
            local_max_ts = get_local_max_sys_updated_on(local_name, instance_id)
            local_count = get_mirror_table_row_count(local_name, instance_id)
            local_max_dt: Optional[datetime] = None
            delta_count: Optional[int] = None

            if local_max_ts:
                try:
                    local_max_dt = datetime.strptime(local_max_ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    logger.warning(
                        "Invalid local watermark format for %s: %s",
                        sn_table_name,
                        local_max_ts,
                    )

            if local_max_dt:
                logger.info(
                    "Delta for %s: local has %d rows, max sys_updated_on=%s, remote=%d",
                    sn_table_name, local_count, local_max_ts, remote_count,
                )
                delta_query = build_delta_query(local_max_ts)
                try:
                    delta_count = client.get_record_count(sn_table_name, delta_query)
                except Exception as exc:
                    logger.warning(
                        "Delta probe count failed for %s (%s), forcing full refresh",
                        sn_table_name, exc,
                    )
                    delta_count = None

            analysis = resolve_delta_decision(
                local_count=local_count,
                remote_count=remote_count,
                watermark=local_max_dt,
                delta_probe_count=delta_count,
            )
            logger.info(
                "Delta decision for %s: %s (%s)",
                sn_table_name,
                analysis.mode,
                analysis.reason,
            )

            if analysis.mode == "skip":
                _finalize_job(
                    job_log_id,
                    state_id,
                    registry.id,
                    instance_id,
                    "completed",
                    0,
                    0,
                    0,
                    local_max_ts,
                    None,
                    0.0,
                )
                with Session(engine) as session:
                    return session.get(SnJobLog, job_log_id)

            if analysis.mode == "full":
                is_full_refresh_run = True
                drop_mirror_table_data(local_name, instance_id)
                query = build_full_query()
            else:
                query = build_delta_query(local_max_ts)

        # Step 5: Paginated fetch loop.
        # Load effective config from Integration Properties (AppConfig) once
        # per pull, so admin-tuned batch_size / delay / max_batches apply.
        _cfg = get_effective_config(instance_id=instance_id)
        _batch_size = _cfg['batch_size']
        _inter_batch_delay = _cfg['inter_batch_delay']
        _max_batches = _cfg['max_batches']

        batch_num = 0
        total_inserted = 0
        total_updated = 0
        last_sys_updated_on: Optional[str] = None
        last_sys_id: Optional[str] = None
        start_time = time.time()

        offset = 0

        while batch_num < _max_batches:
            # Check cancellation before each batch.
            if cancel_event.is_set():
                logger.info("Cancellation requested for %s/%s", instance_id, sn_table_name)
                _finalize_job(job_log_id, state_id, registry.id, instance_id,
                              "cancelled", total_inserted, total_updated, batch_num,
                              last_sys_updated_on, last_sys_id, time.time() - start_time)
                with Session(engine) as session:
                    return session.get(SnJobLog, job_log_id)

            # Fetch using client.get_records() — order_by is passed
            # as a separate sysparm_order_by parameter (proven pattern).
            records = fetch_batch_with_retry(
                client, sn_table_name, query,
                _batch_size, offset, batch_num,
            )

            if not records:
                break

            # Upsert batch.
            inserted, updated = upsert_batch(local_name, instance_id, records, mappings)
            total_inserted += inserted
            total_updated += updated
            batch_num += 1

            # Track the cursor from the last record in this batch.
            last_record = records[-1]
            last_sys_updated_on = last_record.get("sys_updated_on")
            last_sys_id = last_record.get("sys_id")

            # Update job log + ingestion state progress (so UI polls see live counts).
            with Session(engine) as session:
                jl = session.get(SnJobLog, job_log_id)
                if jl:
                    jl.status = "in_progress"
                    jl.rows_inserted = total_inserted
                    jl.rows_updated = total_updated
                    jl.batches_processed = batch_num
                    session.add(jl)

                st = session.get(SnIngestionState, state_id)
                if st:
                    st.last_batch_inserted = total_inserted
                    st.last_batch_updated = total_updated
                    # Live row count from actual mirror table.
                    st.total_rows_in_db = get_mirror_table_row_count(local_name, instance_id)
                    st.updated_at = datetime.utcnow()
                    session.add(st)

                session.commit()

            logger.info(
                "%s batch %d: %d records fetched, %d upserted (%d total so far)",
                sn_table_name, batch_num, len(records), inserted,
                total_inserted + total_updated,
            )

            offset += _batch_size

            # Only stop when we get fewer records than requested --
            # this is the reliable SN signal that we've reached the
            # last page.  An empty batch (caught above) also stops.
            if len(records) < _batch_size:
                break

            # Polite pacing.
            time.sleep(_inter_batch_delay)

        if batch_num >= _max_batches:
            logger.warning(
                "Hit MAX_BATCHES (%d) for %s — possible infinite loop prevented",
                _max_batches, sn_table_name,
            )

        # Step 6: Finalize success.
        elapsed = time.time() - start_time
        _finalize_job(job_log_id, state_id, registry.id, instance_id,
                      "completed", total_inserted, total_updated, batch_num,
                      last_sys_updated_on, last_sys_id, elapsed,
                      is_full_refresh=is_full_refresh_run)

        logger.info(
            "Ingestion of %s complete: %d inserted, %d updated, %d batches in %.1fs",
            sn_table_name, total_inserted, total_updated, batch_num, elapsed,
        )

    except Exception as exc:
        error_msg = str(exc)
        error_stack = traceback.format_exc()
        logger.exception("Ingestion failed for %s/%s", instance_id, sn_table_name)

        with Session(engine) as session:
            jl = session.get(SnJobLog, job_log_id)
            if jl:
                jl.status = "failed"
                jl.completed_at = datetime.utcnow()
                jl.error_message = error_msg
                jl.error_stack = error_stack
                session.add(jl)

            # state_id may be None if the error happened before Step 3
            # (e.g. during ensure_schema_exists).  Fall back to a lookup
            # by (instance_id, sn_table_name) so we still mark the state
            # as failed instead of leaving it stuck at "queued".
            st = None
            if state_id:
                st = session.get(SnIngestionState, state_id)
            else:
                st = session.exec(
                    select(SnIngestionState)
                    .where(SnIngestionState.instance_id == instance_id)
                    .where(SnIngestionState.sn_table_name == sn_table_name)
                ).first()

            if st:
                st.last_run_status = "failed"
                st.last_run_completed_at = datetime.utcnow()
                st.last_error = error_msg
                st.updated_at = datetime.utcnow()
                session.add(st)

            session.commit()

    with Session(engine) as session:
        return session.get(SnJobLog, job_log_id)


def _finalize_job(
    job_log_id: int,
    state_id: int,
    registry_id: int,
    instance_id: int,
    status: str,
    total_inserted: int,
    total_updated: int,
    batches: int,
    last_sys_updated_on: Optional[str],
    last_sys_id: Optional[str],
    elapsed: float,
    is_full_refresh: bool = False,
) -> None:
    """Update job log, ingestion state, and registry after a run."""
    with Session(engine) as session:
        # Job log.
        jl = session.get(SnJobLog, job_log_id)
        if jl:
            jl.status = status
            jl.completed_at = datetime.utcnow()
            jl.rows_inserted = total_inserted
            jl.rows_updated = total_updated
            jl.batches_processed = batches
            session.add(jl)

        # Ingestion state.
        st = session.get(SnIngestionState, state_id)
        if st:
            st.last_run_status = status
            st.last_run_completed_at = datetime.utcnow()
            st.last_batch_inserted = total_inserted
            st.last_batch_updated = total_updated
            st.last_batch_duration_seconds = elapsed
            st.updated_at = datetime.utcnow()

            if status == "completed":
                # Update delta cursor.
                if last_sys_updated_on:
                    try:
                        st.last_successful_sys_updated_on = datetime.strptime(
                            last_sys_updated_on, "%Y-%m-%d %H:%M:%S"
                        )
                    except (ValueError, TypeError):
                        pass
                st.last_successful_sys_id = last_sys_id
                st.cumulative_rows_pulled += total_inserted + total_updated

                if is_full_refresh:
                    st.last_full_refresh_at = datetime.utcnow()
                else:
                    st.last_delta_at = datetime.utcnow()

                st.last_error = None

            session.add(st)

        # Update registry row count + state total_rows_in_db from
        # the actual mirror table so the UI always shows the real count.
        reg = session.get(SnTableRegistry, registry_id)
        actual_row_count: Optional[int] = None
        if reg:
            actual_row_count = get_mirror_table_row_count(reg.local_table_name, instance_id)
            reg.row_count = actual_row_count
            if not reg.first_ingested_at and status == "completed":
                reg.first_ingested_at = datetime.utcnow()
            reg.updated_at = datetime.utcnow()
            session.add(reg)

        # Sync the count back onto the state so the UI (which reads
        # from SnIngestionState) reflects the real DB count.
        if st and actual_row_count is not None:
            st.total_rows_in_db = actual_row_count
            session.add(st)

        session.commit()


# ============================================
# Queue Management
# ============================================

def _run_queue(queue: CsdmIngestionQueue) -> None:
    """Background thread target: process the queue sequentially."""
    while queue.queue and not queue.cancel_all_event.is_set():
        job = queue.queue.pop(0)
        queue.current_job = job

        # Wire up both cancel signals.
        combined_cancel = threading.Event()

        def _watch_cancel():
            while not combined_cancel.is_set():
                if job.cancel_event.is_set() or queue.cancel_all_event.is_set():
                    combined_cancel.set()
                    return
                time.sleep(0.5)

        watcher = threading.Thread(target=_watch_cancel, daemon=True)
        watcher.start()

        try:
            job_log = ingest_table(
                instance_id=queue.instance_id,
                sn_table_name=job.sn_table_name,
                mode=job.mode,
                cancel_event=combined_cancel,
            )
            if job_log and job_log.status == "completed":
                queue.completed_tables.append(job.sn_table_name)
            elif job_log and job_log.status in ("failed",):
                queue.failed_tables.append(job.sn_table_name)
        except Exception:
            logger.exception("Queue job failed for %s", job.sn_table_name)
            queue.failed_tables.append(job.sn_table_name)
        finally:
            combined_cancel.set()  # Stop the watcher.
            watcher.join(timeout=2)

        queue.current_job = None

    # Queue finished.
    with _queues_lock:
        _active_queues.pop(queue.instance_id, None)


def start_ingestion_queue(
    instance_id: int,
    tables: List[str],
    mode: str = "delta",
) -> CsdmIngestionQueue:
    """Start a sequential ingestion queue for the given tables.

    Returns the queue object for status tracking.
    """
    with _queues_lock:
        existing = _active_queues.get(instance_id)
        if existing and existing.thread and existing.thread.is_alive():
            raise RuntimeError(
                f"An ingestion queue is already running for instance {instance_id}. "
                "Cancel it first or wait for completion."
            )

    queue = CsdmIngestionQueue(instance_id=instance_id)
    queue.started_at = datetime.utcnow()

    for tbl in tables:
        job = CsdmIngestionJob(
            instance_id=instance_id,
            sn_table_name=tbl,
            mode=mode,
        )
        queue.queue.append(job)

    thread = threading.Thread(target=_run_queue, args=(queue,), daemon=True, name=f"csdm-q-{instance_id}")
    queue.thread = thread

    with _queues_lock:
        _active_queues[instance_id] = queue

    thread.start()
    logger.info("Started ingestion queue for instance %d: %s", instance_id, tables)
    return queue


# ============================================
# Cancel Functions
# ============================================

def cancel_current_job(instance_id: int) -> bool:
    """Cancel the currently running job for an instance.

    Returns True if a cancellation was signalled.
    """
    with _queues_lock:
        queue = _active_queues.get(instance_id)

    if not queue or not queue.current_job:
        return False

    queue.current_job.cancel_event.set()
    logger.info("Cancel requested for current job on instance %d", instance_id)
    return True


def cancel_all_jobs(instance_id: int) -> bool:
    """Cancel current + clear queue for an instance.

    Returns True if a cancellation was signalled.
    """
    with _queues_lock:
        queue = _active_queues.get(instance_id)

    if not queue:
        return False

    queue.cancel_all_event.set()
    if queue.current_job:
        queue.current_job.cancel_event.set()
    queue.queue.clear()
    logger.info("Cancel-all requested for instance %d", instance_id)
    return True


# ============================================
# Status & Monitoring
# ============================================

def get_queue_status(instance_id: int) -> dict:
    """Get current ingestion status for an instance."""
    with _queues_lock:
        queue = _active_queues.get(instance_id)

    if not queue:
        return {
            "instance_id": instance_id,
            "is_running": False,
            "current_table": None,
            "queued_tables": [],
            "completed_tables": [],
            "failed_tables": [],
            "started_at": None,
        }

    return {
        "instance_id": instance_id,
        "is_running": queue.thread.is_alive() if queue.thread else False,
        "current_table": queue.current_job.sn_table_name if queue.current_job else None,
        "current_mode": queue.current_job.mode if queue.current_job else None,
        "queued_tables": [j.sn_table_name for j in queue.queue],
        "completed_tables": list(queue.completed_tables),
        "failed_tables": list(queue.failed_tables),
        "started_at": queue.started_at.isoformat() if queue.started_at else None,
    }


# ============================================
# Custom Table Registration
# ============================================

def register_custom_table(instance_id: int, sn_table_name: str) -> SnCustomTableRequest:
    """Validate and register a custom table for ingestion."""
    client, instance = _get_client_for_instance(instance_id)

    # Check if already registered.
    with Session(engine) as session:
        existing = session.exec(
            select(SnCustomTableRequest)
            .where(SnCustomTableRequest.instance_id == instance_id)
            .where(SnCustomTableRequest.sn_table_name == sn_table_name)
        ).first()

        if existing:
            return existing

    # Validate the table exists on the instance.
    table_info = validate_table_exists(client, sn_table_name)

    with Session(engine) as session:
        req = SnCustomTableRequest(
            instance_id=instance_id,
            sn_table_name=sn_table_name,
            display_label=table_info.label if table_info else sn_table_name,
            status="validated" if table_info else "failed",
            validation_error=None if table_info else f"Table '{sn_table_name}' not found on instance.",
            requested_at=datetime.utcnow(),
            validated_at=datetime.utcnow() if table_info else None,
        )
        session.add(req)
        session.commit()
        session.refresh(req)

    if table_info:
        # Pre-create the schema so it is ready for ingestion.
        try:
            ensure_schema_exists(instance_id, sn_table_name, client)
            with Session(engine) as session:
                req = session.exec(
                    select(SnCustomTableRequest)
                    .where(SnCustomTableRequest.instance_id == instance_id)
                    .where(SnCustomTableRequest.sn_table_name == sn_table_name)
                ).first()
                if req:
                    req.status = "schema_created"
                    req.schema_created_at = datetime.utcnow()
                    session.add(req)
                    session.commit()
                    session.refresh(req)
        except Exception as exc:
            logger.exception("Schema creation failed for custom table %s", sn_table_name)
            with Session(engine) as session:
                req = session.exec(
                    select(SnCustomTableRequest)
                    .where(SnCustomTableRequest.instance_id == instance_id)
                    .where(SnCustomTableRequest.sn_table_name == sn_table_name)
                ).first()
                if req:
                    req.status = "failed"
                    req.validation_error = str(exc)
                    session.add(req)
                    session.commit()
                    session.refresh(req)

    return req


# ============================================
# Schema Refresh
# ============================================

def refresh_table_schema(instance_id: int, sn_table_name: str) -> dict:
    """Re-fetch dictionary and apply schema changes.

    Returns a summary dict with old and new field counts.
    """
    client, instance = _get_client_for_instance(instance_id)
    local_name = get_local_table_name(sn_table_name)

    with Session(engine) as session:
        registry = session.exec(
            select(SnTableRegistry)
            .where(SnTableRegistry.instance_id == instance_id)
            .where(SnTableRegistry.sn_table_name == sn_table_name)
        ).first()
        old_field_count = registry.field_count if registry else 0

    # Re-run ensure_schema_exists which handles the full dictionary + DDL flow.
    registry = ensure_schema_exists(instance_id, sn_table_name, client)

    return {
        "sn_table_name": sn_table_name,
        "local_table_name": local_name,
        "old_field_count": old_field_count,
        "new_field_count": registry.field_count,
        "schema_version": registry.schema_version,
        "schema_hash": registry.schema_hash,
    }


# ============================================
# Startup Recovery
# ============================================

def recover_interrupted_jobs() -> int:
    """On startup: reset stale states and sync row counts from mirror tables.

    Handles ``in_progress``, ``queued``, and ``started`` states that were
    left behind by a previous server run.  Also backfills
    ``total_rows_in_db`` from the actual mirror table counts so the UI
    always shows correct numbers even after an interruption.

    Returns the number of states reset.
    """
    count = 0
    with Session(engine) as session:
        # 1. Reset in_progress / queued ingestion states.
        stale_states = session.exec(
            select(SnIngestionState)
            .where(
                SnIngestionState.last_run_status.in_(
                    ["in_progress", "queued", "started"]
                )
            )
        ).all()

        for state in stale_states:
            state.last_run_status = "interrupted"
            state.last_error = "Server restarted while ingestion was in progress."
            state.updated_at = datetime.utcnow()
            session.add(state)
            count += 1

        # 2. Reset stale job logs.
        started_logs = session.exec(
            select(SnJobLog)
            .where(SnJobLog.status.in_(["started", "in_progress"]))
        ).all()

        for jl in started_logs:
            jl.status = "interrupted"
            jl.completed_at = datetime.utcnow()
            jl.error_message = "Server restarted while job was running."
            session.add(jl)

        # 3. Backfill total_rows_in_db on ALL states from actual mirror
        #    table counts.  This fixes states where the count was never
        #    written (e.g. old bug or interrupted finalization).
        all_states = session.exec(select(SnIngestionState)).all()
        for state in all_states:
            registry = session.exec(
                select(SnTableRegistry)
                .where(
                    SnTableRegistry.instance_id == state.instance_id,
                    SnTableRegistry.sn_table_name == state.sn_table_name,
                )
            ).first()
            if registry:
                real_count = get_mirror_table_row_count(
                    registry.local_table_name, state.instance_id,
                )
                if real_count != state.total_rows_in_db:
                    state.total_rows_in_db = real_count
                    session.add(state)
                # Also sync the registry
                if real_count != registry.row_count:
                    registry.row_count = real_count
                    session.add(registry)

        session.commit()

    if count:
        logger.info("Recovered %d interrupted CSDM ingestion states", count)
    return count
