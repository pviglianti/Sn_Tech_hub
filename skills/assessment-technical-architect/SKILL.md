---
name: assessment-technical-architect
description: >
  Best practice review and disposition guidance for ServiceNow artifacts.
  Use during the recommendations phase to evaluate artifacts against best
  practices and suggest keep/refactor/replace/retire dispositions.
metadata:
  domain: servicenow-assessment
  phase: recommendations
---

# Technical Architect — Best Practice Review

You are performing a technical review of ServiceNow artifacts from a technical
assessment. Evaluate each artifact against best practice checks and write
actionable recommendations.

## Review Process

1. **Read the artifact detail** via `get_result_detail` — get the full
   configuration record (script, conditions, settings).

2. **Check against best practices.** Common violations:
   - Hardcoded sys_ids in scripts
   - Direct SQL or GlideRecord in client scripts
   - Missing null checks before GlideRecord operations
   - Business rules without conditions (fire on every operation)
   - Synchronous GlideHTTPRequest calls in business rules
   - Global business rules that should be table-specific
   - Scripts that bypass ACLs with setWorkflow(false)
   - Hardcoded credentials or URLs
   - Deprecated API usage (e.g., GlideAjax patterns)

3. **Write the recommendation** via `update_scan_result` to the
   `recommendation` field. Be specific and actionable:

   - **Clean:** "Follows best practices. Recommend keeping as-is and migrating to scoped app."
   - **Violations:** "Violates BP-003 (hardcoded sys_ids line 45) and BP-012
     (no condition on BR). Refactor: add condition filter, replace sys_ids with
     sys_properties lookups."
   - **OOTB duplicate:** "Replicates OOTB assignment rule functionality.
     Recommend replacing with Assignment Lookup Rules."

## Disposition Guidance

Suggest a disposition direction in your recommendation text:
- **Keep** — clean, follows best practices, serves clear purpose
- **Keep and Refactor** — has violations but logic is sound. Specify what to fix.
- **Replace with OOTB** — duplicates platform functionality
- **Evaluate for Retirement** — may be obsolete or unused

**Important:** Do NOT set the `disposition` field. Write your suggestion in
`recommendation` only. Disposition is confirmed by a human.

## Scope Awareness
- Skip artifacts marked `is_out_of_scope`
- Artifacts marked `is_adjacent` get lighter analysis
- Focus deepest review on in-scope customized artifacts

## Multi-Pass Awareness
If recommendation already has content, this is a refinement pass. Leave
existing content untouched unless you find a missed violation or factual error.
