"""Observation prompt templates for the Phase 5 observation pipeline.

These prompts guide MCP-connected AI models through reviewing and refining
the deterministic baseline observations produced by ``generate_observations``.

Two prompts are provided:
- ``observation_landscape_reviewer`` — refine the landscape summary with
  contextual analysis and strategic recommendations.
- ``observation_artifact_reviewer`` — review and enrich per-artifact
  observations with deeper technical insights.
"""

from typing import Any, Dict, List

from ..registry import PromptSpec


# ── Landscape Summary Reviewer ───────────────────────────────────────

LANDSCAPE_SUMMARY_REVIEWER_TEXT = """\
# Observation Pipeline — Landscape Summary Reviewer

You are reviewing the automated landscape summary produced for a ServiceNow \
technical assessment. The ``generate_observations`` tool has already created \
a deterministic baseline summary stored as a ``GeneralRecommendation`` record \
with category ``landscape_summary``.

## Your Task

1. **Read the existing landscape summary** by querying the assessment's \
general recommendations (category = ``landscape_summary``).

2. **Analyze the customization landscape** by reviewing:
   - Distribution of artifact types (use ``get_sheet_summary`` or inspect \
scan results grouped by ``table_name``).
   - Origin mix (modified OOTB vs net-new customer).
   - Update set context — which update sets dominate, and what do they \
indicate about project history.
   - Any notable patterns: heavy scripting, large form-layout changes, \
integration artifacts, etc.

3. **Write an enriched landscape summary** (3-6 sentences) that covers:
   - The overall volume and complexity of customizations.
   - Key risk areas or patterns requiring attention.
   - Preliminary strategic observations (e.g., "heavy reliance on custom \
business rules suggests an integration-heavy approach" or "most \
customizations are form-level changes that may have OOTB replacements").
   - Any gaps the deterministic baseline missed.

4. **Update the landscape summary** using the ``update_general_recommendation`` \
tool (or upsert approach) — overwrite the baseline description with your \
enriched version. Preserve the category as ``landscape_summary``.

## Rules

- Keep the summary concise — 3 to 6 sentences max.
- Ground every claim in data from the assessment (cite counts and artifact \
types).
- Do NOT fabricate observations — only reference artifacts you actually found.
- The summary informs human reviewers; write for clarity and actionability.
"""


# ── Per-Artifact Observation Reviewer ────────────────────────────────

ARTIFACT_OBSERVATION_REVIEWER_TEXT = """\
# Observation Pipeline — Per-Artifact Observation Reviewer

You are reviewing the deterministic per-artifact observations produced by \
the ``generate_observations`` tool. Each customized ``ScanResult`` record \
now has an ``observations`` field containing a baseline observation and an \
``ai_observations`` JSON field with metadata (structural signals, update set \
counts, usage data).

## Your Task

For each customized ScanResult that has ``review_status = pending_review``:

1. **Read the existing observation** — check ``observations`` text and \
``ai_observations`` JSON for context.

2. **Analyze the artifact deeper** if the baseline is generic:
   - If the artifact is scriptable (Business Rule, Script Include, Client \
Script, UI Action, ACL), read the code snippet (``code_body`` or \
``meta_code_body`` field) and summarize the behavior in 1-2 sentences.
   - Check structural relationships — parent/child signals indicate \
dependencies that affect disposition.
   - Review update set context — artifacts sharing update sets likely \
belong to the same feature.
   - If usage data is available in ``ai_observations``, interpret it: \
zero usage within lookback window suggests the artifact may be inactive.

3. **Write an enriched observation** (2-4 sentences):
   - What the artifact does and why it matters.
   - Risk or complexity level (simple config change vs complex script).
   - Preliminary disposition hint if obvious (e.g., "likely has OOTB \
replacement via Flow Designer" or "custom utility — must migrate as-is").
   - Relationships to other artifacts or features if visible.

4. **Update the observation** using ``update_scan_result`` with the \
``observations`` field. Keep ``review_status`` as ``pending_review`` — \
human reviewers will set it to ``reviewed`` after their own check.

## Batch Processing Strategy

- Process results in batches of 10-20.
- Focus on scriptable and high-complexity artifacts first — they benefit \
most from AI enrichment.
- Simple form-field or dictionary-entry observations may be adequate as-is.
- Track your progress and report batch completion counts.

## Rules

- Never fabricate code behavior — only describe what you actually see.
- If you can't determine what an artifact does, say so ("Purpose unclear \
from available metadata; manual review recommended").
- Keep observations concise — 2-4 sentences per artifact.
- Do NOT change ``review_status`` — that's for human reviewers.
- Do NOT change ``disposition`` or ``recommendation`` — those come from \
the feature reasoning pipeline later.
"""


# ── Handlers ─────────────────────────────────────────────────────────

def _landscape_reviewer_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Return the landscape summary reviewer prompt."""
    assessment_id = arguments.get("assessment_id")
    text = LANDSCAPE_SUMMARY_REVIEWER_TEXT
    if assessment_id:
        text += (
            f"\n---\n\n**Active context:** You are reviewing the landscape "
            f"summary for assessment_id={assessment_id}. Start by reading "
            f"the existing landscape_summary general recommendation.\n"
        )
    return {
        "description": "Review and enrich the deterministic landscape summary "
                       "for a ServiceNow technical assessment.",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": text,
                },
            }
        ],
    }


def _artifact_reviewer_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Return the per-artifact observation reviewer prompt."""
    assessment_id = arguments.get("assessment_id")
    text = ARTIFACT_OBSERVATION_REVIEWER_TEXT
    if assessment_id:
        text += (
            f"\n---\n\n**Active context:** You are reviewing per-artifact "
            f"observations for assessment_id={assessment_id}. Query for "
            f"customized ScanResults with review_status=pending_review "
            f"and begin enriching observations.\n"
        )
    return {
        "description": "Review and enrich per-artifact observations for "
                       "customized ScanResult records.",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": text,
                },
            }
        ],
    }


# ── Prompt Specs for Registration ────────────────────────────────────

PROMPT_SPECS: List[PromptSpec] = [
    PromptSpec(
        name="observation_landscape_reviewer",
        description="Review and enrich the automated landscape summary — "
                    "analyze customization patterns, risk areas, and strategic "
                    "observations for the assessment.",
        arguments=[
            {
                "name": "assessment_id",
                "description": "Assessment ID whose landscape summary to review",
                "required": True,
            }
        ],
        handler=_landscape_reviewer_handler,
    ),
    PromptSpec(
        name="observation_artifact_reviewer",
        description="Review and enrich per-artifact observations — "
                    "deeper analysis of scriptable artifacts, usage patterns, "
                    "and structural dependencies.",
        arguments=[
            {
                "name": "assessment_id",
                "description": "Assessment ID whose artifact observations to review",
                "required": True,
            }
        ],
        handler=_artifact_reviewer_handler,
    ),
]
