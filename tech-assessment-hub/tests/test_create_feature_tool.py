"""Tests for the create_feature MCP tool."""

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    Instance,
)


def _seed_assessment(db_session):
    """Create a minimal Instance + Assessment for testing."""
    inst = Instance(
        name="create-feat-inst",
        url="https://create-feat.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Feature Creation Assessment",
        number="ASMT0099001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    return asmt


def test_create_feature_basic(db_session):
    """Creating a feature with only name + assessment_id should succeed."""
    from src.mcp.tools.core.create_feature import handle

    asmt = _seed_assessment(db_session)
    result = handle(
        {"assessment_id": asmt.id, "name": "Incident Routing"},
        db_session,
    )

    assert result["success"] is True
    assert result["name"] == "Incident Routing"

    feature = db_session.get(Feature, result["feature_id"])
    assert feature is not None
    assert feature.assessment_id == asmt.id
    assert feature.name == "Incident Routing"
    assert feature.description is None


def test_create_feature_with_description(db_session):
    """Creating a feature with a description should persist the description."""
    from src.mcp.tools.core.create_feature import handle

    asmt = _seed_assessment(db_session)
    result = handle(
        {
            "assessment_id": asmt.id,
            "name": "SLA Timers",
            "description": "All SLA-related customizations for task tables.",
        },
        db_session,
    )

    assert result["success"] is True
    feature = db_session.get(Feature, result["feature_id"])
    assert feature is not None
    assert feature.description == "All SLA-related customizations for task tables."


def test_create_feature_gets_color_index(db_session):
    """The color_index must be set to feature.id % 20 (range 0..19)."""
    from src.mcp.tools.core.create_feature import handle

    asmt = _seed_assessment(db_session)
    result = handle(
        {"assessment_id": asmt.id, "name": "Color Test Feature"},
        db_session,
    )

    assert result["success"] is True
    color_index = result["color_index"]
    assert 0 <= color_index < 20
    assert color_index == result["feature_id"] % 20

    feature = db_session.get(Feature, result["feature_id"])
    assert feature.color_index == color_index


def test_create_feature_invalid_assessment(db_session):
    """Passing a non-existent assessment_id should raise ValueError."""
    from src.mcp.tools.core.create_feature import handle

    with pytest.raises(ValueError, match="Assessment not found"):
        handle(
            {"assessment_id": 999999, "name": "Ghost Feature"},
            db_session,
        )
