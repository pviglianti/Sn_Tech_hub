---
name: observations
description: >
  Generate detailed functional observations for in-scope artifacts. Use after
  scope triage is complete. Writes what each artifact does and its dependencies.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__generate_observations mcp__tech-assessment-hub__query_instance_live
---

# Observations

Generate functional summaries for in-scope assessment artifacts. Custom results (both ootb modified and net new customer created customizations) that are adjacent and in scope (not marked as out of scope)

## Setup
1. Get assessment ID from user or $ARGUMENTS
2. **Call `get_assessment_context(assessment_id)`** — caches the target app, in_scope_tables, parent_table, and keywords. Frame your observations against this app (don't say "this BR fires on insert" — say "this BR fires on insert to `incident`, the target table for this assessment").
3. Page through `get_customizations(assessment_id, limit=50, offset=<0,50,100,…>)` until the page is short of `limit`. **Client-side filter**: process only rows where `is_out_of_scope == false` (in_scope + adjacent both flow through). Do NOT filter by `review_status` — the tool doesn't accept it and it's a human-only field.

## For each artifact
1. Call `get_result_detail` to read full artifact detail.
2. If a referenced field/table/script is unclear and you need to confirm it exists or what it points to, use `query_instance_live` to peek at the live ServiceNow instance — but only when needed (each call is a network round-trip).
3. Summarize: what does it do, when does it fire, what fields/tables does it touch, dependencies?
4. Call `update_scan_result` to write `observations`.

Keep observations to 2-4 sentences. Focus on WHAT it does, not code structure. If it has any best practice violations (like improper use of `current.update()` in BR that could be recursive, hardcoded sys_ids, GlideRecord in loops, etc.) call them out — these will be the basis for the recommendations stage that follows. The full catalog is checked in the recommendations skill via `get_best_practices`; here just flag what's obviously wrong.

The `generate_observations` MCP tool can bulk-generate baseline observations from artifact metadata when you want a starting point for a large queue — call it, then refine the per-artifact text yourself.

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
  -d '{"target_stage": "review", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
