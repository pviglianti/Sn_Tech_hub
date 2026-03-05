"""Phase 7 integration tests: cross-cutting pipeline consistency.

These tests verify concerns that span multiple pipeline stages and are NOT
covered by the individual unit tests in test_phase7_pipeline_stages.py.

Sections:
    1. Pipeline consistency checks (config dict alignment)
    2. Endpoint-to-handler integration (advance + auto-advance)
    3. Re-run integration (rerun lifecycle, data preservation)
    4. Cross-stage data flow (ai_analysis -> ai_refinement -> report)
"""

import json
import pytest
from unittest.mock import patch

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    PipelineStage,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    OriginType,
    Feature,
    FeatureScanResult,
    GeneralRecommendation,
    Disposition,
)
from src.server import (
    _PIPELINE_STAGE_ORDER,
    _PIPELINE_STAGE_LABELS,
    _PIPELINE_STAGE_AUTONEXT,
    _run_assessment_pipeline_stage,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_instance_and_assessment(db_session, pipeline_stage="scans"):
    """Create a minimal Instance + Assessment at a given pipeline stage."""
    inst = Instance(
        name="integ-test",
        url="https://integ.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Integration Test",
        number="ASMT0055500",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=pipeline_stage,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    return inst, asmt


def _seed_full_pipeline_data(db_session, *, pipeline_stage="ai_analysis"):
    """Seed Instance, Assessment, Scan, ScanResults (customized + ootb),
    Features with linked members, and a GeneralRecommendation.

    Returns (assessment, instance, scan, customized_srs, features).
    """
    inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage)

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="integ-scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    # 3 customized + 1 ootb scan results
    customized_srs = []
    tables = ["sys_script_include", "sys_ui_policy", "sys_script_include"]
    for i in range(3):
        sr = ScanResult(
            scan_id=scan.id,
            sys_id=f"sys_integ_custom_{i}",
            table_name=tables[i],
            name=f"IntegCustom{i}",
            origin_type=OriginType.modified_ootb,
        )
        db_session.add(sr)
        customized_srs.append(sr)

    ootb_sr = ScanResult(
        scan_id=scan.id,
        sys_id="sys_integ_ootb_0",
        table_name="sys_script_include",
        name="IntegOotb0",
        origin_type=OriginType.ootb_untouched,
    )
    db_session.add(ootb_sr)
    db_session.flush()

    # Create 2 features, first with 5+ members (complex), second with 2 (simple)
    feat_complex = Feature(
        assessment_id=asmt.id,
        name="ComplexFeature",
        description="Feature with 5+ members",
    )
    db_session.add(feat_complex)
    db_session.flush()

    # Link all 3 customized + ootb + 2 extra to hit 6 members
    for sr in customized_srs:
        db_session.add(FeatureScanResult(feature_id=feat_complex.id, scan_result_id=sr.id))
    db_session.add(FeatureScanResult(feature_id=feat_complex.id, scan_result_id=ootb_sr.id))
    # Add 2 more scan results to reach 6
    extras = []
    for i in range(2):
        esr = ScanResult(
            scan_id=scan.id,
            sys_id=f"sys_integ_extra_{i}",
            table_name="sys_ui_policy",
            name=f"IntegExtra{i}",
            origin_type=OriginType.modified_ootb,
        )
        db_session.add(esr)
        db_session.flush()
        db_session.add(FeatureScanResult(feature_id=feat_complex.id, scan_result_id=esr.id))
        customized_srs.append(esr)

    feat_simple = Feature(
        assessment_id=asmt.id,
        name="SimpleFeature",
        description="Feature with few members",
        disposition=Disposition.keep_as_is,
        recommendation="Keep it as is",
    )
    db_session.add(feat_simple)
    db_session.flush()
    # Link 2 members to simple feature
    for sr in customized_srs[:2]:
        db_session.add(FeatureScanResult(feature_id=feat_simple.id, scan_result_id=sr.id))

    db_session.commit()
    for sr in customized_srs:
        db_session.refresh(sr)
    db_session.refresh(feat_complex)
    db_session.refresh(feat_simple)
    db_session.refresh(asmt)
    return asmt, inst, scan, customized_srs, [feat_complex, feat_simple]


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
            {"type": "incident", "number": "INC001", "table": "incident",
             "resolved": True, "data": {}, "source": "local"},
        ],
        "has_local_table_data": True,
    }


# ===========================================================================
# Section 1: Pipeline consistency checks
# ===========================================================================

class TestPipelineConsistency:
    """Verify cross-cutting alignment between enum, order list, labels, and autonext."""

    def test_every_stage_in_order_has_label(self):
        """Every stage in _PIPELINE_STAGE_ORDER must have a corresponding label."""
        missing = [s for s in _PIPELINE_STAGE_ORDER if s not in _PIPELINE_STAGE_LABELS]
        assert missing == [], f"Stages missing labels: {missing}"

    def test_every_label_is_in_order(self):
        """Every key in _PIPELINE_STAGE_LABELS must appear in _PIPELINE_STAGE_ORDER."""
        extra = [k for k in _PIPELINE_STAGE_LABELS if k not in _PIPELINE_STAGE_ORDER]
        assert extra == [], f"Label keys not in stage order: {extra}"

    def test_autonext_sources_are_valid_stages(self):
        """Every autonext source must be a valid stage."""
        invalid = [s for s in _PIPELINE_STAGE_AUTONEXT if s not in _PIPELINE_STAGE_ORDER]
        assert invalid == [], f"Autonext sources not in order: {invalid}"

    def test_autonext_targets_are_valid_stages(self):
        """Every autonext target must be a valid stage."""
        invalid = [t for t in _PIPELINE_STAGE_AUTONEXT.values() if t not in _PIPELINE_STAGE_ORDER]
        assert invalid == [], f"Autonext targets not in order: {invalid}"

    def test_autonext_targets_are_adjacent_successors(self):
        """Each autonext target must be the stage immediately following its source."""
        for source, target in _PIPELINE_STAGE_AUTONEXT.items():
            src_idx = _PIPELINE_STAGE_ORDER.index(source)
            tgt_idx = _PIPELINE_STAGE_ORDER.index(target)
            assert tgt_idx == src_idx + 1, (
                f"Autonext {source} -> {target}: target index {tgt_idx} "
                f"is not adjacent to source index {src_idx}"
            )

    def test_enum_values_match_order_list(self):
        """PipelineStage enum values must all appear in _PIPELINE_STAGE_ORDER."""
        enum_values = {member.value for member in PipelineStage}
        order_values = set(_PIPELINE_STAGE_ORDER)
        assert enum_values == order_values, (
            f"Enum values {enum_values} do not match order set {order_values}"
        )

    def test_three_new_ai_stages_in_enum(self):
        """ai_analysis, ai_refinement, and report must exist as PipelineStage members."""
        member_values = {m.value for m in PipelineStage}
        for stage_name in ("ai_analysis", "ai_refinement", "report"):
            assert stage_name in member_values, f"{stage_name} not found in PipelineStage enum"


# ===========================================================================
# Section 2: Endpoint-to-handler integration
# ===========================================================================

class TestEndpointToHandler:
    """Verify that POST advance-pipeline correctly triggers handlers and auto-advance."""

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.gather_artifact_context")
    def test_ai_analysis_advances_stage_to_observations(
        self, mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """Running ai_analysis handler should auto-advance pipeline_stage to observations.

        Note: engines now runs BEFORE ai_analysis in the pipeline (Phase 11A reorder).
        """
        inst, asmt = _seed_instance_and_assessment(db_session, PipelineStage.ai_analysis.value)
        # Add one customized scan result so handler has work
        scan = Scan(assessment_id=asmt.id, scan_type=ScanType.metadata,
                    name="s1", status=ScanStatus.completed)
        db_session.add(scan)
        db_session.flush()
        sr = ScanResult(scan_id=scan.id, sys_id="sys_ep_1", table_name="sys_script_include",
                        name="EndpointTest", origin_type=OriginType.modified_ootb)
        db_session.add(sr)
        db_session.commit()

        mock_gather.return_value = _make_mock_context()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

        # Verify auto-advance: _set_assessment_pipeline_stage called with "observations"
        advance_calls = [
            c for c in mock_set_stage.call_args_list
            if c.args and c.args[1] == PipelineStage.observations.value
        ]
        assert len(advance_calls) >= 1, (
            "Expected auto-advance call to 'observations' after ai_analysis completes"
        )

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    def test_ai_refinement_advances_stage_to_recommendations(
        self, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """Running ai_refinement handler should auto-advance pipeline_stage to recommendations."""
        asmt, _, _, _, _ = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.ai_refinement.value
        )

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

        advance_calls = [
            c for c in mock_set_stage.call_args_list
            if c.args and c.args[1] == PipelineStage.recommendations.value
        ]
        assert len(advance_calls) >= 1, (
            "Expected auto-advance call to 'recommendations' after ai_refinement completes"
        )

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    def test_report_advances_stage_to_complete(
        self, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """Running report handler should auto-advance pipeline_stage to complete."""
        asmt, _, _, _, _ = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.report.value
        )

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="report")

        advance_calls = [
            c for c in mock_set_stage.call_args_list
            if c.args and c.args[1] == PipelineStage.complete.value
        ]
        assert len(advance_calls) >= 1, (
            "Expected auto-advance call to 'complete' after report completes"
        )

    @patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None)
    @patch("src.server._start_assessment_pipeline_job", return_value=True)
    def test_endpoint_advance_through_all_new_stages_sequentially(
        self, mock_start, mock_snap, client, db_session
    ):
        """POST advance-pipeline for each new AI stage should succeed sequentially."""
        inst, asmt = _seed_instance_and_assessment(db_session, PipelineStage.scans.value)

        transitions = [
            ("scans", "engines"),
            ("engines", "ai_analysis"),
            ("ai_analysis", "observations"),
            ("observations", "review"),
        ]
        for current, target in transitions:
            asmt.pipeline_stage = current
            db_session.add(asmt)
            db_session.commit()

            resp = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": target},
            )
            assert resp.status_code == 200, (
                f"Advance {current} -> {target} failed: {resp.text}"
            )
            data = resp.json()
            assert data["success"] is True
            assert data["requested_stage"] == target


# ===========================================================================
# Section 3: Re-run integration
# ===========================================================================

class TestRerunIntegration:
    """Verify re-run lifecycle: complete -> reset -> re-start AI stages."""

    @patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None)
    @patch("src.server._start_assessment_pipeline_job", return_value=True)
    @patch("src.server._set_assessment_pipeline_stage")
    def test_rerun_from_complete_resets_to_scans_then_starts_ai(
        self, mock_set_stage, mock_start, mock_snap, client, db_session
    ):
        """POST rerun=true from complete should reset stage to scans, then start ai_analysis job."""
        inst, asmt = _seed_instance_and_assessment(db_session, PipelineStage.complete.value)

        resp = client.post(
            f"/api/assessments/{asmt.id}/advance-pipeline",
            json={"target_stage": "ai_analysis", "rerun": True},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success"] is True
        assert data["rerun"] is True
        assert data["requested_stage"] == "ai_analysis"

        # Verify _set_assessment_pipeline_stage was called with scans (the reset)
        reset_calls = [
            c for c in mock_set_stage.call_args_list
            if c.args and c.args[1] == PipelineStage.scans.value
        ]
        assert len(reset_calls) >= 1, "Expected stage reset to 'scans' during re-run"

        # Verify the background job was started targeting ai_analysis
        mock_start.assert_called_once()
        start_kwargs = mock_start.call_args
        assert start_kwargs[1]["target_stage"] == "ai_analysis" or \
               (start_kwargs[0] and len(start_kwargs[0]) > 1)

    def test_rerun_preserves_features(self, db_session, client):
        """Re-run should not delete existing Features."""
        asmt, inst, scan, srs, features = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.complete.value
        )
        original_feature_count = db_session.exec(
            select(Feature).where(Feature.assessment_id == asmt.id)
        ).all()
        assert len(original_feature_count) == 2

        # The POST will fail (no mock for _start_job) but importantly
        # it should NOT delete features. Use mock to allow it through.
        with patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None), \
             patch("src.server._start_assessment_pipeline_job", return_value=True), \
             patch("src.server._set_assessment_pipeline_stage"):
            resp = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": "ai_analysis", "rerun": True},
            )
        assert resp.status_code == 200

        # Features still exist
        remaining = db_session.exec(
            select(Feature).where(Feature.assessment_id == asmt.id)
        ).all()
        assert len(remaining) == 2, f"Expected 2 features preserved, got {len(remaining)}"

    def test_rerun_preserves_general_recommendations(self, db_session, client):
        """Re-run should not delete existing GeneralRecommendations."""
        asmt, inst, scan, srs, features = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.complete.value
        )
        # Add a general recommendation
        gr = GeneralRecommendation(
            assessment_id=asmt.id,
            title="Existing Rec",
            category="technical_findings",
            created_by="ai_pipeline",
            description='{"test": true}',
        )
        db_session.add(gr)
        db_session.commit()

        with patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None), \
             patch("src.server._start_assessment_pipeline_job", return_value=True), \
             patch("src.server._set_assessment_pipeline_stage"):
            resp = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": "ai_analysis", "rerun": True},
            )
        assert resp.status_code == 200

        remaining = db_session.exec(
            select(GeneralRecommendation).where(GeneralRecommendation.assessment_id == asmt.id)
        ).all()
        assert len(remaining) >= 1, "GeneralRecommendations should be preserved during re-run"


# ===========================================================================
# Section 4: Cross-stage data flow
# ===========================================================================

class TestCrossStageDataFlow:
    """Verify data written in one stage is correctly read by downstream stages."""

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.gather_artifact_context")
    def test_ai_analysis_writes_observations_then_refinement_enriches(
        self, mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """ai_analysis populates ai_observations; ai_refinement adds technical_review key."""
        # Step 1: Seed and run ai_analysis
        asmt, inst, scan, customized_srs, features = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.ai_analysis.value
        )
        mock_gather.return_value = _make_mock_context()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

        # Verify ai_observations were written
        for sr in customized_srs:
            db_session.refresh(sr)
        populated = [sr for sr in customized_srs if sr.ai_observations is not None]
        assert len(populated) > 0, "ai_analysis should populate ai_observations"

        # Step 2: Now run ai_refinement on the same assessment
        asmt.pipeline_stage = PipelineStage.ai_refinement.value
        db_session.add(asmt)
        db_session.commit()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

        # Verify technical_review was added to existing observations
        for sr in populated:
            db_session.refresh(sr)
            parsed = json.loads(sr.ai_observations)
            assert "technical_review" in parsed, (
                f"ai_refinement should add 'technical_review' to {sr.name}"
            )
            assert parsed["technical_review"]["review_type"] == "mode_a_artifact_review"
            # Original keys from ai_analysis should still be present
            assert "artifact_name" in parsed
            assert "context_enrichment_mode" in parsed

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    def test_refinement_creates_technical_findings_then_report_includes_them(
        self, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """ai_refinement creates GeneralRecommendation(technical_findings);
        report handler includes it in report data."""
        # Step 1: Run ai_refinement
        asmt, inst, scan, customized_srs, features = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.ai_refinement.value
        )

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

        # Verify technical_findings recommendation exists
        tech_recs = db_session.exec(
            select(GeneralRecommendation)
            .where(GeneralRecommendation.assessment_id == asmt.id)
            .where(GeneralRecommendation.category == "technical_findings")
        ).all()
        assert len(tech_recs) == 1, "ai_refinement should create exactly 1 technical_findings rec"

        # Step 2: Run report on the same assessment
        asmt.pipeline_stage = PipelineStage.report.value
        db_session.add(asmt)
        db_session.commit()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="report")

        # Verify report includes the technical_findings rec
        report_recs = db_session.exec(
            select(GeneralRecommendation)
            .where(GeneralRecommendation.assessment_id == asmt.id)
            .where(GeneralRecommendation.category == "assessment_report")
        ).all()
        assert len(report_recs) == 1
        report_data = json.loads(report_recs[0].description)

        # The report's general_recommendations section should count technical_findings
        gr_categories = report_data["general_recommendations"]["by_category"]
        assert "technical_findings" in gr_categories, (
            f"Report should include technical_findings in general_recommendations, "
            f"got: {gr_categories}"
        )

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    def test_report_aggregates_feature_data_from_grouping(
        self, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """Report handler should aggregate Features created during grouping stage."""
        asmt, inst, scan, customized_srs, features = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.report.value
        )

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="report")

        report_recs = db_session.exec(
            select(GeneralRecommendation)
            .where(GeneralRecommendation.assessment_id == asmt.id)
            .where(GeneralRecommendation.category == "assessment_report")
        ).all()
        assert len(report_recs) == 1
        report_data = json.loads(report_recs[0].description)

        # Verify feature aggregation
        feat_data = report_data["features"]
        assert feat_data["total"] == 2, f"Expected 2 features, got {feat_data['total']}"
        # SimpleFeature has disposition keep_as_is, ComplexFeature has None (unset)
        disp_dist = feat_data["disposition_distribution"]
        assert "keep_as_is" in disp_dist, f"Expected keep_as_is in disposition distribution: {disp_dist}"

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.gather_artifact_context")
    def test_full_ai_pipeline_sequence(
        self, mock_gather, mock_set_stage, mock_set_job, db_session, db_engine
    ):
        """Run ai_analysis -> ai_refinement -> report in sequence and verify
        end-to-end data integrity."""
        asmt, inst, scan, customized_srs, features = _seed_full_pipeline_data(
            db_session, pipeline_stage=PipelineStage.ai_analysis.value
        )
        mock_gather.return_value = _make_mock_context()

        # Stage 1: ai_analysis
        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

        # Verify observations written
        analyzed = 0
        for sr in customized_srs:
            db_session.refresh(sr)
            if sr.ai_observations:
                analyzed += 1
        assert analyzed > 0

        # Stage 2: ai_refinement
        asmt.pipeline_stage = PipelineStage.ai_refinement.value
        db_session.add(asmt)
        db_session.commit()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

        # Verify technical_findings GeneralRecommendation created
        tech_recs = db_session.exec(
            select(GeneralRecommendation)
            .where(GeneralRecommendation.assessment_id == asmt.id)
            .where(GeneralRecommendation.category == "technical_findings")
        ).all()
        assert len(tech_recs) == 1
        rollup = json.loads(tech_recs[0].description)
        assert rollup["features_created"] == 2

        # Stage 3: report
        asmt.pipeline_stage = PipelineStage.report.value
        db_session.add(asmt)
        db_session.commit()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="report")

        # Verify report was generated
        report_recs = db_session.exec(
            select(GeneralRecommendation)
            .where(GeneralRecommendation.assessment_id == asmt.id)
            .where(GeneralRecommendation.category == "assessment_report")
        ).all()
        assert len(report_recs) == 1
        report_data = json.loads(report_recs[0].description)

        # Cross-check: report should see the technical_findings rec created in refinement
        assert report_data["general_recommendations"]["total"] >= 1
        assert "technical_findings" in report_data["general_recommendations"]["by_category"]

        # Cross-check: report should see features from grouping
        assert report_data["features"]["total"] == 2

        # Cross-check: report should have correct assessment metadata
        assert report_data["assessment_name"] == "Integration Test"
        assert report_data["assessment_number"] == "ASMT0055500"
        assert report_data["instance_name"] == "integ-test"
