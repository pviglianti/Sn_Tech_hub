"""MCP tool: get_best_practices — fetch admin-curated best practice checks.

Returns the active best practice catalog, optionally filtered by the
sys_class_name of the artifact being reviewed. Use during recommendations
to cite specific, catalogued violations rather than making up ad-hoc rules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import BestPractice, BestPracticeCategory


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "applies_to": {
            "type": "string",
            "description": (
                "ServiceNow sys_class_name of the artifact being reviewed "
                "(e.g., 'sys_script', 'sys_script_include', 'sys_script_client'). "
                "Returns practices targeting that class PLUS generic ones "
                "(where applies_to is NULL/empty)."
            ),
        },
        "category": {
            "type": "string",
            "enum": [c.value for c in BestPracticeCategory],
            "description": "Filter by category.",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Filter by severity.",
        },
        "min_severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Only return practices at this severity or higher.",
        },
    },
}


_SEVERITY_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}


def _matches_applies_to(applies_to_raw: Optional[str], target_class: Optional[str]) -> bool:
    # No filter: include everything
    if not target_class:
        return True
    # Generic check (no applies_to set) — always matches
    if not applies_to_raw:
        return True
    parts = [p.strip() for p in applies_to_raw.split(",") if p.strip()]
    return target_class in parts


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    applies_to = params.get("applies_to")
    category = params.get("category")
    severity = params.get("severity")
    min_severity = params.get("min_severity")

    stmt = select(BestPractice).where(BestPractice.is_active == True)  # noqa: E712
    if category:
        stmt = stmt.where(BestPractice.category == category)
    if severity:
        stmt = stmt.where(BestPractice.severity == severity)

    rows = list(session.exec(stmt).all())

    if min_severity:
        threshold = _SEVERITY_RANK.get(min_severity, 0)
        rows = [r for r in rows if _SEVERITY_RANK.get(r.severity, 0) >= threshold]

    rows = [r for r in rows if _matches_applies_to(r.applies_to, applies_to)]

    # Sort: severity desc, then category, then code
    rows.sort(key=lambda r: (-_SEVERITY_RANK.get(r.severity, 0), r.category.value if hasattr(r.category, "value") else str(r.category), r.code))

    practices = []
    for r in rows:
        practices.append({
            "code": r.code,
            "title": r.title,
            "category": r.category.value if hasattr(r.category, "value") else str(r.category),
            "severity": r.severity,
            "description": r.description,
            "detection_hint": r.detection_hint,
            "recommendation": r.recommendation,
            "applies_to": r.applies_to,
            "source_url": r.source_url,
        })

    return {
        "applies_to_filter": applies_to,
        "category_filter": category,
        "count": len(practices),
        "best_practices": practices,
        "usage": (
            "Cite matching violations in recommendations by the `code` field "
            "(e.g., 'Violates SRV_CURRENT_UPDATE_BEFORE: current.update() in Before BR'). "
            "Use `detection_hint` to spot the pattern in code. Use `recommendation` "
            "text as the starting point for your fix guidance."
        ),
    }


TOOL_SPEC = ToolSpec(
    name="get_best_practices",
    description=(
        "Fetch the active best practice catalog. Filter by sys_class_name via "
        "`applies_to` to get only the checks relevant to the artifact you're "
        "reviewing. Use during the recommendations stage to cite specific "
        "catalogued violations (like current.update() in a Before BR, hardcoded "
        "sys_ids, GlideRecord in loops) with their severity and suggested fixes."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
