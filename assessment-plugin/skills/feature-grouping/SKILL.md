---
name: feature-grouping
description: >
  Group assessed artifacts into logical business features. Use after observations.
  Creates feature records and assigns artifacts to them.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_grouping_signals mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_feature_detail mcp__tech-assessment-hub__feature_grouping_status mcp__tech-assessment-hub__create_feature mcp__tech-assessment-hub__update_feature mcp__tech-assessment-hub__add_result_to_feature mcp__tech-assessment-hub__remove_result_from_feature mcp__tech-assessment-hub__sqlite_query mcp__tech-assessment-hub__advance_pipeline
---

# Feature Grouping

**⚠ TOOL LOCK — read first.**
Your only toolbox is `mcp__tech-assessment-hub__*`. Do NOT use `Bash`, `curl`,
`Read`, `Glob`, `Grep`, `Write`, `WebFetch`, or `WebSearch`. If an MCP tool
fails, retry the same MCP tool — do not fall back to shell or curl.

Group in-scope artifacts into business features.

## Setup

1. Get assessment ID from user or `$ARGUMENTS`.
2. **Call `get_assessment_context(assessment_id)`** — caches target app, in-scope tables, file classes.
3. **Call `get_grouping_signals(assessment_id)`** — returns:
   - `dependency_clusters` — **strongest signal**, from the `dependency_mapper` engine (code refs + structural relationships). Trust these first.
   - `naming_clusters` — medium (shared prefixes/conventions).
   - `temporal_clusters` — weakest (same author + tight time window).
4. **Read the resource `assessment://guide/grouping-signals`** for the full signal taxonomy (update sets, sys_metadata parent/child, etc.). Use it when engine signals miss things.
5. `get_customizations(assessment_id, limit=50, offset=…)` to page through triaged artifacts — **in-scope set = rows where `is_out_of_scope == false`** (adjacent rows are in scope on a different table; include them).
6. `feature_grouping_status(assessment_id)` for coverage + unassigned result IDs. To list existing features, run `sqlite_query("SELECT id, name, feature_kind, composition_type FROM feature WHERE assessment_id = :aid", {"aid": <id>})` — then fetch per-feature detail with `get_feature_detail(feature_id)` as needed. There is no bulk `get_features` tool.

## Why you must use the signals tool

The grouping engines are imperfect. `dependency_mapper` is the one reliable engine — its output is in `dependency_clusters`. Others (table colocation, naming, temporal) often miss or over-group. When engine output looks sparse/wrong:

- Still **read** it — you get free leads from `dependency_clusters`.
- Then **fall back to the grouping-signals doc** to apply signals manually: update set cohorts, code cross-references, sys_metadata parent/child, naming conventions, application/package, reference field values.

## Rules

- Artifacts that deliver ONE business capability = one feature.
- Name by business purpose ("Incident Auto-Assignment" not "BR + SI").
- **Use `dependency_clusters` as your starting groups** — then merge/split based on additional signals.
- Apply the confidence scoring from the grouping-signals resource (High 8+, Medium 4-7, Low 1-3).
- Every in-scope artifact (`is_out_of_scope == false`, including `is_adjacent == true`) must end up in a feature — no orphans.
- Assign artifacts to features with `add_result_to_feature(feature_id=…, result_id=…)`. Remove bad assignments with `remove_result_from_feature(feature_id=…, result_id=…)`.
- Standalone or low-confidence artifacts → category bucket ("Misc Form Customizations", "Unclustered Customizations").
- Present your grouping plan to the user before executing (list each proposed feature + member artifact names + confidence).

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

When you have finished ALL work for this stage, call:

```
mcp__tech-assessment-hub__advance_pipeline(
    assessment_id=<id>,
    target_stage="ai_refinement"
)
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step. Do NOT use Bash/curl — it's disabled in this session.
