"""Tests for the Update Set Analyzer engine."""

import json
from datetime import datetime, timedelta

from sqlmodel import select

from src.models import (
    AppConfig,
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    CustomerUpdateXML,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
    UpdateSet,
    UpdateSetArtifactLink,
    UpdateSetOverlap,
    VersionHistory,
)


def _setup_base(db_session):
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Test",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="test scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    return inst, asmt, scan


def _set_property(db_session, key: str, value: str):
    row = db_session.exec(select(AppConfig).where(AppConfig.instance_id.is_(None), AppConfig.key == key)).first()
    if row is None:
        row = AppConfig(instance_id=None, key=key, value=value, description="test override")
    else:
        row.value = value
    db_session.add(row)
    db_session.commit()


def test_content_overlap_detected_and_links_written(db_session):
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us_a = UpdateSet(instance_id=inst.id, sn_sys_id="us_a", name="US Alpha", completed_on=datetime(2025, 1, 1, 12, 0, 0))
    us_b = UpdateSet(instance_id=inst.id, sn_sys_id="us_b", name="US Beta", completed_on=datetime(2025, 1, 1, 12, 30, 0))
    db_session.add_all([us_a, us_b])
    db_session.flush()

    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="sr1_sysid",
        table_name="sys_script",
        name="BR Shared",
        sys_update_name="sys_script_shared",
        origin_type="modified_ootb",
        update_set_id=us_a.id,
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="sr2_sysid",
        table_name="sys_script_include",
        name="SI Unique",
        sys_update_name="sys_script_unique",
        origin_type="net_new_customer",
        update_set_id=us_a.id,
    )
    db_session.add_all([sr1, sr2])
    db_session.flush()

    db_session.add_all(
        [
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux1",
                name="sys_script_shared",
                update_set_id=us_a.id,
                target_sys_id="sr1_sysid",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux2",
                name="sys_script_shared",
                update_set_id=us_b.id,
                target_sys_id="sr1_sysid",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux3",
                name="sys_script_unique",
                update_set_id=us_a.id,
                target_sys_id="sr2_sysid",
            ),
        ]
    )
    db_session.commit()

    result = run(asmt.id, db_session, mode="base")
    assert result["success"] is True
    assert result["artifact_links_created"] >= 4
    assert result["content_overlaps"] >= 1

    links = list(
        db_session.exec(
            select(UpdateSetArtifactLink).where(UpdateSetArtifactLink.assessment_id == asmt.id)
        ).all()
    )
    sources = {l.link_source for l in links}
    assert "scan_result_current" in sources
    assert "customer_update_xml" in sources

    overlaps = list(
        db_session.exec(
            select(UpdateSetOverlap).where(
                UpdateSetOverlap.assessment_id == asmt.id,
                UpdateSetOverlap.signal_type == "content",
            )
        ).all()
    )
    assert len(overlaps) >= 1
    evidence = json.loads(overlaps[0].evidence_json)
    assert "shared_scan_result_ids" in evidence
    assert evidence["signal_type"] == "content"


def test_default_update_set_downgraded_not_excluded(db_session):
    from src.engines.update_set_analyzer import run

    _set_property(db_session, "reasoning.us.include_default_sets", "true")
    _set_property(db_session, "reasoning.us.default_signal_weight", "0.3")

    inst, asmt, scan = _setup_base(db_session)

    us_default = UpdateSet(instance_id=inst.id, sn_sys_id="us_def", name="Default", is_default=True)
    us_norm = UpdateSet(instance_id=inst.id, sn_sys_id="us_norm", name="Feature US")
    db_session.add_all([us_default, us_norm])
    db_session.flush()

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="sr_default",
        table_name="sys_script",
        name="BR Default Linked",
        sys_update_name="sys_script_default_linked",
        origin_type="net_new_customer",
    )
    db_session.add(sr)
    db_session.flush()

    db_session.add_all(
        [
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_def",
                name="sys_script_default_linked",
                update_set_id=us_default.id,
                target_sys_id="sr_default",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_norm",
                name="sys_script_default_linked",
                update_set_id=us_norm.id,
                target_sys_id="sr_default",
            ),
        ]
    )
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    overlaps = list(
        db_session.exec(
            select(UpdateSetOverlap).where(
                UpdateSetOverlap.assessment_id == asmt.id,
                UpdateSetOverlap.signal_type == "content",
            )
        ).all()
    )
    assert overlaps
    row = overlaps[0]
    pair = {row.update_set_a_id, row.update_set_b_id}
    assert pair == {us_default.id, us_norm.id}

    evidence = json.loads(row.evidence_json)
    assert evidence["includes_default"] is True
    assert row.overlap_score < 1.0


def test_default_update_set_excluded_when_property_false(db_session):
    from src.engines.update_set_analyzer import run

    _set_property(db_session, "reasoning.us.include_default_sets", "false")

    inst, asmt, scan = _setup_base(db_session)

    us_default = UpdateSet(instance_id=inst.id, sn_sys_id="us_def", name="Default", is_default=True)
    us_norm = UpdateSet(instance_id=inst.id, sn_sys_id="us_norm", name="Feature US")
    db_session.add_all([us_default, us_norm])
    db_session.flush()

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="sr_default",
        table_name="sys_script",
        name="BR Default Linked",
        sys_update_name="sys_script_default_linked",
        origin_type="modified_ootb",
    )
    db_session.add(sr)
    db_session.flush()

    db_session.add_all(
        [
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_def",
                name="sys_script_default_linked",
                update_set_id=us_default.id,
                target_sys_id="sr_default",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_norm",
                name="sys_script_default_linked",
                update_set_id=us_norm.id,
                target_sys_id="sr_default",
            ),
        ]
    )
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True

    overlaps = list(
        db_session.exec(select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == asmt.id)).all()
    )
    for row in overlaps:
        assert {row.update_set_a_id, row.update_set_b_id} != {us_default.id, us_norm.id}


def test_version_history_links_and_overlap_detected(db_session):
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us_current = UpdateSet(instance_id=inst.id, sn_sys_id="us_cur", name="Current US")
    us_hist = UpdateSet(instance_id=inst.id, sn_sys_id="us_hist", name="Historical US")
    db_session.add_all([us_current, us_hist])
    db_session.flush()

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="sr_hist",
        table_name="sys_script",
        name="BR Historical",
        sys_update_name="sys_script_hist",
        origin_type="modified_ootb",
        update_set_id=us_current.id,
    )
    db_session.add(sr)
    db_session.flush()

    db_session.add(
        VersionHistory(
            instance_id=inst.id,
            sn_sys_id="vh1",
            sys_update_name="sys_script_hist",
            name="sys_script_hist",
            state="previous",
            source_table="sys_update_set",
            source_sys_id="us_hist",
        )
    )
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["vh_overlaps"] >= 1

    vh_links = list(
        db_session.exec(
            select(UpdateSetArtifactLink).where(
                UpdateSetArtifactLink.assessment_id == asmt.id,
                UpdateSetArtifactLink.link_source == "version_history",
            )
        ).all()
    )
    assert vh_links


def test_name_similarity_signal_detected(db_session):
    from src.engines.update_set_analyzer import run

    _set_property(db_session, "reasoning.us.name_similarity_min_tokens", "1")

    inst, asmt, scan = _setup_base(db_session)

    db_session.add(
        ScanResult(
            scan_id=scan.id,
            sys_id="sr1",
            table_name="sys_script",
            name="BR One",
            sys_update_name="sys_script_one",
            origin_type="modified_ootb",
        )
    )

    us1 = UpdateSet(instance_id=inst.id, sn_sys_id="us1", name="STRY0012345 Login Form")
    us2 = UpdateSet(instance_id=inst.id, sn_sys_id="us2", name="STRY0012345 Login Validation")
    us3 = UpdateSet(instance_id=inst.id, sn_sys_id="us3", name="INC0099999 Unrelated")
    db_session.add_all([us1, us2, us3])
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["name_overlaps"] >= 1

    overlaps = list(
        db_session.exec(
            select(UpdateSetOverlap).where(
                UpdateSetOverlap.assessment_id == asmt.id,
                UpdateSetOverlap.signal_type == "name_similarity",
            )
        ).all()
    )
    pairs = {frozenset([row.update_set_a_id, row.update_set_b_id]) for row in overlaps}
    assert frozenset([us1.id, us2.id]) in pairs


def test_temporal_and_author_sequence_signals(db_session):
    from src.engines.update_set_analyzer import run

    _set_property(db_session, "reasoning.temporal.gap_threshold_minutes", "120")

    inst, asmt, scan = _setup_base(db_session)

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="sr_seq",
        table_name="sys_script",
        name="BR Sequence",
        sys_update_name="sys_script_sequence",
        origin_type="net_new_customer",
    )
    db_session.add(sr)
    db_session.flush()

    t0 = datetime(2025, 1, 2, 8, 0, 0)
    us1 = UpdateSet(
        instance_id=inst.id,
        sn_sys_id="us_seq1",
        name="Payment Step 1",
        completed_on=t0,
        completed_by="dev.alpha",
    )
    us2 = UpdateSet(
        instance_id=inst.id,
        sn_sys_id="us_seq2",
        name="Payment Step 2",
        completed_on=t0 + timedelta(minutes=30),
        completed_by="dev.alpha",
    )
    db_session.add_all([us1, us2])
    db_session.flush()

    db_session.add_all(
        [
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_s1",
                name="sys_script_sequence",
                update_set_id=us1.id,
                target_sys_id="sr_seq",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_s2",
                name="sys_script_sequence",
                update_set_id=us2.id,
                target_sys_id="sr_seq",
            ),
        ]
    )
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["temporal_sequence_overlaps"] >= 1
    assert result["author_sequence_overlaps"] >= 1


def test_enriched_mode_includes_coherence_payload(db_session):
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us1 = UpdateSet(instance_id=inst.id, sn_sys_id="us_en_1", name="Approval Feature A")
    us2 = UpdateSet(instance_id=inst.id, sn_sys_id="us_en_2", name="Approval Feature B")
    db_session.add_all([us1, us2])
    db_session.flush()

    sr1 = ScanResult(
        scan_id=scan.id,
        sys_id="sr_en_1",
        table_name="sys_script",
        name="Approval Validator",
        sys_update_name="sys_script_en_1",
        origin_type="modified_ootb",
        ai_summary="Validates approval state and calls helper",
        ai_observations="Checks manager approval and emits custom event",
    )
    sr2 = ScanResult(
        scan_id=scan.id,
        sys_id="sr_en_2",
        table_name="sys_script_include",
        name="ApprovalHelper",
        sys_update_name="sys_script_en_2",
        origin_type="net_new_customer",
        ai_summary="Shared helper for approval checks",
        ai_observations="Invoked by validation business rules",
    )
    db_session.add_all([sr1, sr2])
    db_session.flush()

    db_session.add(
        CodeReference(
            instance_id=inst.id,
            assessment_id=asmt.id,
            source_scan_result_id=sr1.id,
            source_table="sys_script",
            source_field="script",
            source_name=sr1.name,
            reference_type="script_include",
            target_identifier="ApprovalHelper",
            target_scan_result_id=sr2.id,
            confidence=1.0,
        )
    )
    db_session.add(
        StructuralRelationship(
            instance_id=inst.id,
            assessment_id=asmt.id,
            parent_scan_result_id=sr1.id,
            child_scan_result_id=sr2.id,
            relationship_type="logical_dependency",
            parent_field="script",
            confidence=1.0,
        )
    )

    db_session.add_all(
        [
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_en_1",
                name="sys_script_en_1",
                update_set_id=us1.id,
                target_sys_id="sr_en_1",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_en_2",
                name="sys_script_en_1",
                update_set_id=us2.id,
                target_sys_id="sr_en_1",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_en_3",
                name="sys_script_en_2",
                update_set_id=us1.id,
                target_sys_id="sr_en_2",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux_en_4",
                name="sys_script_en_2",
                update_set_id=us2.id,
                target_sys_id="sr_en_2",
            ),
        ]
    )
    db_session.commit()

    result = run(asmt.id, db_session, mode="enriched")
    assert result["success"] is True
    assert result["mode"] == "enriched"

    overlap = db_session.exec(
        select(UpdateSetOverlap).where(
            UpdateSetOverlap.assessment_id == asmt.id,
            UpdateSetOverlap.signal_type == "content",
        )
    ).first()
    assert overlap is not None
    evidence = json.loads(overlap.evidence_json)
    assert "coherence" in evidence
    assert evidence["coherence"]["avg"] is not None


def test_idempotent_rerun(db_session):
    from src.engines.update_set_analyzer import run

    inst, asmt, scan = _setup_base(db_session)

    us1 = UpdateSet(instance_id=inst.id, sn_sys_id="us1", name="US One")
    us2 = UpdateSet(instance_id=inst.id, sn_sys_id="us2", name="US Two")
    db_session.add_all([us1, us2])
    db_session.flush()

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="sr1",
        table_name="sys_script",
        name="BR Test",
        sys_update_name="sys_script_test",
        origin_type="net_new_customer",
    )
    db_session.add(sr)
    db_session.flush()

    db_session.add_all(
        [
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux1",
                name="sys_script_test",
                update_set_id=us1.id,
                target_sys_id="sr1",
            ),
            CustomerUpdateXML(
                instance_id=inst.id,
                sn_sys_id="cux2",
                name="sys_script_test",
                update_set_id=us2.id,
                target_sys_id="sr1",
            ),
        ]
    )
    db_session.commit()

    run(asmt.id, db_session)
    count1 = len(list(db_session.exec(select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == asmt.id)).all()))
    links1 = len(
        list(
            db_session.exec(
                select(UpdateSetArtifactLink).where(UpdateSetArtifactLink.assessment_id == asmt.id)
            ).all()
        )
    )

    run(asmt.id, db_session)
    count2 = len(list(db_session.exec(select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == asmt.id)).all()))
    links2 = len(
        list(
            db_session.exec(
                select(UpdateSetArtifactLink).where(UpdateSetArtifactLink.assessment_id == asmt.id)
            ).all()
        )
    )

    assert count1 == count2
    assert links1 == links2


def test_no_scan_results_returns_success(db_session):
    from src.engines.update_set_analyzer import run

    inst, asmt, _ = _setup_base(db_session)
    db_session.commit()

    result = run(asmt.id, db_session)
    assert result["success"] is True
    assert result["content_overlaps"] == 0
    assert result["name_overlaps"] == 0
    assert result["vh_overlaps"] == 0
    assert result["artifact_links_created"] == 0
