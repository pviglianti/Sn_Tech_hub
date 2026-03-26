"""Analytics routes extracted from server.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ...database import get_session
from ...inventory_class_catalog import inventory_class_tables
from ...models import Instance
from ...services.sn_client import ServiceNowClientError
from ...services.sn_client_factory import create_client_for_instance

analytics_router = APIRouter(tags=["analytics"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _safe_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _month_labels(start: datetime, end: datetime) -> List[str]:
    labels: List[str] = []
    current = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while current <= end_month:
        labels.append(current.strftime("%Y-%m"))
        year = current.year + (current.month // 12)
        month = (current.month % 12) + 1
        current = current.replace(year=year, month=month, day=1)
    return labels


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(dt: datetime) -> datetime:
    start = _start_of_day(dt)
    return start - timedelta(days=start.weekday())


def _start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _start_of_year(dt: datetime) -> datetime:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_months(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


def _resolve_task_range(range_key: str, custom_value: Optional[int], custom_unit: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    now = datetime.utcnow()

    if range_key == "all_time":
        return None, None
    if range_key == "today":
        return _start_of_day(now), now
    if range_key == "yesterday":
        start = _start_of_day(now) - timedelta(days=1)
        end = _start_of_day(now)
        return start, end
    if range_key == "this_week":
        return _start_of_week(now), now
    if range_key == "last_week":
        end = _start_of_week(now)
        start = end - timedelta(days=7)
        return start, end
    if range_key == "this_month":
        return _start_of_month(now), now
    if range_key == "last_month":
        end = _start_of_month(now)
        start = _shift_months(end, -1)
        return start, end
    if range_key == "this_year" or range_key == "ytd":
        return _start_of_year(now), now
    if range_key == "last_year":
        end = _start_of_year(now)
        start = _start_of_year(now.replace(year=now.year - 1))
        return start, end

    days_map = {
        "last_30_days": 30,
        "last_60_days": 60,
        "last_90_days": 90,
        "last_180_days": 180,
        "last_365_days": 365,
        "last_3_months": 90,
        "last_6_months": 180,
        "last_2_years": 365 * 2,
        "last_5_years": 365 * 5,
    }
    if range_key in days_map:
        return now - timedelta(days=days_map[range_key]), now

    if range_key == "custom" and custom_value and custom_unit:
        unit = custom_unit.lower()
        multiplier = {"days": 1, "weeks": 7, "months": 30, "years": 365}.get(unit, 1)
        return now - timedelta(days=custom_value * multiplier), now

    return None, None


def _format_sn_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@analytics_router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, session: Session = Depends(get_session)):
    """Instance comparison and analytics page."""
    instances = session.exec(select(Instance)).all()
    instances_payload = [
        {
            "id": i.id,
            "name": i.name,
            "company": i.company,
        }
        for i in instances
    ]

    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "instances": instances,
            "instances_json": json.dumps(instances_payload),
        },
    )


@analytics_router.get("/api/analytics/summary")
async def api_analytics_summary(
    instance_ids: str = "",
    session: Session = Depends(get_session),
):
    """API: Summary metrics for instance comparison."""
    instances_query = select(Instance)
    if instance_ids and instance_ids != "all":
        id_list = [int(i) for i in instance_ids.split(",") if i.strip().isdigit()]
        if id_list:
            instances_query = instances_query.where(Instance.id.in_(id_list))

    instances = session.exec(instances_query).all()

    payload = []
    for inst in instances:
        payload.append(
            {
                "id": inst.id,
                "name": inst.name,
                "company": inst.company,
                "inventory": _safe_json(inst.inventory_json, {}),
                "task_counts": _safe_json(inst.task_counts_json, {}),
                "update_set_counts": _safe_json(inst.update_set_counts_json, {}),
                "sys_update_xml_counts": _safe_json(inst.sys_update_xml_counts_json, {}),
                "sys_metadata_customization_count": inst.sys_metadata_customization_count,
                "sys_update_xml_total": inst.sys_update_xml_total,
                "instance_dob": inst.instance_dob.isoformat() if inst.instance_dob else None,
                "instance_age_years": inst.instance_age_years,
                "metrics_last_refreshed_at": inst.metrics_last_refreshed_at.isoformat() if inst.metrics_last_refreshed_at else None,
                "custom_scoped_app_count_x": inst.custom_scoped_app_count_x,
                "custom_scoped_app_count_u": inst.custom_scoped_app_count_u,
                "custom_table_count_x": inst.custom_table_count_x,
                "custom_table_count_u": inst.custom_table_count_u,
                "custom_field_count_x": inst.custom_field_count_x,
                "custom_field_count_u": inst.custom_field_count_u,
            }
        )

    return {"instances": payload, "generated_at": datetime.utcnow().isoformat()}


@analytics_router.get("/api/analytics/tasks-series")
async def api_tasks_series(
    instance_ids: str = "",
    task_type: str = "task",
    window: str = "all",
    session: Session = Depends(get_session),
):
    """API: Monthly task counts for selected instances."""
    task_tables = {
        "task": "task",
        "incident": "incident",
        "change_request": "change_request",
        "change_task": "change_task",
        "problem": "problem",
        "problem_task": "problem_task",
        "sc_req_item": "sc_req_item",
        "sc_task": "sc_task",
    }
    if task_type not in task_tables:
        raise HTTPException(status_code=400, detail="Invalid task_type")

    instances_query = select(Instance)
    if instance_ids and instance_ids != "all":
        id_list = [int(i) for i in instance_ids.split(",") if i.strip().isdigit()]
        if id_list:
            instances_query = instances_query.where(Instance.id.in_(id_list))

    instances = session.exec(instances_query).all()
    if not instances:
        return {"labels": [], "series": {}}

    now = datetime.utcnow()
    window_years = {"1y": 1, "2y": 2, "5y": 5}.get(window)

    instance_starts = {}
    instance_ends = {}
    for inst in instances:
        end_date = inst.metrics_last_refreshed_at or now
        instance_ends[inst.id] = end_date
        start = inst.instance_dob or (end_date - timedelta(days=365 * (window_years or 5)))
        if window_years:
            start = max(start, end_date - timedelta(days=365 * window_years))
        instance_starts[inst.id] = start

    global_start = min(instance_starts.values())
    labels = _month_labels(global_start, now)

    series = {}
    for inst in instances:
        client = create_client_for_instance(inst)
        inst_labels, inst_counts = client.get_monthly_counts(
            task_tables[task_type],
            instance_starts[inst.id],
            instance_ends[inst.id],
        )
        counts_map = {label: count for label, count in zip(inst_labels, inst_counts)}
        series[str(inst.id)] = [counts_map.get(label) for label in labels]

    return {
        "labels": labels,
        "series": series,
    }


@analytics_router.get("/api/analytics/tasks-summary")
async def api_tasks_summary(
    instance_ids: str = "",
    range: str = "all_time",
    task_types: str = "",
    custom_value: Optional[int] = None,
    custom_unit: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """API: Task totals by instance for a given date range."""
    task_tables = {
        "task": "task",
        "incident": "incident",
        "change_request": "change_request",
        "change_task": "change_task",
        "problem": "problem",
        "problem_task": "problem_task",
        "sc_req_item": "sc_req_item",
        "sc_task": "sc_task",
    }

    requested = [t for t in task_types.split(",") if t]
    task_keys = requested if requested else list(task_tables.keys())
    task_keys = [t for t in task_keys if t in task_tables]

    instances_query = select(Instance)
    if instance_ids and instance_ids != "all":
        id_list = [int(i) for i in instance_ids.split(",") if i.strip().isdigit()]
        if id_list:
            instances_query = instances_query.where(Instance.id.in_(id_list))

    instances = session.exec(instances_query).all()
    if not instances:
        return {"series": {}, "range": range}

    start, end = _resolve_task_range(range, custom_value, custom_unit)
    series: Dict[str, Dict[str, Optional[int]]] = {key: {} for key in task_keys}

    for inst in instances:
        client = create_client_for_instance(inst)

        inst_end = end
        if inst.metrics_last_refreshed_at and end:
            if inst.metrics_last_refreshed_at < end:
                inst_end = inst.metrics_last_refreshed_at

        inst_start = start
        if inst_end and inst_start and inst_end < inst_start:
            for key in task_keys:
                series[key][str(inst.id)] = None
            continue

        date_query = ""
        if inst_start:
            date_query = f"sys_created_on>={_format_sn_datetime(inst_start)}"
        if inst_end:
            end_query = f"sys_created_on<{_format_sn_datetime(inst_end)}"
            date_query = f"{date_query}^{end_query}" if date_query else end_query

        for key in task_keys:
            table = task_tables[key]
            count = None
            archive_count = None
            try:
                count = client.get_record_count(table, date_query)
            except ServiceNowClientError:
                count = None

            try:
                archive_count = client.get_record_count(f"ar_{table}", date_query)
            except ServiceNowClientError:
                archive_count = None

            if count is None and archive_count is None:
                series[key][str(inst.id)] = None
            else:
                series[key][str(inst.id)] = (count or 0) + (archive_count or 0)

    return {
        "series": series,
        "range": range,
    }


@analytics_router.get("/api/analytics/config-summary")
async def api_config_summary(
    instance_ids: str = "",
    range: str = "all_time",
    custom_value: Optional[int] = None,
    custom_unit: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """API: Config change totals by instance for a given date range (updated/created dates)."""
    config_tables = inventory_class_tables(include_update_sets=False)

    instances_query = select(Instance)
    if instance_ids and instance_ids != "all":
        id_list = [int(i) for i in instance_ids.split(",") if i.strip().isdigit()]
        if id_list:
            instances_query = instances_query.where(Instance.id.in_(id_list))

    instances = session.exec(instances_query).all()
    if not instances:
        return {"series": {}, "range": range}

    start, end = _resolve_task_range(range, custom_value, custom_unit)
    series: Dict[str, Dict[str, Optional[int]]] = {}
    for key in config_tables.keys():
        series[key] = {}
    for key in [
        "metadata_customizations",
        "update_sets_global",
        "update_sets_scoped",
        "update_sets_total",
        "update_xml_global",
        "update_xml_scoped",
        "update_xml_total",
    ]:
        series[key] = {}

    for inst in instances:
        client = create_client_for_instance(inst)

        inst_end = end
        if inst.metrics_last_refreshed_at and end:
            if inst.metrics_last_refreshed_at < end:
                inst_end = inst.metrics_last_refreshed_at

        inst_start = start
        if inst_end and inst_start and inst_end < inst_start:
            for key in config_tables.keys():
                series[key][str(inst.id)] = None
            continue

        date_query_updated = ""
        if inst_start:
            date_query_updated = f"sys_updated_on>={_format_sn_datetime(inst_start)}"
        if inst_end:
            end_query = f"sys_updated_on<{_format_sn_datetime(inst_end)}"
            date_query_updated = f"{date_query_updated}^{end_query}" if date_query_updated else end_query

        for key, table in config_tables.items():
            scope_query = "sys_scope=global"
            query_parts = [scope_query]
            if date_query_updated:
                query_parts.append(date_query_updated)
            query = "^".join(query_parts)
            count = None
            try:
                count = client.get_record_count(table, query)
            except ServiceNowClientError:
                count = None
            series[key][str(inst.id)] = count

        meta_query = date_query_updated
        meta_count = None
        try:
            meta_count = client.get_record_count("sys_metadata_customization", meta_query)
        except ServiceNowClientError:
            meta_count = None
        series["metadata_customizations"][str(inst.id)] = meta_count

        date_query_created = ""
        if inst_start:
            date_query_created = f"sys_created_on>={_format_sn_datetime(inst_start)}"
        if inst_end:
            end_query = f"sys_created_on<{_format_sn_datetime(inst_end)}"
            date_query_created = f"{date_query_created}^{end_query}" if date_query_created else end_query

        def _count_update_set_range(scope_query: str) -> Optional[int]:
            query_parts = [scope_query] if scope_query else []
            if date_query_created:
                query_parts.append(date_query_created)
            query = "^".join([q for q in query_parts if q])
            try:
                return client.get_record_count("sys_update_set", query)
            except ServiceNowClientError:
                return None

        update_set_total = _count_update_set_range("")
        update_set_global = _count_update_set_range("application.scope=global")
        update_set_scoped = _count_update_set_range("application.scope!=global")
        series["update_sets_total"][str(inst.id)] = update_set_total
        series["update_sets_global"][str(inst.id)] = update_set_global
        series["update_sets_scoped"][str(inst.id)] = update_set_scoped

        def _count_update_xml_range(scope_query: str) -> Optional[int]:
            query_parts = [scope_query] if scope_query else []
            if date_query_updated:
                query_parts.append(date_query_updated)
            query = "^".join([q for q in query_parts if q])
            try:
                return client.get_record_count("sys_update_xml", query)
            except ServiceNowClientError:
                return None

        update_xml_total = _count_update_xml_range("")
        update_xml_global = _count_update_xml_range("update_set.application.scope=global")
        update_xml_scoped = _count_update_xml_range("update_set.application.scope!=global")
        series["update_xml_total"][str(inst.id)] = update_xml_total
        series["update_xml_global"][str(inst.id)] = update_xml_global
        series["update_xml_scoped"][str(inst.id)] = update_xml_scoped

    return {
        "series": series,
        "range": range,
    }
