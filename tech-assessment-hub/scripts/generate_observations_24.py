#!/usr/bin/env python3
"""Generate functional observations for in-scope artifacts in Assessment 24.

Reads each artifact's detail and writes a 2-4 sentence functional summary
covering: what it does, when it fires, what fields/tables it touches,
and what dependencies it has.
"""

import json
import re
import sys
import requests

MCP_URL = "http://127.0.0.1:8081/mcp"
ASSESSMENT_ID = 24


def mcp_call(tool_name, arguments):
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = requests.post(MCP_URL, json=payload, timeout=60)
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")
    content = data["result"]["content"]
    for item in content:
        if item.get("type") == "json":
            return item["json"]
        if item.get("type") == "text":
            return item["text"]
    return content


def sql(query):
    return mcp_call("sqlite_query", {"sql": query})


def get_detail(result_id):
    return mcp_call("get_result_detail", {"result_id": result_id})


def update_result(result_id, observations):
    return mcp_call("update_scan_result", {
        "result_id": result_id,
        "observations": observations,
    })


# ---------------------------------------------------------------------------
# Observation generators by artifact type
# ---------------------------------------------------------------------------

def _extract_field(detail, *keys):
    """Extract a value from nested detail dicts."""
    for d in [detail.get("artifact_detail", {}), detail]:
        for k in keys:
            v = d.get(k)
            if v and isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _extract_table(detail):
    return (_extract_field(detail, "collection", "table", "name_of_table")
            or detail.get("meta_target_table", "") or "")


def _shorten_script(script, max_len=500):
    if not script:
        return ""
    # Remove comment blocks
    script = re.sub(r'/\*.*?\*/', '', script, flags=re.DOTALL)
    script = re.sub(r'//[^\n]*', '', script)
    return script.strip()[:max_len]


def _find_glide_tables(script):
    """Find GlideRecord table references in script."""
    if not script:
        return []
    tables = set()
    for m in re.finditer(r"GlideRecord\s*\(\s*['\"](\w+)['\"]", script):
        tables.add(m.group(1))
    for m in re.finditer(r"getTableName\s*\(\s*\)\s*==\s*['\"](\w+)['\"]", script):
        tables.add(m.group(1))
    return sorted(tables)


def _when_clause(detail):
    """Build a 'when' description from trigger/condition fields."""
    when_val = _extract_field(detail, "when", "trigger_type")
    action_type = _extract_field(detail, "action_insert", "action_update",
                                  "action_delete", "action_query")
    condition = _extract_field(detail, "condition", "filter_condition")

    parts = []
    if when_val:
        parts.append(f"when={when_val}")

    # Check insert/update/delete flags
    ad = detail.get("artifact_detail", {})
    ops = []
    if ad.get("action_insert") in (True, "true", "1"):
        ops.append("insert")
    if ad.get("action_update") in (True, "true", "1"):
        ops.append("update")
    if ad.get("action_delete") in (True, "true", "1"):
        ops.append("delete")
    if ad.get("action_query") in (True, "true", "1"):
        ops.append("query")
    if ops:
        parts.append(f"on {'/'.join(ops)}")

    if condition:
        cond_short = condition[:80] + ("..." if len(condition) > 80 else "")
        parts.append(f"condition: {cond_short}")

    return "; ".join(parts) if parts else ""


def observe_business_rule(detail):
    """Generate observation for sys_script (business rule)."""
    name = _extract_field(detail, "name") or detail.get("name", "?")
    table = _extract_table(detail)
    script = _shorten_script(_extract_field(detail, "script"))
    when = _when_clause(detail)
    tables_ref = _find_glide_tables(script)
    ad = detail.get("artifact_detail", {})
    is_active = ad.get("active", True)

    parts = [f"Business rule '{name}' on table '{table}'."]

    if when:
        parts.append(f"Fires {when}.")

    if not is_active or is_active in ("false", "0", False):
        parts.append("Currently INACTIVE.")

    # Describe what the script does based on patterns
    actions = []
    if script:
        if "setValue" in script or "current." in script:
            fields = set(re.findall(r"\.setValue\s*\(\s*['\"](\w+)['\"]", script))
            if fields:
                actions.append(f"sets fields: {', '.join(sorted(fields)[:5])}")
        if "abort" in script.lower():
            actions.append("may abort the operation")
        if "event" in script.lower() and "fire" in script.lower():
            actions.append("fires events")
        if "email" in script.lower() or "notification" in script.lower():
            actions.append("triggers notifications")
        if "workflow" in script.lower():
            actions.append("interacts with workflows")

    if actions:
        parts.append("Actions: " + "; ".join(actions) + ".")

    if tables_ref:
        other_tables = [t for t in tables_ref if t != table]
        if other_tables:
            parts.append(f"Also queries: {', '.join(other_tables[:4])}.")

    return " ".join(parts)


def observe_client_script(detail):
    """Generate observation for sys_script_client."""
    name = _extract_field(detail, "name") or detail.get("name", "?")
    table = _extract_table(detail)
    script = _shorten_script(_extract_field(detail, "script"))
    ad = detail.get("artifact_detail", {})
    cs_type = ad.get("type", "") or _extract_field(detail, "type")

    parts = [f"Client script '{name}' on '{table}'."]

    if cs_type:
        parts.append(f"Type: {cs_type}.")

    # Analyze client script behavior
    actions = []
    if script:
        if "setMandatory" in script:
            fields = set(re.findall(r"setMandatory\s*\(\s*['\"](\w+)['\"]", script))
            actions.append(f"sets mandatory: {', '.join(sorted(fields)[:4]) or 'fields'}")
        if "setDisplay" in script or "setVisible" in script:
            actions.append("controls field visibility")
        if "setReadOnly" in script:
            actions.append("controls read-only state")
        if "setValue" in script:
            actions.append("sets field values")
        if "getReference" in script or "GlideAjax" in script:
            actions.append("makes server calls")
        if "addOption" in script or "removeOption" in script:
            actions.append("modifies choice lists")
        if "showFieldMsg" in script or "addErrorMessage" in script:
            actions.append("shows user messages")

    if actions:
        parts.append("Behavior: " + "; ".join(actions) + ".")

    return " ".join(parts)


def observe_ui_policy(detail):
    """Generate observation for sys_ui_policy."""
    name = _extract_field(detail, "short_description", "name") or detail.get("name", "?")
    table = _extract_table(detail)
    condition = _extract_field(detail, "conditions", "condition")
    ad = detail.get("artifact_detail", {})
    on_load = ad.get("on_load", False)
    reverse = ad.get("reverse_if_false", False)

    parts = [f"UI policy '{name}' on '{table}'."]

    if condition:
        cond_short = condition[:100] + ("..." if len(condition) > 100 else "")
        parts.append(f"Condition: {cond_short}.")

    flags = []
    if on_load in (True, "true", "1"):
        flags.append("runs on load")
    if reverse in (True, "true", "1"):
        flags.append("reverses if false")
    if flags:
        parts.append(f"Behavior: {', '.join(flags)}.")

    return " ".join(parts)


def observe_ui_policy_action(detail):
    """Generate observation for sys_ui_policy_action."""
    ad = detail.get("artifact_detail", {})
    field = ad.get("field", "") or _extract_field(detail, "field")
    table = _extract_table(detail) or ad.get("table", "")
    mandatory = ad.get("mandatory")
    visible = ad.get("visible")
    read_only = ad.get("disabled")  # 'disabled' = read-only in SN
    ui_policy_name = ad.get("ui_policy", {})
    if isinstance(ui_policy_name, dict):
        ui_policy_name = ui_policy_name.get("display_value", "")

    name = detail.get("name", field or "?")

    effects = []
    if mandatory and mandatory != "leave_alone":
        effects.append(f"mandatory={mandatory}")
    if visible and visible != "leave_alone":
        effects.append(f"visible={visible}")
    if read_only and read_only != "leave_alone":
        effects.append(f"read_only={read_only}")

    parts = [f"UI policy action on field '{field}' (table: '{table}')."]
    if effects:
        parts.append(f"Sets: {', '.join(effects)}.")
    if ui_policy_name:
        parts.append(f"Belongs to policy: '{ui_policy_name}'.")

    return " ".join(parts)


def observe_ui_action(detail):
    """Generate observation for sys_ui_action."""
    name = _extract_field(detail, "name") or detail.get("name", "?")
    table = _extract_table(detail)
    script = _shorten_script(_extract_field(detail, "script"))
    ad = detail.get("artifact_detail", {})
    action_name = ad.get("action_name", "")
    client_script = ad.get("client", False)

    parts = [f"UI action '{name}' on '{table}'."]

    if action_name:
        parts.append(f"Action name: '{action_name}'.")

    if client_script in (True, "true", "1"):
        parts.append("Runs client-side script.")
    elif script:
        parts.append("Runs server-side script.")

    actions = []
    if script:
        tables_ref = _find_glide_tables(script)
        if tables_ref:
            other = [t for t in tables_ref if t != table]
            if other:
                actions.append(f"queries {', '.join(other[:3])}")
        if "workflow" in script.lower():
            actions.append("interacts with workflows")
        if "redirect" in script.lower() or "navigate" in script.lower():
            actions.append("navigates user")

    if actions:
        parts.append("Also: " + "; ".join(actions) + ".")

    return " ".join(parts)


def observe_dictionary(detail):
    """Generate observation for sys_dictionary."""
    ad = detail.get("artifact_detail", {})
    element = ad.get("element", "") or _extract_field(detail, "element", "column_label")
    table = _extract_table(detail) or ad.get("name", "")
    internal_type = ad.get("internal_type", {})
    if isinstance(internal_type, dict):
        internal_type = internal_type.get("display_value", "")
    max_length = ad.get("max_length", "")
    reference = ad.get("reference", {})
    if isinstance(reference, dict):
        reference = reference.get("display_value", "")
    default_val = ad.get("default_value", "")
    mandatory = ad.get("mandatory", False)

    parts = [f"Dictionary entry: field '{element}' on table '{table}'."]

    props = []
    if internal_type:
        props.append(f"type={internal_type}")
    if max_length:
        props.append(f"max_length={max_length}")
    if reference:
        props.append(f"references={reference}")
    if mandatory in (True, "true", "1"):
        props.append("mandatory")
    if default_val:
        props.append(f"default='{default_val[:30]}'")

    if props:
        parts.append(f"Properties: {', '.join(props)}.")

    return " ".join(parts)


def observe_dictionary_override(detail):
    """Generate observation for sys_dictionary_override."""
    ad = detail.get("artifact_detail", {})
    element = ad.get("element", "") or _extract_field(detail, "element")
    table = _extract_table(detail) or ad.get("name", "")
    override_default = ad.get("default_value_override", False)
    override_mandatory = ad.get("mandatory_override", False)
    override_read_only = ad.get("read_only_override", False)

    parts = [f"Dictionary override: field '{element}' on table '{table}'."]

    overrides = []
    if override_default in (True, "true", "1"):
        overrides.append("overrides default value")
    if override_mandatory in (True, "true", "1"):
        overrides.append("overrides mandatory flag")
    if override_read_only in (True, "true", "1"):
        overrides.append("overrides read-only flag")

    if overrides:
        parts.append("Overrides: " + ", ".join(overrides) + ".")
    else:
        parts.append("Extends base dictionary entry.")

    return " ".join(parts)


def observe_acl(detail):
    """Generate observation for sys_security_acl."""
    ad = detail.get("artifact_detail", {})
    name_val = detail.get("name", "?")
    operation = ad.get("operation", "") or _extract_field(detail, "operation")
    acl_type = ad.get("type", "") or _extract_field(detail, "type")
    script = _shorten_script(_extract_field(detail, "script"))
    condition = _extract_field(detail, "condition")
    roles = ad.get("sys_user_role", "")

    parts = [f"ACL '{name_val}'."]

    if operation:
        parts.append(f"Operation: {operation}.")

    access = []
    if roles:
        if isinstance(roles, str):
            access.append(f"requires role(s)")
        elif isinstance(roles, dict):
            access.append(f"requires role: {roles.get('display_value', '?')}")
    if condition:
        access.append("has condition check")
    if script:
        access.append("has script-based evaluation")

    if access:
        parts.append("Access control: " + "; ".join(access) + ".")

    return " ".join(parts)


def observe_script_include(detail):
    """Generate observation for sys_script_include."""
    name = _extract_field(detail, "name", "api_name") or detail.get("name", "?")
    script = _shorten_script(_extract_field(detail, "script"), 800)
    ad = detail.get("artifact_detail", {})
    client_callable = ad.get("client_callable", False)

    parts = [f"Script include '{name}'."]

    if client_callable in (True, "true", "1"):
        parts.append("Client-callable (GlideAjax accessible).")

    # Analyze what the script does
    tables_ref = _find_glide_tables(script)
    if tables_ref:
        parts.append(f"Queries tables: {', '.join(tables_ref[:5])}.")

    functions = []
    if script:
        # Find method names
        for m in re.finditer(r"(\w+)\s*:\s*function\s*\(", script):
            fn = m.group(1)
            if fn not in ("initialize", "type"):
                functions.append(fn)
        if functions:
            parts.append(f"Methods: {', '.join(functions[:5])}.")

    return " ".join(parts)


def observe_catalog_item(detail):
    """Generate observation for sc_cat_item_guide or sc_cat_item_producer."""
    name = _extract_field(detail, "name", "short_description") or detail.get("name", "?")
    ad = detail.get("artifact_detail", {})
    table = ad.get("table_name", "") or _extract_table(detail)
    script = _shorten_script(_extract_field(detail, "script"))
    category = ad.get("category", {})
    if isinstance(category, dict):
        category = category.get("display_value", "")

    sys_class = detail.get("sys_class_name", "")
    kind = "Order guide" if "guide" in sys_class else "Record producer"

    parts = [f"{kind} '{name}'."]

    if table:
        parts.append(f"Target table: '{table}'.")
    if category:
        parts.append(f"Category: '{category}'.")
    if script:
        tables_ref = _find_glide_tables(script)
        if tables_ref:
            parts.append(f"Script queries: {', '.join(tables_ref[:4])}.")

    return " ".join(parts)


def observe_db_object(detail):
    """Generate observation for sys_db_object (table definition)."""
    name = _extract_field(detail, "name", "label") or detail.get("name", "?")
    ad = detail.get("artifact_detail", {})
    super_class = ad.get("super_class", {})
    if isinstance(super_class, dict):
        super_class = super_class.get("display_value", "")
    label = ad.get("label", "")

    parts = [f"Table definition '{name}'."]
    if label:
        parts.append(f"Label: '{label}'.")
    if super_class:
        parts.append(f"Extends: '{super_class}'.")

    return " ".join(parts)


def observe_data_policy(detail):
    """Generate observation for sys_data_policy2."""
    name = _extract_field(detail, "short_description", "name") or detail.get("name", "?")
    table = _extract_table(detail)
    condition = _extract_field(detail, "conditions", "condition")

    parts = [f"Data policy '{name}' on '{table}'."]
    if condition:
        cond_short = condition[:100] + ("..." if len(condition) > 100 else "")
        parts.append(f"Condition: {cond_short}.")

    return " ".join(parts)


def observe_choice(detail):
    """Generate observation for sys_choice."""
    ad = detail.get("artifact_detail", {})
    label = ad.get("label", "") or _extract_field(detail, "label")
    value = ad.get("value", "") or _extract_field(detail, "value")
    element = ad.get("element", "") or _extract_field(detail, "element")
    table = _extract_table(detail) or ad.get("name", "")

    parts = [f"Choice value on '{table}.{element}'."]
    if label:
        parts.append(f"Label: '{label}', value: '{value}'.")

    return " ".join(parts)


def observe_ui_page(detail):
    """Generate observation for sys_ui_page."""
    name = _extract_field(detail, "name") or detail.get("name", "?")
    ad = detail.get("artifact_detail", {})
    description = ad.get("description", "") or _extract_field(detail, "description")

    parts = [f"UI page '{name}'."]
    if description:
        parts.append(f"Description: {description[:100]}.")

    return " ".join(parts)


# Map sys_class_name to observer function
OBSERVERS = {
    "sys_script": observe_business_rule,
    "sys_script_client": observe_client_script,
    "sys_ui_policy": observe_ui_policy,
    "sys_ui_policy_action": observe_ui_policy_action,
    "sys_ui_action": observe_ui_action,
    "sys_dictionary": observe_dictionary,
    "sys_dictionary_override": observe_dictionary_override,
    "sys_security_acl": observe_acl,
    "sys_script_include": observe_script_include,
    "sc_cat_item_guide": observe_catalog_item,
    "sc_cat_item_producer": observe_catalog_item,
    "sys_db_object": observe_db_object,
    "sys_data_policy2": observe_data_policy,
    "sys_choice": observe_choice,
    "sys_ui_page": observe_ui_page,
}


def observe_generic(detail):
    """Fallback observer for unknown artifact types."""
    name = _extract_field(detail, "name", "short_description") or detail.get("name", "?")
    table = _extract_table(detail)
    sys_class = detail.get("sys_class_name", "unknown")
    return f"Artifact '{name}' ({sys_class}) on table '{table}'. No specialized observer available."


def main():
    print("=" * 60)
    print("Assessment 24 — Observation Generation")
    print("=" * 60)

    # Get all in-scope + adjacent artifact IDs (not out_of_scope)
    print("\nFetching in-scope artifacts...")
    all_ids = []
    page = 0
    while True:
        result = sql(
            "SELECT sr.id, sr.sys_class_name, sr.name, sr.observations "
            "FROM scan_result sr JOIN scan s ON sr.scan_id = s.id "
            "WHERE s.assessment_id = 24 "
            "AND sr.id IN (SELECT scan_result_id FROM customization) "
            "AND sr.is_out_of_scope = 0 "
            f"ORDER BY sr.id LIMIT 200 OFFSET {page * 200}"
        )
        rows = result["rows"]
        all_ids.extend(rows)
        if len(rows) < 200:
            break
        page += 1

    print(f"Total to process: {len(all_ids)}")

    # Filter: skip artifacts that already have substantive observations
    to_process = []
    skipped = 0
    for row in all_ids:
        obs = row.get("observations", "")
        # Skip if observations exist and are more than just a scope rationale
        if obs and len(obs) > 80 and "table:" not in obs[:20].lower():
            # Looks like a real observation already exists
            skipped += 1
            continue
        to_process.append(row)

    print(f"Need observations: {len(to_process)} (skipping {skipped} with existing)")

    # Process
    processed = 0
    errors = 0

    for i, row in enumerate(to_process):
        rid = row["id"]
        sys_class = row["sys_class_name"]

        try:
            detail = get_detail(rid)
            observer = OBSERVERS.get(sys_class, observe_generic)
            observation = observer(detail)

            if observation:
                update_result(rid, observation)
                processed += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  Error on {rid} ({sys_class}): {e}")

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(to_process)} "
                  f"(processed={processed}, errors={errors})")

    print(f"\n{'='*60}")
    print("OBSERVATION SUMMARY")
    print(f"{'='*60}")
    print(f"  Total in-scope:  {len(all_ids)}")
    print(f"  Already had obs: {skipped}")
    print(f"  Newly observed:  {processed}")
    print(f"  Errors:          {errors}")


if __name__ == "__main__":
    main()
