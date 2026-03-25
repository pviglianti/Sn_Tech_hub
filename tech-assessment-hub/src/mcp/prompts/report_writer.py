"""Report Writer MCP prompt.

Collects all assessment data from the database and returns a comprehensive
prompt for the AI to generate a structured assessment deliverable report.

This is an MCP Prompt -- it does NOT call an LLM.  It builds context and
returns prompt text for the connected AI model to reason over.
"""

from collections import Counter
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..registry import PromptSpec

# ── Static prompt text (system instructions) ───────────────────────

REPORT_WRITER_TEXT = """\
# Report Writer — ServiceNow Technical Assessment Deliverable

You are writing a formal technical assessment report for a ServiceNow instance.
Your goal is to synthesize all injected context into a clear, professional
deliverable that communicates findings, risks, and recommendations.

## Report Structure

Write the report using the following sections (only include sections that
were requested):

### 1. Executive Summary
- 2-3 paragraphs covering scope, key findings, and top 3 recommendations.
- State the assessment type, instance name, and number of artifacts analyzed.
- Highlight the most critical issues discovered.

### 2. Customization Landscape
- Volume and distribution of customizations across artifact types.
- Origin mix: customer-created vs modified OOTB vs pristine OOTB.
- Update set patterns and development practices observed.

### 3. Feature Analysis
- Each feature group with its disposition, sorted by complexity/risk.
- Member count and primary artifact types for each feature.
- AI-generated summaries and recommendations per feature.
- Ungrouped customized artifacts that require attention.

### 4. Technical Findings
- Systemic issues organized by severity (critical → info).
- Code health indicators and best practice gaps.
- Platform upgrade risks and compatibility concerns.

### 5. Recommendations
- Prioritized action items: critical → high → medium.
- Each recommendation should include rationale and expected impact.
- Group related recommendations where appropriate.

## Scope Filtering

- **Exclude** artifacts marked ``is_out_of_scope`` from all report sections,
  feature counts, and recommendation lists. They are not part of the
  deliverable.
- **Include** artifacts marked ``is_adjacent`` but note their adjacency —
  they are relevant context but not direct customizations of the assessed app.

## Review Status & Disposition

- The report stage is the FINAL stage. After generating the report, set
  ``review_status`` to ``reviewed`` on all in-scope and adjacent artifacts.
- Disposition values in the report are SUGGESTED — the report should present
  them as recommendations for client confirmation, not final decisions.
- Group artifacts by suggested disposition in the feature analysis section.

## Output Formats and Tools

When running through Claude Code, you have access to output plugins for \
producing polished deliverables:

- **Word (docx)** — Primary format for assessment reports. Use the Word \
skill/plugin to create structured documents with headings, tables, and \
professional formatting.
- **Excel (xlsx)** — Artifact inventories, feature-to-disposition matrices, \
comparison tables. Use the Excel skill/plugin for tabular data deliverables.
- **PowerPoint (pptx)** — Executive briefings, stakeholder presentations with \
key findings and recommendations. Use the PowerPoint skill/plugin.
- **PDF** — Formatted final deliverables when PDF output is preferred.

Use the **writing-plans** skill to plan multi-section report production, and \
**executing-plans** to work through the plan with review checkpoints.

## Writing Rules

- Ground every statement in the injected context below — do NOT fabricate.
- Use professional, consultative tone appropriate for a client deliverable.
- Quantify findings wherever data supports it (e.g., "42 of 120 artifacts").
- Flag areas where data is incomplete and further analysis may be needed.
- Keep recommendations actionable and specific to ServiceNow platform.
"""

# Section name constants
SECTION_EXECUTIVE_SUMMARY = "executive_summary"
SECTION_LANDSCAPE = "landscape"
SECTION_FEATURES = "features"
SECTION_TECHNICAL_FINDINGS = "technical_findings"
SECTION_RECOMMENDATIONS = "recommendations"

ALL_SECTIONS = [
    SECTION_EXECUTIVE_SUMMARY,
    SECTION_LANDSCAPE,
    SECTION_FEATURES,
    SECTION_TECHNICAL_FINDINGS,
    SECTION_RECOMMENDATIONS,
]

# Format presets
FORMAT_FULL = "full"
FORMAT_EXECUTIVE_ONLY = "executive_only"
FORMAT_TECHNICAL_ONLY = "technical_only"

FORMAT_SECTION_MAP = {
    FORMAT_FULL: ALL_SECTIONS,
    FORMAT_EXECUTIVE_ONLY: [SECTION_EXECUTIVE_SUMMARY, SECTION_LANDSCAPE, SECTION_RECOMMENDATIONS],
    FORMAT_TECHNICAL_ONLY: [SECTION_FEATURES, SECTION_TECHNICAL_FINDINGS, SECTION_RECOMMENDATIONS],
}


# ── Context-building helpers ────────────────────────────────────────

def _build_assessment_metadata(assessment: Any, instance: Any, scan_count: int) -> str:
    """Build the assessment metadata context section."""
    lines = [
        "## Assessment Metadata\n",
        f"- **Name:** {assessment.name}",
        f"- **Number:** {assessment.number}",
        f"- **State:** {assessment.state.value if assessment.state else 'unknown'}",
        f"- **Type:** {assessment.assessment_type.value if assessment.assessment_type else 'unknown'}",
        f"- **Instance:** {instance.name}" if instance else "- **Instance:** (unknown)",
        f"- **Scans:** {scan_count}",
        "",
    ]
    return "\n".join(lines)


def _build_landscape_section(session: Session, assessment_id: int) -> str:
    """Build the landscape summary from GeneralRecommendation records."""
    from ...models import GeneralRecommendation

    recs = session.exec(
        select(GeneralRecommendation).where(
            GeneralRecommendation.assessment_id == assessment_id,
            GeneralRecommendation.category == "landscape_summary",
        )
    ).all()

    if not recs:
        return "## Customization Landscape\n\n  (No landscape summary data available.)\n"

    lines = ["## Customization Landscape\n"]
    for rec in recs:
        lines.append(f"### {rec.title}\n")
        if rec.description:
            lines.append(rec.description)
        lines.append("")
    return "\n".join(lines)


def _build_technical_findings_section(session: Session, assessment_id: int) -> str:
    """Build technical findings from GeneralRecommendation records."""
    from ...models import GeneralRecommendation

    recs = session.exec(
        select(GeneralRecommendation).where(
            GeneralRecommendation.assessment_id == assessment_id,
            GeneralRecommendation.category == "technical_findings",
        )
    ).all()

    if not recs:
        return "## Technical Findings\n\n  (No technical findings recorded.)\n"

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    recs_sorted = sorted(
        recs,
        key=lambda r: severity_order.get(r.severity.value if r.severity else "info", 5),
    )

    lines = ["## Technical Findings\n"]
    for rec in recs_sorted:
        sev = f"[{rec.severity.value}]" if rec.severity else "[unrated]"
        lines.append(f"### {sev} {rec.title}\n")
        if rec.description:
            lines.append(rec.description)
        lines.append("")
    return "\n".join(lines)


def _build_feature_section(
    session: Session, assessment_id: int,
) -> str:
    """Build feature groups with member counts and dispositions."""
    from ...models import Feature, FeatureScanResult

    features = session.exec(
        select(Feature).where(Feature.assessment_id == assessment_id)
    ).all()

    lines = ["## Feature Analysis\n"]

    if not features:
        lines.append("  (No feature groups defined.)\n")
    else:
        for feat in features:
            member_count = session.exec(
                select(FeatureScanResult).where(
                    FeatureScanResult.feature_id == feat.id,
                )
            ).all()
            disp = feat.disposition.value if feat.disposition else "unassigned"
            lines.append(f"### {feat.name}")
            lines.append(f"- **Disposition:** {disp}")
            lines.append(f"- **Members:** {len(member_count)}")
            if feat.description:
                lines.append(f"- **Description:** {feat.description}")
            if feat.recommendation:
                lines.append(f"- **Recommendation:** {feat.recommendation}")
            if feat.ai_summary:
                lines.append(f"- **AI Summary:** {feat.ai_summary}")
            lines.append("")

    # Ungrouped customized artifacts
    ungrouped = _build_ungrouped_artifacts(session, assessment_id)
    lines.append(ungrouped)

    return "\n".join(lines)


def _build_ungrouped_artifacts(session: Session, assessment_id: int) -> str:
    """Find customized ScanResults NOT linked to any Feature."""
    from ...models import ScanResult, Scan, FeatureScanResult, OriginType

    # Get all scan IDs for this assessment
    scans = session.exec(
        select(Scan).where(Scan.assessment_id == assessment_id)
    ).all()
    scan_ids = [s.id for s in scans]

    if not scan_ids:
        return "### Ungrouped Artifacts\n\n  (No scans found.)\n"

    # Get all customized scan results
    customized_types = [OriginType.modified_ootb, OriginType.net_new_customer]
    customized_results = session.exec(
        select(ScanResult).where(
            ScanResult.scan_id.in_(scan_ids),  # type: ignore[attr-defined]
            ScanResult.origin_type.in_(customized_types),  # type: ignore[attr-defined]
        )
    ).all()

    # Get IDs of scan results linked to features
    grouped_ids = set()
    for sr in customized_results:
        links = session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.scan_result_id == sr.id,
            )
        ).all()
        if links:
            grouped_ids.add(sr.id)

    ungrouped = [sr for sr in customized_results if sr.id not in grouped_ids]

    lines = ["### Ungrouped Artifacts\n"]
    if not ungrouped:
        lines.append("  (All customized artifacts are grouped into features.)\n")
    else:
        lines.append(f"**{len(ungrouped)}** customized artifact(s) not assigned to any feature:\n")
        for sr in ungrouped[:20]:  # Cap display at 20
            lines.append(f"- {sr.name} ({sr.table_name}) — {sr.origin_type.value if sr.origin_type else 'unknown'}")
        if len(ungrouped) > 20:
            lines.append(f"  ... and {len(ungrouped) - 20} more")
    lines.append("")
    return "\n".join(lines)


def _build_recommendations_section(session: Session, assessment_id: int) -> str:
    """Build general recommendations (excluding landscape_summary and technical_findings)."""
    from ...models import GeneralRecommendation

    excluded_categories = {"landscape_summary", "technical_findings"}
    recs = session.exec(
        select(GeneralRecommendation).where(
            GeneralRecommendation.assessment_id == assessment_id,
        )
    ).all()
    recs = [r for r in recs if r.category not in excluded_categories]

    if not recs:
        return "## Recommendations\n\n  (No general recommendations recorded.)\n"

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    recs_sorted = sorted(
        recs,
        key=lambda r: severity_order.get(r.severity.value if r.severity else "info", 5),
    )

    lines = ["## Recommendations\n"]
    for rec in recs_sorted:
        sev = f"[{rec.severity.value}]" if rec.severity else "[unrated]"
        lines.append(f"### {sev} {rec.title}\n")
        if rec.description:
            lines.append(rec.description)
        lines.append("")
    return "\n".join(lines)


def _build_statistics_section(session: Session, assessment_id: int) -> str:
    """Build statistics: total artifacts, customized count, breakdowns."""
    from ...models import ScanResult, Scan, OriginType

    scans = session.exec(
        select(Scan).where(Scan.assessment_id == assessment_id)
    ).all()
    scan_ids = [s.id for s in scans]

    if not scan_ids:
        return "## Statistics\n\n  (No scan data available.)\n"

    all_results = session.exec(
        select(ScanResult).where(
            ScanResult.scan_id.in_(scan_ids),  # type: ignore[attr-defined]
        )
    ).all()

    total = len(all_results)
    customized_types = [OriginType.modified_ootb, OriginType.net_new_customer]
    customized = [sr for sr in all_results if sr.origin_type in customized_types]
    customized_count = len(customized)

    # Reviewed count
    from ...models import ReviewStatus
    reviewed = [sr for sr in all_results if sr.review_status == ReviewStatus.reviewed]

    # Grouped count
    from ...models import FeatureScanResult
    grouped_ids = set()
    for sr in all_results:
        links = session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.scan_result_id == sr.id,
            )
        ).all()
        if links:
            grouped_ids.add(sr.id)

    # Table breakdown
    table_counter: Counter = Counter()
    for sr in all_results:
        table_counter[sr.table_name] += 1

    lines = [
        "## Statistics\n",
        f"- **Total artifacts:** {total}",
        f"- **Customized:** {customized_count}",
        f"- **Reviewed:** {len(reviewed)}",
        f"- **Grouped into features:** {len(grouped_ids)}",
        "",
        "### Breakdown by table_name\n",
    ]
    for table_name, count in table_counter.most_common():
        lines.append(f"- {table_name}: {count}")
    lines.append("")

    return "\n".join(lines)


# ── Main handler ────────────────────────────────────────────────────

def _report_writer_handler(
    arguments: Dict[str, Any],
    *,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Build and return the report writer prompt with injected context.

    When ``session`` is None the handler returns a static prompt without
    dynamic context injection (graceful fallback for environments that
    don't pass a DB session).
    """
    assessment_id_str = arguments.get("assessment_id", "")
    sections_str = arguments.get("sections", "")
    format_str = arguments.get("format", FORMAT_FULL)

    # --- Graceful fallback: no session ---
    if session is None:
        text = REPORT_WRITER_TEXT + (
            "\n---\n\n"
            "**Note:** No database session available. Provide assessment data "
            "manually or use MCP tools to query the assessment.\n"
        )
        if assessment_id_str:
            text += f"\nRequested assessment_id: {assessment_id_str}\n"
        return {
            "description": "Generate a structured assessment report.",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }

    # --- Normal path: query DB and build context ---
    from ...models import Assessment, Instance

    try:
        assessment_id = int(assessment_id_str)
    except (ValueError, TypeError):
        raise ValueError(f"Assessment not found: {assessment_id_str}")

    assessment = session.get(Assessment, assessment_id)
    if assessment is None:
        raise ValueError(f"Assessment not found: {assessment_id}")

    instance = session.get(Instance, assessment.instance_id)

    # Determine which sections to include
    requested_sections = _resolve_sections(sections_str, format_str)

    # Count scans
    from ...models import Scan
    scans = session.exec(
        select(Scan).where(Scan.assessment_id == assessment_id)
    ).all()
    scan_count = len(scans)

    # Build context sections
    context_parts: List[str] = []

    # Always include assessment metadata
    context_parts.append(_build_assessment_metadata(assessment, instance, scan_count))

    # Always include statistics
    context_parts.append(_build_statistics_section(session, assessment_id))

    # Conditional sections
    if SECTION_EXECUTIVE_SUMMARY in requested_sections:
        context_parts.append("## Executive Summary\n")
        context_parts.append(
            "Write a 2-3 paragraph executive summary based on the data above "
            "and below. Cover scope, key findings, and top 3 recommendations.\n"
        )

    if SECTION_LANDSCAPE in requested_sections:
        context_parts.append(_build_landscape_section(session, assessment_id))

    if SECTION_FEATURES in requested_sections:
        context_parts.append(_build_feature_section(session, assessment_id))

    if SECTION_TECHNICAL_FINDINGS in requested_sections:
        context_parts.append(_build_technical_findings_section(session, assessment_id))

    if SECTION_RECOMMENDATIONS in requested_sections:
        context_parts.append(_build_recommendations_section(session, assessment_id))

    # Assemble final prompt
    context_block = "\n".join(context_parts)
    full_text = (
        REPORT_WRITER_TEXT
        + "\n---\n\n"
        + "# Injected Context\n\n"
        + context_block
    )

    return {
        "description": "Generate a structured assessment report.",
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": full_text},
            }
        ],
    }


def _resolve_sections(sections_str: str, format_str: str) -> List[str]:
    """Determine which report sections to include.

    Priority: explicit sections param > format param > all sections.
    """
    if sections_str:
        return [s.strip() for s in sections_str.split(",") if s.strip()]
    return FORMAT_SECTION_MAP.get(format_str, ALL_SECTIONS)


# ── Prompt Specs for Registration ──────────────────────────────────

PROMPT_SPECS: List[PromptSpec] = [
    PromptSpec(
        name="report_writer",
        description="Generate a structured ServiceNow technical assessment report — "
                    "queries assessment metadata, features, recommendations, and "
                    "statistics to build a comprehensive report prompt.",
        arguments=[
            {
                "name": "assessment_id",
                "description": "Assessment ID to generate the report for",
                "required": True,
            },
            {
                "name": "sections",
                "description": (
                    "Comma-separated list of sections to include "
                    "(default: all). Options: executive_summary, landscape, "
                    "features, technical_findings, recommendations"
                ),
                "required": False,
            },
            {
                "name": "format",
                "description": (
                    "Report format preset: 'full' (default), "
                    "'executive_only', 'technical_only'"
                ),
                "required": False,
            },
        ],
        handler=_report_writer_handler,
    ),
]
