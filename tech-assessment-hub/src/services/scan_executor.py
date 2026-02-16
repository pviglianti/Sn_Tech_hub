from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select
from sqlalchemy import text, func, or_

import logging

from .query_builder import (
    build_metadata_query,
    build_metadata_query_variants,
    build_update_xml_query,
    build_update_xml_query_variants,
    parse_list,
    resolve_assessment_drivers,
)
from .scan_rules import get_scan_rules, reload_scan_rules
from .sn_client import ServiceNowClient, ServiceNowClientError
from ..models import (
    AppFileClass,
    Assessment,
    InstanceAppFileType,
    GlobalApp,
    OriginType,
    HeadOwner,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    MetadataCustomization,
    VersionHistory,
    CustomerUpdateXML,
    UpdateSet,
)


def _parse_sn_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _is_scan_cancel_requested(session: Session, scan: Scan) -> bool:
    try:
        session.refresh(scan)
    except Exception:
        return False
    return bool(getattr(scan, "cancel_requested", False))


def _cancel_scan(session: Session, scan: Scan, note: str = "Cancelled by user") -> None:
    scan.status = ScanStatus.cancelled
    scan.completed_at = datetime.utcnow()
    scan.error_message = note
    session.add(scan)
    session.commit()


def _fetch_app_file_classes(
    session: Session,
    class_names: List[str],
    instance_id: Optional[int] = None,
) -> List[AppFileClass]:
    base_rows = list(
        session.exec(
            select(AppFileClass).where(AppFileClass.is_active == True).order_by(AppFileClass.display_order.asc())
        ).all()
    )
    base_map = {row.sys_class_name: row for row in base_rows}

    instance_rows: List[InstanceAppFileType] = []
    if instance_id is not None:
        instance_rows = list(
            session.exec(
                select(InstanceAppFileType)
                .where(InstanceAppFileType.instance_id == instance_id)
                .where(InstanceAppFileType.sys_class_name.is_not(None))
                .order_by(InstanceAppFileType.priority.asc(), InstanceAppFileType.sys_class_name.asc())
            ).all()
        )

    if class_names:
        ordered_names = class_names
    elif instance_rows:
        seen = set()
        all_names: List[str] = []
        for row in instance_rows:
            class_name = (row.sys_class_name or "").strip()
            if not class_name or class_name in seen:
                continue
            seen.add(class_name)
            all_names.append(class_name)
        important_names = [name for name in all_names if base_map.get(name) and base_map[name].is_important]
        ordered_names = important_names or all_names
    else:
        ordered_names = [row.sys_class_name for row in base_rows]

    dynamic_map = {
        (row.sys_class_name or "").strip(): row
        for row in instance_rows
        if (row.sys_class_name or "").strip()
    }

    resolved: List[AppFileClass] = []
    for class_name in ordered_names:
        base_row = base_map.get(class_name)
        if base_row:
            resolved.append(base_row)
            continue

        dynamic_row = dynamic_map.get(class_name)
        if dynamic_row:
            resolved.append(
                AppFileClass(
                    sys_class_name=class_name,
                    label=dynamic_row.label or dynamic_row.name or class_name,
                    target_table_field=dynamic_row.source_field,
                    has_script=True,
                    is_important=False,
                    display_order=dynamic_row.priority or 9999,
                    is_active=True,
                )
            )
    return resolved


def _get_global_app(session: Session, assessment: Assessment) -> Optional[GlobalApp]:
    if assessment.assessment_type.value != "global_app":
        return None
    if not assessment.target_app_id:
        return None
    return session.get(GlobalApp, assessment.target_app_id)


def _lookup_version_history(client: ServiceNowClient, sys_update_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sys_update_name:
        return None
    try:
        records = client.get_records(
            table="sys_update_version",
            query=f"name={sys_update_name}^state=current",
            fields=[
                "sys_id",
                "source_table",
                "source",
                "source_display",
                "sys_recorded_at",
                "sys_created_on",
                "sys_created_by",
            ],
            limit=1,
            order_by="sys_recorded_at",
        )
        return records[0] if records else None
    except ServiceNowClientError:
        return None


def _normalize_version_ref(value: Any) -> str:
    if isinstance(value, dict):
        display_value = value.get("display_value")
        raw_value = value.get("value")
        if isinstance(display_value, str) and display_value.strip():
            return display_value.strip()
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _is_ootb_reverted_current(version_record: Optional[Dict[str, Any]]) -> bool:
    if not version_record:
        return False

    source_table = _normalize_version_ref(version_record.get("source_table")).lower()
    source = _normalize_version_ref(version_record.get("source")).lower()
    source_display = _normalize_version_ref(version_record.get("source_display")).lower()

    values = [source_table, source, source_display]
    for value in values:
        if not value:
            continue
        if "sys_store_app" in value:
            return True
        if "sys_upgrade_history" in value:
            return True
        if value == "store" or value.startswith("store "):
            return True
        if value == "upgrade" or value.startswith("upgrade "):
            return True
        if value.startswith("store application") or "store application" in value:
            return True
        if value.startswith("system upgrade") or "system upgrade" in value:
            return True
    return False


def _is_store_application_current(version_record: Optional[Dict[str, Any]]) -> bool:
    """
    Backward-compatible helper retained for tests/imports.
    Now covers current OOTB reversion sources, including system upgrades.
    """
    return _is_ootb_reverted_current(version_record)


def _has_metadata_customization(client: ServiceNowClient, sys_metadata_sys_id: Optional[str]) -> bool:
    if not sys_metadata_sys_id:
        return False
    try:
        count = client.get_record_count("sys_metadata_customization", f"sys_metadata={sys_metadata_sys_id}")
        return count > 0
    except ServiceNowClientError:
        return False


def _version_history_count(client: ServiceNowClient, sys_update_name: Optional[str]) -> int:
    if not sys_update_name:
        return 0
    try:
        return client.get_record_count("sys_update_version", f"name={sys_update_name}")
    except ServiceNowClientError:
        return 0


def _baseline_changed_from_version_history(
    client: ServiceNowClient,
    sys_update_name: Optional[str],
    current_version_record: Optional[Dict[str, Any]],
) -> bool:
    if not current_version_record:
        return False
    if _is_ootb_reverted_current(current_version_record):
        return False
    return _version_history_count(client, sys_update_name) > 1


def _lookup_version_history_local(
    session: Session,
    instance_id: int,
    sys_update_name: Optional[str],
    sys_metadata_sys_id: Optional[str],
) -> Optional[VersionHistory]:
    if not sys_update_name and not sys_metadata_sys_id:
        return None
    stmt = (
        select(VersionHistory)
        .where(VersionHistory.instance_id == instance_id)
        .where(func.lower(VersionHistory.state) == "current")
    )

    if sys_update_name and sys_metadata_sys_id:
        stmt = stmt.where(
            or_(
                VersionHistory.sys_update_name == sys_update_name,
                VersionHistory.customer_update_sys_id == sys_metadata_sys_id,
            )
        )
    elif sys_update_name:
        stmt = stmt.where(VersionHistory.sys_update_name == sys_update_name)
    else:
        stmt = stmt.where(VersionHistory.customer_update_sys_id == sys_metadata_sys_id)

    return session.exec(
        stmt.order_by(VersionHistory.sys_recorded_at.desc(), VersionHistory.id.desc())
    ).first()


def _lookup_customer_update_local(
    session: Session,
    instance_id: int,
    sys_update_name: Optional[str],
    version_row: Optional[VersionHistory],
) -> Optional[CustomerUpdateXML]:
    if version_row and version_row.update_guid:
        by_guid = session.exec(
            select(CustomerUpdateXML)
            .where(CustomerUpdateXML.instance_id == instance_id)
            .where(CustomerUpdateXML.update_guid == version_row.update_guid)
            .order_by(CustomerUpdateXML.sys_recorded_at.desc(), CustomerUpdateXML.sys_updated_on.desc(), CustomerUpdateXML.id.desc())
        ).first()
        if by_guid:
            return by_guid

    if not sys_update_name:
        return None

    return session.exec(
        select(CustomerUpdateXML)
        .where(CustomerUpdateXML.instance_id == instance_id)
        .where(CustomerUpdateXML.name == sys_update_name)
        .order_by(CustomerUpdateXML.sys_recorded_at.desc(), CustomerUpdateXML.sys_updated_on.desc(), CustomerUpdateXML.id.desc())
    ).first()


def _resolve_update_set_id_local(
    session: Session,
    instance_id: int,
    customer_update: CustomerUpdateXML,
) -> Optional[int]:
    if customer_update.update_set_id:
        return customer_update.update_set_id

    candidates = [customer_update.update_set_sn_sys_id, customer_update.remote_update_set]
    for sn_sys_id in candidates:
        if not sn_sys_id:
            continue
        update_set = session.exec(
            select(UpdateSet)
            .where(UpdateSet.instance_id == instance_id)
            .where(UpdateSet.sn_sys_id == sn_sys_id)
        ).first()
        if update_set:
            return update_set.id
    return None


def _has_metadata_customization_local(
    session: Session,
    instance_id: int,
    sys_metadata_sys_id: Optional[str],
    sys_update_name: Optional[str],
) -> bool:
    """Check for a metadata_customization record that indicates OOTB origin.

    Records with author_type='Custom' are customer-authored and do not
    indicate that the artifact is a modified OOTB record.
    """
    not_custom = MetadataCustomization.author_type != "Custom"

    if sys_metadata_sys_id:
        count = session.exec(
            select(func.count())
            .select_from(MetadataCustomization)
            .where(MetadataCustomization.instance_id == instance_id)
            .where(MetadataCustomization.sys_metadata_sys_id == sys_metadata_sys_id)
            .where(not_custom)
        ).one()
        if count > 0:
            return True

    if sys_update_name:
        count = session.exec(
            select(func.count())
            .select_from(MetadataCustomization)
            .where(MetadataCustomization.instance_id == instance_id)
            .where(MetadataCustomization.sys_update_name == sys_update_name)
            .where(not_custom)
        ).one()
        if count > 0:
            return True

    return False


def _version_history_count_local(
    session: Session,
    instance_id: int,
    sys_update_name: Optional[str],
    sys_metadata_sys_id: Optional[str],
) -> int:
    if not sys_update_name and not sys_metadata_sys_id:
        return 0

    stmt = (
        select(func.count())
        .select_from(VersionHistory)
        .where(VersionHistory.instance_id == instance_id)
    )

    if sys_update_name and sys_metadata_sys_id:
        stmt = stmt.where(
            or_(
                VersionHistory.sys_update_name == sys_update_name,
                VersionHistory.customer_update_sys_id == sys_metadata_sys_id,
            )
        )
    elif sys_update_name:
        stmt = stmt.where(VersionHistory.sys_update_name == sys_update_name)
    else:
        stmt = stmt.where(VersionHistory.customer_update_sys_id == sys_metadata_sys_id)

    count = session.exec(stmt).one()
    return int(count or 0)


def _baseline_changed_from_version_history_local(
    session: Session,
    instance_id: int,
    sys_update_name: Optional[str],
    sys_metadata_sys_id: Optional[str],
    current_version_record: Optional[Dict[str, Any]],
) -> bool:
    if not current_version_record:
        return False
    if _is_ootb_reverted_current(current_version_record):
        return False
    version_count = _version_history_count_local(
        session=session,
        instance_id=instance_id,
        sys_update_name=sys_update_name,
        sys_metadata_sys_id=sys_metadata_sys_id,
    )
    return version_count > 1


def _lookup_earliest_version_history_local(
    session: Session,
    instance_id: int,
    sys_update_name: Optional[str],
    sys_metadata_sys_id: Optional[str],
) -> Optional[VersionHistory]:
    """Look up the earliest (first) version history record for an artifact."""
    if not sys_update_name and not sys_metadata_sys_id:
        return None
    stmt = (
        select(VersionHistory)
        .where(VersionHistory.instance_id == instance_id)
    )

    if sys_update_name and sys_metadata_sys_id:
        stmt = stmt.where(
            or_(
                VersionHistory.sys_update_name == sys_update_name,
                VersionHistory.customer_update_sys_id == sys_metadata_sys_id,
            )
        )
    elif sys_update_name:
        stmt = stmt.where(VersionHistory.sys_update_name == sys_update_name)
    else:
        stmt = stmt.where(VersionHistory.customer_update_sys_id == sys_metadata_sys_id)

    return session.exec(
        stmt.order_by(VersionHistory.sys_recorded_at.asc(), VersionHistory.id.asc())
    ).first()


def _version_row_to_record(version_row: Optional[VersionHistory]) -> Optional[Dict[str, Any]]:
    if not version_row:
        return None
    return {
        "sys_id": version_row.sn_sys_id,
        "source_table": version_row.source_table,
        "source": version_row.source_sys_id,
        "source_display": version_row.source_display,
        "sys_recorded_at": version_row.sys_recorded_at.strftime("%Y-%m-%d %H:%M:%S") if version_row.sys_recorded_at else None,
    }


def _classify_origin(
    version_record: Optional[Dict[str, Any]],
    has_metadata_customization: bool,
    has_customer_update: bool = False,
    earliest_version_record: Optional[Dict[str, Any]] = None,
    changed_baseline_now: bool = False,
) -> Tuple[OriginType, HeadOwner]:
    """Classify a record's origin type per the Assessment Guide v3 decision tree.

    Decision tree (from assessment_guide_and_script_v3_pv.md):
        IF any OOB version exists:
            IF customer versions exist OR baseline changed → modified_ootb
            ELSE → ootb_untouched
        ELSE:
            IF customer versions exist OR baseline changed → net_new_customer
            ELSE → unknown_no_history
    """
    has_customer_signal = (
        has_metadata_customization or has_customer_update or changed_baseline_now
    )

    # 1. Current version is OOB (Store/Upgrade source) → OOB branch.
    if version_record and _is_ootb_reverted_current(version_record):
        if has_customer_signal:
            return OriginType.modified_ootb, HeadOwner.store_upgrade
        return OriginType.ootb_untouched, HeadOwner.store_upgrade

    # 2. Has metadata_customization record → was OOTB, customer changed it.
    if has_metadata_customization:
        return OriginType.modified_ootb, HeadOwner.store_upgrade

    # 3. Customer update or baseline changed → customization with no OOB current.
    if has_customer_update or changed_baseline_now:
        return OriginType.net_new_customer, HeadOwner.customer

    # 4. Fallback: check the earliest version history record.
    if earliest_version_record:
        if _is_ootb_reverted_current(earliest_version_record):
            return OriginType.modified_ootb, HeadOwner.store_upgrade
        source_table = _normalize_version_ref(
            earliest_version_record.get("source_table")
        ) or ""
        if "update_set" in str(source_table).lower():
            return OriginType.net_new_customer, HeadOwner.customer

    # 5. Has version history but can't classify → unknown.
    #    No history at all → unknown_no_history.
    has_any_history = version_record is not None or earliest_version_record is not None
    if has_any_history:
        return OriginType.unknown, HeadOwner.unknown
    return OriginType.unknown_no_history, HeadOwner.unknown


logger = logging.getLogger(__name__)


def _normalize_ref(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value") or value.get("display_value") or json.dumps(value)
    return value


def _existing_results_for_batch(session: Session, scan_id: int, sys_ids: List[str]) -> Dict[str, ScanResult]:
    if not sys_ids:
        return {}
    existing = session.exec(
        select(ScanResult).where(
            ScanResult.scan_id == scan_id,
            ScanResult.sys_id.in_(sys_ids),
        )
    ).all()
    return {result.sys_id: result for result in existing}


def _existing_results_for_assessment(session: Session, assessment_id: int, sys_ids: List[str]) -> Dict[str, ScanResult]:
    if not sys_ids:
        return {}
    existing = session.exec(
        select(ScanResult)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Scan.assessment_id == assessment_id)
        .where(ScanResult.sys_id.in_(sys_ids))
    ).all()
    return {f"{result.sys_id}:{result.table_name}": result for result in existing}


def _apply_since_filter(query: str, since: Optional[datetime], field: str = "sys_updated_on") -> str:
    if not since:
        return query
    stamp = since.strftime("%Y-%m-%d %H:%M:%S")
    if query:
        return f"{query}^{field}>={stamp}"
    return f"{field}>={stamp}"


def _iterate_batches(
    client: ServiceNowClient,
    table: str,
    query: str,
    fields: List[str],
    limit: int = 1000,
    display_value: bool = False,
) -> List[Dict[str, Any]]:
    offset = 0
    while True:
        batch = client.get_records(
            table=table,
            query=query,
            fields=fields,
            limit=limit,
            offset=offset,
            display_value=display_value,
        )
        if not batch:
            break
        yield batch
        if len(batch) < limit:
            break
        offset += limit


def create_scans_for_assessment(
    session: Session,
    assessment: Assessment,
    client: ServiceNowClient,
) -> List[Scan]:
    rules = get_scan_rules()
    assessment_rules = (rules.get("assessment_types") or {}).get(assessment.assessment_type.value, {})
    default_scans = assessment_rules.get("default_scans") or []

    global_app = _get_global_app(session, assessment)
    drivers = resolve_assessment_drivers(assessment, global_app)

    selected_classes = parse_list(assessment.app_file_classes_json)
    app_file_classes = _fetch_app_file_classes(session, selected_classes, instance_id=assessment.instance_id)

    scope_id = None
    if assessment.scope_filter == "global":
        scope_id = client._get_global_scope_sys_id()

    scans: List[Scan] = []

    if "metadata_index" in default_scans:
        for file_class in app_file_classes:
            variants = build_metadata_query_variants(
                app_file_class=file_class,
                drivers=drivers,
                scope_filter=assessment.scope_filter,
                scope_id=scope_id,
                rules=rules,
            )
            for variant in variants:
                query_params = {
                    "app_file_class": file_class.sys_class_name,
                    "target_table": variant.get("target_table"),
                    "keyword": variant.get("keyword"),
                }
                scan = Scan(
                    assessment_id=assessment.id,
                    scan_type=ScanType.metadata_index,
                    name=f"Metadata: {variant.get('label')}",
                    description=f"sys_metadata scan for {variant.get('label')}",
                    encoded_query=variant.get("query") or "",
                    target_table="sys_metadata",
                    query_params_json=json.dumps(query_params),
                )
                session.add(scan)
                scans.append(scan)

    if "update_xml" in default_scans:
        variants = build_update_xml_query_variants(
            drivers=drivers,
            scope_filter=assessment.scope_filter,
            scope_id=scope_id,
            rules=rules,
        )
        for variant in variants:
            query_params = {
                "target_table": variant.get("target_table"),
                "keyword": variant.get("keyword"),
            }
            scan = Scan(
                assessment_id=assessment.id,
                scan_type=ScanType.update_xml,
                name=variant.get("label") or "Update XML",
                description="sys_update_xml scan for assessment scope",
                encoded_query=variant.get("query") or "",
                target_table="sys_update_xml",
                query_params_json=json.dumps(query_params),
            )
            session.add(scan)
            scans.append(scan)

    session.commit()
    for scan in scans:
        session.refresh(scan)

    return scans


def execute_scan(
    session: Session,
    scan: Scan,
    client: ServiceNowClient,
    instance_id: Optional[int] = None,
    file_class: Optional[AppFileClass] = None,
    enable_customization: bool = True,
    enable_version_history: bool = True,
    since: Optional[datetime] = None,
    append_mode: bool = False,
) -> Scan:
    if _is_scan_cancel_requested(session, scan):
        _cancel_scan(session, scan)
        return scan
    rules = get_scan_rules()
    allowed_origin_values = set((rules.get("result_filters") or {}).get("allowed_origin_types") or [])
    dedupe_across_scans = bool((rules.get("result_filters") or {}).get("dedupe_across_scans"))
    initial_found = scan.records_found or 0
    initial_customized = scan.records_customized or 0
    initial_customer_customized = scan.records_customer_customized or 0
    initial_ootb_modified = scan.records_ootb_modified or 0
    if not append_mode:
        scan.records_found = 0
        scan.records_customized = 0
        scan.records_customer_customized = 0
        scan.records_ootb_modified = 0

    scan.status = ScanStatus.running
    scan.started_at = datetime.utcnow()
    scan.error_message = None
    session.add(scan)
    session.commit()
    logger.info("Starting scan %s (%s) query=%s", scan.id, scan.name, scan.encoded_query)

    if instance_id is None:
        assessment = session.get(Assessment, scan.assessment_id)
        if assessment:
            instance_id = assessment.instance_id

    try:
        if scan.scan_type == ScanType.metadata_index:
            fields = [
                "sys_id",
                "sys_class_name",
                "sys_name",
                "sys_update_name",
                "sys_scope",
                "sys_package",
                "sys_created_on",
                "sys_created_by",
                "sys_updated_on",
                "sys_updated_by",
            ]
            target_field = file_class.target_table_field if file_class else None
            if file_class:
                query_rules = (rules.get("app_file_class_queries") or {}).get(file_class.sys_class_name, {})
                target_field = query_rules.get("target_table_field") or target_field
            if target_field and target_field not in fields:
                fields.append(target_field)

            query = _apply_since_filter(scan.encoded_query or "", since, "sys_updated_on")
            customized_count = 0
            customer_customized_count = 0
            ootb_modified_count = 0
            found_count = 0
            for batch in _iterate_batches(
                client,
                table="sys_metadata",
                query=query,
                fields=fields,
                display_value=False,
            ):
                if _is_scan_cancel_requested(session, scan):
                    _cancel_scan(session, scan)
                    return scan
                batch_sys_ids = [record.get("sys_id") or "" for record in batch]
                existing_map = _existing_results_for_batch(session, scan.id, batch_sys_ids) if append_mode else {}
                assessment_map = (
                    _existing_results_for_assessment(session, scan.assessment_id, batch_sys_ids)
                    if dedupe_across_scans else {}
                )
                for record in batch:
                    sys_id = record.get("sys_id") or ""
                    sys_update_name = record.get("sys_update_name")
                    table_name = record.get("sys_class_name") or (file_class.sys_class_name if file_class else "")
                    dedupe_key = f"{sys_id}:{table_name}"

                    has_metadata_customization = False
                    baseline_changed = False
                    version_record = None
                    earliest_version_record = None
                    has_customer_update = False
                    related_customer_update_id = None
                    related_update_set_id = None

                    if instance_id and (enable_customization or enable_version_history):
                        has_metadata_customization = _has_metadata_customization_local(
                            session=session,
                            instance_id=instance_id,
                            sys_metadata_sys_id=sys_id,
                            sys_update_name=sys_update_name,
                        )

                        version_row = _lookup_version_history_local(
                            session=session,
                            instance_id=instance_id,
                            sys_update_name=sys_update_name,
                            sys_metadata_sys_id=sys_id,
                        )
                        version_record = _version_row_to_record(version_row)
                        baseline_changed = _baseline_changed_from_version_history_local(
                            session=session,
                            instance_id=instance_id,
                            sys_update_name=sys_update_name,
                            sys_metadata_sys_id=sys_id,
                            current_version_record=version_record,
                        )

                        customer_update = _lookup_customer_update_local(
                            session=session,
                            instance_id=instance_id,
                            sys_update_name=sys_update_name,
                            version_row=version_row,
                        )
                        if customer_update:
                            has_customer_update = True
                            related_customer_update_id = customer_update.id
                            related_update_set_id = _resolve_update_set_id_local(
                                session=session,
                                instance_id=instance_id,
                                customer_update=customer_update,
                            )

                        if not has_customer_update and not has_metadata_customization:
                            earliest_row = _lookup_earliest_version_history_local(
                                session=session,
                                instance_id=instance_id,
                                sys_update_name=sys_update_name,
                                sys_metadata_sys_id=sys_id,
                            )
                            earliest_version_record = _version_row_to_record(earliest_row)
                    else:
                        if enable_customization:
                            has_metadata_customization = _has_metadata_customization(client, sys_id)
                        if enable_version_history:
                            version_record = _lookup_version_history(client, sys_update_name)
                            baseline_changed = _baseline_changed_from_version_history(
                                client=client,
                                sys_update_name=sys_update_name,
                                current_version_record=version_record,
                            )

                    origin_type, head_owner = _classify_origin(
                        version_record,
                        has_metadata_customization,
                        has_customer_update=has_customer_update,
                        earliest_version_record=earliest_version_record,
                        changed_baseline_now=baseline_changed,
                    )

                    if allowed_origin_values and origin_type.value not in allowed_origin_values:
                        continue

                    result = existing_map.get(sys_id)
                    is_new = result is None
                    if result is None and dedupe_across_scans and assessment_map.get(dedupe_key):
                        continue
                    if result is None:
                        result = ScanResult(
                            scan_id=scan.id,
                            sys_id=sys_id,
                            table_name="",
                            name="",
                        )
                        session.add(result)
                    result.table_name = table_name
                    result.name = record.get("sys_name") or record.get("sys_update_name") or sys_id
                    result.display_value = record.get("sys_name")
                    result.sys_class_name = record.get("sys_class_name")
                    result.sys_update_name = sys_update_name
                    result.sys_scope = _normalize_ref(record.get("sys_scope"))
                    result.sys_package = _normalize_ref(record.get("sys_package"))
                    result.meta_target_table = _normalize_ref(record.get(target_field)) if target_field else None
                    result.origin_type = origin_type
                    result.head_owner = head_owner
                    result.changed_baseline_now = baseline_changed
                    result.current_version_source_table = _normalize_version_ref((version_record or {}).get("source_table")) or None
                    result.current_version_source = (
                        _normalize_version_ref((version_record or {}).get("source_display"))
                        or _normalize_version_ref((version_record or {}).get("source"))
                        or None
                    )
                    result.current_version_sys_id = (version_record or {}).get("sys_id")
                    result.current_version_recorded_at = _parse_sn_datetime((version_record or {}).get("sys_recorded_at"))
                    result.customer_update_xml_id = related_customer_update_id
                    result.update_set_id = related_update_set_id
                    result.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
                    result.sys_updated_by = record.get("sys_updated_by")
                    result.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
                    result.sys_created_by = record.get("sys_created_by")
                    result.raw_data_json = json.dumps(record)

                    if is_new:
                        found_count += 1
                        if origin_type == OriginType.modified_ootb:
                            customized_count += 1
                            ootb_modified_count += 1
                        elif origin_type == OriginType.net_new_customer:
                            customized_count += 1
                            customer_customized_count += 1
                scan.records_found = initial_found + found_count
                scan.records_customized = initial_customized + customized_count
                scan.records_customer_customized = initial_customer_customized + customer_customized_count
                scan.records_ootb_modified = initial_ootb_modified + ootb_modified_count
                session.add(scan)
                session.commit()
            logger.info("Completed scan %s found=%s customized=%s", scan.id, scan.records_found, scan.records_customized)

        elif scan.scan_type == ScanType.update_xml:
            fields = [
                "sys_id",
                "name",
                "type",
                "table",
                "target_name",
                "action",
                "update_set",
                "sys_created_on",
                "sys_created_by",
                "sys_updated_on",
                "sys_updated_by",
            ]
            query = _apply_since_filter(scan.encoded_query or "", since, "sys_updated_on")
            found_count = 0
            for batch in _iterate_batches(
                client,
                table="sys_update_xml",
                query=query,
                fields=fields,
                display_value=False,
            ):
                if _is_scan_cancel_requested(session, scan):
                    _cancel_scan(session, scan)
                    return scan
                batch_sys_ids = [record.get("sys_id") or "" for record in batch]
                existing_map = _existing_results_for_batch(session, scan.id, batch_sys_ids) if append_mode else {}
                assessment_map = (
                    _existing_results_for_assessment(session, scan.assessment_id, batch_sys_ids)
                    if dedupe_across_scans else {}
                )
                for record in batch:
                    sys_id = record.get("sys_id") or ""
                    dedupe_key = f"{sys_id}:sys_update_xml"
                    result = existing_map.get(sys_id)
                    is_new = result is None
                    if result is None and dedupe_across_scans and assessment_map.get(dedupe_key):
                        continue
                    if result is None:
                        result = ScanResult(
                            scan_id=scan.id,
                            sys_id=sys_id,
                            table_name="sys_update_xml",
                            name="",
                        )
                        session.add(result)
                    result.table_name = "sys_update_xml"
                    result.name = record.get("name") or record.get("target_name") or sys_id
                    result.display_value = record.get("target_name")
                    result.sys_class_name = record.get("table") or record.get("type")
                    result.sys_update_name = record.get("name")
                    result.sys_updated_on = _parse_sn_datetime(record.get("sys_updated_on"))
                    result.sys_updated_by = record.get("sys_updated_by")
                    result.sys_created_on = _parse_sn_datetime(record.get("sys_created_on"))
                    result.sys_created_by = record.get("sys_created_by")
                    result.raw_data_json = json.dumps(record)

                    if is_new:
                        found_count += 1
                scan.records_found = initial_found + found_count
                scan.records_customized = initial_customized
                scan.records_customer_customized = initial_customer_customized
                scan.records_ootb_modified = initial_ootb_modified
                session.add(scan)
                session.commit()
            logger.info("Completed scan %s found=%s", scan.id, scan.records_found)

        else:
            scan.error_message = f"Unsupported scan type: {scan.scan_type.value}"
            scan.status = ScanStatus.failed
            scan.completed_at = datetime.utcnow()
            session.add(scan)
            session.commit()
            return scan

        scan.status = ScanStatus.completed
        scan.completed_at = datetime.utcnow()
        session.add(scan)
        session.commit()

        # Sync customization child table
        from .customization_sync import bulk_sync_for_scan
        bulk_sync_for_scan(session, scan.id)

        return scan

    except Exception as exc:
        logger.exception("Scan %s failed", scan.id)
        session.rollback()
        scan.status = ScanStatus.failed
        scan.error_message = str(exc)
        scan.completed_at = datetime.utcnow()
        session.add(scan)
        session.commit()
        return scan


def reset_scan_state(session: Session, scan: Scan, clear_results: bool = True) -> None:
    if clear_results:
        session.exec(text("DELETE FROM scan_result WHERE scan_id = :scan_id").bindparams(scan_id=scan.id))
        scan.records_found = 0
        scan.records_customized = 0
        scan.records_customer_customized = 0
        scan.records_ootb_modified = 0
    scan.status = ScanStatus.pending
    scan.error_message = None
    scan.started_at = None
    scan.completed_at = None
    scan.cancel_requested = False
    scan.cancel_requested_at = None
    session.add(scan)


def run_scans_for_assessment(session: Session, assessment: Assessment, client: ServiceNowClient, mode: str = "full") -> List[Scan]:
    rules = reload_scan_rules() if mode == "rebuild" else get_scan_rules()

    existing_scans = session.exec(select(Scan).where(Scan.assessment_id == assessment.id)).all()
    if mode == "rebuild":
        session.exec(
            text(
                "DELETE FROM feature_scan_result WHERE scan_result_id IN "
                "(SELECT id FROM scan_result WHERE scan_id IN (SELECT id FROM scan WHERE assessment_id = :aid))"
            ).bindparams(aid=assessment.id),
        )
        session.exec(
            text(
                "DELETE FROM scan_result WHERE scan_id IN "
                "(SELECT id FROM scan WHERE assessment_id = :aid)"
            ).bindparams(aid=assessment.id),
        )
        session.exec(text("DELETE FROM scan WHERE assessment_id = :aid").bindparams(aid=assessment.id))
        session.commit()
        scans = create_scans_for_assessment(session, assessment, client)
        mode = "full"
    else:
        scans = existing_scans or create_scans_for_assessment(session, assessment, client)

    last_completed_at: Dict[int, Optional[datetime]] = {}
    if mode in ("full", "delta"):
        for scan in scans:
            last_completed_at[scan.id] = scan.completed_at
            if mode == "full":
                reset_scan_state(session, scan, clear_results=True)
            else:
                reset_scan_state(session, scan, clear_results=False)
        session.commit()

    # Map file_class for metadata scans
    class_map = {
        fc.sys_class_name: fc
        for fc in _fetch_app_file_classes(
            session,
            parse_list(assessment.app_file_classes_json),
            instance_id=assessment.instance_id,
        )
    }

    for scan in scans:
        file_class = None
        if scan.scan_type == ScanType.metadata_index:
            if scan.query_params_json:
                try:
                    params = json.loads(scan.query_params_json)
                    file_class_name = params.get("app_file_class")
                    file_class = class_map.get(file_class_name)
                except (json.JSONDecodeError, TypeError):
                    file_class = None

        enable_customization = True
        enable_version_history = True
        since = last_completed_at.get(scan.id) if mode == "delta" else None
        if _is_scan_cancel_requested(session, scan):
            _cancel_scan(session, scan)
            continue
        execute_scan(
            session=session,
            scan=scan,
            client=client,
            instance_id=assessment.instance_id,
            file_class=file_class,
            enable_customization=enable_customization,
            enable_version_history=enable_version_history,
            since=since,
            append_mode=(mode == "delta"),
        )

    return scans
