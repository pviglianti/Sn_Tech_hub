"""Tests for Phase 7 PipelineStage enum extensions.

Verifies the three new pipeline stages (ai_analysis, ai_refinement, report)
exist with correct values and the full 10-member ordering is preserved.
"""

import pytest

from src.models import PipelineStage


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
