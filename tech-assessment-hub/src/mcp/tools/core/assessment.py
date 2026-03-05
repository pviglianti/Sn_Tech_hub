"""MCP tool: run_assessment — create assessment and trigger scans.

Creates an Assessment record and launches scans in a background thread.
Returns immediately with assessment_id; use get_assessment_results or
get_customization_summary to see results when scans complete.
"""

from typing import Any, Dict
import threading
from datetime import datetime

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    Instance, Assessment, AssessmentType, AssessmentState, GlobalApp,
    NumberSequence,
)
from ....services.encryption import decrypt_password
from ....services.integration_properties import load_ai_analysis_properties
from ....services.sn_client import ServiceNowClient
from ....services.scan_executor import run_scans_for_assessment
from ....database import get_session


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {
            "type": "integer",
            "description": "Instance to assess.",
        },
        "name": {
            "type": "string",
            "description": "Assessment name.",
        },
        "assessment_type": {
            "type": "string",
            "enum": ["global_app", "platform_global", "table", "plugin", "scoped_app"],
            "description": "Type of assessment to run.",
            "default": "platform_global",
        },
        "target_app_id": {
            "type": "integer",
            "description": "GlobalApp ID to target (for global_app type).",
        },
        "scope_filter": {
            "type": "string",
            "enum": ["global", "scoped", "all"],
            "description": "Scope filter. Default: global.",
            "default": "global",
        },
        "mode": {
            "type": "string",
            "enum": ["full", "delta", "rebuild"],
            "description": "Scan mode. Default: full.",
            "default": "full",
        },
    },
    "required": ["instance_id", "name"],
}


def _generate_assessment_number(session: Session) -> str:
    """Generate next ASMT# using NumberSequence."""
    seq = session.exec(
        select(NumberSequence).where(NumberSequence.prefix == "ASMT")
    ).first()
    if not seq:
        seq = NumberSequence(prefix="ASMT", current_value=0)
        session.add(seq)
    number = seq.next_number()
    session.add(seq)
    return number


def _run_scans_in_background(assessment_id: int, mode: str) -> None:
    """Background thread that runs assessment scans with its own session."""
    session = next(get_session())
    try:
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            return
        instance = session.get(Instance, assessment.instance_id)
        if not instance:
            return
        client = ServiceNowClient(
            instance.url,
            instance.username,
            decrypt_password(instance.password_encrypted),
            instance_id=instance.id,
        )
        run_scans_for_assessment(session, assessment, client, mode)
    except Exception:
        pass  # Errors recorded in Scan.error_message
    finally:
        session.close()


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = int(params["instance_id"])
    name = params["name"]
    assessment_type_str = params.get("assessment_type", "platform_global")
    scope_filter = params.get("scope_filter", "global")
    mode = params.get("mode", "full")
    target_app_id = params.get("target_app_id")

    instance = session.get(Instance, instance_id)
    if not instance:
        raise ValueError(f"Instance not found: {instance_id}")

    assessment_type = AssessmentType(assessment_type_str)

    # Generate ASMT number
    number = _generate_assessment_number(session)

    # Snapshot current global analysis_mode so assessment is immune to later changes
    ai_props = load_ai_analysis_properties(session, instance_id=instance_id)

    assessment = Assessment(
        instance_id=instance_id,
        number=number,
        name=name,
        assessment_type=assessment_type,
        scope_filter=scope_filter,
        state=AssessmentState.in_progress,
        analysis_mode=ai_props.analysis_mode,
    )

    if target_app_id and assessment_type == AssessmentType.global_app:
        assessment.target_app_id = target_app_id

    session.add(assessment)
    session.commit()
    session.refresh(assessment)

    # Launch scans in background
    thread = threading.Thread(
        target=_run_scans_in_background,
        args=(assessment.id, mode),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "assessment_id": assessment.id,
        "assessment_number": assessment.number,
        "name": assessment.name,
        "type": assessment_type.value,
        "scope_filter": scope_filter,
        "mode": mode,
        "status": "running",
        "message": "Assessment created and scans started in background. Use get_customization_summary or get_assessment_results to view results.",
    }


TOOL_SPEC = ToolSpec(
    name="run_assessment",
    description=(
        "Create a new assessment and trigger scans against a ServiceNow instance. "
        "Scans run in background; returns immediately with assessment_id. "
        "Use get_customization_summary or get_assessment_results to see results."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
