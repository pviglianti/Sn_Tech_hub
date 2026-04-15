---
name: refinement
description: >
  Refine feature groupings from structural/class-level buckets into functional
  solution-level features. Splits mega-features, merges related ones, and
  renames to describe business capabilities.
allowed-tools: mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_features mcp__tech-assessment-hub__create_feature mcp__tech-assessment-hub__update_feature mcp__tech-assessment-hub__assign_result_to_feature mcp__tech-assessment-hub__remove_result_from_feature
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

1. Call `get_features` to see current features and their artifact counts
2. For each large feature (>20 artifacts), call `get_customizations` filtered
   to that feature to see what's in it
3. Read artifact details with `get_result_detail` to understand what they do
4. Split structural groupings into functional solutions:

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

### Expected output features (examples — discover what actually exists)
- Solution-level: "Pharmacy Incident Solution", "Incident-to-Work-Order Integration"
- Functional: "Incident Auto-Assignment & Routing", "Incident Reopening Logic"
- Cross-cutting: "Incident Security & Access Controls" (only if ACLs are truly standalone)
- Bucket (last resort): "Miscellaneous Incident Form Fields" for truly unrelated standalone items

## Process
1. Analyze the big features first (>20 artifacts)
2. Read a sample of artifacts in each to understand the functional patterns
3. Present your proposed regrouping plan to the user BEFORE executing
4. After user approval, create new features, reassign artifacts, clean up empties
5. **Write feature-level observations** for every feature (see below)

## Feature-Level Observations (Required)

After regrouping, update EVERY feature via `update_feature` with:

- **description** — 2-3 sentences: what business capability this feature delivers,
  how the artifacts work together, who uses it
- **ai_summary** — structured summary: artifact count by type, key patterns,
  dependencies on other features, upgrade risk
- **recommendation** — what should happen to this feature as a whole
  (keep as-is, refactor specific parts, replace with OOTB, evaluate for retirement)
- **change_risk_level** — low/medium/high/critical based on:
  - How many artifacts, how complex the code
  - Whether it touches core platform behavior
  - Whether it has deprecated API usage or security concerns
  - How tightly coupled it is to other features

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
curl -s -X POST http://127.0.0.1:$(cat /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/server.url | sed 's|.*:||' | sed 's|/.*||')/api/assessments/${ASSESSMENT_ID}/advance-pipeline \
  -H "Content-Type: application/json" \
  -d '{"target_stage": "recommendations", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
