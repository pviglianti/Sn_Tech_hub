"""Tests for the artifact_analyzer MCP prompt."""

import json

import pytest
from sqlmodel import Session

from src.models import (
    Assessment, AssessmentState, AssessmentType, Instance,
    OriginType, Scan, ScanResult, ScanStatus, ScanType,
    StructuralRelationship, UpdateSet, UpdateSetArtifactLink,
)


def _seed_result(session: Session):
    inst = Instance(name="test", url="https://test.service-now.com",
                    username="admin", password_encrypted="x")
    session.add(inst)
    session.flush()
    asmt = Assessment(instance_id=inst.id, name="Test", number="ASMT0001",
                      assessment_type=AssessmentType.global_app,
                      state=AssessmentState.in_progress)
    session.add(asmt)
    session.flush()
    scan = Scan(assessment_id=asmt.id, scan_type=ScanType.metadata,
                name="Test Scan", status=ScanStatus.completed)
    session.add(scan)
    session.flush()
    sr = ScanResult(
        scan_id=scan.id, sys_id="abc123", name="Test BR",
        table_name="sys_script",
        origin_type=OriginType.net_new_customer,
        raw_data_json=json.dumps({
            "script": "(function executeRule(current, previous) {\n  current.update();\n})(current, previous);"
        }),
        observations="Baseline observation text.",
    )
    session.add(sr)
    session.commit()
    session.refresh(sr)
    return inst, asmt, sr


def test_artifact_analyzer_prompt_returns_messages(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    _inst, asmt, sr = _seed_result(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    assert "messages" in result
    assert len(result["messages"]) >= 1
    text = result["messages"][0]["content"]["text"]
    assert "Test BR" in text  # Artifact name injected
    assert "sys_script" in text  # Table name injected


def test_artifact_analyzer_includes_code_body(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    _inst, asmt, sr = _seed_result(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "current.update()" in text  # Code body injected from raw_data_json


def test_artifact_analyzer_includes_observations(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    _inst, asmt, sr = _seed_result(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Baseline observation" in text


def test_artifact_analyzer_missing_result_raises(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    handler = PROMPT_SPECS[0].handler
    with pytest.raises(ValueError, match="ScanResult not found"):
        handler({"result_id": "99999", "assessment_id": "1"}, session=db_session)


def test_artifact_analyzer_includes_structural_relationships(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    inst, asmt, sr = _seed_result(db_session)
    # Create a child artifact
    scan = db_session.get(Scan, sr.scan_id)
    child_sr = ScanResult(
        scan_id=scan.id, sys_id="child123", name="Child Action",
        table_name="sys_ui_action",
        origin_type=OriginType.net_new_customer,
    )
    db_session.add(child_sr)
    db_session.flush()
    # Create structural relationship
    rel = StructuralRelationship(
        instance_id=inst.id, assessment_id=asmt.id,
        parent_scan_result_id=sr.id, child_scan_result_id=child_sr.id,
        relationship_type="parent_child", parent_field="collection",
    )
    db_session.add(rel)
    db_session.commit()
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Child Action" in text


def test_artifact_analyzer_includes_update_set_links(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    inst, asmt, sr = _seed_result(db_session)
    us = UpdateSet(instance_id=inst.id, sn_sys_id="us-001", name="Feature Update Set")
    db_session.add(us)
    db_session.flush()
    link = UpdateSetArtifactLink(
        instance_id=inst.id, assessment_id=asmt.id,
        scan_result_id=sr.id, update_set_id=us.id,
        link_source="scan_result_current",
    )
    db_session.add(link)
    db_session.commit()
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Feature Update Set" in text


def test_artifact_analyzer_no_session_returns_static(db_session: Session):
    """When session is None, handler returns static prompt without context."""
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": "1", "assessment_id": "1"},
        session=None,
    )
    assert "messages" in result
    text = result["messages"][0]["content"]["text"]
    assert "ServiceNow artifact" in text
