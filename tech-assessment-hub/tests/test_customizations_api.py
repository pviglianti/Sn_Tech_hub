from datetime import datetime

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Customization,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.services.customization_sync import sync_single_result


def _seed_assessment_with_stale_customizations(db_session):
    instance = Instance(
        name="inst-customizations",
        url="https://inst-customizations.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)

    assessment = Assessment(
        number="ASMT0000999",
        name="Customization API stale rows",
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
        name="Stale customization scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    db_session.add(
        ScanResult(
            scan_id=scan.id,
            sys_id="customized-1",
            table_name="sys_script",
            name="Business Rule A",
            sys_class_name="sys_script",
            origin_type=OriginType.modified_ootb,
            sys_updated_on=datetime.utcnow(),
        )
    )
    db_session.add(
        ScanResult(
            scan_id=scan.id,
            sys_id="ootb-1",
            table_name="sys_script_include",
            name="Script Include OOTB",
            sys_class_name="sys_script_include",
            origin_type=OriginType.ootb_untouched,
            sys_updated_on=datetime.utcnow(),
        )
    )
    db_session.commit()
    return assessment.id, scan.id


def test_assessment_customizations_endpoint_auto_heals_missing_rows(client, db_session):
    assessment_id, scan_id = _seed_assessment_with_stale_customizations(db_session)

    pre_count = len(
        db_session.exec(
            select(Customization.id).where(Customization.scan_id == scan_id)
        ).all()
    )
    assert pre_count == 0

    response = client.get(f"/api/assessments/{assessment_id}/customizations")
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 1
    assert len(payload["customizations"]) == 1
    assert payload["customizations"][0]["name"] == "Business Rule A"

    post_count = len(
        db_session.exec(
            select(Customization.id).where(Customization.scan_id == scan_id)
        ).all()
    )
    assert post_count == 1


def test_customization_options_endpoint_auto_heals_missing_rows(client, db_session):
    assessment_id, scan_id = _seed_assessment_with_stale_customizations(db_session)

    response = client.get(f"/api/customizations/options?assessment_id={assessment_id}")
    assert response.status_code == 200
    payload = response.json()

    assert payload["classes"] == [{"sys_class_name": "sys_script", "count": 1}]

    post_count = len(
        db_session.exec(
            select(Customization.id).where(Customization.scan_id == scan_id)
        ).all()
    )
    assert post_count == 1


def test_assessment_customizations_endpoint_removes_stale_non_customized_rows(client, db_session):
    assessment_id, scan_id = _seed_assessment_with_stale_customizations(db_session)

    result = db_session.exec(
        select(ScanResult).where(ScanResult.scan_id == scan_id).where(ScanResult.sys_id == "customized-1")
    ).first()
    assert result is not None

    sync_single_result(db_session, result)
    pre_count = len(
        db_session.exec(
            select(Customization.id).where(Customization.scan_id == scan_id)
        ).all()
    )
    assert pre_count == 1

    result.origin_type = OriginType.ootb_untouched
    db_session.add(result)
    db_session.commit()

    response = client.get(f"/api/assessments/{assessment_id}/customizations")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["customizations"] == []

    post_count = len(
        db_session.exec(
            select(Customization.id).where(Customization.scan_id == scan_id)
        ).all()
    )
    assert post_count == 0
