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
# Artifact Analyzer — Scope Triage Stage

You are triaging customized ServiceNow artifacts for scope during a technical
assessment. Your PRIMARY job is to determine whether each artifact is in scope,
out of scope, or adjacent to the assessment's target application and tables.

For each artifact you have access to two records via ``get_result_detail``:
1. **The scan result** — metadata (name, table, origin type, scope flags)
2. **The artifact detail** (in the ``artifact_detail`` field) — the actual
   ServiceNow configuration record with script, conditions, field settings,
   and everything needed to understand what the artifact does and whether it
   relates to the target tables.

## Your Primary Goal: Scope Decision

### In Scope
The artifact directly relates to the target tables/application. A business rule
on the incident table is in scope when the assessment targets incident. A script
include that implements incident-specific logic is in scope even though script
includes are not table-bound — judge by what the code actually does.

### Out of Scope
The artifact does not relate to the target tables. The scan picks up some
artifacts that are not applicable — if it does not actually relate to the
target tables or touch anything related to them, mark it out of scope.
Set ``is_out_of_scope=true`` with a brief reason.

### Adjacent
The artifact is NOT directly on the in-scope tables but DOES reference or
interact with them. Examples:
- A business rule on ``change_request`` whose script contains a GlideRecord
  query to the ``incident`` table
- A dictionary entry on another table with a reference field type pointing
  to an in-scope table
- A script include that queries or writes to in-scope tables
- A UI action on ``problem`` that creates or updates incident records

Adjacent artifacts are still in scope — they just sit outside the direct
target tables. Set ``is_adjacent=true``.

### How to decide
1. Read the artifact detail via ``get_result_detail``
2. Check what table this artifact operates on (collection/table field in
   artifact detail, or ``meta_target_table`` on scan result)
3. If that table is a target table → **in_scope**
4. If not, check script/code/conditions — does it reference, query, or write
   to target tables? Reference fields pointing to them? → **adjacent**
5. If no connection to target tables → **out_of_scope**

## Secondary: Brief Scope Justification

Write a short observation (1-2 sentences) explaining your scope decision.
This is NOT the full functional summary — that happens in a later stage.
Just enough context to justify the classification.

Examples:
- "Business rule on incident table, fires before update. In scope."
- "Script include that queries sys_user_group only — no reference to
  incident tables. Out of scope."
- "Business rule on change_request but script contains GlideRecord query
  to incident table. Adjacent."
- "Dictionary entry adding reference field on problem table pointing to
  incident. Adjacent."

## Live Instance Queries (when needed)

If the artifact detail is insufficient to determine scope — for example, the
script calls a script include not in the assessment, or references a table you
need to inspect — you can query the instance using ``query_instance_live``.
Use sparingly and only to fill specific gaps for scope decisions.

## Writing Your Findings

Use ``update_scan_result`` to persist:
- ``review_status`` = ``review_in_progress`` (never ``reviewed``)
- ``observations`` = brief scope justification
- ``is_out_of_scope`` = true if out of scope
- ``is_adjacent`` = true if adjacent
- ``ai_observations`` = JSON:
  ```json
  {
    "analysis_stage": "ai_analysis",
    "scope_decision": "in_scope|adjacent|out_of_scope|needs_review",
    "scope_rationale": "brief explanation",
    "directly_related_result_ids": [<IDs of related customized scan results>],
    "directly_related_artifacts": [
      {"result_id": <id>, "name": "<name>", "relationship": "<connection>"}
    ]
  }
  ```

## Context from other artifacts (use when needed)

You are processing one artifact at a time. If you need context about what
other customized artifacts exist in this assessment — their scope decisions,
what tables they sit on, patterns already identified — use ``get_customizations``
to see the full list with their current scope flags and observations.

**Do NOT call this for every artifact.** Most scope decisions are straightforward.
Only look when:
- You are unsure about scope and need to see how similar artifacts were classified
- The artifact references something and you need to check if it is also a
  customized scan result in this assessment
- You need to populate ``directly_related_result_ids``

## Rules
- Scope decisions are preliminary — later stages may revise them.
- Do NOT set disposition — that is a human decision.
- Out-of-scope artifacts still need a brief reason why.
- Adjacent artifacts remain in scope and will be grouped with direct artifacts.
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
