"""Engine 2: Update Set Analyzer.

Analyzes update set relationships using an artifact-centric workflow:
- start from customized artifacts,
- build deterministic artifact↔update set provenance links,
- emit explainable overlap signals across content, naming, version-history,
  temporal sequence, and author sequence,
- optionally enrich scores with artifact observation context.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlmodel import Session, select

from ..models import (
    Assessment,
    CodeReference,
    CustomerUpdateXML,
    OriginType,
    Scan,
    ScanResult,
    StructuralRelationship,
    UpdateSet,
    UpdateSetArtifactLink,
    UpdateSetOverlap,
    VersionHistory,
)
from ..services.integration_properties import load_reasoning_engine_properties


_TICKET_PATTERN = re.compile(
    r"\b((?:TASK|STRY|INC|CHG|RITM|PRB|REQ|SCTASK|CTASK|KB|DFCT|DMND|ENHC)\d{5,10})\b",
    re.IGNORECASE,
)

_STOP_TOKENS = frozenset(
    {
        "update",
        "set",
        "default",
        "story",
        "task",
        "fix",
        "bug",
        "change",
        "feature",
        "work",
        "the",
        "and",
        "for",
        "with",
    }
)


def run(assessment_id: int, session: Session, mode: str = "base") -> Dict[str, Any]:
    """Run the update set analyzer engine for an assessment.

    Args:
        assessment_id: Assessment primary key.
        session: SQLModel session.
        mode: "base" or "enriched". Enriched mode uses AI summary/observation
            context and relationship density to refine overlap confidence.
    """
    if mode not in {"base", "enriched"}:
        return {
            "success": False,
            "content_overlaps": 0,
            "name_overlaps": 0,
            "vh_overlaps": 0,
            "temporal_sequence_overlaps": 0,
            "author_sequence_overlaps": 0,
            "artifact_links_created": 0,
            "errors": [f"Invalid mode: {mode}"],
        }

    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "content_overlaps": 0,
            "name_overlaps": 0,
            "vh_overlaps": 0,
            "temporal_sequence_overlaps": 0,
            "author_sequence_overlaps": 0,
            "artifact_links_created": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id
    props = load_reasoning_engine_properties(session, instance_id=instance_id)

    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "content_overlaps": 0,
            "name_overlaps": 0,
            "vh_overlaps": 0,
            "temporal_sequence_overlaps": 0,
            "author_sequence_overlaps": 0,
            "artifact_links_created": 0,
            "update_sets_analyzed": 0,
            "errors": [],
            "message": "No scan results found",
            "mode": mode,
        }

    # Idempotent reruns by assessment scope.
    _delete_existing(session, assessment_id)

    sr_by_id: Dict[int, ScanResult] = {int(sr.id): sr for sr in scan_results if sr.id is not None}
    sr_by_sys_id: Dict[str, ScanResult] = {sr.sys_id: sr for sr in scan_results}
    sr_by_update_name: Dict[str, ScanResult] = {
        sr.sys_update_name: sr for sr in scan_results if sr.sys_update_name
    }

    anchor_ids = _get_customized_anchor_ids(scan_results)
    scoped_sr_ids = _expand_relevant_scope(session, assessment_id, anchor_ids)
    if not scoped_sr_ids:
        scoped_sr_ids = set(sr_by_id.keys())

    update_sets = list(session.exec(select(UpdateSet).where(UpdateSet.instance_id == instance_id)).all())
    us_by_id: Dict[int, UpdateSet] = {int(us.id): us for us in update_sets if us.id is not None}
    us_by_sn_sys_id: Dict[str, UpdateSet] = {us.sn_sys_id: us for us in update_sets}
    default_us_ids = {int(us.id) for us in update_sets if us.id is not None and us.is_default}

    links = _build_artifact_links(
        session=session,
        assessment_id=assessment_id,
        instance_id=instance_id,
        scoped_sr_ids=scoped_sr_ids,
        sr_by_id=sr_by_id,
        sr_by_sys_id=sr_by_sys_id,
        sr_by_update_name=sr_by_update_name,
        us_by_id=us_by_id,
        us_by_sn_sys_id=us_by_sn_sys_id,
    )

    for link in links:
        session.add(link)
    session.flush()

    link_rows = list(
        session.exec(
            select(UpdateSetArtifactLink).where(UpdateSetArtifactLink.assessment_id == assessment_id)
        ).all()
    )

    # Build reusable maps by source.
    us_to_sr_content = _map_links_by_us(link_rows, {"scan_result_current", "customer_update_xml"})
    us_to_sr_vh = _map_links_by_us(link_rows, {"version_history"})

    # Include current placement as context for VH comparisons.
    for link in link_rows:
        if link.link_source == "scan_result_current" and link.scan_result_id in {
            l.scan_result_id for l in link_rows if l.link_source == "version_history"
        }:
            us_to_sr_vh[link.update_set_id].add(link.scan_result_id)

    coherence_by_us: Dict[int, float] = {}
    if mode == "enriched":
        coherence_by_us = _compute_us_coherence(
            session=session,
            assessment_id=assessment_id,
            us_to_sr_ids=us_to_sr_content,
            sr_by_id=sr_by_id,
        )

    counters = {
        "content": 0,
        "name_similarity": 0,
        "version_history": 0,
        "temporal_sequence": 0,
        "author_sequence": 0,
    }

    # Content overlap signal.
    counters["content"] = _emit_pairwise_overlaps(
        session=session,
        assessment_id=assessment_id,
        instance_id=instance_id,
        us_to_sr_ids=us_to_sr_content,
        us_by_id=us_by_id,
        default_us_ids=default_us_ids,
        sr_by_id=sr_by_id,
        signal_type="content",
        min_shared=max(1, props.us_min_shared_records),
        include_default_sets=props.us_include_default_sets,
        default_weight=props.us_default_signal_weight,
        mode=mode,
        coherence_by_us=coherence_by_us,
    )

    # Name/family overlap signal.
    counters["name_similarity"] = _emit_name_overlaps(
        session=session,
        assessment_id=assessment_id,
        instance_id=instance_id,
        update_sets=update_sets,
        us_to_sr_ids=us_to_sr_content,
        default_us_ids=default_us_ids,
        include_default_sets=props.us_include_default_sets,
        default_weight=props.us_default_signal_weight,
        min_shared_tokens=max(1, props.us_name_similarity_min_tokens),
        mode=mode,
        coherence_by_us=coherence_by_us,
    )

    # Version history overlap signal.
    counters["version_history"] = _emit_pairwise_overlaps(
        session=session,
        assessment_id=assessment_id,
        instance_id=instance_id,
        us_to_sr_ids=us_to_sr_vh,
        us_by_id=us_by_id,
        default_us_ids=default_us_ids,
        sr_by_id=sr_by_id,
        signal_type="version_history",
        min_shared=max(1, props.us_min_shared_records),
        include_default_sets=props.us_include_default_sets,
        default_weight=props.us_default_signal_weight,
        mode=mode,
        coherence_by_us=coherence_by_us,
    )

    # Temporal sequence signal.
    counters["temporal_sequence"] = _emit_sequence_overlaps(
        session=session,
        assessment_id=assessment_id,
        instance_id=instance_id,
        update_sets=update_sets,
        us_to_sr_ids=us_to_sr_content,
        default_us_ids=default_us_ids,
        include_default_sets=props.us_include_default_sets,
        default_weight=props.us_default_signal_weight,
        gap_threshold_minutes=max(5, props.temporal_gap_threshold_minutes),
        signal_type="temporal_sequence",
        mode=mode,
        coherence_by_us=coherence_by_us,
    )

    # Author sequence signal.
    counters["author_sequence"] = _emit_author_sequence_overlaps(
        session=session,
        assessment_id=assessment_id,
        instance_id=instance_id,
        update_sets=update_sets,
        us_to_sr_ids=us_to_sr_content,
        default_us_ids=default_us_ids,
        include_default_sets=props.us_include_default_sets,
        default_weight=props.us_default_signal_weight,
        gap_threshold_minutes=max(60, props.temporal_gap_threshold_minutes * 4),
        mode=mode,
        coherence_by_us=coherence_by_us,
    )

    session.commit()

    return {
        "success": True,
        "content_overlaps": counters["content"],
        "name_overlaps": counters["name_similarity"],
        "vh_overlaps": counters["version_history"],
        "temporal_sequence_overlaps": counters["temporal_sequence"],
        "author_sequence_overlaps": counters["author_sequence"],
        "artifact_links_created": len(links),
        "update_sets_analyzed": len(update_sets),
        "mode": mode,
        "errors": [],
    }


def _delete_existing(session: Session, assessment_id: int) -> None:
    existing_links = list(
        session.exec(select(UpdateSetArtifactLink).where(UpdateSetArtifactLink.assessment_id == assessment_id)).all()
    )
    for row in existing_links:
        session.delete(row)
    session.flush()

    existing_overlaps = list(
        session.exec(select(UpdateSetOverlap).where(UpdateSetOverlap.assessment_id == assessment_id)).all()
    )
    for row in existing_overlaps:
        session.delete(row)
    session.flush()


def _get_customized_anchor_ids(scan_results: Sequence[ScanResult]) -> Set[int]:
    anchors: Set[int] = set()
    for sr in scan_results:
        if sr.id is None:
            continue
        if sr.origin_type in {OriginType.modified_ootb, OriginType.net_new_customer}:
            anchors.add(int(sr.id))
    return anchors


def _expand_relevant_scope(session: Session, assessment_id: int, anchor_ids: Set[int]) -> Set[int]:
    """Expand from customized anchors using obvious structural/code relationships."""
    if not anchor_ids:
        return set()

    expanded = set(anchor_ids)

    code_refs = list(
        session.exec(select(CodeReference).where(CodeReference.assessment_id == assessment_id)).all()
    )
    for ref in code_refs:
        if ref.source_scan_result_id in expanded:
            if ref.target_scan_result_id is not None:
                expanded.add(int(ref.target_scan_result_id))
        if ref.target_scan_result_id is not None and int(ref.target_scan_result_id) in expanded:
            expanded.add(int(ref.source_scan_result_id))

    structural = list(
        session.exec(
            select(StructuralRelationship).where(StructuralRelationship.assessment_id == assessment_id)
        ).all()
    )
    for rel in structural:
        if rel.parent_scan_result_id in expanded or rel.child_scan_result_id in expanded:
            expanded.add(int(rel.parent_scan_result_id))
            expanded.add(int(rel.child_scan_result_id))

    return expanded


def _build_artifact_links(
    *,
    session: Session,
    assessment_id: int,
    instance_id: int,
    scoped_sr_ids: Set[int],
    sr_by_id: Dict[int, ScanResult],
    sr_by_sys_id: Dict[str, ScanResult],
    sr_by_update_name: Dict[str, ScanResult],
    us_by_id: Dict[int, UpdateSet],
    us_by_sn_sys_id: Dict[str, UpdateSet],
) -> List[UpdateSetArtifactLink]:
    links: Dict[Tuple[int, int, str], UpdateSetArtifactLink] = {}

    def add_link(
        scan_result_id: int,
        update_set_id: int,
        link_source: str,
        *,
        is_current: bool,
        confidence: float,
        evidence: Dict[str, Any],
    ) -> None:
        if scan_result_id not in scoped_sr_ids:
            return
        if update_set_id not in us_by_id:
            return

        key = (scan_result_id, update_set_id, link_source)
        if key in links:
            return
        links[key] = UpdateSetArtifactLink(
            instance_id=instance_id,
            assessment_id=assessment_id,
            scan_result_id=scan_result_id,
            update_set_id=update_set_id,
            link_source=link_source,
            is_current=is_current,
            confidence=confidence,
            evidence_json=json.dumps(evidence, sort_keys=True),
        )

    # 1) Current mapping from scan_result.update_set_id.
    for sr_id in sorted(scoped_sr_ids):
        sr = sr_by_id.get(sr_id)
        if not sr or sr.update_set_id is None:
            continue
        add_link(
            scan_result_id=sr_id,
            update_set_id=int(sr.update_set_id),
            link_source="scan_result_current",
            is_current=True,
            confidence=1.0,
            evidence={"source": "scan_result.update_set_id"},
        )

    # 2) Customer update XML mapping.
    cux_records = list(
        session.exec(
            select(CustomerUpdateXML).where(
                CustomerUpdateXML.instance_id == instance_id,
                CustomerUpdateXML.update_set_id.is_not(None),
            )
        ).all()
    )

    for cux in cux_records:
        if cux.update_set_id is None:
            continue

        sr: Optional[ScanResult] = None
        if cux.target_sys_id:
            sr = sr_by_sys_id.get(cux.target_sys_id)
        if sr is None and cux.name:
            sr = sr_by_update_name.get(cux.name)
        if sr is None or sr.id is None:
            continue

        add_link(
            scan_result_id=int(sr.id),
            update_set_id=int(cux.update_set_id),
            link_source="customer_update_xml",
            is_current=bool(sr.update_set_id == cux.update_set_id),
            confidence=1.0,
            evidence={
                "source": "customer_update_xml",
                "cux_sn_sys_id": cux.sn_sys_id,
                "target_sys_id": cux.target_sys_id,
                "name": cux.name,
            },
        )

    # 3) Version history mapping via source update set sys_id.
    update_names = [sr.sys_update_name for sr in sr_by_id.values() if sr.sys_update_name]
    if update_names:
        vh_records = list(
            session.exec(
                select(VersionHistory).where(
                    VersionHistory.instance_id == instance_id,
                    VersionHistory.source_table == "sys_update_set",
                    VersionHistory.source_sys_id.is_not(None),
                    VersionHistory.sys_update_name.in_(update_names),
                )
            ).all()
        )

        for vh in vh_records:
            if not vh.source_sys_id:
                continue
            us = us_by_sn_sys_id.get(vh.source_sys_id)
            sr = sr_by_update_name.get(vh.sys_update_name)
            if not us or us.id is None or not sr or sr.id is None:
                continue

            add_link(
                scan_result_id=int(sr.id),
                update_set_id=int(us.id),
                link_source="version_history",
                is_current=bool(sr.update_set_id == us.id),
                confidence=0.9,
                evidence={
                    "source": "version_history",
                    "vh_sn_sys_id": vh.sn_sys_id,
                    "vh_state": vh.state,
                    "source_sys_id": vh.source_sys_id,
                },
            )

    return list(links.values())


def _map_links_by_us(
    links: Sequence[UpdateSetArtifactLink],
    link_sources: Set[str],
) -> DefaultDict[int, Set[int]]:
    mapping: DefaultDict[int, Set[int]] = defaultdict(set)
    for link in links:
        if link.link_source in link_sources:
            mapping[int(link.update_set_id)].add(int(link.scan_result_id))
    return mapping


def _emit_pairwise_overlaps(
    *,
    session: Session,
    assessment_id: int,
    instance_id: int,
    us_to_sr_ids: Dict[int, Set[int]],
    us_by_id: Dict[int, UpdateSet],
    default_us_ids: Set[int],
    sr_by_id: Dict[int, ScanResult],
    signal_type: str,
    min_shared: int,
    include_default_sets: bool,
    default_weight: float,
    mode: str,
    coherence_by_us: Dict[int, float],
) -> int:
    count = 0
    us_ids = sorted(uid for uid, members in us_to_sr_ids.items() if members)

    for us_a_id, us_b_id in combinations(us_ids, 2):
        shared_ids = us_to_sr_ids[us_a_id] & us_to_sr_ids[us_b_id]
        if len(shared_ids) < min_shared:
            continue

        includes_default = us_a_id in default_us_ids or us_b_id in default_us_ids
        if includes_default and not include_default_sets:
            continue

        min_size = min(len(us_to_sr_ids[us_a_id]), len(us_to_sr_ids[us_b_id]))
        base_score = (len(shared_ids) / min_size) if min_size > 0 else 0.0

        coherence_payload = _coherence_payload(us_a_id, us_b_id, coherence_by_us)
        score = _merge_score(base_score, coherence_payload.get("avg"), mode)
        score = _apply_default_weight(score, includes_default, default_weight)

        shared_details = [
            {
                "scan_result_id": sid,
                "name": sr_by_id[sid].name if sid in sr_by_id else None,
                "table": sr_by_id[sid].table_name if sid in sr_by_id else None,
            }
            for sid in sorted(shared_ids)
        ]

        evidence = {
            "signal_type": signal_type,
            "mode": mode,
            "shared_scan_result_ids": sorted(shared_ids),
            "shared_details": shared_details,
            "includes_default": includes_default,
            "coherence": coherence_payload,
        }

        session.add(
            UpdateSetOverlap(
                instance_id=instance_id,
                assessment_id=assessment_id,
                update_set_a_id=us_a_id,
                update_set_b_id=us_b_id,
                shared_record_count=len(shared_ids),
                shared_records_json=json.dumps(shared_details, sort_keys=True),
                overlap_score=round(score, 4),
                signal_type=signal_type,
                evidence_json=json.dumps(evidence, sort_keys=True),
            )
        )
        count += 1

    session.flush()
    return count


def _emit_name_overlaps(
    *,
    session: Session,
    assessment_id: int,
    instance_id: int,
    update_sets: Sequence[UpdateSet],
    us_to_sr_ids: Dict[int, Set[int]],
    default_us_ids: Set[int],
    include_default_sets: bool,
    default_weight: float,
    min_shared_tokens: int,
    mode: str,
    coherence_by_us: Dict[int, float],
) -> int:
    parsed: Dict[int, Dict[str, Set[str]]] = {}
    for us in update_sets:
        if us.id is None:
            continue
        us_id = int(us.id)
        parsed[us_id] = {
            "tickets": {t.upper() for t in _TICKET_PATTERN.findall(us.name or "")},
            "tokens": _name_tokens(us.name or ""),
        }

    count = 0
    for us_a_id, us_b_id in combinations(sorted(parsed.keys()), 2):
        includes_default = us_a_id in default_us_ids or us_b_id in default_us_ids
        if includes_default and not include_default_sets:
            continue

        shared_tickets = parsed[us_a_id]["tickets"] & parsed[us_b_id]["tickets"]
        shared_tokens = parsed[us_a_id]["tokens"] & parsed[us_b_id]["tokens"]
        if len(shared_tickets) == 0 and len(shared_tokens) < min_shared_tokens:
            continue

        token_score = min(1.0, 0.4 + 0.1 * len(shared_tokens) + 0.2 * len(shared_tickets))
        coherence_payload = _coherence_payload(us_a_id, us_b_id, coherence_by_us)
        score = _merge_score(token_score, coherence_payload.get("avg"), mode)
        score = _apply_default_weight(score, includes_default, default_weight)

        shared_records = sorted((us_to_sr_ids.get(us_a_id, set()) & us_to_sr_ids.get(us_b_id, set())))
        evidence = {
            "signal_type": "name_similarity",
            "mode": mode,
            "shared_tickets": sorted(shared_tickets),
            "shared_tokens": sorted(shared_tokens),
            "includes_default": includes_default,
            "coherence": coherence_payload,
            "name_a": us_name(parsed, us_a_id, update_sets),
            "name_b": us_name(parsed, us_b_id, update_sets),
        }

        session.add(
            UpdateSetOverlap(
                instance_id=instance_id,
                assessment_id=assessment_id,
                update_set_a_id=us_a_id,
                update_set_b_id=us_b_id,
                shared_record_count=len(shared_records),
                shared_records_json=json.dumps(
                    {
                        "shared_scan_result_ids": shared_records,
                        "shared_tickets": sorted(shared_tickets),
                        "shared_tokens": sorted(shared_tokens),
                    },
                    sort_keys=True,
                ),
                overlap_score=round(score, 4),
                signal_type="name_similarity",
                evidence_json=json.dumps(evidence, sort_keys=True),
            )
        )
        count += 1

    session.flush()
    return count


def _emit_sequence_overlaps(
    *,
    session: Session,
    assessment_id: int,
    instance_id: int,
    update_sets: Sequence[UpdateSet],
    us_to_sr_ids: Dict[int, Set[int]],
    default_us_ids: Set[int],
    include_default_sets: bool,
    default_weight: float,
    gap_threshold_minutes: int,
    signal_type: str,
    mode: str,
    coherence_by_us: Dict[int, float],
) -> int:
    ordered: List[Tuple[UpdateSet, datetime]] = []
    for us in update_sets:
        if us.id is None:
            continue
        ts = _us_timestamp(us)
        if ts is None:
            continue
        ordered.append((us, ts))

    ordered.sort(key=lambda item: item[1])
    count = 0

    for idx in range(1, len(ordered)):
        prev_us, prev_ts = ordered[idx - 1]
        curr_us, curr_ts = ordered[idx]
        if prev_us.id is None or curr_us.id is None:
            continue

        us_a_id = int(prev_us.id)
        us_b_id = int(curr_us.id)
        gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
        if gap_minutes > gap_threshold_minutes:
            continue

        # Keep only sequence links where at least one side has artifacts in scope.
        if not us_to_sr_ids.get(us_a_id) and not us_to_sr_ids.get(us_b_id):
            continue

        includes_default = us_a_id in default_us_ids or us_b_id in default_us_ids
        if includes_default and not include_default_sets:
            continue

        proximity_score = max(0.0, 1.0 - (gap_minutes / max(1.0, gap_threshold_minutes)))
        base_score = 0.5 + (0.5 * proximity_score)
        coherence_payload = _coherence_payload(us_a_id, us_b_id, coherence_by_us)
        score = _merge_score(base_score, coherence_payload.get("avg"), mode)
        score = _apply_default_weight(score, includes_default, default_weight)

        shared_records = sorted((us_to_sr_ids.get(us_a_id, set()) & us_to_sr_ids.get(us_b_id, set())))
        evidence = {
            "signal_type": signal_type,
            "mode": mode,
            "gap_minutes": round(gap_minutes, 2),
            "threshold_minutes": gap_threshold_minutes,
            "time_a": prev_ts.isoformat(),
            "time_b": curr_ts.isoformat(),
            "includes_default": includes_default,
            "coherence": coherence_payload,
        }

        session.add(
            UpdateSetOverlap(
                instance_id=instance_id,
                assessment_id=assessment_id,
                update_set_a_id=us_a_id,
                update_set_b_id=us_b_id,
                shared_record_count=len(shared_records),
                shared_records_json=json.dumps({"shared_scan_result_ids": shared_records}, sort_keys=True),
                overlap_score=round(score, 4),
                signal_type=signal_type,
                evidence_json=json.dumps(evidence, sort_keys=True),
            )
        )
        count += 1

    session.flush()
    return count


def _emit_author_sequence_overlaps(
    *,
    session: Session,
    assessment_id: int,
    instance_id: int,
    update_sets: Sequence[UpdateSet],
    us_to_sr_ids: Dict[int, Set[int]],
    default_us_ids: Set[int],
    include_default_sets: bool,
    default_weight: float,
    gap_threshold_minutes: int,
    mode: str,
    coherence_by_us: Dict[int, float],
) -> int:
    by_author: DefaultDict[str, List[Tuple[UpdateSet, datetime]]] = defaultdict(list)

    for us in update_sets:
        if us.id is None:
            continue
        ts = _us_timestamp(us)
        author = (us.completed_by or us.sys_updated_by or us.sys_created_by or "").strip()
        if not ts or not author:
            continue
        by_author[author].append((us, ts))

    count = 0
    for author, rows in by_author.items():
        rows.sort(key=lambda item: item[1])
        for idx in range(1, len(rows)):
            prev_us, prev_ts = rows[idx - 1]
            curr_us, curr_ts = rows[idx]
            if prev_us.id is None or curr_us.id is None:
                continue

            us_a_id = int(prev_us.id)
            us_b_id = int(curr_us.id)
            if not us_to_sr_ids.get(us_a_id) and not us_to_sr_ids.get(us_b_id):
                continue

            gap_minutes = (curr_ts - prev_ts).total_seconds() / 60.0
            if gap_minutes > gap_threshold_minutes:
                continue

            includes_default = us_a_id in default_us_ids or us_b_id in default_us_ids
            if includes_default and not include_default_sets:
                continue

            base_score = max(0.0, 0.65 - (gap_minutes / max(1.0, gap_threshold_minutes)) * 0.25)
            coherence_payload = _coherence_payload(us_a_id, us_b_id, coherence_by_us)
            score = _merge_score(base_score, coherence_payload.get("avg"), mode)
            score = _apply_default_weight(score, includes_default, default_weight)

            shared_records = sorted((us_to_sr_ids.get(us_a_id, set()) & us_to_sr_ids.get(us_b_id, set())))
            evidence = {
                "signal_type": "author_sequence",
                "mode": mode,
                "author": author,
                "gap_minutes": round(gap_minutes, 2),
                "threshold_minutes": gap_threshold_minutes,
                "includes_default": includes_default,
                "coherence": coherence_payload,
            }

            session.add(
                UpdateSetOverlap(
                    instance_id=instance_id,
                    assessment_id=assessment_id,
                    update_set_a_id=us_a_id,
                    update_set_b_id=us_b_id,
                    shared_record_count=len(shared_records),
                    shared_records_json=json.dumps({"shared_scan_result_ids": shared_records}, sort_keys=True),
                    overlap_score=round(score, 4),
                    signal_type="author_sequence",
                    evidence_json=json.dumps(evidence, sort_keys=True),
                )
            )
            count += 1

    session.flush()
    return count


def _compute_us_coherence(
    *,
    session: Session,
    assessment_id: int,
    us_to_sr_ids: Dict[int, Set[int]],
    sr_by_id: Dict[int, ScanResult],
) -> Dict[int, float]:
    code_refs = list(session.exec(select(CodeReference).where(CodeReference.assessment_id == assessment_id)).all())
    structural = list(
        session.exec(select(StructuralRelationship).where(StructuralRelationship.assessment_id == assessment_id)).all()
    )

    out: Dict[int, float] = {}
    for us_id, sr_ids in us_to_sr_ids.items():
        if not sr_ids:
            out[us_id] = 0.0
            continue

        members = [sr_by_id[sid] for sid in sr_ids if sid in sr_by_id]
        if not members:
            out[us_id] = 0.0
            continue

        texts = [
            _tokens_for_text(" ".join(filter(None, [m.ai_summary, m.ai_observations, m.name])))
            for m in members
        ]
        text_score = _average_pairwise_jaccard(texts)

        table_counts = Counter(m.meta_target_table or m.table_name or "unknown" for m in members)
        table_score = (max(table_counts.values()) / len(members)) if members else 0.0

        dev_counts = Counter((m.sys_updated_by or m.sys_created_by or "unknown") for m in members)
        developer_score = (max(dev_counts.values()) / len(members)) if members else 0.0

        internal_code = 0
        for ref in code_refs:
            if ref.source_scan_result_id in sr_ids and ref.target_scan_result_id in sr_ids:
                internal_code += 1
        code_density = min(1.0, internal_code / max(1, len(members) - 1))

        internal_struct = 0
        for rel in structural:
            if rel.parent_scan_result_id in sr_ids and rel.child_scan_result_id in sr_ids:
                internal_struct += 1
        structural_density = min(1.0, internal_struct / max(1, len(members) - 1))

        score = (
            0.25 * text_score
            + 0.20 * table_score
            + 0.15 * developer_score
            + 0.20 * code_density
            + 0.20 * structural_density
        )
        out[us_id] = round(min(1.0, max(0.0, score)), 4)

    return out


def _coherence_payload(us_a_id: int, us_b_id: int, coherence_by_us: Dict[int, float]) -> Dict[str, Optional[float]]:
    coh_a = coherence_by_us.get(us_a_id)
    coh_b = coherence_by_us.get(us_b_id)
    if coh_a is None or coh_b is None:
        return {"a": coh_a, "b": coh_b, "avg": None}
    return {"a": coh_a, "b": coh_b, "avg": round((coh_a + coh_b) / 2.0, 4)}


def _merge_score(base_score: float, coherence_avg: Optional[float], mode: str) -> float:
    if mode != "enriched" or coherence_avg is None:
        return max(0.0, min(1.0, base_score))
    return max(0.0, min(1.0, (0.75 * base_score) + (0.25 * float(coherence_avg))))


def _apply_default_weight(score: float, includes_default: bool, default_weight: float) -> float:
    if includes_default:
        weighted = score * max(0.0, min(1.0, default_weight))
        return max(0.0, min(1.0, weighted))
    return max(0.0, min(1.0, score))


def _name_tokens(name: str) -> Set[str]:
    tokens = re.split(r"[^A-Za-z0-9]+", name.lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOP_TOKENS and not t.isdigit()}


def _tokens_for_text(text: str) -> Set[str]:
    tokens = re.split(r"[^A-Za-z0-9]+", text.lower())
    return {t for t in tokens if len(t) >= 3 and t not in _STOP_TOKENS and not t.isdigit()}


def _average_pairwise_jaccard(token_sets: Sequence[Set[str]]) -> float:
    if len(token_sets) < 2:
        return 0.5 if token_sets and token_sets[0] else 0.0

    scores: List[float] = []
    for a_idx, b_idx in combinations(range(len(token_sets)), 2):
        a = token_sets[a_idx]
        b = token_sets[b_idx]
        if not a and not b:
            scores.append(1.0)
            continue
        union = a | b
        if not union:
            scores.append(0.0)
            continue
        scores.append(len(a & b) / len(union))
    return sum(scores) / len(scores) if scores else 0.0


def _us_timestamp(us: UpdateSet) -> Optional[datetime]:
    return us.completed_on or us.install_date or us.sys_updated_on or us.sys_created_on


def us_name(parsed: Dict[int, Dict[str, Set[str]]], us_id: int, update_sets: Sequence[UpdateSet]) -> Optional[str]:
    del parsed
    for us in update_sets:
        if us.id is not None and int(us.id) == us_id:
            return us.name
    return None
