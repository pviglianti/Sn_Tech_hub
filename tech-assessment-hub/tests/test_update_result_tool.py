from datetime import datetime

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
