"""
Condition Query Builder
-----------------------
Translates a condition-builder JSON tree (AND/OR groups with nested conditions)
into either:
    1. A SQLite WHERE clause with parameterised placeholders
    2. A ServiceNow encoded query string

Condition tree structure (mirrors the JS ConditionBuilder output):

    {
        "logic": "AND" | "OR",
        "conditions": [
            {"field": "name", "operator": "contains", "value": "incident"},
            {"field": "state", "operator": "is", "value": "1"},
            {
                "logic": "OR",
                "conditions": [ ... ]   # nested group
            }
        ]
    }

A single flat condition (no logic key) is also accepted:
    {"field": "name", "operator": "is", "value": "foo"}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ── Operator definitions ─────────────────────────────────────────────

# Maps (operator_name) -> (sql_template, needs_value)
# In the template, {col} is replaced by the column reference and ? by the
# parameter placeholder.
_SQL_OPS: Dict[str, Tuple[str, bool]] = {
    # string / generic
    "is":            ("{col} = ?",           True),
    "is_not":        ("{col} != ?",          True),
    "is not":        ("{col} != ?",          True),
    "contains":      ("{col} LIKE ?",        True),   # value wrapped in %..%
    "not_contains":  ("{col} NOT LIKE ?",    True),   # value wrapped in %..%
    "starts_with":   ("{col} LIKE ?",        True),   # value + %
    "starts with":   ("{col} LIKE ?",        True),   # value + %
    "ends_with":     ("{col} LIKE ?",        True),   # % + value
    "ends with":     ("{col} LIKE ?",        True),   # % + value
    "is_empty":      ("({col} IS NULL OR {col} = '')", False),
    "is empty":      ("({col} IS NULL OR {col} = '')", False),
    "is_not_empty":  ("({col} IS NOT NULL AND {col} != '')", False),
    "is not empty":  ("({col} IS NOT NULL AND {col} != '')", False),
    # numeric
    "equals":        ("{col} = ?",           True),
    "=":             ("{col} = ?",           True),
    "not_equals":    ("{col} != ?",          True),
    "!=":            ("{col} != ?",          True),
    "greater_than":  ("{col} > ?",           True),
    ">":             ("{col} > ?",           True),
    "less_than":     ("{col} < ?",           True),
    "<":             ("{col} < ?",           True),
    "greater_or_equal": ("{col} >= ?",       True),
    ">=":            ("{col} >= ?",          True),
    "less_or_equal": ("{col} <= ?",          True),
    "<=":            ("{col} <= ?",          True),
    "between":       ("{col} BETWEEN ? AND ?", True),  # value = [lo, hi]
    # datetime
    "before":        ("{col} < ?",           True),
    "after":         ("{col} > ?",           True),
    "today":         ("date({col}) = date('now')", False),
    "this week":     ("{col} >= date('now', 'weekday 0', '-7 days')", False),
    "this month":    ("{col} >= date('now', 'start of month')", False),
    # boolean
    "is_true":       ("{col} = 1",           False),
    "is true":       ("{col} = 1",           False),
    "is_false":      ("({col} = 0 OR {col} IS NULL)", False),
    "is false":      ("({col} = 0 OR {col} IS NULL)", False),
}

# Maps operator_name -> SN encoded-query operator token
_SN_OPS: Dict[str, str] = {
    "is":            "=",
    "is_not":        "!=",
    "is not":        "!=",
    "contains":      "LIKE",
    "not_contains":  "NOT LIKE",
    "starts_with":   "STARTSWITH",
    "starts with":   "STARTSWITH",
    "ends_with":     "ENDSWITH",
    "ends with":     "ENDSWITH",
    "is_empty":      "ISEMPTY",
    "is empty":      "ISEMPTY",
    "is_not_empty":  "ISNOTEMPTY",
    "is not empty":  "ISNOTEMPTY",
    "equals":        "=",
    "=":             "=",
    "not_equals":    "!=",
    "!=":            "!=",
    "greater_than":  ">",
    ">":             ">",
    "less_than":     "<",
    "<":             "<",
    "greater_or_equal": ">=",
    ">=":            ">=",
    "less_or_equal": "<=",
    "<=":            "<=",
    "between":       "BETWEEN",
    "before":        "<",
    "after":         ">",
    "today":         "ONToday@javascript:gs.beginningOfToday()@javascript:gs.endOfToday()",
    "this week":     "ONThis week@javascript:gs.beginningOfThisWeek()@javascript:gs.endOfThisWeek()",
    "this month":    "ONThis month@javascript:gs.beginningOfThisMonth()@javascript:gs.endOfThisMonth()",
    "is_true":       "=true",
    "is true":       "=true",
    "is_false":      "=false",
    "is false":      "=false",
}


# ── Helpers ───────────────────────────────────────────────────────────

def _is_group(node: Dict[str, Any]) -> bool:
    """Return True if the node is a logic group (has 'logic' + 'conditions')."""
    return "logic" in node and "conditions" in node


def _safe_column(name: str, table_alias: str = "") -> str:
    """Return a safely-quoted column reference for SQL."""
    # Only allow alphanumeric + underscore to prevent injection
    clean = "".join(ch for ch in name if ch.isalnum() or ch == "_")
    if not clean:
        raise ValueError(f"Invalid column name: {name!r}")
    if table_alias:
        return f'"{table_alias}"."{clean}"'
    return f'"{clean}"'


# ── SQL WHERE builder ─────────────────────────────────────────────────

def conditions_to_sql_where(
    conditions: Dict[str, Any],
    table_alias: str = "",
) -> Tuple[str, List[Any]]:
    """Convert a condition builder JSON tree to a SQLite WHERE clause.

    Returns:
        (where_clause, params) -- where_clause does NOT include the leading
        "WHERE" keyword.  params is a list of bind values.

    Raises ValueError on unknown operators or malformed input.
    """
    if not conditions:
        return ("1=1", [])

    # Single flat condition (no group wrapper)
    if not _is_group(conditions):
        return _single_condition_sql(conditions, table_alias)

    return _group_to_sql(conditions, table_alias)


def _single_condition_sql(
    cond: Dict[str, Any], table_alias: str
) -> Tuple[str, List[Any]]:
    field = cond.get("field", "")
    operator = cond.get("operator", "")
    value = cond.get("value")

    if operator not in _SQL_OPS:
        raise ValueError(f"Unknown SQL operator: {operator!r}")

    template, needs_value = _SQL_OPS[operator]
    col = _safe_column(field, table_alias)
    clause = template.replace("{col}", col)

    params: List[Any] = []
    if needs_value:
        if operator in ("contains", "not_contains"):
            params.append(f"%{value}%")
        elif operator in ("starts with", "starts_with"):
            params.append(f"{value}%")
        elif operator in ("ends with", "ends_with"):
            params.append(f"%{value}")
        elif operator == "between":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                params.extend(value)
            else:
                raise ValueError(
                    f"'between' operator requires a two-element list, got: {value!r}"
                )
        else:
            params.append(value)

    return (clause, params)


def _group_to_sql(
    group: Dict[str, Any], table_alias: str
) -> Tuple[str, List[Any]]:
    logic = group.get("logic", "AND").upper()
    if logic not in ("AND", "OR"):
        raise ValueError(f"Invalid logic operator: {logic!r}")

    children = group.get("conditions", [])
    if not children:
        return ("1=1", [])

    parts: List[str] = []
    params: List[Any] = []

    for child in children:
        if _is_group(child):
            child_clause, child_params = _group_to_sql(child, table_alias)
        else:
            child_clause, child_params = _single_condition_sql(child, table_alias)
        parts.append(child_clause)
        params.extend(child_params)

    joiner = f" {logic} "
    combined = joiner.join(f"({p})" for p in parts)
    return (f"({combined})", params)


# ── ServiceNow encoded query builder ─────────────────────────────────

def conditions_to_sn_encoded_query(conditions: Dict[str, Any]) -> str:
    """Convert a condition builder JSON tree to a ServiceNow encoded query.

    ServiceNow encoded queries use:
        field=value^field2!=value2^ORfield3LIKEval
        ^NQ for new-query (OR-group at top level)

    Returns the encoded query string (empty string if no conditions).
    """
    if not conditions:
        return ""

    if not _is_group(conditions):
        return _single_condition_sn(conditions)

    return _group_to_sn(conditions)


def _single_condition_sn(cond: Dict[str, Any]) -> str:
    field = cond.get("field", "")
    operator = cond.get("operator", "")
    value = cond.get("value", "")

    if operator not in _SN_OPS:
        raise ValueError(f"Unknown SN operator: {operator!r}")

    sn_op = _SN_OPS[operator]

    # Operators that encode the value within the op token itself
    if operator in ("is empty", "is_empty", "is not empty", "is_not_empty",
                     "today", "this week", "this month"):
        return f"{field}{sn_op}"

    if operator in ("is true", "is_true", "is false", "is_false"):
        return f"{field}{sn_op}"

    if operator == "between":
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return f"{field}{sn_op}{value[0]}@{value[1]}"
        raise ValueError(
            f"'between' operator requires a two-element list, got: {value!r}"
        )

    return f"{field}{sn_op}{value}"


def _group_to_sn(group: Dict[str, Any]) -> str:
    logic = group.get("logic", "AND").upper()
    children = group.get("conditions", [])
    if not children:
        return ""

    parts: List[str] = []
    for child in children:
        if _is_group(child):
            parts.append(_group_to_sn(child))
        else:
            parts.append(_single_condition_sn(child))

    if logic == "AND":
        return "^".join(parts)
    else:
        # OR at top level uses ^NQ, within nested uses ^OR
        return "^OR".join(parts)
