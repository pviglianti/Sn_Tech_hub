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

2. **Read the artifact detail record** by calling ``get_result_detail`` with \
the result_id. The response includes an ``artifact_detail`` field — this is \
the actual ServiceNow configuration record with the field settings, code, \
conditions, and configuration that tell you exactly what this artifact does. \
Use this to write a concrete functional summary:
   - **Business Rules** (sys_script): Read the artifact detail for the script, \
when it fires (before/after/async), what operations trigger it (insert/update/ \
delete), the order, conditions, filter conditions, and what table (collection). \
Describe what the script does in functional terms.
   - **Script Includes** (sys_script_include): Read the class code, what \
methods it exposes, what tables it queries, what it returns.
   - **Client Scripts** (sys_script_client): What form behavior it controls, \
what fields it manipulates, what conditions trigger it.
   - **UI Policies** (sys_ui_policy): What fields it shows/hides/makes \
mandatory, what conditions trigger it, whether reverse_if_false is set.
   - **Dictionary Entries** (sys_dictionary): What table, what field, what \
type (reference, choice, string), if reference what table it points to.
   - **ACLs** (sys_security_acl): What access it controls, what conditions, \
what roles are required.
   - **UI Actions** (sys_ui_action): What the button/link does when clicked.
   - **Notifications** (sysevent_email_action): What triggers it, who receives it.
   - **Scheduled Jobs** (sysauto_script): What it does and how often.

   Your observation should read like a knowledgeable ServiceNow developer \
explaining what this artifact does. Example observations:

   - "This on-insert business rule on incident (order 200, before) appends \
the caller's department name to the short_description field when category \
is 'network'. Condition: category=network AND caller_id is not empty."
   - "This UI policy on the incident form makes business_service mandatory \
and visible when priority is 1-Critical. Reverse if false is enabled, so \
the field returns to optional when priority changes."
   - "This script include exposes the class IncidentEscalation with methods \
escalateToManager() and notifyOnCall(). It queries sys_user_grmember to \
find the on-call rotation and creates notification events via \
gs.eventQueue('incident.escalated')."
   - "This dictionary entry adds a custom reference field u_parent_incident \
to the incident table, referencing incident itself (self-referential). \
Max length 32, not mandatory. Used for parent-child incident linking."

3. **Call out relationships to other customized artifacts**: This is critical \
for grouping. Not every field or table a script touches matters here — what \
matters is when this artifact references, calls, or depends on ANOTHER \
customized scan result that is in scope for this assessment (customer-created \
or OOTB-modified). Those are the relationships that inform feature grouping.

   For example: a business rule's script may call `current.setValue('state', 2)` \
— that is just setting a field, not a relationship to another customized artifact. \
But if that same script does `new IncidentRoutingHelper()` and IncidentRoutingHelper \
is a customized script include that is also a scan result in this assessment — THAT \
is a relationship worth noting. Similarly, if a dictionary entry has a reference \
field type pointing to a table where other customized artifacts live, that is a \
dependency between customized records.

   What to look for:
   - A business rule that calls a custom script include (also a scan result) → name it
   - A client script that references a custom field (also a scan result) → name it
   - A dictionary entry with a reference field pointing to a table with other \
     customized artifacts → note the dependency
   - A UI policy that controls fields added by customized dictionary entries → note it
   - Any artifact whose behavior depends on or feeds into another customized \
     scan result in this assessment

   These cross-artifact dependencies between customized results are what drive \
feature grouping — they tell us which artifacts work together as part of a \
solution. Include them in the observation alongside what the artifact does.

4. **Update the observation** using ``update_scan_result`` with the \
``observations`` field. Keep ``review_status`` as ``review_in_progress``.

## Observation Evolution

Observations evolve across pipeline iterations:

**Early passes (basic):** "This before-update business rule on incident \
(order 200) sets assignment_group based on category. Condition: category \
changes."

**Enriched (with artifact detail + relationships):** "This before-update \
business rule on incident (order 200) fires when category changes. It calls \
the customized script include 'IncidentRoutingHelper' (scan result ID 3045, \
also in this assessment) to look up the category-to-group mapping, then sets \
assignment_group to the returned value. The script also references the \
customized dictionary entry 'u_escalation_tier' (scan result ID 3102) on \
the incident table. Related to the UI policy 'Critical Incident Fields' \
(scan result ID 3078) which controls visibility of the same escalation \
fields on the form."

When enriching, build on what's already there. The key additions are:
- Concrete details from the artifact detail record (order, when, conditions)
- Relationships to OTHER customized scan results in the assessment
- What the code actually does in functional terms (not code reproduction)

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

## Context from other artifacts (use when needed)

You are processing artifacts one at a time. If you need to check what other
customized artifacts exist in this assessment — to find relationships, see
what's been observed, or understand patterns — use ``get_customizations`` to
see the full list with scope flags, observations, and artifact types.

**Do NOT call this for every artifact.** Only look when:
- You need to identify which other customized scan results this artifact
  references or depends on (for the relationship section of the observation)
- You want to check if a script include or table this artifact calls is also
  a customized scan result in the assessment
- You need scan result IDs to reference in the observation

Most artifacts can be summarized from their own artifact detail record alone.
Only reach for the broader list when writing the relationship/dependency part.

## Scope Awareness

- **Skip** artifacts marked ``is_out_of_scope`` — they are excluded from
  feature grouping and final deliverables.
- **Include** artifacts marked ``is_adjacent`` — they are in scope but not \
  directly on the assessed app's tables/forms. Give them lighter treatment \
  but still document what they do and how they interact with the assessed app.
- Scope flags were set by the earlier ``ai_analysis`` stage.

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
