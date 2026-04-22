---
name: refinement
description: >
  Refine feature groupings from structural/class-level buckets into functional
  solution-level features. Splits mega-features, merges related ones, and
  renames to describe business capabilities.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_grouping_signals mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_feature_detail mcp__tech-assessment-hub__feature_grouping_status mcp__tech-assessment-hub__create_feature mcp__tech-assessment-hub__update_feature mcp__tech-assessment-hub__add_result_to_feature mcp__tech-assessment-hub__remove_result_from_feature mcp__tech-assessment-hub__sqlite_query
---

# Feature Refinement — Solution-Level Grouping

The initial grouping organized artifacts by type (all BRs together, all ACLs
together, all dictionary entries together). That is WRONG. Artifacts should be
grouped by the **business solution they deliver together**.

## What a feature should look like

A feature is a business capability. It typically spans MULTIPLE artifact types:
- A "Pharmacy Incident Solution" feature would include BRs, UI policies,
  dictionary entries, client scripts, ACLs — everything that makes the
  pharmacy incident workflow work.
- An "Incident Auto-Assignment" feature would include the assignment BR,
  the script include it calls, the dictionary entries for assignment fields,
  and the ACLs that control who can change assignment.

## Your job

1. **Call `get_assessment_context(assessment_id)`** — caches target app, in-scope tables, parent table, file classes. Use the target app's name when proposing feature names (e.g., for SPM use "Project", "Demand", "Story Workflow" prefixes — not Incident terminology).
2. **Call `get_grouping_signals(assessment_id)`** — returns `dependency_clusters` (the strongest signal: two artifacts belong together because they reference each other in code OR have a sys_metadata structural relationship — e.g., a UI Policy and its UI Policy Actions, a Dictionary entry and its Dictionary Override, a Workflow and its Activities, a Catalog Item and its Variables). Use these as **feature-grouping hints** — when dependency_clusters connect artifacts across two existing features, that's a strong signal those features should merge. Also returns `naming_clusters` (shared prefixes) and `temporal_clusters` (same-author/time) as weaker signals.
3. List existing features: `sqlite_query("SELECT id, name, feature_kind, composition_type FROM feature WHERE assessment_id = :aid", {"aid": <id>})`. For counts per feature, join via the membership table: `sqlite_query("SELECT f.id, f.name, COUNT(fm.result_id) AS n FROM feature f LEFT JOIN feature_scan_result fm ON fm.feature_id = f.id WHERE f.assessment_id = :aid GROUP BY f.id ORDER BY n DESC", {"aid": <id>})`. (There is no bulk `get_features` MCP tool.)
4. For each large feature (>20 artifacts), call `get_feature_detail(feature_id)` to see full metadata + member artifact IDs, then `get_result_detail(result_id)` per member.
5. Read artifact details with `get_result_detail` to understand what they do.
6. Split structural groupings into functional solutions:

### How to split

Look at the artifacts in a feature. Ask: "Do these all serve the SAME business
purpose?" If not, they belong in different features.

**Signals that artifacts belong together:**
- They reference each other in code (script include called by a BR)
- They operate on the same functional area (all deal with assignment)
- They were created together (same update set)
- They share naming patterns (PCG_*, Pharmacy*, AutoAssign*)
- Removing one would break the others

**Signals they should be separate features:**
- They serve different business processes even though they're the same type
- A dictionary entry for "u_pharmacy_type" belongs with pharmacy, not with
  "Incident Field Schema"
- An ACL for assignment fields belongs with assignment logic, not with
  "Incident Security ACLs"

### Naming

Name features by what they DO, not what they ARE:
- BAD: "Incident Business Rules", "Incident Field Schema", "Incident ACLs"
- GOOD: "Pharmacy Incident Solution", "Incident Auto-Assignment & Routing",
  "Incident Priority & SLA Automation", "Incident Form Field Defaults"

### Expected output features (examples — discover what actually exists for the current target app)

These are illustrative. Use the target app name from `get_assessment_context` to drive your naming.

- **Incident assessment:** "Pharmacy Incident Solution", "Incident Auto-Assignment & Routing", "Incident Reopening Logic", "Miscellaneous Incident Form Fields" (bucket)
- **SPM assessment:** "Demand Intake Workflow", "Project Status Reporting", "Story → Feature Promotion Logic", "Resource Allocation Customizations"
- **CMDB assessment:** "CI Reconciliation Rules", "Discovery Pattern Customizations", "CI Relationship Auto-Generation"
- **Cross-cutting (any app):** Security/ACL clusters only if truly standalone; otherwise fold into the functional feature they support.
- **Bucket (last resort):** "Miscellaneous <App> Form Fields" / "Unclustered <App> Customizations" for unrelated standalone items.

## Process
1. Analyze the big features first (>20 artifacts)
2. Read a sample of artifacts in each to understand the functional patterns
3. Present your proposed regrouping plan to the user BEFORE executing
4. After user approval, create new features, reassign artifacts, clean up empties
5. **Write feature-level observations** for every feature (see below)

## Feature-Level Observations (Required)

After regrouping, call `update_feature(feature_id=…, …)` for every feature and set:

- **description** — 2-3 sentences: what business capability this feature delivers,
  how the artifacts work together, who uses it
- **ai_summary** — free-form text: artifact count by type, key patterns,
  dependencies on other features, upgrade risk, and an explicit **change-risk
  assessment** (low / medium / high / critical and why, factoring artifact count
  + complexity, core-platform touchpoints, deprecated APIs, security concerns,
  cross-feature coupling). The structured `change_risk_level` column is set by
  the grouping engine, not by this tool — bake your risk assessment into
  `ai_summary` + `recommendation` instead of trying to write it directly.
- **recommendation** — what should happen to this feature as a whole
  (keep as-is, refactor specific parts, replace with OOTB, evaluate for retirement)

This is the main deliverable of refinement — each feature should tell a complete
story so a human reviewer can understand what it is and what to do about it
without reading individual artifacts.

## Rules
- Every in-scope artifact must stay assigned — no orphans
- Delete empty features after reassignment
- Keep the user informed of progress
- Do NOT skip feature-level observations — they are required output

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
  -d '{"target_stage": "recommendations", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
