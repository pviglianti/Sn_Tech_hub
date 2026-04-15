---
name: scope-triage
description: >
  Run AI scope triage on a ServiceNow technical assessment. Classifies customized
  artifacts as in_scope, adjacent, or out_of_scope. Use when the user says
  "run scope triage", "analyze assessment", or "triage artifacts".
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__query_instance_live
---

# Scope Triage

You have MCP access to the Tech Assessment Hub.

## Setup

1. Ask the user which assessment ID to work on (or use `$ARGUMENTS`).
2. **FIRST — always call `get_assessment_context(assessment_id)`.**
   This returns the live scope definition for THIS assessment. Cache it for every decision.
   Key fields you MUST use:
   - `target_app.name` / `target_app.label` — what app is being assessed
   - `in_scope_tables` — the authoritative list of tables that are IN scope
   - `parent_table` — usually adjacent (e.g., `task` for Incident, `planned_task` for SPM)
   - `keywords` — string hints for tableless artifacts (e.g., `["incident", "inc"]`)
   - `file_classes` — which artifact types the scan covered
   - `scope_filter` — `global` | `scoped` | `all`
3. Call `get_customizations(assessment_id, review_status="pending_review")` to get the queue.

**Never guess target tables.** Incident → `["incident", "incident_task"]`. SPM → 11 tables including `pm_project`, `rm_story`, etc. The tool tells you what they are for THIS assessment — don't assume.

## Decision tree for each artifact

Call `get_result_detail` for the artifact. Let `T` = the artifact's table (usually the `collection` field). Use the cached `get_assessment_context` result:

1. **`T` is in `in_scope_tables`?** → **in_scope**
2. **No table (e.g. script include, UI page)?** Check if code references any `in_scope_tables` or their fields, or matches `keywords`. Also note if it interacts with other in-scope configurations → **in_scope** if yes, **out_of_scope** if no
3. **`T` exists but NOT in `in_scope_tables`?**
   - If `T == parent_table` (e.g., `task`, `planned_task`) → **adjacent**
   - If `T` references/queries/extends an `in_scope_table` → **adjacent**
   - Otherwise → **out_of_scope**

Both `in_scope` and `adjacent` are IN SCOPE. `adjacent` just means "in scope but on a different table."

## Worked examples

**Assessment: Incident** (`in_scope_tables = ["incident", "incident_task"]`, `parent_table = "task"`)

| Artifact | Table | Decision |
|---|---|---|
| Business Rule "Close Incident" | `incident` | **in_scope** |
| Script Include "IncidentUtils" (references `GlideRecord('incident')`) | `null` | **in_scope** |
| Script Include "UtilityMath" (no incident refs) | `null` | **out_of_scope** |
| UI Action "Assign to me" on `task` | `task` | **adjacent** |
| Business Rule on `change_request` | `change_request` | **out_of_scope** |

**Assessment: SPM** (`in_scope_tables` includes `pm_project`, `pm_project_task`, `rm_story`, `rm_epic`, etc.; `parent_table = "planned_task"`)

| Artifact | Table | Decision |
|---|---|---|
| UI Policy on `rm_story` | `rm_story` | **in_scope** |
| Business Rule on `planned_task` | `planned_task` | **adjacent** (parent) |
| Client Script on `task` | `task` | **out_of_scope** (task is too generic; not a target) |

## Write results
Call `update_scan_result`:
- `review_status` = `review_in_progress`
- `observations` = ONE sentence scope justification
- `is_out_of_scope` / `is_adjacent` as appropriate
- `ai_observations` = `{"analysis_stage":"ai_analysis","scope_decision":"...","scope_rationale":"..."}`

## Speed rules
- ONE `get_result_detail` call per artifact
- Do NOT do deep code analysis, but the observation field on the result for an artifact should explain exactly what the configuration does and what other in scope configurations (or adjacent) that it relies on, updates, calls, etc.

## Iterative Refinement Rules

- Observations on both artifacts and features should be REFINED each pass, not
  replaced. Read what exists first. Add to it, tighten it based on additional context provided by later steps in previous passes, correct errors — but
  never blank out or lose prior context.
- Reference artifacts and records by their NAME, not sys_id. Use sys_ids only
  in structured fields (ai_observations JSON, directly_related_result_ids).
  Human-readable text (observations, recommendations, descriptions) should say
  "Business Rule: Before Insert, order 100 and runs on conditions XXXX, then it will Reset Assignment Group field" Example is for business rule, but see related results artifact record for all details and use web/look up something if youree unsure of what it does in servicenow (a configuration type...) DO not make observations like "sys_id: abc123...".
- When referencing other artifacts in observations, use the pattern:
  "Related to <Name> (<table>)" — e.g. "Related to Set Assigned (sys_script)".


## Advance Pipeline (Required — do this LAST)

When you have finished ALL work for this stage, advance the pipeline by running:

```bash
curl -s -X POST https://136-112-232-229.nip.io/api/assessments/${ASSESSMENT_ID}/advance-pipeline \
  -H "Content-Type: application/json" \
  -d '{"target_stage": "observations", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
