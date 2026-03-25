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
# Artifact Analyzer — What Does This Artifact Do?

You are analyzing a single customized ServiceNow artifact from a technical
assessment. Your job is to produce a clear, functional summary of what this
artifact does and how it connects to other customized artifacts in the
assessment.

## Your Two Tasks

### 1. Scope Decision

Make a quick scope determination:

| Scope Decision  | Meaning | Action |
|-----------------|---------|--------|
| ``in_scope``    | Directly customized for the assessed app — on its tables, records, or forms | Proceed to full functional summary |
| ``adjacent``    | In scope for the assessment but NOT directly on the assessed app's tables/records/forms — e.g., a script on change_request that references incident, a field on another table that calls incident APIs | Lighter summary, mark ``is_adjacent=true`` |
| ``out_of_scope``| No relation to the assessed app or trivial OOTB modification | Mark ``is_out_of_scope=true``, write brief reason, skip full analysis |
| ``needs_review``| Unclear — flag for human triage | Note uncertainty, skip full analysis |

**Adjacent does NOT mean out of scope.** Adjacent artifacts are included in \
the assessment and may be grouped into features — they just interact with the \
assessed app indirectly rather than sitting directly on its tables/forms.

Scope decisions are preliminary — they may be revised in later stages as
more context is uncovered. Set ``review_status`` to ``review_in_progress``.

### 2. Functional Summary (the observation)

Describe **what this artifact actually does** in plain, functional language.
Focus on the concrete actions:

- **What does it do?** Sets a field? Queries a table? Creates a record?
  Sends a notification? Enforces a condition? Hides/shows UI elements?
  Validates data? Transforms values? Calls an external API?
- **When does it fire?** On insert? On update? On form load? On a schedule?
  When a condition is met?
- **What tables/fields does it touch?** Which tables does it read from or
  write to? Which fields does it set, check, or manipulate?
- **What other customized artifacts does it connect to?** Call out any
  other artifacts that are also customized scan results in this assessment:
  script includes it calls, business rules on the same table, UI policies
  that control the same fields, client scripts that reference the same
  form, etc. Reference them by name.

### What NOT to include in observations

- **No disposition recommendations.** Do not suggest keep/remove/refactor.
  Disposition is decided by a human after stakeholder review.
- **No update set references.** The observation is about functional behavior,
  not deployment packaging.
- **No code reproduction.** Describe what the code does, don't paste it back.
- **No severity/category judgments.** Just describe function and connections.

## Analysis Focus by Artifact Type

Use ``table_name`` to guide what you look for:

| table_name               | What to Describe                                         |
|--------------------------|----------------------------------------------------------|
| sys_script               | Business Rule: what triggers it, what it does to records |
| sys_script_include       | Script Include: what functions/API it exposes, who calls it |
| sys_script_client        | Client Script: what form behavior it controls            |
| sys_ui_policy            | UI Policy: what fields it shows/hides/makes mandatory    |
| sys_ui_action            | UI Action: what the button/link does when clicked        |
| sys_security_acl         | ACL: what access it controls and conditions              |
| sys_dictionary           | Dictionary: what field it adds/modifies and its config   |
| sys_choice               | Choice: what picklist values it adds or changes          |
| sysevent_email_action    | Notification: what triggers it and who receives it       |
| sysauto_script           | Scheduled Job: what it does and how often                |
| sys_data_policy2         | Data Policy: what it enforces on which fields            |
| sys_ui_policy_action     | UI Policy Action: what field behavior it sets            |
| (other)                  | General: describe what it does and what it touches       |

## Expected Output

Write the observation as a **concise functional paragraph** (2-5 sentences).
Lead with what the artifact does, then note connections to other customized
artifacts in the assessment.

**Good observation example:**
> This business rule fires on insert/update of the incident table when
> priority is critical. It queries the cmdb_ci_service table to look up
> the affected service's support group, then sets the assignment_group
> field to that group. It calls the custom script include
> "IncidentRoutingHelper" (also a customized artifact in this assessment)
> to determine escalation rules. Related: the UI policy
> "Critical Incident Fields" controls field visibility on the same form.

**Bad observation example:**
> This is a modified_ootb artifact in update set "Q4 Incident Changes".
> Recommend keep_and_refactor. Severity: medium. Category: customization.

## Live Instance Queries (when needed)

If the injected context is insufficient to understand an artifact — for example, \
it calls a script include not in the assessment results, or references a table \
you need to inspect — you can query the ServiceNow instance directly using \
``query_instance_live``.

**Governance:** Live queries are controlled by the ``ai_analysis.context_enrichment`` \
property:
- ``auto`` (default) — query only when references are detected and not cached locally.
- ``always`` — query for every artifact (higher cost, fuller context).
- ``never`` — local data only, no live queries.

Check the property before querying. Use live queries sparingly — they are for \
filling specific gaps, not routine analysis.

## Rules

- **Scope first** — decide scope before writing the functional summary.
- **Describe function, not metadata** — what it does, not where it came from.
- **Call out connections** — name other customized artifacts in this assessment
  that this artifact references, calls, or is related to.
- **Ground in injected context** — do NOT fabricate behavior or connections.
- **Enrich existing observations** — if observations already exist, build on
  them rather than replacing.
- **Do NOT set disposition** — leave it untouched. A human decides later.
- **Do NOT set severity or category** — just describe function.
- Set ``review_status`` to ``review_in_progress`` (never ``reviewed``).
- Use ``update_scan_result`` to write back scope flags (``is_out_of_scope``,
  ``is_adjacent``) and the functional observation.
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
