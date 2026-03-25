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

## Purpose

Observations are the foundation of the assessment. They describe **what each \
artifact actually does** in functional terms. Good observations directly feed \
feature grouping — the AI uses them to determine which artifacts work together \
as part of a solution. The basic functional observation should already be present \
from the initial pass; your job is to enrich it.

## Your Task

For each customized ScanResult that has ``review_status`` of ``pending_review``
or ``review_in_progress``:

1. **Read the existing observation** — check ``observations`` text and \
``ai_observations`` JSON for context.

2. **Enrich the functional description** if the baseline is generic or missing \
detail:
   - **Scriptable artifacts** (Business Rule, Script Include, Client Script, \
UI Action, ACL): Read the code snippet (``code_body`` or ``meta_code_body``) \
and describe the behavior concretely — what fields does it set? What tables \
does it query or write to? What conditions trigger it? What GlideRecord \
queries does it run and with what encodedQuery / ref qualifiers?
   - **Fields** (dictionary entries): What table is this field on? What type \
is it (reference, choice, string, etc.)? If it's a reference field, what table \
does it reference and with what reference qualifier?
   - **UI Policies / Client Scripts**: What fields do they show/hide/make \
mandatory? What form conditions trigger them?
   - **Check structural relationships** — parent/child signals indicate direct \
dependencies (UI Policy → UI Policy Actions, etc.)

3. **Call out connections to other customized artifacts**: This is critical for \
grouping. If this artifact calls, references, queries, or is called by another \
customized scan result in this assessment, name it explicitly. These connections \
are definitive grouping signals:
   - A business rule that calls a custom script include → name it
   - A client script that references a custom field → name it
   - An ACL that checks a custom role → name it
   - A scheduled job that queries an in-scope table → note the table

4. **Update the observation** using ``update_scan_result`` with the \
``observations`` field. Keep ``review_status`` as ``review_in_progress``.

## Observation Evolution

Observations evolve across pipeline iterations:

**Early passes (basic):** "This business rule fires on incident insert when \
priority is 1. It queries cmdb_ci_service and sets assignment_group."

**Later passes (with feature context):** "This business rule fires on incident \
insert when priority is critical. It calls the custom script include \
'IncidentRoutingHelper' (also in this assessment) to determine the escalation \
group based on the affected CI's support group. Part of the Critical Incident \
Routing feature along with the UI policy 'Critical Incident Fields' and the \
client script 'Priority Escalation Warning'."

When enriching, build on what's already there. If an observation already has \
good functional detail, add relationship context. If it already has relationship \
context, verify accuracy and add any missing connections.

## What NOT to Include

- **No disposition recommendations** — never suggest keep/remove/refactor/replace. \
Disposition is decided by the customer's stakeholders after reviewing findings.
- **No update set references** — observations describe functional behavior, not \
deployment packaging.
- **No code reproduction** — describe what the code does, don't paste it back.
- **No severity/category judgments** — just describe function and connections.

## Live Instance Queries (when needed)

If the local assessment data is insufficient to understand an artifact — for \
example, a business rule references a script include not in the scan results, \
or a field references a table you need to inspect — you can query the ServiceNow \
instance directly using ``query_instance_live``.

**Governance:** Live queries are controlled by the ``ai_analysis.context_enrichment`` \
property:
- ``auto`` (default) — query only when references are detected and data is not \
cached locally.
- ``always`` — query for every artifact (higher cost, fuller context).
- ``never`` — local data only, no live queries.

Check the property before querying. Use live queries sparingly and only to fill \
specific gaps — not for routine observation enrichment.

## Batch Processing Strategy

- Process results in batches of 10-20.
- Focus on scriptable and high-complexity artifacts first — they benefit \
most from enrichment and provide the most grouping signal.
- Simple form-field or dictionary-entry observations may be adequate with \
just the basic "field X on table Y, type Z, references table W" description.
- Track your progress and report batch completion counts.

## Scope Awareness

- **Skip** artifacts marked ``is_out_of_scope`` — they are excluded from
  feature grouping and final deliverables.
- **Include** artifacts marked ``is_adjacent`` — they are in scope but not \
  directly on the assessed app's tables/forms. Give them lighter treatment \
  but still document what they do and how they interact with the assessed app.
- Scope flags may have been set by the earlier ``ai_analysis`` stage.

## Rules

- Never fabricate code behavior — only describe what you actually see.
- If you can't determine what an artifact does, say so ("Purpose unclear \
from available metadata; manual review recommended").
- Keep observations concise — 2-5 sentences per artifact.
- Do NOT change ``review_status`` — it stays at ``review_in_progress``
  throughout the pipeline until the report stage.
- Do NOT change ``disposition`` — disposition is decided by the customer's \
  stakeholders after all analysis is complete.
- If a human has already reviewed and edited an observation, preserve the \
  premise — you may refine wording for clarity but never change the substance.
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
