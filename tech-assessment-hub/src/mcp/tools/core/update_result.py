"""MCP tool: update_scan_result — AI writes analysis back to a scan result.

Allows the AI to record its disposition, observations, recommendation,
severity, category, and finding details on a ScanResult.
"""

import json
from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Disposition, FindingCategory, ReviewStatus, ScanResult, Severity
from ....services.ai_observation_history import merge_ai_observation_payload
from ....services.customization_sync import sync_single_result


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "result_id": {
            "type": "integer",
            "description": "ID of the scan result to update.",
        },
        "review_status": {
            "type": "string",
            "enum": ["pending_review", "review_in_progress", "reviewed"],
            "description": "Review status.",
        },
        "disposition": {
            "type": "string",
            "enum": ["remove", "keep_as_is", "keep_and_refactor", "needs_analysis"],
            "description": "Disposition recommendation.",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Finding severity.",
        },
        "category": {
            "type": "string",
            "enum": ["customization", "code_quality", "security", "performance", "upgrade_risk", "best_practice"],
            "description": "Finding category.",
        },
        "observations": {
            "type": "string",
            "description": "AI observations about the artifact.",
        },
        "ai_observations": {
            "type": ["object", "array", "string", "null"],
            "description": (
                "Structured AI analysis metadata for the artifact. Accepts either "
                "a JSON object/array or a pre-serialized JSON string."
            ),
        },
        "recommendation": {
            "type": "string",
            "description": "AI recommendation text.",
        },
        "finding_title": {
            "type": "string",
            "description": "Short title for the finding.",
        },
        "finding_description": {
            "type": "string",
            "description": "Detailed finding description.",
        },
        "is_out_of_scope": {
            "type": "boolean",
            "description": "Mark artifact as out of scope (no relation to assessed app or trivial change).",
        },
        "is_adjacent": {
            "type": "boolean",
            "description": "Mark artifact as adjacent (impacts assessed app but not a direct customization).",
        },
    },
    "required": ["result_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    result_id = int(params["result_id"])
    result = session.get(ScanResult, result_id)
    if not result:
        raise ValueError(f"ScanResult not found: {result_id}")

    updated_fields = []

    if "review_status" in params:
        result.review_status = ReviewStatus(params["review_status"])
        updated_fields.append("review_status")

    if "disposition" in params:
        result.disposition = Disposition(params["disposition"])
        updated_fields.append("disposition")

    if "severity" in params:
        result.severity = Severity(params["severity"])
        updated_fields.append("severity")

    if "category" in params:
        result.category = FindingCategory(params["category"])
        updated_fields.append("category")

    for text_field in ("observations", "recommendation", "finding_title", "finding_description"):
        if text_field in params:
            setattr(result, text_field, params[text_field])
            updated_fields.append(text_field)

    if "ai_observations" in params:
        raw_value = params["ai_observations"]
        if raw_value is None:
            result.ai_observations = None
        elif isinstance(raw_value, str):
            try:
                loaded = json.loads(raw_value)
            except Exception:
                result.ai_observations = raw_value
            else:
                if isinstance(loaded, dict):
                    result.ai_observations = json.dumps(
                        merge_ai_observation_payload(
                            result.ai_observations,
                            loaded,
                            stage=str(loaded.get("analysis_stage") or "").strip() or None,
                            replace_current=True,
                        ),
                        sort_keys=True,
                    )
                else:
                    result.ai_observations = raw_value
        elif isinstance(raw_value, dict):
            result.ai_observations = json.dumps(
                merge_ai_observation_payload(
                    result.ai_observations,
                    raw_value,
                    stage=str(raw_value.get("analysis_stage") or "").strip() or None,
                    replace_current=True,
                ),
                sort_keys=True,
            )
        else:
            result.ai_observations = json.dumps(raw_value, sort_keys=True)
        updated_fields.append("ai_observations")

    for bool_field in ("is_out_of_scope", "is_adjacent"):
        if bool_field in params:
            setattr(result, bool_field, bool(params[bool_field]))
            updated_fields.append(bool_field)

    if not updated_fields:
        return {"success": True, "message": "No fields to update.", "result_id": result_id}

    session.add(result)
    session.commit()
    session.refresh(result)
    sync_single_result(session, result)

    return {
        "success": True,
        "result_id": result_id,
        "updated_fields": updated_fields,
        "message": f"Updated {len(updated_fields)} field(s) on ScanResult {result_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="update_scan_result",
    description=(
        "Update a scan result with AI analysis: disposition, severity, category, "
        "observations, structured ai_observations, recommendation, and finding "
        "details. Only specified fields are updated - omitted fields are left unchanged."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
