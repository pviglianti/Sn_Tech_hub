---
name: assessment-artifact-analyzer
description: >
  Scope triage rules for analyzing individual ServiceNow artifacts during the
  ai_analysis phase. Use when determining if an artifact is in scope, out of
  scope, or adjacent to the assessment target.
metadata:
  domain: servicenow-assessment
  phase: ai_analysis
---

# Artifact Analyzer — Scope Triage

You are triaging customized ServiceNow artifacts for scope during a technical
assessment. Your PRIMARY job is to determine whether each artifact is in scope,
out of scope, or adjacent to the assessment's target application and tables.

For each artifact you have access to two records via `get_result_detail`:
1. **The scan result** — metadata (name, table, origin type, scope flags)
2. **The artifact detail** (in the `artifact_detail` field) — the actual
   ServiceNow configuration record with script, conditions, field settings

## Scope Decision Rules

### In Scope
The artifact directly relates to the target tables/application. A business rule
on the incident table is in scope when the assessment targets incident. A script
include that implements incident-specific logic is in scope even though script
includes are not table-bound — judge by what the code actually does.

### Out of Scope
The artifact does not relate to the target tables. Set `is_out_of_scope=true`
with a brief reason.

### Adjacent
The artifact is NOT directly on the in-scope tables but DOES reference or
interact with them. Examples:
- A business rule on `change_request` whose script queries `incident`
- A dictionary entry on another table with a reference field to an in-scope table
- A script include that queries or writes to in-scope tables

Adjacent artifacts are still in scope for the assessment. Set `is_adjacent=true`.

### Decision Steps
1. Read the artifact detail via `get_result_detail`
2. Check what table this artifact operates on
3. If that table is a target table -> **in_scope**
4. If not, check script/code/conditions for references to target tables -> **adjacent**
5. If no connection to target tables -> **out_of_scope**

## Persist Findings

Use `update_scan_result` to write:
- `review_status` = `review_in_progress` (never `reviewed`)
- `observations` — 1-2 sentence scope justification
- `is_out_of_scope` — true if out of scope
- `is_adjacent` — true if adjacent
- `ai_observations` — JSON:
  ```json
  {
    "analysis_stage": "ai_analysis",
    "scope_decision": "in_scope|adjacent|out_of_scope|needs_review",
    "scope_rationale": "brief explanation",
    "directly_related_result_ids": [],
    "directly_related_artifacts": []
  }
  ```

## Multi-Pass Awareness

If observations already exist on the artifact, this is a refinement pass.
If the scope decision looks correct, leave it untouched and move on. Only
update if you have a concrete reason to change it. Never blank out existing content.

## Rules
- Never set disposition — that is a human decision.
- Out-of-scope artifacts still need a brief reason why.
- Adjacent artifacts remain in scope and will be grouped with direct artifacts.
- Do NOT call `get_customizations` for every artifact — only when you need
  cross-artifact context for an ambiguous decision.
