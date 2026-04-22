---
name: recommendations
description: >
  Generate best-practice recommendations for assessed artifacts. Reviews code
  quality, checks for violations, and suggests keep/refactor/replace/retire.
  Core philosophy: minimize technical debt, shift toward OOTB ServiceNow, refactor if OOTB won't fit.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__get_best_practices mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_feature_detail mcp__tech-assessment-hub__update_scan_result mcp__tech-assessment-hub__upsert_feature_recommendation mcp__tech-assessment-hub__search_servicenow_docs mcp__tech-assessment-hub__sqlite_query
---

# Recommendations

Review artifacts for best practices and write recommendations.

## Core philosophy (read this first)

**Every customization is technical debt.** Your goal is to minimize it.

Priority order for every recommendation:

1. **Replace with OOTB** — if ServiceNow now offers an equivalent platform feature (dictionary mandatory, UI policy, dependent fields, OOTB notification, flow designer, etc.), the customization should be removed and replaced. Shifting closer to OOTB = less upgrade risk, less maintenance burden.
2. **Refactor** — if the business need is real and no OOTB fit exists, keep the functionality but clean up violations (remove `current.update()` in BRs, eliminate hardcoded sys_ids, add error handling, replace client-side GlideRecord with GlideAjax, etc.).
3. **Keep as-is** — only for customizations that are (a) well-implemented, (b) business-critical, AND (c) have no OOTB equivalent. This should be a minority of recommendations.
4. **Retire** — for dead code, broken references, duplicates, or customizations whose original purpose no longer exists.

**When in doubt, look up what's available now.** ServiceNow adds platform capability every release — something that required custom code in 2019 may be OOTB today. Use `search_servicenow_docs` (or a web search) for the specific in-scope product (Incident, SPM, Catalog, etc.) to check if a newer OOTB alternative exists.

## Setup

1. Get assessment ID from user or `$ARGUMENTS`.
2. **Call `get_assessment_context(assessment_id)`** — gives you target app, in-scope tables, file classes. Keep the target app name handy — you'll use it when searching for OOTB alternatives.
3. Page through `get_customizations(assessment_id, limit=50, offset=…)` to pull the in-scope review queue. **Client-side filter**: process only rows where `is_out_of_scope == false` (in_scope + adjacent both count as in scope). For the feature list, run `sqlite_query("SELECT id, name FROM feature WHERE assessment_id = :aid", {"aid": <id>})` (there is no bulk `get_features` tool); fetch feature-level detail with `get_feature_detail(feature_id)`.

## For each in-scope artifact

1. Read full detail via `get_result_detail(result_id)`.
2. **Call `get_best_practices(applies_to=<artifact's sys_class_name>)`** — returns the catalogued violations that apply to this artifact type (sorted by severity). These are the authoritative rules. Examples of critical ones:
   - `SRV_CURRENT_UPDATE_BEFORE` — `current.update()` in Before BR (causes recursion / double writes)
   - `SRV_CURRENT_UPDATE_AFTER` — `current.update()` in After BR (same problem)
   - `SRV_CURRENT_UPDATE_NO_WORKFLOW` — `current.update()` without `setWorkflow(false)`
   - `SRV_GLIDERECORD_IN_LOOP` — GlideRecord queries inside loops (performance)
   - Hardcoded sys_ids (look for literal 32-char hex strings)
   - Bypassed ACLs (`setWorkflow(false)` + security-sensitive writes)
   - Client-side GlideRecord (should be GlideAjax)
   - Deprecated APIs (check the docs)
3. **Check for OOTB alternatives** — for this target app (from `get_assessment_context`), does ServiceNow now handle this OOTB? Use `search_servicenow_docs` or web search. Typical OOTB replacements:
   - Client script making field mandatory → dictionary or UI policy
   - Client script for dependent values → dictionary dependent values
   - Custom notification → OOTB notification engine
   - Script-driven approvals → Flow Designer approval action
   - Custom assignment logic → Assignment rules / Assignment Data Lookup
4. **Write recommendation** via `update_scan_result`:
   - Start with the disposition direction (keep / refactor / replace / retire) — this is a SUGGESTION, not a system setting.
   - Cite specific violation codes from `get_best_practices` (e.g., "Violates SRV_CURRENT_UPDATE_BEFORE").
   - If an OOTB replacement exists, name it and explain the migration path.
   - If refactoring, give concrete code-level fix guidance — not generic advice.
   - If keeping, justify why it's business-critical AND well-implemented AND has no OOTB fit.

**Never SET the `disposition` field** — only suggest in recommendation text. The user makes the final call.

## Recommendation shape (examples)

**Replace example:**
> Disposition suggestion: **Replace with OOTB**.
> This Client Script makes `short_description` mandatory on `incident`. ServiceNow supports this declaratively via dictionary `mandatory=true` or a UI Policy — both are upgrade-safe and avoid the performance cost of a client script. Migration: set the dictionary field `sys_dictionary.incident.short_description.mandatory = true`, then deactivate this script.

**Refactor example:**
> Disposition suggestion: **Refactor**.
> Business rule "Auto-close stale incidents" — legitimate business need, but violates:
> - `SRV_CURRENT_UPDATE_AFTER` (critical): uses `current.update()` in After BR → will loop.
> - Hardcoded sys_id of assignment group `abc123...` on line 14 → break on clone or group rename.
> Fix: (a) change to Before BR and drop `current.update()`; (b) look up the group via name: `new GlideRecord('sys_user_group').get('name', 'IT Support')`.

**Keep example (rare):**
> Disposition suggestion: **Keep as-is**.
> Script Include `AcmeRevenueCalculator` encodes a proprietary revenue allocation formula unique to Acme — no OOTB equivalent. Well-implemented (initialize, strict-mode, error handling, test coverage), business-critical, called by 14 downstream BRs. No debt to retire here.

**Retire example:**
> Disposition suggestion: **Retire**.
> Business Rule "Legacy MDM sync" — references `u_legacy_mdm_id` field which no longer exists in dictionary. Error thrown on every insert to `incident` for 14 months per syslog. Remove entirely.

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
  -d '{"target_stage": "report", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
