"""Feature graph governance helpers.

Centralizes feature membership rollups, coverage checks, and manual override
validation so the pipeline, MCP tools, and UI all reason over the same rules.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlmodel import Session, select

from ..models import Feature, FeatureScanResult, OriginType, ReviewStatus, Scan, ScanResult

_CUSTOMIZED_ORIGIN_VALUES = {
    OriginType.modified_ootb.value,
    OriginType.net_new_customer.value,
}

_ASSIGNMENT_SOURCE_PRIORITY = {
    "human": 3,
    "ai": 2,
    "engine": 1,
}


def _origin_value(result: ScanResult) -> Optional[str]:
    if result.origin_type is None:
        return None
    if hasattr(result.origin_type, "value"):
        return result.origin_type.value
    return str(result.origin_type)


def is_customized_result(result: ScanResult) -> bool:
    return (_origin_value(result) or "") in _CUSTOMIZED_ORIGIN_VALUES


def is_in_scope_customized_result(result: ScanResult) -> bool:
    return is_customized_result(result) and not bool(result.is_out_of_scope)


def _best_assignment_rank(link: FeatureScanResult) -> Tuple[int, int, float, int, int]:
    source = str(link.assignment_source or "engine").strip().lower()
    return (
        _ASSIGNMENT_SOURCE_PRIORITY.get(source, 0),
        1 if bool(link.is_primary) else 0,
        float(link.assignment_confidence or 0.0),
        int(link.iteration_number or 0),
        int(link.id or 0),
    )


def _load_feature_member_results(
    session: Session,
    *,
    feature_ids: Iterable[int],
) -> Dict[int, List[ScanResult]]:
    feature_ids = [int(fid) for fid in feature_ids if fid is not None]
    if not feature_ids:
        return {}

    rows = session.exec(
        select(FeatureScanResult, ScanResult)
        .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
        .where(FeatureScanResult.feature_id.in_(feature_ids))
    ).all()

    members_by_feature: Dict[int, List[ScanResult]] = {}
    for link, result in rows:
        members_by_feature.setdefault(int(link.feature_id), []).append(result)
    return members_by_feature


def derive_composition_type(results: Iterable[ScanResult]) -> Optional[str]:
    relevant = [row for row in results if row is not None]
    if not relevant:
        return None
    adjacent_count = sum(1 for row in relevant if bool(row.is_adjacent))
    if adjacent_count <= 0:
        return "direct"
    if adjacent_count >= len(relevant):
        return "adjacent"
    return "mixed"


def refresh_feature_metadata(
    session: Session,
    *,
    assessment_id: Optional[int] = None,
    feature_ids: Optional[Iterable[int]] = None,
    commit: bool = False,
) -> Dict[str, Any]:
    if feature_ids is not None:
        normalized_feature_ids = [int(fid) for fid in feature_ids if fid is not None]
        if not normalized_feature_ids:
            return {"updated": 0, "feature_ids": []}
        features = session.exec(
            select(Feature).where(Feature.id.in_(normalized_feature_ids))
        ).all()
    elif assessment_id is not None:
        features = session.exec(
            select(Feature)
            .where(Feature.assessment_id == int(assessment_id))
            .order_by(Feature.id.asc())
        ).all()
    else:
        raise ValueError("assessment_id or feature_ids is required")

    members_by_feature = _load_feature_member_results(
        session,
        feature_ids=[feature.id for feature in features if feature.id is not None],
    )

    updated = 0
    for feature in features:
        previous_kind = feature.feature_kind
        previous_composition = feature.composition_type

        feature.feature_kind = "bucket" if feature.bucket_key else "functional"
        feature.composition_type = derive_composition_type(members_by_feature.get(int(feature.id or 0), []))

        if previous_kind != feature.feature_kind or previous_composition != feature.composition_type:
            session.add(feature)
            updated += 1

    if commit:
        session.commit()
    else:
        session.flush()

    return {
        "updated": updated,
        "feature_ids": [int(feature.id) for feature in features if feature.id is not None],
    }


def _load_best_assignments(
    session: Session,
    *,
    assessment_id: int,
) -> Dict[int, FeatureScanResult]:
    rows = session.exec(
        select(FeatureScanResult, Feature, ScanResult)
        .join(Feature, FeatureScanResult.feature_id == Feature.id)
        .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Feature.assessment_id == int(assessment_id))
        .where(Scan.assessment_id == int(assessment_id))
    ).all()

    best_by_result: Dict[int, FeatureScanResult] = {}
    for link, _feature, result in rows:
        if result.id is None or not is_in_scope_customized_result(result):
            continue
        existing = best_by_result.get(int(result.id))
        if existing is None or _best_assignment_rank(link) > _best_assignment_rank(existing):
            best_by_result[int(result.id)] = link
    return best_by_result


def build_feature_assignment_summary(
    session: Session,
    *,
    assessment_id: int,
    sample_limit: int = 25,
) -> Dict[str, Any]:
    results = session.exec(
        select(ScanResult)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .where(Scan.assessment_id == int(assessment_id))
        .order_by(ScanResult.id.asc())
    ).all()

    in_scope_customized = [row for row in results if is_in_scope_customized_result(row)]
    best_assignments = _load_best_assignments(session, assessment_id=assessment_id)
    assigned_ids = set(best_assignments.keys())

    feature_rows = session.exec(
        select(Feature).where(Feature.assessment_id == int(assessment_id))
    ).all()
    features_by_id = {int(feature.id): feature for feature in feature_rows if feature.id is not None}

    human_standalone: List[ScanResult] = []
    unresolved: List[ScanResult] = []
    reviewed_without_assignment: List[ScanResult] = []
    for row in in_scope_customized:
        if int(row.id or 0) in assigned_ids:
            continue
        observations = (row.observations or "").strip()
        is_reviewed = row.review_status == ReviewStatus.reviewed
        if is_reviewed and observations:
            human_standalone.append(row)
            continue
        unresolved.append(row)
        if is_reviewed and not observations:
            reviewed_without_assignment.append(row)

    provisional_features = [
        feature for feature in feature_rows
        if str(feature.name_status or "provisional").strip().lower() == "provisional"
    ]
    bucket_features = [
        feature for feature in feature_rows
        if str(feature.feature_kind or "functional").strip().lower() == "bucket"
    ]

    composition_counts = {"direct": 0, "adjacent": 0, "mixed": 0, "unset": 0}
    for feature in feature_rows:
        comp = str(feature.composition_type or "").strip().lower()
        if comp in composition_counts:
            composition_counts[comp] += 1
        else:
            composition_counts["unset"] += 1

    unresolved_payload = [
        {
            "id": row.id,
            "name": row.name,
            "table_name": row.table_name,
            "is_adjacent": bool(row.is_adjacent),
            "review_status": row.review_status.value if row.review_status else None,
            "links": {
                "result": f"/results/{int(row.id)}",
            },
        }
        for row in unresolved[: max(1, int(sample_limit))]
        if row.id is not None
    ]
    reviewed_in_scope_count = sum(
        1 for row in in_scope_customized if row.review_status == ReviewStatus.reviewed
    )
    manual_override_ready = len(unresolved) == 0 and reviewed_in_scope_count == len(in_scope_customized)
    if len(unresolved) > 0:
        blocking_reason = (
            "Not every in-scope customized artifact is covered. "
            "Assign each artifact to a feature or add reviewed human observations explaining why it stands alone."
        )
    elif reviewed_in_scope_count != len(in_scope_customized):
        blocking_reason = (
            "Manual override requires human review on every in-scope customized artifact."
        )
    else:
        blocking_reason = None

    feature_refs_by_result: Dict[int, Dict[str, Any]] = {}
    for result_id, link in best_assignments.items():
        feature = features_by_id.get(int(link.feature_id))
        feature_refs_by_result[result_id] = {
            "feature_id": int(link.feature_id),
            "feature_name": feature.name if feature else f"Feature {int(link.feature_id)}",
            "feature_kind": feature.feature_kind if feature else None,
            "composition_type": feature.composition_type if feature else None,
            "name_status": feature.name_status if feature else None,
            "assignment_source": link.assignment_source,
        }

    return {
        "assessment_id": int(assessment_id),
        "in_scope_customized_total": len(in_scope_customized),
        "assigned_count": len(assigned_ids),
        "human_standalone_count": len(human_standalone),
        "resolved_count": len(assigned_ids) + len(human_standalone),
        "unassigned_count": len(unresolved),
        "all_in_scope_assigned": len(unresolved) == 0,
        "reviewed_in_scope_count": reviewed_in_scope_count,
        "manual_override_ready": manual_override_ready,
        "provisional_feature_count": len(provisional_features),
        "bucket_feature_count": len(bucket_features),
        "feature_count": len(feature_rows),
        "composition_counts": composition_counts,
        "blocking_reason": blocking_reason,
        "unassigned_result_ids": [int(row.id) for row in unresolved if row.id is not None],
        "unassigned_results": unresolved_payload,
        "reviewed_without_assignment_count": len(reviewed_without_assignment),
        "feature_assignments_by_result": feature_refs_by_result,
    }


def replace_result_feature_membership(
    session: Session,
    *,
    feature_id: int,
    scan_result: ScanResult,
    assignment_source: str,
    assignment_confidence: Optional[float] = None,
    notes: Optional[str] = None,
    membership_type: str = "primary",
    is_primary: bool = True,
    iteration_number: int = 0,
) -> FeatureScanResult:
    if scan_result.id is None:
        raise ValueError("ScanResult must be persisted before assigning to a feature.")
    if not is_customized_result(scan_result):
        raise ValueError(
            "Only customized results (modified_ootb / net_new_customer) can be assigned to features."
        )

    existing_links = session.exec(
        select(FeatureScanResult).where(FeatureScanResult.scan_result_id == int(scan_result.id))
    ).all()
    for link in existing_links:
        existing_source = str(link.assignment_source or "engine").strip().lower()
        if existing_source == "human" and assignment_source != "human" and int(link.feature_id) != int(feature_id):
            raise ValueError(
                f"ScanResult {int(scan_result.id)} has a human-authored feature assignment. "
                "Human feature memberships are authoritative and must be changed by a human."
            )

    retained_link: Optional[FeatureScanResult] = None
    for link in existing_links:
        if int(link.feature_id) == int(feature_id):
            retained_link = link
            continue
        session.delete(link)

    if retained_link is None:
        retained_link = FeatureScanResult(
            feature_id=int(feature_id),
            scan_result_id=int(scan_result.id),
        )

    retained_link.is_primary = bool(is_primary)
    retained_link.notes = notes
    retained_link.membership_type = membership_type
    retained_link.assignment_source = assignment_source
    retained_link.assignment_confidence = assignment_confidence
    retained_link.iteration_number = int(iteration_number or 0)
    session.add(retained_link)
    session.flush()
    return retained_link
