"""Web route — POST /api/assessments/{id}/run-stage.

Bridges the web UI to the SkillDispatcher service. Used by the
"Run AI Stage" buttons in the assessment detail page.

Default mode: fire-and-forget. We spawn the skill in a background thread
and return 202 immediately with a stream_id. The browser subscribes to
GET /api/assessments/{id}/ai-stream?stream_id=<id> for live events. This
avoids nginx's proxy_read_timeout (600s) killing long runs.

For callers that still want the old synchronous behavior — e.g. curl
scripts that expect the final result in the HTTP response — pass
{"blocking": true}.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...database import get_session
from ...models import Assessment
from ...services.skill_dispatcher import (
    STAGE_TO_SKILL,
    SkillNotFoundError,
    run_skill,
    start_skill_background,
)


logger = logging.getLogger(__name__)


run_stage_router = APIRouter(tags=["run-stage"])


@run_stage_router.post("/api/assessments/{assessment_id}/run-stage")
def api_run_stage(
    assessment_id: int,
    payload: Optional[Dict[str, Any]] = None,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    payload = payload or {}
    stage = (payload.get("stage") or "").strip()
    if not stage:
        raise HTTPException(status_code=400, detail="`stage` is required (e.g. 'scope_triage')")
    if stage not in STAGE_TO_SKILL:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stage '{stage}'. Valid: {sorted(STAGE_TO_SKILL.keys())}",
        )

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail=f"Assessment {assessment_id} not found")

    blocking = bool(payload.get("blocking", False))

    try:
        if blocking:
            result = run_skill(
                session=session,
                assessment_id=assessment_id,
                stage=stage,
                user_instructions=payload.get("instructions"),
                dispatcher=payload.get("dispatcher"),
                model=payload.get("model"),
                timeout_seconds=int(payload.get("timeout_seconds") or 1800),
            )
            stream_id = None
            if isinstance(result.raw, dict):
                stream_id = result.raw.get("stream_id")
            return {
                "assessment_id": assessment_id,
                "stage": stage,
                "mode": "blocking",
                "stream_id": stream_id,
                "success": result.success,
                "transport": result.transport,
                "tool_call_count": result.tool_call_count,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_read_tokens": result.cache_read_tokens,
                "cache_write_tokens": result.cache_write_tokens,
                "duration_seconds": round(result.duration_seconds, 2),
                "error": result.error,
                "output": result.output,
            }

        stream_id, stream_path = start_skill_background(
            assessment_id=assessment_id,
            stage=stage,
            user_instructions=payload.get("instructions"),
            dispatcher=payload.get("dispatcher"),
            model=payload.get("model"),
            timeout_seconds=int(payload.get("timeout_seconds") or 1800),
        )
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Skill missing: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_stage failed for assessment=%s stage=%s", assessment_id, stage)
        raise HTTPException(status_code=500, detail=f"run_stage failed: {exc}")

    return {
        "assessment_id": assessment_id,
        "stage": stage,
        "mode": "background",
        "status": "running",
        "stream_id": stream_id,
        "stream_url": f"/api/assessments/{assessment_id}/ai-stream?stream_id={stream_id}",
        "stream_log_path": str(stream_path),
        "message": (
            "AI stage started in background. Subscribe to stream_url for live "
            "events. Pass {\"blocking\": true} for the old synchronous behavior."
        ),
    }
