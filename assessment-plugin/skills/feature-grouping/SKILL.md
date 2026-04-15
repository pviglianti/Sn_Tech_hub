---
name: feature-grouping
description: >
  Group assessed artifacts into logical business features. Use after observations.
  Creates feature records and assigns artifacts to them.
allowed-tools: mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_features mcp__tech-assessment-hub__create_feature mcp__tech-assessment-hub__update_feature mcp__tech-assessment-hub__assign_result_to_feature
---

# Feature Grouping

Group in-scope artifacts into business features.

## Setup
1. Get assessment ID from user or $ARGUMENTS
2. Call `get_customizations` to see triaged artifacts
3. Call `get_features` to see existing features

## Rules
- Artifacts that deliver ONE business capability = one feature
- Name by business purpose ("Incident Auto-Assignment" not "BR + SI")
- Use engine signals (update sets, code refs, naming patterns) as hints
- Every in-scope artifact must end up in a feature — no orphans
- Standalone artifacts → category bucket ("Misc Form Customizations")
- Present your grouping plan to the user before executing

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
curl -s -X POST https://136-112-232-229.nip.io/api/assessments/${ASSESSMENT_ID}/advance-pipeline \
  -H "Content-Type: application/json" \
  -d '{"target_stage": "ai_refinement", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
