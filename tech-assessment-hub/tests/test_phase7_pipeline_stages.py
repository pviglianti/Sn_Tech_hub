"""Tests for Phase 7 PipelineStage enum extensions.

Verifies the three new pipeline stages (ai_analysis, ai_refinement, report)
exist with correct values and the full 10-member ordering is preserved.
Also tests pipeline stage configuration dicts and advance-pipeline endpoint.
"""

import pytest
from unittest.mock import patch

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    PipelineStage,
)


def test_pipeline_stage_has_exactly_10_members():
    """PipelineStage must have exactly 10 members after Phase 7 additions."""
    members = list(PipelineStage)
    assert len(members) == 10, (
        f"Expected 10 PipelineStage members, got {len(members)}: "
        f"{[m.value for m in members]}"
    )


def test_ai_analysis_exists_with_correct_value():
    assert PipelineStage.ai_analysis == "ai_analysis"
    assert PipelineStage.ai_analysis.value == "ai_analysis"


def test_ai_refinement_exists_with_correct_value():
    assert PipelineStage.ai_refinement == "ai_refinement"
    assert PipelineStage.ai_refinement.value == "ai_refinement"


def test_report_exists_with_correct_value():
    assert PipelineStage.report == "report"
    assert PipelineStage.report.value == "report"


def test_pipeline_stage_order_is_correct():
    """Enum member order must match the intended pipeline progression."""
    expected_order = [
        "scans",
        "ai_analysis",
        "engines",
        "observations",
        "review",
        "grouping",
        "ai_refinement",
        "recommendations",
        "report",
        "complete",
    ]
    actual_order = [member.value for member in PipelineStage]
    assert actual_order == expected_order, (
        f"PipelineStage order mismatch.\n"
        f"  Expected: {expected_order}\n"
        f"  Actual:   {actual_order}"
    )


# ---------------------------------------------------------------------------
# Task 2 tests: Pipeline stage configuration dicts
# ---------------------------------------------------------------------------

from src.server import (
    _PIPELINE_STAGE_ORDER,
    _PIPELINE_STAGE_LABELS,
    _PIPELINE_STAGE_AUTONEXT,
)


def test_pipeline_stage_order_has_10_entries():
    """_PIPELINE_STAGE_ORDER must contain exactly 10 entries."""
    assert len(_PIPELINE_STAGE_ORDER) == 10, (
        f"Expected 10 entries in _PIPELINE_STAGE_ORDER, got {len(_PIPELINE_STAGE_ORDER)}"
    )


def test_pipeline_stage_order_correct_sequence():
    """_PIPELINE_STAGE_ORDER must list stages in the correct 10-stage order."""
    expected = [
        "scans",
        "ai_analysis",
        "engines",
        "observations",
        "review",
        "grouping",
        "ai_refinement",
        "recommendations",
        "report",
        "complete",
    ]
    assert _PIPELINE_STAGE_ORDER == expected, (
        f"_PIPELINE_STAGE_ORDER mismatch.\n  Expected: {expected}\n  Actual: {_PIPELINE_STAGE_ORDER}"
    )


def test_pipeline_stage_labels_has_all_10():
    """_PIPELINE_STAGE_LABELS must have exactly 10 entries including the 3 new ones."""
    assert len(_PIPELINE_STAGE_LABELS) == 10, (
        f"Expected 10 labels, got {len(_PIPELINE_STAGE_LABELS)}"
    )
    assert _PIPELINE_STAGE_LABELS["ai_analysis"] == "AI Analysis"
    assert _PIPELINE_STAGE_LABELS["ai_refinement"] == "AI Refinement"
    assert _PIPELINE_STAGE_LABELS["report"] == "Report"


def test_pipeline_stage_autonext_includes_new_stages():
    """_PIPELINE_STAGE_AUTONEXT must include ai_analysis->engines, ai_refinement->recommendations, report->complete."""
    assert _PIPELINE_STAGE_AUTONEXT["ai_analysis"] == "engines"
    assert _PIPELINE_STAGE_AUTONEXT["ai_refinement"] == "recommendations"
    assert _PIPELINE_STAGE_AUTONEXT["report"] == "complete"


def test_pipeline_stage_autonext_grouping_goes_to_ai_refinement():
    """grouping must auto-advance to ai_refinement (NOT directly to recommendations)."""
    assert _PIPELINE_STAGE_AUTONEXT["grouping"] == "ai_refinement", (
        f"Expected grouping -> ai_refinement, got grouping -> {_PIPELINE_STAGE_AUTONEXT.get('grouping')}"
    )
    # Confirm the old direct path grouping -> recommendations is gone
    assert _PIPELINE_STAGE_AUTONEXT["grouping"] != "recommendations"


# ---------------------------------------------------------------------------
# Task 3 tests: advance-pipeline endpoint
# ---------------------------------------------------------------------------

def _seed_assessment_at_stage(db_session, pipeline_stage: str):
    """Helper: create an Instance + Assessment at a specific pipeline_stage."""
    inst = Instance(
        name="test-inst",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Test Assessment",
        number="ASMT0077700",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=pipeline_stage,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    return asmt


@patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None)
@patch("src.server._start_assessment_pipeline_job", return_value=True)
def test_advance_pipeline_accepts_ai_analysis_target(mock_start, mock_snap, client, db_session):
    """POST with target_stage=ai_analysis should return 200."""
    asmt = _seed_assessment_at_stage(db_session, PipelineStage.scans.value)
    resp = client.post(
        f"/api/assessments/{asmt.id}/advance-pipeline",
        json={"target_stage": "ai_analysis"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["requested_stage"] == "ai_analysis"


@patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None)
@patch("src.server._start_assessment_pipeline_job", return_value=True)
def test_advance_pipeline_accepts_ai_refinement_target(mock_start, mock_snap, client, db_session):
    """POST with target_stage=ai_refinement should return 200."""
    asmt = _seed_assessment_at_stage(db_session, PipelineStage.grouping.value)
    resp = client.post(
        f"/api/assessments/{asmt.id}/advance-pipeline",
        json={"target_stage": "ai_refinement"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["requested_stage"] == "ai_refinement"


@patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None)
@patch("src.server._start_assessment_pipeline_job", return_value=True)
def test_advance_pipeline_accepts_report_target(mock_start, mock_snap, client, db_session):
    """POST with target_stage=report should return 200."""
    asmt = _seed_assessment_at_stage(db_session, PipelineStage.recommendations.value)
    resp = client.post(
        f"/api/assessments/{asmt.id}/advance-pipeline",
        json={"target_stage": "report"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["requested_stage"] == "report"


@patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None)
@patch("src.server._start_assessment_pipeline_job", return_value=True)
@patch("src.server._set_assessment_pipeline_stage")
def test_advance_pipeline_rerun_from_complete(mock_set_stage, mock_start, mock_snap, client, db_session):
    """POST with target_stage=ai_analysis + rerun=true from complete stage should return 200."""
    asmt = _seed_assessment_at_stage(db_session, PipelineStage.complete.value)
    resp = client.post(
        f"/api/assessments/{asmt.id}/advance-pipeline",
        json={"target_stage": "ai_analysis", "rerun": True},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["rerun"] is True
    assert data["requested_stage"] == "ai_analysis"


def test_advance_pipeline_backwards_blocked_without_rerun(client, db_session):
    """POST with target_stage=ai_analysis from complete WITHOUT rerun should return 409."""
    asmt = _seed_assessment_at_stage(db_session, PipelineStage.complete.value)
    resp = client.post(
        f"/api/assessments/{asmt.id}/advance-pipeline",
        json={"target_stage": "ai_analysis"},
    )
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# Task 5 tests: AI Analysis properties (batch_size + context_enrichment)
# ---------------------------------------------------------------------------

def test_ai_analysis_batch_size_property_registered():
    from src.services.integration_properties import (
        AI_ANALYSIS_BATCH_SIZE,
        SECTION_AI_ANALYSIS,
        PROPERTY_DEFINITIONS,
    )
    assert AI_ANALYSIS_BATCH_SIZE == "ai_analysis.batch_size"
    assert AI_ANALYSIS_BATCH_SIZE in PROPERTY_DEFINITIONS
    defn = PROPERTY_DEFINITIONS[AI_ANALYSIS_BATCH_SIZE]
    assert defn.section == SECTION_AI_ANALYSIS
    assert defn.default == "0"


def test_ai_analysis_context_enrichment_property_registered():
    from src.services.integration_properties import (
        AI_ANALYSIS_CONTEXT_ENRICHMENT,
        PROPERTY_DEFINITIONS,
    )
    assert AI_ANALYSIS_CONTEXT_ENRICHMENT == "ai_analysis.context_enrichment"
    assert AI_ANALYSIS_CONTEXT_ENRICHMENT in PROPERTY_DEFINITIONS
    defn = PROPERTY_DEFINITIONS[AI_ANALYSIS_CONTEXT_ENRICHMENT]
    assert defn.default == "auto"


def test_load_ai_analysis_properties_defaults(db_session):
    from src.services.integration_properties import (
        load_ai_analysis_properties,
        AIAnalysisProperties,
    )
    props = load_ai_analysis_properties(db_session)
    assert isinstance(props, AIAnalysisProperties)
    assert props.batch_size == 0
    assert props.context_enrichment == "auto"
