"""Preflight data browser routes."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, text
from sqlmodel import Session, select

from ...database import get_session
from ...models import DataPullType, Instance
from ...models_sn import SnTableRegistry
from ...services.condition_query_builder import conditions_to_sql_where
from ...services.data_pull_executor import (
    get_data_browser_config_map,
    get_data_browser_reference_rules,
    get_data_pull_type_to_sn_table,
    get_data_type_labels,
)

data_browser_router = APIRouter(tags=["data-browser"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

DATA_TYPE_LABELS = get_data_type_labels()
DATA_BROWSER_CONFIG = get_data_browser_config_map()
DATA_BROWSER_DATA_TYPES: List[DataPullType] = list(DATA_BROWSER_CONFIG.keys())
DATA_BROWSER_REFERENCE_RULES: Dict[DataPullType, Dict[str, Dict[str, Any]]] = get_data_browser_reference_rules()
DATA_PULL_TYPE_TO_SN_TABLE: Dict[DataPullType, str] = get_data_pull_type_to_sn_table()

_DATA_BROWSER_UNSEARCHABLE_FIELDS = {
    "raw_data_json",
    "payload",
    "payload_hash",
    "package_json",
}

_COLUMN_LABEL_MAP: Dict[str, str] = {
    "sn_sys_id": "Sys ID",
    "sys_updated_on": "Updated On",
    "sys_updated_by": "Updated By",
    "sys_recorded_at": "Recorded At",
    "last_refreshed_at": "Last Refreshed",
    "update_set_sn_sys_id": "Update Set",
    "is_default": "Default",
    "target_name": "Target Name",
    "target_sys_id": "Target Sys ID",
    "update_guid": "Update GUID",
    "record_name": "Record Name",
    "source_table": "Source Table",
    "source_sys_id": "Source Sys ID",
    "sys_metadata_sys_id": "Metadata Sys ID",
    "sys_update_name": "Update Name",
    "author_type": "Author Type",
    "plugin_id": "Plugin ID",
    "sys_package": "Package",
    "sys_scope": "Scope",
    "super_class": "Super Class",
    "completed_on": "Completed On",
    "completed_by": "Completed By",
}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _data_browser_column_kind(column: Any) -> str:
    """Infer a simple kind label for UI widgets and filtering."""
    try:
        py_type = column.type.python_type
    except Exception:
        return "string"

    if py_type is bool:
        return "boolean"
    if py_type in (int, float):
        return "number"
    if py_type in (datetime, date):
        return "date"
    return "string"


def _parse_bool(value: str) -> bool:
    v = value.strip().lower()
    if v in {"true", "1", "yes", "y", "on"}:
        return True
    if v in {"false", "0", "no", "n", "off"}:
        return False
    raise ValueError("Invalid boolean")


def _parse_number(value: str) -> float:
    return float(value.strip())


def _parse_date(value: str) -> date:
    # Expect YYYY-MM-DD (from <input type="date">)
    return date.fromisoformat(value.strip())


def _column_label(col_name: str) -> str:
    """Return a human-friendly column label for a static model column."""
    if col_name in _COLUMN_LABEL_MAP:
        return _COLUMN_LABEL_MAP[col_name]
    return col_name.replace("_", " ").title()


def _find_data_browser_record_id(
    session: Session,
    instance_id: int,
    data_type: DataPullType,
    field_name: str,
    value: Any,
) -> Optional[int]:
    if value in (None, ""):
        return None
    config = DATA_BROWSER_CONFIG.get(data_type)
    if not config:
        return None
    model = config["model"]
    table_columns = {col.name: col for col in model.__table__.columns}  # type: ignore[attr-defined]
    if field_name not in table_columns:
        return None

    field_attr = getattr(model, field_name)
    query = (
        select(model.id)
        .where(model.instance_id == instance_id)
        .where(field_attr == value)
        .order_by(model.id.desc())
    )
    return session.exec(query).first()


def _build_data_browser_record_reference_url(
    *,
    instance_id: int,
    data_type: DataPullType,
    record_id: int,
) -> str:
    return f"/data-browser/record?instance_id={instance_id}&data_type={data_type.value}&record_id={record_id}"


def _resolve_data_browser_field_reference(
    session: Session,
    instance_id: int,
    current_data_type: DataPullType,
    field_name: str,
    field_value: Any,
    record: Any,
) -> Optional[Dict[str, Any]]:
    rules = DATA_BROWSER_REFERENCE_RULES.get(current_data_type, {})
    rule = rules.get(field_name)
    if not rule:
        return None

    source_table_equals = rule.get("source_table_equals")
    if source_table_equals:
        source_table_value = getattr(record, "source_table", None)
        if (source_table_value or "").strip().lower() != str(source_table_equals).strip().lower():
            return None

    target_data_type = rule["target_data_type"]
    target_field = rule["target_field"]
    target_id = _find_data_browser_record_id(
        session=session,
        instance_id=instance_id,
        data_type=target_data_type,
        field_name=target_field,
        value=field_value,
    )
    if not target_id:
        return None
    return {
        "data_type": target_data_type.value,
        "field": target_field,
        "record_id": target_id,
        "url": _build_data_browser_record_reference_url(
            instance_id=instance_id,
            data_type=target_data_type,
            record_id=target_id,
        ),
    }


@data_browser_router.get("/data-browser", response_class=HTMLResponse)
async def data_browser_page(
    request: Request,
    instance_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """Top-level data browser for instance reference data."""
    instances = session.exec(select(Instance).order_by(Instance.name)).all()
    selected_instance_id = instance_id
    if selected_instance_id is None and instances:
        selected_instance_id = instances[0].id

    data_types = [dt.value for dt in DATA_BROWSER_DATA_TYPES]
    data_type_labels = DATA_TYPE_LABELS
    return templates.TemplateResponse(
        "data_browser.html",
        {
            "request": request,
            "instances": instances,
            "selected_instance_id": selected_instance_id,
            "data_types": data_types,
            "data_types_json": json.dumps(data_types),
            "data_type_labels": data_type_labels,
            "data_type_labels_json": json.dumps(data_type_labels),
            "default_data_type_json": json.dumps(DataPullType.update_sets.value),
        },
    )


@data_browser_router.get("/api/data-browser/records")
async def api_data_browser_records(
    instance_id: int,
    data_type: Optional[str] = None,
    table: Optional[str] = None,
    filter_field: Optional[str] = None,
    filter_value: Optional[str] = None,
    sort_field: Optional[str] = None,
    sort_dir: str = "desc",
    conditions: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """Return cached reference data records for an instance + data type.

    Accepts ``data_type`` or ``table`` (alias). Supports sorting via
    ``sort_field``/``sort_dir`` and ConditionBuilder filtering via
    ``conditions`` (JSON).
    """
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    effective_type = data_type or table
    if not effective_type:
        raise HTTPException(status_code=400, detail="data_type or table required")
    try:
        dt = DataPullType(effective_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data_type")

    config = DATA_BROWSER_CONFIG.get(dt)
    if not config:
        raise HTTPException(status_code=400, detail="Unsupported data_type")

    model = config["model"]
    columns = config["columns"]
    default_order_by = config.get("order_by")

    where_clauses = [model.instance_id == instance_id]

    table_columns = {col.name: col for col in model.__table__.columns}  # type: ignore[attr-defined]

    # Legacy single-field filter (still supported for backward compat)
    if filter_field and filter_value is not None:
        if filter_field not in table_columns:
            raise HTTPException(status_code=400, detail="Invalid filter_field")
        if filter_field in _DATA_BROWSER_UNSEARCHABLE_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported filter_field")

        field_attr = getattr(model, filter_field)
        col = table_columns[filter_field]
        kind = _data_browser_column_kind(col)

        raw_value = str(filter_value).strip()
        if raw_value:
            try:
                if kind == "string":
                    where_clauses.append(field_attr.ilike(f"%{raw_value}%"))
                elif kind == "number":
                    where_clauses.append(field_attr == _parse_number(raw_value))
                elif kind == "boolean":
                    where_clauses.append(field_attr == _parse_bool(raw_value))
                elif kind == "date":
                    parsed_date = _parse_date(raw_value)
                    try:
                        py_type = col.type.python_type
                    except Exception:
                        py_type = None
                    if py_type is datetime:
                        start = datetime.combine(parsed_date, datetime.min.time())
                        end = start + timedelta(days=1)
                        where_clauses.append(field_attr >= start)
                        where_clauses.append(field_attr < end)
                    else:
                        where_clauses.append(field_attr == parsed_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid filter_value")

    # ConditionBuilder JSON filter
    if conditions:
        try:
            parsed_conds = json.loads(conditions)
            if parsed_conds:
                cond_sql, cond_params = conditions_to_sql_where(parsed_conds)
                if cond_sql and cond_sql != "1=1":
                    named_sql = cond_sql
                    bind_kw: Dict[str, Any] = {}
                    for i, val in enumerate(cond_params):
                        pname = f"_cond_{i}"
                        named_sql = named_sql.replace("?", f":{pname}", 1)
                        bind_kw[pname] = val
                    where_clauses.append(text(named_sql).bindparams(**bind_kw))
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid conditions: {exc}")

    total = session.exec(select(func.count()).select_from(model).where(*where_clauses)).one()

    query = select(model).where(*where_clauses)

    # Sorting: explicit sort_field takes priority over config default
    if sort_field and sort_field in table_columns:
        sort_attr = getattr(model, sort_field)
        if sort_dir == "asc":
            query = query.order_by(sort_attr)
        else:
            query = query.order_by(desc(sort_attr))
    elif default_order_by is not None:
        query = query.order_by(desc(default_order_by))

    records = session.exec(query.offset(offset).limit(limit)).all()

    rows: List[Dict[str, Any]] = []
    for record in records:
        row = {"_id": record.id}
        for col in columns:
            row[col] = _serialize_value(getattr(record, col, None))
        raw_data = getattr(record, "raw_data_json", None)
        row["_has_raw"] = bool(raw_data)
        rows.append(row)

    return {
        "instance_id": instance_id,
        "data_type": dt.value,
        "columns": columns,
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@data_browser_router.get("/api/data-browser/schema")
async def api_data_browser_schema(
    data_type: Optional[str] = None,
    table: Optional[str] = None,
    instance_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Return field metadata for a data browser tab.

    Accepts ``data_type`` or ``table`` (alias). When ``instance_id`` is
    provided the response includes ``available_tables`` for reference link
    rendering. Field objects include DataTable.js-compatible keys:
    ``local_column``, ``column_label``, ``is_reference``, ``sn_reference_table``.
    """
    effective_type = data_type or table
    if not effective_type:
        raise HTTPException(status_code=400, detail="data_type or table required")
    try:
        dt = DataPullType(effective_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data_type")

    config = DATA_BROWSER_CONFIG.get(dt)
    if not config:
        raise HTTPException(status_code=400, detail="Unsupported data_type")

    model = config["model"]
    common_fields = list(config.get("columns", []))
    ref_rules = DATA_BROWSER_REFERENCE_RULES.get(dt, {})
    fields: List[Dict[str, Any]] = []

    for col in model.__table__.columns:  # type: ignore[attr-defined]
        name = col.name
        kind = _data_browser_column_kind(col)
        searchable = name not in _DATA_BROWSER_UNSEARCHABLE_FIELDS
        suggestable = searchable and kind == "string"

        ref_info = ref_rules.get(name)
        is_reference = bool(ref_info)
        sn_reference_table = None
        if ref_info:
            target_dt = ref_info.get("target_data_type")
            if target_dt:
                sn_reference_table = DATA_PULL_TYPE_TO_SN_TABLE.get(target_dt)

        fields.append(
            {
                "name": name,
                "kind": kind,
                "searchable": searchable,
                "suggestable": suggestable,
                "local_column": name,
                "column_label": _column_label(name),
                "is_reference": is_reference,
                "sn_reference_table": sn_reference_table,
            }
        )

    default_field = common_fields[0] if common_fields else (fields[0]["name"] if fields else None)

    available_tables: List[str] = []
    if instance_id:
        regs = session.exec(
            select(SnTableRegistry)
            .where(SnTableRegistry.instance_id == instance_id)
        ).all()
        available_tables = sorted({r.sn_table_name for r in regs})

    return {
        "data_type": dt.value,
        "common_fields": common_fields,
        "fields": fields,
        "default_field": default_field,
        "available_tables": available_tables,
    }


@data_browser_router.get("/api/data-browser/suggest")
async def api_data_browser_suggest(
    instance_id: int,
    data_type: str,
    field: str,
    q: str = "",
    limit: int = 20,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """API: Return type-ahead suggestions for a string field."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        dt = DataPullType(data_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data_type")

    config = DATA_BROWSER_CONFIG.get(dt)
    if not config:
        raise HTTPException(status_code=400, detail="Unsupported data_type")

    model = config["model"]
    table_columns = {col.name: col for col in model.__table__.columns}  # type: ignore[attr-defined]
    if field not in table_columns:
        raise HTTPException(status_code=400, detail="Invalid field")
    if field in _DATA_BROWSER_UNSEARCHABLE_FIELDS:
        raise HTTPException(status_code=400, detail="Unsupported field")

    col = table_columns[field]
    if _data_browser_column_kind(col) != "string":
        raise HTTPException(status_code=400, detail="Suggestions only supported for string fields")

    query_text = (q or "").strip()
    if len(query_text) < 2:
        return {"suggestions": []}

    field_attr = getattr(model, field)
    pattern = f"%{query_text.lower()}%"
    query = (
        select(field_attr)
        .where(model.instance_id == instance_id)
        .where(field_attr.is_not(None))
        .where(func.lower(field_attr).like(pattern))
        .distinct()
        .order_by(field_attr)
        .limit(max(1, min(limit, 50)))
    )
    values = session.exec(query).all()
    suggestions: List[str] = []
    for value in values:
        if value is None:
            continue
        text_value = str(value)
        if not text_value:
            continue
        if len(text_value) > 220:
            continue
        suggestions.append(text_value)

    return {"suggestions": suggestions}


@data_browser_router.get("/api/data-browser/raw")
async def api_data_browser_raw(
    instance_id: int,
    data_type: str,
    record_id: int,
    session: Session = Depends(get_session),
):
    """API: Return raw JSON payload for a single record."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        dt = DataPullType(data_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data_type")

    config = DATA_BROWSER_CONFIG.get(dt)
    if not config:
        raise HTTPException(status_code=400, detail="Unsupported data_type")

    model = config["model"]
    record = session.exec(
        select(model)
        .where(model.id == record_id)
        .where(model.instance_id == instance_id)
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    return {"raw": getattr(record, "raw_data_json", None)}


@data_browser_router.get("/data-browser/record", response_class=HTMLResponse)
async def data_browser_record_detail(
    request: Request,
    instance_id: int,
    data_type: str,
    record_id: int,
    preview: bool = False,
    session: Session = Depends(get_session),
):
    """Detail page for a single cached data-browser record."""
    instance = session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    try:
        dt = DataPullType(data_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data_type")

    config = DATA_BROWSER_CONFIG.get(dt)
    if not config:
        raise HTTPException(status_code=400, detail="Unsupported data_type")

    model = config["model"]
    record = session.exec(
        select(model)
        .where(model.id == record_id)
        .where(model.instance_id == instance_id)
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    field_rows: List[Dict[str, Any]] = []
    for col in model.__table__.columns:  # type: ignore[attr-defined]
        name = col.name
        value = getattr(record, name, None)
        serialized = _serialize_value(value)
        reference = _resolve_data_browser_field_reference(
            session=session,
            instance_id=instance_id,
            current_data_type=dt,
            field_name=name,
            field_value=value,
            record=record,
        )
        field_rows.append(
            {
                "name": name,
                "value": serialized,
                "reference": reference,
            }
        )

    sn_table = DATA_PULL_TYPE_TO_SN_TABLE.get(dt)
    sn_sys_id = getattr(record, "sn_sys_id", None)
    instance_record_url = None
    if sn_table and sn_sys_id:
        instance_record_url = f"{instance.url.rstrip('/')}/{sn_table}.do?sys_id={sn_sys_id}"

    context = {
        "request": request,
        "instance": instance,
        "data_type": dt.value,
        "data_type_label": DATA_TYPE_LABELS.get(dt.value, dt.value),
        "record_id": record_id,
        "preview_mode": preview,
        "full_record_url": _build_data_browser_record_reference_url(
            instance_id=instance_id,
            data_type=dt,
            record_id=record_id,
        ),
        "field_rows": field_rows,
        "raw_json": getattr(record, "raw_data_json", None),
        "instance_record_url": instance_record_url,
    }

    if preview:
        return templates.TemplateResponse("data_browser_record_preview.html", context)
    return templates.TemplateResponse("data_browser_record.html", context)
