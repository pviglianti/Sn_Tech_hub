"""Preferences routes (integration properties page + API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from ...database import get_session
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

    @preferences_router.get("/integration-properties", response_class=HTMLResponse)
    async def integration_properties_page(request: Request, session: Session = Depends(get_session)):
        """Integration properties management page."""
        snapshots = list_integration_property_snapshots(session)
        return templates.TemplateResponse(
            "integration_properties.html",
            {
                "request": request,
                "properties_json": json.dumps(snapshots),
                "section_order_json": json.dumps(SECTION_ORDER),
                "property_scope": PROPERTY_SCOPE_APPLICATION,
            },
        )

    @preferences_router.get("/api/display-timezone")
    async def api_display_timezone(session: Session = Depends(get_session)):
        """Public endpoint returning the configured display timezone IANA string."""
        return {"timezone": load_display_timezone(session)}

    @preferences_router.get("/api/integration-properties")
    async def api_integration_properties(
        session: Session = Depends(get_session),
        _: Dict[str, Any] = Depends(require_mcp_admin),
    ):
        """Admin-only integration properties catalog + effective values."""
        return {
            "success": True,
            "scope": PROPERTY_SCOPE_APPLICATION,
            "properties": list_integration_property_snapshots(session),
        }

    @preferences_router.post("/api/integration-properties")
    async def api_integration_properties_update(
        request: Request,
        session: Session = Depends(get_session),
        _: Dict[str, Any] = Depends(require_mcp_admin),
    ):
        """Admin-only integration properties update endpoint."""
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        updates = payload.get("properties")
        if not isinstance(updates, dict) or not updates:
            raise HTTPException(status_code=400, detail="'properties' object is required")
        try:
            properties = update_integration_properties(session, updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "success": True,
            "scope": PROPERTY_SCOPE_APPLICATION,
            "properties": properties,
        }

    return preferences_router
