"""Phase 11C — Legacy feature data cleanup CLI.

Assessment-scoped utility that removes duplicate scan_result artifacts,
non-customized feature memberships, and empty/orphan features.

Default mode is dry-run (read-only report). Use --apply for destructive cleanup.

Usage:
    cd tech-assessment-hub
    ./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001
    ./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001 --apply --yes
    ./venv/bin/python -m src.scripts.cleanup_legacy_feature_data --assessment-id ASMT0000001 --json
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.database import get_session
from src import models_sn  # noqa: F401  # ensure SN mirror relationships are registered
from src.services.legacy_cleanup_service import LegacyCleanupService, CleanupReport


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleanup_legacy_feature_data",
        description="Clean up legacy feature data for a specific assessment.",
    )
    parser.add_argument(
        "--assessment-id",
        required=True,
        help="Assessment ID to clean up (e.g. ASMT0000001).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply destructive cleanup (default is dry-run).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Skip interactive confirmation prompt (for automation).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output report as JSON instead of human-readable table.",
    )
    return parser


def _format_number(n: Optional[int]) -> str:
    """Format an integer with comma separators, or '-' if None."""
    if n is None:
        return "-"
    return f"{n:,}"


def _print_human_report(report: CleanupReport) -> None:
    """Print the cleanup report in human-readable format."""
    mode = "APPLY" if not report.dry_run else "DRY-RUN"
    stage = report.preflight.pipeline_stage if report.preflight else "unknown"

    print()
    print("=== Phase 11C Legacy Cleanup Report ===")
    print(f"Assessment: {report.assessment_id}")
    print(f"Mode: {mode}")
    print(f"Pipeline Stage: {stage}")

    if report.preflight:
        pf = report.preflight
        safe_label = "SAFE" if pf.human_fsr_count == 0 else "AT RISK"
        print()
        print("--- Pre-flight ---")
        print(f"Human memberships at risk:    {_format_number(pf.human_fsr_count)} ({safe_label})")
        print(f"Total scan results:           {_format_number(pf.total_scan_results)}")
        print(f"Duplicate groups:             {_format_number(pf.duplicate_groups)}")
        print(f"Excess duplicate rows:        {_format_number(pf.excess_rows)}")
        print(f"Non-customized FSR rows:      {_format_number(pf.non_customized_fsrs)}")
        print(f"Total features:               {_format_number(pf.total_features)}")
        print(f"Features with custom members: {_format_number(pf.customized_features)}")

        if not pf.safe_to_proceed:
            print()
            print(f"ABORT: {pf.abort_reason}")

    if report.dedup:
        dd = report.dedup
        print()
        print("--- Deduplication ---")
        print(f"Groups processed:                {_format_number(dd.groups_processed)}")
        print(f"Scan result rows removed:        {_format_number(dd.rows_deleted)}")
        print(f"FSR rows re-pointed:             {_format_number(dd.fsrs_repointed)}")
        print(f"Customization rows re-pointed:   {_format_number(dd.customizations_repointed)}")

    if report.membership:
        print()
        print("--- Membership Cleanup ---")
        print(f"Non-customized FSRs removed: {_format_number(report.membership.fsrs_deleted)}")

    if report.features:
        print()
        print("--- Feature Cleanup ---")
        print(f"Empty features removed:      {_format_number(report.features.features_deleted)}")

    print()
    print("--- Summary ---")
    status = "SUCCESS" if report.success else "FAILED"
    print(f"Status: {status}")
    if report.error:
        print(f"Error: {report.error}")
    print(f"Elapsed: {report.elapsed_seconds:.1f}s")
    print()


def _print_json_report(report: CleanupReport) -> None:
    """Print the cleanup report as JSON."""
    print(json.dumps(asdict(report), indent=2, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint. Returns exit code: 0=success, 1=preflight failure, 2=runtime error."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    dry_run = not args.apply

    session_iter = get_session()
    session = next(session_iter)
    try:
        service = LegacyCleanupService(
            session=session,
            assessment_id=args.assessment_id,
            dry_run=dry_run,
        )

        # If --apply, run dry-run first to show what will happen, then confirm
        if args.apply:
            # Run a dry-run pass first to show the report and check pre-flight
            dry_service = LegacyCleanupService(
                session=session,
                assessment_id=args.assessment_id,
                dry_run=True,
            )
            dry_report = dry_service.run()

            # Check pre-flight result
            if not dry_report.preflight or not dry_report.preflight.safe_to_proceed:
                if args.json_output:
                    _print_json_report(dry_report)
                else:
                    _print_human_report(dry_report)
                return 1

            # Show the dry-run report before prompting
            if not args.json_output:
                _print_human_report(dry_report)
                print("WARNING: Recommended to back up your database before running --apply.")
                print()

            # Confirmation gate
            if not args.yes:
                try:
                    answer = input("Type 'YES' to confirm destructive cleanup: ")
                except (EOFError, KeyboardInterrupt):
                    print("\nAborted.")
                    return 0
                if answer.strip() != "YES":
                    print("Aborted — no changes made.")
                    return 0

            # Now run the actual apply
            report = service.run()
        else:
            report = service.run()

        # Check pre-flight failure (dry-run path)
        if not report.success and report.preflight and not report.preflight.safe_to_proceed:
            if args.json_output:
                _print_json_report(report)
            else:
                _print_human_report(report)
            return 1

        # Check runtime error
        if not report.success:
            if args.json_output:
                _print_json_report(report)
            else:
                _print_human_report(report)
            return 2

        # Success
        if args.json_output:
            _print_json_report(report)
        else:
            _print_human_report(report)
        return 0
    finally:
        session_iter.close()


if __name__ == "__main__":
    sys.exit(main())
