"""Tests for /results/{id}/update route: customized-only guard + human assignment_source."""

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


def _seed_route_data(db_session):
    """Create Instance -> Assessment -> Scan -> 2 ScanResults + Feature."""
    inst = Instance(
        name="route-guard",
        url="https://route-guard.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Route Guard Assessment",
        number="ASMT_RG_001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="route scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    cust = ScanResult(
        scan_id=scan.id,
        sys_id="rg_cust",
        table_name="sys_script_include",
        name="CustomHelper",
        origin_type=OriginType.modified_ootb,
    )
    ootb = ScanResult(
        scan_id=scan.id,
        sys_id="rg_ootb",
        table_name="sys_script_include",
        name="OotbHelper",
        origin_type=OriginType.ootb_untouched,
    )
    db_session.add_all([cust, ootb])
    db_session.flush()

    feature = Feature(assessment_id=asmt.id, name="Existing Feature")
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(cust)
    db_session.refresh(ootb)
    db_session.refresh(feature)

    return cust, ootb, feature


def test_route_rejects_non_customized_feature_assignment(client, db_session):
    """POST /results/{id}/update with feature_id for OOTB result -> 400."""
    _, ootb, feature = _seed_route_data(db_session)

    resp = client.post(
        f"/results/{ootb.id}/update",
        data={"feature_id": str(feature.id)},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "customized" in resp.text.lower()


def test_route_rejects_new_feature_for_non_customized(client, db_session):
    """POST /results/{id}/update with new_feature_name for OOTB result -> 400 (no orphan Feature)."""
    _, ootb, _ = _seed_route_data(db_session)

    resp = client.post(
        f"/results/{ootb.id}/update",
        data={"new_feature_name": "Should Not Exist"},
        follow_redirects=False,
    )
    assert resp.status_code == 400

    # No orphan Feature should have been created
    orphan = db_session.exec(
        select(Feature).where(Feature.name == "Should Not Exist")
    ).first()
    assert orphan is None


def test_route_stamps_human_assignment_source(client, db_session):
    """POST /results/{id}/update with feature_id stamps assignment_source='human'."""
    cust, _, feature = _seed_route_data(db_session)

    resp = client.post(
        f"/results/{cust.id}/update",
        data={"feature_id": str(feature.id)},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 303)

    link = db_session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature.id,
            FeatureScanResult.scan_result_id == cust.id,
        )
    ).first()
    assert link is not None
    assert link.assignment_source == "human"
