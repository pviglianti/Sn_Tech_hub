"""One-time backfill: populate customization table from existing scan_results.

Run after deploying the Customization model to fill the child table for
all historically-classified results.

Usage:
    cd tech-assessment-hub
    ./venv/bin/python -m src.scripts.backfill_customizations
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sqlmodel import Session, select

from src.database import engine
from src import models_sn  # noqa: F401  # ensure SN mirror relationships are registered
from src.models import Customization, ScanResult
from src.services.customization_sync import (
    CUSTOMIZED_ORIGIN_TYPES,
    _build_customization_from_result,
)


def backfill() -> int:
    """Populate customization rows for all existing customized scan_results."""
    with Session(engine) as session:
        results = session.exec(
            select(ScanResult).where(
                ScanResult.origin_type.in_([ot.value for ot in CUSTOMIZED_ORIGIN_TYPES])
            )
        ).all()

        existing = set(session.exec(select(Customization.scan_result_id)).all())

        count = 0
        for result in results:
            if result.id not in existing:
                session.add(_build_customization_from_result(result))
                count += 1

        if count:
            session.commit()

        return count


if __name__ == "__main__":
    inserted = backfill()
    print(f"Backfill complete: {inserted} customization rows created.")
