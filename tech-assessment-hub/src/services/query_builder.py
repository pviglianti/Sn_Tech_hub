from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .scan_rules import get_scan_rules
from ..models import AppFileClass, AppFileClassQuery, Assessment, GlobalApp


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
    """Resolve scan driver values (tables, keywords, prefixes) from GlobalApp DB records.

    All scope data now comes from the GlobalApp table directly — no YAML overrides.
    """
    drivers: Dict[str, List[str]] = {
        "core_tables": [],
        "keywords": [],
        "target_tables": [],
        "plugins": [],
        "table_prefixes": [],
    }

    if assessment.assessment_type.value == "global_app" and global_app:
        core_tables = parse_list(global_app.core_tables_json)
        drivers["core_tables"] = _dedupe([t for t in core_tables if t])

        base_keywords = parse_list(global_app.keywords_json)
        base_keywords.extend(drivers["core_tables"])
        base_keywords.append((global_app.name or "").lower())
        if global_app.label:
            base_keywords.append(global_app.label.lower())
        drivers["keywords"] = _dedupe([k for k in base_keywords if k])
        drivers["plugins"] = parse_list(global_app.plugins_json)
        drivers["table_prefixes"] = parse_list(global_app.table_prefixes_json)

    if assessment.assessment_type.value == "table":
        drivers["target_tables"] = parse_list(assessment.target_tables_json)
        if not drivers["keywords"]:
            drivers["keywords"] = drivers["target_tables"].copy()

    if assessment.assessment_type.value == "plugin":
        drivers["plugins"] = parse_list(assessment.target_plugins_json)

    # For global_app, treat core tables as target tables for query building
    if assessment.assessment_type.value == "global_app":
        drivers["target_tables"] = drivers["core_tables"].copy()

    drivers["table_prefixes"] = _dedupe([p for p in drivers["table_prefixes"] if p])

    return drivers


def _scope_condition(scope_filter: str, scope_id: Optional[str], scope_rules: Dict[str, Any], key: str) -> Optional[str]:
    """Build an optional scope filter from scan_rules.yaml.

    Scope filtering is driven entirely by the YAML config.  If the config
    value is empty the query is not narrowed — the assessment's table/keyword
    drivers are the only thing that controls what gets pulled.
    """
    pattern = (scope_rules.get(scope_filter) or {}).get(key, "")
    if pattern:
        return pattern.format(scope_id=scope_id or "global")
    return None


def _join_groups(groups: List[List[str]]) -> str:
    filtered = ["^".join([c for c in group if c]) for group in groups if group]
    return "^NQ".join([g for g in filtered if g])


# Default fallback keyword pattern used when a class has no configured queries
_DEFAULT_KEYWORD_PATTERN = "123TEXTQUERY321={keyword}"


def build_metadata_query(
    app_file_class: AppFileClass,
    drivers: Dict[str, List[str]],
    scope_filter: str,
    scope_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
    queries: Optional[List[AppFileClassQuery]] = None,
) -> str:
    """Build a single combined metadata query for an app file class.

    If *queries* is provided, patterns are read from the DB rows.
    Otherwise falls back to YAML for backward compatibility.
    """
    rules = rules or get_scan_rules()
    scope_rules = rules.get("scope_filters") or {}

    base_conditions: List[str] = [f"sys_class_name={app_file_class.sys_class_name}"]
    scope_condition = _scope_condition(scope_filter, scope_id, scope_rules, "metadata")
    if scope_condition:
        base_conditions.append(scope_condition)
    base_query = "^".join(base_conditions)

    groups: List[List[str]] = []

    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []

    if queries is not None:
        # DB-driven: iterate over AppFileClassQuery rows
        for q in queries:
            if not q.is_active:
                continue
            pattern = q.pattern
            has_table = "{table}" in pattern
            has_keyword = "{keyword}" in pattern

            if has_table and q.query_type in ("table_pattern", "custom") and target_tables:
                for table in target_tables:
                    if "{base}" in pattern:
                        groups.append([pattern.format(base=base_query, table=table)])
                    else:
                        groups.append(base_conditions + [pattern.format(table=table)])
            if has_keyword and q.query_type in ("keyword_pattern", "custom") and keywords:
                for keyword in keywords:
                    if "{base}" in pattern:
                        groups.append([pattern.format(base=base_query, keyword=keyword)])
                    else:
                        groups.append(base_conditions + [pattern.format(keyword=keyword)])
    else:
        # Legacy YAML fallback
        query_rules = (rules.get("app_file_class_queries") or {}).get(app_file_class.sys_class_name, {})
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
        # Fallback: keyword text search if we have keywords, otherwise bare class filter
        if keywords:
            for keyword in keywords:
                groups.append(base_conditions + [_DEFAULT_KEYWORD_PATTERN.format(keyword=keyword)])
        else:
            groups.append(base_conditions)

    return _join_groups(groups)


def build_metadata_query_variants(
    app_file_class: AppFileClass,
    drivers: Dict[str, List[str]],
    scope_filter: str,
    scope_id: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
    queries: Optional[List[AppFileClassQuery]] = None,
) -> List[Dict[str, Any]]:
    """Build per-value scan variants for an app file class.

    Each variant becomes one Scan record.  If *queries* is provided,
    patterns are read from the DB rows.  Otherwise falls back to YAML.
    """
    rules = rules or get_scan_rules()
    scope_rules = rules.get("scope_filters") or {}

    base_conditions: List[str] = [f"sys_class_name={app_file_class.sys_class_name}"]
    scope_condition = _scope_condition(scope_filter, scope_id, scope_rules, "metadata")
    if scope_condition:
        base_conditions.append(scope_condition)
    base_query = "^".join(base_conditions)

    variants: List[Dict[str, Any]] = []

    target_tables = drivers.get("target_tables") or []
    keywords = drivers.get("keywords") or []
    table_prefixes = drivers.get("table_prefixes") or []

    if queries is not None:
        # DB-driven: iterate over AppFileClassQuery rows
        for q in queries:
            if not q.is_active:
                continue
            pattern = q.pattern

            has_table_placeholder = "{table}" in pattern
            has_keyword_placeholder = "{keyword}" in pattern

            if has_table_placeholder and (q.query_type in ("table_pattern", "custom")) and target_tables:
                # One scan per target table
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
                # Also expand table prefixes for STARTSWITH patterns
                if table_prefixes and "STARTSWITH" in pattern:
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

            if has_keyword_placeholder and (q.query_type in ("keyword_pattern", "custom")) and keywords:
                # One scan per keyword
                for keyword in keywords:
                    if "{base}" in pattern:
                        query = pattern.format(base=base_query, keyword=keyword)
                    else:
                        query = "^".join(base_conditions + [pattern.format(keyword=keyword)])
                    variants.append({
                        "query": query,
                        "label": f"{app_file_class.label} ({keyword})",
                        "keyword": keyword,
                    })

    else:
        # Legacy YAML fallback
        query_rules = (rules.get("app_file_class_queries") or {}).get(app_file_class.sys_class_name, {})
        pattern = query_rules.get("pattern")
        keyword_pattern = query_rules.get("keyword_pattern") or _DEFAULT_KEYWORD_PATTERN

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

    # Fallback: default keyword search if no queries produced variants
    if not variants:
        if keywords:
            for keyword in keywords:
                query = "^".join(base_conditions + [_DEFAULT_KEYWORD_PATTERN.format(keyword=keyword)])
                variants.append({
                    "query": query,
                    "label": f"{app_file_class.label} ({keyword})",
                    "keyword": keyword,
                })
        else:
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
