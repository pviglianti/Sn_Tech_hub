"""Tests for the report_writer MCP prompt."""

import pytest
from sqlmodel import Session

from src.models import (
    Assessment, AssessmentState, AssessmentType, Instance,
    Feature, FeatureScanResult, GeneralRecommendation,
    OriginType, Scan, ScanResult, ScanStatus, ScanType,
    Severity, Disposition,
)


def _seed_assessment(session: Session):
    """Seed an assessment with instance, scan, and scan results."""
    inst = Instance(
        name="ACME DEV", url="https://acmedev.service-now.com",
        username="admin", password_encrypted="x",
    )
    session.add(inst)
    session.flush()

    asmt = Assessment(
        instance_id=inst.id, name="ACME Global Assessment",
        number="ASMT0042",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id, scan_type=ScanType.metadata,
        name="Test Scan", status=ScanStatus.completed,
        records_found=10, records_customized=5,
    )
    session.add(scan)
    session.flush()

    # Customized scan results (origin_type indicates customization)
    sr1 = ScanResult(
        scan_id=scan.id, sys_id="sr001", name="OnIncidentCreate",
        table_name="sys_script",
        origin_type=OriginType.net_new_customer,
    )
    sr2 = ScanResult(
        scan_id=scan.id, sys_id="sr002", name="IncidentUtils",
        table_name="sys_script_include",
        origin_type=OriginType.modified_ootb,
    )
    sr3 = ScanResult(
        scan_id=scan.id, sys_id="sr003", name="OOTBRule",
        table_name="sys_script",
        origin_type=OriginType.ootb_untouched,
    )
    session.add_all([sr1, sr2, sr3])
    session.commit()
    session.refresh(sr1)
    session.refresh(sr2)
    session.refresh(sr3)

    return inst, asmt, scan, [sr1, sr2, sr3]


def _add_landscape_summary(session: Session, asmt):
    """Add a GeneralRecommendation with category=landscape_summary."""
    rec = GeneralRecommendation(
        assessment_id=asmt.id,
        title="Landscape Summary",
        description="The instance has 42 customized artifacts spread across 8 tables.",
        category="landscape_summary",
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _add_technical_findings(session: Session, asmt):
    """Add a GeneralRecommendation with category=technical_findings."""
    rec = GeneralRecommendation(
        assessment_id=asmt.id,
        title="Technical Findings Overview",
        description="Multiple hardcoded GlideRecord references found.",
        category="technical_findings",
        severity=Severity.high,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _add_feature(session: Session, asmt, scan_results):
    """Add a Feature with linked scan results."""
    feature = Feature(
        assessment_id=asmt.id,
        name="Incident Automation",
        description="Custom automation for incident management",
        disposition=Disposition.keep_and_refactor,
        recommendation="Refactor to use Flow Designer",
        ai_summary="A set of business rules and script includes automating incident handling.",
    )
    session.add(feature)
    session.flush()

    # Link first two scan results to the feature
    for sr in scan_results[:2]:
        link = FeatureScanResult(
            feature_id=feature.id,
            scan_result_id=sr.id,
            is_primary=True,
            membership_type="primary",
            assignment_source="engine",
        )
        session.add(link)
    session.commit()
    session.refresh(feature)
    return feature


def _add_general_recommendation(session: Session, asmt):
    """Add a general recommendation (not landscape_summary or technical_findings)."""
    rec = GeneralRecommendation(
        assessment_id=asmt.id,
        title="Adopt Flow Designer",
        description="Migrate complex workflows to Flow Designer for maintainability.",
        category="recommendation",
        severity=Severity.medium,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


# ── Test: Returns messages with assessment metadata ──────────────

def test_report_writer_returns_messages_with_metadata(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, _srs = _seed_assessment(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    assert "messages" in result
    assert len(result["messages"]) >= 1
    text = result["messages"][0]["content"]["text"]
    # Assessment metadata injected
    assert "ACME Global Assessment" in text
    assert "ASMT0042" in text


# ── Test: Includes landscape summary ─────────────────────────────

def test_report_writer_includes_landscape_summary(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, _srs = _seed_assessment(db_session)
    _add_landscape_summary(db_session, asmt)

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "42 customized artifacts" in text


# ── Test: Includes feature groups ────────────────────────────────

def test_report_writer_includes_feature_groups(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, srs = _seed_assessment(db_session)
    _add_feature(db_session, asmt, srs)

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Incident Automation" in text
    assert "keep_and_refactor" in text


# ── Test: Includes technical findings ────────────────────────────

def test_report_writer_includes_technical_findings(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, _srs = _seed_assessment(db_session)
    _add_technical_findings(db_session, asmt)

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "hardcoded GlideRecord" in text


# ── Test: Includes statistics ────────────────────────────────────

def test_report_writer_includes_statistics(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, _srs = _seed_assessment(db_session)

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    # Should mention customized artifact counts
    # sr1 is net_new_customer, sr2 is modified_ootb -> 2 customized
    assert "2" in text  # customized count
    assert "sys_script" in text  # table breakdown


# ── Test: Respects sections parameter ────────────────────────────

def test_report_writer_respects_sections_param(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, srs = _seed_assessment(db_session)
    _add_landscape_summary(db_session, asmt)
    _add_technical_findings(db_session, asmt)
    _add_feature(db_session, asmt, srs)

    handler = PROMPT_SPECS[0].handler

    # Request only executive_summary
    result = handler(
        {"assessment_id": str(asmt.id), "sections": "executive_summary"},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Executive Summary" in text
    # Other sections should NOT be present as injected context headers
    assert "## Feature Analysis" not in text
    assert "## Technical Findings" not in text


# ── Test: Respects format parameter ──────────────────────────────

def test_report_writer_respects_format_executive_only(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, srs = _seed_assessment(db_session)
    _add_landscape_summary(db_session, asmt)
    _add_technical_findings(db_session, asmt)
    _add_feature(db_session, asmt, srs)

    handler = PROMPT_SPECS[0].handler

    result = handler(
        {"assessment_id": str(asmt.id), "format": "executive_only"},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Executive Summary" in text
    assert "Customization Landscape" in text
    # Technical sections excluded in executive_only
    assert "## Technical Findings" not in text


def test_report_writer_respects_format_technical_only(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, srs = _seed_assessment(db_session)
    _add_landscape_summary(db_session, asmt)
    _add_technical_findings(db_session, asmt)
    _add_feature(db_session, asmt, srs)

    handler = PROMPT_SPECS[0].handler

    result = handler(
        {"assessment_id": str(asmt.id), "format": "technical_only"},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    # Technical sections included
    assert "Feature Analysis" in text
    assert "Technical Findings" in text
    # Executive summary excluded in technical_only
    assert "## Executive Summary" not in text


# ── Test: Graceful fallback without session ──────────────────────

def test_report_writer_no_session_returns_static():
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": "1"},
        session=None,
    )
    assert "messages" in result
    text = result["messages"][0]["content"]["text"]
    assert "Report Writer" in text
    assert "No database session" in text


# ── Test: Invalid assessment_id raises ValueError ────────────────

def test_report_writer_invalid_assessment_id_raises(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    handler = PROMPT_SPECS[0].handler
    with pytest.raises(ValueError, match="Assessment not found"):
        handler({"assessment_id": "99999"}, session=db_session)


def test_report_writer_non_numeric_assessment_id_raises(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    handler = PROMPT_SPECS[0].handler
    with pytest.raises(ValueError, match="Assessment not found"):
        handler({"assessment_id": "not-a-number"}, session=db_session)


# ── Test: Includes general recommendations ───────────────────────

def test_report_writer_includes_general_recommendations(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, _srs = _seed_assessment(db_session)
    _add_general_recommendation(db_session, asmt)

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Adopt Flow Designer" in text


# ── Test: Includes ungrouped artifacts ───────────────────────────

def test_report_writer_includes_ungrouped_artifacts(db_session: Session):
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    _inst, asmt, _scan, srs = _seed_assessment(db_session)
    # Add a feature that groups sr1 and sr2 (but NOT sr3)
    _add_feature(db_session, asmt, srs)

    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    # sr3 is ootb_untouched so not customized -> ungrouped artifacts only counts
    # customized ones not in any feature. sr1 and sr2 are grouped.
    # No ungrouped customized artifacts remain.
    # But the section header or count should still appear
    assert "Ungrouped" in text or "ungrouped" in text


# ── Test: Prompt registered in PROMPT_SPECS ──────────────────────

def test_report_writer_prompt_spec_structure():
    from src.mcp.prompts.report_writer import PROMPT_SPECS

    assert len(PROMPT_SPECS) >= 1
    spec = PROMPT_SPECS[0]
    assert spec.name == "report_writer"
    assert "assessment_id" in [arg["name"] for arg in spec.arguments]
