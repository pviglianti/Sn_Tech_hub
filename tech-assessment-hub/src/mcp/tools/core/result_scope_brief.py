"""MCP tool: get_result_scope_brief — minimal detail for scope triage.

The full `get_result_detail` tool joins five extra tables (UpdateSet,
CustomerUpdateXML, VersionHistory ×10, artifact-detail raw SQL) and loads
the whole `raw_data_json` blob. On real assessments that can take 60+s per
call — enough to time out the Claude CLI's MCP HTTP client and hang the run.

For scope triage the classifier only needs a handful of fields: the business
target table, the container table, the name, and the code/condition excerpts
that reveal whether an off-target artifact still touches an in-scope table.
This tool returns exactly that, and nothing else, in <100ms.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from sqlmodel import Session

from ....models import ScanResult
from ...registry import ToolSpec


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "result_id": {
            "type": "integer",
            "description": "ID of the scan result to summarize for scope triage.",
        },
        "script_chars": {
            "type": "integer",
            "description": (
                "Maximum characters of any script-like field to include "
                "(default 2000). Keeps the response small enough to avoid "
                "API round-trip stalls."
            ),
            "default": 2000,
        },
    },
    "required": ["result_id"],
}


# Fields from raw_data_json worth surfacing for scope decisions. Keeping
# this list short is the entire point of this tool.
_SCOPE_RELEVANT_RAW_KEYS = (
    "collection",
    "table",
    "table_name",
    "target_table",
    "condition",
    "filter_condition",
    "advanced_condition",
    "when",
    "action_insert",
    "action_update",
    "action_delete",
    "action_query",
    "reference",
    "reference_qual",
    "element",
    "applies_extended",
    "scope",
    "active",
)

# Script-like fields can be huge. Truncate to a cap so the tool_result stays
# small; the classifier can ask for the full detail if truncation hides the
# decisive evidence.
_SCRIPT_LIKE_KEYS = (
    "script",
    "client_script",
    "processing_script",
    "condition_script",
    "html",
    "default_value",
    "activities_json",
)


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    result_id = params.get("result_id")
    if result_id is None:
        raise ValueError("result_id is required")
    script_cap = int(params.get("script_chars") or 2000)
    if script_cap < 0:
        script_cap = 0

    result = session.get(ScanResult, int(result_id))
    if not result:
        raise ValueError(f"ScanResult not found: {result_id}")

    raw: Dict[str, Any] = {}
    if result.raw_data_json:
        try:
            raw = json.loads(result.raw_data_json) or {}
            if not isinstance(raw, dict):
                raw = {}
        except (ValueError, TypeError):
            raw = {}

    scope_fields: Dict[str, Any] = {}
    for key in _SCOPE_RELEVANT_RAW_KEYS:
        if key in raw and raw[key] not in (None, ""):
            scope_fields[key] = raw[key]

    script_excerpts: Dict[str, Dict[str, Any]] = {}
    for key in _SCRIPT_LIKE_KEYS:
        val = raw.get(key)
        if not val or not isinstance(val, str):
            continue
        if script_cap == 0:
            script_excerpts[key] = {"length": len(val), "excerpt": "", "truncated": True}
            continue
        truncated = len(val) > script_cap
        script_excerpts[key] = {
            "length": len(val),
            "excerpt": val[:script_cap],
            "truncated": truncated,
        }

    return {
        "success": True,
        "result_id": result.id,
        "sys_id": result.sys_id,
        "name": result.name,
        "sys_class_name": result.sys_class_name,
        "sys_scope": result.sys_scope,
        # The two table fields. meta_target_table is the business subject
        # (e.g. `incident`); table_name is the metadata container (e.g.
        # `sys_script`). Scope decisions should key off meta_target_table
        # first and only fall through to code inspection when that is null
        # or not in the in-scope list.
        "meta_target_table": result.meta_target_table,
        "table_name": result.table_name,
        "origin_type": result.origin_type.value if result.origin_type else None,
        "head_owner": result.head_owner.value if result.head_owner else None,
        # Fields lifted out of raw_data_json that actually drive the
        # decision tree (table/collection, condition, reference qual, etc.).
        "scope_fields": scope_fields,
        # Script/HTML bodies, capped. The classifier greps these for
        # `GlideRecord('incident')` and similar cross-table evidence.
        "script_excerpts": script_excerpts,
        # Existing human/AI observations — useful for iterative refinement
        # and dedupe (if scope_decision is already present, skip).
        "observations": result.observations,
        "ai_observations": result.ai_observations,
    }


TOOL_SPEC = ToolSpec(
    name="get_result_scope_brief",
    description=(
        "Return a lightweight scope-triage-focused summary of a single scan "
        "result: its business target table, metadata container table, scope-"
        "relevant raw fields (collection, condition, when, reference_qual, "
        "etc.), truncated excerpts of script-like fields (script, html, "
        "processing_script), and any prior ai_observations. Far faster and "
        "smaller than get_result_detail — use this for scope classification. "
        "Escalate to get_result_detail only when the excerpt is truncated and "
        "the tail actually matters for the decision."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
