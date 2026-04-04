"""Technical Architect MCP prompt.

Two-mode prompt handler:
  Mode A — Per-artifact technical review (result_id + assessment_id)
  Mode B — Assessment-wide technical debt roll-up (assessment_id only)

This is an MCP Prompt -- it does NOT call an LLM.  It builds context and
returns prompt text for the connected AI model to reason over.
"""

import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..registry import PromptSpec

# ── Static prompt text — Mode A (per-artifact review) ──────────────────

MODE_A_TEXT = """\
# Technical Architect — Per-Artifact Technical Review

You are performing a technical review of a single ServiceNow artifact from a
technical assessment. Your goal is to evaluate the artifact against the best
practice checks provided below and write actionable recommendations.

## How to Review

1. **Read the artifact detail** — use ``get_result_detail`` to get the full
   artifact detail record (script, conditions, configuration). This is the
   actual ServiceNow configuration record — the same data the observation
   stage used to summarize what the artifact does.

2. **Check against every applicable BestPractice** — the injected context
   below includes all active best practice checks that apply to this artifact
   type. Evaluate the artifact against EACH one. Common violations to look for:
   - Hardcoded sys_ids in scripts
   - Direct SQL or GlideRecord in client scripts
   - Missing null checks before GlideRecord operations
   - Business rules without conditions (fire on every operation)
   - Synchronous GlideHTTPRequest calls in business rules
   - Global business rules that should be table-specific
   - Scripts that bypass ACLs with setWorkflow(false)
   - Hardcoded credentials or URLs

3. **Write the recommendation** — use ``update_scan_result`` to set the
   ``recommendation`` field on the scan result. This is where your findings go.
   The recommendation should be specific and actionable:

   **If the artifact is clean:** "Follows best practices. No violations found.
   Recommend keeping as-is and migrating to scoped application."

   **If there are violations:** "Violates BP-003 (hardcoded sys_ids in line 45)
   and BP-012 (no condition on business rule — fires on every update). Should be
   refactored if the customer wants to keep this: add a condition filter and
   replace hardcoded sys_ids with sys_properties lookups."

   **If it's really bad:** "Multiple critical violations: BP-001 (synchronous
   HTTP callout in before business rule causing form hang), BP-003 (hardcoded
   credentials in script), BP-015 (GlideRecord in client script). Strongly
   recommend refactoring — this artifact will cause performance issues and is
   a security risk. If keeping, all three violations must be addressed."

   **If it duplicates OOTB:** "This business rule replicates the OOTB
   assignment rule functionality available via Assignment Lookup Rules.
   Recommend replacing with OOTB configuration to reduce maintenance burden."

## Disposition Guidance

Based on your best practice review, suggest a disposition direction in the
recommendation text:

- **Keep** — clean, follows best practices, serves clear purpose
- **Keep and Refactor** — has violations but the logic is sound. Specify
  exactly what needs to be fixed.
- **Replace with OOTB** — duplicates platform functionality
- **Evaluate for Retirement** — may be obsolete or unused

**Important:** Do NOT set the ``disposition`` field on the scan result.
Write your suggestion in the ``recommendation`` field only. Disposition
is confirmed by a human after stakeholder review.

## Scope Awareness

- Skip artifacts marked ``is_out_of_scope``
- Artifacts marked ``is_adjacent`` get lighter analysis
- Focus your deepest review on in-scope, customized artifacts

## Multi-Pass Awareness

This stage may run multiple times.

- **If the recommendation field is empty** — first pass. Do your full best
  practice review and write recommendations from scratch.
- **If the recommendation field already has content** — refinement pass.
  Read the existing recommendation. Verify it against the current artifact
  state. Add any findings missed in prior passes. If the observation has
  been enriched since the last pass (new relationships, clearer context),
  update the recommendation to reflect that. If the existing recommendation
  looks thorough and accurate, leave it and move on.

## Rules

- Evaluate against EVERY applicable BestPractice check in the list below.
- Be specific — cite the BestPractice code (e.g., BP-003) and the line or
  field where the violation occurs.
- Write the recommendation to the ``recommendation`` field via ``update_scan_result``.
- Do not repeat code verbatim — describe what it does and what's wrong.
- Keep ``review_status`` as ``review_in_progress`` (never ``reviewed``).
- Never set ``disposition`` directly — suggest it in the recommendation text.
"""

# ── Static prompt text — Mode B (assessment-wide roll-up) ──────────────

MODE_B_TEXT = """\
# Technical Architect — Assessment-Wide Technical Debt Roll-up

You are producing an assessment-wide technical findings summary.  Your goal
is to scan across all artifacts for systemic patterns, aggregate findings by
severity, and identify the most impactful technical debt items.

## Expected Output Structure

```
Assessment-Wide Technical Findings — [assessment number]
CRITICAL [count]: [Finding] — [X] artifacts affected
HIGH [count]: ...
MEDIUM [count]: ...
```

## Rules

- Ground every statement in the injected context below — do NOT fabricate.
- Focus on systemic patterns, not individual artifact issues.
- Group related findings together (e.g., all hardcoded sys_id violations).
- Prioritize findings by business impact and remediation effort.
- Reference BestPractice codes where applicable.
- Keep the analysis concise and actionable.
"""


# ── Context-building helpers ────────────────────────────────────────

def _extract_code_snippet(scan_result: Any, max_lines: int = 200) -> Optional[str]:
    """Extract code from raw_data_json if available."""
    if not scan_result.raw_data_json:
        return None
    try:
        raw = json.loads(scan_result.raw_data_json)
    except (json.JSONDecodeError, TypeError):
        return None
    for key in ("script", "code_body", "meta_code_body", "condition"):
        code = raw.get(key)
        if code and isinstance(code, str) and code.strip():
            lines = code.splitlines()
            if len(lines) > max_lines:
                return (
                    "\n".join(lines[:max_lines])
                    + f"\n... (truncated, {len(lines)} total lines)"
                )
            return code
    return None


def _build_best_practice_checklist(
    session: Session,
    applies_to: Optional[str] = None,
) -> str:
    """Query active BestPractice records, optionally filter by applies_to.

    If ``applies_to`` is provided (e.g., "sys_script"), include:
    - BestPractice records where applies_to is NULL (applies to all)
    - BestPractice records where applies_to contains the given table name

    Always exclude is_active=False records.
    Returns formatted checklist text.
    """
    from ...models import BestPractice

    # Query all active best practices
    stmt = select(BestPractice).where(BestPractice.is_active == True)  # noqa: E712
    all_active = session.exec(stmt).all()

    if applies_to:
        # Filter: NULL applies_to (global) OR applies_to contains this table
        filtered = []
        for bp in all_active:
            if bp.applies_to is None:
                # NULL means applies to all
                filtered.append(bp)
            elif applies_to in [t.strip() for t in bp.applies_to.split(",")]:
                filtered.append(bp)
        practices = filtered
    else:
        # No filter — return all active (Mode B)
        practices = list(all_active)

    if not practices:
        return "  (no applicable best practice checks found)"

    lines: List[str] = []
    for bp in practices:
        severity_tag = f"[{bp.severity.upper()}]" if bp.severity else ""
        scope_tag = f" (applies to: {bp.applies_to})" if bp.applies_to else " (all)"
        lines.append(
            f"  - **{bp.code}** {severity_tag} {bp.title}{scope_tag}"
        )
        if bp.description:
            lines.append(f"    {bp.description}")
        if bp.detection_hint:
            lines.append(f"    Detection: {bp.detection_hint}")
        if bp.recommendation:
            lines.append(f"    Recommendation: {bp.recommendation}")
    return "\n".join(lines)


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


def _build_assessment_summary(
    session: Session, assessment_id: int,
) -> str:
    """Build aggregate summary of all ScanResults in this assessment."""
    from ...models import ScanResult, Scan

    # Get all scans in this assessment
    scans = session.exec(
        select(Scan).where(Scan.assessment_id == assessment_id)
    ).all()

    if not scans:
        return "  (no scans found)"

    scan_ids = [s.id for s in scans]

    # Get all scan results
    results = session.exec(
        select(ScanResult).where(
            ScanResult.scan_id.in_(scan_ids)  # type: ignore[attr-defined]
        )
    ).all()

    if not results:
        return "  (no scan results found)"

    # Aggregate by table_name
    table_counts: Dict[str, int] = {}
    total = len(results)
    for sr in results:
        table_counts[sr.table_name] = table_counts.get(sr.table_name, 0) + 1

    lines: List[str] = []
    lines.append(f"  Total artifacts: {total}")
    lines.append(f"  Artifact types:")
    for table, count in sorted(table_counts.items(), key=lambda x: -x[1]):
        lines.append(f"    - {table}: {count}")

    # Aggregate by origin_type if available
    origin_counts: Dict[str, int] = {}
    for sr in results:
        origin = sr.origin_type.value if sr.origin_type else "unknown"
        origin_counts[origin] = origin_counts.get(origin, 0) + 1
    if origin_counts:
        lines.append(f"  Origin types:")
        for origin, count in sorted(origin_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    - {origin}: {count}")

    # Aggregate by disposition if available
    disposition_counts: Dict[str, int] = {}
    for sr in results:
        if sr.disposition:
            disp = sr.disposition.value
            disposition_counts[disp] = disposition_counts.get(disp, 0) + 1
    if disposition_counts:
        lines.append(f"  Dispositions assigned:")
        for disp, count in sorted(disposition_counts.items(), key=lambda x: -x[1]):
            lines.append(f"    - {disp}: {count}")

    return "\n".join(lines)


def _build_general_recommendations_context(
    session: Session, assessment_id: int,
) -> str:
    """Query GeneralRecommendation rows for this assessment."""
    from ...models import GeneralRecommendation

    recs = session.exec(
        select(GeneralRecommendation).where(
            GeneralRecommendation.assessment_id == assessment_id,
        )
    ).all()

    if not recs:
        return "  (no general recommendations)"

    lines: List[str] = []
    for rec in recs:
        severity_tag = f" [{rec.severity.value}]" if rec.severity else ""
        lines.append(f"  - **{rec.title}**{severity_tag}")
        if rec.description:
            lines.append(f"    {rec.description}")
    return "\n".join(lines)


# ── Mode A handler ──────────────────────────────────────────────────

def _handle_mode_a(
    arguments: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    """Mode A: Per-artifact technical review."""
    from ...models import ScanResult

    result_id_str = arguments.get("result_id", "")
    assessment_id_str = arguments.get("assessment_id", "")

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
    sections.append(
        f"- **Origin:** "
        f"{scan_result.origin_type.value if scan_result.origin_type else 'unknown'}"
    )
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

    # 2. Code snippet (up to 200 lines)
    code = _extract_code_snippet(scan_result, max_lines=200)
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

    # 4. Update set context
    if assessment_id:
        us_ctx = _build_update_set_context(session, result_id, assessment_id)
        sections.append("## Update Set Links\n")
        sections.append(us_ctx)
        sections.append("")

    # 5. BestPractice checklist (filtered by applies_to matching table_name)
    bp_checklist = _build_best_practice_checklist(
        session, applies_to=scan_result.table_name,
    )
    sections.append("## Applicable Best Practice Checks\n")
    sections.append(bp_checklist)
    sections.append("")

    # Assemble final prompt
    context_block = "\n".join(sections)
    full_text = (
        MODE_A_TEXT
        + "\n---\n\n"
        + "# Injected Context\n\n"
        + context_block
    )

    return {
        "description": "Per-artifact technical review with BestPractice evaluation.",
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": full_text},
            }
        ],
    }


# ── Mode B handler ──────────────────────────────────────────────────

def _handle_mode_b(
    arguments: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    """Mode B: Assessment-wide technical debt roll-up."""
    from ...models import Assessment

    assessment_id_str = arguments.get("assessment_id", "")

    try:
        assessment_id = int(assessment_id_str)
    except (ValueError, TypeError):
        raise ValueError(f"Assessment not found: {assessment_id_str}")

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise ValueError(f"Assessment not found: {assessment_id}")

    # Build context sections
    sections: List[str] = []

    # 1. Assessment metadata
    sections.append("## Assessment Metadata\n")
    sections.append(f"- **Name:** {assessment.name}")
    sections.append(f"- **Number:** {assessment.number}")
    sections.append(f"- **State:** {assessment.state.value}")
    sections.append("")

    # 2. Aggregate summary
    summary_ctx = _build_assessment_summary(session, assessment_id)
    sections.append("## Assessment-Wide Artifact Summary\n")
    sections.append(summary_ctx)
    sections.append("")

    # 3. General recommendations (landscape context)
    rec_ctx = _build_general_recommendations_context(session, assessment_id)
    sections.append("## General Recommendations (Landscape)\n")
    sections.append(rec_ctx)
    sections.append("")

    # 4. Full BestPractice catalog (all active, NOT filtered by applies_to)
    bp_checklist = _build_best_practice_checklist(session, applies_to=None)
    sections.append("## Full Best Practice Catalog (Active)\n")
    sections.append(bp_checklist)
    sections.append("")

    # Assemble final prompt
    context_block = "\n".join(sections)
    full_text = (
        MODE_B_TEXT
        + "\n---\n\n"
        + "# Injected Context\n\n"
        + context_block
    )

    return {
        "description": "Assessment-wide technical debt roll-up.",
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": full_text},
            }
        ],
    }


# ── Main handler (dispatch) ──────────────────────────────────────────

def _technical_architect_handler(
    arguments: Dict[str, Any],
    *,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Build and return the technical architect prompt.

    Mode dispatch:
      - If ``result_id`` is provided -> Mode A (per-artifact review)
      - If only ``assessment_id``    -> Mode B (assessment-wide roll-up)

    When ``session`` is None the handler returns a static prompt without
    dynamic context injection (graceful fallback).
    """
    result_id_str = arguments.get("result_id", "")
    assessment_id_str = arguments.get("assessment_id", "")
    has_result_id = bool(result_id_str)

    # --- Graceful fallback: no session ---
    if session is None:
        if has_result_id:
            text = MODE_A_TEXT
        else:
            text = MODE_B_TEXT

        text += (
            "\n---\n\n"
            "**Note:** No database session available. Provide artifact details "
            "manually or use MCP tools to query the assessment data.\n"
        )
        if result_id_str:
            text += f"\nRequested result_id: {result_id_str}\n"
        if assessment_id_str:
            text += f"Requested assessment_id: {assessment_id_str}\n"

        return {
            "description": "Technical architect review (no DB session).",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }

    # --- Normal path: dispatch to Mode A or Mode B ---
    if has_result_id:
        return _handle_mode_a(arguments, session)
    else:
        return _handle_mode_b(arguments, session)


# ── Prompt Specs for Registration ──────────────────────────────────

PROMPT_SPECS: List[PromptSpec] = [
    PromptSpec(
        name="technical_architect",
        description="Technical architect review — Mode A evaluates a single "
                    "artifact against BestPractice checks with disposition "
                    "guidance; Mode B produces an assessment-wide technical "
                    "debt roll-up.  Dispatches based on whether result_id "
                    "is provided.",
        arguments=[
            {
                "name": "result_id",
                "description": (
                    "ScanResult ID for per-artifact review (Mode A). "
                    "Omit for assessment-wide roll-up (Mode B)."
                ),
                "required": False,
            },
            {
                "name": "assessment_id",
                "description": "Assessment ID (required for both modes).",
                "required": True,
            },
        ],
        handler=_technical_architect_handler,
    ),
]
