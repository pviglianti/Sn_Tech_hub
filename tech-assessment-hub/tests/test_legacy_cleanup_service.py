"""Unit tests for LegacyCleanupService (Phase 11C — C3).

These tests define the contract that W1 must implement.
All tests use in-memory SQLite with seeded fixture data.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Customization,
    Feature,
    FeatureScanResult,
    Instance,
    OriginType,
    PipelineStage,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)

# W1 creates this module — tests will fail with ImportError until W1 delivers.
from src.services.legacy_cleanup_service import (
    CleanupReport,
    DedupResult,
    FeatureResult,
    LegacyCleanupService,
    MembershipResult,
    PreflightResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instance(session: Session) -> Instance:
    inst = Instance(
        name="test",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="x",
    )
    session.add(inst)
    session.flush()
    return inst


def _make_assessment(
    session: Session,
    instance: Instance,
    *,
    number: str = "ASMT0001",
    pipeline_stage: PipelineStage = PipelineStage.scans,
) -> Assessment:
    asmt = Assessment(
        instance_id=instance.id,
        name="Test Assessment",
        number=number,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
        pipeline_stage=pipeline_stage,
    )
    session.add(asmt)
    session.flush()
    return asmt


def _make_scan(session: Session, assessment: Assessment) -> Scan:
    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="test scan",
        status=ScanStatus.completed,
    )
    session.add(scan)
    session.flush()
    return scan


def _make_scan_result(
    session: Session,
    scan: Scan,
    *,
    sys_id: str = "aaa111",
    table_name: str = "sys_script",
    name: str = "BR - Test",
    origin_type: OriginType | None = None,
) -> ScanResult:
    sr = ScanResult(
        scan_id=scan.id,
        sys_id=sys_id,
        table_name=table_name,
        name=name,
        origin_type=origin_type,
    )
    session.add(sr)
    session.flush()
    return sr


def _make_feature(
    session: Session,
    assessment: Assessment,
    *,
    name: str = "Feature A",
) -> Feature:
    feat = Feature(assessment_id=assessment.id, name=name)
    session.add(feat)
    session.flush()
    return feat


def _make_fsr(
    session: Session,
    feature: Feature,
    scan_result: ScanResult,
    *,
    assignment_source: str = "engine",
) -> FeatureScanResult:
    fsr = FeatureScanResult(
        feature_id=feature.id,
        scan_result_id=scan_result.id,
        assignment_source=assignment_source,
    )
    session.add(fsr)
    session.flush()
    return fsr


def _make_customization(
    session: Session,
    scan_result: ScanResult,
    scan: Scan,
) -> Customization:
    cust = Customization(
        scan_result_id=scan_result.id,
        scan_id=scan.id,
        sys_id=scan_result.sys_id,
        table_name=scan_result.table_name,
        name=scan_result.name,
        origin_type=scan_result.origin_type,
    )
    session.add(cust)
    session.flush()
    return cust


def _seed_basic(session: Session):
    """Seed instance + assessment + scan. Returns (instance, assessment, scan)."""
    inst = _make_instance(session)
    asmt = _make_assessment(session, inst)
    scan = _make_scan(session, asmt)
    session.commit()
    return inst, asmt, scan


# ---------------------------------------------------------------------------
# 1. Pre-flight checks
# ---------------------------------------------------------------------------


class TestPreflightChecks:
    """Tests 1-4: Pre-flight safety checks."""

    def test_preflight_assessment_not_found(self, db_session):
        """#1: Returns safe_to_proceed=False when assessment_id doesn't exist."""
        svc = LegacyCleanupService(db_session, "ASMT_NONEXISTENT", dry_run=True)
        report = svc.run()

        assert report.preflight.assessment_exists is False
        assert report.preflight.safe_to_proceed is False
        assert report.success is False

    def test_preflight_active_pipeline_blocks(self, db_session):
        """#2: Returns safe_to_proceed=False when pipeline_stage is not scans/complete."""
        inst = _make_instance(db_session)
        asmt = _make_assessment(
            db_session, inst, pipeline_stage=PipelineStage.engines
        )
        _make_scan(db_session, asmt)
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=True)
        report = svc.run()

        assert report.preflight.assessment_exists is True
        assert report.preflight.safe_to_proceed is False
        assert report.preflight.abort_reason is not None
        assert "pipeline" in report.preflight.abort_reason.lower()

    def test_preflight_human_fsr_aborts(self, db_session):
        """#3: Returns safe_to_proceed=False when human FSR count > 0."""
        inst, asmt, scan = _seed_basic(db_session)
        sr = _make_scan_result(
            db_session, scan, origin_type=OriginType.modified_ootb
        )
        feat = _make_feature(db_session, asmt)
        _make_fsr(db_session, feat, sr, assignment_source="human")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=True)
        report = svc.run()

        assert report.preflight.human_fsr_count > 0
        assert report.preflight.safe_to_proceed is False
        assert report.preflight.abort_reason is not None
        assert "human" in report.preflight.abort_reason.lower()

    def test_preflight_clean_assessment(self, db_session):
        """#4: Returns correct counts for an assessment with known test data."""
        inst, asmt, scan = _seed_basic(db_session)
        # Two duplicates of the same artifact
        sr1 = _make_scan_result(
            db_session,
            scan,
            sys_id="dup1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr2 = _make_scan_result(
            db_session,
            scan,
            sys_id="dup1",
            table_name="sys_script",
            origin_type=OriginType.unknown_no_history,
        )
        # One non-customized
        sr3 = _make_scan_result(
            db_session,
            scan,
            sys_id="nc1",
            table_name="sys_script",
            origin_type=OriginType.ootb_untouched,
        )
        feat = _make_feature(db_session, asmt)
        _make_fsr(db_session, feat, sr1, assignment_source="engine")
        _make_fsr(db_session, feat, sr3, assignment_source="engine")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=True)
        report = svc.run()

        assert report.preflight.assessment_exists is True
        assert report.preflight.safe_to_proceed is True
        assert report.preflight.human_fsr_count == 0
        assert report.preflight.total_scan_results == 3
        assert report.preflight.duplicate_groups >= 1
        assert report.preflight.excess_rows >= 1
        assert report.preflight.non_customized_fsrs >= 1


# ---------------------------------------------------------------------------
# 5. Dry-run safety
# ---------------------------------------------------------------------------


class TestDryRunSafety:
    """Test 5: dry_run=True must never mutate the database."""

    def test_dryrun_no_mutations(self, db_session):
        """#5: After run() with dry_run=True, session has no pending changes;
        row counts unchanged."""
        inst, asmt, scan = _seed_basic(db_session)
        sr1 = _make_scan_result(
            db_session,
            scan,
            sys_id="dup1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr2 = _make_scan_result(
            db_session,
            scan,
            sys_id="dup1",
            table_name="sys_script",
            origin_type=None,
        )
        sr3 = _make_scan_result(
            db_session,
            scan,
            sys_id="nc1",
            table_name="sys_script_include",
            origin_type=OriginType.ootb_untouched,
        )
        feat = _make_feature(db_session, asmt)
        _make_fsr(db_session, feat, sr2, assignment_source="engine")
        _make_fsr(db_session, feat, sr3, assignment_source="engine")
        db_session.commit()

        # Capture counts before
        sr_count_before = len(db_session.exec(select(ScanResult)).all())
        fsr_count_before = len(db_session.exec(select(FeatureScanResult)).all())
        feat_count_before = len(db_session.exec(select(Feature)).all())

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=True)
        report = svc.run()

        # Verify no pending changes
        assert not db_session.dirty
        assert not db_session.new
        assert not db_session.deleted

        # Verify row counts unchanged
        sr_count_after = len(db_session.exec(select(ScanResult)).all())
        fsr_count_after = len(db_session.exec(select(FeatureScanResult)).all())
        feat_count_after = len(db_session.exec(select(Feature)).all())
        assert sr_count_after == sr_count_before
        assert fsr_count_after == fsr_count_before
        assert feat_count_after == feat_count_before

        assert report.dry_run is True
        assert report.success is True


# ---------------------------------------------------------------------------
# 6-10. Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Tests 6-10: Canonical selection, tie-breaking, and re-pointing."""

    def test_dedup_canonical_selection(self, db_session):
        """#6: Given 3 copies with different origin_types, keeps modified_ootb."""
        inst, asmt, scan = _seed_basic(db_session)
        sr_best = _make_scan_result(
            db_session,
            scan,
            sys_id="d1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr_mid = _make_scan_result(
            db_session,
            scan,
            sys_id="d1",
            table_name="sys_script",
            origin_type=OriginType.net_new_customer,
        )
        sr_worst = _make_scan_result(
            db_session,
            scan,
            sys_id="d1",
            table_name="sys_script",
            origin_type=OriginType.unknown_no_history,
        )
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.dedup is not None
        assert report.dedup.groups_processed >= 1
        assert report.dedup.rows_deleted == 2

        # Only sr_best survives
        remaining = db_session.exec(
            select(ScanResult).where(
                ScanResult.sys_id == "d1",
                ScanResult.table_name == "sys_script",
            )
        ).all()
        assert len(remaining) == 1
        assert remaining[0].id == sr_best.id

    def test_dedup_scan_id_tiebreak(self, db_session):
        """#7: Same origin_type — keeps highest scan_id."""
        inst = _make_instance(db_session)
        asmt = _make_assessment(db_session, inst)
        scan1 = _make_scan(db_session, asmt)
        scan2 = _make_scan(db_session, asmt)
        db_session.commit()

        sr_old = _make_scan_result(
            db_session,
            scan1,
            sys_id="d2",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr_new = _make_scan_result(
            db_session,
            scan2,
            sys_id="d2",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        remaining = db_session.exec(
            select(ScanResult).where(
                ScanResult.sys_id == "d2",
                ScanResult.table_name == "sys_script",
            )
        ).all()
        assert len(remaining) == 1
        # scan2 has higher id so sr_new should be kept
        assert remaining[0].scan_id == scan2.id

    def test_dedup_sr_id_tiebreak(self, db_session):
        """#8: Same origin_type and scan_id — keeps lowest sr.id."""
        inst, asmt, scan = _seed_basic(db_session)
        sr_first = _make_scan_result(
            db_session,
            scan,
            sys_id="d3",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr_second = _make_scan_result(
            db_session,
            scan,
            sys_id="d3",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        remaining = db_session.exec(
            select(ScanResult).where(
                ScanResult.sys_id == "d3",
                ScanResult.table_name == "sys_script",
            )
        ).all()
        assert len(remaining) == 1
        assert remaining[0].id == sr_first.id

    def test_dedup_repoints_fsr(self, db_session):
        """#9: After dedup, FSR rows point to canonical scan_result_id."""
        inst, asmt, scan = _seed_basic(db_session)
        sr_keep = _make_scan_result(
            db_session,
            scan,
            sys_id="d4",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr_drop = _make_scan_result(
            db_session,
            scan,
            sys_id="d4",
            table_name="sys_script",
            origin_type=None,
        )
        feat = _make_feature(db_session, asmt)
        fsr = _make_fsr(db_session, feat, sr_drop, assignment_source="engine")
        db_session.commit()

        fsr_id = fsr.id
        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.dedup.fsrs_repointed >= 1

        # FSR now points to canonical row
        updated_fsr = db_session.get(FeatureScanResult, fsr_id)
        assert updated_fsr is not None
        assert updated_fsr.scan_result_id == sr_keep.id

    def test_dedup_repoints_customizations(self, db_session):
        """#10: After dedup, customization child rows point to canonical scan_result_id."""
        inst, asmt, scan = _seed_basic(db_session)
        sr_keep = _make_scan_result(
            db_session,
            scan,
            sys_id="d5",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr_drop = _make_scan_result(
            db_session,
            scan,
            sys_id="d5",
            table_name="sys_script",
            origin_type=OriginType.net_new_customer,
        )
        cust = _make_customization(db_session, sr_drop, scan)
        db_session.commit()

        cust_id = cust.id
        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.dedup.customizations_repointed >= 1

        # Customization now points to canonical row
        updated_cust = db_session.get(Customization, cust_id)
        assert updated_cust is not None
        assert updated_cust.scan_result_id == sr_keep.id


# ---------------------------------------------------------------------------
# 11-13. Membership removal
# ---------------------------------------------------------------------------


class TestMembershipRemoval:
    """Tests 11-13: Non-customized membership cleanup."""

    def test_remove_non_customized_memberships(self, db_session):
        """#11: Deletes FSR rows with non-customized origin_type and non-human source."""
        inst, asmt, scan = _seed_basic(db_session)
        # Non-customized scan result
        sr_nc = _make_scan_result(
            db_session,
            scan,
            sys_id="nc1",
            table_name="sys_script",
            origin_type=OriginType.ootb_untouched,
        )
        feat = _make_feature(db_session, asmt)
        fsr = _make_fsr(db_session, feat, sr_nc, assignment_source="engine")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.membership is not None
        assert report.membership.fsrs_deleted >= 1

        # FSR should be gone
        remaining = db_session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.id == fsr.id
            )
        ).first()
        assert remaining is None

    def test_preserves_customized_memberships(self, db_session):
        """#12: FSR rows with modified_ootb/net_new_customer origin are kept."""
        inst, asmt, scan = _seed_basic(db_session)
        sr_mod = _make_scan_result(
            db_session,
            scan,
            sys_id="cust1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr_new = _make_scan_result(
            db_session,
            scan,
            sys_id="cust2",
            table_name="sys_script_include",
            origin_type=OriginType.net_new_customer,
        )
        feat = _make_feature(db_session, asmt)
        fsr1 = _make_fsr(db_session, feat, sr_mod, assignment_source="engine")
        fsr2 = _make_fsr(db_session, feat, sr_new, assignment_source="ai")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        # Both FSRs survive
        surviving = db_session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.feature_id == feat.id
            )
        ).all()
        assert len(surviving) == 2

    def test_preserves_human_authored_memberships(self, db_session):
        """#13: FSR rows with assignment_source='human' trigger abort.
        The preflight gate prevents any deletions when human FSRs exist."""
        inst, asmt, scan = _seed_basic(db_session)
        sr = _make_scan_result(
            db_session,
            scan,
            sys_id="h1",
            table_name="sys_script",
            origin_type=OriginType.ootb_untouched,
        )
        feat = _make_feature(db_session, asmt)
        _make_fsr(db_session, feat, sr, assignment_source="human")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        # Should abort in preflight — no mutations happen
        assert report.preflight.human_fsr_count == 1
        assert report.preflight.safe_to_proceed is False
        assert report.success is False

        # FSR is untouched
        surviving = db_session.exec(select(FeatureScanResult)).all()
        assert len(surviving) == 1


# ---------------------------------------------------------------------------
# 14-15. Feature deletion
# ---------------------------------------------------------------------------


class TestFeatureDeletion:
    """Tests 14-15: Empty feature cleanup."""

    def test_delete_empty_features(self, db_session):
        """#14: Features with zero FSR rows after cleanup are deleted."""
        inst, asmt, scan = _seed_basic(db_session)
        sr = _make_scan_result(
            db_session,
            scan,
            sys_id="e1",
            table_name="sys_script",
            origin_type=OriginType.ootb_untouched,
        )
        feat = _make_feature(db_session, asmt, name="Empty Feature")
        # Sole membership is non-customized — will be removed
        _make_fsr(db_session, feat, sr, assignment_source="engine")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.features is not None
        assert report.features.features_deleted >= 1

        # Feature should be gone
        remaining = db_session.exec(
            select(Feature).where(Feature.id == feat.id)
        ).first()
        assert remaining is None

    def test_preserves_features_with_members(self, db_session):
        """#15: Features with remaining customized FSR rows survive."""
        inst, asmt, scan = _seed_basic(db_session)
        sr = _make_scan_result(
            db_session,
            scan,
            sys_id="k1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        feat = _make_feature(db_session, asmt, name="Alive Feature")
        _make_fsr(db_session, feat, sr, assignment_source="engine")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        # Feature with customized member survives
        remaining = db_session.exec(
            select(Feature).where(Feature.id == feat.id)
        ).first()
        assert remaining is not None


# ---------------------------------------------------------------------------
# 16. Transaction rollback
# ---------------------------------------------------------------------------


class TestTransactionSafety:
    """Test 16: Apply mode transaction safety."""

    def test_apply_single_transaction_rollback(self, db_session, monkeypatch):
        """#16: Inject error mid-apply; verify full rollback (no partial state)."""
        inst, asmt, scan = _seed_basic(db_session)
        sr1 = _make_scan_result(
            db_session,
            scan,
            sys_id="r1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        sr2 = _make_scan_result(
            db_session,
            scan,
            sys_id="r1",
            table_name="sys_script",
            origin_type=None,
        )
        sr_nc = _make_scan_result(
            db_session,
            scan,
            sys_id="r2",
            table_name="sys_script_include",
            origin_type=OriginType.ootb_untouched,
        )
        feat = _make_feature(db_session, asmt)
        _make_fsr(db_session, feat, sr_nc, assignment_source="engine")
        db_session.commit()

        sr_count_before = len(db_session.exec(select(ScanResult)).all())
        fsr_count_before = len(db_session.exec(select(FeatureScanResult)).all())
        feat_count_before = len(db_session.exec(select(Feature)).all())

        # Inject error into membership removal step
        original_method = LegacyCleanupService._remove_non_customized_memberships

        def _boom(self_inner):
            raise RuntimeError("Injected error for rollback test")

        monkeypatch.setattr(
            LegacyCleanupService,
            "_remove_non_customized_memberships",
            _boom,
        )

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is False
        assert report.error is not None
        assert "Injected error" in report.error

        # Full rollback — no partial state
        sr_count_after = len(db_session.exec(select(ScanResult)).all())
        fsr_count_after = len(db_session.exec(select(FeatureScanResult)).all())
        feat_count_after = len(db_session.exec(select(Feature)).all())
        assert sr_count_after == sr_count_before
        assert fsr_count_after == fsr_count_before
        assert feat_count_after == feat_count_before


# ---------------------------------------------------------------------------
# 17. Full end-to-end apply
# ---------------------------------------------------------------------------


class TestFullEndToEnd:
    """Test 17: Realistic data, verify final state after apply."""

    def test_full_cleanup_apply_end_to_end(self, db_session):
        """#17: Seed realistic data (scaled down); verify final state."""
        inst, asmt, scan = _seed_basic(db_session)

        # --- Duplicates: 3 groups, 2 extras each = 6 excess rows ---
        canonical_srs = []
        for i in range(3):
            sr_keep = _make_scan_result(
                db_session,
                scan,
                sys_id=f"dup{i}",
                table_name="sys_script",
                origin_type=OriginType.modified_ootb,
            )
            canonical_srs.append(sr_keep)
            for j in range(2):
                _make_scan_result(
                    db_session,
                    scan,
                    sys_id=f"dup{i}",
                    table_name="sys_script",
                    origin_type=OriginType.unknown_no_history,
                    name=f"BR - dup{i} copy{j}",
                )

        # --- Non-customized results with FSR memberships ---
        nc_srs = []
        for i in range(5):
            nc = _make_scan_result(
                db_session,
                scan,
                sys_id=f"nc{i}",
                table_name="sys_ui_action",
                origin_type=OriginType.ootb_untouched,
            )
            nc_srs.append(nc)

        # --- Customized result (should survive) ---
        sr_custom = _make_scan_result(
            db_session,
            scan,
            sys_id="cust1",
            table_name="sys_script_include",
            origin_type=OriginType.modified_ootb,
        )

        # --- Features ---
        feat_alive = _make_feature(db_session, asmt, name="Alive Feature")
        _make_fsr(db_session, feat_alive, sr_custom, assignment_source="engine")
        _make_fsr(db_session, feat_alive, canonical_srs[0], assignment_source="ai")

        feat_dead = _make_feature(db_session, asmt, name="Dead Feature")
        for nc in nc_srs:
            _make_fsr(db_session, feat_dead, nc, assignment_source="engine")

        db_session.commit()

        # --- Run cleanup ---
        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.dry_run is False
        assert report.elapsed_seconds >= 0

        # Dedup: 3 groups, 6 excess rows deleted
        assert report.dedup.groups_processed == 3
        assert report.dedup.rows_deleted == 6

        # Memberships: 5 non-customized FSRs deleted
        assert report.membership.fsrs_deleted == 5

        # Features: dead feature deleted, alive survives
        assert report.features.features_deleted >= 1
        alive = db_session.exec(
            select(Feature).where(Feature.name == "Alive Feature")
        ).first()
        assert alive is not None
        dead = db_session.exec(
            select(Feature).where(Feature.name == "Dead Feature")
        ).first()
        assert dead is None


# ---------------------------------------------------------------------------
# 18. Report dataclass
# ---------------------------------------------------------------------------


class TestReportDataclass:
    """Test 18: CleanupReport has all expected fields."""

    def test_report_dataclass_fields(self):
        """#18: CleanupReport has all expected fields with correct types."""
        import dataclasses

        assert dataclasses.is_dataclass(CleanupReport)

        field_names = {f.name for f in dataclasses.fields(CleanupReport)}
        expected = {
            "assessment_id",
            "dry_run",
            "preflight",
            "dedup",
            "membership",
            "features",
            "success",
            "error",
            "elapsed_seconds",
        }
        assert expected.issubset(field_names), (
            f"Missing fields: {expected - field_names}"
        )

        # Sub-dataclasses
        assert dataclasses.is_dataclass(PreflightResult)
        assert dataclasses.is_dataclass(DedupResult)
        assert dataclasses.is_dataclass(MembershipResult)
        assert dataclasses.is_dataclass(FeatureResult)


# ---------------------------------------------------------------------------
# 19. No-op on clean assessment
# ---------------------------------------------------------------------------


class TestNoOp:
    """Test 19: Clean assessment produces zero-action report."""

    def test_no_duplicates_no_op(self, db_session):
        """#19: Clean assessment returns zero-action report."""
        inst, asmt, scan = _seed_basic(db_session)
        # Single unique scan result with customized origin
        sr = _make_scan_result(
            db_session,
            scan,
            sys_id="unique1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        feat = _make_feature(db_session, asmt)
        _make_fsr(db_session, feat, sr, assignment_source="engine")
        db_session.commit()

        svc = LegacyCleanupService(db_session, asmt.number, dry_run=False)
        report = svc.run()

        assert report.success is True
        assert report.dedup.groups_processed == 0
        assert report.dedup.rows_deleted == 0
        assert report.membership.fsrs_deleted == 0
        assert report.features.features_deleted == 0


# ---------------------------------------------------------------------------
# 20. Assessment scope isolation
# ---------------------------------------------------------------------------


class TestScopeIsolation:
    """Test 20: Cleanup on assessment 1 does not affect assessment 2."""

    def test_assessment_scope_isolation(self, db_session):
        """#20: Cleanup on assessment 1 does not touch assessment 2 data."""
        inst = _make_instance(db_session)

        # Assessment 1 — with duplicates and non-customized data
        asmt1 = _make_assessment(db_session, inst, number="ASMT0001")
        scan1 = _make_scan(db_session, asmt1)

        # Assessment 2 — similar data but should be untouched
        asmt2 = _make_assessment(db_session, inst, number="ASMT0002")
        scan2 = _make_scan(db_session, asmt2)
        db_session.commit()

        # Assessment 1: duplicates
        _make_scan_result(
            db_session,
            scan1,
            sys_id="iso1",
            table_name="sys_script",
            origin_type=OriginType.modified_ootb,
        )
        _make_scan_result(
            db_session,
            scan1,
            sys_id="iso1",
            table_name="sys_script",
            origin_type=None,
        )

        # Assessment 2: same sys_id/table_name but different assessment
        sr2_a = _make_scan_result(
            db_session,
            scan2,
            sys_id="iso1",
            table_name="sys_script",
            origin_type=OriginType.ootb_untouched,
        )
        sr2_b = _make_scan_result(
            db_session,
            scan2,
            sys_id="iso1",
            table_name="sys_script",
            origin_type=None,
        )
        feat2 = _make_feature(db_session, asmt2, name="A2 Feature")
        _make_fsr(db_session, feat2, sr2_a, assignment_source="engine")
        _make_fsr(db_session, feat2, sr2_b, assignment_source="engine")
        db_session.commit()

        # Snapshot assessment 2 counts
        a2_sr_before = len(
            db_session.exec(
                select(ScanResult).where(ScanResult.scan_id == scan2.id)
            ).all()
        )
        a2_fsr_before = len(
            db_session.exec(
                select(FeatureScanResult).where(
                    FeatureScanResult.feature_id == feat2.id
                )
            ).all()
        )
        a2_feat_before = len(
            db_session.exec(
                select(Feature).where(Feature.assessment_id == asmt2.id)
            ).all()
        )

        # Run cleanup on assessment 1 only
        svc = LegacyCleanupService(db_session, asmt1.number, dry_run=False)
        report = svc.run()
        assert report.success is True

        # Assessment 2 data unchanged
        a2_sr_after = len(
            db_session.exec(
                select(ScanResult).where(ScanResult.scan_id == scan2.id)
            ).all()
        )
        a2_fsr_after = len(
            db_session.exec(
                select(FeatureScanResult).where(
                    FeatureScanResult.feature_id == feat2.id
                )
            ).all()
        )
        a2_feat_after = len(
            db_session.exec(
                select(Feature).where(Feature.assessment_id == asmt2.id)
            ).all()
        )

        assert a2_sr_after == a2_sr_before
        assert a2_fsr_after == a2_fsr_before
        assert a2_feat_after == a2_feat_before
