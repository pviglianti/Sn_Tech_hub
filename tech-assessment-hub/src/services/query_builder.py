from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .scan_rules import get_scan_rules
from ..models import AppFileClass, Assessment, GlobalApp


def parse_list(value: Optional[Any]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if str(v).strip()]
            except json.JSONDecodeError:
                pass
        if "," in raw:
            return [part.strip() for part in raw.split(",") if part.strip()]
        return [raw]
    return [str(value).strip()]


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def resolve_assessment_drivers(assessment: Assessment, global_app: Optional[GlobalApp]) -> Dict[str, List[str]]:
    drivers: Dict[str, List[str]] = {
        "core_tables": [],
        "keywords": [],
        "target_tables": [],
        "plugins": [],
        "table_prefixes": [],
    }

    if assessment.assessment_type.value == "global_app" and global_app:
        rules = get_scan_rules()
        overrides = (rules.get("global_app_overrides") or {}).get(global_app.name or "", {})
        extra_tables = parse_list(overrides.get("tables"))
        extra_keywords = parse_list(overrides.get("keywords"))
        extra_prefixes = parse_list(overrides.get("table_prefixes"))

        core_tables = parse_list(global_app.core_tables_json)
        core_tables.extend(extra_tables)
        drivers["core_tables"] = _dedupe([t for t in core_tables if t])

        base_keywords = parse_list(global_app.keywords_json)
        base_keywords.extend(drivers["core_tables"])
        base_keywords.extend(extra_keywords)
        base_keywords.append((global_app.name or "").lower())
        if global_app.label:
            base_keywords.append(global_app.label.lower())
        drivers["keywords"] = _dedupe([k for k in base_keywords if k])
        drivers["plugins"] = parse_list(global_app.plugins_json)
        drivers["table_prefixes"].extend(extra_prefixes)

    if assessment.assessment_type.value == "table":
        drivers["target_tables"] = parse_list(assessment.target_tables_json)
        if not drivers["keywords"]:
            drivers["keywords"] = drivers["target_tables"].copy()

    if assessment.assessment_type.value == "plugin":
        drivers["plugins"] = parse_list(assessment.target_plugins_json)

    # For global_app, treat core tables as target tables for query building
    if assessment.assessment_type.value == "global_app":
        drivers["target_tables"] = drivers["core_tables"].copy()
        if global_app and global_app.name == "cmdb":
            drivers["table_prefixes"].append("cmdb_")

    drivers["table_prefixes"] = _dedupe([p for p in drivers["table_prefixes"] if p])

    return drivers


def _scope_condition(scope_filter: str, scope_id: Optional[str], scope_rules: Dict[str, Any], key: str) -> Optional[str]:
    if scope_filter == "global":
        pattern = (scope_rules.get("global") or {}).get(key, "")
        if pattern:
            return pattern.format(scope_id=scope_id or "global")
        if key == "metadata":
            return "sys_scope=global"
        if key == "update_xml":
            return "update_set.application.scope=global"
    return None


def _join_groups(groups: List[List[str]]) -> str:
    filtered = ["^".join([c for c in group if c]) for group in groups if group]
    return "^NQ".join([g for g in filtered if g])


def build_metadata_query(
    app_file_class: AppFileClass,
    drivers: Dict[str, List[str]],
    scope_filter: str,
    scope_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> str:
    rules = rules or get_scan_rules()
    query_rules = (rules.get("app_file_class_queries") or {}).get(app_file_class.sys_class_name, {})
    scope_rules = rules.get("scope_filters") or {}

    base_conditions: List[str] = [f"sys_class_name={app_file_class.sys_class_name}"]
    scope_condition = _scope_condition(scope_filter, scope_id, scope_rules, "metadata")
    if scope_condition:
        base_conditions.append(scope_condition)
    base_query = "^".join(base_conditions)

    groups: List[List[str]] = []

    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []

    pattern = query_rules.get("pattern")
    keyword_pattern = query_rules.get("keyword_pattern")

    if pattern and target_tables:
        for table in target_tables:
            if "{base}" in pattern:
                groups.append([pattern.format(base=base_query, table=table)])
            else:
                groups.append(base_conditions + [pattern.format(table=table)])

    if keyword_pattern and keywords:
        for keyword in keywords:
            if "{base}" in keyword_pattern:
                groups.append([keyword_pattern.format(base=base_query, keyword=keyword)])
            else:
                groups.append(base_conditions + [keyword_pattern.format(keyword=keyword)])

    if not groups:
        groups.append(base_conditions)

    return _join_groups(groups)


def build_metadata_query_variants(
    app_file_class: AppFileClass,
    drivers: Dict[str, List[str]],
    scope_filter: str,
    scope_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    rules = rules or get_scan_rules()
    query_rules = (rules.get("app_file_class_queries") or {}).get(app_file_class.sys_class_name, {})
    scope_rules = rules.get("scope_filters") or {}

    base_conditions: List[str] = [f"sys_class_name={app_file_class.sys_class_name}"]
    scope_condition = _scope_condition(scope_filter, scope_id, scope_rules, "metadata")
    if scope_condition:
        base_conditions.append(scope_condition)
    base_query = "^".join(base_conditions)

    variants: List[Dict[str, Any]] = []

    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []

    pattern = query_rules.get("pattern")
    keyword_pattern = query_rules.get("keyword_pattern") or "123TEXTQUERY321={keyword}"
    table_prefixes = drivers.get("table_prefixes") or []

    if pattern and target_tables:
        for table in target_tables:
            if "{base}" in pattern:
                query = pattern.format(base=base_query, table=table)
            else:
                query = "^".join(base_conditions + [pattern.format(table=table)])
            variants.append({
                "query": query,
                "label": f"{app_file_class.label} ({table})",
                "target_table": table,
            })
    if pattern and table_prefixes and "STARTSWITH" in pattern:
        for prefix in table_prefixes:
            if "{base}" in pattern:
                query = pattern.format(base=base_query, table=prefix)
            else:
                query = "^".join(base_conditions + [pattern.format(table=prefix)])
            variants.append({
                "query": query,
                "label": f"{app_file_class.label} ({prefix})",
                "target_table": prefix,
            })

    if keyword_pattern and keywords:
        for keyword in keywords:
            if "{base}" in keyword_pattern:
                query = keyword_pattern.format(base=base_query, keyword=keyword)
            else:
                query = "^".join(base_conditions + [keyword_pattern.format(keyword=keyword)])
            variants.append({
                "query": query,
                "label": f"{app_file_class.label} ({keyword})",
                "keyword": keyword,
            })

    if not variants:
        variants.append({
            "query": "^".join(base_conditions),
            "label": app_file_class.label,
        })

    return variants


def build_update_xml_query(
    drivers: Dict[str, List[str]],
    scope_filter: str,
    scope_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> str:
    rules = rules or get_scan_rules()
    scope_rules = rules.get("scope_filters") or {}
    update_rules = rules.get("update_xml_filters") or {}

    base_conditions: List[str] = []
    scope_condition = _scope_condition(scope_filter, scope_id, scope_rules, "update_xml")
    if scope_condition:
        base_conditions.append(scope_condition)

    groups: List[List[str]] = []
    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []

    by_table = update_rules.get("by_table") or {}
    patterns = by_table.get("patterns") or []
    for table in target_tables:
        for pattern in patterns:
            groups.append(base_conditions + [pattern.format(table=table)])

    keyword_rule = update_rules.get("by_keyword") or {}
    keyword_pattern = keyword_rule.get("pattern")
    if keyword_pattern:
        for keyword in keywords:
            groups.append(base_conditions + [keyword_pattern.format(keyword=keyword)])

    if not groups:
        groups.append(base_conditions or [])

    return _join_groups(groups)


def build_update_xml_query_variants(
    drivers: Dict[str, List[str]],
    scope_filter: str,
    scope_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    rules = rules or get_scan_rules()
    scope_rules = rules.get("scope_filters") or {}
    update_rules = rules.get("update_xml_filters") or {}

    base_conditions: List[str] = []
    scope_condition = _scope_condition(scope_filter, scope_id, scope_rules, "update_xml")
    if scope_condition:
        base_conditions.append(scope_condition)

    variants: List[Dict[str, Any]] = []
    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []

    by_table = update_rules.get("by_table") or {}
    patterns = by_table.get("patterns") or []
    for table in target_tables:
        groups = [base_conditions + [pattern.format(table=table)] for pattern in patterns]
        query = _join_groups(groups)
        variants.append({
            "query": query,
            "label": f"Update XML ({table})",
            "target_table": table,
        })

    keyword_rule = update_rules.get("by_keyword") or {}
    keyword_pattern = keyword_rule.get("pattern")
    if keyword_pattern:
        for keyword in keywords:
            query = _join_groups([base_conditions + [keyword_pattern.format(keyword=keyword)]])
            variants.append({
                "query": query,
                "label": f"Update XML ({keyword})",
                "keyword": keyword,
            })

    if not variants:
        variants.append({
            "query": _join_groups([base_conditions]) if base_conditions else "",
            "label": "Update XML",
        })

    return variants
