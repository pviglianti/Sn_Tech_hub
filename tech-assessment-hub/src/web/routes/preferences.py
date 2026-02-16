"""Preferences routes (integration properties page + API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ...database import get_session
from ...models import Instance
from ...services.integration_properties import (
    PROPERTY_SCOPE_APPLICATION,
    SECTION_ORDER,
    list_integration_property_snapshots,
    load_display_timezone,
    update_integration_properties,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_preferences_router(require_mcp_admin: Callable[..., Dict[str, Any]]) -> APIRouter:
    """Create preferences router with injected admin dependency."""
    preferences_router = APIRouter(tags=["preferences"])

    def _resolve_instance_scope(instance_id: Optional[int], session: Session) -> Optional[int]:
        if instance_id is None:
            return None
        instance = session.get(Instance, instance_id)
        if not instance:
            raise HTTPException(status_code=404, detail=f"Instance not found: {instance_id}")
        return instance.id

    @preferences_router.get("/integration-properties", response_class=HTMLResponse)
    async def integration_properties_page(
        request: Request,
        instance_id: Optional[int] = Query(default=None),
        session: Session = Depends(get_session),
    ):
        """Integration properties management page."""
        resolved_instance_id = _resolve_instance_scope(instance_id, session)
        snapshots = list_integration_property_snapshots(session, instance_id=resolved_instance_id)
        instances = session.exec(select(Instance).order_by(Instance.name.asc())).all()
        instance_options = [{"id": inst.id, "name": inst.name} for inst in instances]
        return templates.TemplateResponse(
            "integration_properties.html",
            {
                "request": request,
                "properties_json": json.dumps(snapshots),
                "section_order_json": json.dumps(SECTION_ORDER),
                "instance_options_json": json.dumps(instance_options),
                "selected_instance_id": resolved_instance_id,
                "property_scope": PROPERTY_SCOPE_APPLICATION,
            },
        )

    @preferences_router.get("/api/display-timezone")
    async def api_display_timezone(
        instance_id: Optional[int] = Query(default=None),
        session: Session = Depends(get_session),
    ):
        """Public endpoint returning the configured display timezone IANA string."""
        resolved_instance_id = _resolve_instance_scope(instance_id, session)
        return {"timezone": load_display_timezone(session, instance_id=resolved_instance_id)}

    @preferences_router.get("/api/integration-properties")
    async def api_integration_properties(
        instance_id: Optional[int] = Query(default=None),
        session: Session = Depends(get_session),
        _: Dict[str, Any] = Depends(require_mcp_admin),
    ):
        """Admin-only integration properties catalog + effective values."""
        resolved_instance_id = _resolve_instance_scope(instance_id, session)
        return {
            "success": True,
            "scope": PROPERTY_SCOPE_APPLICATION,
            "instance_id": resolved_instance_id,
            "properties": list_integration_property_snapshots(session, instance_id=resolved_instance_id),
        }

    @preferences_router.post("/api/integration-properties")
    async def api_integration_properties_update(
        request: Request,
        instance_id: Optional[int] = Query(default=None),
        session: Session = Depends(get_session),
        _: Dict[str, Any] = Depends(require_mcp_admin),
    ):
        """Admin-only integration properties update endpoint."""
        resolved_instance_id = _resolve_instance_scope(instance_id, session)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        updates = payload.get("properties")
        if not isinstance(updates, dict) or not updates:
            raise HTTPException(status_code=400, detail="'properties' object is required")
        try:
            properties = update_integration_properties(session, updates, instance_id=resolved_instance_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "success": True,
            "scope": PROPERTY_SCOPE_APPLICATION,
            "instance_id": resolved_instance_id,
            "properties": properties,
        }

    return preferences_router
