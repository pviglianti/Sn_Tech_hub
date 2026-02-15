"""Instance management routes extracted from server.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import case
from sqlmodel import Session, select

from ...database import get_session
from ...models import ConnectionStatus, DataPullType, Instance, InstanceAppFileType
from ...services.dictionary_pull_orchestrator import start_dictionary_pull
from ...services.encryption import decrypt_password, encrypt_password
from ...services.sn_client import ServiceNowClient, ServiceNowClientError
from ...app_file_class_catalog import default_assessment_availability_for_instance_file_type


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
        session: Session = Depends(get_session),
    ):
        """Add a new instance."""
        url = normalize_instance_url(url)

        encrypted_password = encrypt_password(password)

        instance = Instance(
            name=name,
            url=url,
            username=username,
            password_encrypted=encrypted_password,
            company=company,
        )
        session.add(instance)
        session.commit()
        session.refresh(instance)

        # Auto-capture metrics on add (best-effort)
        try:
            instance_password = decrypt_password(instance.password_encrypted)
            client = ServiceNowClient(instance.url, instance.username, instance_password)
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

        instance_password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(instance.url, instance.username, instance_password)
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
        session: Session = Depends(get_session),
    ):
        """Update an existing instance."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        normalized_url = normalize_instance_url(url)

        instance.name = name
        instance.url = normalized_url
        instance.username = username
        instance.company = company

        if password:
            instance.password_encrypted = encrypt_password(password)

        instance.connection_status = ConnectionStatus.untested
        instance.updated_at = datetime.utcnow()

        session.add(instance)
        session.commit()

        return RedirectResponse(url="/instances", status_code=303)

    return instances_router
