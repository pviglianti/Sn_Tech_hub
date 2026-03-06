"""Tests for per-stage tool set definitions and prompt template builder."""

import pytest

from src.services.ai_stage_tool_sets import (
    STAGE_TOOL_SETS,
    build_batch_prompt,
)


def test_stage_tool_sets_has_all_ai_stages():
    """Every AI stage has a tool set defined."""
    expected = {"ai_analysis", "observations", "ai_refinement", "grouping", "recommendations", "report"}
    assert expected == set(STAGE_TOOL_SETS.keys())


def test_stage_tool_sets_are_prefixed():
    """All tool names use the mcp__tech-assessment-hub__ prefix."""
    for stage, tools in STAGE_TOOL_SETS.items():
        for tool in tools:
            assert tool.startswith("mcp__tech-assessment-hub__"), f"{stage}: {tool}"


def test_build_batch_prompt_basic():
    """build_batch_prompt produces a prompt with assessment and batch metadata."""
    prompt = build_batch_prompt(
        stage_instructions="Analyze each artifact for complexity.",
        assessment_id=42,
        stage="ai_analysis",
        batch_index=0,
        total_batches=4,
        artifact_ids=[101, 102, 103],
    )
    assert "Assessment ID: 42" in prompt
    assert "ai_analysis" in prompt
    assert "Batch: 1 of 4" in prompt
    assert "101" in prompt
    assert "Analyze each artifact for complexity." in prompt


def test_build_batch_prompt_with_artifact_names():
    """build_batch_prompt includes artifact names when provided."""
    prompt = build_batch_prompt(
        stage_instructions="Test instructions",
        assessment_id=1,
        stage="ai_analysis",
        batch_index=0,
        total_batches=1,
        artifact_ids=[101, 102],
        artifact_names=["My Script Include", "My Business Rule"],
    )
    assert "ID 101: My Script Include" in prompt
    assert "ID 102: My Business Rule" in prompt
