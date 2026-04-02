"""Tests for the Code Reference Parser engine."""

from sqlmodel import select
from sqlalchemy import text

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    CodeReference,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


def test_parse_script_include_instantiation():
    from src.engines.code_reference_parser import extract_references

    script = """
    var helper = new ApprovalHelper();
    helper.checkApproval(current);
    """
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "ApprovalHelper"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "script_include"


def test_parse_glide_record_query():
    from src.engines.code_reference_parser import extract_references

    script = """
    var gr = new GlideRecord('incident');
    gr.addQuery('active', true);
    gr.query();
    """
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "incident"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "table_query"


def test_parse_gs_include():
    from src.engines.code_reference_parser import extract_references

    script = "gs.include('ApprovalUtils');"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "ApprovalUtils"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "script_include"


def test_parse_event_queue():
    from src.engines.code_reference_parser import extract_references

    script = "gs.eventQueue('custom.approval.needed', current, gs.getUserID(), '');"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "custom.approval.needed"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "event"


def test_parse_glide_ajax():
    from src.engines.code_reference_parser import extract_references

    script = "var ga = new GlideAjax('MyAjaxUtil');"
    refs = extract_references(script, "sys_script_client", "script")

    match = [r for r in refs if r["target_identifier"] == "MyAjaxUtil"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "script_include"


def test_parse_rest_message():
    from src.engines.code_reference_parser import extract_references

    script = "var rm = new sn_ws.RESTMessageV2('Outbound API', 'post');"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "Outbound API"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "rest_message"


def test_parse_workflow_start():
    from src.engines.code_reference_parser import extract_references

    script = "workflow.start('approval_flow', current);"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "approval_flow"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "workflow"


def test_parse_sp_get_widget():
    from src.engines.code_reference_parser import extract_references

    script = "var widget = $sp.getWidget('my-custom-widget');"
    refs = extract_references(script, "sp_widget", "script")

    match = [r for r in refs if r["target_identifier"] == "my-custom-widget"]
    assert len(match) == 1
    assert match[0]["reference_type"] == "sp_widget"


def test_parse_sys_id_reference():
    from src.engines.code_reference_parser import extract_references

    script = """
    var sysId = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6';
    gr.get(sysId);
    """
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["reference_type"] == "sys_id_reference"]
    assert len(match) == 1
    assert match[0]["target_identifier"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def test_parse_client_g_form():
    from src.engines.code_reference_parser import extract_references

    script = """
    g_form.setValue('state', '6');
    g_form.setMandatory('u_custom_field', true);
    """
    refs = extract_references(script, "sys_script_client", "script")

    field_refs = [r for r in refs if r["reference_type"] == "field_reference"]
    field_names = {r["target_identifier"] for r in field_refs}
    assert "state" in field_names
    assert "u_custom_field" in field_names


def test_parse_multiple_references_in_one_script():
    from src.engines.code_reference_parser import extract_references

    script = """
    var helper = new ApprovalHelper();
    var gr = new GlideRecord('sc_req_item');
    gr.addQuery('sys_id', current.sys_id);
    gr.query();
    if (gr.next()) {
        gs.eventQueue('custom.ritm.approved', gr, gs.getUserID(), '');
    }
    """
    refs = extract_references(script, "sys_script", "script")

    types = {r["reference_type"] for r in refs}
    assert "script_include" in types
    assert "table_query" in types
    assert "event" in types
    assert len(refs) >= 3


def test_extract_references_returns_line_numbers():
    from src.engines.code_reference_parser import extract_references

    script = "line1\nvar gr = new GlideRecord('incident');\nline3"
    refs = extract_references(script, "sys_script", "script")

    match = [r for r in refs if r["target_identifier"] == "incident"]
    assert len(match) == 1
    assert match[0]["line_number"] == 2


def test_engine_run_populates_code_references(db_session, db_engine):
    from src.engines.code_reference_parser import run

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

    sr_br = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR - Approval Check",
    )
    sr_si = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_script_include",
        name="ApprovalHelper",
    )
    db_session.add_all([sr_br, sr_si])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_business_rule (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (_instance_id, sys_id, name, script)
                VALUES (:inst_id, :sys_id, :name, :script)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "aaa111",
                "name": "BR - Approval Check",
                "script": "var helper = new ApprovalHelper();\nvar gr = new GlideRecord('sc_req_item');\ngr.query();",
            },
        )
        conn.commit()

    result = run(asmt.id, db_session)

    assert result["success"] is True
    assert result["references_created"] >= 2

    refs = db_session.exec(select(CodeReference).where(CodeReference.assessment_id == asmt.id)).all()
    assert len(refs) >= 2
    ref_types = {r.reference_type for r in refs}
    assert "script_include" in ref_types
    assert "table_query" in ref_types


def test_engine_run_resolves_target_scan_result(db_session, db_engine):
    from src.engines.code_reference_parser import run

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

    sr_br = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR - Approval Check",
    )
    sr_si = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222",
        table_name="sys_script_include",
        name="ApprovalHelper",
    )
    db_session.add_all([sr_br, sr_si])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_business_rule (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (_instance_id, sys_id, name, script)
                VALUES (:inst_id, :sys_id, :name, :script)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "aaa111",
                "name": "BR - Approval Check",
                "script": "var helper = new ApprovalHelper();",
            },
        )
        conn.commit()

    run(asmt.id, db_session)

    refs = db_session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == asmt.id,
            CodeReference.reference_type == "script_include",
            CodeReference.target_identifier == "ApprovalHelper",
        )
    ).all()

    assert len(refs) == 1
    assert refs[0].target_scan_result_id == sr_si.id


def test_engine_run_resolves_all_matching_script_include_results(db_session, db_engine):
    from src.engines.code_reference_parser import run

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
        number="ASMT0001A",
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

    sr_br = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111-multi",
        table_name="sys_script",
        name="BR - Shared Helper Check",
        sys_scope="global",
    )
    sr_si_a = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222-multi-a",
        table_name="sys_script_include",
        name="SharedHelper",
        sys_scope="global",
    )
    sr_si_b = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222-multi-b",
        table_name="sys_script_include",
        name="SharedHelper",
        sys_scope="x_app_scope",
    )
    db_session.add_all([sr_br, sr_si_a, sr_si_b])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_business_rule (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (_instance_id, sys_id, name, script)
                VALUES (:inst_id, :sys_id, :name, :script)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "aaa111-multi",
                "name": "BR - Shared Helper Check",
                "script": "var helper = new SharedHelper();",
            },
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_script_include (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    api_name TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_script_include (_instance_id, sys_id, name, api_name)
                VALUES (:inst_id, :sys_id, :name, :api_name)
                """
            ),
            [
                {
                    "inst_id": inst.id,
                    "sys_id": "bbb222-multi-a",
                    "name": "SharedHelper",
                    "api_name": "SharedHelper",
                },
                {
                    "inst_id": inst.id,
                    "sys_id": "bbb222-multi-b",
                    "name": "SharedHelper",
                    "api_name": "x_app.SharedHelper",
                },
            ],
        )
        conn.commit()

    run(asmt.id, db_session)

    refs = db_session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == asmt.id,
            CodeReference.reference_type == "script_include",
            CodeReference.target_identifier == "SharedHelper",
        )
    ).all()

    assert {ref.target_scan_result_id for ref in refs} == {sr_si_a.id}


def test_engine_run_resolves_script_include_by_exact_api_name(db_session, db_engine):
    from src.engines.code_reference_parser import run

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
        number="ASMT0001B",
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

    sr_br = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111-api",
        table_name="sys_script",
        name="BR - Explicit Scoped Helper",
        sys_scope="global",
    )
    sr_si_global = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222-api-a",
        table_name="sys_script_include",
        name="SharedHelper",
        sys_scope="global",
    )
    sr_si_scoped = ScanResult(
        scan_id=scan.id,
        sys_id="bbb222-api-b",
        table_name="sys_script_include",
        name="SharedHelper",
        sys_scope="x_app_scope",
    )
    db_session.add_all([sr_br, sr_si_global, sr_si_scoped])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_business_rule (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_script_include (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    api_name TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (_instance_id, sys_id, name, script)
                VALUES (:inst_id, :sys_id, :name, :script)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "aaa111-api",
                "name": "BR - Explicit Scoped Helper",
                "script": "gs.include('x_app.SharedHelper');",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_script_include (_instance_id, sys_id, name, api_name)
                VALUES (:inst_id, :sys_id, :name, :api_name)
                """
            ),
            [
                {
                    "inst_id": inst.id,
                    "sys_id": "bbb222-api-a",
                    "name": "SharedHelper",
                    "api_name": "SharedHelper",
                },
                {
                    "inst_id": inst.id,
                    "sys_id": "bbb222-api-b",
                    "name": "SharedHelper",
                    "api_name": "x_app.SharedHelper",
                },
            ],
        )
        conn.commit()

    run(asmt.id, db_session)

    refs = db_session.exec(
        select(CodeReference).where(
            CodeReference.assessment_id == asmt.id,
            CodeReference.reference_type == "script_include",
            CodeReference.target_identifier == "x_app.SharedHelper",
        )
    ).all()

    assert {ref.target_scan_result_id for ref in refs} == {sr_si_scoped.id}


def test_engine_run_resolves_field_and_reference_qual_dependencies(db_session, db_engine):
    from src.engines.code_reference_parser import run

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

    sr_table = ScanResult(
        scan_id=scan.id,
        sys_id="tbl111",
        table_name="sys_db_object",
        name="incident",
    )
    sr_field = ScanResult(
        scan_id=scan.id,
        sys_id="dict111",
        table_name="sys_dictionary",
        name="incident.u_custom_field",
        raw_data_json='{"name":"incident","element":"u_custom_field"}',
    )
    sr_ref_qual = ScanResult(
        scan_id=scan.id,
        sys_id="dict222",
        table_name="sys_dictionary",
        name="incident.u_requester",
        raw_data_json='{"name":"incident","element":"u_requester"}',
    )
    sr_si = ScanResult(
        scan_id=scan.id,
        sys_id="si111",
        table_name="sys_script_include",
        name="AssignmentHelper",
    )
    sr_br = ScanResult(
        scan_id=scan.id,
        sys_id="br111",
        table_name="sys_script",
        name="BR - Dependency Check",
        meta_target_table="incident",
    )
    db_session.add_all([sr_table, sr_field, sr_ref_qual, sr_si, sr_br])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_business_rule (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_entry (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT,
                    reference_qual TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (_instance_id, sys_id, name, script)
                VALUES (:inst_id, :sys_id, :name, :script)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "br111",
                "name": "BR - Dependency Check",
                "script": (
                    "var helper = new AssignmentHelper();\n"
                    "current.u_custom_field = 'x';\n"
                    "var gr = new GlideRecord('incident');\n"
                    "gr.query();"
                ),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_entry (_instance_id, sys_id, name, element, reference_qual)
                VALUES (:inst_id, :sys_id, :name, :element, :reference_qual)
                """
            ),
            [
                {
                    "inst_id": inst.id,
                    "sys_id": "dict111",
                    "name": "incident",
                    "element": "u_custom_field",
                    "reference_qual": None,
                },
                {
                    "inst_id": inst.id,
                    "sys_id": "dict222",
                    "name": "incident",
                    "element": "u_requester",
                    "reference_qual": "javascript:new AssignmentHelper().filter(current.u_custom_field);",
                },
            ],
        )
        conn.commit()

    run(asmt.id, db_session)

    refs = db_session.exec(
        select(CodeReference).where(CodeReference.assessment_id == asmt.id)
    ).all()

    assert any(
        ref.reference_type == "field_reference"
        and ref.source_scan_result_id == sr_br.id
        and ref.target_scan_result_id == sr_field.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "table_query"
        and ref.source_scan_result_id == sr_br.id
        and ref.target_scan_result_id == sr_table.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "script_include"
        and ref.source_scan_result_id == sr_ref_qual.id
        and ref.target_scan_result_id == sr_si.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "field_reference"
        and ref.source_scan_result_id == sr_ref_qual.id
        and ref.target_scan_result_id == sr_field.id
        for ref in refs
    )


def test_engine_run_resolves_field_dependencies_from_detail_tables(db_session, db_engine):
    from src.engines.code_reference_parser import run

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

    sr_field = ScanResult(
        scan_id=scan.id,
        sys_id="dict-entry-1",
        table_name="sys_dictionary",
        name="Custom field label",
        raw_data_json='{"sys_name":"Custom field label"}',
    )
    sr_override_target = ScanResult(
        scan_id=scan.id,
        sys_id="dict-override-1",
        table_name="sys_dictionary_override",
        name="assigned_to",
        raw_data_json='{"sys_name":"assigned_to"}',
    )
    sr_override_source = ScanResult(
        scan_id=scan.id,
        sys_id="dict-override-2",
        table_name="sys_dictionary_override",
        name="assignment_group",
        raw_data_json='{"sys_name":"assignment_group"}',
    )
    sr_override_source_base = ScanResult(
        scan_id=scan.id,
        sys_id="dict-entry-2",
        table_name="sys_dictionary",
        name="Assignment group",
        raw_data_json='{"sys_name":"Assignment group"}',
    )
    sr_si = ScanResult(
        scan_id=scan.id,
        sys_id="si-dependency-1",
        table_name="sys_script_include",
        name="AssignmentHelper",
    )
    sr_br = ScanResult(
        scan_id=scan.id,
        sys_id="br-dependency-1",
        table_name="sys_script",
        name="BR - Incident Dependency Check",
        meta_target_table="incident",
    )
    db_session.add_all([sr_field, sr_override_target, sr_override_source, sr_override_source_base, sr_si, sr_br])
    db_session.flush()

    with db_engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_business_rule (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS asmt_dictionary_entry (
                    _row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    _instance_id INTEGER NOT NULL,
                    sys_id TEXT NOT NULL,
                    name TEXT,
                    element TEXT,
                    reference_qual TEXT
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
                    element TEXT,
                    reference_qual TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (_instance_id, sys_id, name, script)
                VALUES (:inst_id, :sys_id, :name, :script)
                """
            ),
            {
                "inst_id": inst.id,
                "sys_id": "br-dependency-1",
                "name": "BR - Incident Dependency Check",
                "script": "current.u_custom_field = 'x';\ncurrent.assignment_group = 'abc';",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_entry (_instance_id, sys_id, name, element, reference_qual)
                VALUES (:inst_id, :sys_id, :name, :element, :reference_qual)
                """
            ),
            [
                {
                    "inst_id": inst.id,
                    "sys_id": "dict-entry-1",
                    "name": "incident",
                    "element": "u_custom_field",
                    "reference_qual": None,
                },
                {
                    "inst_id": inst.id,
                    "sys_id": "dict-entry-2",
                    "name": "incident",
                    "element": "assignment_group",
                    "reference_qual": None,
                },
            ],
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_dictionary_override (_instance_id, sys_id, name, element, reference_qual)
                VALUES (:inst_id, :sys_id, :name, :element, :reference_qual)
                """
            ),
            [
                {
                    "inst_id": inst.id,
                    "sys_id": "dict-override-1",
                    "name": "incident",
                    "element": "assigned_to",
                    "reference_qual": "",
                },
                {
                    "inst_id": inst.id,
                    "sys_id": "dict-override-2",
                    "name": "incident",
                    "element": "assignment_group",
                    "reference_qual": "javascript:new AssignmentHelper().filter(current.assigned_to);",
                },
            ],
        )
        conn.commit()

    run(asmt.id, db_session)

    refs = db_session.exec(
        select(CodeReference).where(CodeReference.assessment_id == asmt.id)
    ).all()

    assert any(
        ref.reference_type == "field_reference"
        and ref.source_scan_result_id == sr_br.id
        and ref.target_scan_result_id == sr_field.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "field_reference"
        and ref.source_scan_result_id == sr_br.id
        and ref.target_scan_result_id == sr_override_source.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "field_reference"
        and ref.source_scan_result_id == sr_br.id
        and ref.target_scan_result_id == sr_override_source_base.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "script_include"
        and ref.source_scan_result_id == sr_override_source.id
        and ref.target_scan_result_id == sr_si.id
        for ref in refs
    )
    assert any(
        ref.reference_type == "field_reference"
        and ref.source_scan_result_id == sr_override_source.id
        and ref.target_scan_result_id == sr_override_target.id
        for ref in refs
    )


def test_resolve_targets_returns_all_exact_name_matches_for_untyped_reference():
    from src.engines.code_reference_parser import _resolve_targets

    event_ref = CodeReference(
        source_scan_result_id=1,
        reference_type="event",
        target_identifier="shared.identifier",
    )
    candidate_a = ScanResult(
        id=10,
        scan_id=1,
        sys_id="sr10",
        table_name="sys_script_include",
        name="shared.identifier",
    )
    candidate_b = ScanResult(
        id=11,
        scan_id=1,
        sys_id="sr11",
        table_name="sys_ui_policy",
        name="shared.identifier",
    )

    resolved = _resolve_targets(
        event_ref,
        source_sr=None,
        sr_by_sys_id={},
        sr_by_name={"shared.identifier": [candidate_a, candidate_b]},
        sr_by_table={},
        table_results_by_name={},
        field_targets_by_key={},
        source_table_hints_by_result_id={},
        script_include_targets_by_api_name={},
    )

    assert [candidate.id for candidate in resolved] == [candidate_a.id, candidate_b.id]
