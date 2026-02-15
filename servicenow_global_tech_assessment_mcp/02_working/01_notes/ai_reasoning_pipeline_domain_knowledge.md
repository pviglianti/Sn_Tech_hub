# AI Reasoning Pipeline — Domain Knowledge & Methodology

> **Source**: PV verbal walkthrough, 2026-02-15. This is how a human expert does technical assessments manually. The AI reasoning pipeline must replicate and assist with this process.
> **Status**: Living document — update as methodology refines.

---

## 1. Two Levels of Analysis Output

### Assessment Results (individual records)
Each scanned app file / metadata record gets:
- **Summary**: Short description of what it is / what it does.
- **Observations**: Iterative — start basic, refine as you learn more. Updated across multiple passes as context grows.
  - Example: "This script appears to do XYZ" → later: "This script conflicts with [other record], and part of it is broken" → later: "This is part of a feature group that handles [process], and this specific script calls [script include X]"
- Observations can note: broken logic, references to other records, conflicts/competition with other config, OOTB alternatives, deprecated patterns, etc.

### Features (groups of related config)
Emergent from the grouping process. Each feature gets:
- **Description**: What this group of configuration is designed to accomplish (the business intent).
- **Observations**: Feature-level insights (not just per-record).
- **Recommendation / Disposition**:
  - **Keep** — valuable, well-built, serves a real need
  - **Refactor** — good intent, bad implementation (or could be scoped to an app for future-proofing)
  - **Replace with OOTB** — ServiceNow has this built-in now; custom version is unnecessary
  - **Remove** — not needed anymore (platform matured, business process changed, feature is dead/broken)
- Supporting evidence and observations that help the customer decide.

### General Technical Recommendations (instance + assessment scoped)
- Separate concept from features and results.
- Logged and updated as findings emerge during the iterative process.
- May need consolidation/adjustment as the full picture clarifies.
- Examples: "This instance heavily uses client scripts for things UI policies handle declaratively — recommend a training initiative" or "Update sets are not organized by feature — recommend adopting a branching/scoping discipline."

---

## 2. The Grouping Process (Iterative, Multi-Pass)

This is NOT a one-shot classification. It's iterative:

1. **Pass 1 — Initial scan**: Summarize each result record. Basic observations.
2. **Pass 2 — Temporal/structural grouping**: Look for indicators of relatedness (see Section 3).
3. **Pass 3 — Feature emergence**: Group related records into logical features. Write feature-level observations.
4. **Pass N — Refinement**: As you learn more, update observations on BOTH individual results AND features. Discover new relationships. Merge or split features. Add cross-references.

A single app file can support more than one feature (e.g., a shared script include used by multiple features).

---

## 3. Grouping Indicators (How to Detect Relatedness)

These are heuristics, not gospel — but they're strong signals:

### Temporal Proximity
- **Sort all results by created or updated date.** Config items made in succession are likely related.
- Items created by the **same developer** in a similar timeframe are strong candidates for being part of the same solution.

### Update Set Analysis (Critical)
- **Same update set**: Items in the same update set are often part of the same story/feature/bug fix.
  - Caveat: Sometimes update sets are messy — lots of unrelated changes dumped together. Sometimes they're clean (one per story/feature).
- **Similar update set names**: If `US_FeatureX_v1` and `US_FeatureX_Enhancement_2024` exist, the contents are likely related even years apart.
- **Cross-update-set version history**: THIS IS A STRONG INDICATOR.
  - If Update Set 1 touches records A, B, C, D and Update Set 66 also touches records B, C (with current versions), those update sets are working on the same feature/solution.
  - Multiple update sets containing updates against overlapping records across version history = high confidence of feature relationship.
  - The non-current versions of an app file appearing in newer update sets = the feature was enhanced/maintained over time.

### Record References & Dependencies
- Scripts that call/reference other scripts (script includes, business rules calling utility functions).
- Client scripts and UI policies operating on the same form/fields.
- Dictionary entries, dictionary overrides, and scripts all touching the same table/fields.
- Catalog items with associated variables, UI policies, client scripts, and workflows.

### Structural Co-location
- Same application scope.
- Same table focus (multiple config items all operating on the same table).
- Related tables (parent/child relationships).

---

## 4. Key App File Types for Feature Detection

These are the "building blocks" of custom solutions in ServiceNow. They're the most important types for identifying features:

| App File Type | Why It Matters |
|---|---|
| **Dictionary entries** | Custom fields, table structure — the foundation of custom data |
| **Tables** | Custom tables = custom data model |
| **Dictionary overrides** | Customizations to inherited fields |
| **Business rules** | Server-side logic triggered by record operations |
| **Script includes** | Reusable server-side code (often shared across features) |
| **Client scripts** | Browser-side form logic |
| **UI policies** (with/without script) | Declarative or scripted form behavior |
| **UI policy actions** | What UI policies actually do |
| **Data policies** | Server-enforced data constraints |
| **Action policies** | Control what actions are available |
| **Record producers / Catalog items** | User-facing request forms |
| **Portal widgets** | Service Portal UI components |
| **Workflows / Flow Designer flows** | Process automation |

---

## 5. Common Finding Patterns (What AI Should Look For)

### OOTB Alternative Exists
- Custom fields replicating OOTB field functionality → recommendation: use OOTB fields instead, remove custom.
- Client scripts making fields mandatory → use dictionary mandatory attribute or UI policy instead (declarative, no code).
- Client scripts implementing dependent field behavior → use dictionary entries for dependent values (platform feature, no code).
- Scripts doing what UI policies, catalog UI policies, or action policies can do declaratively → recommend declarative approach.
- Custom notification logic when OOTB notification engine handles it.

### Platform Maturity Gap
- Feature was built when the platform was immature or the business process was immature.
- ServiceNow has since released OOTB capability that covers this.
- The custom solution is now unnecessary or redundant.

### Bad Implementation, Good Intent
- The business need is real and there's no OOTB solution.
- But the implementation is poor: bad coding patterns, deprecated APIs, over-engineered, fragile.
- Recommendation: Refactor and reimplement properly.
- Consider putting it into an application scope so it can be easily removed if a future upgrade/entitlement produces the feature OOTB.

### Dead or Broken Config
- Scripts with errors, broken references, or logic that can never execute.
- Config items that reference tables/fields that no longer exist.
- Features that appear abandoned (no updates in years, no evidence of use).

### Competing/Conflicting Config
- Multiple custom solutions trying to do the same thing (built by different teams at different times).
- A custom solution AND an OOTB solution both active on the same process.
- Conflicting business rules or client scripts on the same table.

---

## 6. Token Efficiency Strategy — Engines Before AI

Build deterministic engines to pre-stage and pre-group data BEFORE the AI sees it. AI should focus on judgment, not data sorting.

### Engine candidates (pre-AI staging):
- **Temporal clustering**: Group results by created/updated date proximity + same developer.
- **Update set content analysis**: Map which update sets touch which records. Identify cross-update-set overlap (strong grouping signal).
- **Version history chain**: For each app file, trace its version history across update sets. Show the "lifecycle" of each record.
- **Reference graph**: Parse script bodies for references to other records (table names, sys_ids, script include names). Build a dependency graph.
- **Table co-location**: Group all config items operating on the same table.
- **Same-scope grouping**: Group items sharing an application scope.

### What AI does on top of engine output:
- Interprets the clusters: "These 12 items across 3 update sets form a feature that handles [X]."
- Writes observations requiring judgment: "This script is fragile because..." or "This conflicts with OOTB [X] which was released in [version]."
- Makes disposition recommendations with evidence.
- Identifies patterns that engines can't: business intent, design quality, OOTB alternatives.

---

## 7. Data Model Implications

The AI pipeline needs these record types to write findings back to:

1. **Assessment Result** (existing) — individual scanned app files. Gets: summary, observations (iterative), references to related results.
2. **Feature** (new or existing) — grouped config items. Gets: description, feature-level observations, disposition recommendation, linked results.
3. **General Technical Recommendation** (new) — instance + assessment scoped. Gets: recommendation text, severity/priority, linked features/results.

All three have observations that are **iterative** — they get updated across multiple AI passes as context grows.

---

## 8. Process Flow (How It Actually Works)

```
Data Pull (already built)
    │
    ├── Mirror SN data to local DB
    │
    ▼
Engine Pre-Processing (to build)
    │
    ├── Temporal clustering
    ├── Update set content mapping + cross-US overlap detection
    ├── Version history chains
    ├── Reference graph (script parsing)
    ├── Table co-location grouping
    │
    ▼
AI Pass 1 — Initial Scan (to build)
    │
    ├── Summarize each result
    ├── Basic observations
    ├── Flag obvious patterns (broken, deprecated, OOTB alternative)
    │
    ▼
AI Pass 2 — Grouping (to build)
    │
    ├── Use engine output + AI judgment to form feature groups
    ├── Write feature descriptions
    ├── Update individual result observations with grouping context
    │
    ▼
AI Pass N — Refinement (to build)
    │
    ├── Cross-reference features
    ├── Identify competing/conflicting features
    ├── Refine observations on both results and features
    ├── Write disposition recommendations
    ├── Log general technical recommendations
    │
    ▼
AI writes all findings back to local DB
    │
    ▼
Web App displays findings (already built: browse, detail views)
```

---

## 9. Companion Documents

- **`grouping_signals.md`** (same directory) — Detailed signal taxonomy with 8 signal categories, confidence scoring weights, 4-phase clustering algorithm design, and cluster output JSON schema. Created 2026-01-31. Restored from archive 2026-02-15.
- **`assessment_guide_and_script_v3_pv.md`** (`01_source_data/01_reference_docs/`) — The classification logic for detecting customizations (update version history method + baseline comparison method). Defines `origin_type` and `classification` field logic.
- **`snow_flow_analysis/`** (same directory) — 10-part analysis of Snow-flow tools. Doc 09 = tool mapping matrix, Doc 10 = integration plan.
- **Planned deliverable**: `03_outputs/05_feature_grouping_heuristics_and_clustering_rules.md` — per `deliverables_spec.md`, acceptance criteria: "deterministic grouping rules and confidence model." To be produced from this methodology + grouping_signals.md when pipeline is built.

## Archive Note
This document captures methodology as described by PV. It will be refined as the pipeline is implemented and tested against real assessment data.
