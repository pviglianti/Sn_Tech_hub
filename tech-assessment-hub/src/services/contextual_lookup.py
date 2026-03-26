"""Contextual lookup service -- local-first data enrichment with SN fallback.

Used by AI pipeline stage handlers to gather context. Always checks local DB
first (TableDefinition, Fact cache, ScanResult, etc.), only queries ServiceNow
when data is missing and the context_enrichment property allows it.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..models import (
    Fact,
    Feature,
    FeatureScanResult,
    Instance,
    ScanResult,
    TableDefinition,
    UpdateSet,
    UpdateSetArtifactLink,
)
from .sn_client import ServiceNowClientError
from .sn_client_factory import create_client_for_instance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FACT_MODULE = "tech_assessment"
_FACT_TOPIC_TYPE = "reference_lookup"
_CACHE_TTL_HOURS = 12

# Reference detection patterns.
# Order matters: longer prefixes must come before shorter ones
# (e.g. WOTASK before WOT before WO) to avoid partial matches.
_REFERENCE_PATTERNS: List[Dict[str, str]] = [
    {"prefix": "WOTASK", "type": "wm_task", "table": "wm_task"},
    {"prefix": "WOT", "type": "wm_task", "table": "wm_task"},
    {"prefix": "WO", "type": "wm_order", "table": "wm_order"},
    {"prefix": "RITM", "type": "sc_req_item", "table": "sc_req_item"},
    {"prefix": "REQ", "type": "sc_request", "table": "sc_request"},
    {"prefix": "INC", "type": "incident", "table": "incident"},
    {"prefix": "CHG", "type": "change_request", "table": "change_request"},
    {"prefix": "PRB", "type": "problem", "table": "problem"},
    {"prefix": "TASK", "type": "task", "table": "task"},
    {"prefix": "KB", "type": "kb_knowledge", "table": "kb_knowledge"},
]

# Build a single compiled regex that matches all patterns.
# Uses alternation with longest-prefix-first ordering.
_PREFIXES = "|".join(p["prefix"] for p in _REFERENCE_PATTERNS)
_REF_REGEX = re.compile(rf"\b({_PREFIXES})(\d{{5,10}})\b")

# Build a quick lookup from prefix string to pattern metadata.
_PREFIX_MAP: Dict[str, Dict[str, str]] = {p["prefix"]: p for p in _REFERENCE_PATTERNS}


# ---------------------------------------------------------------------------
# 1. detect_references
# ---------------------------------------------------------------------------

def detect_references(text: str) -> List[Dict[str, str]]:
    """Detect ServiceNow reference patterns in text.

    Returns a deduplicated list of dicts:
        [{"type": "incident", "number": "INC0012345", "table": "incident"}, ...]
    """
    if not text:
        return []

    seen: set[str] = set()
    results: List[Dict[str, str]] = []

    for match in _REF_REGEX.finditer(text):
        prefix = match.group(1)
        digits = match.group(2)
        number = f"{prefix}{digits}"

        if number in seen:
            continue
        seen.add(number)

        meta = _PREFIX_MAP[prefix]
        results.append({
            "type": meta["type"],
            "number": number,
            "table": meta["table"],
        })

    return results


# ---------------------------------------------------------------------------
# 2. check_local_table_data
# ---------------------------------------------------------------------------

def check_local_table_data(session: Session, instance_id: int, table_name: str) -> bool:
    """Check if we have a TableDefinition for *table_name* on this instance."""
    row = session.exec(
        select(TableDefinition)
        .where(TableDefinition.instance_id == instance_id)
        .where(TableDefinition.name == table_name)
        .limit(1)
    ).first()
    return row is not None


# ---------------------------------------------------------------------------
# 3. lookup_reference_local
# ---------------------------------------------------------------------------

def _fact_key_for_ref(table: str, number: str) -> str:
    return f"ref:{table}:{number}"


def lookup_reference_local(
    session: Session,
    instance_id: int,
    ref: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Try to find a referenced record in local Fact cache.

    Returns the cached data dict, or None if not found / expired.
    """
    key = _fact_key_for_ref(ref["table"], ref["number"])
    now = datetime.utcnow()

    cached = session.exec(
        select(Fact)
        .where(Fact.instance_id == instance_id)
        .where(Fact.module == _FACT_MODULE)
        .where(Fact.topic_type == _FACT_TOPIC_TYPE)
        .where(Fact.topic_value == ref["table"])
        .where(Fact.fact_key == key)
        .limit(1)
    ).first()

    if cached and cached.valid_until and cached.valid_until >= now:
        try:
            return json.loads(cached.fact_value or "{}")
        except Exception:
            return None

    return None


# ---------------------------------------------------------------------------
# 4. lookup_reference_remote
# ---------------------------------------------------------------------------

_REMOTE_FIELDS = [
    "number",
    "short_description",
    "description",
    "state",
    "priority",
    "category",
]


def lookup_reference_remote(
    session: Session,
    instance_id: int,
    ref: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Query ServiceNow for a referenced record and cache as a Fact.

    Returns the record dict, or None on failure / not found.
    """
    instance = session.get(Instance, instance_id)
    if not instance:
        logger.warning("lookup_reference_remote: Instance %s not found", instance_id)
        return None

    try:
        client = create_client_for_instance(instance)
        records = client.get_records(
            table=ref["table"],
            query=f"number={ref['number']}",
            fields=_REMOTE_FIELDS,
            limit=1,
        )
    except (ServiceNowClientError, Exception) as exc:
        logger.warning(
            "lookup_reference_remote: SN query failed for %s: %s",
            ref["number"],
            exc,
        )
        return None

    if not records:
        return None

    record = records[0]

    # Cache as Fact
    now = datetime.utcnow()
    valid_until = now + timedelta(hours=_CACHE_TTL_HOURS)
    key = _fact_key_for_ref(ref["table"], ref["number"])

    existing = session.exec(
        select(Fact)
        .where(Fact.instance_id == instance_id)
        .where(Fact.module == _FACT_MODULE)
        .where(Fact.topic_type == _FACT_TOPIC_TYPE)
        .where(Fact.topic_value == ref["table"])
        .where(Fact.fact_key == key)
        .limit(1)
    ).first()

    payload = json.dumps(record, sort_keys=True)

    if existing:
        existing.fact_value = payload
        existing.confidence = 1.0
        existing.valid_until = valid_until
        existing.updated_at = now
    else:
        existing = Fact(
            instance_id=instance_id,
            module=_FACT_MODULE,
            topic_type=_FACT_TOPIC_TYPE,
            topic_value=ref["table"],
            fact_key=key,
            fact_value=payload,
            created_by="computed",
            output_type="reference",
            deliverable_target="observation_pipeline",
            confidence=1.0,
            valid_until=valid_until,
            source_table=ref["table"],
            computed_at=now,
            created_at=now,
            updated_at=now,
        )
    session.add(existing)
    session.commit()

    return record


# ---------------------------------------------------------------------------
# 5. resolve_references
# ---------------------------------------------------------------------------

def resolve_references(
    session: Session,
    instance_id: int,
    text: str,
    enrichment_mode: str = "auto",
) -> List[Dict[str, Any]]:
    """Detect and resolve ServiceNow references in *text*.

    Args:
        session: Active DB session.
        instance_id: Instance to scope lookups to.
        text: Free-form text to scan for reference patterns.
        enrichment_mode: One of "auto", "always", "never".
            - "never": detect only, no resolution.
            - "auto": resolve locally first, remote fallback if missing.
            - "always": always query remote (fresh data), even if local exists.

    Returns:
        List of dicts with keys: type, number, table, resolved, data, source.
    """
    refs = detect_references(text)
    if not refs:
        return []

    if enrichment_mode == "never":
        return [
            {
                **ref,
                "resolved": False,
                "data": None,
                "source": None,
            }
            for ref in refs
        ]

    results: List[Dict[str, Any]] = []
    for ref in refs:
        data: Optional[Dict[str, Any]] = None
        source: Optional[str] = None

        if enrichment_mode == "auto":
            # Try local first
            data = lookup_reference_local(session, instance_id, ref)
            if data is not None:
                source = "local"
            else:
                data = lookup_reference_remote(session, instance_id, ref)
                if data is not None:
                    source = "remote"
        elif enrichment_mode == "always":
            data = lookup_reference_remote(session, instance_id, ref)
            if data is not None:
                source = "remote"

        results.append({
            **ref,
            "resolved": data is not None,
            "data": data,
            "source": source,
        })

    return results


# ---------------------------------------------------------------------------
# 6. gather_artifact_context
# ---------------------------------------------------------------------------

def gather_artifact_context(
    session: Session,
    instance_id: int,
    scan_result_id: int,
    enrichment_mode: str = "auto",
    graph: Optional[Any] = None,
) -> Dict[str, Any]:
    """Gather full context for a single artifact (ScanResult).

    Returns a dict suitable for injection into MCP prompts:
        - artifact: basic ScanResult info
        - update_sets: related update sets via UpdateSetArtifactLink
        - human_context: observations, disposition, feature memberships
        - references: resolved references found in text fields
        - has_local_table_data: whether we have TableDefinition for this table
    """
    sr = session.get(ScanResult, scan_result_id)
    if not sr:
        return {
            "artifact": None,
            "update_sets": [],
            "human_context": {},
            "references": [],
            "has_local_table_data": False,
        }

    # --- artifact basics ---
    artifact_info: Dict[str, Any] = {
        "id": sr.id,
        "name": sr.name,
        "table_name": sr.table_name,
        "sys_class_name": sr.sys_class_name,
        "origin_type": sr.origin_type.value if sr.origin_type else None,
        "sys_id": sr.sys_id,
    }

    # --- update sets via link table ---
    us_links = session.exec(
        select(UpdateSetArtifactLink)
        .where(UpdateSetArtifactLink.scan_result_id == sr.id)
    ).all()

    update_sets_info: List[Dict[str, Any]] = []
    us_text_parts: List[str] = []
    for link in us_links:
        us = session.get(UpdateSet, link.update_set_id)
        if us:
            us_entry: Dict[str, Any] = {
                "id": us.id,
                "name": us.name,
                "description": us.description,
                "state": us.state,
                "link_source": link.link_source,
                "is_current": link.is_current,
            }
            update_sets_info.append(us_entry)
            # Collect text for reference scanning
            if us.name:
                us_text_parts.append(us.name)
            if us.description:
                us_text_parts.append(us.description)

    # --- human context (observations, disposition, features) ---
    feature_links = session.exec(
        select(FeatureScanResult)
        .where(FeatureScanResult.scan_result_id == sr.id)
    ).all()

    features_info: List[Dict[str, Any]] = []
    for fl in feature_links:
        feat = session.get(Feature, fl.feature_id)
        if feat:
            features_info.append({
                "id": feat.id,
                "name": feat.name,
                "disposition": feat.disposition.value if feat.disposition else None,
            })

    human_context: Dict[str, Any] = {
        "observations": sr.observations,
        "ai_observations": sr.ai_observations,
        "disposition": sr.disposition.value if sr.disposition else None,
        "review_status": sr.review_status.value if sr.review_status else None,
        "recommendation": sr.recommendation,
        "features": features_info,
    }

    # --- reference resolution ---
    # Collect all text sources for reference detection
    text_parts: List[str] = []
    if sr.observations:
        text_parts.append(sr.observations)
    if sr.ai_observations:
        text_parts.append(sr.ai_observations)
    if sr.finding_description:
        text_parts.append(sr.finding_description)
    text_parts.extend(us_text_parts)

    combined_text = " ".join(text_parts)
    references = resolve_references(session, instance_id, combined_text, enrichment_mode)

    # --- local table data flag ---
    has_local = check_local_table_data(session, instance_id, sr.table_name)

    # --- relationship graph enrichment (optional) ---
    graph_enrichment: Dict[str, Any] = {}
    if graph is not None:
        all_neighbors = graph.neighbors(scan_result_id, min_weight=0.0)
        customized_neighbors = graph.customized_neighbors(scan_result_id, min_weight=0.0)

        related_customizations = []
        for nid in customized_neighbors:
            n_sr = session.get(ScanResult, nid)
            if n_sr:
                related_customizations.append({
                    "id": nid,
                    "name": n_sr.name,
                    "table": n_sr.table_name,
                    "relationship_types": graph.edge_types(scan_result_id, nid),
                    "weight": graph.edge_weight(scan_result_id, nid),
                })

        graph_enrichment = {
            "related_customizations": related_customizations,
            "cross_reference_summary": {
                "total_neighbors": len(all_neighbors),
                "total_related_customizations": len(customized_neighbors),
            },
        }

    return {
        "artifact": artifact_info,
        "update_sets": update_sets_info,
        "human_context": human_context,
        "references": references,
        "has_local_table_data": has_local,
        **graph_enrichment,
    }
