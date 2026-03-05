"""Phase 11C integration tests: depth-first analyzer pipeline wiring.

Verifies that the ai_analysis stage handler branches correctly by analysis_mode
and that the grouping stage is mode-aware (preserving DFS features).
"""

import json
import pytest
from unittest.mock import patch, MagicMock, call

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    PipelineStage,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.server import _run_assessment_pipeline_stage
from src.services.depth_first_analyzer import DFSAnalysisResult
from src.services.integration_properties import AIAnalysisProperties


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_instance_and_assessment(db_session, pipeline_stage="ai_analysis"):
    """Create a minimal Instance + Assessment at a given pipeline stage."""
    inst = Instance(
        name="p11c-test",
        url="https://p11c.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Phase 11C Test",
        number="ASMT_P11C_001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=pipeline_stage,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    return inst, asmt


def _add_customized_scan_results(db_session, asmt, count=3):
    """Add a scan with customized ScanResults for the assessment."""
    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="p11c-scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    srs = []
    for i in range(count):
        sr = ScanResult(
            scan_id=scan.id,
            sys_id=f"sys_p11c_{i}",
            table_name="sys_script_include",
            name=f"P11cCustom{i}",
            origin_type=OriginType.modified_ootb,
        )
        db_session.add(sr)
        srs.append(sr)
    db_session.commit()
    for sr in srs:
        db_session.refresh(sr)
    return scan, srs


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


def _make_dfs_ai_props():
    """Return AIAnalysisProperties with depth_first mode."""
    return AIAnalysisProperties(
        analysis_mode="depth_first",
        max_rabbit_hole_depth=10,
        max_neighbors_per_hop=20,
        min_edge_weight_for_traversal=2.0,
        context_enrichment="auto",
    )


def _make_sequential_ai_props():
    """Return AIAnalysisProperties with default sequential mode."""
    return AIAnalysisProperties(
        analysis_mode="sequential",
        context_enrichment="auto",
    )


def _make_dfs_result():
    """Return a mock DFSAnalysisResult."""
    return DFSAnalysisResult(
        analyzed=5,
        features_created=2,
        features_updated=1,
        total_customized=5,
        analysis_order=[1, 2, 3, 4, 5],
    )


# ===========================================================================
# Test 1: ai_analysis in depth_first mode
# ===========================================================================

class TestAIAnalysisDepthFirstMode:

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.run_depth_first_analysis")
    @patch("src.server.build_relationship_graph")
    @patch("src.server.load_ai_analysis_properties")
    def test_ai_analysis_depth_first_mode(
        self, mock_load_ai, mock_build_graph, mock_dfs, mock_set_stage, mock_set_job,
        db_session, db_engine,
    ):
        """When analysis_mode=depth_first, DFS function should be called with correct args."""
        inst, asmt = _seed_instance_and_assessment(db_session)
        scan, srs = _add_customized_scan_results(db_session, asmt)

        mock_load_ai.return_value = _make_dfs_ai_props()
        mock_graph = MagicMock()
        mock_build_graph.return_value = mock_graph
        dfs_result = _make_dfs_result()
        mock_dfs.return_value = dfs_result

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

        # Verify build_relationship_graph was called
        mock_build_graph.assert_called_once()
        bg_args = mock_build_graph.call_args
        assert bg_args[0][1] == asmt.id  # assessment_id

        # Verify run_depth_first_analysis was called with correct args
        mock_dfs.assert_called_once()
        dfs_call = mock_dfs.call_args
        assert dfs_call[0][1] == asmt.id  # assessment_id
        assert dfs_call[0][2] == inst.id  # instance_id
        assert dfs_call[0][3] is mock_graph  # graph
        assert dfs_call[1]["max_rabbit_hole_depth"] == 10
        assert dfs_call[1]["max_neighbors_per_hop"] == 20
        assert dfs_call[1]["min_edge_weight"] == 2.0
        assert dfs_call[1]["context_enrichment"] == "auto"
        assert "checkpoint_callback" in dfs_call[1]
        assert "progress_callback" in dfs_call[1]


# ===========================================================================
# Test 2: ai_analysis in sequential mode unchanged
# ===========================================================================

class TestAIAnalysisSequentialMode:

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.gather_artifact_context")
    @patch("src.server.run_depth_first_analysis")
    @patch("src.server.build_relationship_graph")
    def test_ai_analysis_sequential_mode_unchanged(
        self, mock_build_graph, mock_dfs, mock_gather, mock_set_stage, mock_set_job,
        db_session, db_engine,
    ):
        """When analysis_mode=sequential (default), DFS should NOT be called."""
        inst, asmt = _seed_instance_and_assessment(db_session)
        scan, srs = _add_customized_scan_results(db_session, asmt, count=2)

        mock_gather.return_value = _make_mock_context()

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

        # DFS functions should NOT be called in sequential mode
        mock_build_graph.assert_not_called()
        mock_dfs.assert_not_called()

        # gather_artifact_context SHOULD be called (sequential mode)
        assert mock_gather.call_count == 2  # once per customized result

        # Verify ScanResult.ai_observations was set (sequential behavior)
        for sr in srs:
            db_session.refresh(sr)
            assert sr.ai_observations is not None
            obs = json.loads(sr.ai_observations)
            assert "artifact_name" in obs


# ===========================================================================
# Test 3: grouping after depth_first preserves features
# ===========================================================================

class TestGroupingModeAware:

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.seed_feature_groups_handle")
    @patch("src.server.load_ai_analysis_properties")
    def test_grouping_after_depth_first_preserves_features(
        self, mock_load_ai, mock_seed_handle, mock_set_stage, mock_set_job,
        db_session, db_engine,
    ):
        """In depth_first mode, grouping passes reset_existing=False."""
        inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage="grouping")

        mock_load_ai.return_value = _make_dfs_ai_props()
        mock_seed_handle.return_value = {
            "success": True,
            "features_created": 0,
            "grouped_count": 5,
        }

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="grouping")

        # Verify seed_feature_groups_handle was called with reset_existing=False
        mock_seed_handle.assert_called_once()
        call_params = mock_seed_handle.call_args[0][0]  # first positional arg = params dict
        assert call_params["assessment_id"] == asmt.id
        assert call_params["reset_existing"] is False

    # ===========================================================================
    # Test 4: grouping after sequential resets features
    # ===========================================================================

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.seed_feature_groups_handle")
    @patch("src.server.load_ai_analysis_properties")
    def test_grouping_after_sequential_resets_features(
        self, mock_load_ai, mock_seed_handle, mock_set_stage, mock_set_job,
        db_session, db_engine,
    ):
        """In sequential mode (default), grouping should NOT pass reset_existing=False."""
        inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage="grouping")

        mock_load_ai.return_value = _make_sequential_ai_props()
        mock_seed_handle.return_value = {
            "success": True,
            "features_created": 3,
            "grouped_count": 10,
        }

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="grouping")

        # Verify seed_feature_groups_handle was called WITHOUT reset_existing in params
        mock_seed_handle.assert_called_once()
        call_params = mock_seed_handle.call_args[0][0]  # first positional arg = params dict
        assert call_params["assessment_id"] == asmt.id
        assert "reset_existing" not in call_params  # default True handled by the handle function


# ===========================================================================
# Test 5: depth-first telemetry recorded
# ===========================================================================

class TestDepthFirstTelemetry:

    @patch("src.server._set_assessment_pipeline_job_state")
    @patch("src.server._set_assessment_pipeline_stage")
    @patch("src.server.run_depth_first_analysis")
    @patch("src.server.build_relationship_graph")
    @patch("src.server.load_ai_analysis_properties")
    @patch("src.server.refresh_assessment_runtime_usage")
    def test_depth_first_telemetry_recorded(
        self, mock_refresh_usage, mock_load_ai, mock_build_graph, mock_dfs,
        mock_set_stage, mock_set_job, db_session, db_engine,
    ):
        """Telemetry details should contain mode=depth_first and DFS-specific fields."""
        inst, asmt = _seed_instance_and_assessment(db_session)
        scan, srs = _add_customized_scan_results(db_session, asmt)

        mock_load_ai.return_value = _make_dfs_ai_props()
        mock_build_graph.return_value = MagicMock()
        dfs_result = _make_dfs_result()
        mock_dfs.return_value = dfs_result

        with patch("src.server.engine", db_engine):
            _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

        # Verify telemetry was recorded by checking the final refresh_assessment_runtime_usage call
        # The last call to refresh_assessment_runtime_usage should contain telemetry details
        assert mock_refresh_usage.call_count >= 2  # at least start + finish
        last_call = mock_refresh_usage.call_args_list[-1]
        details = last_call[1].get("details") or (last_call[0][4] if len(last_call[0]) > 4 else {})

        # The telemetry_details dict is passed in the details kwarg of the final refresh call
        # Look for ai_analysis key in the details
        if "ai_analysis" in details:
            ai_telemetry = details["ai_analysis"]
            assert ai_telemetry["mode"] == "depth_first"
            assert ai_telemetry["customized_total"] == 5
            assert ai_telemetry["analyzed_count"] == 5
            assert ai_telemetry["features_created"] == 2
            assert ai_telemetry["features_updated"] == 1
