"""CLI integration tests for cleanup_legacy_feature_data (Phase 11C — C3).

These tests define the contract that W2 must implement.
All tests use in-memory SQLite with seeded fixture data and invoke the CLI
main() function directly with patched DB session.
"""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from io import StringIO
from typing import List, Optional
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
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

# W1/W2 create these modules — tests will fail with ImportError until delivered.
from src.services.legacy_cleanup_service import CleanupReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_assessment(session: Session, *, number: str = "ASMT0001"):
    """Create a minimal assessment with one scan result and one feature."""
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
        number=number,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.pending,
        pipeline_stage=PipelineStage.scans,
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

    sr = ScanResult(
        scan_id=scan.id,
        sys_id="s1",
        table_name="sys_script",
        name="BR - Test",
        origin_type=OriginType.modified_ootb,
    )
    session.add(sr)
    session.flush()

    feat = Feature(assessment_id=asmt.id, name="Test Feature")
    session.add(feat)
    session.flush()

    fsr = FeatureScanResult(
        feature_id=feat.id,
        scan_result_id=sr.id,
        assignment_source="engine",
    )
    session.add(fsr)
    session.commit()

    return asmt


def _run_cli(
    args: List[str],
    *,
    db_session: Session,
    input_text: Optional[str] = None,
):
    """Import and invoke the CLI main function with patched DB session.

    Returns (exit_code, stdout_text).
    """
    from src.scripts import cleanup_legacy_feature_data as cli_mod

    captured = StringIO()
    exit_code = 0

    # Patch get_session to yield our test session
    def _mock_get_session():
        yield db_session

    with ExitStack() as stack:
        # Patch session provider
        if hasattr(cli_mod, "get_session"):
            stack.enter_context(
                patch.object(cli_mod, "get_session", _mock_get_session)
            )
        else:
            stack.enter_context(
                patch("src.database.get_session", _mock_get_session)
            )

        # Patch stdin for confirmation prompts
        if input_text is not None:
            stack.enter_context(
                patch("builtins.input", return_value=input_text)
            )

        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            ret = cli_mod.main(args)
            if isinstance(ret, int):
                exit_code = ret
        except SystemExit as e:
            exit_code = e.code if e.code is not None else 0
        finally:
            sys.stdout = old_stdout

    return exit_code, captured.getvalue()


# ---------------------------------------------------------------------------
# 1. Default dry-run
# ---------------------------------------------------------------------------


class TestCLIDryRun:
    """Test 1: Running without --apply produces report, exit 0, no mutations."""

    def test_cli_dryrun_default(self, db_session):
        """#1: Default invocation (no --apply) is dry-run mode."""
        asmt = _seed_assessment(db_session)

        sr_before = len(db_session.exec(select(ScanResult)).all())
        fsr_before = len(db_session.exec(select(FeatureScanResult)).all())

        exit_code, output = _run_cli(
            ["--assessment-id", asmt.number], db_session=db_session
        )

        assert exit_code == 0
        # Output should mention dry-run
        assert "DRY-RUN" in output.upper() or "dry" in output.lower()

        # No mutations
        sr_after = len(db_session.exec(select(ScanResult)).all())
        fsr_after = len(db_session.exec(select(FeatureScanResult)).all())
        assert sr_after == sr_before
        assert fsr_after == fsr_before


# ---------------------------------------------------------------------------
# 2. Apply requires confirmation
# ---------------------------------------------------------------------------


class TestCLIConfirmation:
    """Test 2: --apply without --yes prompts; non-YES input aborts."""

    def test_cli_apply_requires_confirmation(self, db_session):
        """#2: --apply without --yes prompts, 'NO' input exits cleanly."""
        asmt = _seed_assessment(db_session)

        exit_code, output = _run_cli(
            ["--assessment-id", asmt.number, "--apply"],
            db_session=db_session,
            input_text="NO",
        )

        # Should exit without applying — exit code 0 (user chose not to proceed)
        # or a non-error exit. The key is it doesn't crash and doesn't apply.
        assert exit_code in (0, 1)

        # No mutations
        sr_after = len(db_session.exec(select(ScanResult)).all())
        assert sr_after > 0  # Data still there


# ---------------------------------------------------------------------------
# 3. Apply with --yes
# ---------------------------------------------------------------------------


class TestCLIApplyYes:
    """Test 3: --apply --yes runs without prompting."""

    def test_cli_apply_with_yes_flag(self, db_session):
        """#3: --apply --yes bypasses confirmation prompt."""
        asmt = _seed_assessment(db_session)

        exit_code, output = _run_cli(
            ["--assessment-id", asmt.number, "--apply", "--yes"],
            db_session=db_session,
        )

        assert exit_code == 0
        # Should indicate apply mode
        upper = output.upper()
        assert "APPLY" in upper or "SUCCESS" in upper


# ---------------------------------------------------------------------------
# 4. JSON output
# ---------------------------------------------------------------------------


class TestCLIJsonOutput:
    """Test 4: --json produces valid JSON parseable as CleanupReport."""

    def test_cli_json_output(self, db_session):
        """#4: --json outputs valid JSON with expected keys."""
        asmt = _seed_assessment(db_session)

        exit_code, output = _run_cli(
            ["--assessment-id", asmt.number, "--json"],
            db_session=db_session,
        )

        assert exit_code == 0

        # Parse as JSON
        data = json.loads(output.strip())
        assert isinstance(data, dict)

        # Must contain core report fields
        assert "assessment_id" in data
        assert "dry_run" in data
        assert "success" in data
        assert data["assessment_id"] == asmt.number


# ---------------------------------------------------------------------------
# 5. Bad assessment exits with code 1
# ---------------------------------------------------------------------------


class TestCLIBadAssessment:
    """Test 5: Non-existent assessment_id exits with code 1."""

    def test_cli_bad_assessment_exit_1(self, db_session):
        """#5: Non-existent assessment_id exits with code 1."""
        exit_code, output = _run_cli(
            ["--assessment-id", "ASMT_DOES_NOT_EXIST"],
            db_session=db_session,
        )

        assert exit_code == 1


# ---------------------------------------------------------------------------
# 6. Missing assessment-id
# ---------------------------------------------------------------------------


class TestCLIMissingArgs:
    """Test 6: Missing --assessment-id prints usage, exits with code 2."""

    def test_cli_missing_assessment_id(self, db_session):
        """#6: Missing --assessment-id exits with code 2."""
        exit_code, output = _run_cli([], db_session=db_session)

        assert exit_code == 2
