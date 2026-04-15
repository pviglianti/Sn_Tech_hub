---
name: scope-triage
description: >
  Run AI scope triage on a ServiceNow technical assessment. Classifies customized
  artifacts as in_scope, adjacent, or out_of_scope. Use when the user says
  "run scope triage", "analyze assessment", or "triage artifacts".
allowed-tools: mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__query_instance_live
---

# Scope Triage

You have MCP access to the Tech Assessment Hub.

## Setup
1. Ask the user which assessment ID to work on (or use $ARGUMENTS)
2. Call `get_customizations` to see what needs triage
3. Filter to `review_status=pending_review` — skip already-done ones

## Decision tree for each artifact

Call `get_result_detail` for the artifact. Then:

1. **Table is a target table?** → in_scope
2. **No table (e.g. script include)?** Check if code references target tables → in_scope if yes, out_of_scope if no
3. **Table exists but NOT a target table?** Check if it references/queries target tables → adjacent if yes, out_of_scope if no

Both in_scope and adjacent are IN SCOPE. Adjacent just means "in scope but on a different table."

## Write results
Call `update_scan_result`:
- `review_status` = `review_in_progress`
- `observations` = ONE sentence scope justification
- `is_out_of_scope` / `is_adjacent` as appropriate
- `ai_observations` = `{"analysis_stage":"ai_analysis","scope_decision":"...","scope_rationale":"..."}`

## Speed rules
- ONE `get_result_detail` call per artifact
- Do NOT do deep code analysis — just enough for scope
- Report progress every 10 artifacts

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
  -d '{"target_stage": "observations", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
