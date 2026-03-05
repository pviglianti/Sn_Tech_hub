"""Tests for add_result_to_feature / remove_result_from_feature MCP tools."""

import pytest
from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


# ── Helpers ─────────────────────────────────────────────────────────

def _seed(db_session):
    """Create Instance -> Assessment -> Scan -> 2 ScanResults + Feature."""
    inst = Instance(
        name="mem-inst",
        url="https://mem-inst.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Membership Assessment",
        number="ASMT0099001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="meta scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()

    customized_result = ScanResult(
        scan_id=scan.id,
        sys_id="abc123",
        table_name="sys_script_include",
        name="CustomHelper",
        origin_type=OriginType.modified_ootb,
    )
    non_customized_result = ScanResult(
        scan_id=scan.id,
        sys_id="def456",
        table_name="sys_script_include",
        name="OotbHelper",
        origin_type=OriginType.ootb_untouched,
    )
    db_session.add(customized_result)
    db_session.add(non_customized_result)
    db_session.flush()

    feature = Feature(assessment_id=asmt.id, name="Custom Approval Flow")
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(customized_result)
    db_session.refresh(non_customized_result)
    db_session.refresh(feature)

    return feature, customized_result, non_customized_result


# ── Tests ───────────────────────────────────────────────────────────

def test_add_customized_result(db_session):
    """Adding a modified_ootb result creates a FeatureScanResult with source='ai'."""
    from src.mcp.tools.core.feature_membership import handle_add

    feature, cust_result, _ = _seed(db_session)

    result = handle_add(
        {"feature_id": feature.id, "scan_result_id": cust_result.id},
        db_session,
    )

    assert result["success"] is True
    assert "link_id" in result

    link = db_session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature.id,
            FeatureScanResult.scan_result_id == cust_result.id,
        )
    ).first()
    assert link is not None
    assert link.assignment_source == "ai"
    assert link.assignment_confidence == 1.0
    assert link.is_primary is True
    assert link.membership_type == "primary"


def test_reject_non_customized_result(db_session):
    """ootb_untouched result must be rejected with ValueError."""
    from src.mcp.tools.core.feature_membership import handle_add

    feature, _, non_cust_result = _seed(db_session)

    with pytest.raises(ValueError, match="not a customized record"):
        handle_add(
            {"feature_id": feature.id, "scan_result_id": non_cust_result.id},
            db_session,
        )


def test_add_idempotent(db_session):
    """Adding the same result twice creates only one FeatureScanResult link."""
    from src.mcp.tools.core.feature_membership import handle_add

    feature, cust_result, _ = _seed(db_session)

    first = handle_add(
        {"feature_id": feature.id, "scan_result_id": cust_result.id},
        db_session,
    )
    assert first["success"] is True
    assert "link_id" in first

    second = handle_add(
        {"feature_id": feature.id, "scan_result_id": cust_result.id},
        db_session,
    )
    assert second["success"] is True
    assert "already" in second["message"]

    count = len(
        db_session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.feature_id == feature.id,
                FeatureScanResult.scan_result_id == cust_result.id,
            )
        ).all()
    )
    assert count == 1


def test_remove_result(db_session):
    """Removing an existing membership deletes the link."""
    from src.mcp.tools.core.feature_membership import handle_add, handle_remove

    feature, cust_result, _ = _seed(db_session)

    handle_add(
        {"feature_id": feature.id, "scan_result_id": cust_result.id},
        db_session,
    )

    result = handle_remove(
        {"feature_id": feature.id, "scan_result_id": cust_result.id},
        db_session,
    )
    assert result["success"] is True
    assert "Removed" in result["message"]

    link = db_session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature.id,
            FeatureScanResult.scan_result_id == cust_result.id,
        )
    ).first()
    assert link is None


def test_remove_nonexistent(db_session):
    """Removing a non-existent membership returns success (idempotent)."""
    from src.mcp.tools.core.feature_membership import handle_remove

    feature, cust_result, _ = _seed(db_session)

    result = handle_remove(
        {"feature_id": feature.id, "scan_result_id": cust_result.id},
        db_session,
    )
    assert result["success"] is True
    assert "No membership found" in result["message"]


def test_db_unique_constraint_rejects_duplicate(db_session):
    """DB-level UniqueConstraint prevents duplicate (feature_id, scan_result_id) pairs."""
    from sqlalchemy.exc import IntegrityError

    feature, cust_result, _ = _seed(db_session)

    link1 = FeatureScanResult(
        feature_id=feature.id,
        scan_result_id=cust_result.id,
        is_primary=True,
        assignment_source="ai",
    )
    db_session.add(link1)
    db_session.commit()

    link2 = FeatureScanResult(
        feature_id=feature.id,
        scan_result_id=cust_result.id,
        is_primary=True,
        assignment_source="engine",
    )
    db_session.add(link2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_registry_includes_membership_tools():
    """Both tools are registered in the global registry."""
    from src.mcp.registry import build_registry

    registry = build_registry()
    assert registry.has_tool("add_result_to_feature")
    assert registry.has_tool("remove_result_from_feature")
