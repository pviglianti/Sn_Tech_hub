"""Tests for the Table Co-location engine."""

import json

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    TableColocationSummary,
)


def _setup_base(session):
    """Create the minimal Instance -> Assessment -> Scan hierarchy."""
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Test",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="test scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    return inst, asmt, scan


def test_table_colocation_basic(db_session):
    """3 records targeting 'sc_req_item' produces 1 summary with record_count=3."""
    from src.engines.table_colocation import run

    inst, asmt, scan = _setup_base(db_session)

    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="Before Insert on RITM",
        meta_target_table="sc_req_item",
        sys_updated_by="alice",
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_ui_policy",
        name="Make Priority Mandatory",
        meta_target_table="sc_req_item",
        sys_updated_by="bob",
    )
    sr3 = ScanResult(
        scan_id=scan.id,
        sys_id="ccc333",
        table_name="sys_dictionary",
        name="sc_req_item.u_custom",
        meta_target_table="sc_req_item",
        sys_updated_by="alice",
    )
    db_session.add_all([sr1, sr2, sr3])
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["summaries_created"] == 1
    assert result["errors"] == []

    summaries = db_session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == asmt.id
        )
    ).all()
    assert len(summaries) == 1

    summary = summaries[0]
    assert summary.target_table == "sc_req_item"
    assert summary.record_count == 3
    assert summary.instance_id == inst.id

    record_ids = json.loads(summary.record_ids_json)
    assert set(record_ids) == {sr1.id, sr2.id, sr3.id}

    artifact_types = json.loads(summary.artifact_types_json)
    assert set(artifact_types) == {"sys_script", "sys_ui_policy", "sys_dictionary"}

    developers = json.loads(summary.developers_json)
    assert set(developers) == {"alice", "bob"}


def test_table_colocation_multiple_tables(db_session):
    """Records targeting 2 different tables produce 2 summaries."""
    from src.engines.table_colocation import run

    _inst, asmt, scan = _setup_base(db_session)

    # Two records for incident
    db_session.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                sys_id="inc_a",
                table_name="sys_script",
                name="BR on Incident",
                meta_target_table="incident",
                sys_updated_by="alice",
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="inc_b",
                table_name="sys_ui_policy",
                name="Policy on Incident",
                meta_target_table="incident",
                sys_updated_by="bob",
            ),
        ]
    )
    # Two records for change_request
    db_session.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                sys_id="chg_a",
                table_name="sys_script",
                name="BR on Change",
                meta_target_table="change_request",
                sys_updated_by="carol",
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="chg_b",
                table_name="sys_dictionary",
                name="change_request.u_field",
                meta_target_table="change_request",
                sys_updated_by="carol",
            ),
        ]
    )
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["summaries_created"] == 2

    summaries = db_session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == asmt.id
        )
    ).all()
    tables = {s.target_table for s in summaries}
    assert tables == {"incident", "change_request"}


def test_table_colocation_single_record_skipped(db_session):
    """A table with only 1 record does not produce a summary."""
    from src.engines.table_colocation import run

    _inst, asmt, scan = _setup_base(db_session)

    db_session.add(
        ScanResult(
            scan_id=scan.id,
            sys_id="lone_a",
            table_name="sys_script",
            name="Lone BR",
            meta_target_table="problem",
            sys_updated_by="dave",
        )
    )
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["summaries_created"] == 0

    summaries = db_session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == asmt.id
        )
    ).all()
    assert len(summaries) == 0


def test_table_colocation_no_target_table(db_session):
    """Records with null/empty meta_target_table produce 0 summaries."""
    from src.engines.table_colocation import run

    _inst, asmt, scan = _setup_base(db_session)

    db_session.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                sys_id="null_a",
                table_name="sys_script_include",
                name="UtilsA",
                meta_target_table=None,
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="null_b",
                table_name="sys_script_include",
                name="UtilsB",
                meta_target_table="",
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="null_c",
                table_name="sys_script_include",
                name="UtilsC",
                meta_target_table="   ",
            ),
        ]
    )
    db_session.flush()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["summaries_created"] == 0


def test_table_colocation_idempotent(db_session):
    """Running the engine twice yields the same summary count."""
    from src.engines.table_colocation import run

    _inst, asmt, scan = _setup_base(db_session)

    db_session.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                sys_id="idem_a",
                table_name="sys_script",
                name="BR A",
                meta_target_table="incident",
                sys_updated_by="eve",
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="idem_b",
                table_name="sys_ui_policy",
                name="Policy B",
                meta_target_table="incident",
                sys_updated_by="frank",
            ),
        ]
    )
    db_session.flush()

    result1 = run(asmt.id, db_session)
    assert result1["success"] is True
    assert result1["summaries_created"] == 1

    result2 = run(asmt.id, db_session)
    assert result2["success"] is True
    assert result2["summaries_created"] == 1

    # Verify only 1 summary row exists (old one was deleted)
    summaries = db_session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == asmt.id
        )
    ).all()
    assert len(summaries) == 1


def test_table_colocation_assessment_not_found(db_session):
    """Non-existent assessment returns success=False."""
    from src.engines.table_colocation import run

    result = run(999999, db_session)

    assert result["success"] is False
    assert "Assessment not found" in result["errors"][0]


def test_table_colocation_no_scan_results(db_session):
    """Assessment with no scan results returns success with 0 summaries."""
    from src.engines.table_colocation import run

    _inst, asmt, _scan = _setup_base(db_session)

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["summaries_created"] == 0


def test_table_colocation_developers_filters_none(db_session):
    """Records with None sys_updated_by are excluded from developers list."""
    from src.engines.table_colocation import run

    _inst, asmt, scan = _setup_base(db_session)

    db_session.add_all(
        [
            ScanResult(
                scan_id=scan.id,
                sys_id="dev_a",
                table_name="sys_script",
                name="BR A",
                meta_target_table="incident",
                sys_updated_by=None,
            ),
            ScanResult(
                scan_id=scan.id,
                sys_id="dev_b",
                table_name="sys_ui_policy",
                name="Policy B",
                meta_target_table="incident",
                sys_updated_by="alice",
            ),
        ]
    )
    db_session.flush()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["summaries_created"] == 1

    summary = db_session.exec(
        select(TableColocationSummary).where(
            TableColocationSummary.assessment_id == asmt.id
        )
    ).first()
    developers = json.loads(summary.developers_json)
    assert developers == ["alice"]
