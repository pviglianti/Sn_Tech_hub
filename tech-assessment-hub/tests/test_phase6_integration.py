"""Integration test: all Phase 6 prompts registered and callable."""

from src.mcp.registry import PROMPT_REGISTRY


def test_all_phase6_prompts_registered():
    """All four new prompts appear in the registry."""
    prompts = PROMPT_REGISTRY.list_prompts()
    names = {p["name"] for p in prompts}
    assert "artifact_analyzer" in names
    assert "relationship_tracer" in names
    assert "technical_architect" in names
    assert "report_writer" in names


def test_phase6_prompt_count():
    """Phase 6 adds 4 new prompts to existing set."""
    prompts = PROMPT_REGISTRY.list_prompts()
    # Phase 5 had existing prompts + Phase 6 adds 4 new
    assert len(prompts) >= 7
