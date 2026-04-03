"""Scan Configuration admin page routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

scan_config_admin_router = APIRouter(tags=["scan-config-admin"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@scan_config_admin_router.get("/admin/scan-config/scopes", response_class=HTMLResponse)
async def admin_scopes_page(request: Request):
    """Scan Scopes (Global Apps) admin page."""
    return templates.TemplateResponse("admin_scopes.html", {"request": request})


@scan_config_admin_router.get("/admin/scan-config/file-classes", response_class=HTMLResponse)
async def admin_file_classes_page(request: Request):
    """App File Classes & Query Patterns admin page."""
    return templates.TemplateResponse("admin_file_classes.html", {"request": request})


@scan_config_admin_router.get("/admin/scan-config/assessment-types", response_class=HTMLResponse)
async def admin_assessment_types_page(request: Request):
    """Assessment Types admin page."""
    return templates.TemplateResponse("admin_assessment_types.html", {"request": request})


