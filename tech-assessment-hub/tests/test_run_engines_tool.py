"""Tests for the run_preprocessing_engines MCP tool."""

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
)


def test_run_engines_tool_executes(db_session, db_engine):
    from src.mcp.tools.pipeline.run_engines import handle

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

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="aaa111",
        table_name="sys_script",
        name="BR Test",
    )
    db_session.add(sr)
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
                VALUES (:sr_id, 'aaa111', 'BR Test', 'var gr = new GlideRecord(''incident'');')
                """
            ),
            {"sr_id": sr.id},
        )
        conn.commit()

    result = handle({"assessment_id": asmt.id}, db_session)

    assert result["success"] is True
    assert "engines_run" in result
    assert len(result["engines_run"]) >= 1


def test_run_engines_tool_spec_exists():
    from src.mcp.tools.pipeline.run_engines import TOOL_SPEC

    assert TOOL_SPEC.name == "run_preprocessing_engines"
    assert TOOL_SPEC.permission == "write"
