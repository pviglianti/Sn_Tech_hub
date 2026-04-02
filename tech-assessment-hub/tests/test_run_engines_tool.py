"""Tests for the run_preprocessing_engines MCP tool."""

from types import SimpleNamespace

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
                VALUES (:inst_id, 'aaa111', 'BR Test', 'var gr = new GlideRecord(''incident'');')
                """
            ),
            {"inst_id": inst.id},
        )
        conn.commit()

    result = handle({"assessment_id": asmt.id}, db_session)

    assert result["success"] is True
    assert "engines_run" in result
    assert len(result["engines_run"]) >= 1


def test_run_engines_tool_fails_on_engine_reported_errors(db_session, monkeypatch):
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

    monkeypatch.setattr(
        "src.mcp.tools.pipeline.run_engines.importlib.import_module",
        lambda _path: SimpleNamespace(run=lambda *_args, **_kwargs: {
            "success": True,
            "relationships_created": 0,
            "errors": ["bad mapping"],
        }),
    )

    result = handle({"assessment_id": asmt.id, "engines": ["structural_mapper"]}, db_session)

    assert result["success"] is False
    assert result["errors"] == ["structural_mapper: bad mapping"]


def test_run_engines_tool_surfaces_zero_output_warning(db_session, monkeypatch):
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

    db_session.add(
        ScanResult(
            scan_id=scan.id,
            sys_id="act_bbb222",
            table_name="sys_ui_policy_action",
            name="Set Priority Mandatory",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        "src.mcp.tools.pipeline.run_engines.importlib.import_module",
        lambda _path: SimpleNamespace(run=lambda *_args, **_kwargs: {
            "success": True,
            "relationships_created": 0,
            "mappings_processed": 1,
            "errors": [],
        }),
    )

    result = handle({"assessment_id": asmt.id, "engines": ["structural_mapper"]}, db_session)

    assert result["success"] is True
    assert result["warnings"]
    assert "created 0 relationships" in result["warnings"][0]


def test_run_engines_tool_spec_exists():
    from src.mcp.tools.pipeline.run_engines import TOOL_SPEC

    assert TOOL_SPEC.name == "run_preprocessing_engines"
    assert TOOL_SPEC.permission == "write"
