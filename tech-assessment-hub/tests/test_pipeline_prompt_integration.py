"""Tests for pipeline prompt integration (Phase 9 — Prompt Injection).

Verifies:
1. PipelinePromptProperties frozen dataclass and loader
2. PIPELINE_USE_REGISTERED_PROMPTS property appears in admin snapshot
3. ai_analysis handler calls artifact_analyzer prompt when enabled
4. ai_analysis handler uses legacy JSON path when disabled (default)
5. report handler calls report_writer prompt when enabled
6. report handler uses legacy JSON path when disabled (default)
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.models import (
    AppConfig,
    Assessment,
    AssessmentState,
    AssessmentType,
    GeneralRecommendation,
    Instance,
    OriginType,
    PipelineStage,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.services.integration_properties import (
    PIPELINE_USE_REGISTERED_PROMPTS,
    PipelinePromptProperties,
    list_integration_property_snapshots,
    load_pipeline_prompt_properties,
    update_integration_properties,
)


# ---------------------------------------------------------------------------
# Property loader tests
# ---------------------------------------------------------------------------


def test_load_pipeline_prompt_properties_defaults(db_session):
    """Default should be use_registered_prompts=False."""
    props = load_pipeline_prompt_properties(db_session)
    assert isinstance(props, PipelinePromptProperties)
    assert props.use_registered_prompts is False


def test_load_pipeline_prompt_properties_enabled(db_session, sample_instance):
    """Setting property to 'true' should enable prompt integration."""
    update_integration_properties(
        db_session,
        {PIPELINE_USE_REGISTERED_PROMPTS: "true"},
        instance_id=sample_instance.id,
    )
    props = load_pipeline_prompt_properties(db_session, instance_id=sample_instance.id)
    assert props.use_registered_prompts is True


def test_pipeline_prompt_property_in_snapshot(db_session):
    """Property should appear in the admin property snapshot."""
    rows = list_integration_property_snapshots(db_session)
    by_key = {row["key"]: row for row in rows}
    assert PIPELINE_USE_REGISTERED_PROMPTS in by_key
    defn = by_key[PIPELINE_USE_REGISTERED_PROMPTS]
    assert defn["value_type"] == "select"
    # current_value is None when no app_config override exists; default is "false"
    assert defn["current_value"] is None or defn["current_value"] == "false"
    assert defn["default"] == "false"


# ---------------------------------------------------------------------------
# Seed helpers (reused by ai_analysis and report tests)
# ---------------------------------------------------------------------------


def _seed_assessment(db_session, *, pipeline_stage="ai_analysis"):
    """Create an Instance + Assessment + Scan with customized ScanResults."""
    inst = Instance(
        name="prompt-test-inst",
        url="https://prompt-test.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Prompt Integration Test",
        number="ASMT0099901",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=pipeline_stage,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="test-scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    customized = []
    for i in range(2):
        sr = ScanResult(
            scan_id=scan.id,
            sys_id=f"sys_prompt_custom_{i}",
            table_name="sys_script_include",
            name=f"PromptScript{i}",
            origin_type=OriginType.modified_ootb,
        )
        db_session.add(sr)
        customized.append(sr)

    db_session.commit()
    for sr in customized:
        db_session.refresh(sr)
    db_session.refresh(asmt)
    return asmt, customized


def _make_mock_context():
    """Return a fake gather_artifact_context response."""
    return {
        "artifact": {"id": 1, "name": "TestArtifact", "table_name": "sys_script_include"},
        "update_sets": [{"id": 10, "name": "US1"}],
        "human_context": {
            "observations": None,
            "disposition": None,
            "features": [],
        },
        "references": [],
        "has_local_table_data": False,
    }


# ---------------------------------------------------------------------------
# ai_analysis handler tests — prompt integration
# ---------------------------------------------------------------------------


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
@patch("src.server.load_pipeline_prompt_properties")
@patch("src.server.PROMPT_REGISTRY")
def test_ai_analysis_uses_prompt_when_enabled(
    mock_registry,
    mock_load_prompt_props,
    mock_gather,
    mock_set_stage,
    mock_set_job,
    db_session,
    db_engine,
):
    """When use_registered_prompts=True, ai_analysis enriches JSON with prompt text."""
    asmt, customized = _seed_assessment(db_session, pipeline_stage="ai_analysis")

    mock_load_prompt_props.return_value = PipelinePromptProperties(use_registered_prompts=True)
    mock_registry.has_prompt.return_value = True
    mock_registry.get_prompt.return_value = {
        "description": "Analyze artifact",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "Rich prompt context for artifact"}}
        ],
    }
    mock_gather.return_value = _make_mock_context()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    for sr in customized:
        db_session.refresh(sr)
        assert sr.ai_observations is not None
        parsed = json.loads(sr.ai_observations)
        # Should have both the base JSON fields and the prompt enrichment
        assert "artifact_name" in parsed
        assert parsed.get("registered_prompt") == "artifact_analyzer"
        assert "Rich prompt context" in parsed.get("prompt_context", "")

    # gather_artifact_context IS called (always), plus prompt registry
    assert mock_gather.call_count == 2
    assert mock_registry.get_prompt.call_count == 2


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
@patch("src.server.load_pipeline_prompt_properties")
@patch("src.server.PROMPT_REGISTRY")
def test_ai_analysis_uses_legacy_json_when_disabled(
    mock_registry,
    mock_load_prompt_props,
    mock_gather,
    mock_set_stage,
    mock_set_job,
    db_session,
    db_engine,
):
    """When use_registered_prompts=False (default), ai_analysis uses legacy JSON path."""
    asmt, customized = _seed_assessment(db_session, pipeline_stage="ai_analysis")

    mock_load_prompt_props.return_value = PipelinePromptProperties(use_registered_prompts=False)
    mock_gather.return_value = _make_mock_context()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    for sr in customized:
        db_session.refresh(sr)
        assert sr.ai_observations is not None
        parsed = json.loads(sr.ai_observations)
        assert "artifact_name" in parsed
        assert "context_enrichment_mode" in parsed

    # Legacy path uses gather_artifact_context
    assert mock_gather.call_count == 2
    # Prompt registry should NOT be called
    mock_registry.get_prompt.assert_not_called()


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
@patch("src.server.load_pipeline_prompt_properties")
@patch("src.server.PROMPT_REGISTRY")
def test_ai_analysis_falls_back_when_prompt_not_registered(
    mock_registry,
    mock_load_prompt_props,
    mock_gather,
    mock_set_stage,
    mock_set_job,
    db_session,
    db_engine,
):
    """If use_registered_prompts=True but prompt not in registry, fall back to legacy."""
    asmt, customized = _seed_assessment(db_session, pipeline_stage="ai_analysis")

    mock_load_prompt_props.return_value = PipelinePromptProperties(use_registered_prompts=True)
    mock_registry.has_prompt.return_value = False  # Prompt not registered
    mock_gather.return_value = _make_mock_context()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    for sr in customized:
        db_session.refresh(sr)
        parsed = json.loads(sr.ai_observations)
        assert "artifact_name" in parsed
        # Should have error about prompt not registered
        assert "registered_prompt_error" in parsed

    assert mock_gather.call_count == 2
    mock_registry.get_prompt.assert_not_called()


# ---------------------------------------------------------------------------
# report handler tests — prompt integration
# ---------------------------------------------------------------------------


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.load_pipeline_prompt_properties")
@patch("src.server.PROMPT_REGISTRY")
def test_report_uses_prompt_when_enabled(
    mock_registry,
    mock_load_prompt_props,
    mock_set_stage,
    mock_set_job,
    db_session,
    db_engine,
):
    """When use_registered_prompts=True, report stage calls report_writer prompt."""
    asmt, _ = _seed_assessment(db_session, pipeline_stage="report")

    mock_load_prompt_props.return_value = PipelinePromptProperties(use_registered_prompts=True)
    mock_registry.has_prompt.return_value = True
    mock_registry.get_prompt.return_value = {
        "description": "Generate report",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": "# Full Assessment Report\n\nRich report content here."}}
        ],
    }

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="report")

    # Check the stored GeneralRecommendation has rich content
    from sqlmodel import select
    report = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "assessment_report")
    ).first()

    assert report is not None
    assert "Full Assessment Report" in report.description
    assert "Rich report content" in report.description
    mock_registry.get_prompt.assert_called_once()


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.load_pipeline_prompt_properties")
@patch("src.server.PROMPT_REGISTRY")
def test_report_uses_legacy_json_when_disabled(
    mock_registry,
    mock_load_prompt_props,
    mock_set_stage,
    mock_set_job,
    db_session,
    db_engine,
):
    """When use_registered_prompts=False (default), report stores JSON data."""
    asmt, _ = _seed_assessment(db_session, pipeline_stage="report")

    mock_load_prompt_props.return_value = PipelinePromptProperties(use_registered_prompts=False)

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="report")

    from sqlmodel import select
    report = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "assessment_report")
    ).first()

    assert report is not None
    # Legacy path stores JSON
    parsed = json.loads(report.description)
    assert "assessment_name" in parsed
    assert "statistics" in parsed
    assert "features" in parsed

    mock_registry.get_prompt.assert_not_called()
