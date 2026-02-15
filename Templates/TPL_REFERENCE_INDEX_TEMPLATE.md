# 00_admin/reference_index.md (Template)

## Purpose
This file is the inventory + triage map for everything in 01_source_data/.
It must be completed before any deep analysis.

## Operating rules (non-negotiable)
- Inventory first. No synthesis until this is complete.
- If a required input is missing, record it in insights.md (Missing inputs) before proceeding.
- Prefer authoritative sources first (official/vendor docs), then platform exports, then community sources.

## Inventory table (required)
Fill one row per file found under 01_source_data/.

| path | type | 1-line summary | priority | intended use | notes / caveats |
|---|---|---|---|---|---|
|  | brief |  | high | scope + requirements |  |
|  | reference_doc |  | high | authoritative guidance |  |
|  | export_raw |  | high | instance facts / evidence |  |
|  | code_snippet |  | med | implementation evidence |  |
|  | unknown |  | low | triage |  |

### Allowed values
- type: brief | reference_doc | export_raw | code_snippet | unknown
- priority: high | med | low
- intended use: authoritative guidance | data input | instance evidence | background | triage

## Authoritative-first rule (conflict resolution)
When there is conflict, use this order:
1) Official docs / vendor documentation
2) Platform data exports (what the instance actually does)
3) Community posts / blogs (only if consistent with 1 and 2)

If conflict remains unresolved:
- write an open question in insights.md with a resolution plan and candidate sources to check.

## Triage rule for 01_source_data/99_inbox_drop/
For each item in inbox_drop:
- classify it into one of the standard source folders, or leave it in inbox_drop with type=unknown
- add a note about what would make it usable

## Completion gate (required)
Before analysis begins, reference_index.md must include:
- every file under 01_source_data/
- priority set for each
- intended use set for each
- at least one missing-input note in insights.md if anything is absent