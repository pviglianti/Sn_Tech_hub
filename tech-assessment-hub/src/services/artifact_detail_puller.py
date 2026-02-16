"""Artifact Detail Puller — post-scan service that pulls full artifact records.

After assessment scans complete, this service:
  1. Collects distinct (sys_class_name, sys_id) pairs from scan results
  2. Groups them by class (only those in ARTIFACT_DETAIL_DEFS)
  3. Batch-queries the real SN tables (sys_script, sys_script_include, etc.)
  4. Upserts into the per-class asmt_* tables via artifact_ddl

The relationship from scan_result → artifact is a simple dict lookup:
    scan_result.sys_class_name → ARTIFACT_DETAIL_DEFS[class_name]["local_table"]
    scan_result.sys_id         → asmt_*.sys_id WHERE _instance_id = instance_id
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from ..artifact_detail_defs import (
    ARTIFACT_DETAIL_DEFS,
    get_class_label,
    get_sn_fields_for_class,
)
from ..models import Assessment, Scan, ScanResult
from .artifact_ddl import upsert_artifact_records
from .sn_client import ServiceNowClient

logger = logging.getLogger(__name__)

# Max sys_ids per SN API request (50 × 32-char sys_ids ≈ 1,650 chars in query)
DEFAULT_BATCH_SIZE = 50

# Delay between batches to be polite to the SN instance (seconds)
DEFAULT_INTER_BATCH_DELAY = 0.5

# Callback signature: (sys_class_name, label, status, pulled, total)
PostflightCallback = Callable[[str, str, str, int, int], None]


def _collect_artifact_targets(
    session: Session,
    assessment_id: int,
) -> Dict[str, Set[str]]:
    """Collect distinct (sys_class_name → set of sys_ids) from scan results.

    Only includes classes that exist in ARTIFACT_DETAIL_DEFS.
    Uses table_name from scan_result as the class identifier (this is the
    actual SN table name, e.g., "sys_script_include").
    """
    scans = session.exec(
        select(Scan).where(Scan.assessment_id == assessment_id)
    ).all()
    scan_ids = [s.id for s in scans]
    if not scan_ids:
        return {}

    results = session.exec(
        select(ScanResult.table_name, ScanResult.sys_id).where(
            ScanResult.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
        )
    ).all()

    targets: Dict[str, Set[str]] = defaultdict(set)
    for table_name, sys_id in results:
        class_name = table_name or ""
        if class_name in ARTIFACT_DETAIL_DEFS and sys_id:
            targets[class_name].add(sys_id)

    return dict(targets)


def _batch_pull_class(
    client: ServiceNowClient,
    engine: Engine,
    sys_class_name: str,
    instance_id: int,
    sys_ids: List[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    inter_batch_delay: float = DEFAULT_INTER_BATCH_DELAY,
) -> Tuple[int, int]:
    """Pull artifact details for one class in batches.

    For each batch of <=batch_size sys_ids:
      1. Build query: sys_idIN<id1>,<id2>,...
      2. Call client.get_records() with the right fields
      3. Upsert via artifact_ddl

    Returns:
        (total_inserted, total_updated)
    """
    fields = get_sn_fields_for_class(sys_class_name)
    total_inserted = 0
    total_updated = 0

    for i in range(0, len(sys_ids), batch_size):
        batch = sys_ids[i : i + batch_size]
        query = f"sys_idIN{','.join(batch)}"

        try:
            records = client.get_records(
                table=sys_class_name,
                query=query,
                fields=fields,
                limit=batch_size,
            )
        except Exception as exc:
            logger.error(
                "Failed to pull %s batch %d for instance %d: %s",
                sys_class_name, i // batch_size, instance_id, exc,
            )
            continue

        if records:
            inserted, updated = upsert_artifact_records(
                engine=engine,
                sys_class_name=sys_class_name,
                instance_id=instance_id,
                records=records,
            )
            total_inserted += inserted
            total_updated += updated

        # Be polite to the SN instance
        if i + batch_size < len(sys_ids) and inter_batch_delay > 0:
            time.sleep(inter_batch_delay)

    return total_inserted, total_updated


def pull_artifact_details_for_assessment(
    session: Session,
    assessment: Assessment,
    client: ServiceNowClient,
    engine: Engine,
    progress_callback: Optional[PostflightCallback] = None,
) -> Dict[str, Any]:
    """Pull full artifact details for all scan results in an assessment.

    Args:
        session: DB session.
        assessment: The assessment whose scan results to process.
        client: Authenticated SN client for the assessment's instance.
        engine: SQLAlchemy engine for raw SQL operations.
        progress_callback: Optional callback(sys_class_name, label, status, pulled, total)
            called as each class starts, progresses, and completes.

    Returns:
        Summary dict: {
            "total_classes": N,
            "total_pulled": N,
            "by_class": {class_name: {"label": str, "pulled": N, "total": N, "status": str}}
        }
    """
    targets = _collect_artifact_targets(session, assessment.id)

    if not targets:
        logger.info("No artifact targets found for assessment %d", assessment.id)
        return {"total_classes": 0, "total_pulled": 0, "by_class": {}}

    instance_id = assessment.instance_id
    summary: Dict[str, Any] = {
        "total_classes": len(targets),
        "total_pulled": 0,
        "by_class": {},
    }

    # Notify all classes as pending first
    if progress_callback:
        for class_name, sys_ids in targets.items():
            label = get_class_label(class_name)
            progress_callback(class_name, label, "pending", 0, len(sys_ids))

    for class_name, sys_ids in targets.items():
        label = get_class_label(class_name)
        total = len(sys_ids)
        logger.info(
            "Pulling %d %s artifacts for assessment %d (instance %d)",
            total, label, assessment.id, instance_id,
        )

        # Notify: running
        if progress_callback:
            progress_callback(class_name, label, "running", 0, total)

        try:
            inserted, updated = _batch_pull_class(
                client=client,
                engine=engine,
                sys_class_name=class_name,
                instance_id=instance_id,
                sys_ids=list(sys_ids),
            )
            pulled = inserted + updated
            status = "completed"

            summary["by_class"][class_name] = {
                "label": label,
                "pulled": pulled,
                "total": total,
                "inserted": inserted,
                "updated": updated,
                "status": status,
            }
            summary["total_pulled"] += pulled

            logger.info(
                "Completed %s: %d inserted, %d updated (of %d targets)",
                label, inserted, updated, total,
            )

        except Exception as exc:
            status = "failed"
            summary["by_class"][class_name] = {
                "label": label,
                "pulled": 0,
                "total": total,
                "status": status,
                "error": str(exc),
            }
            logger.error("Failed pulling %s: %s", label, exc)

        # Notify: completed or failed
        if progress_callback:
            pulled = summary["by_class"][class_name].get("pulled", 0)
            progress_callback(class_name, label, status, pulled, total)

    return summary
