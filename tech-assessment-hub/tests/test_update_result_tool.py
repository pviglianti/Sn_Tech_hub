from datetime import datetime
import json

from sqlmodel import select

from src.mcp.tools.core.update_result import handle
from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Customization,
    Disposition,
    Instance,
    OriginType,
    ReviewStatus,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.services.customization_sync import sync_single_result


def _seed_customized_result(db_session, create_customization: bool) -> int:
    instance = Instance(
        name="inst-update-result",
        url="https://inst-update-result.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)

    assessment = Assessment(
        number="ASMT0000998",
        name="Update result MCP tool test",
        instance_id=instance.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Update result scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    result = ScanResult(
        scan_id=scan.id,
        sys_id="result-sync-1",
        table_name="sys_script",
        name="Business Rule Sync",
        sys_class_name="sys_script",
        origin_type=OriginType.modified_ootb,
        review_status=ReviewStatus.pending_review,
        sys_updated_on=datetime.utcnow(),
    )
    db_session.add(result)
    db_session.commit()
    db_session.refresh(result)

    if create_customization:
        sync_single_result(db_session, result)

    return result.id


def test_update_result_tool_updates_existing_customization_row(db_session):
    result_id = _seed_customized_result(db_session, create_customization=True)

    payload = {
        "result_id": result_id,
        "review_status": "reviewed",
        "disposition": "keep_and_refactor",
        "observations": "Updated from MCP tool",
        "ai_observations": {
            "analysis_stage": "ai_analysis",
            "scope_decision": "adjacent",
            "directly_related_result_ids": [999],
        },
        "recommendation": "Refactor and modularize",
    }
    response = handle(payload, db_session)

    assert response["success"] is True

    customization = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result_id)
    ).first()
    assert customization is not None
    assert customization.review_status == ReviewStatus.reviewed
    assert customization.disposition == Disposition.keep_and_refactor
    assert customization.observations == "Updated from MCP tool"
    assert customization.recommendation == "Refactor and modularize"

    refreshed = db_session.get(ScanResult, result_id)
    assert refreshed is not None
    assert refreshed.ai_observations is not None
    assert "\"scope_decision\": \"adjacent\"" in refreshed.ai_observations


def test_update_result_tool_backfills_missing_customization_row(db_session):
    result_id = _seed_customized_result(db_session, create_customization=False)

    pre = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result_id)
    ).first()
    assert pre is None

    payload = {
        "result_id": result_id,
        "review_status": "review_in_progress",
        "recommendation": "New recommendation text",
    }
    response = handle(payload, db_session)

    assert response["success"] is True

    customization = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result_id)
    ).first()
    assert customization is not None
    assert customization.review_status == ReviewStatus.review_in_progress
    assert customization.recommendation == "New recommendation text"


def test_update_result_tool_preserves_prior_pass_history(db_session):
    result_id = _seed_customized_result(db_session, create_customization=True)
    seeded = db_session.get(ScanResult, result_id)
    assert seeded is not None
    seeded.ai_observations = json.dumps(
        {
            "pass_history": [
                {
                    "iteration": 1,
                    "stage": "ai_analysis",
                    "reason": "ai_loop_rerun",
                    "archived_at": "2026-04-04T00:00:00",
                    "summary_keys": ["scope_decision"],
                    "snapshot": {"scope_decision": "in_scope"},
                }
            ]
        },
        sort_keys=True,
    )
    db_session.add(seeded)
    db_session.commit()

    payload = {
        "result_id": result_id,
        "ai_observations": {
            "analysis_stage": "ai_analysis",
            "scope_decision": "adjacent",
            "scope_rationale": "Touches the target table indirectly.",
        },
    }
    response = handle(payload, db_session)

    assert response["success"] is True

    refreshed = db_session.get(ScanResult, result_id)
    assert refreshed is not None
    parsed = json.loads(refreshed.ai_observations or "{}")
    assert parsed.get("ai_loop_iteration") == 2
    assert parsed.get("scope_decision") == "adjacent"
    history = parsed.get("pass_history") or []
    assert len(history) == 1
    assert history[0]["snapshot"]["scope_decision"] == "in_scope"
