---
name: scope-triage
description: >
  Classify every customized artifact in a ServiceNow technical assessment as
  in_scope (direct customization of the assessed app/tables), adjacent (related
  but not direct — still counts as in scope), or out_of_scope (unrelated).
  Invoke as /scope-triage <assessment_id> with optional extra context.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__query_instance_live
---

# Scope Triage

You have MCP access to the Tech Assessment Hub. Your job is to classify **every**
customized artifact in one assessment as **in_scope**, **adjacent**, or
**out_of_scope**, and persist that decision.

## Inputs

`$ARGUMENTS` contains the assessment_id plus optional operator context, e.g.:
- `1` → assessment_id=1, no extra notes.
- `1 focus only on Incident; treat any task-level BRs as adjacent` →
  assessment_id=1, the rest is additional operator guidance you MUST factor in.

Parse the first whitespace-delimited token as the integer assessment_id. Any
remaining text is operator context and overrides defaults when they conflict.

If `$ARGUMENTS` is empty, ask the operator once for the assessment_id, then
proceed automatically.

## Setup (run once)

1. `get_assessment_context(assessment_id)` — **cache this**. Key fields:
   - `target_app.name` / `target_app.label` — the app being assessed
   - `in_scope_tables` — authoritative in-scope table list
   - `parent_table` — typically treated as adjacent (e.g. `task`, `planned_task`)
   - `keywords` — string hints for tableless artifacts
   - `scope_filter` — `global` | `scoped` | `all`
2. Apply operator context from `$ARGUMENTS` on top of the cached defaults.

## Processing loop — process EVERY artifact

**You MUST walk the full customization queue and call `update_scan_result`
exactly once per artifact. Do not stop early. Do not ask the operator for
confirmation mid-loop — the rule below is sufficient.**

Pseudocode:

```
offset = 0
totals = {in_scope: 0, adjacent: 0, out_of_scope: 0}
while True:
    page = get_customizations(assessment_id=<id>, limit=50, offset=offset)
    for cust in page.customizations:
        detail = get_result_detail(result_id=cust.scan_result_id)
        decision = classify(detail, cust)   # see Decision tree
        update_scan_result(
            result_id=cust.scan_result_id,
            observations="<one concise sentence — what it does + which in-scope / "
                         "adjacent records or tables it touches, calls, or is called by>",
            ai_observations={
                "analysis_stage": "ai_analysis",
                "scope_decision": decision,           # "in_scope" | "adjacent" | "out_of_scope"
                "scope_rationale": "<1 sentence why>",
            },
            is_out_of_scope=(decision == "out_of_scope"),
            is_adjacent=(decision == "adjacent"),
        )
        totals[decision] += 1
    # progress ping every page
    emit "Processed {offset + len(page.customizations)} / {page.total} — "
         "{totals.in_scope} in_scope, {totals.adjacent} adjacent, "
         "{totals.out_of_scope} out_of_scope"
    if len(page.customizations) < 50: break
    offset += 50
```

**Hard rules:**
- **Never set `review_status`.** That is a human (or later-stage) field; leave it
  as `pending_review`.
- **Always call `update_scan_result` for every artifact**, and always pass both
  `is_out_of_scope` and `is_adjacent` explicitly so in_scope artifacts end up
  `is_out_of_scope=false, is_adjacent=false`.
- **Exactly one of** `is_out_of_scope` / `is_adjacent` may be true; never both.
- Use `get_customizations` with `assessment_id`, `limit`, and `offset` only —
  the tool does not accept a review_status filter; the customization table IS
  the filter (everything in it is already customized).
- Report a one-line progress summary after each page.

## Decision tree

For each artifact, let `T` = its target table (usually `detail.collection` or
`detail.table_name`). Using the cached context:

1. `T` is in `in_scope_tables` → **in_scope**
2. No table (script include, UI page, fix script, etc.) → inspect the code:
   - references an `in_scope_tables` value, its fields, or matches `keywords`,
     or interacts with in-scope configurations → **in_scope**
   - otherwise → **out_of_scope**
3. `T` exists but NOT in `in_scope_tables`:
   - `T == parent_table` → **adjacent**
   - `T` references/queries/extends an in-scope table → **adjacent**
   - otherwise → **out_of_scope**

`in_scope` and `adjacent` both count as IN SCOPE. `adjacent` just means "in
scope but not on a target table."

## Observation quality

- ONE concise sentence per artifact. Describe what the artifact does and which
  in-scope or adjacent records/tables it references, updates, calls, or is
  called by.
- Reference other artifacts by **name + type**, not sys_id, e.g.
  "Business Rule: Before Insert on incident — sets Assignment Group from
  category; related to Script Include 'IncidentUtils'".
- Use sys_ids only inside structured JSON fields
  (`ai_observations`, `directly_related_result_ids`), never in human-readable
  text.
- If you're uncertain what a ServiceNow configuration type does, say so
  briefly — do not fabricate.

## Worked examples

**Incident assessment** (`in_scope_tables = ["incident","incident_task"]`,
`parent_table = "task"`)

| Artifact | Table | Decision |
|---|---|---|
| Business Rule "Close Incident" | incident | **in_scope** |
| Script Include "IncidentUtils" (refs `GlideRecord('incident')`) | null | **in_scope** |
| Script Include "UtilityMath" (no incident refs) | null | **out_of_scope** |
| UI Action "Assign to me" on task | task | **adjacent** |
| Business Rule on change_request | change_request | **out_of_scope** |

**SPM assessment** (`in_scope_tables` includes `pm_project`, `pm_project_task`,
`rm_story`, `rm_epic`, …; `parent_table = "planned_task"`)

| Artifact | Table | Decision |
|---|---|---|
| UI Policy on rm_story | rm_story | **in_scope** |
| Business Rule on planned_task | planned_task | **adjacent** |
| Client Script on task | task | **out_of_scope** (task is too generic) |

## Iterative refinement

If an artifact already has observations/ai_observations from an earlier pass,
**refine** — read what's there, tighten it, correct errors, add new context
from this pass. Do not blank out prior text. Structured fields may be
replaced when your new decision is more confident than the prior one.

## Advance pipeline (required — do this LAST)

When the loop has processed every customization, advance the pipeline:

```bash
curl -s -X POST https://136-112-232-229.nip.io/api/assessments/${ASSESSMENT_ID}/advance-pipeline \
  -H "Content-Type: application/json" \
  -d '{"target_stage": "observations", "force": true}'
```

Do not skip this step.
