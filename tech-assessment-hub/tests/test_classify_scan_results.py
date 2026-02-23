"""Tests for classify_scan_results() — the standalone post-VH classification stage."""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from src.models import (
    Assessment,
    HeadOwner,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    VersionHistory,
    MetadataCustomization,
    CustomerUpdateXML,
)
from src.services.scan_executor import classify_scan_results


@pytest.fixture()
def db_session(tmp_path):
    """Create a throwaway SQLite database with the full schema."""
    from sqlmodel import SQLModel, create_engine

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed_instance_and_assessment(session: Session) -> tuple:
    """Create an Instance + Assessment and return (instance, assessment)."""
    instance = Instance(
        name="test-instance",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="fake",
    )
    session.add(instance)
    session.commit()
    session.refresh(instance)

    assessment = Assessment(
        number="ASMT0000099",
        name="Test Assessment",
        instance_id=instance.id,
    )
    session.add(assessment)
    session.commit()
    session.refresh(assessment)
    return instance, assessment


def _seed_scan_with_pending_result(
    session: Session, assessment, *, sys_id="abc123", sys_update_name="sys_script_include_abc123"
) -> tuple:
    """Create a Scan with one pending_classification ScanResult."""
    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Test Scan",
        status=ScanStatus.completed,
        records_found=1,
        records_customized=0,
        records_ootb_modified=0,
        records_customer_customized=0,
    )
    session.add(scan)
    session.commit()
    session.refresh(scan)

    result = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id,
        table_name="sys_script_include",
        name="TestScript",
        sys_update_name=sys_update_name,
        origin_type=OriginType.pending_classification,
        head_owner=HeadOwner.unknown,
    )
    session.add(result)
    session.commit()
    session.refresh(result)
    return scan, result


# ── Basic tests ──


def test_no_pending_results_returns_zero(db_session):
    """When no results have pending_classification, returns zeros."""
    instance, assessment = _seed_instance_and_assessment(db_session)
    summary = classify_scan_results(db_session, assessment.id)
    assert summary == {"classified": 0, "scans_updated": 0}


def test_classifies_pending_result_to_unknown_no_history(db_session):
    """With no VH/metadata/customer_update data, result becomes unknown_no_history."""
    instance, assessment = _seed_instance_and_assessment(db_session)
    scan, result = _seed_scan_with_pending_result(db_session, assessment)

    summary = classify_scan_results(db_session, assessment.id)

    assert summary["classified"] == 1
    assert summary["scans_updated"] == 1

    db_session.refresh(result)
    assert result.origin_type == OriginType.unknown_no_history
    assert result.head_owner == HeadOwner.unknown


def test_classifies_with_metadata_customization(db_session):
    """With a metadata_customization record, result becomes modified_ootb."""
    instance, assessment = _seed_instance_and_assessment(db_session)
    scan, result = _seed_scan_with_pending_result(db_session, assessment)

    # Seed metadata customization record (author_type must be non-NULL and
    # not "Custom" to be recognized as an OOB-modified indicator)
    mc = MetadataCustomization(
        sn_sys_id="mc001",
        instance_id=instance.id,
        sys_metadata_sys_id="abc123",
        sys_update_name="sys_script_include_abc123",
        author_type="ServiceNow",
    )
    session = db_session
    session.add(mc)
    session.commit()

    summary = classify_scan_results(session, assessment.id)

    assert summary["classified"] == 1
    session.refresh(result)
    assert result.origin_type == OriginType.modified_ootb


def test_classifies_with_version_history_ootb(db_session):
    """With an OOB version history record, result classified as ootb_untouched."""
    instance, assessment = _seed_instance_and_assessment(db_session)
    scan, result = _seed_scan_with_pending_result(db_session, assessment)

    # Seed VH record with OOB source (sys_store -> store/upgrade)
    vh = VersionHistory(
        sn_sys_id="vh001",
        instance_id=instance.id,
        sys_update_name="sys_script_include_abc123",
        name="sys_script_include_abc123",
        state="current",
        sys_recorded_at=datetime(2026, 1, 1),
        source_table="sys_store_app",
        source_sys_id="store001",
        source_display="Store App",
        type="sys_script_include",
    )
    db_session.add(vh)
    db_session.commit()

    summary = classify_scan_results(db_session, assessment.id)

    assert summary["classified"] == 1
    db_session.refresh(result)
    assert result.origin_type == OriginType.ootb_untouched
    assert result.head_owner == HeadOwner.store_upgrade


def test_scan_counts_recomputed_after_classification(db_session):
    """Scan records_customized and breakdown counts are recomputed."""
    instance, assessment = _seed_instance_and_assessment(db_session)

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata_index,
        name="Count Test Scan",
        status=ScanStatus.completed,
        records_found=2,
        records_customized=0,
        records_ootb_modified=0,
        records_customer_customized=0,
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    # Two pending results — one will become modified_ootb, one unknown_no_history
    r1 = ScanResult(
        scan_id=scan.id,
        sys_id="r1",
        table_name="sys_script_include",
        name="Script1",
        sys_update_name="sys_script_include_r1",
        origin_type=OriginType.pending_classification,
        head_owner=HeadOwner.unknown,
    )
    r2 = ScanResult(
        scan_id=scan.id,
        sys_id="r2",
        table_name="sys_script_include",
        name="Script2",
        sys_update_name="sys_script_include_r2",
        origin_type=OriginType.pending_classification,
        head_owner=HeadOwner.unknown,
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    # Seed metadata customization for r1 only
    mc = MetadataCustomization(
        sn_sys_id="mc_r1",
        instance_id=instance.id,
        sys_metadata_sys_id="r1",
        sys_update_name="sys_script_include_r1",
        author_type="ServiceNow",
    )
    db_session.add(mc)
    db_session.commit()

    classify_scan_results(db_session, assessment.id)

    db_session.refresh(scan)
    assert scan.records_ootb_modified == 1
    assert scan.records_customer_customized == 0
    assert scan.records_customized == 1  # only 1 modified_ootb


def test_already_classified_results_not_reclassified(db_session):
    """Results that are NOT pending_classification are left untouched."""
    instance, assessment = _seed_instance_and_assessment(db_session)
    scan, _ = _seed_scan_with_pending_result(db_session, assessment)

    # Add a second result that's already classified
    already_classified = ScanResult(
        scan_id=scan.id,
        sys_id="already_done",
        table_name="sys_script_include",
        name="AlreadyDone",
        origin_type=OriginType.net_new_customer,
        head_owner=HeadOwner.customer,
    )
    db_session.add(already_classified)
    db_session.commit()
    db_session.refresh(already_classified)

    classify_scan_results(db_session, assessment.id)

    db_session.refresh(already_classified)
    # Should remain net_new_customer — not reclassified
    assert already_classified.origin_type == OriginType.net_new_customer
    assert already_classified.head_owner == HeadOwner.customer


def test_version_fields_populated_after_classification(db_session):
    """Version tracking fields on ScanResult are filled during classification."""
    instance, assessment = _seed_instance_and_assessment(db_session)
    scan, result = _seed_scan_with_pending_result(db_session, assessment)

    vh = VersionHistory(
        sn_sys_id="vh_fields",
        instance_id=instance.id,
        sys_update_name="sys_script_include_abc123",
        name="sys_script_include_abc123",
        state="current",
        sys_recorded_at=datetime(2026, 1, 15, 10, 30, 0),
        source_table="sys_store_app",
        source_sys_id="store_xyz",
        source_display="My Store App",
        type="sys_script_include",
    )
    db_session.add(vh)
    db_session.commit()

    classify_scan_results(db_session, assessment.id)

    db_session.refresh(result)
    assert result.current_version_source_table == "sys_store_app"
    assert result.current_version_source == "My Store App"
    assert result.current_version_sys_id == "vh_fields"
    assert result.current_version_recorded_at == datetime(2026, 1, 15, 10, 30, 0)
