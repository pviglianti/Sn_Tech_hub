"""Artifact Analyzer MCP prompt.

Queries the database for a single ScanResult and its related context
(structural relationships, update set links, observations) and returns
a structured prompt that guides the MCP client through artifact analysis.

This is an MCP Prompt -- it does NOT call an LLM.  It builds context and
returns prompt text for the connected AI model to reason over.
"""

import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..registry import PromptSpec

# ── Static prompt text (system instructions) ───────────────────────

ARTIFACT_ANALYZER_TEXT = """\
# Artifact Analyzer — AI Analysis Stage

You are analyzing customized ServiceNow artifacts during a technical assessment.
For each artifact, you have access to two key records:

1. **The scan result** — metadata about the artifact (name, table, origin type,
   scope flags, review status)
2. **The artifact detail record** — the actual ServiceNow configuration record
   with the best details for understanding what it does. For a business rule this
   includes the script, when it fires (before/after/async), what operations trigger
   it (insert/update/delete), the order, conditions, and the table it runs on.
   For a UI policy it includes the conditions and actions. For a script include
   it includes the full class code. Use ``get_result_detail`` to retrieve both —
   the artifact detail is returned in the ``artifact_detail`` field.

## Step 1: Determine Scope

Before analyzing what an artifact does, you must first determine if it is
**in scope** for this assessment. The assessment targets specific tables and
applications (shown in the Assessment Scope section below).

### In Scope
The artifact directly relates to the target tables/application. A business rule
on the incident table is in scope when the assessment targets incident. A script
include that implements incident-specific logic is in scope even though script
includes are not table-bound.

### Out of Scope
The artifact does not relate to the target tables/application. The scan picks up
some artifacts that are not applicable — for example, a business rule on
cmdb_ci_server when the assessment targets incident. Mark it out of scope with
a brief reason and move on. Set ``is_out_of_scope=true``.

### Adjacent
The artifact is NOT directly on the in-scope tables but DOES reference or
interact with them. Examples:

- A business rule on ``change_request`` that has a script referencing the
  ``incident`` table (when incident is in scope)
- A dictionary entry on another table with a reference field type pointing
  to the ``incident`` table
- A script include that queries or writes to in-scope tables even though
  the script include itself is not table-bound
- A UI action on ``problem`` that creates or updates incident records

Adjacent artifacts are still in scope for the assessment — they just sit
outside the direct target tables. Mark ``is_adjacent=true``.

### Scope Decision Process
1. Check what table this artifact operates on (collection/table field in the
   artifact detail, or ``meta_target_table`` on the scan result)
2. If that table is one of the assessment's target tables → **in_scope**
3. If not, check the artifact's script/code/conditions — does it reference,
   query, or write to any of the target tables? Does it have reference fields
   pointing to target tables? → **adjacent** (mark ``is_adjacent=true``)
4. If it has no connection to the target tables → **out_of_scope** (mark
   ``is_out_of_scope=true``, write a brief reason why)

## Step 2: Summarize What It Does

Once you have determined scope, read the artifact detail record returned by
``get_result_detail`` (in the ``artifact_detail`` field). This is the actual
configuration record from ServiceNow with all the field settings, code,
conditions, and configuration that tell you exactly what this artifact does.

Use this to write a **concrete, functional observation** that describes
the artifact's behavior. Your observation should read like a knowledgeable
ServiceNow developer explaining what this artifact does to a colleague.

### What to include in the observation

- **What it does** — sets fields, queries tables, creates records, sends
  notifications, enforces conditions, hides/shows UI elements, validates data
- **When it fires** — on insert, on update, before/after, on form load,
  on a schedule, under what conditions
- **Configuration details** — the order, priority, conditions, filter
  conditions, what fields it touches, what values it sets
- **What code does** — if it has a script, describe what the script does
  in functional terms (not by reproducing the code)
- **Connections** — call out other customized artifacts in this assessment
  that this artifact references, calls, or is related to

### Examples of good observations

**Business Rule:**
> This before-insert business rule on the incident table (order 200) fires
> when priority is 1-Critical. It sets the assignment_group field to the
> service desk escalation group by querying cmdb_ci_service for the affected
> CI's support group. Condition: priority=1. It calls the custom script
> include "IncidentRoutingHelper" (also in this assessment) for escalation
> logic.

**UI Policy:**
> This UI policy on the incident form makes the "business_service" field
> mandatory and visible when the category is "network". It also sets
> "subcategory" to read-only. Reverse if false is enabled, so the field
> returns to optional when category changes away from network.

**Script Include:**
> This script include exposes the class "IncidentEscalation" with methods
> escalateToManager() and notifyOnCall(). It queries sys_user_grmember to
> find the on-call rotation and creates notification events via
> gs.eventQueue('incident.escalated'). Called by the business rule
> "Auto Escalate Critical" (also in this assessment).

**Dictionary Entry:**
> This adds a custom reference field "u_parent_incident" to the incident
> table, referencing the incident table itself (self-referential). Max
> length 32, not mandatory. Used for parent-child incident linking.

### What NOT to include

- No disposition recommendations (keep/remove/refactor) — a human decides later
- No code reproduction — describe what the code does, don't paste it back
- No severity/category judgments — just describe function
- No update set references — the observation is about behavior, not packaging

## Live Instance Queries (when needed)

If the artifact detail and scan result context are insufficient — for example,
the script calls a script include not in the assessment, or references a table
you need to inspect — you can query the ServiceNow instance directly using
``query_instance_live``.

Use live queries sparingly and only to fill specific gaps.

## Writing Your Findings

Use ``update_scan_result`` to persist:

- ``review_status`` = ``review_in_progress`` (never ``reviewed``)
- ``observations`` = your functional summary paragraph
- ``is_out_of_scope`` = true if out of scope
- ``is_adjacent`` = true if adjacent
- ``ai_observations`` = JSON object:
  ```json
  {
    "analysis_stage": "ai_analysis",
    "scope_decision": "in_scope|adjacent|out_of_scope|needs_review",
    "scope_rationale": "brief explanation of why this scope was chosen",
    "directly_related_result_ids": [<IDs of other customized scan results related to this artifact>],
    "directly_related_artifacts": [
      {"result_id": <id>, "name": "<name>", "relationship": "<how they connect>"}
    ]
  }
  ```

**Do NOT set disposition.** That is a human decision made after review.
"""


# ── Context-building helpers ────────────────────────────────────────

def _extract_code_snippet(scan_result: Any, max_lines: int = 150) -> Optional[str]:
    """Extract code from raw_data_json if available."""
    if not scan_result.raw_data_json:
        return None
    try:
        raw = json.loads(scan_result.raw_data_json)
    except (json.JSONDecodeError, TypeError):
        return None
    # Look for script fields in the raw data
    for key in ("script", "code_body", "meta_code_body", "condition"):
        code = raw.get(key)
        if code and isinstance(code, str) and code.strip():
            lines = code.splitlines()
            if len(lines) > max_lines:
                return "\n".join(lines[:max_lines]) + f"\n... (truncated, {len(lines)} total lines)"
            return code
    return None


def _build_structural_context(
    session: Session, scan_result_id: int, assessment_id: int,
) -> str:
    """Query StructuralRelationship rows for this artifact."""
    from ...models import StructuralRelationship, ScanResult

    # Parent relationships (this artifact is a child)
    parent_rels = session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.child_scan_result_id == scan_result_id,
            StructuralRelationship.assessment_id == assessment_id,
        )
    ).all()

    # Child relationships (this artifact is a parent)
    child_rels = session.exec(
        select(StructuralRelationship).where(
            StructuralRelationship.parent_scan_result_id == scan_result_id,
            StructuralRelationship.assessment_id == assessment_id,
        )
    ).all()

    lines: List[str] = []
    if parent_rels:
        for rel in parent_rels:
            parent = session.get(ScanResult, rel.parent_scan_result_id)
            parent_name = parent.name if parent else f"(id={rel.parent_scan_result_id})"
            parent_table = parent.table_name if parent else "unknown"
            lines.append(
                f"  - Parent: {parent_name} ({parent_table}) "
                f"[{rel.relationship_type}]"
            )
    if child_rels:
        for rel in child_rels:
            child = session.get(ScanResult, rel.child_scan_result_id)
            child_name = child.name if child else f"(id={rel.child_scan_result_id})"
            child_table = child.table_name if child else "unknown"
            lines.append(
                f"  - Child: {child_name} ({child_table}) "
                f"[{rel.relationship_type}]"
            )
    return "\n".join(lines) if lines else "  (none found)"


def _build_update_set_context(
    session: Session, scan_result_id: int, assessment_id: int,
) -> str:
    """Query UpdateSetArtifactLink rows to find associated update sets."""
    from ...models import UpdateSetArtifactLink, UpdateSet

    links = session.exec(
        select(UpdateSetArtifactLink).where(
            UpdateSetArtifactLink.scan_result_id == scan_result_id,
            UpdateSetArtifactLink.assessment_id == assessment_id,
        )
    ).all()

    if not links:
        return "  (none linked)"

    lines: List[str] = []
    for link in links:
        us = session.get(UpdateSet, link.update_set_id)
        us_name = us.name if us else f"(id={link.update_set_id})"
        current_marker = " [current]" if link.is_current else ""
        lines.append(f"  - {us_name}{current_marker} (source: {link.link_source})")
    return "\n".join(lines)


# ── Main handler ────────────────────────────────────────────────────

def _artifact_analyzer_handler(
    arguments: Dict[str, Any],
    *,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Build and return the artifact analyzer prompt with injected context.

    When ``session`` is None the handler returns a static prompt without
    dynamic context injection (graceful fallback for environments that
    don't pass a DB session).
    """
    result_id_str = arguments.get("result_id", "")
    assessment_id_str = arguments.get("assessment_id", "")

    # --- Graceful fallback: no session ---
    if session is None:
        text = ARTIFACT_ANALYZER_TEXT + (
            "\n---\n\n"
            "**Note:** No database session available. Provide artifact details "
            "manually or use MCP tools to query the assessment data.\n"
        )
        if result_id_str:
            text += f"\nRequested result_id: {result_id_str}\n"
        if assessment_id_str:
            text += f"Requested assessment_id: {assessment_id_str}\n"
        return {
            "description": "Analyze a single ServiceNow artifact in depth.",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }

    # --- Normal path: query DB and build context ---
    from ...models import ScanResult

    try:
        result_id = int(result_id_str)
    except (ValueError, TypeError):
        raise ValueError(f"ScanResult not found: {result_id_str}")

    scan_result = session.get(ScanResult, result_id)
    if scan_result is None:
        raise ValueError(f"ScanResult not found: {result_id}")

    assessment_id = int(assessment_id_str) if assessment_id_str else None

    # Build context sections
    sections: List[str] = []

    # 1. Artifact metadata
    sections.append("## Artifact Metadata\n")
    sections.append(f"- **Name:** {scan_result.name}")
    sections.append(f"- **Table:** {scan_result.table_name}")
    sections.append(f"- **Origin:** {scan_result.origin_type.value if scan_result.origin_type else 'unknown'}")
    sections.append(f"- **Active:** {scan_result.is_active}")
    if scan_result.meta_target_table:
        sections.append(f"- **Target Table:** {scan_result.meta_target_table}")
    if scan_result.finding_description:
        sections.append(f"- **Description:** {scan_result.finding_description}")
    if scan_result.review_status:
        sections.append(f"- **Review Status:** {scan_result.review_status.value}")
    if scan_result.disposition:
        sections.append(f"- **Disposition:** {scan_result.disposition.value}")
    if scan_result.is_out_of_scope:
        sections.append("- **Out of Scope:** Yes")
    if scan_result.is_adjacent:
        sections.append("- **Adjacent:** Yes")
    sections.append("")

    # 2. Code snippet
    code = _extract_code_snippet(scan_result)
    if code:
        sections.append("## Code Snippet\n")
        sections.append("```javascript")
        sections.append(code)
        sections.append("```\n")

    # 3. Existing observations
    if scan_result.observations:
        sections.append("## Existing Observations\n")
        sections.append(scan_result.observations)
        sections.append("")
    if scan_result.ai_observations:
        sections.append("## AI Observations (JSON)\n")
        sections.append(f"```json\n{scan_result.ai_observations}\n```\n")

    # 4. Structural relationships
    if assessment_id:
        structural_ctx = _build_structural_context(session, result_id, assessment_id)
        sections.append("## Structural Relationships\n")
        sections.append(structural_ctx)
        sections.append("")

        # 5. Update set links
        us_ctx = _build_update_set_context(session, result_id, assessment_id)
        sections.append("## Update Set Links\n")
        sections.append(us_ctx)
        sections.append("")

    # Assemble final prompt
    context_block = "\n".join(sections)
    full_text = (
        ARTIFACT_ANALYZER_TEXT
        + "\n---\n\n"
        + "# Injected Context\n\n"
        + context_block
    )

    return {
        "description": "Analyze a single ServiceNow artifact in depth.",
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": full_text},
            }
        ],
    }


# ── Prompt Specs for Registration ──────────────────────────────────

PROMPT_SPECS: List[PromptSpec] = [
    PromptSpec(
        name="artifact_analyzer",
        description="Deep-dive analysis of a single ServiceNow artifact — "
                    "queries metadata, code, structural relationships, and "
                    "update set context to build a comprehensive analysis prompt.",
        arguments=[
            {
                "name": "result_id",
                "description": "ScanResult ID of the artifact to analyze",
                "required": True,
            },
            {
                "name": "assessment_id",
                "description": "Assessment ID for scoping related data queries",
                "required": True,
            },
        ],
        handler=_artifact_analyzer_handler,
    ),
]
