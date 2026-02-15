"""MCP tool: group_by_feature — feature clustering heuristic.

Groups scan results into Features by update set, creator, or auto strategy.
Populates the Feature and FeatureScanResult tables that have existed since
the data model was built but have never been used.
"""

from typing import Any, Dict, List
from datetime import datetime
from collections import defaultdict

from sqlmodel import Session, select, col, func

from ...registry import ToolSpec
from ....models import (
    ScanResult, Scan, Assessment, Feature, FeatureScanResult,
    OriginType, UpdateSet,
)


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment to group results for.",
        },
        "strategy": {
            "type": "string",
            "enum": ["update_set", "creator", "auto"],
            "description": "Grouping strategy. 'auto' uses update_set first, then creator for ungrouped.",
            "default": "auto",
        },
        "min_group_size": {
            "type": "integer",
            "description": "Minimum results to form a feature group (default 2).",
            "default": 2,
        },
    },
    "required": ["assessment_id"],
}


def _get_customized_results(session: Session, assessment_id: int) -> List[ScanResult]:
    """Get all non-OOTB results for the assessment."""
    scan_ids = list(session.exec(
        select(Scan.id).where(Scan.assessment_id == assessment_id)
    ).all())
    if not scan_ids:
        return []

    return list(session.exec(
        select(ScanResult)
        .where(col(ScanResult.scan_id).in_(scan_ids))
        .where(ScanResult.origin_type != OriginType.ootb_untouched)
    ).all())


def _group_by_update_set(results: List[ScanResult]) -> Dict[int, List[ScanResult]]:
    """Cluster results by their update_set_id."""
    groups: Dict[int, List[ScanResult]] = defaultdict(list)
    for r in results:
        if r.update_set_id:
            groups[r.update_set_id].append(r)
    return groups


def _group_by_creator(results: List[ScanResult]) -> Dict[str, List[ScanResult]]:
    """Cluster results by sys_created_by."""
    groups: Dict[str, List[ScanResult]] = defaultdict(list)
    for r in results:
        creator = r.sys_created_by or "unknown"
        groups[creator].append(r)
    return groups


def _create_feature(
    session: Session,
    assessment_id: int,
    name: str,
    results: List[ScanResult],
    update_set_id: int = None,
) -> Feature:
    """Create a Feature record and link scan results."""
    feature = Feature(
        assessment_id=assessment_id,
        name=name,
        primary_update_set_id=update_set_id,
    )
    session.add(feature)
    session.flush()  # Get the ID

    for r in results:
        link = FeatureScanResult(
            feature_id=feature.id,
            scan_result_id=r.id,
            is_primary=True,
        )
        session.add(link)

    return feature


def _build_group_summary(results: List[ScanResult]) -> Dict[str, Any]:
    """Build a summary dict for a feature group."""
    tables = defaultdict(int)
    origins = defaultdict(int)
    for r in results:
        tables[r.table_name] += 1
        if r.origin_type:
            origins[r.origin_type.value] += 1

    return {
        "member_count": len(results),
        "tables": dict(tables),
        "origin_mix": dict(origins),
        "top_creator": max(
            set(r.sys_created_by or "unknown" for r in results),
            key=lambda c: sum(1 for r in results if (r.sys_created_by or "unknown") == c),
        ),
    }


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    strategy = params.get("strategy", "auto")
    min_group_size = params.get("min_group_size", 2)

    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    # Clear existing features for this assessment (re-grouping)
    existing_features = session.exec(
        select(Feature).where(Feature.assessment_id == assessment_id)
    ).all()
    for f in existing_features:
        # Delete links first
        links = session.exec(
            select(FeatureScanResult).where(FeatureScanResult.feature_id == f.id)
        ).all()
        for link in links:
            session.delete(link)
        session.delete(f)
    session.flush()

    results = _get_customized_results(session, assessment_id)
    if not results:
        session.commit()
        return {"success": True, "features_created": 0, "groups": [], "ungrouped_count": 0}

    grouped_ids: set = set()
    features_created = []

    if strategy in ("update_set", "auto"):
        us_groups = _group_by_update_set(results)
        for us_id, members in us_groups.items():
            if len(members) < min_group_size:
                continue
            # Get update set name
            us = session.get(UpdateSet, us_id)
            name = f"Update Set: {us.name}" if us else f"Update Set #{us_id}"
            feature = _create_feature(session, assessment_id, name, members, update_set_id=us_id)
            grouped_ids.update(r.id for r in members)
            features_created.append({
                "name": name,
                **_build_group_summary(members),
            })

    ungrouped = [r for r in results if r.id not in grouped_ids]

    if strategy in ("creator", "auto") and ungrouped:
        creator_groups = _group_by_creator(ungrouped)
        for creator, members in creator_groups.items():
            if len(members) < min_group_size:
                continue
            name = f"Creator: {creator}"
            feature = _create_feature(session, assessment_id, name, members)
            grouped_ids.update(r.id for r in members)
            features_created.append({
                "name": name,
                **_build_group_summary(members),
            })

    session.commit()

    final_ungrouped = len(results) - len(grouped_ids)

    return {
        "success": True,
        "features_created": len(features_created),
        "total_results": len(results),
        "grouped_count": len(grouped_ids),
        "ungrouped_count": final_ungrouped,
        "groups": features_created,
    }


TOOL_SPEC = ToolSpec(
    name="group_by_feature",
    description=(
        "Group assessment scan results into feature clusters by update set, "
        "creator, or auto strategy. Creates Feature records in the database. "
        "Use after running an assessment to organize customizations into "
        "human-meaningful feature groups for analysis."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
