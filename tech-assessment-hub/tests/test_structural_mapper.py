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
    db_session.add_all([sr_policy, sr_action])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_ui_policy_action (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    ui_policy TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_ui_policy_action (_instance_id, sys_id, name, ui_policy)
                VALUES (:inst_id, :sys_id, :name, :ui_policy)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "act_bbb222",
                "name": "Set Priority Mandatory",
                "ui_policy": "pol_aaa111",
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
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    ui_policy TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_ui_policy_action (_instance_id, sys_id, name, ui_policy)
                VALUES (:inst_id, :sys_id, :name, :ui_policy)
                """
            ),
            {
                "inst_id": inst.id,
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


def test_structural_mapper_finds_dictionary_entry_parent_table(db_session, db_engine):
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
    db_session.add_all([sr_table, sr_dict])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_entry (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_entry (_instance_id, sys_id, name, element)
                VALUES (:inst_id, :sys_id, :name, :element)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "dict_ddd444",
                "name": "incident",
                "element": "u_custom_field",
            },
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["errors"] == []

    rels = db_session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == asmt.id,
            StructuralRelationship.relationship_type == "dictionary_entry",
        )
    ).all()

    assert len(rels) == 1
    assert rels[0].parent_scan_result_id == sr_table.id
    assert rels[0].child_scan_result_id == sr_dict.id


def test_structural_mapper_finds_dictionary_override_parent_entry(db_session, db_engine):
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

    sr_dict = ScanResult(
        scan_id=scan.id,
        sys_id="dict_ddd444",
        table_name="sys_dictionary",
        name="incident.u_custom_field",
        meta_target_table="incident",
    )
    sr_override = ScanResult(
        scan_id=scan.id,
        sys_id="ovr_eee555",
        table_name="sys_dictionary_override",
        name="u_custom_field",
    )
    db_session.add_all([sr_dict, sr_override])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_entry (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_override (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_entry (_instance_id, sys_id, name, element)
                VALUES (:inst_id, :sys_id, :name, :element)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "dict_ddd444",
                "name": "incident",
                "element": "u_custom_field",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_override (_instance_id, sys_id, name, element)
                VALUES (:inst_id, :sys_id, :name, :element)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "ovr_eee555",
                "name": "incident",
                "element": "u_custom_field",
            },
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["errors"] == []

    rels = db_session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == asmt.id,
            StructuralRelationship.relationship_type == "dictionary_override",
        )
    ).all()

    assert len(rels) == 1
    assert rels[0].parent_scan_result_id == sr_dict.id
    assert rels[0].child_scan_result_id == sr_override.id


def test_structural_mapper_finds_inherited_dictionary_override_parent_entry(db_session, db_engine):
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
        number="ASMT0002",
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

    sr_task_dict = ScanResult(
        scan_id=scan.id,
        sys_id="dict_task_assigned_to",
        table_name="sys_dictionary",
        name="task.assigned_to",
        meta_target_table="task",
    )
    sr_incident_override = ScanResult(
        scan_id=scan.id,
        sys_id="ovr_incident_assigned_to",
        table_name="sys_dictionary_override",
        name="assigned_to",
        meta_target_table="incident",
    )
    db_session.add_all([sr_task_dict, sr_incident_override])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_entry (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_override (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_table (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    super_class TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_entry (_instance_id, sys_id, name, element)
                VALUES (:inst_id, :sys_id, :name, :element)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "dict_task_assigned_to",
                "name": "task",
                "element": "assigned_to",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_override (_instance_id, sys_id, name, element)
                VALUES (:inst_id, :sys_id, :name, :element)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "ovr_incident_assigned_to",
                "name": "incident",
                "element": "assigned_to",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_table (_instance_id, sys_id, name, super_class)
                VALUES (:inst_id, :sys_id, :name, :super_class)
                """
            ),
            [
                {
                    "inst_id": inst.id,
                    "sys_id": "tbl_incident",
                    "name": "incident",
                    "super_class": "tbl_task",
                },
                {
                    "inst_id": inst.id,
                    "sys_id": "tbl_task",
                    "name": "task",
                    "super_class": "",
                },
            ],
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["errors"] == []

    rels = db_session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == asmt.id,
            StructuralRelationship.relationship_type == "dictionary_override",
        )
    ).all()

    assert len(rels) == 1
    assert rels[0].parent_scan_result_id == sr_task_dict.id
    assert rels[0].child_scan_result_id == sr_incident_override.id


def test_structural_mapper_finds_ui_policy_action_field_parent_dictionary(db_session, db_engine):
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
        number="ASMT0003",
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

    sr_dict = ScanResult(
        scan_id=scan.id,
        sys_id="dict_field_1",
        table_name="sys_dictionary",
        name="incident.priority",
        meta_target_table="incident",
    )
    sr_action = ScanResult(
        scan_id=scan.id,
        sys_id="action_field_1",
        table_name="sys_ui_policy_action",
        name="Set Priority Mandatory",
    )
    db_session.add_all([sr_dict, sr_action])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_entry (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_ui_policy_action (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    ui_policy TEXT,
                    "table" TEXT,
                    "field" TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_entry (_instance_id, sys_id, name, element)
                VALUES (:inst_id, :sys_id, :name, :element)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "dict_field_1",
                "name": "incident",
                "element": "priority",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_ui_policy_action (_instance_id, sys_id, name, ui_policy, "table", "field")
                VALUES (:inst_id, :sys_id, :name, :ui_policy, :table_name, :field_name)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "action_field_1",
                "name": "Set Priority Mandatory",
                "ui_policy": None,
                "table_name": "incident",
                "field_name": "priority",
            },
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["errors"] == []

    rels = db_session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.assessment_id == asmt.id,
            StructuralRelationship.relationship_type == "ui_policy_field",
        )
    ).all()

    assert len(rels) == 1
    assert rels[0].parent_scan_result_id == sr_dict.id
    assert rels[0].child_scan_result_id == sr_action.id
