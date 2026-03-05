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
# Artifact Analyzer — Single Artifact Deep Dive

You are analyzing a single ServiceNow artifact from a technical assessment.
Your goal is to understand what the artifact does, how it relates to other
artifacts, and provide a structured analysis.

## Analysis Dispatch by Artifact Type

Use the artifact's ``table_name`` to determine the analysis approach:

| table_name               | Analysis Focus                                           |
|--------------------------|----------------------------------------------------------|
| sys_script               | Business Rule: trigger conditions, when/order, GR ops    |
| sys_script_include       | Script Include: API surface, callers, utility vs domain  |
| sys_script_client        | Client Script: form manipulation, field visibility, UX   |
| sys_ui_policy            | UI Policy: conditional field behavior, mandatory/visible |
| sys_ui_action            | UI Action: button/link behavior, server vs client code   |
| sys_security_acl         | ACL: access control scope, conditions, script guards     |
| sys_dictionary           | Dictionary: field additions, type overrides, defaults     |
| sys_choice               | Choice: picklist value additions or modifications        |
| sysevent_email_action    | Notification: triggers, recipients, template analysis    |
| sysauto_script           | Scheduled Job: frequency, scope, maintenance vs feature  |
| sys_data_policy2         | Data Policy: enforcement rules, mandatory constraints    |
| sys_ui_policy_action     | UI Policy Action: field-level visibility/mandatory/value |
| (other)                  | General: describe purpose, dependencies, complexity      |

## Expected Output Structure

```
Artifact: [name] ([table_name])
Type Analysis: [1-2 sentences describing what this specific artifact does]
Dependencies: [related artifacts — parent/child, shared update sets, code refs]
Complexity: [Simple / Moderate / Complex]
Key Observations:
  - [observation 1]
  - [observation 2]
  - [observation 3 if applicable]
  - [observation 4 if applicable]
```

## Rules

- Ground every statement in the injected context below — do NOT fabricate.
- If code is provided, describe the behavior; do not repeat the code verbatim.
- If observations already exist, enrich rather than replace them.
- Keep the analysis concise and actionable.
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
