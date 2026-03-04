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
                    id INTEGER PRIMARY KEY,
                    scan_result_id INTEGER,
                    sn_sys_id TEXT,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (scan_result_id, sn_sys_id, name, script)
                VALUES (:sr_id, :sys_id, :name, :script)
                """
            ),
            {
                "sr_id": sr_br.id,
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
                    id INTEGER PRIMARY KEY,
                    scan_result_id INTEGER,
                    sn_sys_id TEXT,
                    name TEXT,
                    script TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO asmt_business_rule (scan_result_id, sn_sys_id, name, script)
                VALUES (:sr_id, :sys_id, :name, :script)
                """
            ),
            {
                "sr_id": sr_br.id,
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
