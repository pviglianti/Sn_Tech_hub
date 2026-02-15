"""MCP admin-related page routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ...database import get_session
from ...models import Instance

mcp_admin_router = APIRouter(tags=["mcp-admin"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@mcp_admin_router.get("/mcp-console", response_class=HTMLResponse)
async def mcp_console_page(request: Request, session: Session = Depends(get_session)):
    """MCP console page for testing JSON-RPC calls."""
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
        "mcp_console.html",
        {
            "request": request,
            "instances_json": json.dumps(instances_payload),
        },
    )
