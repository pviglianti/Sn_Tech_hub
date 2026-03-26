"""Instance management routes extracted from server.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Form, HTTPException, Query as QueryParam, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case, text
from sqlmodel import Session, select

from ...database import get_session
from ...models import AuthType, ConnectionStatus, DataPullType, Instance, InstanceAppFileType
from ...services.dictionary_pull_orchestrator import start_dictionary_pull
from ...services.encryption import decrypt_password, encrypt_password
from ...services.sn_client import ServiceNowClient, ServiceNowClientError
from ...services.sn_client_factory import create_client_for_instance
from ...services.condition_query_builder import conditions_to_sql_where
from ...app_file_class_catalog import default_assessment_availability_for_instance_file_type
from ...artifact_detail_defs import get_class_label


# ---------------------------------------------------------------------------
# App File Options — field schema + data query (module-level, testable)
# ---------------------------------------------------------------------------

# Static field schema for InstanceAppFileType rows exposed via DataTable.js.
_APP_FILE_OPTIONS_FIELDS = [
    {"local_column": "is_available_for_assessment", "column_label": "Available", "kind": "boolean"},
    {"local_column": "is_default_for_assessment", "column_label": "Default Selected", "kind": "boolean"},
    {"local_column": "display_label", "column_label": "Display Name", "kind": "string"},
    {"local_column": "sys_class_name", "column_label": "Technical Name", "kind": "string"},
    {"local_column": "name", "column_label": "App File Type Name", "kind": "string"},
    {"local_column": "type", "column_label": "Type", "kind": "string"},
    {"local_column": "source_table_name", "column_label": "Source Table", "kind": "string"},
    {"local_column": "source_table", "column_label": "Source Table Sys ID", "kind": "string"},
    {"local_column": "source_field", "column_label": "Source Field", "kind": "string"},
    {"local_column": "parent_table_name", "column_label": "Parent Table", "kind": "string"},
    {"local_column": "parent_table", "column_label": "Parent Table Sys ID", "kind": "string"},
    {"local_column": "parent_field", "column_label": "Parent Field", "kind": "string"},
    {"local_column": "use_parent_scope", "column_label": "Use Parent Scope", "kind": "boolean"},
    {"local_column": "children_provider_class", "column_label": "Children Provider Class", "kind": "string"},
    {"local_column": "priority", "column_label": "Priority", "kind": "number"},
    {"local_column": "sn_sys_id", "column_label": "sys_id", "kind": "string"},
]

# Columns that live on the physical DB table (used for sorting / condition mapping).
# "display_label" is virtual (computed) — not in the table.
_VIRTUAL_COLUMNS = {"display_label"}

# Valid DB columns for sorting and condition filters.
_VALID_DB_COLUMNS = {f["local_column"] for f in _APP_FILE_OPTIONS_FIELDS if f["local_column"] not in _VIRTUAL_COLUMNS}


def _app_file_options_field_schema() -> Dict[str, Any]:
    """Return the static field schema for the app file options DataTable."""
    return {"fields": list(_APP_FILE_OPTIONS_FIELDS)}


def _resolve_display_label(row: InstanceAppFileType) -> str:
    """Compute a user-friendly display label for an InstanceAppFileType row."""
    label = (row.label or "").strip()
    name = (row.name or "").strip()
    sys_class = (row.sys_class_name or "").strip()
    if label and label != sys_class:
        return label
    if name and name != sys_class:
        return name
    if sys_class:
        return get_class_label(sys_class)
    return "-"


def _safe_sort_column(col_name: Optional[str]) -> Optional[str]:
    """Validate and return a safe column name for ORDER BY."""
    if not col_name:
        return None
    clean = "".join(ch for ch in col_name if ch.isalnum() or ch == "_")
    if clean in _VALID_DB_COLUMNS:
        return clean
    return None


def _row_to_dict(row: InstanceAppFileType) -> Dict[str, Any]:
    """Serialize an InstanceAppFileType row to a DataTable-compatible dict."""
    return {
        "id": row.id,
        "is_available_for_assessment": bool(row.is_available_for_assessment),
        "is_default_for_assessment": bool(row.is_default_for_assessment),
        "display_label": _resolve_display_label(row),
        "sys_class_name": row.sys_class_name or "",
        "name": row.name or "",
        "type": row.type or "",
        "source_table_name": row.source_table_name or "",
        "source_table": row.source_table or "",
        "source_field": row.source_field or "",
        "parent_table_name": row.parent_table_name or "",
        "parent_table": row.parent_table or "",
        "parent_field": row.parent_field or "",
        "use_parent_scope": row.use_parent_scope,
        "children_provider_class": row.children_provider_class or "",
        "priority": row.priority,
        "sn_sys_id": row.sn_sys_id or "",
    }


def _query_app_file_options_data(
    session: Session,
    *,
    instance_id: int,
    offset: int = 0,
    limit: int = 50,
    sort_field: Optional[str] = None,
    sort_dir: str = "asc",
    conditions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Query InstanceAppFileType rows with pagination, sorting, and condition filtering.

    Returns a dict with ``total`` (int) and ``rows`` (list of dicts) matching
    the DataTable.js data contract.
    """
    # Build base WHERE
    base_where = '"instance_id" = :instance_id'
    params: Dict[str, Any] = {"instance_id": instance_id}

    # Apply condition builder filters via raw SQL
    if conditions:
        cond_where, cond_params = conditions_to_sql_where(conditions)
        # conditions_to_sql_where uses ? placeholders — convert to named
        param_idx = 0
        named_cond = ""
        for ch in cond_where:
            if ch == "?":
                pname = f"_cp{param_idx}"
                named_cond += f":{pname}"
                params[pname] = cond_params[param_idx]
                param_idx += 1
            else:
                named_cond += ch
        base_where += " AND " + named_cond

    # Use session's connection for raw SQL (works in tests with in-memory DB)
    conn = session.connection()

    # Count query
    count_sql = f'SELECT COUNT(*) FROM "instance_app_file_type" WHERE {base_where}'
    total = conn.execute(text(count_sql), params).scalar() or 0

    # Data query with sorting
    safe_col = _safe_sort_column(sort_field)
    if safe_col:
        direction = "DESC" if sort_dir.lower() == "desc" else "ASC"
        order_clause = f'ORDER BY "{safe_col}" {direction}'
    else:
        order_clause = 'ORDER BY CASE WHEN "priority" IS NULL THEN 1 ELSE 0 END, "priority" ASC, "label" ASC, "sys_class_name" ASC'

    data_sql = f'SELECT "id" FROM "instance_app_file_type" WHERE {base_where} {order_clause} LIMIT :_limit OFFSET :_offset'
    data_params = dict(params)
    data_params["_limit"] = limit
    data_params["_offset"] = offset

    row_ids = [r[0] for r in conn.execute(text(data_sql), data_params).fetchall()]

    if not row_ids:
        return {"total": total, "rows": []}

    # Fetch full ORM objects in the correct order
    rows_by_id: Dict[int, InstanceAppFileType] = {}
    for row in session.exec(
        select(InstanceAppFileType).where(InstanceAppFileType.id.in_(row_ids))
    ).all():
        if row.id is not None:
            rows_by_id[row.id] = row

    ordered_rows = [rows_by_id[rid] for rid in row_ids if rid in rows_by_id]

    return {
        "total": total,
        "rows": [_row_to_dict(r) for r in ordered_rows],
    }


def create_instances_router(
    *,
    templates: Jinja2Templates,
    normalize_instance_url: Callable[[str], str],
    start_data_pull_job: Callable[..., bool],
    refresh_instance_metrics: Callable[[Instance], Dict[str, Any]],
    apply_instance_metrics: Callable[[Instance, Dict[str, Any]], None],
    sync_app_file_types_for_instance: Callable[..., str],
    resolve_app_file_display_label: Callable[..., str],
    coerce_bool_payload_field: Callable[[Dict[str, Any], str], Tuple[bool, Optional[bool]]],
    parse_app_file_type_ids_payload: Callable[[Dict[str, Any]], List[int]],
    set_instance_app_file_type_assessment_flags: Callable[..., Optional[InstanceAppFileType]],
    apply_instance_app_file_type_assessment_flags: Callable[..., None],
    start_proactive_vh_pull: Callable[[int], bool] = lambda _: False,
) -> APIRouter:
    """Create instance router with injected helpers from server module."""
    instances_router = APIRouter(tags=["instances"])

    @instances_router.get("/instances", response_class=HTMLResponse)
    async def list_instances(request: Request, session: Session = Depends(get_session)):
        """List all instances."""
        instances = session.exec(select(Instance)).all()
        return templates.TemplateResponse("instances.html", {
            "request": request,
            "instances": instances,
        })

    @instances_router.get("/instances/add", response_class=HTMLResponse)
    async def add_instance_form(request: Request):
        """Show add instance form."""
        return templates.TemplateResponse("instance_form.html", {
            "request": request,
            "instance": None,
            "action": "Add",
        })

    @instances_router.post("/instances/add")
    async def add_instance(
        request: Request,
        name: str = Form(...),
        url: str = Form(...),
        username: str = Form(...),
        password: str = Form(...),
        company: str = Form(None),
        auth_type: str = Form("basic"),
        client_id: str = Form(None),
        client_secret: str = Form(None),
        session: Session = Depends(get_session),
    ):
        """Add a new instance."""
        url = normalize_instance_url(url)

        # Validate auth_type
        if auth_type not in (AuthType.basic.value, AuthType.oauth.value):
            auth_type = AuthType.basic.value

        encrypted_password = encrypt_password(password)

        instance = Instance(
            name=name,
            url=url,
            auth_type=auth_type,
            username=username,
            password_encrypted=encrypted_password,
            company=company,
            client_id=client_id if auth_type == "oauth" else None,
            client_secret_encrypted=(
                encrypt_password(client_secret) if auth_type == "oauth" and client_secret else None
            ),
        )
        session.add(instance)
        session.commit()
        session.refresh(instance)

        # Auto-capture metrics on add (best-effort)
        try:
            client = create_client_for_instance(instance)
            test_result = client.test_connection()
            if not test_result.get("success"):
                raise ServiceNowClientError(test_result.get("message", "Authentication failed"))
            instance.connection_status = ConnectionStatus.connected
            instance.last_connected = datetime.utcnow()
            if test_result.get("version"):
                instance.instance_version = test_result.get("version")
            session.add(instance)
            session.commit()

            # Kick off app file type cache and tables metadata once connection is confirmed.
            # Initial connection always uses "full" mode — no delta/probe shortcuts.
            start_data_pull_job(
                instance.id,
                [DataPullType.app_file_types.value, DataPullType.sys_db_object.value],
                "full",
                source_context="initial_data",
            )

            # Kick off dictionary pull for all default tables.
            start_dictionary_pull(instance.id, source_context="initial_data")

            # Proactive VH pull — starts pulling all VH states in the background
            # so it's ready before the first assessment is run.
            start_proactive_vh_pull(instance.id)

            metrics = client.get_instance_metrics()
            apply_instance_metrics(instance, metrics)
            session.add(instance)
            session.commit()
        except ServiceNowClientError:
            pass

        return RedirectResponse(url="/instances", status_code=303)

    @instances_router.post("/instances/{instance_id}/test")
    async def test_instance_connection(
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Test connection to a ServiceNow instance."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        client = create_client_for_instance(instance)
        result = client.test_connection()

        if result["success"]:
            instance.connection_status = ConnectionStatus.connected
            instance.last_connected = datetime.utcnow()
            instance.instance_version = result.get("version")
        else:
            instance.connection_status = ConnectionStatus.failed

        instance.updated_at = datetime.utcnow()
        session.add(instance)
        session.commit()

        if result["success"]:
            # Connection test triggers a full pull — no delta/probe shortcuts.
            start_data_pull_job(
                instance.id,
                [DataPullType.app_file_types.value, DataPullType.sys_db_object.value],
                "full",
                source_context="initial_data",
            )
            start_dictionary_pull(instance.id, source_context="initial_data")
            start_proactive_vh_pull(instance.id)

        return result

    @instances_router.post("/instances/{instance_id}/metrics/refresh")
    async def refresh_instance_metrics_endpoint(
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Refresh stored metrics for an instance."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        try:
            metrics = refresh_instance_metrics(instance)
            session.add(instance)
            session.commit()
            return {"success": True, "metrics": metrics}
        except ServiceNowClientError as exc:
            return {"success": False, "error": str(exc)}

    @instances_router.post("/instances/{instance_id}/delete")
    async def delete_instance(
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Delete an instance."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        session.delete(instance)
        session.commit()

        return RedirectResponse(url="/instances", status_code=303)

    @instances_router.get("/instances/{instance_id}/assessment-app-file-options", response_class=HTMLResponse)
    async def instance_assessment_app_file_options_page(
        request: Request,
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Manage per-instance app file type availability for assessment slush bucket."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        def _load_rows() -> List[InstanceAppFileType]:
            return session.exec(
                select(InstanceAppFileType)
                .where(InstanceAppFileType.instance_id == instance_id)
                .order_by(
                    case((InstanceAppFileType.priority.is_(None), 1), else_=0),
                    InstanceAppFileType.priority.asc(),
                    InstanceAppFileType.label.asc(),
                    InstanceAppFileType.sys_class_name.asc(),
                )
            ).all()

        app_file_types = _load_rows()
        auto_sync_status: Optional[str] = None
        auto_sync_message: Optional[str] = None

        if not app_file_types:
            try:
                effective_mode = sync_app_file_types_for_instance(session, instance, mode="smart")
                if effective_mode == "skip":
                    sync_app_file_types_for_instance(session, instance, mode="full")
                app_file_types = _load_rows()
                auto_sync_status = "completed" if app_file_types else "empty"
            except Exception as exc:
                auto_sync_status = "failed"
                auto_sync_message = str(exc)

        available_count = sum(1 for row in app_file_types if bool(row.is_available_for_assessment))
        default_count = sum(
            1
            for row in app_file_types
            if bool(row.is_available_for_assessment) and bool(row.is_default_for_assessment)
        )
        display_labels_by_id = {
            row.id: resolve_app_file_display_label(
                explicit_label=row.label,
                record_name=row.name,
                sys_class_name=row.sys_class_name,
            )
            for row in app_file_types
            if row.id is not None
        }
        return templates.TemplateResponse(
            "instance_assessment_app_file_options.html",
            {
                "request": request,
                "instance": instance,
                "app_file_types": app_file_types,
                "display_labels_by_id": display_labels_by_id,
                "available_count": available_count,
                "default_count": default_count,
                "auto_sync_status": auto_sync_status,
                "auto_sync_message": auto_sync_message,
            },
        )

    @instances_router.get("/api/instances/{instance_id}/assessment-app-file-options/schema")
    async def api_app_file_options_schema(instance_id: int):
        """Return field schema for the app file options DataTable."""
        return _app_file_options_field_schema()

    @instances_router.get("/api/instances/{instance_id}/assessment-app-file-options/data")
    async def api_app_file_options_data(
        instance_id: int,
        offset: int = QueryParam(0),
        limit: int = QueryParam(50),
        sort_field: Optional[str] = QueryParam(None),
        sort_dir: str = QueryParam("asc"),
        conditions: Optional[str] = QueryParam(None),
        session: Session = Depends(get_session),
    ):
        """Return paginated, sortable, filterable app file options for DataTable.js."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        parsed_conditions = None
        if conditions:
            import json
            try:
                parsed_conditions = json.loads(conditions)
            except (json.JSONDecodeError, TypeError):
                pass

        return _query_app_file_options_data(
            session,
            instance_id=instance_id,
            offset=offset,
            limit=limit,
            sort_field=sort_field,
            sort_dir=sort_dir,
            conditions=parsed_conditions,
        )

    @instances_router.post("/api/instances/{instance_id}/assessment-app-file-options/{app_file_type_id}")
    async def update_instance_assessment_app_file_option(
        instance_id: int,
        app_file_type_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Update whether an instance app file type appears in assessment slush bucket options."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        has_available, is_available = coerce_bool_payload_field(payload, "is_available_for_assessment")
        has_default, is_default = coerce_bool_payload_field(payload, "is_default_for_assessment")

        if not has_available and not has_default:
            raise HTTPException(
                status_code=400,
                detail="Missing is_available_for_assessment or is_default_for_assessment",
            )

        updated = set_instance_app_file_type_assessment_flags(
            session,
            instance_id=instance_id,
            app_file_type_id=app_file_type_id,
            is_available_for_assessment=is_available if has_available else None,
            is_default_for_assessment=is_default if has_default else None,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Instance app file type not found")

        return {
            "success": True,
            "instance_id": instance_id,
            "app_file_type_id": updated.id,
            "is_available_for_assessment": bool(updated.is_available_for_assessment),
            "is_default_for_assessment": bool(updated.is_default_for_assessment),
        }

    @instances_router.post("/api/instances/{instance_id}/assessment-app-file-options/bulk/update")
    async def bulk_update_instance_assessment_app_file_options(
        instance_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Bulk update availability/default flags for multiple instance app file type rows."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        app_file_type_ids = parse_app_file_type_ids_payload(payload)

        has_available, is_available = coerce_bool_payload_field(payload, "is_available_for_assessment")
        has_default, is_default = coerce_bool_payload_field(payload, "is_default_for_assessment")
        if not has_available and not has_default:
            raise HTTPException(
                status_code=400,
                detail="Missing is_available_for_assessment or is_default_for_assessment",
            )

        rows = session.exec(
            select(InstanceAppFileType)
            .where(InstanceAppFileType.instance_id == instance_id)
            .where(InstanceAppFileType.id.in_(app_file_type_ids))
        ).all()
        row_by_id = {row.id: row for row in rows if row.id is not None}

        updated_rows: List[InstanceAppFileType] = []
        for row_id in app_file_type_ids:
            row = row_by_id.get(row_id)
            if not row:
                continue
            apply_instance_app_file_type_assessment_flags(
                row,
                is_available_for_assessment=is_available if has_available else None,
                is_default_for_assessment=is_default if has_default else None,
            )
            session.add(row)
            updated_rows.append(row)

        session.commit()
        for row in updated_rows:
            session.refresh(row)

        return {
            "success": True,
            "instance_id": instance_id,
            "updated_count": len(updated_rows),
            "rows": [
                {
                    "app_file_type_id": row.id,
                    "is_available_for_assessment": bool(row.is_available_for_assessment),
                    "is_default_for_assessment": bool(row.is_default_for_assessment),
                }
                for row in updated_rows
                if row.id is not None
            ],
        }

    @instances_router.post("/api/instances/{instance_id}/assessment-app-file-options/actions/restore-default-selected")
    async def restore_instance_assessment_app_file_option_defaults(
        instance_id: int,
        request: Request,
        session: Session = Depends(get_session),
    ):
        """Restore both availability and default-selected to catalog baseline for provided rows."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        app_file_type_ids = parse_app_file_type_ids_payload(payload)

        rows = session.exec(
            select(InstanceAppFileType)
            .where(InstanceAppFileType.instance_id == instance_id)
            .where(InstanceAppFileType.id.in_(app_file_type_ids))
        ).all()
        row_by_id = {row.id: row for row in rows if row.id is not None}

        updated_rows: List[InstanceAppFileType] = []
        for row_id in app_file_type_ids:
            row = row_by_id.get(row_id)
            if not row:
                continue
            baseline_default = default_assessment_availability_for_instance_file_type(
                sys_class_name=row.sys_class_name,
                label=row.label,
                name=row.name,
            )
            if baseline_default:
                row.is_available_for_assessment = True
            row.is_default_for_assessment = bool(baseline_default)
            session.add(row)
            updated_rows.append(row)

        session.commit()
        for row in updated_rows:
            session.refresh(row)

        return {
            "success": True,
            "instance_id": instance_id,
            "updated_count": len(updated_rows),
            "rows": [
                {
                    "app_file_type_id": row.id,
                    "is_available_for_assessment": bool(row.is_available_for_assessment),
                    "is_default_for_assessment": bool(row.is_default_for_assessment),
                }
                for row in updated_rows
                if row.id is not None
            ],
        }

    @instances_router.get("/instances/{instance_id}/edit", response_class=HTMLResponse)
    async def edit_instance_form(
        request: Request,
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Show edit instance form."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        return templates.TemplateResponse("instance_form.html", {
            "request": request,
            "instance": instance,
            "action": "Edit",
        })

    @instances_router.post("/instances/{instance_id}")
    async def update_instance(
        instance_id: int,
        name: str = Form(...),
        url: str = Form(...),
        username: str = Form(...),
        password: str = Form(None),
        company: str = Form(None),
        auth_type: str = Form("basic"),
        client_id: str = Form(None),
        client_secret: str = Form(None),
        session: Session = Depends(get_session),
    ):
        """Update an existing instance."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        if auth_type not in (AuthType.basic.value, AuthType.oauth.value):
            auth_type = AuthType.basic.value

        normalized_url = normalize_instance_url(url)

        instance.name = name
        instance.url = normalized_url
        instance.username = username
        instance.company = company
        instance.auth_type = auth_type

        if password:
            instance.password_encrypted = encrypt_password(password)

        # OAuth fields
        if auth_type == "oauth":
            if client_id is not None:
                instance.client_id = client_id
            if client_secret:
                instance.client_secret_encrypted = encrypt_password(client_secret)
            # Clear cached tokens when credentials change
            instance.oauth_access_token_encrypted = None
            instance.oauth_refresh_token_encrypted = None
            instance.oauth_token_expires_at = None
        else:
            # Switching to basic — clear OAuth fields
            instance.client_id = None
            instance.client_secret_encrypted = None
            instance.oauth_access_token_encrypted = None
            instance.oauth_refresh_token_encrypted = None
            instance.oauth_token_expires_at = None

        instance.connection_status = ConnectionStatus.untested
        instance.updated_at = datetime.utcnow()

        session.add(instance)
        session.commit()

        return RedirectResponse(url="/instances", status_code=303)

    return instances_router
