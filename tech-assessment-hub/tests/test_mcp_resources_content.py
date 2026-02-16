"""Tests for MCP assessment reference resources (Phase 3)."""

import pytest

from src.mcp.registry import RESOURCE_REGISTRY


# --- Expected URIs from the plan ---

EXPECTED_URIS = [
    "assessment://guide/classification-rules",
    "assessment://guide/grouping-signals",
    "assessment://guide/finding-patterns",
    "assessment://guide/app-file-types",
    "assessment://schema/scan-result-fields",
    "assessment://schema/feature-fields",
]


# --- Registration tests ---


def test_all_planned_resources_registered():
    """All 6 planned resources must be registered."""
    for uri in EXPECTED_URIS:
        assert RESOURCE_REGISTRY.has_resource(uri), f"Missing resource: {uri}"


def test_resource_count():
    """Exactly 6 assessment resources should be registered."""
    resources = RESOURCE_REGISTRY.list_resources()
    assessment_resources = [r for r in resources if r["uri"].startswith("assessment://")]
    assert len(assessment_resources) == 6


# --- Structure tests ---


@pytest.mark.parametrize("uri", EXPECTED_URIS)
def test_resource_returns_valid_structure(uri):
    """Each resource must return MCP-compliant content structure."""
    result = RESOURCE_REGISTRY.read_resource(uri)

    assert "contents" in result
    assert isinstance(result["contents"], list)
    assert len(result["contents"]) == 1

    content = result["contents"][0]
    assert content["uri"] == uri
    assert content["mimeType"] == "text/markdown"
    assert len(content["text"]) > 50  # Non-trivial content


# --- Content-specific tests for domain resources ---


def test_classification_rules_covers_origin_types():
    """Classification rules resource must explain all origin types."""
    result = RESOURCE_REGISTRY.read_resource("assessment://guide/classification-rules")
    text = result["contents"][0]["text"]

    for origin in ["modified_ootb", "ootb_untouched", "net_new_customer", "unknown_no_history"]:
        assert origin in text, f"Missing origin type: {origin}"


def test_classification_rules_covers_decision_tree():
    """Classification rules resource must include the decision logic."""
    result = RESOURCE_REGISTRY.read_resource("assessment://guide/classification-rules")
    text = result["contents"][0]["text"]

    assert "sys_upgrade_history" in text or "version history" in text.lower()
    assert "baseline" in text.lower()


def test_grouping_signals_covers_signal_categories():
    """Grouping signals resource must cover the key signal categories."""
    result = RESOURCE_REGISTRY.read_resource("assessment://guide/grouping-signals")
    text = result["contents"][0]["text"].lower()

    assert "update set" in text
    assert "table" in text
    assert "naming" in text or "name" in text
    assert "code reference" in text or "cross-reference" in text


def test_grouping_signals_covers_confidence():
    """Grouping signals resource must include confidence scoring."""
    result = RESOURCE_REGISTRY.read_resource("assessment://guide/grouping-signals")
    text = result["contents"][0]["text"].lower()

    assert "confidence" in text


def test_finding_patterns_covers_common_patterns():
    """Finding patterns resource must describe the key patterns."""
    result = RESOURCE_REGISTRY.read_resource("assessment://guide/finding-patterns")
    text = result["contents"][0]["text"].lower()

    assert "ootb alternative" in text or "ootb" in text
    assert "dead" in text or "broken" in text
    assert "refactor" in text


def test_app_file_types_covers_key_types():
    """App file types resource must list important ServiceNow app file types."""
    result = RESOURCE_REGISTRY.read_resource("assessment://guide/app-file-types")
    text = result["contents"][0]["text"].lower()

    for file_type in ["business rule", "script include", "client script", "ui polic"]:
        assert file_type in text, f"Missing app file type: {file_type}"


def test_scan_result_schema_covers_key_fields():
    """Scan result schema resource must list key ScanResult model fields."""
    result = RESOURCE_REGISTRY.read_resource("assessment://schema/scan-result-fields")
    text = result["contents"][0]["text"]

    for field in ["origin_type", "head_owner", "disposition", "observations", "table_name"]:
        assert field in text, f"Missing ScanResult field: {field}"


def test_feature_schema_covers_key_fields():
    """Feature schema resource must list key Feature model fields."""
    result = RESOURCE_REGISTRY.read_resource("assessment://schema/feature-fields")
    text = result["contents"][0]["text"]

    for field in ["name", "description", "disposition", "recommendation", "assessment_id"]:
        assert field in text, f"Missing Feature field: {field}"
