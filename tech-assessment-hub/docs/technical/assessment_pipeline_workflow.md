# Assessment Pipeline Workflow — Technical Reference

> **Last updated**: 2026-03-06
> **Scope**: End-to-end assessment lifecycle from scan creation through final report delivery

---

## Table of Contents

1. [Pipeline Overview](#pipeline-overview)
2. [Stage-by-Stage Breakdown](#stage-by-stage-breakdown)
3. [Preprocessing Engines](#preprocessing-engines)
4. [AI Prompt Templates](#ai-prompt-templates)
5. [Per-Stage Tool Sets](#per-stage-tool-sets)
6. [Record Types & Data Model](#record-types--data-model)
7. [Feature Grouping & Convergence](#feature-grouping--convergence)
8. [Dispatch Mechanism](#dispatch-mechanism)
9. [Orchestration Roles](#orchestration-roles)
10. [Final Deliverables](#final-deliverables)

---

## Pipeline Overview

The assessment pipeline has **10 stages**. Every stage requires a **manual button press** to advance — there is no auto-progression. Each AI stage spawns a background thread tracked by `_AssessmentPipelineJob`.

### Core Philosophy

- **Think functionally, not structurally.** Engines produce raw signals with noise. The AI's job is: "What does this artifact do? Does it work with others as part of a solution?"
- **Observations evolve.** Each pipeline pass deepens understanding. Early passes produce basic summaries; later passes connect artifacts to features.
- **Disposition is human-only.** AI never sets or suggests keep/remove/refactor/replace. That decision happens after stakeholders review findings. AI describes WHAT and HOW — humans decide WHAT TO DO.
- **Human changes are facts.** If a human edits scope, observations, or feature assignments, AI preserves the premise and can only refine wording.
- **Multiple iterations are normal.** Expect 2-3 full pipeline runs before the story is stable. Re-run from `complete` resets to `ai_analysis`.
- **Nothing left floating.** Every in-scope customized record must be grouped — either in a functional feature or a categorical catch-all.

### Iteration Model

The pipeline is designed for multiple full passes. Each pass deepens the analysis:
- **Pass 1**: Basic functional observations, initial scope decisions, engine-driven feature seeds
- **Pass 2**: Enriched observations with feature context, refined groupings, categorical catch-alls for ungrouped records
- **Pass 3+**: Stabilized story, final recommendations, human review optional at each iteration boundary

```
SCANS → ENGINES → AI_ANALYSIS → OBSERVATIONS → REVIEW → GROUPING → AI_REFINEMENT → RECOMMENDATIONS → REPORT → COMPLETE
  ↑                                                                                                              ↓
  └──────────────────────────────── rerun=true (reset to ai_analysis) ────────────────────────────────────────────┘
```

**Advancement endpoint**: `POST /api/assessments/{id}/advance-pipeline`

```json
{
  "target_stage": "engines",
  "skip_review": false,
  "force": false,
  "rerun": false
}
```

**Allowed targets**: `ai_analysis`, `engines`, `observations`, `review`, `grouping`, `ai_refinement`, `recommendations`, `report`

**Rules**:
- Cannot move backwards (except `rerun` from `complete` → `ai_analysis`)
- Cannot skip multiple stages (except `review` → `grouping` with `skip_review=true`)
- Review gate must be satisfied before grouping unless `skip_review=true`

---

## Stage-by-Stage Breakdown

### Stage 1: SCANS — Data Collection

| Attribute | Value |
|-----------|-------|
| **Trigger** | `run_assessment(instance_id, name)` via UI or MCP |
| **Human** | Initiates; no intervention during execution |
| **Background job** | Yes — scan executor thread |
| **Config** | `config/scan_rules.yaml` |

**What happens**:
- Queries ServiceNow tables (sys_script, sys_script_include, sys_ui_policy, sys_business_rule, etc.) via REST API
- Classifies each artifact by `origin_type`: `modified_ootb`, `net_new_customer`, `ootb_untouched`
- Creates `ScanResult` rows in local database
- `customization_sync.py` mirrors customized results into `Customization` child table (token-efficient read target)

**Output records**: `ScanResult`, `Customization`

---

### Stage 2: ENGINES — Deterministic Preprocessing

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance → `run_preprocessing_engines(assessment_id)` |
| **Human** | Clicks advance; no intervention during execution |
| **Background job** | Yes |
| **MCP tool** | `run_preprocessing_engines` |

Runs 6 deterministic engines in sequence. See [Preprocessing Engines](#preprocessing-engines) for full details.

**Output records**: `structural_relationship`, `code_reference`, `update_set_artifact_link`, `update_set_overlap`, `temporal_cluster`, `naming_cluster`, `table_colocation_summary`

---

### Stage 3: AI_ANALYSIS — Per-Artifact AI Deep-Dive

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance |
| **Human** | None during execution |
| **Background job** | Yes — dispatched via `ClaudeCodeDispatcher` |
| **AI prompt** | `artifact_analyzer` |
| **Tool set** | `get_customizations`, `get_result_detail`, `update_scan_result` |

**What happens**:
- For each customized artifact, AI receives injected context:
  - Artifact metadata (name, table, origin, is_active, meta_target_table)
  - Code snippet (first 150 lines)
  - Existing observations
  - Structural relationships (parents/children)
  - Update set links (background context only — not surfaced in output)
- AI performs two tasks:
  1. **Scope decision**: in_scope / adjacent / out_of_scope / needs_review
  2. **Functional summary**: Plain-language description of what the artifact does — what fields it sets, what tables it queries, what records it creates, when it fires — and connections to other customized artifacts in the assessment
- AI does **NOT** set disposition (human decides after stakeholder review), severity, or category
- Writes back to `ScanResult`: observations (functional summary), scope flags (`is_out_of_scope`, `is_adjacent`)
- Sets `review_status` → `review_in_progress`

**Dispatch**: Batched via `ClaudeCodeDispatcher` with budget cap per batch.

---

### Stage 4: OBSERVATIONS — Deterministic Baseline + Usage Enrichment

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance |
| **Human** | None during execution |
| **Background job** | Yes |
| **MCP tool** | `generate_observations` |
| **AI prompts** | `observation_landscape_reviewer`, `observation_artifact_reviewer` |
| **Tool set** | `generate_observations`, `get_result_detail`, `get_customizations` |

**What happens**:
For each customized result (batched, default 10):
1. Counts structural signals (parent/child relationships)
2. Finds update set links and primary update set name
3. Optionally queries ServiceNow for live usage counts (configurable: `always`/`auto`/`never`)
4. Generates human-readable observation text + structured JSON

**Sample observation text**:
```
This modified_ootb artifact `sys_script_my_rule` (sys_script) is treated as customized
and included in feature-grouping analysis. It has 1 linked update-set signal(s);
primary context is `Update_Set_Alpha`. Structural analysis found 2 related parent/child
signal(s). Usage checks: incident: 145 record(s).
```

**Sample ai_observations JSON**:
```json
{
  "generated_at": "2026-03-06T15:30:45.123456",
  "generator": "deterministic_pipeline_v1",
  "structural_signal_count": 2,
  "update_set_signal_count": 1,
  "usage_responses": [
    { "table": "incident", "count": 145, "success": true, "cached": false }
  ]
}
```

**Also creates**: `GeneralRecommendation` with `category="landscape_summary"` — assessment-wide customization landscape overview.

---

### Stage 5: REVIEW — Optional Human Pause Point

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance → sets stage, returns gate status immediately |
| **Human** | **OPTIONAL** — can review/edit scope, observations, features, or skip |
| **Background job** | **None** — no background work |
| **Bypass** | `skip_review=true` auto-marks remaining as reviewed |

**Purpose**: Pause point at each iteration boundary. The AI typically runs through the full pipeline 2-3 times before a human looks. At each iteration, Stage 5 offers the opportunity to review, but it's not mandatory.

**What a human might do**:
- Fix scope decisions (mark out-of-scope, mark adjacent)
- Edit observations to correct inaccuracies
- Create or reassign feature groupings
- Update feature descriptions or observations
- Any human changes become **authoritative facts** — subsequent AI passes preserve the premise

**Gate check**:
```python
{
  "reviewed": count,
  "pending": count,
  "in_progress": count,
  "total_customized": total,
  "all_reviewed": reviewed >= total
}
```

Must have `all_reviewed == true` OR `skip_review == true` to proceed to grouping.

---

### Stage 6: GROUPING — Feature Seeding

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance (only when review gate satisfied) |
| **Human** | None during execution |
| **Background job** | Yes |
| **MCP tool** | `seed_feature_groups` |
| **Tool set** | `create_feature`, `add_result_to_feature`, `feature_grouping_status`, `get_customizations` |

**What happens**:
1. Builds weighted graph from all 6 engine output tables
2. Edge weights accumulate per signal type (see table below)
3. Connected components with cumulative weight ≥ `min_edge_weight` (default 2.0) form groups
4. Filter by `min_group_size` (default 2)
5. Only customized results become `FeatureScanResult` members; non-customized become `FeatureContextArtifact`

**Edge weight table**:

| Signal Source | Weight | Source Table |
|--------------|--------|--------------|
| Update set artifact link | 3.0 | `update_set_artifact_link` |
| Update set overlap | 2.5 | `update_set_overlap` |
| Temporal cluster | 2.0 | `temporal_cluster` |
| Naming cluster | 2.0 | `naming_cluster` |
| Table colocation | 2.0 | `table_colocation_summary` |
| Code reference | 2.0 | `code_reference` |
| Structural relationship | 2.0 | `structural_relationship` |

**Confidence scoring**: `max(0, min(1, avg_edge_weight/5)) * 0.6 + member_degree * 0.4`

**Naming strategy**: Primary update set name → naming cluster label → primary table (fallback chain).

**Output records**: `Feature`, `FeatureScanResult`, `FeatureContextArtifact`

---

### Stage 7: AI_REFINEMENT — Feature Analysis

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance |
| **Human** | None during execution |
| **Background job** | Yes |
| **AI prompts** | `technical_architect` (Mode A per-artifact, Mode B assessment roll-up) |
| **MCP tool** | `run_feature_reasoning` |
| **Tool set** | `feature_detail`, `get_result_detail`, `feature_grouping_status` |

**What happens**:
- Evaluates features against `BestPractice` knowledge base records
- Runs iterative reasoning loop: observe → group_refine → verify
- Convergence: `delta_ratio < 0.01 AND high_confidence_changes == 0`
- Typical: 2–4 passes, tracked by `FeatureGroupingRun`

**Output**: `Feature.ai_summary`, `Feature.disposition`, `Feature.recommendation`

See [Feature Grouping & Convergence](#feature-grouping--convergence) for iteration details.

---

### Stage 8: RECOMMENDATIONS — OOTB Replacement Mapping

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance |
| **Human** | None during execution |
| **Background job** | Yes |
| **AI prompts** | `feature_reasoning_orchestrator`, `technical_architect` |
| **MCP tool** | `upsert_feature_recommendation` |
| **Tool set** | `feature_recommendation`, `feature_detail`, `get_customizations` |

**What AI does**: For each feature, identifies OOTB ServiceNow capabilities that could replace custom code.

**Sample FeatureRecommendation**:
```
recommendation_type: "replace"
ootb_capability_name: "Incident Management REST API"
product_name: "ServiceNow Incident Management"
sku_or_license: "IT Service Management (ITSM)"
requires_plugins: ["com.snc.incident"]
fit_confidence: 0.85
rationale: "Custom API wrapper duplicates OOTB table API with added auth layer..."
evidence: { "matched_patterns": [...], "coverage_pct": 0.92 }
```

---

### Stage 9: REPORT — Final Deliverable Generation

| Attribute | Value |
|-----------|-------|
| **Trigger** | Manual advance |
| **Human** | None during execution |
| **Background job** | Yes |
| **AI prompt** | `report_writer` |
| **Tool set** | `assessment_results`, `feature_detail`, `get_customizations` |

**5 Report sections**:
1. **Executive Summary** — 2-3 paragraphs: scope, key findings, top 3 recommendations
2. **Customization Landscape** — volume, distribution, origin mix, update set patterns
3. **Feature Analysis** — features by complexity/risk, member counts, AI summaries, recommendations
4. **Technical Findings** — systemic issues by severity (critical → info)
5. **Recommendations** — prioritized action items with rationale and expected impact

**Format presets**:
- `full` — all 5 sections
- `executive_only` — sections 1, 2, 5
- `technical_only` — sections 3, 4, 5

**Context injected into prompt**: Assessment metadata, statistics (total/customized/reviewed/grouped counts), feature records with members and recommendations, GeneralRecommendation records, landscape summary.

**Output**: `GeneralRecommendation` with `category="assessment_report"` containing full report.

**Final action**: Sets `review_status=reviewed` on all in-scope/adjacent artifacts.

---

### Stage 10: COMPLETE

| Attribute | Value |
|-----------|-------|
| **Trigger** | Automatic after report |
| **Re-run** | `rerun=true` resets back to `ai_analysis` |

---

## Preprocessing Engines

All 6 engines are deterministic (no AI), idempotent (delete + recreate on rerun), and have no inter-engine dependencies.

### Engine 1: Structural Mapper
**File**: `src/engines/structural_mapper.py`

Maps explicit parent/child relationships between artifacts using known reference field patterns.

| Pattern | Relationship Type | Reference Field | Example |
|---------|------------------|-----------------|---------|
| UI Policy Actions → UI Policy | `ui_policy_action` | `ui_policy` (sys_id) | `Approver Policy → Set Is Disabled` |
| Dictionary → Table | `dictionary_entry` | `collection_name` (table name) | `incident → incident.priority` |
| Dictionary Override → Dictionary | `dictionary_override` | `collection_name` (table name) | `incident → custom_priority_default` |

**Output table**: `structural_relationship` — fields: `parent_scan_result_id`, `child_scan_result_id`, `relationship_type`, `parent_field`, `confidence` (always 1.0)

---

### Engine 2: Code Reference Parser
**File**: `src/engines/code_reference_parser.py`

Parses script/code fields with 9 regex patterns to find cross-references.

| Pattern | Reference Type | Example Match |
|---------|---------------|---------------|
| `new SomeClass(` | script_include | `new NotificationHelper()` |
| `new GlideRecord('table')` | table_query | `new GlideRecord('cmdb_ci')` |
| `gs.include('name')` | script_include | `gs.include('Utils')` |
| `gs.eventQueue('name')` | event | `gs.eventQueue('incident.changed')` |
| `new GlideAjax('name')` | script_include | `new GlideAjax('AjaxHelper')` |
| `new RESTMessageV2('name')` | rest_message | `new RESTMessageV2('MyAPI')` |
| `workflow.startFlow('name')` | workflow | `workflow.startFlow('Approval')` |
| `$sp.getWidget('name')` | sp_widget | `$sp.getWidget('my-widget')` |
| 32-char hex string | sys_id_reference | `a1b2c3d4...` |

**Output table**: `code_reference` — fields: `source_scan_result_id`, `source_table`, `source_field`, `reference_type`, `target_identifier`, `target_scan_result_id` (resolved if found), `line_number`, `code_snippet`

---

### Engine 3: Update Set Analyzer
**File**: `src/engines/update_set_analyzer.py`

Links artifacts to update sets from 3 sources, then computes 5 overlap signal types between update set pairs.

**Link sources**:
1. `scan_result.update_set_id` (current placement) — `link_source="scan_result_current"`
2. `customer_update_xml` records — `link_source="customer_update_xml"`
3. `version_history` records — `link_source="version_history"`

**5 Overlap signal types**:

| Signal Type | What It Measures | Score Basis |
|-------------|-----------------|-------------|
| `content` | Shared artifacts between update sets | Jaccard index |
| `name_similarity` | Shared ticket IDs or name tokens | Token overlap ratio |
| `version_history` | Artifacts with VH entries linking to same US | Shared VH record count |
| `temporal_sequence` | Update sets created/completed within gap threshold (default 5 min) | Time proximity |
| `author_sequence` | Same developer created both within extended gap (default 240 min) | Author + time proximity |

**Output tables**: `update_set_artifact_link`, `update_set_overlap`

---

### Engine 4: Temporal Clusterer
**File**: `src/engines/temporal_clusterer.py`

Groups artifacts by same developer + close time proximity into development session clusters.

**Parameters** (from integration properties):
- `temporal_gap_threshold_minutes`: 30 (default)
- `temporal_min_cluster_size`: 2 (default)

**Algorithm**: Group by developer → sort by `sys_updated_on` → walk: if gap ≤ threshold, extend cluster; else emit cluster (if ≥ min_size) and start new.

**Sample output**:
```
developer: john.smith | 09:15–11:30 | 7 artifacts | avg gap 18min | tables: sys_script, sys_br
developer: jane.doe  | 14:00–15:45 | 5 artifacts | avg gap 22min | tables: sys_ui_policy
```

**Output tables**: `temporal_cluster`, `temporal_cluster_member`

---

### Engine 5: Naming Analyzer
**File**: `src/engines/naming_analyzer.py`

Groups artifacts by shared naming prefixes/patterns.

**Algorithm**: Tokenize names (split on spaces/hyphens/underscores/dots) → generate all prefix sequences → group by prefix → keep groups ≥ `min_cluster_size` → deduplicate (prefer longest/most specific).

**Sample output**:
```
"incident mgmt": 5 members | tables: sys_script, sys_br
"custom approver": 3 members | tables: sys_ui_policy
"asset sync": 2 members | tables: sys_script_include
```

**Output table**: `naming_cluster` — fields: `cluster_label`, `pattern_type`, `member_count`, `member_ids_json`, `tables_involved_json`

---

### Engine 6: Table Colocation
**File**: `src/engines/table_colocation.py`

Groups artifacts by their target ServiceNow table (`meta_target_table`).

**Sample output**:
```
incident: 6 artifacts | types: sys_script, sys_br, sys_ui_policy | devs: john.smith, jane.doe
cmdb_ci_computer: 3 artifacts | types: sys_script_include, sys_br | devs: admin
```

**Output table**: `table_colocation_summary` — fields: `target_table`, `record_count`, `record_ids_json`, `artifact_types_json`, `developers_json`

---

## AI Prompt Templates

All prompts live in `src/mcp/prompts/` and are registered via `PromptSpec` objects in the `PromptRegistry`.

### 1. `tech_assessment_expert` — Full Methodology (System Prompt)
**File**: `src/mcp/prompts/tech_assessment.py`
**Handler**: `_expert_handler()` — injects `assessment_id` context if provided
**Size**: ~7,000 words

Comprehensive ServiceNow technical assessment methodology covering:
- Core philosophy (think functionally, observations evolve, disposition is human-only, human changes are facts)
- Assessment methodology (depth-first, temporal order, rabbit holes into other customized records)
- Scope decisions (in_scope, adjacent, out_of_scope) with examples
- Signal quality hierarchy (definitive → strong → contextual → weak) with update set quality evaluation
- Origin classification decision tree (modified_ootb, net_new_customer, ootb_untouched, unknown)
- Categorical catch-all buckets for ungrouped records (Form Fields & UI, ACLs & Roles, etc.)
- Common finding patterns (OOTB alternatives, maturity gaps, dead configs, competing configs)
- Key app file type analysis guides (dictionaries, business rules, script includes, etc.)
- Tool usage guide with all available MCP tools
- Token efficiency rules
- Live instance query governance (`query_instance_live` controlled by `ai_analysis.context_enrichment` property)

---

### 2. `tech_assessment_reviewer` — Review Validation
**File**: `src/mcp/prompts/tech_assessment.py`
**Handler**: `_reviewer_handler()`
**Size**: ~1,200 words

Lighter review checklist for validating existing findings:
- Classification accuracy, scope accuracy, observation quality
- Feature coherence (do members actually work together?), completeness checks
- Coverage verification (nothing left floating)
- Disposition is human-only — AI validates analysis quality, not disposition correctness
- Human changes are authoritative; AI may refine wording but not premise

---

### 3. `feature_reasoning_orchestrator` — Iterative Grouping Loop
**File**: `src/mcp/prompts/tech_assessment.py`
**Handler**: `_reasoning_orchestrator_handler()` — injects `assessment_id`
**Size**: ~2,200 words

Drives the full feature grouping lifecycle:
1. Evaluate update set quality (clean/mixed/dirty) — determines signal weighting
2. Call `seed_feature_groups` for deterministic initial clustering
3. Call `run_feature_reasoning` iteratively until convergence
4. Review/refine features with human-readable descriptions
5. Handle ungrouped records via categorical catch-all features (Form Fields & UI, ACLs & Roles, etc.)
6. Pause for optional human review — human changes are authoritative facts
7. Generate OOTB recommendations via `upsert_feature_recommendation` (informational, not disposition)

Key principles: disposition is human-only, human changes are facts, nothing left floating, observations evolve across passes

Also includes Claude Code skills and output tools guidance for later iterations and deliverable production

---

### 4. `artifact_analyzer` — Single Artifact Deep-Dive
**File**: `src/mcp/prompts/artifact_analyzer.py`
**Handler**: `_artifact_analyzer_handler()` — dynamic context injection from DB
**Size**: ~1,000 words + injected context

**Injected context** (queried from database):
- Artifact metadata (name, table, origin, is_active, meta_target_table, etc.)
- Code snippet (first 150 lines)
- Existing observations
- Structural relationships (parents/children from `StructuralRelationship`)
- Update set links (background context — not surfaced in output)

**AI task**: Two jobs only:
1. **Scope decision** — in_scope / adjacent / out_of_scope / needs_review
2. **Functional summary** — Plain-language observation: what does it do (sets fields, queries tables, creates records, fires on what trigger), and what other customized artifacts in this assessment does it reference or connect to

**AI does NOT**: Set disposition, severity, or category. Does not mention update sets in observations. Does not reproduce code.

**Live instance queries**: Can use `query_instance_live` to fill context gaps (e.g., referenced script include not in results). Governed by `ai_analysis.context_enrichment` property (auto/always/never).

**Type-specific focus**: Different analysis angle per `table_name` — sys_script (what triggers, what it does to records), sys_script_include (what API it exposes, who calls it), sys_ui_policy (what fields it shows/hides), etc.

---

### 5. `observation_landscape_reviewer` — Landscape Summary Enrichment
**File**: `src/mcp/prompts/observation_prompt.py`
**Handler**: `_landscape_reviewer_handler()` — injects `assessment_id`
**Size**: ~500 words

Reviews and enriches the automated landscape summary (`GeneralRecommendation` with `category=landscape_summary`). Produces 3-6 sentence enriched narrative grounded in data.

---

### 6. `observation_artifact_reviewer` — Per-Artifact Observation Enrichment
**File**: `src/mcp/prompts/observation_prompt.py`
**Handler**: `_artifact_reviewer_handler()` — injects `assessment_id`
**Size**: ~900 words

Batch-processes customized artifacts (10-20 at a time). For each with `review_status` pending/in_progress: reads existing observation → enriches functional description (what fields it sets, what tables it queries, ref qualifiers, triggers) → calls out connections to other customized scan results → writes enriched 2-5 sentence observation. Prioritizes scriptable artifacts. Observations evolve across passes — early passes are basic functional summaries, later passes include feature context and cross-artifact relationships. No disposition recommendations — describe function and connections only.

---

### 7. `relationship_tracer` — Cross-Artifact Dependency Mapping
**File**: `src/mcp/prompts/relationship_tracer.py`
**Handler**: `_relationship_tracer_handler()` — dynamic context injection from DB
**Arguments**: `result_id`, `assessment_id`, `max_depth` (default 3), `direction` (outward/inward/both)

**Injected context**:
- Starting artifact (name, table, origin, observations)
- Code snippet (first 100 lines)
- Direct structural relationships
- Update set siblings
- Table-level neighbors (capped at 20)
- Naming cluster context
- Existing feature context

**AI output**: Core cluster → adjacent artifacts → distant connections → recommended grouping narrative.

---

### 8. `report_writer` — Final Report Generation
**File**: `src/mcp/prompts/report_writer.py`
**Handler**: `_report_writer_handler()` — dynamic context injection from DB
**Arguments**: `assessment_id`, `sections` (optional CSV), `format` (full/executive_only/technical_only)
**Size**: ~2,000 words + injected context

**Injected context**:
- Assessment metadata (name, number, state, type, instance, scan count)
- Statistics (total, customized, reviewed, grouped, breakdown by table)
- Landscape summary from `GeneralRecommendation`
- All `Feature` records with member counts, dispositions, descriptions, recommendations, AI summaries
- Ungrouped customized artifacts
- Technical findings from `GeneralRecommendation`

**Format presets**:
- `full`: Executive Summary, Landscape, Features, Technical Findings, Recommendations
- `executive_only`: Executive Summary, Landscape, Recommendations
- `technical_only`: Features, Technical Findings, Recommendations

---

### 9. `technical_architect` — Technical Review (Dual Mode)
**File**: `src/mcp/prompts/technical_architect.py`
**Handler**: `_technical_architect_handler()` — dispatches Mode A or Mode B based on `result_id` presence
**Arguments**: `result_id` (optional), `assessment_id` (required)

**Mode A** (per-artifact, when `result_id` provided, ~650 words):
- Evaluates single artifact against applicable `BestPractice` records
- Injected: metadata, code (200 lines), observations, update set links, filtered BestPractice catalog
- Output: code quality rating, issues with BP codes, suggested disposition, rationale, refactoring guidance

**Mode B** (assessment-wide roll-up, when `result_id` omitted, ~300 words):
- Scans across all artifacts for systemic patterns
- Injected: assessment metadata, artifact type/origin/disposition breakdown, landscape recommendations, full BestPractice catalog
- Output: findings grouped by severity (critical → medium) with artifact counts and BP code references

---

## Per-Stage Tool Sets

Defined in `src/services/ai_stage_tool_sets.py`. Each AI stage gets only the MCP tools it needs:

| Stage | MCP Tools Available |
|-------|-------------------|
| `ai_analysis` | `get_customizations`, `get_result_detail`, `update_scan_result`, `query_instance_live`* |
| `observations` | `generate_observations`, `get_result_detail`, `get_customizations`, `query_instance_live`* |
| `grouping` | `create_feature`, `add_result_to_feature`, `feature_grouping_status`, `get_customizations` |
| `ai_refinement` | `feature_detail`, `get_result_detail`, `feature_grouping_status` |
| `recommendations` | `feature_recommendation`, `feature_detail`, `get_customizations` |
| `report` | `assessment_results`, `feature_detail`, `get_customizations` |

\* `query_instance_live` availability governed by `ai_analysis.context_enrichment` property (auto/always/never)

---

## Record Types & Data Model

All models in `src/models.py`.

### Core Assessment Records

| Record | Table | Created By | Purpose |
|--------|-------|-----------|---------|
| `Assessment` | `assessment` | User/MCP | Top-level container (instance, name, type, state, current_stage) |
| `ScanResult` | `scan_result` | Scan executor | Individual artifact + findings (origin, disposition, observations, etc.) |
| `Customization` | `customization` | `customization_sync.py` | Token-efficient mirror of customized ScanResults only |

### Engine Output Records

| Record | Table | Created By | Purpose |
|--------|-------|-----------|---------|
| `StructuralRelationship` | `structural_relationship` | Engine 1 | Parent/child metadata links |
| `CodeReference` | `code_reference` | Engine 2 | Script cross-references |
| `UpdateSetArtifactLink` | `update_set_artifact_link` | Engine 3 | Artifact → UpdateSet provenance |
| `UpdateSetOverlap` | `update_set_overlap` | Engine 3 | Cross-update-set overlap signals |
| `TemporalCluster` | `temporal_cluster` | Engine 4 | Developer activity session windows |
| `TemporalClusterMember` | `temporal_cluster_member` | Engine 4 | Junction: cluster ↔ scan_result |
| `NamingCluster` | `naming_cluster` | Engine 5 | Naming pattern groups |
| `TableColocationSummary` | `table_colocation_summary` | Engine 6 | Same-table artifact groups |

### Feature & Grouping Records

| Record | Table | Created By | Purpose |
|--------|-------|-----------|---------|
| `Feature` | `feature` | Seeding + AI | Logical grouping of customizations |
| `FeatureScanResult` | `feature_scan_result` | Seeding + AI | Membership link with confidence + evidence |
| `FeatureContextArtifact` | `feature_context_artifact` | Seeding | Non-customized reference artifacts (context, not members) |
| `FeatureGroupingRun` | `feature_grouping_run` | Reasoning loop | Iteration state and convergence tracking |
| `FeatureRecommendation` | `feature_recommendation` | AI (Stage 8) | OOTB replacement with product/SKU/plugin info |
| `GeneralRecommendation` | `general_recommendation` | AI (Stages 4, 9) | Assessment-wide findings (landscape, governance, report) |
| `BestPractice` | `best_practice` | Admin/KB | Evaluation checklist items for technical_architect |

### Key Enums

| Enum | Values |
|------|--------|
| `OriginType` | `modified_ootb`, `net_new_customer`, `ootb_untouched`, `unknown`, `unknown_no_history` |
| `ReviewStatus` | `pending_review`, `review_in_progress`, `reviewed` |
| `Disposition` | `remove`, `keep_as_is`, `keep_and_refactor`, `needs_analysis` |
| `Severity` | `critical`, `high`, `medium`, `low`, `info` |
| `FindingCategory` | `customization`, `code_quality`, `security`, `performance`, `upgrade_risk`, `best_practice` |
| `PipelineStage` | `scans`, `engines`, `ai_analysis`, `observations`, `review`, `grouping`, `ai_refinement`, `recommendations`, `report`, `complete` |

---

## Feature Grouping & Convergence

### Seeding (Stage 6)

`seed_feature_groups` builds a weighted graph:
1. Read all engine output tables
2. Create edges between scan_result pairs that share signals
3. Accumulate edge weights by signal type
4. Find connected components via BFS
5. Filter by `min_edge_weight` (default 2.0) and `min_group_size` (default 2)
6. Create `Feature` + `FeatureScanResult` (customized) + `FeatureContextArtifact` (non-customized)

### Iterative Reasoning (Stage 7)

`run_feature_reasoning` executes reasoning passes:

| Pass Type | Action | Modifies Membership? |
|-----------|--------|---------------------|
| `group_refine` | Re-seeds feature groups | Yes |
| `observe` | Read-only analysis pass | No |
| `verify` | Read-only validation pass | No |
| `auto` | Chooses based on current state | Depends |

**Membership snapshot & delta tracking**:
- Priority ranking: `human > ai > engine`
- Then: `is_primary`, `confidence`, `iteration_number`, `created_at`

**Convergence formula**:
```python
delta_ratio = changed_results / total_customized_results
converged = (delta_ratio < membership_delta_threshold)  # default 0.01
            AND (high_confidence_changes == 0)
```

**Stop conditions** (any one triggers stop):
1. Converged (delta_ratio < 1% AND no high-confidence changes)
2. Max iterations reached (default 3)
3. Pass type is `verify` (explicit endpoint)

**Typical**: 2–4 passes to convergence.

**Delta payload example**:
```json
{
  "total_results_considered": 150,
  "changed_results": 1,
  "high_confidence_changes": 0,
  "delta_ratio": 0.00667,
  "changed_result_ids": [45]
}
```

---

## Dispatch Mechanism

**File**: `src/services/claude_code_dispatcher.py`

The `ClaudeCodeDispatcher` manages AI stage execution:

- Spawns `claude -p` CLI process with MCP server config
- Batches artifacts for processing
- Per-batch cost cap via `--max-budget-usd`
- 300-second timeout per batch
- Returns `DispatchResult` with metrics (API calls, tokens, cost)
- Assessment hard limit enforced via `_enforce_assessment_stage_budget()`

**Stage tool sets** defined in `src/services/ai_stage_tool_sets.py` — each stage gets only necessary MCP tools.

**Cost tracking**: `AssessmentRuntimeUsage` table records per-stage spend. When hard limit reached, stage stops with `blocked_cost_limit` error.

---

## Orchestration Roles

For multi-agent orchestrated runs via `.claude/orchestration/roles/`:

| Role | Model | Effort | Purpose |
|------|-------|--------|---------|
| `architect` | opus | high | Technical planning, design reviews |
| `project_manager` | sonnet | medium | Task assignment, delivery coordination |
| `dev` | sonnet/opus | medium/high | Implementation in worktrees |
| `code_reviewer` | sonnet/opus | medium/high | Constrained review (read+bash only) |
| `dev_crosstester` | haiku/sonnet | low/medium | Cross-testing peer code |
| `ui_tester` | sonnet | low | Visual regression, form validation |
| `architect_heartbeat` | opus | medium | One-shot critical findings snapshot |
| `pm_heartbeat` | sonnet | low | One-shot progress gate check |
| `scribe` | haiku | low | Optional progress documentation |

**Tool restrictions**: Reviewer/crosstester limited to read+edit+bash. Reviewer bash allowlist: `git status`, `git diff`, `git log`, `pytest`, `npm test`.

**Config**: `.claude/orchestration/config.md`

---

## Final Deliverables

When the pipeline reaches `complete`, the following records constitute the assessment output:

### Per-Artifact Level
- **`ScanResult`** — Each customized artifact has: `observations` (functional summary — what it does, what it connects to), `ai_observations` (structured JSON), scope flags (`is_out_of_scope`, `is_adjacent`), `review_status=reviewed`
- **`disposition`** field exists but is set by human after stakeholder review, NOT by AI

### Feature Level
- **`Feature`** — Each logical grouping has: `name`, `description`, `ai_summary`, `confidence_score`
- **`Feature.disposition`** and **`Feature.recommendation`** fields exist but are set by human after stakeholder review, NOT by AI
- **`FeatureScanResult`** — Membership links with `confidence`, `evidence_json`, `assignment_source` (engine/ai/human)
- **`FeatureRecommendation`** — OOTB replacement analysis (informational) with `recommendation_type`, `ootb_capability_name`, `product_name`, `sku_or_license`, `requires_plugins`, `fit_confidence`, `rationale`, `evidence`

### Assessment Level
- **`GeneralRecommendation`** (`category="landscape_summary"`) — Customization landscape overview
- **`GeneralRecommendation`** (`category="assessment_report"`) — Full structured report (5 sections)
- **`GeneralRecommendation`** (other categories) — Governance gaps, platform maturity findings, upgrade risks, etc.

### Report Output
The `report_writer` prompt produces a structured report stored as `GeneralRecommendation` with `category="assessment_report"`:
- Executive Summary
- Customization Landscape
- Feature Analysis (with member counts, dispositions, AI summaries, recommendations)
- Technical Findings (systemic issues by severity)
- Recommendations (prioritized action items)

### Output Formats (Claude Code)
When running through Claude Code, output plugins produce polished deliverables:
- **Word (docx)** — Assessment reports, finding summaries, executive briefings
- **Excel (xlsx)** — Artifact inventories, feature matrices, comparison tables
- **PowerPoint (pptx)** — Executive presentations, stakeholder briefings
- **PDF** — Formatted final deliverables

---

## Key File Paths

| Component | Path |
|-----------|------|
| Pipeline config (stages) | `src/server.py` (lines 449–476) |
| Engine implementations | `src/engines/*.py` |
| MCP tool registry | `src/mcp/registry.py` |
| Core MCP tools | `src/mcp/tools/core/` |
| Pipeline MCP tools | `src/mcp/tools/pipeline/` |
| AI prompt templates | `src/mcp/prompts/` |
| Stage tool sets | `src/services/ai_stage_tool_sets.py` |
| Claude Code dispatcher | `src/services/claude_code_dispatcher.py` |
| Customization sync | `src/services/customization_sync.py` |
| Integration properties | `src/services/integration_properties.py` |
| Data models | `src/models.py` |
| Scan rules config | `config/scan_rules.yaml` |
| Orchestration roles | `.claude/orchestration/roles/` |
| Orchestration config | `.claude/orchestration/config.md` |
