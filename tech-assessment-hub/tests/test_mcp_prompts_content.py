"""Tests for MCP assessment methodology prompt content (Phase 2 + 3/4)."""

import pytest

from src.mcp.registry import PROMPT_REGISTRY


# --- Registration tests ---


def test_tech_assessment_expert_prompt_registered():
    """The tech_assessment_expert prompt must be registered in PROMPT_REGISTRY."""
    assert PROMPT_REGISTRY.has_prompt("tech_assessment_expert")


def test_tech_assessment_reviewer_prompt_registered():
    """The tech_assessment_reviewer prompt must be registered in PROMPT_REGISTRY."""
    assert PROMPT_REGISTRY.has_prompt("tech_assessment_reviewer")


# --- Structure tests ---


def test_expert_prompt_returns_valid_mcp_messages():
    """Expert prompt handler must return MCP-compliant message structure."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")

    assert "description" in result
    assert "messages" in result
    assert isinstance(result["messages"], list)
    assert len(result["messages"]) >= 1

    msg = result["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"]["type"] == "text"
    assert len(msg["content"]["text"]) > 100  # Non-trivial content


def test_reviewer_prompt_returns_valid_mcp_messages():
    """Reviewer prompt handler must return MCP-compliant message structure."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_reviewer")

    assert "description" in result
    assert "messages" in result
    assert isinstance(result["messages"], list)
    assert len(result["messages"]) >= 1

    msg = result["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"]["type"] == "text"
    assert len(msg["content"]["text"]) > 100


# --- Content coverage tests (key methodology elements present) ---


def test_expert_prompt_covers_classification_rules():
    """Expert prompt must explain origin classification (modified_ootb, net_new_customer, etc.)."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    assert "modified_ootb" in text
    assert "net_new_customer" in text
    assert "ootb_untouched" in text


def test_expert_prompt_covers_disposition_framework():
    """Expert prompt must explain disposition categories."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    # All four dispositions from the methodology
    for keyword in ["keep", "refactor", "replace", "remove"]:
        assert keyword.lower() in text.lower(), f"Missing disposition keyword: {keyword}"


def test_expert_prompt_covers_iterative_methodology():
    """Expert prompt must describe multi-pass iterative approach."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    assert "pass" in text.lower() or "iterative" in text.lower()


def test_expert_prompt_covers_grouping_signals():
    """Expert prompt must reference grouping signal categories."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    assert "update set" in text.lower()
    assert "grouping" in text.lower() or "cluster" in text.lower()


def test_expert_prompt_covers_tool_usage():
    """Expert prompt must guide which MCP tools to use."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    # Should reference key tools
    assert "get_assessment_results" in text or "tool" in text.lower()


def test_expert_prompt_covers_token_efficiency():
    """Expert prompt must include token efficiency guidance."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    assert "token" in text.lower() or "summary" in text.lower()


def test_reviewer_prompt_is_lighter_than_expert():
    """Reviewer prompt should be more focused (shorter) than expert prompt."""
    expert = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    reviewer = PROMPT_REGISTRY.get_prompt("tech_assessment_reviewer")

    expert_len = len(expert["messages"][0]["content"]["text"])
    reviewer_len = len(reviewer["messages"][0]["content"]["text"])

    assert reviewer_len < expert_len


def test_expert_prompt_accepts_assessment_id_argument():
    """Expert prompt should accept optional assessment_id argument."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert", {"assessment_id": "42"})

    # Should still return valid structure (argument is optional context)
    assert "messages" in result
    text = result["messages"][0]["content"]["text"]
    assert len(text) > 100


# --- Phase 3/4: Feature Reasoning Orchestrator prompt tests ---


def test_feature_reasoning_orchestrator_prompt_registered():
    """The feature_reasoning_orchestrator prompt must be registered."""
    assert PROMPT_REGISTRY.has_prompt("feature_reasoning_orchestrator")


def test_orchestrator_prompt_returns_valid_mcp_messages():
    """Orchestrator prompt handler must return MCP-compliant message structure."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "99"}
    )

    assert "description" in result
    assert "messages" in result
    assert isinstance(result["messages"], list)
    assert len(result["messages"]) >= 1

    msg = result["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"]["type"] == "text"
    assert len(msg["content"]["text"]) > 100


def test_orchestrator_prompt_includes_assessment_id_context():
    """When assessment_id is provided, prompt should include active context."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "42"}
    )
    text = result["messages"][0]["content"]["text"]

    assert "assessment_id=42" in text


def test_orchestrator_prompt_references_pipeline_tools():
    """Orchestrator prompt must reference the four key pipeline tools."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "1"}
    )
    text = result["messages"][0]["content"]["text"]

    for tool_name in (
        "seed_feature_groups",
        "run_feature_reasoning",
        "feature_grouping_status",
        "upsert_feature_recommendation",
    ):
        assert tool_name in text, f"Missing tool reference: {tool_name}"


def test_orchestrator_prompt_covers_convergence_logic():
    """Orchestrator prompt must explain convergence criteria and decision logic."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "1"}
    )
    text = result["messages"][0]["content"]["text"]

    assert "converged" in text.lower()
    assert "should_continue" in text
    assert "delta" in text


def test_orchestrator_prompt_covers_pass_types():
    """Orchestrator prompt must explain all four pass types."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "1"}
    )
    text = result["messages"][0]["content"]["text"]

    for pass_type in ("auto", "observe", "group_refine", "verify"):
        assert pass_type in text, f"Missing pass type: {pass_type}"


def test_orchestrator_prompt_covers_ootb_recommendations():
    """Orchestrator prompt must guide OOTB replacement recommendation flow."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "1"}
    )
    text = result["messages"][0]["content"]["text"]

    assert "recommendation_type" in text
    assert "ootb_capability_name" in text or "OOTB" in text
    assert "product_name" in text or "product" in text.lower()


def test_orchestrator_prompt_covers_non_negotiable_rules():
    """Orchestrator must emphasize customized-only and human-override rules."""
    result = PROMPT_REGISTRY.get_prompt(
        "feature_reasoning_orchestrator", {"assessment_id": "1"}
    )
    text = result["messages"][0]["content"]["text"]

    assert "customized" in text.lower()
    assert "human" in text.lower()


def test_expert_prompt_now_references_pipeline_tools():
    """Expert prompt (Phase 2) should now also reference Phase 3+ pipeline tools."""
    result = PROMPT_REGISTRY.get_prompt("tech_assessment_expert")
    text = result["messages"][0]["content"]["text"]

    assert "seed_feature_groups" in text
    assert "run_feature_reasoning" in text
    assert "feature_grouping_status" in text
    assert "upsert_feature_recommendation" in text
