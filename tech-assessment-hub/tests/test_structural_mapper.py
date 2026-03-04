"""Tests for the Structural Mapper engine."""

from sqlmodel import select
from sqlalchemy import text

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    StructuralRelationship,
)


def test_structural_mapper_finds_ui_policy_action(db_session, db_engine):
    from src.engines.structural_mapper import run

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

    sr_policy = ScanResult(
        scan_id=scan.id,
        sys_id="pol_aaa111",
        table_name="sys_ui_policy",
        name="Make Priority Mandatory",
    )
    sr_action = ScanResult(
        scan_id=scan.id,
        sys_id="act_bbb222",
        table_name="sys_ui_policy_action",
        name="Set Priority Mandatory",
    )
    sr_table = ScanResult(
        scan_id=scan.id,
        sys_id="tbl_ccc333",
        table_name="sys_db_object",
        name="incident",
        meta_target_table="incident",
    )
    sr_dict = ScanResult(
        scan_id=scan.id,
        sys_id="dict_ddd444",
        table_name="sys_dictionary",
        name="incident.u_custom_field",
        meta_target_table="incident",
    )
    db_session.add_all([sr_policy, sr_action, sr_table, sr_dict])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_ui_policy_action (
                    id INTEGER PRIMARY KEY,
                    scan_result_id INTEGER,
                    sn_sys_id TEXT,
                    name TEXT,
                    ui_policy TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_ui_policy_action (scan_result_id, sn_sys_id, name, ui_policy)
                VALUES (:sr_id, :sys_id, :name, :ui_policy)
                """
            ),
            {
                "sr_id": sr_action.id,
                "sys_id": "act_bbb222",
                "name": "Set Priority Mandatory",
                "ui_policy": "pol_aaa111",
            },
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary (
                    id INTEGER PRIMARY KEY,
                    scan_result_id INTEGER,
                    sn_sys_id TEXT,
                    name TEXT,
                    element TEXT,
                    collection_name TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary (scan_result_id, sn_sys_id, name, element, collection_name)
                VALUES (:sr_id, :sys_id, :name, :element, :collection)
                """
            ),
            {
                "sr_id": sr_dict.id,
                "sys_id": "dict_ddd444",
                "name": "incident.u_custom_field",
                "element": "u_custom_field",
                "collection": "incident",
            },
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True

    rels = db_session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == asmt.id,
            StructuralRelationship.relationship_type == "ui_policy_action",
        )
    ).all()

    assert len(rels) >= 1
    rel = rels[0]
    assert rel.parent_scan_result_id == sr_policy.id
    assert rel.child_scan_result_id == sr_action.id


def test_structural_mapper_returns_summary(db_session, db_engine):
    from src.engines.structural_mapper import run

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

    sr_policy = ScanResult(
        scan_id=scan.id,
        sys_id="pol_aaa111",
        table_name="sys_ui_policy",
        name="Make Priority Mandatory",
    )
    sr_action = ScanResult(
        scan_id=scan.id,
        sys_id="act_bbb222",
        table_name="sys_ui_policy_action",
        name="Set Priority Mandatory",
    )
    db_session.add_all([sr_policy, sr_action])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_ui_policy_action (
                    id INTEGER PRIMARY KEY,
                    scan_result_id INTEGER,
                    sn_sys_id TEXT,
                    name TEXT,
                    ui_policy TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_ui_policy_action (scan_result_id, sn_sys_id, name, ui_policy)
                VALUES (:sr_id, :sys_id, :name, :ui_policy)
                """
            ),
            {
                "sr_id": sr_action.id,
                "sys_id": "act_bbb222",
                "name": "Set Priority Mandatory",
                "ui_policy": "pol_aaa111",
            },
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert "relationships_created" in result
    assert result["relationships_created"] >= 1
