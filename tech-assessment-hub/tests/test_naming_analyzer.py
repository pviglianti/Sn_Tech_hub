"""Tests for the Naming Analyzer engine (Engine 3).

Validates prefix-based naming cluster detection across ScanResults.
"""

import json

import pytest
from sqlmodel import select

from src.engines.naming_analyzer import run, _tokenize, _build_prefix_clusters
from src.models import (
    AppConfig,
    Instance,
    Assessment,
    AssessmentState,
    AssessmentType,
    Scan,
    ScanType,
    ScanStatus,
    ScanResult,
    NamingCluster,
)
from src.services.integration_properties import REASONING_NAMING_MIN_PREFIX_TOKENS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_base(session):
    """Create Instance + Assessment + Scan scaffolding."""
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
        name="Test",
        number="ASMT0001",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
    )
    session.add(asmt)
    session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="test scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()

    return inst, asmt, scan


def _add_scan_result(session, scan, name, table_name="sys_script_include", sys_id=None):
    """Add a single ScanResult with the given name."""
    import uuid

    sr = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id or str(uuid.uuid4().hex[:32]),
        table_name=table_name,
        name=name,
    )
    session.add(sr)
    session.flush()
    return sr


# ---------------------------------------------------------------------------
# Unit tests for _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_space_delimited(self):
        assert _tokenize("RITM Approval Check") == ["RITM", "Approval", "Check"]

    def test_hyphen_delimited(self):
        assert _tokenize("RITM-Approval-Check") == ["RITM", "Approval", "Check"]

    def test_underscore_delimited(self):
        assert _tokenize("RITM_Approval_Check") == ["RITM", "Approval", "Check"]

    def test_dot_delimited(self):
        assert _tokenize("RITM.Approval.Check") == ["RITM", "Approval", "Check"]

    def test_servicenow_dash_convention(self):
        """ServiceNow uses ' - ' (space-dash-space) as a common separator."""
        assert _tokenize("RITM Approval - Check Status") == [
            "RITM", "Approval", "Check", "Status"
        ]

    def test_mixed_delimiters(self):
        assert _tokenize("RITM_Approval - Check.Status") == [
            "RITM", "Approval", "Check", "Status"
        ]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_single_token(self):
        assert _tokenize("RITM") == ["RITM"]


# ---------------------------------------------------------------------------
# Integration tests using db_session
# ---------------------------------------------------------------------------

class TestNamingAnalyzerBasicPrefix:
    """3 records sharing 'RITM Approval' prefix should produce 1 cluster."""

    def test_naming_analyzer_basic_prefix(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        _add_scan_result(db_session, scan, "RITM Approval - Check Status")
        _add_scan_result(db_session, scan, "RITM Approval - Send Notification")
        _add_scan_result(db_session, scan, "RITM Approval - Validate Form")

        result = run(asmt.id, db_session)

        assert result["success"] is True
        assert result["clusters_created"] >= 1
        assert result["errors"] == []

        clusters = list(
            db_session.exec(
                select(NamingCluster).where(
                    NamingCluster.assessment_id == asmt.id
                )
            ).all()
        )

        # There should be at least one cluster with label containing "RITM Approval"
        labels = [c.cluster_label for c in clusters]
        assert any("RITM" in lbl and "Approval" in lbl for lbl in labels), (
            f"Expected a cluster containing 'RITM Approval', got: {labels}"
        )

        # Check cluster properties
        for c in clusters:
            assert c.pattern_type == "prefix"
            assert c.confidence == 1.0
            assert c.member_count >= 2
            member_ids = json.loads(c.member_ids_json)
            assert len(member_ids) == c.member_count
            tables = json.loads(c.tables_involved_json)
            assert isinstance(tables, list)


class TestNamingAnalyzerNoCommonPrefix:
    """Records with completely different names should produce 0 clusters."""

    def test_naming_analyzer_no_common_prefix(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        _add_scan_result(db_session, scan, "Alpha Beta Gamma")
        _add_scan_result(db_session, scan, "Delta Epsilon Zeta")
        _add_scan_result(db_session, scan, "Eta Theta Iota")

        result = run(asmt.id, db_session)

        assert result["success"] is True
        assert result["clusters_created"] == 0
        assert result["errors"] == []


class TestNamingAnalyzerMultipleClusters:
    """Two groups of records with different prefixes should produce 2 clusters."""

    def test_naming_analyzer_multiple_clusters(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        # Group 1: "Incident Auto" prefix
        _add_scan_result(db_session, scan, "Incident Auto Assignment Rule")
        _add_scan_result(db_session, scan, "Incident Auto Close Handler")

        # Group 2: "Change Request" prefix
        _add_scan_result(db_session, scan, "Change Request Approval Flow")
        _add_scan_result(db_session, scan, "Change Request Validation Script")

        # Unrelated (no group)
        _add_scan_result(db_session, scan, "Catalog Item Setup Wizard")

        result = run(asmt.id, db_session)

        assert result["success"] is True
        assert result["clusters_created"] == 2
        assert result["errors"] == []

        clusters = list(
            db_session.exec(
                select(NamingCluster).where(
                    NamingCluster.assessment_id == asmt.id
                )
            ).all()
        )

        labels = sorted([c.cluster_label for c in clusters])
        assert len(labels) == 2
        assert any("Incident" in lbl and "Auto" in lbl for lbl in labels)
        assert any("Change" in lbl and "Request" in lbl for lbl in labels)


class TestNamingAnalyzerIdempotent:
    """Running the engine twice should produce the same result count."""

    def test_naming_analyzer_idempotent(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        _add_scan_result(db_session, scan, "RITM Approval - Check Status")
        _add_scan_result(db_session, scan, "RITM Approval - Send Notification")
        _add_scan_result(db_session, scan, "RITM Approval - Validate Form")

        result1 = run(asmt.id, db_session)
        count1 = result1["clusters_created"]

        result2 = run(asmt.id, db_session)
        count2 = result2["clusters_created"]

        assert count1 == count2
        assert result2["success"] is True

        # Only one set of clusters should exist (old ones deleted)
        clusters = list(
            db_session.exec(
                select(NamingCluster).where(
                    NamingCluster.assessment_id == asmt.id
                )
            ).all()
        )
        assert len(clusters) == count2


class TestNamingAnalyzerAssessmentNotFound:
    """Running with a non-existent assessment_id returns an error."""

    def test_assessment_not_found(self, db_session):
        result = run(999999, db_session)
        assert result["success"] is False
        assert "Assessment not found" in result["errors"][0]


class TestNamingAnalyzerNoScanResults:
    """Assessment with no scan results returns success with 0 clusters."""

    def test_no_scan_results(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        result = run(asmt.id, db_session)
        assert result["success"] is True
        assert result["clusters_created"] == 0


class TestNamingAnalyzerLongestPrefixPreferred:
    """When a longer prefix qualifies, it is preferred over a shorter one."""

    def test_longest_prefix_preferred(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        # All share "RITM Approval" (2 tokens), but only 2 share
        # "RITM Approval Check" (3 tokens).
        _add_scan_result(db_session, scan, "RITM Approval Check Status Alpha")
        _add_scan_result(db_session, scan, "RITM Approval Check Status Beta")
        _add_scan_result(db_session, scan, "RITM Approval Send Notification Extra")

        result = run(asmt.id, db_session)
        assert result["success"] is True

        clusters = list(
            db_session.exec(
                select(NamingCluster).where(
                    NamingCluster.assessment_id == asmt.id
                )
            ).all()
        )

        # The two "RITM Approval Check Status" items should cluster at
        # their longest shared prefix "RITM Approval Check Status" (4 tokens).
        # The remaining "RITM Approval Send Notification Extra" is alone, so
        # the short "RITM Approval" prefix should NOT form a competing cluster
        # of size 3 (because the 2 long-prefix members are claimed).
        # The remaining single member doesn't meet min_cluster_size=2.
        labels = [c.cluster_label for c in clusters]
        assert any("Check" in lbl and "Status" in lbl for lbl in labels), (
            f"Expected longest prefix cluster, got: {labels}"
        )


class TestNamingAnalyzerTablesInvolved:
    """Clusters should track distinct table_names of their members."""

    def test_tables_involved(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        _add_scan_result(
            db_session, scan, "RITM Approval - Check Status",
            table_name="sys_script_include",
        )
        _add_scan_result(
            db_session, scan, "RITM Approval - Send Notification",
            table_name="sys_script",
        )

        result = run(asmt.id, db_session)
        assert result["success"] is True

        clusters = list(
            db_session.exec(
                select(NamingCluster).where(
                    NamingCluster.assessment_id == asmt.id
                )
            ).all()
        )

        assert len(clusters) >= 1
        for c in clusters:
            tables = json.loads(c.tables_involved_json)
            assert "sys_script_include" in tables or "sys_script" in tables


class TestNamingAnalyzerInstanceScopedProperties:
    """Instance-specific naming properties should override global/default values."""

    def test_instance_scoped_min_prefix_tokens(self, db_session):
        inst, asmt, scan = _setup_base(db_session)

        db_session.add(
            AppConfig(
                instance_id=None,
                key=REASONING_NAMING_MIN_PREFIX_TOKENS,
                value="2",
                description="Global naming prefix tokens",
            )
        )
        db_session.add(
            AppConfig(
                instance_id=inst.id,
                key=REASONING_NAMING_MIN_PREFIX_TOKENS,
                value="3",
                description="Instance naming prefix tokens",
            )
        )

        _add_scan_result(db_session, scan, "Incident Auto Assignment")
        _add_scan_result(db_session, scan, "Incident Auto Closure")

        result = run(asmt.id, db_session)
        assert result["success"] is True
        # Shared prefix is only 2 tokens ("Incident Auto"), so instance override
        # of 3 should suppress cluster creation.
        assert result["clusters_created"] == 0
