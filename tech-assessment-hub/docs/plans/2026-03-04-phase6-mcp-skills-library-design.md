# Phase 6 — MCP Skills/Prompts Library + Best Practice Knowledge Base

**Date:** 2026-03-04
**Status:** Approved
**Approach:** Layered System (Approach C) — foundation prompt + 3 specialized prompts + admin-editable best practice catalog

---

## Overview

Phase 5 delivered the pipeline UI, deterministic observations, and human review gates. Phase 6 adds the AI intelligence layer: a library of MCP prompts that guide Claude through deep artifact analysis, dependency tracing, technical best-practice evaluation, and final report generation — all powered by dynamic context injection from the database and an admin-editable best practice catalog.

### Delivery Model: MCP Prompts + Dynamic Context

Each prompt is registered as an MCP `PromptSpec`. The handler function accepts parameters (e.g., `result_id`, `assessment_id`), queries the database, and injects relevant data (code body, signals, relationships, usage data) directly into the prompt text before returning it to the MCP client. No embedded LLM calls — the MCP client's model does the reasoning.

### Architecture

```
Layer 1 (Foundation):
  artifact_analyzer — per-artifact deep dive with type-specific dispatch

Layer 2 (Specialized):
  relationship_tracer — cross-artifact dependency graph tracing
  technical_architect — code quality + systemic technical debt (driven by BestPractice catalog)
  report_writer — assessment deliverable generation

Data Layer:
  BestPractice model — admin-editable catalog of ~40+ checks across 8 categories
```

### Execution Order in an Assessment

1. `generate_observations` tool (deterministic baseline — Phase 5)
2. `observation_landscape_reviewer` + `observation_artifact_reviewer` (AI enrichment — Phase 5)
3. Human review gate
4. `artifact_analyzer` on key artifacts (deep dives)
5. `relationship_tracer` on complex clusters (dependency mapping)
6. Grouping (`seed_feature_groups`)
7. `technical_architect` Mode A on flagged artifacts + Mode B assessment-wide
8. Recommendations (`run_feature_reasoning`)
9. `report_writer` (final deliverable)

---

## Component 1: `BestPractice` Model + Admin UI

### Model

| Field | Type | Description |
|-------|------|-------------|
| `id` | int PK | Auto ID |
| `code` | str unique | Short code, e.g. `SRV_CURRENT_UPDATE`, `CLI_DOM_MANIP` |
| `title` | str | Human-readable name |
| `category` | enum | `technical_server`, `technical_client`, `architecture`, `process`, `security`, `performance`, `upgradeability`, `catalog`, `integration` |
| `severity` | enum | `critical`, `high`, `medium`, `low`, `info` |
| `description` | text | Full explanation of the best practice |
| `detection_hint` | text | What to look for — regex patterns, field names, code signatures |
| `recommendation` | text | What to do instead |
| `applies_to` | str (nullable) | Comma-separated `sys_class_name` values, or null = all |
| `is_active` | bool | Toggle on/off |
| `source_url` | str (nullable) | Link to SN docs / community article |
| `created_at` | datetime | |
| `updated_at` | datetime | |

### Categories

| Category | Scope |
|----------|-------|
| `technical_server` | Server-side scripting: current.update(), GlideRecord in loops, error handling, async BRs |
| `technical_client` | Client-side scripting: DOM manipulation, sync GlideAjax, client GlideRecord, UI Policy work |
| `architecture` | Platform design: table extensions, scoped apps, DL framework, modularity, legacy workflows |
| `process` | Development process: update sets, naming conventions, code comments, sys_id hardcoding |
| `security` | ACLs, access control, credentials in code |
| `performance` | Query efficiency, indexing, async processing, Before Query BRs |
| `upgradeability` | OOTB modifications, skipped record risk, scoped app isolation |
| `catalog` | Service Catalog: variable sets, UI policies, list collector usage |
| `integration` | External connections: hard-coded endpoints, retry logic, credentials |

### Seed Data (~41 checks)

#### Technical — Server Side

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `SRV_CURRENT_UPDATE_BEFORE` | current.update() in Before Business Rules | Critical | `current.update()` in sys_script where when=before. Never needed — SN auto-saves current after Before BR. |
| `SRV_CURRENT_UPDATE_AFTER` | current.update() in After Business Rules | Critical | `current.update()` in sys_script where when=after. Causes double-update + recursive execution risk. |
| `SRV_CURRENT_UPDATE_NO_WORKFLOW` | current.update() without setWorkflow(false) | Critical | `current.update()` without nearby `setWorkflow(false)` — recursive BR chain risk. |
| `SRV_GLIDERECORD_IN_LOOP` | GlideRecord queries inside loops | High | `GlideRecord` + `while`/`for` nesting. Use GlideAggregate or IN operator instead. |
| `SRV_NO_TRY_CATCH` | No error handling in server scripts | Medium | Server script body with no `try`/`catch` block. |
| `SRV_AFTER_NOT_ASYNC` | After BR where Async BR would suffice | Medium | After BR with no user-facing side effects — should be Async for performance. |
| `SRV_GLOBAL_BR_NO_TABLE` | Global Business Rule without table filter | Medium | sys_script with empty table field — fires on every table operation. |
| `SRV_SCRIPT_INCLUDE_NO_INIT` | Script Include missing initialize() | Low | sys_script_include class without `initialize` method. |
| `SRV_CLIENT_CALLABLE_MISUSE` | Script Include client-callable flag misuse | Medium | client_callable=true but no AbstractAjaxProcessor extension. |
| `SRV_DEPRECATED_API` | Deprecated API usage | Medium | `current.variables` in wrong context, legacy method calls. |

#### Technical — Client Side

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `CLI_DOM_MANIPULATION` | DOM manipulation (unsupported) | High | `$('`, `document.get`, `jQuery(` in client scripts. Not supported — may break on upgrades. Sometimes needed but should be flagged. |
| `CLI_SYNC_GLIDEAJAX` | Synchronous GlideAjax calls | High | `getXMLWait()` in client scripts — blocks browser thread. |
| `CLI_GLIDERECORD_CLIENT` | GlideRecord used client-side | Medium | `GlideRecord` in sys_script_client — should use GlideAjax per SN docs. |
| `CLI_DOING_UI_POLICY_WORK` | Client script setting mandatory/visible/readonly | High | `g_form.setMandatory`, `g_form.setVisible`, `g_form.setReadOnly` in client script — should be UI Policy + UI Policy Actions. |
| `CLI_GSCRATCHPAD_MISUSE` | g_scratchpad misuse | Medium | Excessive or incorrect g_scratchpad patterns. |

#### Architecture

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `ARCH_EXTEND_CORE_TABLE` | Extending core task-child tables | Critical | Custom table extending incident, change_request, problem. Task is fine — but not its children. Fractures AI training data, complicates routing/SLAs/reporting. |
| `ARCH_CUSTOM_FIELD_OOTB_EXISTS` | Custom field where OOTB field exists | High | `u_` field on table where similar standard field is unused. |
| `ARCH_LOOKUP_NOT_DL` | Lookup table not using Data Lookup framework | High | Custom table for lookups not extending dl_matcher. Unlimited tables — any lookup should be DL table. |
| `ARCH_NOT_MODULAR` | Business logic not modular/reusable | Medium | Logic in BR that should be extracted to reusable Script Include. |
| `ARCH_GLOBAL_NOT_SCOPED` | Custom code in global scope | Medium | Custom artifacts without scoped application packaging. |
| `ARCH_LEGACY_WORKFLOW` | Legacy Workflow instead of Flow Designer | Medium | Active legacy workflow — SN deprecating end of 2025. |
| `ARCH_CATALOG_CLIENT_NOT_UI_POLICY` | Catalog Client Script instead of Catalog UI Policy | Medium | Catalog client script doing field visibility/mandatory. |
| `ARCH_NO_VARIABLE_SETS` | Catalog variables not using Variable Sets | Low | Repeated variables across catalog items instead of shared sets. |
| `ARCH_LIST_COLLECTOR_OVERUSE` | List Collector variable overuse | Medium | Slush bucket variables — not supported by g_form API. |

#### Process

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `PROC_DEFAULT_UPDATE_SET` | Artifacts in Default update set | High | Update set = "Default" — changes made directly in environment. |
| `PROC_NO_US_NAMING` | No update set naming convention | Medium | Update set names lack common prefix, project code, or story number. |
| `PROC_OVERSIZED_US` | Update set too large (>100 entries) | Medium | Update set XML count > 100. Recommended max 500-1000 XML; >100 artifacts signals poor batching. |
| `PROC_NO_US_BATCHING` | Related update sets not batched | Medium | Related update sets without parent/child grouping. |
| `PROC_NO_CODE_COMMENTS` | No comments in code | Medium | Code body with 0 comment lines — header block + inline expected. |
| `PROC_HARDCODED_SYSID` | Hard-coded sys_ids in scripts | High | 32-character hex strings in code body. Use System Properties or Script Include constants. |
| `PROC_NO_SYSTEM_PROPERTIES` | Config values not in System Properties | High | Hard-coded config values that should use `gs.getProperty()`. |

#### Security

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `SEC_ACL_SCRIPT_NO_ROLE` | Scripted ACL without role shielding | High | ACL with script condition but no role requirement — script runs on every evaluation. Shield with roles first. |
| `SEC_NO_ACL_CUSTOM_TABLE` | Custom table missing ACLs | High | Custom table with no ACL records. |
| `SEC_OVERLY_PERMISSIVE_ACL` | Overly permissive ACL | Medium | ACL granting access to broad roles without conditions. |
| `SEC_CREDENTIALS_IN_CODE` | Credentials or secrets in scripts | Critical | Passwords, API keys, tokens in code body. |

#### Performance

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `PERF_UNINDEXED_QUERY` | Queries on unindexed fields | High | GlideRecord queries on large tables without indexed where clause. |
| `PERF_HEAVY_BEFORE_QUERY_BR` | Heavy Before Query Business Rule | High | Complex scripting in Before Query BR — runs on every query to the table. |
| `PERF_SYNC_WHERE_ASYNC` | Synchronous processing where async works | Medium | Blocking operations that could use event queue or async BR. |
| `PERF_NOTIFICATION_OVERUSE` | Excessive record-based notifications | Low | Many condition-based notifications that could be event-driven for better troubleshooting. |

#### Upgradeability

| Code | Title | Severity | Detection Hint |
|------|-------|----------|----------------|
| `UPG_MODIFIED_OOTB_SCRIPT` | Direct modification of OOTB scripts | High | modified_ootb origin on scripted artifacts — creates skipped records on upgrade. Extend or override instead. |
| `UPG_HIGH_SKIPPED_RISK` | High skipped record risk | Medium | Many modified OOTB artifacts — will create upgrade conflicts. Use scoped apps to isolate. |

### Admin UI

- List view at `/admin/best-practices` — filterable by category, severity, active status
- Inline editing of all fields
- JSON seed file for import/export
- Future: related list on Assessment showing which best practices were flagged (via findings model)

---

## Component 2: `artifact_analyzer` Prompt

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `result_id` | Yes | ScanResult to analyze |
| `assessment_id` | Yes | Assessment scope |

### Dynamic Context Injection

The handler queries DB and pre-loads into prompt text:

1. **Result metadata** — name, table (`sys_class_name`), origin, target table, active flag, description, update set names
2. **Code body** — `code_body` or `meta_code_body` (first 150 lines; note if truncated)
3. **Engine signals** — `GroupingSignal` rows referencing this result (naming, update set, structural engines)
4. **Structural relationships** — `StructuralRelationship` rows (parent/child) with related result names/tables
5. **Usage data** — from `ai_observations` JSON if available (count within lookback window)
6. **Existing observations** — current `observations` text from Phase 5 pipeline

### Per-Type Analysis Dispatch

The prompt includes type-specific analysis strategies:

| `sys_class_name` | Focus Areas |
|-------------------|-------------|
| `sys_script` (Business Rules) | When does it run (before/after/async/display)? What table? What conditions? Does it modify current or related records? |
| `sys_script_include` (Script Includes) | Is it a utility class or API? Client-callable? Does it extend AbstractAjaxProcessor? What methods does it expose? |
| `sys_ui_script` / `sys_script_client` | Which form/table? onChange/onLoad/onSubmit? What fields does it touch? Does it make server calls? |
| `sys_ui_action` (UI Actions) | Client/server/both? What does the button/link do? Global or form-context? |
| `sys_security_acl` (ACLs) | What operation (read/write/create/delete)? Role requirements? Scripted conditions? |
| `sys_dictionary` / `sys_db_object` | Custom field or custom table? What type? Default value? Referenced table? |
| `sys_ui_policy` / `sys_ui_form_section` | What conditions trigger it? What actions (mandatory/visible/readonly)? |

### Output Structure

```
Artifact: [name] ([table])
Type Analysis: [1-2 sentences — what it does based on code/metadata]
Dependencies: [related artifacts via signals/relationships]
Complexity: [Simple / Moderate / Complex]
Key Observations: [2-4 bullet points]
```

---

## Component 3: `relationship_tracer` Prompt

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `result_id` | Yes | Starting ScanResult to trace from |
| `assessment_id` | Yes | Assessment scope |
| `max_depth` | No | How many hops to trace (default: 3) |
| `direction` | No | `"outward"` (default), `"inward"`, or `"both"` |

### Dynamic Context Injection

1. **Starting artifact** — name, table, origin, observations, code snippet (first 100 lines)
2. **Direct structural relationships** — all StructuralRelationship rows (parent + child), with related result name/table/origin
3. **Update set siblings** — other ScanResults sharing same update set(s) via UpdateSetArtifactLink, grouped by update set name
4. **Table-level neighbors** — other customized ScanResults on same `table_name` or `meta_target_table`
5. **Engine signals** — GroupingSignal rows referencing this result
6. **Existing feature context** — if FeatureGroupMember exists, include feature name + other members (prompt works without this)

### Analysis Strategy

1. **Map the dependency graph** — follow each relationship type outward. For each connected artifact: what it is, how it connects, same-feature vs same-area.
2. **Identify feature boundaries** — update set boundaries, table boundaries, naming pattern breaks.
3. **Surface hidden dependencies** — BR calling Script Include, Client Script referencing UI Policy, ACL protecting custom field.
4. **Output a relationship map:**
   - Core cluster (definitely same feature)
   - Adjacent artifacts (probably related, worth grouping)
   - Distant connections (shared table, likely different features)
   - Recommended grouping narrative (1-2 sentences)

---

## Component 4: `technical_architect` Prompt

Two modes in one prompt — per-artifact (Mode A) and assessment-wide (Mode B).

### Mode A: Per-Artifact Technical Review

**Parameters:** `result_id` (required), `assessment_id` (required)

**Dynamic Context:** Full code body (up to 200 lines), artifact metadata, existing observations, update set context, usage data, plus all active `BestPractice` records filtered by `applies_to` matching this artifact's `sys_class_name`.

**Analysis Framework:**

The prompt receives the BestPractice catalog entries as a structured checklist and evaluates the artifact against each applicable check. Categories covered:

- Server-side script checks (current.update, GlideRecord in loops, error handling, async opportunities)
- Client-side script checks (DOM manipulation, sync GlideAjax, UI Policy work in client scripts)
- Architecture checks (table extensions, custom fields, DL framework, modularity, scoped apps)
- OOTB quick-check (lightweight — obvious replacements only: UI Policy for client script field manipulation, Flow Designer for legacy workflows, Approval Engine, Notification system, Data Lookup Definitions)

**Disposition Decision Tree:**

```
Obvious OOTB replacement? → YES: "Replace with OOTB [feature]"
                           → NO: continue ↓
Code clean / best practices? → YES: "Keep" — package into own custom scoped app
                              → Minor issues: "Keep with cleanup" — list fixes
                              → Significant issues: "Refactor" — detail what needs rewriting
Zero usage in lookback? → YES: "Evaluate for retirement"
```

**Scoped Application Guidance:**
- Default: each feature → its own custom scoped application
- Exception: related/parent-child features may share a scope or use dependent/claimed file relationships
- Benefits: clean namespace, easy disposal if OOTB replaces it later, proper dependency tracking

**Output:**
```
Code Quality: [Good / Needs Improvement / Poor]
Issues Found: [bullet list with BestPractice codes]
Disposition: [Keep / Refactor / Replace with OOTB / Evaluate for Retirement]
Rationale: [1-2 sentences]
If Refactor: what to fix
If Keep: scoped app recommendation
```

### Mode B: Assessment-Wide Technical Debt Roll-up

**Parameters:** `assessment_id` (required)

**Dynamic Context:** All customized ScanResults (summary), aggregated stats, 5-10 sample code snippets, update set summary, landscape summary, plus all active `BestPractice` records.

**The prompt scans across all artifacts for systemic patterns** using the BestPractice catalog detection hints. It aggregates findings by severity and reports affected artifact counts.

**Output:**
```
Assessment-Wide Technical Findings — [assessment number]

CRITICAL [count]:
  [#] [Finding] — [X] artifacts affected
      Examples: [names]
      Recommendation: [fix]

HIGH [count]: ...
MEDIUM [count]: ...

Overall Code Health: [Good / Fair / Poor / Concerning]
Scoped Application Readiness: [Ready / Needs Work / Major Refactoring]
Top 3 Priorities: [action items]
```

Stored as `GeneralRecommendation` with category `technical_findings`. When the dedicated findings table arrives, the output structure is already aligned for migration.

---

## Component 5: `report_writer` Prompt

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `assessment_id` | Yes | Assessment to report on |
| `sections` | No | Which to generate (default: all). Options: executive_summary, landscape, features, technical_findings, recommendations |
| `format` | No | `"full"` (default), `"executive_only"`, `"technical_only"` |

### Dynamic Context Injection

1. Assessment metadata (number, instance, state, scan counts, pipeline stage)
2. Landscape summary (GeneralRecommendation, category=landscape_summary)
3. Technical findings (GeneralRecommendation, category=technical_findings)
4. Feature groups (Feature records with member counts, dispositions, recommendations)
5. General recommendations (all other GeneralRecommendation records)
6. Statistics (total artifacts, customized count, reviewed count, grouped count, breakdowns)
7. Ungrouped artifacts (customized ScanResults not in any feature)

### Report Sections

1. **Executive Summary** — 2-3 paragraphs: scope, key findings, top 3 recommendations
2. **Customization Landscape** — volume, distribution, origin mix, update set patterns
3. **Feature Analysis** — each feature group with disposition, sorted by complexity/risk; ungrouped artifacts
4. **Technical Findings** — systemic issues by severity, code health, best practice gaps
5. **Recommendations** — prioritized action items: critical → high → medium

### Output Destination

Stored as GeneralRecommendation with category `assessment_report`.

---

## Implementation Order

```
6A: BestPractice model + seed data + admin UI
6B: artifact_analyzer prompt (foundation)
6C: relationship_tracer prompt
6D: technical_architect prompt (reads BestPractice catalog)
6E: report_writer prompt
```

6A is the foundation — the catalog must exist before 6D can use it. 6B and 6C are independent of each other. 6D depends on 6A. 6E depends on all others being available (but works with partial data).

---

## Key Reuse Points

| Existing Infrastructure | Reused In |
|------------------------|-----------|
| `PromptSpec` + prompt handler pattern | All 4 prompts |
| `GeneralRecommendation` model | technical_architect Mode B output, report_writer output |
| `ScanResult.observations` + `ai_observations` | artifact_analyzer reads context from these |
| `StructuralRelationship` model | relationship_tracer + artifact_analyzer context |
| `GroupingSignal` model | All prompts for signal context |
| `UpdateSetArtifactLink` + `UpdateSet` | relationship_tracer + artifact_analyzer context |
| Integration properties pattern | BestPractice admin follows same pattern |
| Existing admin list view pattern | BestPractice admin UI |

---

## Sources

- [Never use current.update in a Business Rule](https://www.servicenow.com/community/developer-blog/never-use-current-update-in-a-business-rule/ba-p/2274329)
- [UI Policy and Client Script best practice](https://www.servicenow.com/community/developer-forum/ui-policy-and-client-script-best-practice/m-p/3247425)
- [Incident Management - to extend or not](https://www.servicenow.com/community/itsm-articles/best-practice-incident-management-to-extend-or-not-to-extend-and/ta-p/3486025)
- [Avoid hardcoded values in scripts](https://www.servicenow.com/community/developer-articles/scripting-best-practices-avoid-using-hardcoded-values-in-scripts/ta-p/2466714)
- [Update Set Leading Practices](https://www.servicenow.com/community/developer-blog/servicenow-update-set-leading-practices-part-1/ba-p/3246473)
- [Performance Best Practices Server-side](https://www.servicenow.com/community/developer-articles/performance-best-practices-for-server-side-coding-in-servicenow/ta-p/2324426)
- [Configuring ACLs the Right Way](https://www.servicenow.com/community/platform-privacy-security-blog/configuring-acls-the-right-way/ba-p/3446017)
- [Migrate Legacy Workflows to Flows](https://www.servicenow.com/community/workflow-automation-articles/migrate-legacy-workflows-to-flows-and-playbooks-workflow/ta-p/3132026)
- [Service Catalog Best Practices](https://www.servicenow.com/community/servicenow-ai-platform-blog/servicenow-service-catalog-best-practices-designing-and/ba-p/2721122)
- [Managing skipped updates during upgrades](https://www.servicenow.com/community/developer-blog/best-practices-to-manage-skipped-updates-effectively-during/ba-p/3421456)
- [Application Development - Work in a scope](https://www.servicenow.com/community/servicenow-ai-platform-blog/application-development-best-practice-1-work-in-a-scope/ba-p/2288784)
- [Data Lookup Rules](https://www.servicenow.com/community/developer-blog/the-power-of-servicenow-data-matching-using-data-lookup-rules/ba-p/3008708)
- [Enforcing Best Practices with Instance Scan](https://www.servicenow.com/community/developer-articles/enforcing-best-practices-and-development-standards-for-your/ta-p/2349946)
- [Scoped Applications best practices](https://www.servicenow.com/community/architect-forum/scoped-applications-best-practices/m-p/2443232)
