"""Per-stage tool restrictions and prompt template for Claude Code dispatch.

Each AI pipeline stage gets only the MCP tools it needs. This is safer
(limits blast radius) and cheaper (less tool schema in context window).
"""

from __future__ import annotations

from typing import Dict, List, Optional

_PREFIX = "mcp__tech-assessment-hub__"

STAGE_TOOL_SETS: Dict[str, List[str]] = {
    "ai_analysis": [
        f"{_PREFIX}get_customizations",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}update_scan_result",
    ],
    "observations": [
        f"{_PREFIX}generate_observations",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}get_customizations",
    ],
    "ai_refinement": [
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}feature_grouping_status",
    ],
    "grouping": [
        f"{_PREFIX}create_feature",
        f"{_PREFIX}add_result_to_feature",
        f"{_PREFIX}feature_grouping_status",
        f"{_PREFIX}get_customizations",
    ],
    "recommendations": [
        f"{_PREFIX}feature_recommendation",
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_customizations",
    ],
    "report": [
        f"{_PREFIX}assessment_results",
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_customizations",
    ],
}

_BATCH_PROMPT_TEMPLATE = """\
You are a ServiceNow technical assessment AI. You have access to the
tech-assessment-hub MCP tools to read and write assessment data.

## Task
{stage_instructions}

## Assessment
- Assessment ID: {assessment_id}
- Stage: {stage}
- Batch: {batch_display} of {total_batches}

## Artifacts to Process
{artifact_list}

## Instructions
1. SCOPE TRIAGE FIRST: For each artifact, read its basic details and decide:
   - "in_scope" → proceed to full analysis
   - "adjacent" → related but not a direct customization (e.g., references assessed
     tables/data); set is_adjacent=true, lighter analysis
   - "out_of_scope" → no relation to the assessed app or trivial OOTB modification;
     set is_out_of_scope=true with brief observation, skip deep analysis
   - "needs_review" → unclear scope; set observation noting uncertainty, skip deep analysis
2. For in-scope artifacts, analyze according to the stage requirements above.
3. Write your findings back using the update/write tools.
4. Set review_status to "review_in_progress" — NEVER set it to "reviewed".
   Review status only transitions to "reviewed" at the report stage after human confirmation.
5. Do NOT set a final disposition. You may suggest a disposition in your observations
   or recommendation text, but the disposition field is only confirmed by a human reviewer.
6. Be thorough but efficient — stay within your tool set.
7. Scope decisions are preliminary and may be revised in later pipeline stages
   as more context is uncovered (relationships, feature groupings, usage data).
   Out-of-scope artifacts are excluded from feature grouping and final deliverables.

## Output
After processing all artifacts, summarize what you did as a JSON object:
{{"processed": <count>, "findings": [<brief summary per artifact>]}}
"""


def build_batch_prompt(
    *,
    stage_instructions: str,
    assessment_id: int,
    stage: str,
    batch_index: int,
    total_batches: int,
    artifact_ids: List[int],
    artifact_names: Optional[List[str]] = None,
) -> str:
    """Build the full prompt for one batch dispatch."""
    if artifact_names and len(artifact_names) == len(artifact_ids):
        artifact_list = "\n".join(
            f"- ID {aid}: {name}" for aid, name in zip(artifact_ids, artifact_names)
        )
    else:
        artifact_list = "\n".join(f"- ID {aid}" for aid in artifact_ids)

    return _BATCH_PROMPT_TEMPLATE.format(
        stage_instructions=stage_instructions,
        assessment_id=assessment_id,
        stage=stage,
        batch_display=batch_index + 1,
        total_batches=total_batches,
        artifact_list=artifact_list,
    )
