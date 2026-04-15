"""Re-run the customization classifier against an existing assessment's scan
results, without re-pulling scan data.

Usage: python -m scripts.reclassify_assessment <assessment_id>

Resets origin_type -> pending_classification for every ScanResult tied to the
assessment, then calls services.scan_executor.classify_scan_results which
reads local preflight data (version_history, metadata_customization,
customer_update_xml) and writes back origin_type + head_owner + derived
version fields. Observation / scope / disposition / AI fields are NOT touched.
"""
import sys
from sqlmodel import Session, select

from src.database import engine
from src import models  # noqa: F401 — register all ORM classes
from src import models_sn  # noqa: F401 — SnTableRegistry etc.
from src.models import Scan, ScanResult, OriginType
from src.services.scan_executor import classify_scan_results


def main(assessment_id: int) -> int:
    with Session(engine) as session:
        scan_ids = [
            s.id for s in session.exec(
                select(Scan).where(Scan.assessment_id == assessment_id)
            ).all()
        ]
        if not scan_ids:
            print(f"No scans for assessment {assessment_id}")
            return 1

        results = session.exec(
            select(ScanResult).where(ScanResult.scan_id.in_(scan_ids))
        ).all()
        before = {}
        for r in results:
            key = r.origin_type.value if r.origin_type else None
            before[key] = before.get(key, 0) + 1
            r.origin_type = OriginType.pending_classification
            session.add(r)
        session.commit()
        print(f"Reset {len(results)} rows to pending_classification. Prior counts: {before}")

        summary = classify_scan_results(session, assessment_id)
        print(f"classify_scan_results summary: {summary}")

        after_rows = session.exec(
            select(ScanResult).where(ScanResult.scan_id.in_(scan_ids))
        ).all()
        after = {}
        for r in after_rows:
            key = r.origin_type.value if r.origin_type else None
            after[key] = after.get(key, 0) + 1
        print(f"Post-classification counts: {after}")
    return 0


if __name__ == "__main__":
    aid = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    sys.exit(main(aid))
