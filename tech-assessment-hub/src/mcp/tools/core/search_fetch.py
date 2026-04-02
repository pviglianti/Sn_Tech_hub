"""MCP search/fetch tools for ChatGPT app and deep research compatibility.

These tools intentionally follow the standard `search(query)` / `fetch(id)`
shapes so the existing Tech Assessment Hub MCP endpoint can be connected from
ChatGPT developer mode and used by deep research.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import (
    Assessment,
    Feature,
    FeatureRecommendation,
    FeatureScanResult,
    GeneralRecommendation,
    Instance,
    Scan,
    ScanResult,
)


SEARCH_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Natural-language search query for tech assessment knowledge.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

FETCH_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "Opaque document identifier returned by the search tool.",
        },
    },
    "required": ["id"],
    "additionalProperties": False,
}

_MAX_RESULTS = 10
_MAX_FETCH_TEXT_CHARS = 12000


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = str(url).strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def _app_path(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _result_urls(instance: Optional[Instance], result: ScanResult) -> Tuple[str, Dict[str, Optional[str]]]:
    base = _normalize_url(instance.url if instance else None)
    metadata_url = (
        f"{base}/sys_metadata.do?sys_id={result.sys_id}&sysparm_ignore_class=true"
        if base and result.sys_id
        else None
    )
    config_url = (
        f"{base}/{result.table_name}.do?sys_id={result.sys_id}"
        if base and result.table_name and result.sys_id
        else None
    )
    default_url = config_url or metadata_url or _app_path(f"/results/{result.id}")
    return default_url, {"config_record_url": config_url, "metadata_record_url": metadata_url}


def _score_text(query: str, tokens: Iterable[str], *fields: Any) -> int:
    haystack = " ".join(_normalize_text(field).lower() for field in fields if field is not None)
    if not haystack:
        return 0

    score = 0
    if query in haystack:
        score += 12
    for token in tokens:
        if token and token in haystack:
            score += 3
    return score


def _serialize_search_results(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"results": items}),
            }
        ]
    }


def _serialize_fetch_document(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload),
            }
        ]
    }


def _search_scan_results(session: Session, query_text: str, tokens: List[str]) -> List[Dict[str, Any]]:
    like_terms = [f"%{query_text}%"] + [f"%{token}%" for token in tokens if token]

    stmt = (
        select(ScanResult, Assessment, Instance)
        .join(Scan, ScanResult.scan_id == Scan.id)
        .join(Assessment, Scan.assessment_id == Assessment.id)
        .join(Instance, Assessment.instance_id == Instance.id)
        .where(
            or_(
                *[
                    func.lower(column).like(term)
                    for term in like_terms
                    for column in (
                        func.coalesce(ScanResult.name, ""),
                        func.coalesce(ScanResult.display_value, ""),
                        func.coalesce(ScanResult.table_name, ""),
                        func.coalesce(ScanResult.finding_title, ""),
                        func.coalesce(ScanResult.finding_description, ""),
                        func.coalesce(ScanResult.recommendation, ""),
                        func.coalesce(ScanResult.observations, ""),
                        func.coalesce(ScanResult.ai_summary, ""),
                        func.coalesce(ScanResult.ai_observations, ""),
                        func.coalesce(ScanResult.sys_update_name, ""),
                        func.coalesce(ScanResult.meta_target_table, ""),
                        func.coalesce(Assessment.name, ""),
                        func.coalesce(Assessment.number, ""),
                        func.coalesce(Instance.name, ""),
                    )
                ]
            )
        )
        .limit(200)
    )

    matches: List[Dict[str, Any]] = []
    for result, assessment, instance in session.exec(stmt).all():
        score = _score_text(
            query_text,
            tokens,
            result.name,
            result.display_value,
            result.table_name,
            result.finding_title,
            result.finding_description,
            result.recommendation,
            result.observations,
            result.ai_summary,
            result.ai_observations,
            result.sys_update_name,
            assessment.name,
            assessment.number,
            instance.name,
        )
        if score <= 0:
            continue
        url, _ = _result_urls(instance, result)
        title_parts = [assessment.number or f"Assessment {assessment.id}", result.table_name, result.name]
        matches.append(
            {
                "id": f"scan_result:{result.id}",
                "title": " | ".join(part for part in title_parts if part),
                "url": url,
                "_score": score,
                "_updated": result.sys_updated_on.isoformat() if result.sys_updated_on else "",
            }
        )
    return matches


def _search_features(session: Session, query_text: str, tokens: List[str]) -> List[Dict[str, Any]]:
    like_terms = [f"%{query_text}%"] + [f"%{token}%" for token in tokens if token]
    stmt = (
        select(Feature, Assessment)
        .join(Assessment, Feature.assessment_id == Assessment.id)
        .where(
            or_(
                *[
                    func.lower(column).like(term)
                    for term in like_terms
                    for column in (
                        func.coalesce(Feature.name, ""),
                        func.coalesce(Feature.description, ""),
                        func.coalesce(Feature.ai_summary, ""),
                        func.coalesce(Feature.recommendation, ""),
                        func.coalesce(Assessment.name, ""),
                        func.coalesce(Assessment.number, ""),
                    )
                ]
            )
        )
        .limit(100)
    )

    matches: List[Dict[str, Any]] = []
    for feature, assessment in session.exec(stmt).all():
        score = _score_text(
            query_text,
            tokens,
            feature.name,
            feature.description,
            feature.ai_summary,
            feature.recommendation,
            assessment.name,
            assessment.number,
        )
        if score <= 0:
            continue
        matches.append(
            {
                "id": f"feature:{feature.id}",
                "title": f"{assessment.number or f'Assessment {assessment.id}'} | Feature | {feature.name}",
                "url": _app_path(f"/assessments/{assessment.id}"),
                "_score": score,
                "_updated": feature.updated_at.isoformat() if feature.updated_at else "",
            }
        )
    return matches


def _search_general_recommendations(session: Session, query_text: str, tokens: List[str]) -> List[Dict[str, Any]]:
    like_terms = [f"%{query_text}%"] + [f"%{token}%" for token in tokens if token]
    stmt = (
        select(GeneralRecommendation, Assessment)
        .join(Assessment, GeneralRecommendation.assessment_id == Assessment.id)
        .where(
            or_(
                *[
                    func.lower(column).like(term)
                    for term in like_terms
                    for column in (
                        func.coalesce(GeneralRecommendation.title, ""),
                        func.coalesce(GeneralRecommendation.description, ""),
                        func.coalesce(GeneralRecommendation.category, ""),
                        func.coalesce(Assessment.name, ""),
                        func.coalesce(Assessment.number, ""),
                    )
                ]
            )
        )
        .limit(100)
    )

    matches: List[Dict[str, Any]] = []
    for recommendation, assessment in session.exec(stmt).all():
        score = _score_text(
            query_text,
            tokens,
            recommendation.title,
            recommendation.description,
            recommendation.category,
            assessment.name,
            assessment.number,
        )
        if score <= 0:
            continue
        kind = "Assessment Report" if recommendation.category == "assessment_report" else "Recommendation"
        matches.append(
            {
                "id": f"general_recommendation:{recommendation.id}",
                "title": f"{assessment.number or f'Assessment {assessment.id}'} | {kind} | {recommendation.title}",
                "url": _app_path(f"/assessments/{assessment.id}"),
                "_score": score,
                "_updated": recommendation.updated_at.isoformat() if recommendation.updated_at else "",
            }
        )
    return matches


def handle_search(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    raw_query = _normalize_text(params.get("query"))
    if not raw_query:
        raise ValueError("query is required")

    query_text = raw_query.lower()
    tokens = [token for token in query_text.split() if token]

    matches = []
    matches.extend(_search_scan_results(session, query_text, tokens))
    matches.extend(_search_features(session, query_text, tokens))
    matches.extend(_search_general_recommendations(session, query_text, tokens))

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(matches, key=lambda row: (-int(row["_score"]), row["_updated"]), reverse=False):
        item_id = str(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        deduped.append(
            {
                "id": item_id,
                "title": item["title"],
                "url": item["url"],
            }
        )
        if len(deduped) >= _MAX_RESULTS:
            break

    return _serialize_search_results(deduped)


def _format_json_block(value: Any) -> Optional[str]:
    if value in (None, "", [], {}):
        return None
    try:
        return json.dumps(value, indent=2, sort_keys=True)
    except Exception:
        return str(value)


def _truncate_text(text: str) -> str:
    if len(text) <= _MAX_FETCH_TEXT_CHARS:
        return text
    return text[:_MAX_FETCH_TEXT_CHARS].rstrip() + "\n\n[truncated]"


def _fetch_scan_result(session: Session, raw_id: str) -> Dict[str, Any]:
    _, _, suffix = raw_id.partition(":")
    try:
        result_id = int(suffix)
    except ValueError as exc:
        raise ValueError(f"Invalid scan result id: {raw_id}") from exc

    result = session.get(ScanResult, result_id)
    if not result:
        raise ValueError(f"Scan result not found: {result_id}")

    scan = session.get(Scan, result.scan_id)
    assessment = session.get(Assessment, scan.assessment_id) if scan else None
    instance = session.get(Instance, assessment.instance_id) if assessment else None
    url, extra_urls = _result_urls(instance, result)

    feature_links = session.exec(
        select(FeatureScanResult, Feature)
        .join(Feature, FeatureScanResult.feature_id == Feature.id)
        .where(FeatureScanResult.scan_result_id == result_id)
    ).all()

    features = [
        {
            "feature_id": feature.id,
            "name": feature.name,
            "is_primary": link.is_primary,
            "membership_type": link.membership_type,
            "assignment_source": link.assignment_source,
        }
        for link, feature in feature_links
    ]

    sections = [
        f"Assessment: {assessment.number} - {assessment.name}" if assessment else None,
        f"Instance: {instance.name} ({instance.url})" if instance and instance.url else (f"Instance: {instance.name}" if instance else None),
        f"Artifact: {result.name}",
        f"Table: {result.table_name}",
        f"Display value: {result.display_value}" if result.display_value else None,
        f"Origin type: {result.origin_type.value}" if result.origin_type else None,
        f"Head owner: {result.head_owner.value}" if result.head_owner else None,
        f"Review status: {result.review_status.value}" if result.review_status else None,
        f"Disposition: {result.disposition.value}" if result.disposition else None,
        f"Recommendation: {result.recommendation}" if result.recommendation else None,
        f"Observations: {result.observations}" if result.observations else None,
        f"AI summary: {result.ai_summary}" if result.ai_summary else None,
        f"AI observations: {result.ai_observations}" if result.ai_observations else None,
        f"Finding title: {result.finding_title}" if result.finding_title else None,
        f"Finding description: {result.finding_description}" if result.finding_description else None,
        f"Scope: {result.sys_scope}" if result.sys_scope else None,
        f"Package: {result.sys_package}" if result.sys_package else None,
        f"Update name: {result.sys_update_name}" if result.sys_update_name else None,
        f"Target table: {result.meta_target_table}" if result.meta_target_table else None,
        f"Updated by: {result.sys_updated_by}" if result.sys_updated_by else None,
        f"Updated on: {result.sys_updated_on.isoformat()}" if result.sys_updated_on else None,
        f"Created by: {result.sys_created_by}" if result.sys_created_by else None,
        f"Created on: {result.sys_created_on.isoformat()}" if result.sys_created_on else None,
    ]

    if features:
        sections.append("Features:\n" + "\n".join(f"- {f['name']} (primary={f['is_primary']})" for f in features))

    raw_data = None
    if result.raw_data_json:
        try:
            raw_data = json.loads(result.raw_data_json)
        except json.JSONDecodeError:
            raw_data = result.raw_data_json
    raw_block = _format_json_block(raw_data)
    if raw_block:
        sections.append("Raw data:\n" + raw_block)

    text = _truncate_text("\n\n".join(section for section in sections if section))

    return {
        "id": raw_id,
        "title": f"{assessment.number if assessment else 'Assessment'} | {result.table_name} | {result.name}",
        "text": text,
        "url": url,
        "metadata": {
            "document_type": "scan_result",
            "assessment_id": assessment.id if assessment else None,
            "assessment_number": assessment.number if assessment else None,
            "assessment_name": assessment.name if assessment else None,
            "instance_id": instance.id if instance else None,
            "instance_name": instance.name if instance else None,
            "table_name": result.table_name,
            "result_id": result.id,
            "sys_id": result.sys_id,
            "feature_ids": [item["feature_id"] for item in features],
            **extra_urls,
        },
    }


def _fetch_feature(session: Session, raw_id: str) -> Dict[str, Any]:
    _, _, suffix = raw_id.partition(":")
    try:
        feature_id = int(suffix)
    except ValueError as exc:
        raise ValueError(f"Invalid feature id: {raw_id}") from exc

    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    assessment = session.get(Assessment, feature.assessment_id)
    members = session.exec(
        select(FeatureScanResult, ScanResult)
        .join(ScanResult, FeatureScanResult.scan_result_id == ScanResult.id)
        .where(FeatureScanResult.feature_id == feature_id)
    ).all()
    recommendations = session.exec(
        select(FeatureRecommendation).where(FeatureRecommendation.feature_id == feature_id)
    ).all()

    member_lines = [
        f"- {scan_result.table_name}:{scan_result.name} (primary={link.is_primary}, disposition={scan_result.disposition.value if scan_result.disposition else 'n/a'})"
        for link, scan_result in members
    ]
    recommendation_lines = [
        f"- {rec.recommendation_type}: {rec.ootb_capability_name or rec.product_name or rec.rationale or 'recommendation'}"
        for rec in recommendations
    ]

    text = _truncate_text(
        "\n\n".join(
            section
            for section in [
                f"Assessment: {assessment.number} - {assessment.name}" if assessment else None,
                f"Feature: {feature.name}",
                f"Description: {feature.description}" if feature.description else None,
                f"Disposition: {feature.disposition.value}" if feature.disposition else None,
                f"Recommendation: {feature.recommendation}" if feature.recommendation else None,
                f"AI summary: {feature.ai_summary}" if feature.ai_summary else None,
                "Members:\n" + "\n".join(member_lines) if member_lines else "Members: none linked",
                "Feature recommendations:\n" + "\n".join(recommendation_lines) if recommendation_lines else None,
            ]
            if section
        )
    )

    return {
        "id": raw_id,
        "title": f"{assessment.number if assessment else 'Assessment'} | Feature | {feature.name}",
        "text": text,
        "url": _app_path(f"/assessments/{feature.assessment_id}"),
        "metadata": {
            "document_type": "feature",
            "feature_id": feature.id,
            "assessment_id": feature.assessment_id,
            "member_count": len(members),
            "recommendation_count": len(recommendations),
        },
    }


def _fetch_general_recommendation(session: Session, raw_id: str) -> Dict[str, Any]:
    _, _, suffix = raw_id.partition(":")
    try:
        recommendation_id = int(suffix)
    except ValueError as exc:
        raise ValueError(f"Invalid recommendation id: {raw_id}") from exc

    recommendation = session.get(GeneralRecommendation, recommendation_id)
    if not recommendation:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    assessment = session.get(Assessment, recommendation.assessment_id)
    title_prefix = "Assessment Report" if recommendation.category == "assessment_report" else "Recommendation"
    text = _truncate_text(
        "\n\n".join(
            section
            for section in [
                f"Assessment: {assessment.number} - {assessment.name}" if assessment else None,
                f"{title_prefix}: {recommendation.title}",
                f"Category: {recommendation.category}" if recommendation.category else None,
                f"Severity: {recommendation.severity.value}" if recommendation.severity else None,
                recommendation.description,
            ]
            if section
        )
    )

    return {
        "id": raw_id,
        "title": f"{assessment.number if assessment else 'Assessment'} | {title_prefix} | {recommendation.title}",
        "text": text,
        "url": _app_path(f"/assessments/{recommendation.assessment_id}"),
        "metadata": {
            "document_type": "assessment_report" if recommendation.category == "assessment_report" else "general_recommendation",
            "recommendation_id": recommendation.id,
            "assessment_id": recommendation.assessment_id,
            "category": recommendation.category,
        },
    }


def handle_fetch(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    raw_id = _normalize_text(params.get("id"))
    if not raw_id:
        raise ValueError("id is required")

    if raw_id.startswith("scan_result:"):
        payload = _fetch_scan_result(session, raw_id)
    elif raw_id.startswith("feature:"):
        payload = _fetch_feature(session, raw_id)
    elif raw_id.startswith("general_recommendation:"):
        payload = _fetch_general_recommendation(session, raw_id)
    else:
        raise ValueError(f"Unsupported document id: {raw_id}")

    return _serialize_fetch_document(payload)


SEARCH_TOOL_SPEC = ToolSpec(
    name="search",
    description=(
        "Use this when you need to search the Tech Assessment Hub knowledge base for "
        "assessments, findings, feature groups, reports, and recommendations related "
        "to a user's question."
    ),
    input_schema=SEARCH_INPUT_SCHEMA,
    handler=handle_search,
    permission="read",
)


FETCH_TOOL_SPEC = ToolSpec(
    name="fetch",
    description=(
        "Use this when you already have a document id from search and need the full "
        "Tech Assessment Hub document content for analysis or citation."
    ),
    input_schema=FETCH_INPUT_SCHEMA,
    handler=handle_fetch,
    permission="read",
)
