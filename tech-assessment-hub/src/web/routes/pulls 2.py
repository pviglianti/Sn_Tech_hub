"""Data pull and instance data management routes extracted from server.py."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from ...database import get_session
from ...models import (
    Application,
    CustomerUpdateXML,
    DataPullStatus,
    DataPullType,
    Instance,
    InstanceAppFileType,
    InstanceDataPull,
    JobRun,
    JobRunStatus,
    InstancePlugin,
    MetadataCustomization,
    Package,
    PluginView,
    Scope,
    TableDefinition,
    UpdateSet,
    VersionHistory,
)
from ...services.data_pull_executor import _estimate_expected_total, _get_db_derived_watermark
from ...services.dictionary_pull_orchestrator import get_dictionary_pull_status
from ...services.encryption import decrypt_password
from ...services.integration_sync_runner import resolve_delta_decision
from ...services.sn_client import ServiceNowClient


def create_pulls_router(
    *,
    templates: Jinja2Templates,
    start_data_pull_job: Callable[[int, List[str], str], bool],
    clear_instance_data_types: Callable[[Session, int, List[DataPullType]], None],
    get_active_data_pull_job: Callable[[int], Optional[Any]],
    request_cancel_data_pulls: Callable[[Session, int, List[DataPullType], bool], None],
) -> APIRouter:
    """Create pulls router with injected server helpers."""
    pulls_router = APIRouter(tags=["pulls"])
    _ACTIVE_RUN_STATUSES = [JobRunStatus.queued, JobRunStatus.running]

    def _data_type_label(data_type: str) -> str:
        return str(data_type or "").replace("_", " ").title()

    def _parse_requested_data_types(raw_json: Optional[str]) -> List[str]:
        if not raw_json:
            return []
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                return [str(value).strip() for value in parsed if str(value).strip()]
        except json.JSONDecodeError:
            return []
        return []

    def _serialize_run_summary(
        run: Optional[JobRun],
        pull_status: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not run:
            return None

        data_types = _parse_requested_data_types(run.requested_data_types_json)
        queue_total = max(int(run.queue_total or 0), len(data_types))
        queue_completed = min(max(int(run.queue_completed or 0), 0), queue_total) if queue_total > 0 else 0

        current_data_type = run.current_data_type
        if run.status == JobRunStatus.running and not current_data_type:
            for dt in data_types:
                status = (pull_status.get(dt) or {}).get("status")
                if status == DataPullStatus.running.value:
                    current_data_type = dt
                    break

        current_pull = pull_status.get(current_data_type) if current_data_type else None
        current_expected = None
        current_pulled = None
        current_in_db = None
        current_fraction = 0.0
        if current_pull:
            current_expected = current_pull.get("expected_total")
            current_pulled = current_pull.get("records_pulled")
            current_in_db = current_pull.get("record_count")
            if current_expected and int(current_expected) > 0:
                current_fraction = min(1.0, float(current_pulled or 0) / float(current_expected))

        if run.status in {JobRunStatus.completed, JobRunStatus.failed, JobRunStatus.cancelled}:
            progress_pct = 100
        elif queue_total > 0:
            progress_pct = int(round(((queue_completed + current_fraction) / float(queue_total)) * 100))
        else:
            progress_pct = 0

        eta_seconds = run.estimated_remaining_seconds
        if run.status == JobRunStatus.running:
            completed_durations: List[float] = []
            for dt in data_types:
                pull = pull_status.get(dt) or {}
                if pull.get("status") in {
                    DataPullStatus.completed.value,
                    DataPullStatus.failed.value,
                    DataPullStatus.cancelled.value,
                }:
                    duration = pull.get("duration")
                    if duration is not None and float(duration) > 0:
                        completed_durations.append(float(duration))

            avg_duration = (sum(completed_durations) / len(completed_durations)) if completed_durations else None
            current_remaining = None
            if current_pull:
                current_duration = current_pull.get("duration")
                if (
                    current_duration is not None
                    and current_expected is not None
                    and int(current_expected) > 0
                    and (current_pulled or 0) > 0
                ):
                    fraction = min(1.0, float(current_pulled) / float(current_expected))
                    current_remaining = max(0.0, (float(current_duration) / fraction) - float(current_duration))
                elif avg_duration is not None:
                    current_remaining = avg_duration

            remaining_after_current = max(0, queue_total - queue_completed - (1 if current_data_type else 0))
            if current_remaining is not None or avg_duration is not None:
                eta_seconds = max(
                    0.0,
                    float(current_remaining or 0.0) + float(avg_duration or 0.0) * float(remaining_after_current),
                )
            else:
                eta_seconds = None

        return {
            "run_uid": run.run_uid,
            "status": run.status.value if hasattr(run.status, "value") else str(run.status),
            "module": run.module,
            "job_type": run.job_type,
            "mode": run.mode,
            "queue_total": queue_total,
            "queue_completed": queue_completed,
            "queue_remaining": max(0, queue_total - queue_completed - (1 if current_data_type else 0)),
            "current_index": run.current_index,
            "current_data_type": current_data_type,
            "current_data_type_label": _data_type_label(current_data_type) if current_data_type else None,
            "current_records_pulled": current_pulled,
            "current_expected_total": current_expected,
            "current_records_in_db": current_in_db,
            "progress_pct": progress_pct,
            "estimated_remaining_seconds": eta_seconds,
            "message": run.message,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "last_heartbeat_at": run.last_heartbeat_at.isoformat() if run.last_heartbeat_at else None,
        }

    def _get_active_run_uid(session: Session, instance_id: int) -> Optional[str]:
        active = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == "preflight")
            .where(JobRun.job_type == "data_pull")
            .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
            .order_by(JobRun.created_at.desc())
        ).first()
        return active.run_uid if active else None

    def _instance_record_counts(session: Session, instance_id: int) -> Dict[str, int]:
        return {
            DataPullType.update_sets.value: session.exec(
                select(func.count()).select_from(UpdateSet).where(UpdateSet.instance_id == instance_id)
            ).one(),
            DataPullType.customer_update_xml.value: session.exec(
                select(func.count()).select_from(CustomerUpdateXML).where(CustomerUpdateXML.instance_id == instance_id)
            ).one(),
            DataPullType.version_history.value: session.exec(
                select(func.count()).select_from(VersionHistory).where(VersionHistory.instance_id == instance_id)
            ).one(),
            DataPullType.metadata_customization.value: session.exec(
                select(func.count()).select_from(MetadataCustomization).where(MetadataCustomization.instance_id == instance_id)
            ).one(),
            DataPullType.app_file_types.value: session.exec(
                select(func.count()).select_from(InstanceAppFileType).where(InstanceAppFileType.instance_id == instance_id)
            ).one(),
            DataPullType.plugins.value: session.exec(
                select(func.count()).select_from(InstancePlugin).where(InstancePlugin.instance_id == instance_id)
            ).one(),
            DataPullType.plugin_view.value: session.exec(
                select(func.count()).select_from(PluginView).where(PluginView.instance_id == instance_id)
            ).one(),
            DataPullType.scopes.value: session.exec(
                select(func.count()).select_from(Scope).where(Scope.instance_id == instance_id)
            ).one(),
            DataPullType.packages.value: session.exec(
                select(func.count()).select_from(Package).where(Package.instance_id == instance_id)
            ).one(),
            DataPullType.applications.value: session.exec(
                select(func.count()).select_from(Application).where(Application.instance_id == instance_id)
            ).one(),
            DataPullType.sys_db_object.value: session.exec(
                select(func.count()).select_from(TableDefinition).where(TableDefinition.instance_id == instance_id)
            ).one(),
        }

    @pulls_router.post("/api/data-browser/pull")
    async def api_data_browser_pull(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """API: Trigger a data pull for a single data type."""
        payload = await request.json()
        instance_id = payload.get("instance_id")
        data_type = payload.get("data_type")
        mode = payload.get("mode", "full")

        if not instance_id or not data_type:
            raise HTTPException(status_code=400, detail="instance_id and data_type are required")

        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        try:
            DataPullType(data_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid data_type")

        valid_modes = ["full", "delta", "smart"]
        if mode not in valid_modes:
            raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {valid_modes}")

        started = start_data_pull_job(instance_id, [data_type], mode)
        return {
            "success": True,
            "started": started,
            "mode": mode,
            "run_uid": _get_active_run_uid(session, instance_id),
        }

    @pulls_router.get("/api/data-browser/sync-analysis")
    async def api_sync_analysis(
        instance_id: int,
        data_type: str,
        session: Session = Depends(get_session),
    ):
        """API: Get sync analysis for a data type without actually syncing."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        try:
            dt = DataPullType(data_type)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid data_type")

        pull = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type == dt)
        ).first()

        model_map = {
            DataPullType.update_sets: UpdateSet,
            DataPullType.customer_update_xml: CustomerUpdateXML,
            DataPullType.version_history: VersionHistory,
            DataPullType.metadata_customization: MetadataCustomization,
            DataPullType.app_file_types: InstanceAppFileType,
            DataPullType.plugins: InstancePlugin,
            DataPullType.plugin_view: PluginView,
            DataPullType.scopes: Scope,
            DataPullType.packages: Package,
            DataPullType.applications: Application,
            DataPullType.sys_db_object: TableDefinition,
        }

        model_class = model_map.get(dt)
        if not model_class:
            raise HTTPException(status_code=400, detail="Unsupported data_type")

        local_count = session.exec(
            select(func.count())
            .select_from(model_class)
            .where(model_class.instance_id == instance_id)
        ).one()

        try:
            instance_password = decrypt_password(instance.password_encrypted)
            client = ServiceNowClient(instance.url, instance.username, instance_password)
            remote_count = _estimate_expected_total(session, client, dt, since=None, instance_id=instance_id) or 0
        except Exception as exc:
            return {
                "data_type": data_type,
                "error": f"Failed to get remote count: {str(exc)}",
                "local_count": local_count,
                "remote_count": None,
            }

        last_sys_updated_on = _get_db_derived_watermark(session, instance_id, dt)
        if last_sys_updated_on is None and pull:
            last_sys_updated_on = pull.last_sys_updated_on

        delta_probe_count = None
        if last_sys_updated_on is not None:
            delta_probe_count = _estimate_expected_total(
                session,
                client,
                dt,
                since=last_sys_updated_on,
                instance_id=instance_id,
            )

        decision = resolve_delta_decision(
            local_count=local_count,
            remote_count=remote_count,
            watermark=last_sys_updated_on,
            delta_probe_count=delta_probe_count,
        )

        return {
            "data_type": data_type,
            "recommended_mode": decision.mode,
            "reason": decision.reason,
            "local_count": decision.local_count,
            "remote_count": decision.remote_count,
            "delta_probe_count": decision.delta_probe_count,
            "last_sync": pull.last_pulled_at.isoformat() if pull and pull.last_pulled_at else None,
        }

    @pulls_router.post("/api/data-browser/clear")
    async def api_data_browser_clear(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """API: Clear cached data for a single type or all types for an instance."""
        payload = await request.json()
        instance_id = payload.get("instance_id")
        data_type = payload.get("data_type")

        if not instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")

        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        if data_type:
            try:
                data_types = [DataPullType(data_type)]
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid data_type")
        else:
            data_types = list(DataPullType)

        clear_instance_data_types(session, instance_id, data_types)

        return {"success": True}

    @pulls_router.post("/api/data-browser/cancel")
    async def api_data_browser_cancel(
        request: Request,
        session: Session = Depends(get_session),
    ):
        """API: Request cancellation for running/queued data pulls."""
        payload = await request.json()
        instance_id = payload.get("instance_id")
        data_type = payload.get("data_type")

        if not instance_id:
            raise HTTPException(status_code=400, detail="instance_id is required")

        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        if data_type:
            try:
                data_types = [DataPullType(data_type)]
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid data_type")
        else:
            data_types = list(DataPullType)

        job = get_active_data_pull_job(instance_id)
        request_cancel_data_pulls(session, instance_id, data_types, signal_workers=(job is not None))

        if not data_type and job:
            job.cancel_event.set()

        return {"success": True}

    @pulls_router.post("/api/instances/{instance_id}/data-refresh")
    async def api_instance_data_refresh(
        request: Request,
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """API: Trigger a full refresh of all reference data for an instance."""
        mode = "full"
        try:
            payload = await request.json()
            if isinstance(payload, dict) and payload.get("mode"):
                mode = payload["mode"]
        except Exception:
            mode = "full"

        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        data_types = [dt.value for dt in DataPullType]
        started = start_data_pull_job(instance_id, data_types, mode)
        return {
            "success": True,
            "started": started,
            "run_uid": _get_active_run_uid(session, instance_id),
        }

    @pulls_router.get("/instances/{instance_id}/data", response_class=HTMLResponse)
    async def instance_data_page(
        request: Request,
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Data management page for an instance."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        data_pulls = {}
        for data_type in DataPullType:
            pull = session.exec(
                select(InstanceDataPull)
                .where(InstanceDataPull.instance_id == instance_id)
                .where(InstanceDataPull.data_type == data_type)
            ).first()
            if not pull:
                pull = InstanceDataPull(
                    instance_id=instance_id,
                    data_type=data_type,
                    status=DataPullStatus.idle,
                )
                session.add(pull)
            data_pulls[data_type.value] = pull

        session.commit()

        record_counts = _instance_record_counts(session, instance_id)

        return templates.TemplateResponse("instance_data.html", {
            "request": request,
            "instance": instance,
            "data_pulls": data_pulls,
            "record_counts": record_counts,
            "data_types": [dt.value for dt in DataPullType],
        })

    @pulls_router.post("/instances/{instance_id}/data/pull")
    async def start_data_pull(
        request: Request,
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Start a data pull for selected data types."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        form_data = await request.form()
        data_types = form_data.getlist("data_types")
        mode = form_data.get("mode", "full")

        if not data_types:
            return RedirectResponse(url=f"/instances/{instance_id}/data", status_code=303)

        start_data_pull_job(instance_id, data_types, mode)

        return RedirectResponse(url=f"/instances/{instance_id}/data", status_code=303)

    @pulls_router.get("/api/instances/{instance_id}/data-status")
    async def api_instance_data_status(
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """API: Get data pull status for polling."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        data_pulls = session.exec(
            select(InstanceDataPull)
            .where(InstanceDataPull.instance_id == instance_id)
            .where(InstanceDataPull.data_type.in_(list(DataPullType)))
        ).all()

        record_counts = _instance_record_counts(session, instance_id)

        pull_status = {}
        for pull in data_pulls:
            duration = None
            if pull.started_at and pull.completed_at:
                duration = (pull.completed_at - pull.started_at).total_seconds()
            elif pull.started_at:
                duration = (datetime.utcnow() - pull.started_at).total_seconds()

            pull_status[pull.data_type.value] = {
                "status": pull.status.value,
                "records_pulled": pull.records_pulled,
                "last_pulled_at": pull.last_pulled_at.isoformat() if pull.last_pulled_at else None,
                "started_at": pull.started_at.isoformat() if pull.started_at else None,
                "completed_at": pull.completed_at.isoformat() if pull.completed_at else None,
                "duration": duration,
                "error_message": pull.error_message,
                "cancel_requested": pull.cancel_requested,
                "cancel_requested_at": pull.cancel_requested_at.isoformat() if pull.cancel_requested_at else None,
                "expected_total": pull.expected_total,
                "expected_total_at": pull.expected_total_at.isoformat() if pull.expected_total_at else None,
                "record_count": record_counts.get(pull.data_type.value, 0),
            }

        active_run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == "preflight")
            .where(JobRun.job_type == "data_pull")
            .where(JobRun.status.in_(_ACTIVE_RUN_STATUSES))
            .order_by(JobRun.created_at.desc())
        ).first()
        latest_run = session.exec(
            select(JobRun)
            .where(JobRun.instance_id == instance_id)
            .where(JobRun.module == "preflight")
            .where(JobRun.job_type == "data_pull")
            .order_by(JobRun.created_at.desc())
        ).first()

        return {
            "instance_id": instance_id,
            "pulls": pull_status,
            "active_run": _serialize_run_summary(active_run, pull_status),
            "latest_run": _serialize_run_summary(latest_run, pull_status),
            "record_counts": record_counts,
            "last_updated": datetime.utcnow().isoformat(),
        }

    @pulls_router.get("/api/instances/{instance_id}/dictionary-pull-status")
    async def api_dictionary_pull_status(
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """API: Get dictionary pull progress for polling."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        return get_dictionary_pull_status(instance_id)

    @pulls_router.get("/api/tables/{sn_table_name}/field-schema")
    async def api_table_field_schema(
        sn_table_name: str,
        instance_id: int = Query(...),
        session: Session = Depends(get_session),
    ):
        """API: Get field metadata for a ServiceNow table."""
        from ...models_sn import SnFieldMapping, SnTableRegistry

        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        registry = session.exec(
            select(SnTableRegistry)
            .where(SnTableRegistry.instance_id == instance_id)
            .where(SnTableRegistry.sn_table_name == sn_table_name)
        ).first()

        if not registry:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{sn_table_name}' not found in registry for instance {instance_id}",
            )

        field_mappings = session.exec(
            select(SnFieldMapping)
            .where(SnFieldMapping.registry_id == registry.id)
            .where(SnFieldMapping.is_active == True)
        ).all()

        fields = []
        for fm in field_mappings:
            fields.append({
                "element": fm.sn_element,
                "column_label": fm.column_label or fm.sn_element,
                "internal_type": fm.sn_internal_type,
                "is_reference": fm.is_reference,
                "reference_table": fm.sn_reference_table,
                "is_mandatory": fm.is_mandatory,
                "is_read_only": fm.is_read_only,
            })

        return {
            "table_name": registry.sn_table_name,
            "table_label": registry.sn_table_label or registry.sn_table_name,
            "fields": fields,
        }

    @pulls_router.post("/instances/{instance_id}/data/clear")
    async def clear_instance_data(
        request: Request,
        instance_id: int,
        session: Session = Depends(get_session),
    ):
        """Clear cached data for selected data types."""
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail="Instance not found")

        form_data = await request.form()
        data_type_values = form_data.getlist("clear_data_types")
        data_types: List[DataPullType] = []
        for dt_str in data_type_values:
            try:
                data_types.append(DataPullType(dt_str))
            except ValueError:
                continue

        if data_types:
            clear_instance_data_types(session, instance_id, data_types)

        return RedirectResponse(url=f"/instances/{instance_id}/data", status_code=303)

    return pulls_router
