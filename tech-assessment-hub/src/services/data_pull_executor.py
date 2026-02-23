"""
Data Pull Executor - Background execution of instance-level data pulls.

Similar to scan_executor.py but operates at the instance level,
pulling and caching ServiceNow configuration data for later use.
"""

from __future__ import annotations
import logging
import json
import uuid
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Type, Callable
import threading

from sqlmodel import Session, select
from sqlalchemy import text, or_, func


class DataPullMode(str, Enum):
    """Mode for data pull operations."""
    full = "full"
    delta = "delta"
    smart = "smart"

from .sn_client import ServiceNowClient, ServiceNowClientError
from .integration_sync_runner import resolve_delta_decision
from ..models import (
    Instance, InstanceDataPull, DataPullType, DataPullStatus,
    UpdateSet, CustomerUpdateXML, VersionHistory,
    MetadataCustomization, InstancePlugin, PluginView, Scope, Package, Application, TableDefinition,
    AppFileClass, InstanceAppFileType
)
from ..app_file_class_catalog import default_assessment_availability_for_instance_file_type
from ..table_registry_catalog import PREFLIGHT_SN_TABLE_MAP

logger = logging.getLogger(__name__)


def _parse_sn_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ServiceNow datetime format."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_sn_bool(value: Any) -> Optional[bool]:
    """Parse ServiceNow boolean value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _normalize_ref(value: Any) -> Optional[str]:
    """Normalize reference field value (could be dict with value/display_value)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("value") or value.get("display_value")
    return str(value) if value else None


def _normalize_ref_display(value: Any) -> Optional[str]:
    """Return display_value from a reference when available."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("display_value") or value.get("value")
    return str(value) if value else None


def _default_assessment_availability(
    sys_class_name: Optional[str],
    label: Optional[str],
    name: Optional[str],
) -> bool:
    return default_assessment_availability_for_instance_file_type(
        sys_class_name=sys_class_name,
        label=label,
        name=name,
    )


def _default_assessment_selected(
    sys_class_name: Optional[str],
    label: Optional[str],
    name: Optional[str],
) -> bool:
    return default_assessment_availability_for_instance_file_type(
        sys_class_name=sys_class_name,
        label=label,
        name=name,
    )


def _fetch_app_file_class_names(session: Session, instance_id: Optional[int] = None) -> List[str]:
    class_names: List[str] = []
    seen = set()

    if instance_id is not None:
        instance_rows = session.exec(
            select(InstanceAppFileType.sys_class_name)
            .where(InstanceAppFileType.instance_id == instance_id)
            .where(InstanceAppFileType.sys_class_name.is_not(None))
            .where(InstanceAppFileType.is_available_for_assessment == True)
        ).all()
        for row in instance_rows:
            value = row if isinstance(row, str) else (row[0] if row else None)
            normalized = (value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                class_names.append(normalized)
        if class_names:
            return class_names

    rows = session.exec(
        select(AppFileClass.sys_class_name)
        .where(AppFileClass.is_active == True)
        .order_by(AppFileClass.display_order.asc())
    ).all()
    for row in rows:
        value = row if isinstance(row, str) else (row[0] if row else None)
        normalized = (value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            class_names.append(normalized)
    return class_names


# ------------------------------------------------------------------
# DB-derived delta watermark
# ------------------------------------------------------------------

# Map DataPullType → (ORM model, sys_updated_on column) for the tables
# that support delta via sys_updated_on.  Tables not listed here (e.g.
# app_file_types, plugin_view, packages) fall back to the stored
# checkpoint in InstanceDataPull.last_sys_updated_on.
_WATERMARK_MAP: Dict[DataPullType, tuple] = {
    DataPullType.update_sets: (UpdateSet, UpdateSet.sys_updated_on),
    DataPullType.customer_update_xml: (CustomerUpdateXML, CustomerUpdateXML.sys_updated_on),
    DataPullType.version_history: (VersionHistory, VersionHistory.sys_updated_on),
    DataPullType.metadata_customization: (MetadataCustomization, MetadataCustomization.sys_updated_on),
    DataPullType.app_file_types: (InstanceAppFileType, InstanceAppFileType.sys_updated_on),
    DataPullType.scopes: (Scope, Scope.sys_updated_on),
    DataPullType.plugins: (InstancePlugin, InstancePlugin.sys_updated_on),
    DataPullType.plugin_view: (PluginView, PluginView.sys_updated_on),
    DataPullType.packages: (Package, Package.sys_updated_on),
    DataPullType.applications: (Application, Application.sys_updated_on),
    DataPullType.sys_db_object: (TableDefinition, TableDefinition.sys_updated_on),
}


def _get_db_derived_watermark(
    session: Session,
    instance_id: int,
    data_type: DataPullType,
) -> Optional[datetime]:
    """Compute MAX(sys_updated_on) from local data — authoritative watermark.

    This is more reliable than the stored checkpoint in
    ``InstanceDataPull.last_sys_updated_on`` because it always reflects
    what is actually in the DB (even after a truncated / interrupted pull).
    """
    entry = _WATERMARK_MAP.get(data_type)
    if not entry:
        return None

    model_class, ts_col = entry
    try:
        result = session.exec(
            select(func.max(ts_col)).where(
                model_class.instance_id == instance_id  # type: ignore[attr-defined]
            )
        ).first()
        return result  # type: ignore[return-value]
    except Exception as exc:
        logger.warning(
            "DB-derived watermark query failed for %s (instance %s): %s",
            data_type.value, instance_id, exc,
        )
        return None


def _set_expected_total(session: Session, pull: InstanceDataPull, total: Optional[int]) -> None:
    pull.expected_total = total
    pull.expected_total_at = datetime.utcnow() if total is not None else None
    pull.updated_at = datetime.utcnow()
    session.add(pull)
    session.commit()


def _get_local_cached_count(
    session: Session,
    instance_id: int,
    data_type: DataPullType,
) -> int:
    """Return local cached row count for a pull type."""
    entry = _WATERMARK_MAP.get(data_type)
    if not entry:
        return 0
    model_class = entry[0]
    try:
        return int(
            session.exec(
                select(func.count())
                .select_from(model_class)
                .where(model_class.instance_id == instance_id)  # type: ignore[attr-defined]
            ).one()
        )
    except Exception as exc:
        logger.warning(
            "Failed to compute local cached count for %s (instance %s): %s",
            data_type.value, instance_id, exc,
        )
        return 0


def _estimate_expected_total(
    session: Session,
    client: ServiceNowClient,
    data_type: DataPullType,
    since: Optional[datetime],
    instance_id: Optional[int] = None,
    inclusive: bool = True,
    version_state_filter: Optional[str] = None,
) -> Optional[int]:
    try:
        if data_type == DataPullType.update_sets:
            query = client.build_update_set_query(since=since, inclusive=inclusive)
            return client.get_record_count("sys_update_set", query)
        if data_type == DataPullType.customer_update_xml:
            query = client.build_customer_update_xml_query(since=since, inclusive=inclusive)
            return client.get_record_count("sys_update_xml", query)
        if data_type == DataPullType.version_history:
            query = client.build_version_history_query(since=since, inclusive=inclusive, state_filter=version_state_filter)
            return client.get_record_count("sys_update_version", query)
        if data_type == DataPullType.metadata_customization:
            class_names = _fetch_app_file_class_names(session, instance_id=instance_id)
            return client.get_metadata_customization_count(since=since, class_names=class_names, inclusive=inclusive)
        if data_type == DataPullType.app_file_types:
            query = client.build_app_file_types_query(since=since, inclusive=inclusive)
            return client.get_record_count("sys_app_file_type", query)
        if data_type == DataPullType.plugins:
            query = client.build_plugins_query(active_only=False, since=since, inclusive=inclusive)
            return client.get_record_count("sys_plugins", query)
        if data_type == DataPullType.plugin_view:
            query = client.build_plugin_view_query(active_only=False, since=since, inclusive=inclusive)
            return client.get_record_count("v_plugin", query)
        if data_type == DataPullType.scopes:
            query = client.build_scopes_query(active_only=False, since=since, inclusive=inclusive)
            return client.get_record_count("sys_scope", query)
        if data_type == DataPullType.packages:
            query = client.build_packages_query(since=since, inclusive=inclusive)
            return client.get_record_count("sys_package", query)
        if data_type == DataPullType.applications:
            query = client.build_applications_query(active_only=False, since=since, inclusive=inclusive)
            return client.get_record_count("sys_app", query)
        if data_type == DataPullType.sys_db_object:
            query = client.build_sys_db_object_query(since=since, inclusive=inclusive)
            return client.get_record_count("sys_db_object", query)
    except Exception as exc:
        logger.warning("Failed to estimate expected total for %s: %s", data_type.value, exc)
        return None
    return None


def _resolve_delta_pull_mode(
    session: Session,
    client: ServiceNowClient,
    instance_id: int,
    data_type: DataPullType,
    last_sync: Optional[datetime],
    watermark: Optional[datetime],
) -> Tuple[str, Optional[datetime], str, int, Optional[int], Optional[int]]:
    """Resolve delta execution to skip/delta/full using count+probe strategy."""
    local_count = _get_local_cached_count(session, instance_id, data_type)
    remote_total = _estimate_expected_total(
        session,
        client,
        data_type,
        since=None,
        instance_id=instance_id,
    )
    delta_probe_count = _estimate_expected_total(
        session,
        client,
        data_type,
        since=watermark,
        instance_id=instance_id,
        inclusive=False,
    )
    decision = resolve_delta_decision(
        local_count=local_count,
        remote_count=remote_total,
        watermark=watermark,
        delta_probe_count=delta_probe_count,
    )
    return (
        decision.mode,
        decision.since,
        decision.reason,
        decision.local_count,
        decision.remote_count,
        decision.delta_probe_count,
    )


def _get_or_create_data_pull(
    session: Session,
    instance_id: int,
    data_type: DataPullType
) -> InstanceDataPull:
    """Get existing data pull record or create new one."""
    pull = session.exec(
        select(InstanceDataPull)
        .where(InstanceDataPull.instance_id == instance_id)
        .where(InstanceDataPull.data_type == data_type)
    ).first()

    if not pull:
        pull = InstanceDataPull(
            instance_id=instance_id,
            data_type=data_type,
            status=DataPullStatus.idle
        )
        session.add(pull)
        session.commit()
        session.refresh(pull)

    return pull


def _start_pull(session: Session, pull: InstanceDataPull, run_uid: Optional[str] = None) -> None:
    """Mark a pull as started."""
    pull.status = DataPullStatus.running
    pull.started_at = datetime.utcnow()
    pull.completed_at = None
    pull.last_pulled_at = None
    pull.error_message = None
    pull.records_pulled = 0
    pull.cancel_requested = False
    pull.cancel_requested_at = None
    pull.expected_total = None
    pull.expected_total_at = None
    pull.run_uid = run_uid
    session.add(pull)
    session.commit()


def _complete_pull(session: Session, pull: InstanceDataPull, records: int, max_updated: Optional[datetime] = None) -> None:
    """Mark a pull as completed."""
    pull.status = DataPullStatus.completed
    pull.completed_at = datetime.utcnow()
    pull.last_pulled_at = datetime.utcnow()
    pull.records_pulled = records
    pull.updated_at = datetime.utcnow()
    if max_updated:
        pull.last_sys_updated_on = max_updated
    session.add(pull)
    session.commit()


def _fail_pull(session: Session, pull: InstanceDataPull, error: str) -> None:
    """Mark a pull as failed."""
    pull.status = DataPullStatus.failed
    pull.completed_at = datetime.utcnow()
    pull.error_message = error
    pull.updated_at = datetime.utcnow()
    session.add(pull)
    session.commit()


def _cancel_pull(session: Session, pull: InstanceDataPull, note: str = "Cancelled by user") -> None:
    """Mark a pull as cancelled."""
    pull.status = DataPullStatus.cancelled
    pull.completed_at = datetime.utcnow()
    pull.error_message = note
    pull.updated_at = datetime.utcnow()
    # Clear transient cancel flag so future pulls can start normally.
    pull.cancel_requested = False
    pull.cancel_requested_at = None
    session.add(pull)
    session.commit()


def _is_cancel_requested(session: Session, pull: Optional[InstanceDataPull]) -> bool:
    """Return True if a cancel was requested for this pull."""
    if not pull:
        return False
    try:
        session.refresh(pull)
    except Exception:
        return False
    return bool(pull.cancel_requested)


def _check_cancel_during_loop(
    session: Session,
    pull: Optional[InstanceDataPull],
    total_records: int,
    every: int = 200,
) -> bool:
    """Check for cancellation periodically during long loops."""
    if not pull or total_records == 0:
        return False
    if total_records % every != 0:
        return False
    if _is_cancel_requested(session, pull):
        _cancel_pull(session, pull)
        return True
    return False


def _update_pull_progress(session: Session, pull: Optional[InstanceDataPull], records: int) -> None:
    """Update progress counters during long-running pulls."""
    if not pull:
        return
    pull.records_pulled = records
    pull.updated_at = datetime.utcnow()
    session.add(pull)


def _cleanup_orphan_records(
    session: Session,
    instance_id: int,
    table_name: str,
    current_batch_id: str,
) -> int:
    """
    Delete records that were not seen in the current batch.

    This handles records that were deleted in ServiceNow or no longer match
    the query criteria. Only runs for full pulls.

    Returns:
        Number of records deleted
    """
    # Delete orphans (records with different batch_id or NULL batch_id)
    result = session.exec(
        text(f"""
            DELETE FROM {table_name}
            WHERE instance_id = :instance_id
            AND (sync_batch_id != :batch_id OR sync_batch_id IS NULL)
        """).bindparams(instance_id=instance_id, batch_id=current_batch_id)
    )
    session.commit()

    deleted_count = result.rowcount if hasattr(result, 'rowcount') else 0
    if deleted_count > 0:
        logger.info("Cleaned up %d orphan records from %s", deleted_count, table_name)

    return deleted_count


# ============================================
# PULL FUNCTIONS FOR EACH DATA TYPE
# ============================================

def _pull_update_sets(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull update sets and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_update_sets(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(UpdateSet)
                .where(UpdateSet.instance_id == instance_id)
                .where(UpdateSet.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                update_set = existing
            else:
                update_set = UpdateSet(instance_id=instance_id, sn_sys_id=sn_sys_id, name="")
                session.add(update_set)

            # Map fields
            update_set.name = record.get("name", "")
            update_set.description = record.get("description")
            update_set.state = record.get("state")
            update_set.application = _normalize_ref(record.get("application"))
            update_set.release_date = _parse_sn_datetime(record.get("release_date"))
            update_set.is_default = _parse_sn_bool(record.get("is_default")) or False
            update_set.completed_on = _parse_sn_datetime(record.get("completed_on"))
            update_set.completed_by = _normalize_ref(record.get("completed_by"))
            update_set.parent = _normalize_ref(record.get("parent"))
            update_set.origin_sys_id = _normalize_ref(record.get("origin_sys_id"))
            update_set.remote_sys_id = _normalize_ref(record.get("remote_sys_id"))
            update_set.merged_to = _normalize_ref(record.get("merged_to"))
            update_set.install_date = _parse_sn_datetime(record.get("install_date"))
            update_set.installed_from = record.get("installed_from")
            update_set.base_update_set = _normalize_ref(record.get("base_update_set"))
            update_set.batch_install_plan = _normalize_ref(record.get("batch_install_plan"))
            update_set.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            update_set.sys_created_by = record.get("sys_created_by")
            update_set.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            update_set.sys_updated_by = record.get("sys_updated_by")
            update_set.sys_mod_count = record.get("sys_mod_count")
            update_set.raw_data_json = json.dumps(record)
            update_set.last_refreshed_at = pulled_at
            update_set.sync_batch_id = batch_id

            # Track max updated timestamp
            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of update_sets, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch (handles deletions in SN)
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "update_set", batch_id)

    return total_records, max_updated


def _pull_customer_update_xml(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull customer update XML records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()
    update_set_cache: Dict[str, int] = {}
    missing_update_set_id: Optional[int] = None

    for batch in client.pull_customer_update_xml(since=since, include_payload=False):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue
            update_set_id: Optional[int] = None
            update_set_sn_sys_id = _normalize_ref(record.get("update_set")) or _normalize_ref(record.get("remote_update_set"))

            with session.no_autoflush:
                if update_set_sn_sys_id:
                    update_set_id = update_set_cache.get(update_set_sn_sys_id)
                    if update_set_id is None:
                        update_set = session.exec(
                            select(UpdateSet)
                            .where(UpdateSet.instance_id == instance_id)
                            .where(UpdateSet.sn_sys_id == update_set_sn_sys_id)
                        ).first()
                        if not update_set:
                            update_set = UpdateSet(
                                instance_id=instance_id,
                                sn_sys_id=update_set_sn_sys_id,
                                name="(unknown)"
                            )
                            session.add(update_set)
                            session.flush()
                        update_set_id = update_set.id
                        update_set_cache[update_set_sn_sys_id] = update_set_id
                else:
                    if missing_update_set_id is None:
                        fallback = session.exec(
                            select(UpdateSet)
                            .where(UpdateSet.instance_id == instance_id)
                            .where(UpdateSet.sn_sys_id == "__missing__")
                        ).first()
                        if not fallback:
                            fallback = UpdateSet(
                                instance_id=instance_id,
                                sn_sys_id="__missing__",
                                name="(missing update_set)"
                            )
                            session.add(fallback)
                            session.flush()
                        missing_update_set_id = fallback.id
                    update_set_id = missing_update_set_id

            with session.no_autoflush:
                existing = session.exec(
                    select(CustomerUpdateXML)
                    .where(CustomerUpdateXML.instance_id == instance_id)
                    .where(CustomerUpdateXML.sn_sys_id == sn_sys_id)
                ).first()

            if existing:
                cux = existing
            else:
                cux = CustomerUpdateXML(instance_id=instance_id, sn_sys_id=sn_sys_id, name="")
                session.add(cux)

            # Map fields
            cux.name = record.get("name", "")
            cux.action = record.get("action")
            cux.type = record.get("type")
            cux.target_name = record.get("target_name")
            cux.update_set_sn_sys_id = update_set_sn_sys_id
            cux.update_set_id = update_set_id
            cux.category = record.get("category")
            cux.update_guid = record.get("update_guid")
            cux.update_guid_history = record.get("update_guid_history")
            cux.application = _normalize_ref(record.get("application"))
            cux.comments = record.get("comments")
            cux.replace_on_upgrade = _parse_sn_bool(record.get("replace_on_upgrade"))
            cux.remote_update_set = _normalize_ref(record.get("remote_update_set"))
            cux.update_domain = _normalize_ref(record.get("update_domain"))
            cux.view = record.get("view")
            cux.table = record.get("table")
            cux.sys_recorded_at = _parse_sn_datetime(record.get("sys_recorded_at"))
            cux.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            cux.sys_created_by = record.get("sys_created_by")
            cux.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            cux.sys_updated_by = record.get("sys_updated_by")
            cux.sys_mod_count = record.get("sys_mod_count")
            cux.payload_hash = record.get("payload_hash")
            cux.raw_data_json = json.dumps(record)
            cux.last_refreshed_at = pulled_at
            cux.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of customer_update_xml, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "customer_update_xml", batch_id)

    return total_records, max_updated


def _pull_version_history(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
    state_filter: Optional[str] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull version history records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_version_history(since=since, state_filter=state_filter):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(VersionHistory)
                .where(VersionHistory.instance_id == instance_id)
                .where(VersionHistory.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                vh = existing
            else:
                vh = VersionHistory(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    name="",
                    sys_update_name=""
                )
                session.add(vh)

            # Map fields
            vh.name = record.get("name", "")
            vh.sys_update_name = record.get("name", "")  # name IS the sys_update_name
            vh.state = record.get("state")
            vh.source_table = _normalize_ref(record.get("source_table"))
            vh.source_sys_id = _normalize_ref(record.get("source"))
            vh.source_display = _normalize_ref(record.get("source_display"))
            vh.customer_update_sys_id = _normalize_ref(record.get("sys_customer_update"))
            vh.update_guid = record.get("update_guid")
            vh.update_guid_history = record.get("update_guid_history")
            vh.record_name = record.get("record_name")
            vh.action = record.get("action")
            vh.application = _normalize_ref(record.get("application"))
            vh.file_path = record.get("file_path")
            vh.instance_id_sn = record.get("instance_id")
            vh.instance_name = record.get("instance_name")
            vh.reverted_from = _normalize_ref(record.get("reverted_from"))
            vh.type = record.get("type")
            vh.sys_tags = record.get("sys_tags")
            vh.payload_hash = record.get("payload_hash")
            vh.sys_recorded_at = _parse_sn_datetime(record.get("sys_recorded_at"))
            vh.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            vh.sys_created_by = record.get("sys_created_by")
            vh.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            vh.sys_updated_by = record.get("sys_updated_by")
            vh.sys_mod_count = record.get("sys_mod_count")
            vh.raw_data_json = json.dumps(record)
            vh.last_refreshed_at = pulled_at
            vh.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on")) or _parse_sn_datetime(record.get("sys_recorded_at"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of version_history, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "version_history", batch_id)

    return total_records, max_updated


def _pull_metadata_customizations(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
    class_names: Optional[List[str]] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull metadata customization records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    if class_names is None:
        class_names = _fetch_app_file_class_names(session, instance_id=instance_id)

    for batch in client.pull_metadata_customizations(since=since, class_names=class_names):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(MetadataCustomization)
                .where(MetadataCustomization.instance_id == instance_id)
                .where(MetadataCustomization.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                mc = existing
            else:
                mc = MetadataCustomization(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    sys_metadata_sys_id="",
                    sys_update_name=""
                )
                session.add(mc)

            # Map fields
            mc.sys_metadata_sys_id = _normalize_ref(record.get("sys_metadata")) or ""
            mc.sys_update_name = record.get("sys_update_name", "")
            mc.author_type = record.get("author_type")
            mc.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            mc.sys_created_by = record.get("sys_created_by")
            mc.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            mc.sys_updated_by = record.get("sys_updated_by")
            mc.raw_data_json = json.dumps(record)
            mc.last_refreshed_at = pulled_at
            mc.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of metadata_customization, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "metadata_customization", batch_id)

    return total_records, max_updated


def _pull_app_file_types(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull sys_app_file_type records and upsert into database."""
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_app_file_types(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated

        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(InstanceAppFileType)
                .where(InstanceAppFileType.instance_id == instance_id)
                .where(InstanceAppFileType.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                app_file_type = existing
            else:
                app_file_type = InstanceAppFileType(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                )
                session.add(app_file_type)

            source_table_ref = record.get("sys_source_table")
            parent_table_ref = record.get("sys_parent_table")
            sys_class_name = (
                _normalize_ref_display(source_table_ref)
                or record.get("sys_class_name")
                or record.get("name")
            )

            app_file_type.sys_class_name = str(sys_class_name).strip() if sys_class_name else None
            app_file_type.name = record.get("name")
            app_file_type.label = record.get("label") or record.get("name")
            if existing is None or app_file_type.is_available_for_assessment is None:
                app_file_type.is_available_for_assessment = _default_assessment_availability(
                    app_file_type.sys_class_name,
                    app_file_type.label,
                    app_file_type.name,
                )
            if existing is None or app_file_type.is_default_for_assessment is None:
                app_file_type.is_default_for_assessment = _default_assessment_selected(
                    app_file_type.sys_class_name,
                    app_file_type.label,
                    app_file_type.name,
                )
            if not bool(app_file_type.is_available_for_assessment):
                app_file_type.is_default_for_assessment = False
            app_file_type.source_table = _normalize_ref(source_table_ref)
            app_file_type.source_table_name = _normalize_ref_display(source_table_ref)
            app_file_type.parent_table = _normalize_ref(parent_table_ref)
            app_file_type.parent_table_name = _normalize_ref_display(parent_table_ref)
            app_file_type.source_field = record.get("sys_source_field")
            app_file_type.parent_field = record.get("sys_parent_field")
            app_file_type.use_parent_scope = _parse_sn_bool(record.get("sys_use_parent_scope"))
            app_file_type.type = record.get("sys_type")
            app_file_type.children_provider_class = record.get("sys_children_provider_class")
            app_file_type.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            app_file_type.sys_created_by = record.get("sys_created_by")
            app_file_type.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            app_file_type.sys_updated_by = record.get("sys_updated_by")
            app_file_type.sys_mod_count = record.get("sys_mod_count")
            try:
                app_file_type.priority = int(record.get("priority")) if record.get("priority") is not None else None
            except (TypeError, ValueError):
                app_file_type.priority = None
            app_file_type.raw_data_json = json.dumps(record)
            app_file_type.last_refreshed_at = pulled_at
            app_file_type.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of app_file_types, total so far: %d", total_records)

    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "instance_app_file_type", batch_id)

    return total_records, max_updated


def _pull_plugins(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull plugin records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_plugins(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(InstancePlugin)
                .where(InstancePlugin.instance_id == instance_id)
                .where(InstancePlugin.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                plugin = existing
            else:
                plugin = InstancePlugin(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    plugin_id="",
                    name=""
                )
                session.add(plugin)

            # Map fields - 'source' field is the plugin_id
            plugin.plugin_id = record.get("source", "")
            plugin.name = record.get("name", "")
            plugin.version = record.get("version")
            plugin.state = record.get("state")
            plugin.description = record.get("description")
            plugin.vendor = record.get("vendor")
            plugin.active = _parse_sn_bool(record.get("active"))
            plugin.scope = _normalize_ref(record.get("scope"))
            plugin.parent = _normalize_ref(record.get("parent"))
            plugin.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            plugin.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            plugin.raw_data_json = json.dumps(record)
            plugin.last_refreshed_at = pulled_at
            plugin.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of plugins, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "instance_plugin", batch_id)

    return total_records, max_updated


def _pull_plugin_view(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull v_plugin records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_plugin_view(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(PluginView)
                .where(PluginView.instance_id == instance_id)
                .where(PluginView.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                plugin_view = existing
            else:
                plugin_view = PluginView(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                )
                session.add(plugin_view)

            plugin_view.plugin_id = record.get("id") or record.get("plugin_id")
            plugin_view.name = record.get("name")
            plugin_view.definition = record.get("definition")
            plugin_view.scope = _normalize_ref(record.get("scope"))
            plugin_view.version = record.get("version")
            plugin_view.active = _parse_sn_bool(record.get("active"))
            plugin_view.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            plugin_view.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            plugin_view.raw_data_json = json.dumps(record)
            plugin_view.last_refreshed_at = pulled_at
            plugin_view.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of plugin_view, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "plugin_view", batch_id)

    return total_records, max_updated


def _pull_scopes(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull scope records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_scopes(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(Scope)
                .where(Scope.instance_id == instance_id)
                .where(Scope.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                scope_rec = existing
            else:
                scope_rec = Scope(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    scope="",
                    name=""
                )
                session.add(scope_rec)

            # Map fields
            scope_rec.scope = record.get("scope", "")
            scope_rec.name = record.get("name", "")
            scope_rec.short_description = record.get("short_description")
            scope_rec.version = record.get("version")
            scope_rec.vendor = record.get("vendor")
            scope_rec.vendor_prefix = record.get("vendor_prefix")
            scope_rec.private = _parse_sn_bool(record.get("private"))
            scope_rec.licensable = _parse_sn_bool(record.get("licensable"))
            scope_rec.active = _parse_sn_bool(record.get("active")) or True
            scope_rec.source = record.get("source")
            scope_rec.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            scope_rec.sys_created_by = record.get("sys_created_by")
            scope_rec.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            scope_rec.sys_updated_by = record.get("sys_updated_by")
            scope_rec.raw_data_json = json.dumps(record)
            scope_rec.last_refreshed_at = pulled_at
            scope_rec.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of scopes, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "scope", batch_id)

    return total_records, max_updated


def _pull_packages(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull package records from sys_package and upsert into database.

    Note: sys_package is NOT OOTB web-accessible. If this fails, the admin
    needs to enable web access on the sys_db_object record for sys_package.
    """
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_packages(since=since if mode == "delta" else None):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(Package)
                .where(Package.instance_id == instance_id)
                .where(Package.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                pkg = existing
            else:
                pkg = Package(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    name=""
                )
                session.add(pkg)

            # Map fields from sys_package
            pkg.name = record.get("name", "")
            pkg.source = record.get("source")  # ID field - maps to plugin_id
            pkg.version = record.get("version")
            pkg.active = _parse_sn_bool(record.get("active")) if record.get("active") else True
            pkg.licensable = _parse_sn_bool(record.get("licensable"))
            pkg.trackable = _parse_sn_bool(record.get("trackable"))
            pkg.enforce_license = record.get("enforce_license")
            pkg.license_category = record.get("license_category")
            pkg.license_model = record.get("license_model")
            pkg.ide_created = record.get("ide_created")
            pkg.package_json = _normalize_ref(record.get("package_json"))
            pkg.sys_class_name = record.get("sys_class_name")
            pkg.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            pkg.sys_created_by = record.get("sys_created_by")
            pkg.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            pkg.sys_updated_by = record.get("sys_updated_by")
            pkg.sys_mod_count = record.get("sys_mod_count")
            pkg.raw_data_json = json.dumps(record)
            pkg.last_refreshed_at = pulled_at
            pkg.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of packages, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "package", batch_id)

    return total_records, max_updated


def _pull_applications(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull application records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_applications(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(Application)
                .where(Application.instance_id == instance_id)
                .where(Application.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                app = existing
            else:
                app = Application(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    name=""
                )
                session.add(app)

            app.name = record.get("name", "")
            app.scope = _normalize_ref(record.get("scope")) or _normalize_ref(record.get("sys_scope"))
            app.short_description = record.get("short_description")
            app.version = record.get("version")
            app.vendor = record.get("vendor")
            app.vendor_prefix = record.get("vendor_prefix")
            app.active = _parse_sn_bool(record.get("active"))
            app.source = record.get("source")
            app.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            app.sys_created_by = record.get("sys_created_by")
            app.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            app.sys_updated_by = record.get("sys_updated_by")
            app.raw_data_json = json.dumps(record)
            app.last_refreshed_at = pulled_at
            app.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of applications, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "application", batch_id)

    return total_records, max_updated


def _pull_sys_db_object(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull] = None,
) -> Tuple[int, Optional[datetime]]:
    """Pull sys_db_object records and upsert into database."""
    # Generate batch ID for tracking which records were seen in this pull
    batch_id = str(uuid.uuid4())

    total_records = 0
    max_updated = None
    pulled_at = datetime.utcnow()

    for batch in client.pull_sys_db_object(since=since):
        if _is_cancel_requested(session, pull):
            _cancel_pull(session, pull)
            return total_records, max_updated
        for record in batch:
            sn_sys_id = record.get("sys_id")
            if not sn_sys_id:
                continue

            existing = session.exec(
                select(TableDefinition)
                .where(TableDefinition.instance_id == instance_id)
                .where(TableDefinition.sn_sys_id == sn_sys_id)
            ).first()

            if existing:
                tbl = existing
            else:
                tbl = TableDefinition(
                    instance_id=instance_id,
                    sn_sys_id=sn_sys_id,
                    name=""
                )
                session.add(tbl)

            # Map key fields + store raw payload
            tbl.name = record.get("name", "")
            tbl.label = record.get("label")
            tbl.super_class = _normalize_ref(record.get("super_class"))
            tbl.sys_package = _normalize_ref(record.get("sys_package"))
            tbl.sys_scope = _normalize_ref(record.get("sys_scope"))
            tbl.access = record.get("access")
            tbl.extension_model = record.get("extension_model")
            tbl.is_extendable = _parse_sn_bool(record.get("is_extendable"))
            tbl.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
            tbl.sys_created_by = record.get("sys_created_by")
            tbl.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            tbl.sys_updated_by = record.get("sys_updated_by")
            tbl.sys_mod_count = record.get("sys_mod_count")
            tbl.raw_data_json = json.dumps(record)
            tbl.last_refreshed_at = pulled_at
            tbl.sync_batch_id = batch_id

            updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
            if updated_on and (max_updated is None or updated_on > max_updated):
                max_updated = updated_on

            total_records += 1
            if _check_cancel_during_loop(session, pull, total_records):
                session.commit()
                return total_records, max_updated

        _update_pull_progress(session, pull, total_records)
        session.commit()
        logger.info("Pulled batch of sys_db_object, total so far: %d", total_records)

    # Full mode: clean up records not seen in this batch
    if mode == "full":
        _cleanup_orphan_records(session, instance_id, "table_definition", batch_id)

    return total_records, max_updated


PullHandler = Callable[
    [
        Session,
        int,
        ServiceNowClient,
        Optional[datetime],
        str,
        Optional[InstanceDataPull],
        Optional[str],
    ],
    Tuple[int, Optional[datetime]],
]


@dataclass(frozen=True)
class DataPullSpec:
    """Single source of truth for DataPullType execution + UI metadata."""

    data_type: DataPullType
    sn_table_name: str
    label: str
    static_model: Optional[Type[Any]]
    pull_handler: PullHandler
    browser_columns: List[str]
    browser_order_by: Optional[Any]
    dictionary_participation: bool
    storage_table_name: str
    reference_rules: Dict[str, Dict[str, Any]]


def _sn_table_name_for_data_type(data_type: DataPullType) -> str:
    """Resolve SN table name from canonical preflight map (with explicit overrides)."""
    if data_type == DataPullType.plugin_view:
        return "v_plugin"
    value = PREFLIGHT_SN_TABLE_MAP.get(data_type.value)
    if value:
        return value
    raise ValueError(f"No SN table mapping configured for {data_type.value}")


def _dispatch_update_sets(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_update_sets(session, instance_id, client, since, mode, pull)


def _dispatch_customer_update_xml(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_customer_update_xml(session, instance_id, client, since, mode, pull)


def _dispatch_version_history(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_version_history(
        session,
        instance_id,
        client,
        since,
        mode,
        pull,
        state_filter=version_state_filter,
    )


def _dispatch_metadata_customization(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_metadata_customizations(session, instance_id, client, since, mode, pull)


def _dispatch_app_file_types(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_app_file_types(session, instance_id, client, since, mode, pull)


def _dispatch_plugins(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_plugins(session, instance_id, client, since, mode, pull)


def _dispatch_plugin_view(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_plugin_view(session, instance_id, client, since, mode, pull)


def _dispatch_scopes(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_scopes(session, instance_id, client, since, mode, pull)


def _dispatch_packages(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_packages(session, instance_id, client, since, mode, pull)


def _dispatch_applications(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_applications(session, instance_id, client, since, mode, pull)


def _dispatch_sys_db_object(
    session: Session,
    instance_id: int,
    client: ServiceNowClient,
    since: Optional[datetime],
    mode: str,
    pull: Optional[InstanceDataPull],
    _version_state_filter: Optional[str],
) -> Tuple[int, Optional[datetime]]:
    return _pull_sys_db_object(session, instance_id, client, since, mode, pull)


DATA_PULL_SPECS: Dict[DataPullType, DataPullSpec] = {
    DataPullType.update_sets: DataPullSpec(
        data_type=DataPullType.update_sets,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.update_sets),
        label="Update Sets",
        static_model=UpdateSet,
        pull_handler=_dispatch_update_sets,
        browser_columns=[
            "sn_sys_id", "name", "state", "application", "is_default",
            "completed_on", "sys_updated_on", "sys_updated_by", "last_refreshed_at",
        ],
        browser_order_by=UpdateSet.sys_updated_on,
        dictionary_participation=True,
        storage_table_name="update_set",
        reference_rules={
            "application": {"target_data_type": DataPullType.scopes, "target_field": "sn_sys_id"},
        },
    ),
    DataPullType.customer_update_xml: DataPullSpec(
        data_type=DataPullType.customer_update_xml,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.customer_update_xml),
        label="Update XML",
        static_model=CustomerUpdateXML,
        pull_handler=_dispatch_customer_update_xml,
        browser_columns=[
            "sn_sys_id", "name", "table", "type", "action", "target_name",
            "update_set_sn_sys_id", "category", "sys_updated_on",
            "sys_updated_by", "last_refreshed_at",
        ],
        browser_order_by=CustomerUpdateXML.sys_updated_on,
        dictionary_participation=True,
        storage_table_name="customer_update_xml",
        reference_rules={
            "update_set_id": {"target_data_type": DataPullType.update_sets, "target_field": "id"},
            "update_set_sn_sys_id": {"target_data_type": DataPullType.update_sets, "target_field": "sn_sys_id"},
            "table": {"target_data_type": DataPullType.sys_db_object, "target_field": "name"},
        },
    ),
    DataPullType.version_history: DataPullSpec(
        data_type=DataPullType.version_history,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.version_history),
        label="Version History",
        static_model=VersionHistory,
        pull_handler=_dispatch_version_history,
        browser_columns=[
            "sn_sys_id", "name", "state", "source_table", "source_sys_id",
            "update_guid", "record_name", "sys_updated_on",
            "sys_recorded_at", "last_refreshed_at",
        ],
        browser_order_by=VersionHistory.sys_recorded_at,
        dictionary_participation=True,
        storage_table_name="version_history",
        reference_rules={
            "source_sys_id": {
                "target_data_type": DataPullType.update_sets,
                "target_field": "sn_sys_id",
                "source_table_equals": "sys_update_set",
            },
            "customer_update_sys_id": {"target_data_type": DataPullType.customer_update_xml, "target_field": "target_sys_id"},
        },
    ),
    DataPullType.metadata_customization: DataPullSpec(
        data_type=DataPullType.metadata_customization,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.metadata_customization),
        label="Metadata Customization",
        static_model=MetadataCustomization,
        pull_handler=_dispatch_metadata_customization,
        browser_columns=[
            "sn_sys_id", "sys_update_name", "author_type",
            "sys_updated_on", "sys_updated_by", "last_refreshed_at",
        ],
        browser_order_by=MetadataCustomization.sys_updated_on,
        dictionary_participation=True,
        storage_table_name="metadata_customization",
        reference_rules={
            "sys_metadata_sys_id": {"target_data_type": DataPullType.customer_update_xml, "target_field": "target_sys_id"},
        },
    ),
    DataPullType.app_file_types: DataPullSpec(
        data_type=DataPullType.app_file_types,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.app_file_types),
        label="Application File Types",
        static_model=InstanceAppFileType,
        pull_handler=_dispatch_app_file_types,
        browser_columns=[
            "sn_sys_id", "sys_class_name", "label", "name",
            "source_table_name", "parent_table_name", "sys_updated_on", "last_refreshed_at",
        ],
        browser_order_by=InstanceAppFileType.sys_updated_on,
        dictionary_participation=True,
        storage_table_name="instance_app_file_type",
        reference_rules={
            "source_table": {"target_data_type": DataPullType.sys_db_object, "target_field": "sn_sys_id"},
            "source_table_name": {"target_data_type": DataPullType.sys_db_object, "target_field": "name"},
            "parent_table": {"target_data_type": DataPullType.sys_db_object, "target_field": "sn_sys_id"},
            "parent_table_name": {"target_data_type": DataPullType.sys_db_object, "target_field": "name"},
        },
    ),
    DataPullType.plugins: DataPullSpec(
        data_type=DataPullType.plugins,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.plugins),
        label="Plugins",
        static_model=InstancePlugin,
        pull_handler=_dispatch_plugins,
        browser_columns=[
            "sn_sys_id", "plugin_id", "name", "version",
            "state", "active", "scope", "sys_updated_on", "last_refreshed_at",
        ],
        browser_order_by=InstancePlugin.name,
        dictionary_participation=True,
        storage_table_name="instance_plugin",
        reference_rules={},
    ),
    DataPullType.plugin_view: DataPullSpec(
        data_type=DataPullType.plugin_view,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.plugin_view),
        label="Plugin Versions",
        static_model=PluginView,
        pull_handler=_dispatch_plugin_view,
        browser_columns=[
            "sn_sys_id", "plugin_id", "name", "definition",
            "scope", "version", "active", "sys_updated_on", "last_refreshed_at",
        ],
        browser_order_by=PluginView.name,
        dictionary_participation=False,
        storage_table_name="plugin_view",
        reference_rules={},
    ),
    DataPullType.scopes: DataPullSpec(
        data_type=DataPullType.scopes,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.scopes),
        label="Scopes",
        static_model=Scope,
        pull_handler=_dispatch_scopes,
        browser_columns=[
            "sn_sys_id", "scope", "name", "vendor",
            "version", "active", "sys_updated_on", "last_refreshed_at",
        ],
        browser_order_by=Scope.scope,
        dictionary_participation=True,
        storage_table_name="scope",
        reference_rules={},
    ),
    DataPullType.packages: DataPullSpec(
        data_type=DataPullType.packages,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.packages),
        label="Packages",
        static_model=Package,
        pull_handler=_dispatch_packages,
        browser_columns=[
            "sn_sys_id", "name", "source", "version",
            "active", "licensable", "trackable", "sys_updated_on", "last_refreshed_at",
        ],
        browser_order_by=Package.name,
        dictionary_participation=True,
        storage_table_name="package",
        reference_rules={},
    ),
    DataPullType.applications: DataPullSpec(
        data_type=DataPullType.applications,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.applications),
        label="Custom Applications",
        static_model=Application,
        pull_handler=_dispatch_applications,
        browser_columns=[
            "sn_sys_id", "name", "scope", "version",
            "vendor", "active", "sys_updated_on", "last_refreshed_at",
        ],
        browser_order_by=Application.name,
        dictionary_participation=True,
        storage_table_name="application",
        reference_rules={},
    ),
    DataPullType.sys_db_object: DataPullSpec(
        data_type=DataPullType.sys_db_object,
        sn_table_name=_sn_table_name_for_data_type(DataPullType.sys_db_object),
        label="Table Definitions",
        static_model=TableDefinition,
        pull_handler=_dispatch_sys_db_object,
        browser_columns=[
            "sn_sys_id", "name", "label", "super_class",
            "sys_package", "sys_scope", "sys_updated_on", "sys_updated_by", "last_refreshed_at",
        ],
        browser_order_by=TableDefinition.name,
        dictionary_participation=True,
        storage_table_name="table_definition",
        reference_rules={},
    ),
}


def get_data_pull_spec(data_type: DataPullType) -> DataPullSpec:
    spec = DATA_PULL_SPECS.get(data_type)
    if not spec:
        raise ValueError(f"Unknown data type: {data_type}")
    return spec


def get_data_type_labels() -> Dict[str, str]:
    return {spec.data_type.value: spec.label for spec in DATA_PULL_SPECS.values()}


def get_data_browser_config_map() -> Dict[DataPullType, Dict[str, Any]]:
    return {
        spec.data_type: {
            "model": spec.static_model,
            "columns": list(spec.browser_columns),
            "order_by": spec.browser_order_by,
        }
        for spec in DATA_PULL_SPECS.values()
        if spec.static_model is not None
    }


def get_data_browser_reference_rules() -> Dict[DataPullType, Dict[str, Dict[str, Any]]]:
    return {
        spec.data_type: spec.reference_rules
        for spec in DATA_PULL_SPECS.values()
        if spec.reference_rules
    }


def get_data_pull_type_to_sn_table() -> Dict[DataPullType, str]:
    return {spec.data_type: spec.sn_table_name for spec in DATA_PULL_SPECS.values()}


def get_data_pull_storage_tables() -> Dict[DataPullType, str]:
    return {spec.data_type: spec.storage_table_name for spec in DATA_PULL_SPECS.values()}


def get_assessment_preflight_data_types() -> List[DataPullType]:
    return list(DATA_PULL_SPECS.keys())


def get_assessment_preflight_model_map() -> Dict[DataPullType, Type[Any]]:
    return {
        spec.data_type: spec.static_model
        for spec in DATA_PULL_SPECS.values()
        if spec.static_model is not None
    }


# ============================================
# MAIN EXECUTOR FUNCTIONS
# ============================================

def execute_data_pull(
    session: Session,
    instance: Instance,
    client: ServiceNowClient,
    data_type: DataPullType,
    mode: str = "full",
    run_uid: Optional[str] = None,
    version_state_filter: Optional[str] = None,
) -> InstanceDataPull:
    """
    Execute a data pull for a specific data type.

    Args:
        session: Database session
        instance: Target instance
        client: ServiceNow client (already authenticated)
        data_type: Type of data to pull
        mode: "full" (replace all) or "delta" (since last pull)

    Returns:
        Updated InstanceDataPull record
    """
    pull = _get_or_create_data_pull(session, instance.id, data_type)
    if _is_cancel_requested(session, pull):
        _cancel_pull(session, pull)
        return pull

    effective_mode = mode
    decision_reason = "Explicit mode"
    local_count_for_decision = None
    remote_count_for_decision = None

    # Determine since timestamp and effective mode using shared decision contract.
    if mode == "delta" or mode == "smart":
        since = _get_db_derived_watermark(session, instance.id, data_type)
        if since is None:
            since = pull.last_sys_updated_on
        effective_mode, since, decision_reason, local_count_for_decision, remote_count_for_decision, _ = _resolve_delta_pull_mode(
            session=session,
            client=client,
            instance_id=instance.id,
            data_type=data_type,
            last_sync=pull.last_pulled_at,
            watermark=since,
        )
    else:
        # mode == "full"
        since = None

    _start_pull(session, pull, run_uid=run_uid)
    pull.sync_mode = effective_mode
    pull.sync_decision_reason = decision_reason
    pull.state_filter_applied = version_state_filter if data_type == DataPullType.version_history else None
    if local_count_for_decision is not None:
        pull.last_local_count = local_count_for_decision
    if remote_count_for_decision is not None:
        pull.last_remote_count = remote_count_for_decision
    pull.updated_at = datetime.utcnow()
    session.add(pull)
    session.commit()

    if effective_mode == "skip":
        _complete_pull(session, pull, records=0, max_updated=None)
        logger.info("Skipped pull of %s for instance %s: %s", data_type.value, instance.id, decision_reason)
        return pull

    expected_total = _estimate_expected_total(
        session, client, data_type, since, instance_id=instance.id,
        version_state_filter=version_state_filter,
    )
    if expected_total is not None:
        _set_expected_total(session, pull, expected_total)

    try:
        spec = get_data_pull_spec(data_type)
        records, max_updated = spec.pull_handler(
            session,
            instance.id,
            client,
            since,
            effective_mode,
            pull,
            version_state_filter,
        )

        session.refresh(pull)
        if pull.status == DataPullStatus.cancelled or pull.cancel_requested:
            _cancel_pull(session, pull)
            return pull

        _complete_pull(session, pull, records, max_updated)
        logger.info("Completed pull of %s for instance %s: %d records", data_type.value, instance.id, records)

    except Exception as exc:
        logger.exception("Data pull failed for %s on instance %s", data_type.value, instance.id)
        session.rollback()
        error_msg = str(exc)

        # Enhance error message for packages (sys_package) with web access instructions
        if data_type == DataPullType.packages and ("403" in error_msg or "forbidden" in error_msg.lower() or "404" in error_msg):
            instance_name = instance.url.replace("https://", "").replace("http://", "").replace(".service-now.com", "")
            web_access_link = f"{instance.url}/sys_db_object.do?sysparm_nostack=true&sysparm_refkey=name&sysparm_query=name=sys_package"
            error_msg = (
                f"{error_msg}\n\n"
                f"sys_package table requires web service access. "
                f"Have a system admin enable 'Allow access to this table via web services' on the Application Access tab:\n"
                f"{web_access_link}"
            )

        _fail_pull(session, pull, error_msg)

    return pull


def run_data_pulls_for_instance(
    session: Session,
    instance: Instance,
    client: ServiceNowClient,
    data_types: List[DataPullType],
    mode: DataPullMode = DataPullMode.full,
    cancel_event: Optional[threading.Event] = None,
    run_uid: Optional[str] = None,
    on_pull_start: Optional[Callable[[DataPullType, int, int], None]] = None,
    on_pull_complete: Optional[Callable[[DataPullType, InstanceDataPull, int, int], None]] = None,
    version_state_filter: Optional[str] = None,
) -> Dict[DataPullType, InstanceDataPull]:
    """
    Run multiple data pulls for an instance.

    Args:
        session: Database session
        instance: Target instance
        client: ServiceNow client
        data_types: List of data types to pull
        mode: DataPullMode.full or DataPullMode.delta

    Returns:
        Dict mapping data type to pull result
    """
    results = {}
    mode_str = mode.value if isinstance(mode, DataPullMode) else mode
    total = len(data_types)
    for index, data_type in enumerate(data_types, start=1):
        if cancel_event and cancel_event.is_set():
            break
        if on_pull_start:
            try:
                on_pull_start(data_type, index, total)
            except Exception as exc:
                logger.warning("on_pull_start callback failed for %s: %s", data_type.value, exc)
        results[data_type] = execute_data_pull(
            session,
            instance,
            client,
            data_type,
            mode_str,
            run_uid=run_uid,
            version_state_filter=version_state_filter if data_type == DataPullType.version_history else None,
        )
        if on_pull_complete:
            try:
                on_pull_complete(data_type, results[data_type], index, total)
            except Exception as exc:
                logger.warning("on_pull_complete callback failed for %s: %s", data_type.value, exc)
    return results
