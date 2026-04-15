---
name: recommendations
description: >
  Generate best-practice recommendations for assessed artifacts. Reviews code
  quality, checks for violations, and suggests keep/refactor/replace/retire.
allowed-tools: mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_features mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__generate_recommendations mcp__tech-assessment-hub__search_servicenow_docs
---

# Recommendations

Review artifacts for best practices and write recommendations.

## For each in-scope artifact
1. Read full detail via `get_result_detail`
2. Check: hardcoded sys_ids, missing conditions, deprecated APIs, client-side GlideRecord, bypassed ACLs
3. Write recommendation via `update_scan_result`:
   - Clean → "Follows best practices. Keep as-is."
   - Violations → cite specific issues and fixes
   - OOTB duplicate → suggest platform replacement
4. Suggest disposition direction in text (keep/refactor/replace/retire)

Never SET the disposition field — only suggest in recommendation text.

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
  -d '{"target_stage": "report", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
