"""Tests for the Customization child table sync logic."""

from sqlalchemy import inspect
from sqlmodel import select

from src.models import (
    Assessment,
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
from src.services.customization_sync import (
    bulk_sync_for_scan,
    is_customized,
    sync_single_result,
)


# ── Helpers ──

def _make_assessment(session, instance):
    a = Assessment(
        instance_id=instance.id,
        number="ASMT0099001",
        name="Test Assessment",
        assessment_type=AssessmentType.global_app,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def _make_scan(session, assessment):
    s = Scan(
        assessment_id=assessment.id,
        name="Test Scan",
        scan_type=ScanType.metadata_index,
        status=ScanStatus.completed,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _make_result(session, scan, name, origin_type, table_name="sys_script_include"):
    r = ScanResult(
        scan_id=scan.id,
        sys_id=f"sid_{name}",
        table_name=table_name,
        name=name,
        origin_type=origin_type,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


# ── is_customized tests ──

def test_is_customized_true_for_modified_ootb():
    assert is_customized(OriginType.modified_ootb) is True


def test_is_customized_true_for_net_new_customer():
    assert is_customized(OriginType.net_new_customer) is True


def test_is_customized_false_for_ootb_untouched():
    assert is_customized(OriginType.ootb_untouched) is False


def test_is_customized_false_for_none():
    assert is_customized(None) is False


# ── bulk_sync_for_scan tests ──

def test_bulk_sync_creates_rows_for_customized(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)

    r_modified = _make_result(db_session, scan, "modified_br", OriginType.modified_ootb)
    r_net_new = _make_result(db_session, scan, "net_new_si", OriginType.net_new_customer)
    r_ootb = _make_result(db_session, scan, "ootb_si", OriginType.ootb_untouched)

    count = bulk_sync_for_scan(db_session, scan.id)

    assert count == 2

    customizations = db_session.exec(
        select(Customization).where(Customization.scan_id == scan.id)
    ).all()
    assert len(customizations) == 2

    cust_result_ids = {c.scan_result_id for c in customizations}
    assert r_modified.id in cust_result_ids
    assert r_net_new.id in cust_result_ids
    assert r_ootb.id not in cust_result_ids


def test_bulk_sync_skips_existing(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)

    _make_result(db_session, scan, "cust_br", OriginType.modified_ootb)

    first_count = bulk_sync_for_scan(db_session, scan.id)
    assert first_count == 1

    second_count = bulk_sync_for_scan(db_session, scan.id)
    assert second_count == 0


def test_bulk_sync_updates_existing_rows(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)

    result = _make_result(db_session, scan, "bulk_upd", OriginType.modified_ootb)
    bulk_sync_for_scan(db_session, scan.id)

    result.review_status = ReviewStatus.reviewed
    result.disposition = Disposition.keep_and_refactor
    result.recommendation = "Refactor this customization"
    result.observations = "Observation text"
    result.name = "bulk_upd_renamed"
    db_session.add(result)
    db_session.commit()

    inserted = bulk_sync_for_scan(db_session, scan.id)
    assert inserted == 0

    row = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result.id)
    ).first()
    assert row is not None
    assert row.review_status == ReviewStatus.reviewed
    assert row.disposition == Disposition.keep_and_refactor
    assert row.recommendation == "Refactor this customization"
    assert row.observations == "Observation text"
    assert row.name == "bulk_upd_renamed"


def test_bulk_sync_deletes_stale_rows_for_non_customized(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)

    result = _make_result(db_session, scan, "bulk_del", OriginType.modified_ootb)
    first_inserted = bulk_sync_for_scan(db_session, scan.id)
    assert first_inserted == 1

    result.origin_type = OriginType.ootb_untouched
    db_session.add(result)
    db_session.commit()

    inserted = bulk_sync_for_scan(db_session, scan.id)
    assert inserted == 0

    row = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result.id)
    ).first()
    assert row is None


def test_bulk_sync_returns_count(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)

    _make_result(db_session, scan, "a", OriginType.modified_ootb)
    _make_result(db_session, scan, "b", OriginType.net_new_customer)
    _make_result(db_session, scan, "c", OriginType.ootb_untouched)

    count = bulk_sync_for_scan(db_session, scan.id)
    assert count == 2


# ── sync_single_result tests ──

def test_sync_single_creates_for_customized(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)
    result = _make_result(db_session, scan, "new_cust", OriginType.modified_ootb)

    sync_single_result(db_session, result)

    cust = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result.id)
    ).first()

    assert cust is not None
    assert cust.scan_id == scan.id
    assert cust.sys_id == result.sys_id
    assert cust.table_name == result.table_name
    assert cust.name == result.name
    assert cust.origin_type == OriginType.modified_ootb


def test_sync_single_deletes_when_reclassified(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)
    result = _make_result(db_session, scan, "reclass", OriginType.modified_ootb)

    # First sync creates the customization row
    sync_single_result(db_session, result)
    cust = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result.id)
    ).first()
    assert cust is not None

    # Reclassify to ootb_untouched
    result.origin_type = OriginType.ootb_untouched
    db_session.add(result)
    db_session.commit()

    sync_single_result(db_session, result)

    cust_after = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result.id)
    ).first()
    assert cust_after is None


def test_sync_single_updates_fields(db_session, sample_instance):
    assessment = _make_assessment(db_session, sample_instance)
    scan = _make_scan(db_session, assessment)
    result = _make_result(db_session, scan, "upd_disp", OriginType.net_new_customer)

    # Create initial customization row
    sync_single_result(db_session, result)

    # Update disposition on the result
    result.disposition = Disposition.keep_and_refactor
    db_session.add(result)
    db_session.commit()

    # Re-sync
    sync_single_result(db_session, result)

    cust = db_session.exec(
        select(Customization).where(Customization.scan_result_id == result.id)
    ).first()
    assert cust is not None
    assert cust.disposition == Disposition.keep_and_refactor


# ── Schema verification ──

def test_customization_table_exists(db_engine):
    inspector = inspect(db_engine)
    table_names = inspector.get_table_names()
    assert "customization" in table_names
