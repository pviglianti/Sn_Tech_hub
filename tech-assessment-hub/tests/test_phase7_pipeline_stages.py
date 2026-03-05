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


# ---------------------------------------------------------------------------
# Task 6 tests: AI Analysis pipeline stage handler
# ---------------------------------------------------------------------------

import json
from unittest.mock import MagicMock

from src.models import (
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    OriginType,
)
from src.services.integration_properties import AIAnalysisProperties


def _seed_assessment_with_scan_results(db_session, *, num_customized=2, num_ootb=1):
    """Seed an Instance, Assessment, Scan, and ScanResults for ai_analysis tests.

    Returns (assessment, list_of_customized_scan_results).
    """
    inst = Instance(
        name="ai-test-inst",
        url="https://ai-test.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="AI Analysis Test",
        number="ASMT0099900",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=PipelineStage.ai_analysis.value,
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

    customized_results = []
    for i in range(num_customized):
        sr = ScanResult(
            scan_id=scan.id,
            sys_id=f"sys_custom_{i}",
            table_name="sys_script_include",
            name=f"CustomScript{i}",
            origin_type=OriginType.modified_ootb,
        )
        db_session.add(sr)
        customized_results.append(sr)

    for i in range(num_ootb):
        sr = ScanResult(
            scan_id=scan.id,
            sys_id=f"sys_ootb_{i}",
            table_name="sys_script_include",
            name=f"OotbScript{i}",
            origin_type=OriginType.ootb_untouched,
        )
        db_session.add(sr)

    db_session.commit()
    for sr in customized_results:
        db_session.refresh(sr)
    db_session.refresh(asmt)
    return asmt, customized_results


def _make_mock_context(sr_name="TestArtifact", sr_table="sys_script_include"):
    """Return a fake gather_artifact_context response."""
    return {
        "artifact": {"id": 1, "name": sr_name, "table_name": sr_table},
        "update_sets": [{"id": 10, "name": "US1"}],
        "human_context": {
            "observations": None,
            "ai_observations": None,
            "disposition": None,
            "review_status": "pending_review",
            "recommendation": None,
            "features": [],
        },
        "references": [
            {"type": "incident", "number": "INC0012345", "table": "incident", "resolved": True, "data": {}, "source": "local"},
        ],
        "has_local_table_data": True,
    }


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
def test_ai_analysis_handler_populates_ai_observations(
    mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """ai_analysis handler should populate ai_observations JSON for customized results."""
    asmt, customized = _seed_assessment_with_scan_results(db_session, num_customized=2, num_ootb=1)

    mock_gather.return_value = _make_mock_context()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    # Refresh to get updated values
    for sr in customized:
        db_session.refresh(sr)

    for sr in customized:
        assert sr.ai_observations is not None, f"ai_observations should be populated for {sr.name}"
        parsed = json.loads(sr.ai_observations)
        assert "artifact_name" in parsed
        assert "artifact_table" in parsed
        assert "context_enrichment_mode" in parsed
        assert "references_found" in parsed
        assert "has_local_data" in parsed
        assert "human_context_present" in parsed
        assert "update_sets_count" in parsed

    assert mock_gather.call_count == 2, "gather_artifact_context should be called once per customized result"


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
def test_ai_analysis_handler_batch_size_zero_processes_all(
    mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """batch_size=0 should process all customized artifacts at once."""
    asmt, customized = _seed_assessment_with_scan_results(db_session, num_customized=5, num_ootb=0)

    mock_gather.return_value = _make_mock_context()

    # Default AIAnalysisProperties has batch_size=0
    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    assert mock_gather.call_count == 5, "All 5 customized artifacts should be processed"

    for sr in customized:
        db_session.refresh(sr)
        assert sr.ai_observations is not None


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
@patch("src.server.load_ai_analysis_properties")
def test_ai_analysis_handler_passes_enrichment_mode(
    mock_load_props, mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """The enrichment_mode from properties should be passed to gather_artifact_context."""
    asmt, customized = _seed_assessment_with_scan_results(db_session, num_customized=1, num_ootb=0)

    mock_load_props.return_value = AIAnalysisProperties(batch_size=0, context_enrichment="never")
    mock_gather.return_value = _make_mock_context()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    # Verify enrichment_mode was passed through
    assert mock_gather.call_count == 1
    call_args = mock_gather.call_args
    assert call_args[0][3] == "never", "enrichment_mode should be 'never'"

    db_session.refresh(customized[0])
    parsed = json.loads(customized[0].ai_observations)
    assert parsed["context_enrichment_mode"] == "never"


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
def test_ai_analysis_handler_skips_ootb_results(
    mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """Only customized (modified_ootb, net_new_customer) results should be analyzed."""
    asmt, _ = _seed_assessment_with_scan_results(db_session, num_customized=0, num_ootb=3)

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    assert mock_gather.call_count == 0, "OOTB results should not be analyzed"


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
def test_ai_analysis_handler_human_context_flag(
    mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """human_context_present should be True when observations or disposition exist."""
    asmt, customized = _seed_assessment_with_scan_results(db_session, num_customized=1, num_ootb=0)

    ctx = _make_mock_context()
    ctx["human_context"]["observations"] = "Human wrote this note"
    ctx["human_context"]["disposition"] = "keep"
    mock_gather.return_value = ctx

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    db_session.refresh(customized[0])
    parsed = json.loads(customized[0].ai_observations)
    assert parsed["human_context_present"] is True


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
def test_ai_analysis_handler_references_count(
    mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """references_found should count only resolved references."""
    asmt, customized = _seed_assessment_with_scan_results(db_session, num_customized=1, num_ootb=0)

    ctx = _make_mock_context()
    ctx["references"] = [
        {"type": "incident", "number": "INC001", "resolved": True, "data": {}, "source": "local"},
        {"type": "change_request", "number": "CHG001", "resolved": False, "data": None, "source": None},
        {"type": "problem", "number": "PRB001", "resolved": True, "data": {}, "source": "remote"},
    ]
    mock_gather.return_value = ctx

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    db_session.refresh(customized[0])
    parsed = json.loads(customized[0].ai_observations)
    assert parsed["references_found"] == 2, "Only resolved references should be counted"


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
@patch("src.server.gather_artifact_context")
def test_ai_analysis_handler_progress_updates(
    mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
):
    """Handler should update progress via _set_assessment_pipeline_job_state for each artifact."""
    asmt, customized = _seed_assessment_with_scan_results(db_session, num_customized=3, num_ootb=0)

    mock_gather.return_value = _make_mock_context()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    # The function calls _set_assessment_pipeline_job_state:
    # 1x at start (from _run_assessment_pipeline_stage itself, before the handler)
    # 3x for progress (one per artifact)
    # 1x at completion
    # Total = 5 calls
    progress_calls = [
        c for c in mock_set_job.call_args_list
        if c.kwargs.get("message", "").startswith("Analyzing artifact")
    ]
    assert len(progress_calls) == 3, f"Expected 3 progress calls, got {len(progress_calls)}"


# ---------------------------------------------------------------------------
# Task 7 tests: AI Refinement pipeline stage handler
# ---------------------------------------------------------------------------

from sqlmodel import select  # noqa: E402 – late import for Task 7 tests

from src.models import (
    Feature,
    FeatureScanResult,
    GeneralRecommendation,
    Disposition,
    BestPractice,
    BestPracticeCategory,
)


def _seed_assessment_with_features(db_session, *, num_features=1, members_per_feature=5, tables=None):
    """Seed an Instance, Assessment, Scan, Features and linked ScanResults for ai_refinement tests.

    Returns (assessment, list_of_features, list_of_scan_results).
    """
    if tables is None:
        tables = ["sys_script_include"]

    inst = Instance(
        name="refine-test-inst",
        url="https://refine-test.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="AI Refinement Test",
        number="ASMT0088800",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=PipelineStage.ai_refinement.value,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="refine-scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    all_features = []
    all_scan_results = []

    for fi in range(num_features):
        feat = Feature(
            assessment_id=asmt.id,
            name=f"Feature_{fi}",
            description=f"Test feature {fi}",
        )
        db_session.add(feat)
        db_session.flush()

        for mi in range(members_per_feature):
            table = tables[mi % len(tables)]
            sr = ScanResult(
                scan_id=scan.id,
                sys_id=f"sys_feat{fi}_member{mi}",
                table_name=table,
                name=f"Artifact_F{fi}_M{mi}",
                origin_type=OriginType.modified_ootb,
            )
            db_session.add(sr)
            db_session.flush()

            link = FeatureScanResult(
                feature_id=feat.id,
                scan_result_id=sr.id,
            )
            db_session.add(link)
            all_scan_results.append(sr)

        all_features.append(feat)

    db_session.commit()
    for f in all_features:
        db_session.refresh(f)
    for sr in all_scan_results:
        db_session.refresh(sr)
    db_session.refresh(asmt)
    return asmt, all_features, all_scan_results


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
def test_ai_refinement_handler_analyzes_complex_features(
    mock_set_stage, mock_set_job, db_session, db_engine
):
    """Features with 5+ members should get ai_summary populated."""
    asmt, features, _ = _seed_assessment_with_features(
        db_session,
        num_features=1,
        members_per_feature=6,
        tables=["sys_script_include", "sys_ui_policy"],
    )

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    db_session.refresh(features[0])
    assert features[0].ai_summary is not None, "ai_summary should be populated for complex feature"

    parsed = json.loads(features[0].ai_summary)
    assert parsed["refinement_type"] == "complex_feature_analysis"
    assert parsed["member_count"] == 6
    assert parsed["cross_table_relationship"] is True
    assert len(parsed["member_artifacts"]) == 6
    assert len(parsed["tables_involved"]) == 2


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
def test_ai_refinement_handler_skips_simple_features(
    mock_set_stage, mock_set_job, db_session, db_engine
):
    """Features with <5 members should NOT get ai_summary populated."""
    asmt, features, _ = _seed_assessment_with_features(
        db_session,
        num_features=1,
        members_per_feature=3,
    )

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    db_session.refresh(features[0])
    assert features[0].ai_summary is None, "ai_summary should NOT be populated for simple feature"


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
def test_ai_refinement_handler_mode_a_enriches_ai_observations(
    mock_set_stage, mock_set_job, db_session, db_engine
):
    """Artifacts with ai_observations should get a 'technical_review' key added."""
    asmt, features, scan_results = _seed_assessment_with_features(
        db_session,
        num_features=1,
        members_per_feature=2,
    )

    # Populate ai_observations on one scan result (simulating ai_analysis stage output)
    prior_analysis = {"artifact_name": "Artifact_F0_M0", "context_enrichment_mode": "auto"}
    scan_results[0].ai_observations = json.dumps(prior_analysis, sort_keys=True)
    db_session.add(scan_results[0])
    db_session.commit()

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    db_session.refresh(scan_results[0])
    parsed = json.loads(scan_results[0].ai_observations)
    assert "technical_review" in parsed, "ai_observations should contain 'technical_review' key"
    assert parsed["technical_review"]["review_type"] == "mode_a_artifact_review"
    # Prior keys should still be present
    assert "artifact_name" in parsed
    assert "context_enrichment_mode" in parsed


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
def test_ai_refinement_handler_creates_general_recommendation(
    mock_set_stage, mock_set_job, db_session, db_engine
):
    """A GeneralRecommendation with category='technical_findings' should be created."""
    asmt, _, _ = _seed_assessment_with_features(
        db_session,
        num_features=2,
        members_per_feature=3,
    )

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    recs = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "technical_findings")
    ).all()
    assert len(recs) == 1, f"Expected 1 GeneralRecommendation, got {len(recs)}"
    rec = recs[0]

    assert rec.title == "AI Refinement \u2014 Technical Debt Roll-up"
    assert rec.created_by == "ai_pipeline"

    rollup = json.loads(rec.description)
    assert "total_customized_artifacts" in rollup
    assert "customized_by_table" in rollup
    assert "features_created" in rollup
    assert "disposition_distribution" in rollup
    assert "active_best_practice_checks" in rollup
    assert rollup["features_created"] == 2


@patch("src.server._set_assessment_pipeline_job_state")
@patch("src.server._set_assessment_pipeline_stage")
def test_ai_refinement_handler_progress_updates(
    mock_set_stage, mock_set_job, db_session, db_engine
):
    """Progress updates should be called at the expected stages."""
    asmt, _, _ = _seed_assessment_with_features(
        db_session,
        num_features=1,
        members_per_feature=2,
    )

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    # Collect all progress calls from the handler (excluding the initial 15% from the wrapper)
    handler_calls = [
        c for c in mock_set_job.call_args_list
        if c.kwargs.get("stage") == "ai_refinement" and c.kwargs.get("status") == "running"
    ]
    # We expect: 15% (complex features), 45% (artifact review), 75% (roll-up), 95% (committing)
    # Plus the initial 15% from _run_assessment_pipeline_stage wrapper
    progress_values = [c.kwargs.get("progress_percent") for c in handler_calls]
    assert 15 in progress_values, f"15% progress not found in {progress_values}"
    assert 45 in progress_values, f"45% progress not found in {progress_values}"
    assert 75 in progress_values, f"75% progress not found in {progress_values}"
    assert 95 in progress_values, f"95% progress not found in {progress_values}"

    # Final completion call
    completion_calls = [
        c for c in mock_set_job.call_args_list
        if c.kwargs.get("status") == "completed"
    ]
    assert len(completion_calls) == 1, "Should have exactly one completion call"
