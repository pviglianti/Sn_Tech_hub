---
name: observations
description: >
  Generate detailed functional observations for in-scope artifacts. Use after
  scope triage is complete. Writes what each artifact does and its dependencies.
allowed-tools: mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__generate_observations mcp__tech-assessment-hub__query_instance_live
---

# Observations

Generate functional summaries for in-scope assessment artifacts.

## Setup
1. Get assessment ID from user or $ARGUMENTS
2. Call `get_customizations` — find artifacts with `review_status=review_in_progress` that are NOT out_of_scope

## For each artifact
1. Call `get_result_detail` to read full artifact detail
2. Summarize: what does it do, when does it fire, what fields/tables does it touch, dependencies?
3. Call `update_scan_result` to write `observations`

Keep observations to 2-4 sentences. Focus on WHAT it does, not code structure.

## Iterative Refinement Rules

- Observations on both artifacts and features should be REFINED each pass, not
  replaced. Read what exists first. Add to it, tighten it, correct errors — but
  never blank out or lose prior context.
- Reference artifacts and records by their NAME, not sys_id. Use sys_ids only
  in structured fields (ai_observations JSON, directly_related_result_ids).
  Human-readable text (observations, recommendations, descriptions) should say
  "Business Rule: Reset Assignment Group On Reopen" not "sys_id: abc123...".
- When referencing other artifacts in observations, use the pattern:
  "Related to <Name> (<table>)" — e.g. "Related to Set Assigned (sys_script)".


## Advance Pipeline (Required — do this LAST)

When you have finished ALL work for this stage, advance the pipeline by running:

```bash
curl -s -X POST http://127.0.0.1:$(cat /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/server.url | sed 's|.*:||' | sed 's|/.*||')/api/assessments/${ASSESSMENT_ID}/advance-pipeline \
  -H "Content-Type: application/json" \
  -d '{"target_stage": "review", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
