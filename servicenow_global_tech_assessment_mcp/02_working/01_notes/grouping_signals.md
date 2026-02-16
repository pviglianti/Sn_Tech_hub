# Feature/Solution Grouping Signals (Working Notes)

## Source
- Snow-Flow analysis (ChatGPT/Codex deep research)
- Project goal: group "application files/records" into human-meaningful "custom features/solutions"
- Date: 2026-01-31

---

## The Grouping Problem

### Goal
Given thousands of customized records across dozens of tables, identify which records belong together as a "feature" or "solution" that delivers a specific business capability.

**Example**: "Custom Approval Workflow for Change" might include:
- 2 business rules (on change_request)
- 1 script include (ApprovalHelper)
- 3 client scripts
- 1 UI action
- 1 workflow
- 5 notifications
- 2 UI policies

These should be grouped together, not analyzed as 15 separate items.

---

## Signal Categories

### 1. Update Set Cohorts
**Principle**: Records captured in the same update set were likely changed together for the same purpose.

**Signal strength**: STRONG (explicit grouping by developer)

**How to use**:
- Query `sys_update_xml` grouped by `update_set`
- Records in same update set = candidate cluster
- Multiple update sets with similar names = larger feature
- Leverage update set name and description. If update set references a task number, look up task to determine what it was for and may help infer what the update set contains.
- After a tool performs analysis of artificat including interpretation of script, leverage its findings/observations and find observations amongst other artifcats that may indicate that they are used together
- sys_update_xml records that are still current in the version history that are created in successsion (or updated) by the same developer or in same update set often indicate a group of application files/configurations meant to work together.

**Caveats**:
- Update sets may contain unrelated changes (cleanup, multiple fixes)
- May span multiple features if developer didn't separate
- "Default" update set contains everything not explicitly assigned or work done directly in production, not best practice but happens.. leverage time as the key things here (updated and updated by) any in scope updates in default that seem to be created insuccession or updated in a tight timeframe may indicate a commmon feature/grouping

**Heuristics**:
- Weight by update set name similarity (e.g., "RITM Approval Phase 1", "RITM Approval Phase 2")
- "Default" update set - treat with lower confidence - only useful indicator is if other updates created in same timeframe by same developer are also still the current versions. Analyze what they do and if they seem to work together to provide a feature or solution.
- Consider `sys_created_by` and 'sys_updated_by' as well as the updated date/time as it will equal created or be source for files w multiple updates + time window

---

### 2. Table Affinity
**Principle**: Multiple customizations targeting the same table are possibly related.

**Signal strength**: MEDIUM (common but not definitive)

**How to use**:
- Group business rules, client scripts, UI policies, UI actions by target table
- Records targeting `incident` likely form feature clusters around incident
- see if artifcats were in same update set or updated/created at same time by same user

**Caveats**:
- Large tables (incident, task) may have many unrelated customizations
- Need secondary signals to split

**Heuristics**:
- Combine with naming patterns
- Combine with temporal proximity
- Weight by table specificity (custom tables = stronger signal)

---

### 3. Naming Conventions
**Principle**: Developers often use consistent naming prefixes/suffixes for related components.

**Signal strength**: MEDIUM-STRONG (when present)

**How to use**:
- Extract common prefixes: `u_custom_approval_*`, `ACME_*`, `Project_X_*`
- Cluster records with matching prefixes
- Look for numbered sequences: `*_phase1`, `*_phase2`

**Caveats**:
- Not all developers follow conventions
- Prefixes may be company-wide, not feature-specific

**Heuristics**:
- Tokenize names, find common n-grams 
- Weight by specificity (longer prefix = stronger)
- Combine with table affinity

---

### 4. Code References (Cross-References)
**Principle**: If code in record A calls/references record B, they're related.

**Signal strength**: STRONG (explicit dependency)

**How to use**:
- Parse script fields for:
  - `GlideRecord` calls (table references)
  - Script include instantiation (`new ClassName()`)
  - `gs.include()` calls
  - `sn_ws.RESTMessageV2` calls
  - Workflow/flow references
- Build dependency graph

**Types of references**:
| Pattern | Reference Type |
|---------|----------------|
| `new ClassName()` | Script include |
| `GlideRecord('table_name')` | Table |
| `gs.include('name')` | Script include |
| `current.field` references | Field |
| `gs.eventQueue('event_name')` | Event |
| `workflow.start('wf_name')` | Workflow |

**Caveats**:
- Parsing JavaScript is imperfect
- Dynamic references may be missed
- Large dependency graphs may need pruning

**Heuristics**:
- Use AST parsing if possible (or regex fallback)
- Weight by reference type (script include call = strong; table query = weak)
- Limit graph depth (2-3 levels)

---

### 5. sys_metadata Parent/Child
**Principle**: Some records have explicit parent-child relationships in metadata.

**Signal strength**: STRONG (system-defined)

**How to use**:
- Query `sys_metadata` for parent relationships
- Some tables have explicit parent fields

**Known relationships**:
- Table → Business rules (via `collection` field)
- Table → Dictionary entries (via `name` field)
- UI Policy → UI Policy Actions (via `ui_policy` reference)
- Workflow → Activities (via `workflow_version`)

**Caveats**:
- Not all relationships are explicit
- May need to traverse multiple levels

---

### 6. Temporal Proximity
**Principle**: Records created/updated at the same time by the same user are likely related.

**Signal strength**: WEAK-MEDIUM (circumstantial)

**How to use**:
- Cluster by `sys_created_on` + `sys_created_by` within time window
- Same user, same day = candidate cluster

**Caveats**:
- User may work on multiple features in same day
- Bulk imports may have identical timestamps but unrelated content

**Heuristics**:
- Use tight time windows (minutes, not days)
- Combine with other signals (naming, table)
- Weight by user specificity (admin = weak; specialist = stronger)

---

### 7. Reference Field Values
**Principle**: Records referencing the same target record are related to that target.

**Signal strength**: MEDIUM (explicit but indirect)

**How to use**:
- Business rules, client scripts with same `collection` = related
- Multiple scripts referencing same script include
- Multiple flows triggered by same table event

**Caveats**:
- Common targets (task, incident) will have many records

---

### 8. Application / Package
**Principle**: Records in the same application or plugin belong together.

**Signal strength**: STRONG for scoped apps, WEAK for global

**How to use**:
- Scoped apps: `sys_scope` field explicitly groups
- Global: `sys_package` may indicate plugin origin

**Caveats**:
- Global scope is a catch-all
- Plugin boundaries may not match business features

---

## Clustering Algorithm Design (Draft)

### Phase 1: Initial Clusters (High-Confidence)
1. **Update set clusters**: Group by update set (exclude Default)
2. **Scoped app clusters**: Group by `sys_scope` (non-global)
3. **Package clusters**: Group by `sys_package` (plugins)

### Phase 2: Merge by Strong Signals
1. **Code reference merge**: If cluster A references cluster B, consider merging
2. **Naming merge**: If cluster names share significant prefix, consider merging
3. **Update set name merge**: Similar update set names = merge

### Phase 3: Split by Weak Signals
1. **Table split**: If cluster spans many unrelated tables, consider splitting
2. **Time split**: If cluster spans long time period, consider splitting
3. **User split**: If cluster has many distinct authors, consider splitting

### Phase 4: Orphan Assignment
1. Records not in any cluster = orphans
2. Assign orphans to nearest cluster by:
   - Code references (strongest)
   - Table affinity + naming
   - Temporal proximity
3. Remaining orphans = "Unclustered Customizations"

---

## Confidence Scoring

Each cluster gets a confidence score:

| Signal | Weight |
|--------|--------|
| Same update set | +3 |
| Same scoped app | +5 |
| Code reference (direct) | +4 |
| Code reference (transitive) | +2 |
| Same table target | +1 |
| Similar naming (prefix match) | +2 |
| Same author + close time | +1 |
| Multiple signals align | +2 (bonus) |

**Confidence levels**:
- High (8+): Strong cluster, likely a real feature
- Medium (4-7): Probable cluster, needs validation
- Low (1-3): Weak cluster, may be coincidental

---

## Cluster Output Schema

```json
{
  "cluster_id": "uuid",
  "cluster_name": "Auto-generated or user-provided",
  "confidence": "high|medium|low",
  "confidence_score": 8,
  "signals": [
    { "type": "update_set", "value": "RITM Approval", "weight": 3 },
    { "type": "code_reference", "value": "ApprovalHelper referenced", "weight": 4 }
  ],
  "records": [
    { "sys_id": "...", "table": "sys_script", "name": "BR - Approval Check" },
    { "sys_id": "...", "table": "sys_script_include", "name": "ApprovalHelper" }
  ],
  "tables_involved": ["sys_script", "sys_script_include", "sys_script_client"],
  "primary_table": "change_request",
  "authors": ["admin", "john.doe"],
  "date_range": {
    "earliest": "2024-01-15",
    "latest": "2024-03-20"
  }
}
```

---

## Open Questions

1. **How to handle circular references?** (A → B → A)
2. **What's the right cluster size?** (Too small = fragmented; too large = meaningless)
3. **How to name clusters automatically?** (Most common word? Table target?)
4. **How to handle version history in clustering?** (Same record, different versions)
5. **Should deleted records be included?** (In update sets but no longer exist)
6. **How to validate clusters?** (Need sample data or user feedback)

---

## Test Cases Needed

1. **Clean feature**: All records in one update set, consistent naming → should cluster perfectly
2. **Messy feature**: Spread across multiple update sets, inconsistent naming → should still cluster
3. **Independent fixes**: Multiple unrelated bug fixes in same update set → should NOT cluster
4. **Large table**: Many customizations on `incident` → should split into multiple clusters
5. **Orphan script include**: Called by many unrelated scripts → should remain separate or assign to primary caller
