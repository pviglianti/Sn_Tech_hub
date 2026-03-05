"""Legacy cleanup service for removing duplicate scan results,
non-customized feature memberships, and empty features.

Phase 11C — assessment-scoped cleanup with dry-run (default) and apply modes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func, text
from sqlmodel import Session, select

from ..models import (
    Assessment,
    Customization,
    Feature,
    FeatureScanResult,
    PipelineStage,
    Scan,
    ScanResult,
)

logger = logging.getLogger(__name__)

# Origin type priority for canonical row selection during dedup.
# Higher value = preferred as canonical.
_ORIGIN_PRIORITY = {
    "modified_ootb": 3,
    "net_new_customer": 2,
    "unknown_no_history": 1,
}
_ORIGIN_PRIORITY_DEFAULT = 0  # NULL or any unrecognized value

# Origin types that count as "customized"
_CUSTOMIZED_ORIGIN_TYPES = {"modified_ootb", "net_new_customer"}

# Pipeline stages where cleanup is safe to run
_SAFE_PIPELINE_STAGES = {PipelineStage.scans, PipelineStage.complete}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PreflightResult:
    assessment_exists: bool
    pipeline_stage: str
    safe_to_proceed: bool
    human_fsr_count: int
    total_scan_results: int
    duplicate_groups: int
    excess_rows: int
    non_customized_fsrs: int
    total_features: int
    customized_features: int
    abort_reason: Optional[str]


@dataclass
class DedupResult:
    groups_processed: int = 0
    rows_deleted: int = 0
    fsrs_repointed: int = 0
    customizations_repointed: int = 0


@dataclass
class MembershipResult:
    fsrs_deleted: int = 0


@dataclass
class FeatureResult:
    features_deleted: int = 0


@dataclass
class CleanupReport:
    assessment_id: str
    dry_run: bool
    preflight: PreflightResult
    dedup: Optional[DedupResult] = None
    membership: Optional[MembershipResult] = None
    features: Optional[FeatureResult] = None
    success: bool = False
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LegacyCleanupService:
    """Assessment-scoped cleanup of legacy/duplicate data.

    Modes:
      - dry_run=True  (default): read-only analysis, zero mutations.
      - dry_run=False (--apply): destructive cleanup within a single transaction.
    """

    def __init__(self, session: Session, assessment_id: str, dry_run: bool = True):
        self.session = session
        self.assessment_id = assessment_id
        self.dry_run = dry_run
        # Resolved during preflight
        self._assessment: Optional[Assessment] = None
        self._scan_ids: list[int] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> CleanupReport:
        """Execute the full cleanup pipeline and return a report."""
        t0 = time.monotonic()

        preflight = self._preflight_checks()
        report = CleanupReport(
            assessment_id=self.assessment_id,
            dry_run=self.dry_run,
            preflight=preflight,
        )

        if not preflight.safe_to_proceed:
            report.elapsed_seconds = time.monotonic() - t0
            report.success = False
            report.error = preflight.abort_reason
            return report

        if self.dry_run:
            # Dry-run: compute what *would* happen without mutating.
            report.dedup = self._deduplicate_scan_results()
            report.membership = self._remove_non_customized_memberships()
            report.features = self._delete_empty_features()
            report.success = True
            report.elapsed_seconds = time.monotonic() - t0
            return report

        # Apply mode — single transaction with rollback on error
        try:
            report.dedup = self._deduplicate_scan_results()
            report.membership = self._remove_non_customized_memberships()
            report.features = self._delete_empty_features()
            self.session.commit()
            report.success = True
        except Exception as exc:
            self.session.rollback()
            report.success = False
            report.error = str(exc)
            logger.exception("Cleanup apply failed for %s", self.assessment_id)
        finally:
            report.elapsed_seconds = time.monotonic() - t0

        return report

    # ------------------------------------------------------------------
    # Step 0: Pre-flight safety checks
    # ------------------------------------------------------------------

    def _preflight_checks(self) -> PreflightResult:
        assessment = self.session.exec(
            select(Assessment).where(Assessment.number == self.assessment_id)
        ).first()

        if assessment is None:
            return PreflightResult(
                assessment_exists=False,
                pipeline_stage="",
                safe_to_proceed=False,
                human_fsr_count=0,
                total_scan_results=0,
                duplicate_groups=0,
                excess_rows=0,
                non_customized_fsrs=0,
                total_features=0,
                customized_features=0,
                abort_reason=f"Assessment '{self.assessment_id}' not found.",
            )

        self._assessment = assessment

        # Gather scan IDs for this assessment
        self._scan_ids = list(
            self.session.exec(
                select(Scan.id).where(Scan.assessment_id == assessment.id)
            ).all()
        )

        # Pipeline stage check
        if assessment.pipeline_stage not in _SAFE_PIPELINE_STAGES:
            return self._build_preflight(
                assessment,
                safe=False,
                reason=(
                    f"Pipeline stage '{assessment.pipeline_stage.value}' is not safe "
                    f"for cleanup. Allowed stages: "
                    f"{', '.join(s.value for s in _SAFE_PIPELINE_STAGES)}."
                ),
            )

        # Human FSR gate — unconditional abort
        human_fsr_count = self._count_human_fsrs()
        if human_fsr_count > 0:
            result = self._build_preflight(
                assessment,
                safe=False,
                reason=(
                    f"Found {human_fsr_count} human-authored FSR row(s). "
                    "Cleanup aborted to preserve zero-loss guarantee."
                ),
            )
            result.human_fsr_count = human_fsr_count
            return result

        return self._build_preflight(assessment, safe=True, reason=None)

    def _build_preflight(
        self,
        assessment: Assessment,
        *,
        safe: bool,
        reason: Optional[str],
    ) -> PreflightResult:
        """Compute all preflight counts for a valid assessment."""
        dup_groups, excess_rows = self._count_duplicates()
        return PreflightResult(
            assessment_exists=True,
            pipeline_stage=assessment.pipeline_stage.value,
            safe_to_proceed=safe,
            human_fsr_count=self._count_human_fsrs(),
            total_scan_results=self._count_total_scan_results(),
            duplicate_groups=dup_groups,
            excess_rows=excess_rows,
            non_customized_fsrs=self._count_non_customized_fsrs(),
            total_features=self._count_features(),
            customized_features=self._count_customized_features(),
            abort_reason=reason,
        )

    # ------------------------------------------------------------------
    # Step 1: Deduplicate scan_result artifacts
    # ------------------------------------------------------------------

    def _deduplicate_scan_results(self) -> DedupResult:
        """Deduplicate scan_result rows by (table_name, sys_id) within assessment scans."""
        if not self._scan_ids:
            return DedupResult()

        # Find duplicate groups: same (table_name, sys_id) appearing in multiple scan_results
        # within this assessment's scans.
        dup_stmt = (
            select(ScanResult.table_name, ScanResult.sys_id)
            .where(ScanResult.scan_id.in_(self._scan_ids))  # type: ignore[union-attr]
            .group_by(ScanResult.table_name, ScanResult.sys_id)
            .having(func.count(ScanResult.id) > 1)
        )
        dup_groups = self.session.exec(dup_stmt).all()

        result = DedupResult()
        result.groups_processed = len(dup_groups)

        for table_name, sys_id in dup_groups:
            # Get all scan_result rows in this group
            rows = self.session.exec(
                select(ScanResult)
                .where(
                    ScanResult.scan_id.in_(self._scan_ids),  # type: ignore[union-attr]
                    ScanResult.table_name == table_name,
                    ScanResult.sys_id == sys_id,
                )
                .order_by(ScanResult.id)
            ).all()

            if len(rows) < 2:
                continue

            canonical = self._pick_canonical(rows)
            non_canonical = [r for r in rows if r.id != canonical.id]

            non_canonical_ids = [r.id for r in non_canonical]

            if self.dry_run:
                # Count what would be affected without mutating
                fsr_count = self.session.exec(
                    select(func.count(FeatureScanResult.id)).where(
                        FeatureScanResult.scan_result_id.in_(non_canonical_ids)  # type: ignore[union-attr]
                    )
                ).one()
                cust_count = self.session.exec(
                    select(func.count(Customization.id)).where(
                        Customization.scan_result_id.in_(non_canonical_ids)  # type: ignore[union-attr]
                    )
                ).one()
                result.rows_deleted += len(non_canonical_ids)
                result.fsrs_repointed += fsr_count
                result.customizations_repointed += cust_count
            else:
                # Re-point FSRs to canonical
                fsrs_to_repoint = self.session.exec(
                    select(FeatureScanResult).where(
                        FeatureScanResult.scan_result_id.in_(non_canonical_ids)  # type: ignore[union-attr]
                    )
                ).all()
                for fsr in fsrs_to_repoint:
                    # Check if canonical already has an FSR for this feature
                    existing = self.session.exec(
                        select(FeatureScanResult).where(
                            FeatureScanResult.feature_id == fsr.feature_id,
                            FeatureScanResult.scan_result_id == canonical.id,
                        )
                    ).first()
                    if existing:
                        # Duplicate link — delete the non-canonical one
                        self.session.delete(fsr)
                    else:
                        fsr.scan_result_id = canonical.id
                    result.fsrs_repointed += 1

                # Re-point customization child rows
                custs_to_repoint = self.session.exec(
                    select(Customization).where(
                        Customization.scan_result_id.in_(non_canonical_ids)  # type: ignore[union-attr]
                    )
                ).all()
                for cust in custs_to_repoint:
                    # Check if canonical already has a customization row
                    existing_cust = self.session.exec(
                        select(Customization).where(
                            Customization.scan_result_id == canonical.id,
                            Customization.id != cust.id,
                        )
                    ).first()
                    if existing_cust:
                        # Duplicate — delete the non-canonical one
                        self.session.delete(cust)
                    else:
                        # Keep relationship state consistent before deleting the
                        # non-canonical parent scan_result.
                        cust.scan_result_id = canonical.id
                        cust.scan_result = canonical
                    result.customizations_repointed += 1

                # Delete non-canonical scan_result rows
                for sr in non_canonical:
                    self.session.delete(sr)
                result.rows_deleted += len(non_canonical)

        return result

    @staticmethod
    def _pick_canonical(rows: list[ScanResult]) -> ScanResult:
        """Select the canonical row from a duplicate group.

        Priority: richest origin_type → highest scan_id → lowest sr.id.
        """

        def sort_key(sr: ScanResult) -> tuple[int, int, int]:
            origin_val = _ORIGIN_PRIORITY.get(
                sr.origin_type.value if sr.origin_type else "",
                _ORIGIN_PRIORITY_DEFAULT,
            )
            return (origin_val, sr.scan_id, -(sr.id or 0))

        return max(rows, key=sort_key)

    # ------------------------------------------------------------------
    # Step 2: Remove non-customized feature-scan-result memberships
    # ------------------------------------------------------------------

    def _remove_non_customized_memberships(self) -> MembershipResult:
        """Delete FSR rows whose scan_result is not customized and not human-authored."""
        if not self._scan_ids:
            return MembershipResult()

        # Find FSR rows to remove:
        # - The linked scan_result has origin_type NOT IN ('modified_ootb', 'net_new_customer') OR is NULL
        # - The FSR assignment_source is NOT 'human'
        # - Scoped to this assessment's features
        stmt = (
            select(FeatureScanResult)
            .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
            .join(Feature, FeatureScanResult.feature_id == Feature.id)
            .where(Feature.assessment_id == self._assessment.id)  # type: ignore[union-attr]
            .where(
                (ScanResult.origin_type.notin_(_CUSTOMIZED_ORIGIN_TYPES))  # type: ignore[union-attr]
                | (ScanResult.origin_type.is_(None))  # type: ignore[union-attr]
            )
            .where(
                (FeatureScanResult.assignment_source != "human")
                | (FeatureScanResult.assignment_source.is_(None))  # type: ignore[union-attr]
            )
        )

        if self.dry_run:
            # Count only
            count_stmt = (
                select(func.count(FeatureScanResult.id))
                .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
                .join(Feature, FeatureScanResult.feature_id == Feature.id)
                .where(Feature.assessment_id == self._assessment.id)  # type: ignore[union-attr]
                .where(
                    (ScanResult.origin_type.notin_(_CUSTOMIZED_ORIGIN_TYPES))  # type: ignore[union-attr]
                    | (ScanResult.origin_type.is_(None))  # type: ignore[union-attr]
                )
                .where(
                    (FeatureScanResult.assignment_source != "human")
                    | (FeatureScanResult.assignment_source.is_(None))  # type: ignore[union-attr]
                )
            )
            count = self.session.exec(count_stmt).one()
            return MembershipResult(fsrs_deleted=count)

        # Apply: fetch and delete
        to_delete = self.session.exec(stmt).all()
        for fsr in to_delete:
            self.session.delete(fsr)
        return MembershipResult(fsrs_deleted=len(to_delete))

    # ------------------------------------------------------------------
    # Step 3: Delete empty/orphan features
    # ------------------------------------------------------------------

    def _delete_empty_features(self) -> FeatureResult:
        """Delete features with zero remaining FSR rows after cleanup."""
        if self._assessment is None:
            return FeatureResult()

        # Find features for this assessment that have no FSR rows
        # Use a LEFT JOIN / subquery approach
        fsr_count_subq = (
            select(
                FeatureScanResult.feature_id,
                func.count(FeatureScanResult.id).label("cnt"),
            )
            .group_by(FeatureScanResult.feature_id)
            .subquery()
        )

        empty_features_stmt = (
            select(Feature)
            .outerjoin(fsr_count_subq, Feature.id == fsr_count_subq.c.feature_id)
            .where(Feature.assessment_id == self._assessment.id)
            .where(
                (fsr_count_subq.c.cnt.is_(None)) | (fsr_count_subq.c.cnt == 0)
            )
        )

        if self.dry_run:
            count_stmt = (
                select(func.count(Feature.id))
                .outerjoin(fsr_count_subq, Feature.id == fsr_count_subq.c.feature_id)
                .where(Feature.assessment_id == self._assessment.id)
                .where(
                    (fsr_count_subq.c.cnt.is_(None)) | (fsr_count_subq.c.cnt == 0)
                )
            )
            count = self.session.exec(count_stmt).one()
            return FeatureResult(features_deleted=count)

        # Apply: fetch and delete
        empty_features = self.session.exec(empty_features_stmt).all()
        for feature in empty_features:
            self.session.delete(feature)
        return FeatureResult(features_deleted=len(empty_features))

    # ------------------------------------------------------------------
    # Helper queries (all assessment-scoped)
    # ------------------------------------------------------------------

    def _count_total_scan_results(self) -> int:
        if not self._scan_ids:
            return 0
        return self.session.exec(
            select(func.count(ScanResult.id)).where(
                ScanResult.scan_id.in_(self._scan_ids)  # type: ignore[union-attr]
            )
        ).one()

    def _count_duplicates(self) -> tuple[int, int]:
        """Return (number_of_duplicate_groups, total_excess_rows)."""
        if not self._scan_ids:
            return 0, 0

        # Subquery: group by (table_name, sys_id) and count
        group_counts = (
            select(
                ScanResult.table_name,
                ScanResult.sys_id,
                func.count(ScanResult.id).label("cnt"),
            )
            .where(ScanResult.scan_id.in_(self._scan_ids))  # type: ignore[union-attr]
            .group_by(ScanResult.table_name, ScanResult.sys_id)
            .having(func.count(ScanResult.id) > 1)
            .subquery()
        )

        # Count groups
        groups = self.session.exec(
            select(func.count()).select_from(group_counts)
        ).one()

        # Sum excess rows (count - 1 per group)
        excess = self.session.exec(
            select(func.coalesce(func.sum(group_counts.c.cnt - 1), 0)).select_from(
                group_counts
            )
        ).one()

        return groups, excess

    def _count_human_fsrs(self) -> int:
        """Count FSR rows with assignment_source='human' for this assessment."""
        if self._assessment is None:
            return 0
        return self.session.exec(
            select(func.count(FeatureScanResult.id))
            .join(Feature, FeatureScanResult.feature_id == Feature.id)
            .where(Feature.assessment_id == self._assessment.id)
            .where(FeatureScanResult.assignment_source == "human")
        ).one()

    def _count_non_customized_fsrs(self) -> int:
        """Count FSR rows linked to non-customized scan_results."""
        if self._assessment is None:
            return 0
        return self.session.exec(
            select(func.count(FeatureScanResult.id))
            .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
            .join(Feature, FeatureScanResult.feature_id == Feature.id)
            .where(Feature.assessment_id == self._assessment.id)
            .where(
                (ScanResult.origin_type.notin_(_CUSTOMIZED_ORIGIN_TYPES))  # type: ignore[union-attr]
                | (ScanResult.origin_type.is_(None))  # type: ignore[union-attr]
            )
            .where(
                (FeatureScanResult.assignment_source != "human")
                | (FeatureScanResult.assignment_source.is_(None))  # type: ignore[union-attr]
            )
        ).one()

    def _count_features(self) -> int:
        if self._assessment is None:
            return 0
        return self.session.exec(
            select(func.count(Feature.id)).where(
                Feature.assessment_id == self._assessment.id
            )
        ).one()

    def _count_customized_features(self) -> int:
        """Count features that have at least one FSR linked to a customized scan_result."""
        if self._assessment is None:
            return 0
        return self.session.exec(
            select(func.count(func.distinct(Feature.id)))
            .join(FeatureScanResult, Feature.id == FeatureScanResult.feature_id)
            .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
            .where(Feature.assessment_id == self._assessment.id)
            .where(ScanResult.origin_type.in_(_CUSTOMIZED_ORIGIN_TYPES))  # type: ignore[union-attr]
        ).one()
