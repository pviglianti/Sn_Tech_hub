---
name: scope-triage
description: >
  Classify every customized artifact in a ServiceNow technical assessment as
  in_scope (direct customization of the assessed app/tables), adjacent (related
  but not direct — still counts as in scope), or out_of_scope (unrelated).
  Invoke as /scope-triage <assessment_id> with optional extra context.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_scope_brief mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__query_instance_live mcp__tech-assessment-hub__advance_pipeline
---

# Scope Triage

**⚠ TOOL LOCK — read first.**
You have exactly ONE toolbox: `mcp__tech-assessment-hub__*`. Do NOT use
`Bash`, `curl`, `Read`, `Glob`, `Grep`, `Write`, `WebFetch`, or `WebSearch`
under any circumstance. They are either unavailable or wrong for this task —
the assessment data lives on the hub, not on the filesystem. If a
`mcp__tech-assessment-hub__*` tool fails, **retry that same tool** (don't
fall back to curl; we'll see the MCP error in the audit log and fix it).

Your job is to classify **every** customized artifact in one assessment as
**in_scope**, **adjacent**, or **out_of_scope**, and persist that decision via
`mcp__tech-assessment-hub__update_scan_result`.

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

## Processing loop — one page per session

**Scope of this session:** process up to 50 artifacts (one page of
`get_customizations`), then stop and exit cleanly. Do NOT fetch further
pages. The dispatcher re-invokes this skill for the next batch. Keeping each
CLI session to 50 artifacts caps context growth, avoids Anthropic subscription
rate-limit backoffs, and lets each `update_scan_result` become visible in
the UI as it's written.

**⚠ SERIAL TOOL CALLS — one tool per turn.**
Do NOT emit multiple `tool_use` blocks in the same assistant message. Each
turn must contain exactly ONE tool call. The loop is:

    (optional 1 tool_use: get_result_detail) →
    (1 tool_use: update_scan_result) →
    (next artifact) → …

Parallel tool batches cause the CLI to assemble a giant user message the
API struggles to accept, and one slow/failed call blocks the rest.

**⚠ USE `meta_target_table`, NOT `table_name`, FOR THE FAST-PATH DECISION.**
`get_customizations` returns two table-ish fields per row:

- `table_name` — the **metadata container** (`sys_script`, `sys_script_include`,
  `sys_dictionary`, `sys_ui_policy`, …). Almost never the real subject.
- `meta_target_table` — the **business target** (`incident`, `change_request`,
  `task`, …). THIS is what matters for scope.

Apply this narrow shortcut:

| `cust.meta_target_table` case                         | Action                                  |
|---|---|
| value is in `in_scope_tables` (non-null match)        | **in_scope** — skip detail              |
| anything else (parent table, other table, null, etc.) | **get_result_detail** then classify     |

**Why only a direct target-table match is safe to skip:**
A Business Rule whose `meta_target_table = change_request` can still call
`new GlideRecord('incident')` and push updates there — **adjacent** (in
scope), even though the hosting table is out of scope. Same story for
script includes / fix scripts / UI pages / flows that have no
`meta_target_table` but touch in-scope behavior in their code body. And
`parent_table` is not auto-adjacent — a customization on `task` could be
pure task behavior with no incident touchpoint, i.e. out_of_scope. So for
anything that isn't a direct target-table match, fetch the detail and
inspect the code/fields.

Skipping `get_result_detail` for direct-target-table hits is a big win:
most customizations in a focused assessment ARE on the target tables, so
this shortcut keeps the fast path fast without sacrificing accuracy on
the cross-table adjacency cases that actually need judgment.

**⚠ SKIP ARTIFACTS ALREADY TRIAGED.**
`get_customizations` also returns each row's `ai_observations`. If that
field is non-null and contains `"scope_decision"`, a prior chunk already
triaged this artifact — skip it (do not call `get_result_detail` or
`update_scan_result` for it). This is what lets the auto-chain dispatcher
run multiple chunks without duplicating work.

Pseudocode:

```
page = get_customizations(assessment_id=<id>, limit=50, offset=<from_operator_context_or_0>)
totals = {in_scope: 0, adjacent: 0, out_of_scope: 0, skipped_detail: 0}

for cust in page.customizations:
    # Dedupe: was this already triaged in a prior chunk?
    if cust.ai_observations and '"scope_decision"' in cust.ai_observations:
        continue

    target = cust.meta_target_table  # NOT cust.table_name

    if target and target in in_scope_tables:
        # Fast path: artifact targets an in-scope table → in_scope.
        # No detail fetch; the target table alone is sufficient evidence.
        decision = "in_scope"
        rationale = f"meta_target_table {target} is a target table"
        totals["skipped_detail"] += 1
    else:
        # Anything else — null target, parent table, or some other table —
        # MAY still be adjacent because the code references in-scope
        # tables. Inspect the lightweight scope brief first.
        brief = get_result_scope_brief(result_id=cust.scan_result_id)
        decision, rationale = classify_from_brief(brief, cust)
        # Only escalate to get_result_detail if the brief's script_excerpts
        # were truncated AND the truncated tail might change the decision.
        # In practice, a 2KB excerpt already reveals any in-scope
        # GlideRecord call or target-table reference near the top of the
        # file, so full detail is rarely needed.

    update_scan_result(
        result_id=cust.scan_result_id,
        observations="<one concise sentence — what it does + which in-scope / "
                     "adjacent records or tables it touches, calls, or is called by>",
        ai_observations={
            "analysis_stage": "ai_analysis",
            "scope_decision": decision,
            "scope_rationale": rationale,
        },
        is_out_of_scope=(decision == "out_of_scope"),
        is_adjacent=(decision == "adjacent"),
    )
    totals[decision] += 1

# ONE progress line, then stop.
emit f"Processed {len(page.customizations)} of this page — "
     f"{totals['in_scope']} in_scope, {totals['adjacent']} adjacent, "
     f"{totals['out_of_scope']} out_of_scope, "
     f"{totals['skipped_detail']} used table-only decision."

# Advance only when the whole queue is done.
if page.total <= page.offset + len(page.customizations):
    advance_pipeline(assessment_id=<id>, target_stage="observations")

# Exit. Do NOT request the next page here.
```

**Hard rules:**
- **Never set `review_status`.** That is a human (or later-stage) field; leave it
  as `pending_review`.
- **Always call `update_scan_result` for every artifact**, and always pass both
  `is_out_of_scope` and `is_adjacent` explicitly so in_scope artifacts end up
  `is_out_of_scope=false, is_adjacent=false`.
- **The three decisions are mutually exclusive — AT MOST one flag is true:**

  | decision      | `is_out_of_scope` | `is_adjacent` |
  |---|---|---|
  | `in_scope`    | false             | false         |
  | `adjacent`    | false             | **true**      |
  | `out_of_scope`| **true**          | false         |

  If you've decided an artifact is `out_of_scope`, **do NOT also evaluate
  for adjacency** — out_of_scope means it does not relate to the assessment
  at all. `is_adjacent` on an out_of_scope record must be `false`, always.
  Never pass `is_out_of_scope=true` with `is_adjacent=true` in the same
  call; the record-merge rejects that as a contradiction.
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

**If the table-level check doesn't give you a clear answer** — `table_name`
is null, the table is generic (e.g. `task`, `sys_metadata`), or the artifact
type doesn't really have a target table — pull the full record with
`get_result_detail(result_id)` and check **all relevant data points** on it
before deciding. Which fields matter depends on the artifact class (different
app-file types have different fields): Business Rules have `collection` +
`script` + `condition` + `when`; Dictionary entries have `name` + `element` +
`default_value`; UI Policies / Client Scripts have `table` + `conditions`;
Script Includes have `script`; UI Pages have `html` + `client_script` +
`processing_script`; Flows/Workflows have `activities_json` + `table`; etc.
Read whatever fields are populated on this record, and also fall back to
`raw_data_json` for unfamiliar classes. A `GlideRecord('incident')` inside a
Script Include's `script` field is enough to make it in_scope even though
`table_name` is null.

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

When the loop has processed every customization, advance the pipeline by
calling the MCP tool:

```
mcp__tech-assessment-hub__advance_pipeline(
    assessment_id=<id>,
    target_stage="observations"
)
```

Do not skip this step. Do not use Bash/curl — it's disabled in this session.
