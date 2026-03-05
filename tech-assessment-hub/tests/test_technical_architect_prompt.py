"""Tests for the technical_architect MCP prompt.

Covers Mode A (per-artifact review) and Mode B (assessment-wide roll-up),
BestPractice filtering by applies_to, inactive exclusion, and graceful
fallback without a DB session.
"""

import json

import pytest
from sqlmodel import Session

# Import registry first to avoid circular import when importing the prompt
# module directly (registry._populate_prompt_registry runs at module level).
import src.mcp.registry  # noqa: F401

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    BestPractice,
    BestPracticeCategory,
    GeneralRecommendation,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    Severity,
)


# ── Seed helpers ──────────────────────────────────────────────────────


def _seed_instance_and_assessment(session: Session):
    """Create Instance -> Assessment, return (instance, assessment)."""
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Test Assessment",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()
    return inst, asmt


def _seed_scan_result(session: Session, assessment_id: int, **overrides):
    """Create Scan -> ScanResult, return the ScanResult."""
    scan = Scan(
        assessment_id=assessment_id,
        scan_type=ScanType.metadata,
        name=overrides.pop("scan_name", "Test Scan"),
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    defaults = dict(
        scan_id=scan.id,
        sys_id="abc123",
        table_name="sys_script",
        name="BR - Test Rule",
        raw_data_json=json.dumps({"script": "var x = 1;\ngs.info(x);"}),
    )
    defaults.update(overrides)
    sr = ScanResult(**defaults)
    session.add(sr)
    session.flush()
    return sr


def _seed_best_practices(session: Session):
    """Seed several BestPractice rows with varying applies_to and is_active.

    Returns a dict of code -> BestPractice for easy assertion.
    """
    bps = [
        BestPractice(
            code="BP001",
            title="Avoid GlideRecord in Client Scripts",
            category=BestPracticeCategory.technical_client,
            severity="high",
            description="Client-side GR calls degrade performance.",
            applies_to="sys_script_client",
            is_active=True,
        ),
        BestPractice(
            code="BP002",
            title="Use current object in Business Rules",
            category=BestPracticeCategory.technical_server,
            severity="medium",
            description="Prefer current over GlideRecord queries.",
            applies_to="sys_script,sys_script_include",
            is_active=True,
        ),
        BestPractice(
            code="BP003",
            title="No hardcoded sys_ids",
            category=BestPracticeCategory.architecture,
            severity="high",
            description="Never hardcode sys_ids in scripts.",
            applies_to=None,  # Applies to ALL tables
            is_active=True,
        ),
        BestPractice(
            code="BP004",
            title="Deprecated API usage",
            category=BestPracticeCategory.upgradeability,
            severity="critical",
            description="Avoid using deprecated GlideAjax patterns.",
            applies_to="sys_script",
            is_active=False,  # INACTIVE — should be excluded
        ),
        BestPractice(
            code="BP005",
            title="ACL script guard best practice",
            category=BestPracticeCategory.security,
            severity="medium",
            description="ACL scripts should validate roles.",
            applies_to="sys_security_acl",
            is_active=True,
        ),
    ]
    session.add_all(bps)
    session.flush()
    return {bp.code: bp for bp in bps}


# ── Mode A Tests ──────────────────────────────────────────────────────


class TestModeA:
    """Mode A: per-artifact technical review (result_id provided)."""

    def test_mode_a_returns_artifact_context_and_checklist(self, db_session):
        """Mode A returns messages with artifact context + BestPractice checklist."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        sr = _seed_scan_result(db_session, asmt.id, table_name="sys_script")
        _seed_best_practices(db_session)
        db_session.commit()

        result = _technical_architect_handler(
            {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
            session=db_session,
        )

        assert "messages" in result
        text = result["messages"][0]["content"]["text"]

        # Should contain artifact metadata
        assert "BR - Test Rule" in text
        assert "sys_script" in text

        # Should contain code snippet
        assert "var x = 1" in text

        # Should contain applicable BestPractice items
        assert "BP002" in text  # applies_to includes sys_script
        assert "BP003" in text  # applies_to is NULL (all)

        # Should contain output structure markers
        assert "Code Quality" in text
        assert "Disposition" in text

    def test_mode_a_filters_best_practice_by_applies_to(self, db_session):
        """Mode A filters BestPractice by applies_to matching table_name."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        sr = _seed_scan_result(db_session, asmt.id, table_name="sys_script")
        _seed_best_practices(db_session)
        db_session.commit()

        result = _technical_architect_handler(
            {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
            session=db_session,
        )
        text = result["messages"][0]["content"]["text"]

        # BP001 applies_to sys_script_client only — should NOT appear
        assert "BP001" not in text

        # BP002 applies_to sys_script,sys_script_include — SHOULD appear
        assert "BP002" in text

        # BP003 applies_to None (all) — SHOULD appear
        assert "BP003" in text

        # BP005 applies_to sys_security_acl — should NOT appear
        assert "BP005" not in text

    def test_mode_a_excludes_inactive_best_practices(self, db_session):
        """Mode A excludes inactive BestPractice records."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        sr = _seed_scan_result(db_session, asmt.id, table_name="sys_script")
        _seed_best_practices(db_session)
        db_session.commit()

        result = _technical_architect_handler(
            {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
            session=db_session,
        )
        text = result["messages"][0]["content"]["text"]

        # BP004 is inactive — should NOT appear even though applies_to=sys_script
        assert "BP004" not in text

    def test_mode_a_raises_for_invalid_result_id(self, db_session):
        """Raises ValueError for missing/invalid result_id in Mode A."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        db_session.commit()

        with pytest.raises(ValueError, match="ScanResult not found"):
            _technical_architect_handler(
                {"result_id": "999999", "assessment_id": str(asmt.id)},
                session=db_session,
            )

    def test_mode_a_raises_for_non_numeric_result_id(self, db_session):
        """Raises ValueError for non-numeric result_id."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        with pytest.raises(ValueError, match="ScanResult not found"):
            _technical_architect_handler(
                {"result_id": "not-a-number", "assessment_id": "1"},
                session=db_session,
            )

    def test_mode_a_includes_observations(self, db_session):
        """Mode A includes existing observations in context."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        sr = _seed_scan_result(
            db_session,
            asmt.id,
            table_name="sys_script",
            observations="Uses deprecated API pattern.",
        )
        _seed_best_practices(db_session)
        db_session.commit()

        result = _technical_architect_handler(
            {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
            session=db_session,
        )
        text = result["messages"][0]["content"]["text"]
        assert "Uses deprecated API pattern" in text


# ── Mode B Tests ──────────────────────────────────────────────────────


class TestModeB:
    """Mode B: assessment-wide technical debt roll-up (no result_id)."""

    def test_mode_b_returns_assessment_wide_summary(self, db_session):
        """Mode B returns assessment-wide summary context."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        # Create several scan results to aggregate
        _seed_scan_result(
            db_session, asmt.id,
            sys_id="s1", table_name="sys_script", name="BR1",
        )
        _seed_scan_result(
            db_session, asmt.id,
            sys_id="s2", table_name="sys_script_include", name="SI1",
            scan_name="Scan 2",
        )
        _seed_scan_result(
            db_session, asmt.id,
            sys_id="s3", table_name="sys_script_client", name="CS1",
            scan_name="Scan 3",
        )
        _seed_best_practices(db_session)
        db_session.commit()

        result = _technical_architect_handler(
            {"assessment_id": str(asmt.id)},
            session=db_session,
        )

        assert "messages" in result
        text = result["messages"][0]["content"]["text"]

        # Should mention assessment number
        assert "ASMT0001" in text

        # Should contain aggregate counts
        assert "sys_script" in text

        # Should contain output structure markers for Mode B
        assert "Assessment-Wide" in text

    def test_mode_b_includes_all_active_best_practices(self, db_session):
        """Mode B includes ALL active BestPractice records (not filtered by applies_to)."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        _seed_scan_result(db_session, asmt.id)
        bps = _seed_best_practices(db_session)
        db_session.commit()

        result = _technical_architect_handler(
            {"assessment_id": str(asmt.id)},
            session=db_session,
        )
        text = result["messages"][0]["content"]["text"]

        # ALL active BPs should appear (BP001, BP002, BP003, BP005)
        assert "BP001" in text
        assert "BP002" in text
        assert "BP003" in text
        assert "BP005" in text

        # BP004 is inactive — should NOT appear
        assert "BP004" not in text

    def test_mode_b_includes_general_recommendations(self, db_session):
        """Mode B includes GeneralRecommendation landscape context."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        _, asmt = _seed_instance_and_assessment(db_session)
        _seed_scan_result(db_session, asmt.id)
        _seed_best_practices(db_session)

        rec = GeneralRecommendation(
            assessment_id=asmt.id,
            title="Reduce script include sprawl",
            description="Too many small script includes.",
            category="architecture",
            severity=Severity.medium,
        )
        db_session.add(rec)
        db_session.commit()

        result = _technical_architect_handler(
            {"assessment_id": str(asmt.id)},
            session=db_session,
        )
        text = result["messages"][0]["content"]["text"]
        assert "Reduce script include sprawl" in text


# ── Graceful Fallback Tests ──────────────────────────────────────────


class TestGracefulFallback:
    """Tests for session=None fallback behavior."""

    def test_graceful_fallback_without_session(self):
        """Returns static prompt text when session is None."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        result = _technical_architect_handler(
            {"result_id": "42", "assessment_id": "7"},
            session=None,
        )

        assert "messages" in result
        text = result["messages"][0]["content"]["text"]
        assert "No database session available" in text
        assert "42" in text
        assert "7" in text

    def test_graceful_fallback_mode_b_without_session(self):
        """Mode B fallback without session also works."""
        from src.mcp.prompts.technical_architect import _technical_architect_handler

        result = _technical_architect_handler(
            {"assessment_id": "7"},
            session=None,
        )

        assert "messages" in result
        text = result["messages"][0]["content"]["text"]
        assert "No database session available" in text


# ── Registration Tests ────────────────────────────────────────────────


class TestRegistration:
    """Tests for PROMPT_SPECS registration."""

    def test_prompt_specs_list_not_empty(self):
        """PROMPT_SPECS contains at least one PromptSpec."""
        from src.mcp.prompts.technical_architect import PROMPT_SPECS

        assert len(PROMPT_SPECS) >= 1

    def test_prompt_spec_has_correct_name(self):
        """The prompt is named 'technical_architect'."""
        from src.mcp.prompts.technical_architect import PROMPT_SPECS

        names = [s.name for s in PROMPT_SPECS]
        assert "technical_architect" in names

    def test_prompt_registered_in_registry(self):
        """The prompt is registered in PROMPT_REGISTRY."""
        from src.mcp.registry import PROMPT_REGISTRY

        assert PROMPT_REGISTRY.has_prompt("technical_architect")
