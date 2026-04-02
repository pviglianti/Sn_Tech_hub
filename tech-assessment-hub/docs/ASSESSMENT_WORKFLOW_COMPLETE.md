# ServiceNow Technical Assessment Hub — Complete Assessment Workflow

> End-to-end reference covering every stage, engine, AI pass, prompt, property, and
> execution path from assessment creation through final report delivery.

---

## Table of Contents

1. [High-Level Pipeline Overview](#1-high-level-pipeline-overview)
2. [Assessment Creation](#2-assessment-creation)
3. [Stage 1 — Scans](#3-stage-1--scans)
4. [Stage 2 — Engines](#4-stage-2--engines)
5. [Stage 3 — AI Analysis](#5-stage-3--ai-analysis)
6. [Stage 4 — Observations](#6-stage-4--observations)
7. [Stage 5 — Review Gate](#7-stage-5--review-gate)
8. [Stage 6 — Grouping](#8-stage-6--grouping)
9. [Stage 7 — AI Refinement](#9-stage-7--ai-refinement)
10. [Stage 8 — Recommendations](#10-stage-8--recommendations)
11. [Stage 9 — Report](#11-stage-9--report)
12. [Stage 10 — Complete](#12-stage-10--complete)
13. [Properties Reference](#13-properties-reference)
14. [MCP Prompts Reference](#14-mcp-prompts-reference)
15. [Per-Stage Tool Sets](#15-per-stage-tool-sets)
16. [Scan Modes (Full / Delta / Rebuild)](#16-scan-modes)
17. [Assessment Type Branching](#17-assessment-type-branching)
18. [ASCII Pipeline Diagram](#18-ascii-pipeline-diagram)

---

## 1. High-Level Pipeline Overview

The assessment pipeline is a **10-stage, manually-advanced** workflow. Every stage
transition requires an explicit user action via the `POST /api/assessments/{id}/advance-pipeline`
endpoint — there is no automatic chaining (`_PIPELINE_STAGE_AUTONEXT` is empty).

```
┌──────────┐   ┌─────────┐   ┌────────────┐   ┌──────────────┐   ┌────────┐
│  SCANS   │──▶│ ENGINES │──▶│ AI ANALYSIS│──▶│ OBSERVATIONS │──▶│ REVIEW │
└──────────┘   └─────────┘   └────────────┘   └──────────────┘   └────────┘
                                                                      │
     ┌────────────────────────────────────────────────────────────────┘
     ▼
┌──────────┐   ┌───────────────┐   ┌─────────────────┐   ┌────────┐   ┌──────────┐
│ GROUPING │──▶│ AI REFINEMENT │──▶│ RECOMMENDATIONS │──▶│ REPORT │──▶│ COMPLETE │
└──────────┘   └───────────────┘   └─────────────────┘   └────────┘   └──────────┘
```

**Stage nature:**

| # | Stage | Nature | Execution |
|---|-------|--------|-----------|
| 1 | `scans` | Deterministic | Background thread (`_AssessmentScanJob`) |
| 2 | `engines` | Deterministic | Background thread (`_AssessmentPipelineJob`) |
| 3 | `ai_analysis` | AI-driven | CLI subprocess dispatch per artifact |
| 4 | `observations` | Deterministic | In-process handler, no LLM |
| 5 | `review` | Human gate | No computation — blocks until reviewed |
| 6 | `grouping` | AI-driven | CLI subprocess dispatch (multi-pass) |
| 7 | `ai_refinement` | AI-driven | CLI subprocess + server-side enrichment |
| 8 | `recommendations` | AI-driven | CLI subprocess dispatch |
| 9 | `report` | Deterministic + AI | Data assembly + optional prompt injection |
| 10 | `complete` | Terminal | Sets `state = completed` |

**Key files:**
- Pipeline stage constants: `src/server.py:464–491`
- Stage execution router: `src/server.py:1644` (`_run_assessment_pipeline_stage`)
- Job tracking: `_AssessmentScanJob` (line 403), `_AssessmentPipelineJob` (line 444)

---

## 2. Assessment Creation

**Route:** `POST /assessments/add` (`src/server.py:8561`)

When a user creates a new assessment, they configure these inputs:

### 2.1 Required Inputs

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Assessment display name |
| `instance_id` | FK | Target ServiceNow instance |
| `assessment_type` | enum | Determines scan strategy (see §17) |

### 2.2 Assessment Types

```python
class AssessmentType(str, Enum):
    global_app       = "global_app"        # Pick from known ITSM apps
    table            = "table"             # Pick one or more SN tables
    plugin           = "plugin"            # Pick plugins/packages
    platform_global  = "platform_global"   # Platform-wide configs
    scoped_app       = "scoped_app"        # Future use
```

### 2.3 Type-Specific Target Fields

| Assessment Type | Target Field | Example |
|-----------------|-------------|---------|
| `global_app` | `target_app_id` → FK to `GlobalApp` | Incident, Change, CMDB |
| `table` | `target_tables_json` → JSON array | `["incident", "task"]` |
| `plugin` | `target_plugins_json` → JSON array | `["com.snc.change_management"]` |
| `platform_global` | *(none — platform-wide)* | — |

### 2.4 Scope & File Class Options

| Field | Values | Default | Effect |
|-------|--------|---------|--------|
| `scope_filter` | `global`, `scoped`, `all` | `global` | Filters artifacts by scope type |
| `app_file_classes_json` | JSON array of class names | *(all)* | Restricts which artifact types to scan |

Available file classes: `sys_script`, `sys_script_include`, `sys_script_client`, `sys_ui_policy`,
`sys_ui_policy_action`, `sys_data_policy2`, `wf_workflow`, `sys_report`, `sys_dictionary`,
`sys_choice`, `sp_widget`, `sp_page`, `sys_ui_action`

### 2.5 Initial State

On creation, the assessment is initialized as:
- `state = pending`
- `pipeline_stage = scans`
- `number` = auto-assigned (`ASMT0000001`, `ASMT0000002`, …)

The user must then click **Start** (`POST /assessments/{id}/start`) to change `state` to
`in_progress`, after which scans can be launched.

---

## 3. Stage 1 — Scans

**Pipeline stage:** `scans`
**Trigger:** `POST /assessments/{id}/run-scans` (or `refresh-scans`, `rebuild-scans`)
**Execution:** Background thread via `_AssessmentScanJob`

The scan stage is itself a multi-phase sub-workflow tracked by internal scan stages.

### 3.1 Scan Sub-Workflow

```
┌─────────┐   ┌──────────────────────┐   ┌──────────────────────────────┐
│ QUEUED  │──▶│ VALIDATING INSTANCE  │──▶│ PREFLIGHT: REQUIRED SYNC     │
└─────────┘   └──────────────────────┘   └──────────────────────────────┘
                                                       │
              ┌────────────────────────────────────────┘
              ▼
┌──────────────────┐   ┌─────────────────────────────────┐
│  RUNNING SCANS   │──▶│ POSTFLIGHT: ARTIFACT DETAIL PULL │
└──────────────────┘   └─────────────────────────────────┘
                                       │
              ┌────────────────────────┘
              ▼
┌──────────────────────────────────┐   ┌─────────────────────┐
│ WAITING FOR CONCURRENT PREFLIGHT │──▶│ VERSION HISTORY      │
│  (VH + Customer Update XML)      │   │ CATCH-UP             │
└──────────────────────────────────┘   └─────────────────────┘
                                                  │
              ┌───────────────────────────────────┘
              ▼
┌──────────────────────┐   ┌───────────┐
│ CLASSIFYING RESULTS  │──▶│ COMPLETED │
└──────────────────────┘   └───────────┘
```

### 3.2 Preflight Data Sync

Before scans can run, the system synchronizes required data types from the ServiceNow instance.

**Required types** (`ASSESSMENT_PREFLIGHT_REQUIRED_TYPES`):
1. `metadata_customization`
2. `app_file_types`
3. `version_history`
4. `customer_update_xml`
5. `update_sets`

**Concurrency model:** Some types run in parallel background threads, others run sequentially.
The `preflight.concurrent_types` property controls which types are parallelized
(default: `version_history`, `customer_update_xml`).

**Staleness:** Data is considered stale after `ASSESSMENT_PREFLIGHT_STALE_MINUTES` (default 10,
configurable via `TECH_ASSESSMENT_PREFLIGHT_STALE_MINUTES` env var). Stale data triggers a
re-pull; fresh data is reused.

**Wait timeout:** `ASSESSMENT_PREFLIGHT_WAIT_SECONDS` = 900 seconds (15 minutes).

### 3.3 Scan Execution

Scans are created by `scan_executor.py:create_scans_for_assessment()`, which reads
`scan_rules.yaml` to determine which scan kinds to run based on assessment type.

**Default scan kind:** `metadata_index` (queries `sys_metadata`)

**Scan query building:** `query_builder.py:resolve_assessment_drivers()` builds driver
dictionaries per assessment type:
- `global_app` → reads `GlobalApp.core_tables_json` + `global_app_overrides` from YAML
- `table` → uses `assessment.target_tables_json`
- `plugin` → uses `assessment.target_plugins_json`
- `platform_global` → empty drivers (broadest scope)

**Origin classification** (`classify_scan_results()`): Each `ScanResult` is classified by
origin type:

| Origin Type | Meaning |
|-------------|---------|
| `ootb` | Out-of-the-box, unmodified |
| `modified_ootb` | OOTB artifact with customer modifications |
| `net_new_customer` | Entirely customer-created |
| `skipped` | Excluded by filter rules |

### 3.4 Postflight: Artifact Detail Pull

After scans complete, `pull_artifact_details_for_assessment()` fetches detailed artifact
content (script bodies, conditions, etc.) from ServiceNow into local artifact detail tables.
This runs as a separate `JobRun` with `module="postflight"`. **Non-fatal** — failure is logged
but does not abort the scan workflow.

### 3.5 Properties Affecting Scans

| Property | Default | Effect |
|----------|---------|--------|
| `integration.fetch.default_batch_size` | 200 | Records per API call to SN |
| `integration.fetch.inter_batch_delay` | 0.5s | Delay between batches |
| `integration.fetch.request_timeout` | 60s | Per-request timeout |
| `integration.fetch.max_batches` | 5000 | Safety cap on batch iterations |
| `integration.pull.order_desc` | true | Newest-first pull ordering |
| `integration.pull.max_records` | 5000 | Max records per table pull |
| `integration.pull.bail_unchanged_run` | 50 | Re-pull bail-out threshold |
| `preflight.concurrent_types` | `version_history, customer_update_xml` | Which preflight types run in parallel |

---

## 4. Stage 2 — Engines

**Pipeline stage:** `engines`
**Trigger:** Advance pipeline to `engines` stage
**Execution:** Background thread; calls `run_preprocessing_engines_handle()`

Seven deterministic preprocessing engines run in a fixed order across three phases.
All engines follow the same contract: `run(assessment_id, session) -> Dict[str, Any]`.

### 4.1 Engine Execution Order

```
╔══════════════════════════════════════════════════════════════════╗
║  PHASE 1 (Foundation — no dependencies)                         ║
║  ┌─────────────────────┐  ┌───────────────────────┐            ║
║  │ structural_mapper   │  │ code_reference_parser  │            ║
║  │ Parent/child rels   │  │ Cross-references in    │            ║
║  │ from known patterns │  │ script/code fields     │            ║
║  └─────────┬───────────┘  └───────────┬───────────┘            ║
╠════════════╪══════════════════════════╪══════════════════════════╣
║  PHASE 2 (Independent signal generators)                        ║
║  ┌──────────────────┐ ┌──────────────────┐ ┌────────────────┐  ║
║  │ update_set_       │ │ temporal_        │ │ naming_        │  ║
║  │ analyzer          │ │ clusterer        │ │ analyzer       │  ║
║  │ US overlap &      │ │ Time-proximity   │ │ Prefix-based   │  ║
║  │ artifact links    │ │ developer groups │ │ clusters       │  ║
║  └──────────────────┘ └──────────────────┘ └────────────────┘  ║
║  ┌──────────────────┐                                           ║
║  │ table_colocation │                                           ║
║  │ Same-table        │                                           ║
║  │ artifact groups   │                                           ║
║  └──────────────────┘                                           ║
╠══════════════════════════════════════════════════════════════════╣
║  PHASE 3 (Depends on Phase 1 outputs)                           ║
║  ┌──────────────────────────────────────────────────────┐       ║
║  │ dependency_mapper                                     │       ║
║  │ Full dependency graph, transitive chains, clusters,   │       ║
║  │ risk scoring, feature risk propagation                │       ║
║  └──────────────────────────────────────────────────────┘       ║
╚══════════════════════════════════════════════════════════════════╝
```

### 4.2 Engine 1: Structural Mapper

**File:** `src/engines/structural_mapper.py`
**Purpose:** Maps explicit parent→child structural relationships using known reference field
patterns.

**Relationship mappings:**

| Child Table | Parent Table | Reference Field | Relationship Type |
|-------------|-------------|-----------------|-------------------|
| `sys_ui_policy_action` | `sys_ui_policy` | `ui_policy` (sys_id) | `ui_policy_action` |
| `sys_dictionary` | `sys_db_object` | `collection_name` (table) | `dictionary_entry` |
| `sys_dictionary_override` | `sys_dictionary` | `collection_name` (table) | `dictionary_override` |

**Output:** `structural_relationship` table rows (parent/child `ScanResult` IDs, type, confidence=1.0)
**Config:** None — hard-coded mappings.
**Idempotent:** Deletes existing rows before re-running.

### 4.3 Engine 2: Code Reference Parser

**File:** `src/engines/code_reference_parser.py`
**Purpose:** Regex-based extraction of cross-references from script/code fields in artifact
detail tables.

**Reference types detected:**

| Pattern | Reference Type | Example |
|---------|---------------|---------|
| `new ClassName(` | `script_include` | `new IncidentUtils()` |
| `GlideRecord('table')` | `table_query` | `new GlideRecord('incident')` |
| `gs.include('name')` | `script_include` | `gs.include('SLAUtils')` |
| `gs.eventQueue('name')` | `event` | `gs.eventQueue('incident.created')` |
| `new GlideAjax('name')` | `script_include` | `new GlideAjax('AjaxHelper')` |
| `new RESTMessageV2('name')` | `rest_message` | `new RESTMessageV2('Outbound')` |
| `workflow.start('name')` | `workflow` | `workflow.startFlow('approval')` |
| `$sp.getWidget('name')` | `sp_widget` | `$sp.getWidget('my-widget')` |
| 32-char hex literal | `sys_id_reference` | `'a1b2c3d4...'` |
| `g_form.method('field')` | `field_reference` | `g_form.setValue('state')` |
| `current.field` | `field_reference` | `current.assignment_group` |

**Output:** `code_reference` table rows (source/target IDs, type, line number, snippet, confidence=1.0)
**Resolution:** Attempts to match `target_identifier` to a `ScanResult` within the same assessment.
**Config:** None.

### 4.4 Engine 3: Update Set Analyzer

**File:** `src/engines/update_set_analyzer.py`
**Purpose:** The most complex engine. Builds provenance links between artifacts and update sets
from three sources, then emits five types of pairwise overlap signals.

**Artifact link sources:**

| Source | Confidence | Mechanism |
|--------|-----------|-----------|
| `scan_result_current` | 1.0 | Direct `ScanResult.update_set_id` field |
| `customer_update_xml` | 1.0 | Match by `target_sys_id` or `name` |
| `version_history` | 0.9 | Match by `sys_update_name` + `sys_update_set` |

**Overlap signal types:**

| Signal | Basis | Score Formula |
|--------|-------|---------------|
| `content` | Shared scan result members | `\|shared\| / min(\|A\|, \|B\|)` |
| `name_similarity` | Shared ticket IDs/tokens | `0.4 + 0.1*tokens + 0.2*tickets` (cap 1.0) |
| `version_history` | VH-derived shared links | Same as content |
| `temporal_sequence` | Close timestamps | `0.5 + 0.5 * proximity_score` |
| `author_sequence` | Same author, close time | `0.65 - (gap/threshold) * 0.25` |

**Modes:**
- `base` (default) — standard overlap scoring
- `enriched` — blends 75% base + 25% per-update-set coherence scores (from AI summaries, table distribution, developer consistency, internal code/structural density)

**Output:** `update_set_artifact_link` + `update_set_overlap` table rows.

**Properties:**

| Property | Default | Effect |
|----------|---------|--------|
| `reasoning.us.min_shared_records` | 1 | Min shared artifacts for content overlap |
| `reasoning.us.name_similarity_min_tokens` | 2 | Min shared name tokens |
| `reasoning.us.include_default_sets` | true | Include "Default" update sets |
| `reasoning.us.default_signal_weight` | 0.3 | Score multiplier for default sets |

### 4.5 Engine 4: Temporal Clusterer

**File:** `src/engines/temporal_clusterer.py`
**Purpose:** Groups artifacts by developer + temporal proximity. Same developer + within gap
threshold = same work session cluster.

**Algorithm:** Sort by `sys_updated_on` per developer, split on gaps > threshold.

**Output:** `temporal_cluster` + `temporal_cluster_member` table rows.

**Properties:**

| Property | Default | Effect |
|----------|---------|--------|
| `reasoning.temporal.gap_threshold_minutes` | 60 | Max gap to stay in same cluster |
| `reasoning.temporal.min_cluster_size` | 2 | Min members to emit |

### 4.6 Engine 5: Naming Analyzer

**File:** `src/engines/naming_analyzer.py`
**Purpose:** Groups artifacts sharing common naming prefixes (e.g., `INC_`, `Incident Notification`).

**Algorithm:** Tokenize names on `[\s\-_\.]+`, generate all prefix lengths ≥ min tokens,
group by prefix tuple, deduplicate via longest-prefix-wins.

**Output:** `naming_cluster` table rows.

**Properties:**

| Property | Default | Effect |
|----------|---------|--------|
| `reasoning.naming.min_cluster_size` | 2 | Min members to emit |
| `reasoning.naming.min_prefix_tokens` | 2 | Min token length for prefix |

### 4.7 Engine 6: Table Co-location

**File:** `src/engines/table_colocation.py`
**Purpose:** Groups artifacts targeting the same ServiceNow table.

**Output:** `table_colocation_summary` rows (target table, member IDs, artifact types, developers).
**Config:** None. Groups with ≥2 members are emitted.

### 4.8 Engine 7: Dependency Mapper (Separate Dependency Graph)

**File:** `src/engines/dependency_mapper.py`
**Graph implementation:** `src/services/dependency_graph.py`
**Purpose:** Highest-level synthesis engine. Builds an **entirely separate graph**
(`DependencyGraph`) from the original feature-seeding graph (`RelationshipGraph`).
Consumes Phase 1 outputs (code references + structural relationships) to construct a
directed dependency graph with transitive chains, circular dependency detection,
connected-component clusters, and risk scoring.

**Depends on:** Must run after `structural_mapper` and `code_reference_parser`.

#### 4.8.1 Two Separate Graphs: Dependency Graph vs. Relationship Graph

The codebase contains two architecturally distinct graph implementations:

| | **Dependency Graph** (new) | **Relationship Graph** (original) |
|---|---|---|
| **File** | `src/services/dependency_graph.py` | `src/services/relationship_graph.py` |
| **Class** | `DependencyGraph` | `RelationshipGraph` |
| **Edge class** | `DependencyEdge` (type, weight, **direction**, **criticality**, shared_via) | `RelationshipEdge` (type, weight, direction) |
| **Signal sources** | 3 (code refs, structural rels, shared deps) | 7 (all engine outputs) |
| **Node tracking** | `all_ids` + `customized_ids` + `_table_names` | `customized_ids` only |
| **Algorithms** | BFS chains, DFS cycle detection, connected-component clustering, risk scoring | None (read-only traversal lookups) |
| **Persisted output** | `DependencyChain` + `DependencyCluster` DB rows | None (in-memory only) |
| **Side effects** | Propagates `change_risk_score` to `Feature` rows | None |
| **Purpose** | Dependency analysis, risk assessment, feeds strongest signal INTO relationship graph | Feature seeding input for `seed_feature_groups` |
| **Direction naming** | `outbound` / `inbound` / `bidirectional` | `outgoing` / `incoming` / `bidirectional` |

The dependency graph's persisted `DependencyCluster` output feeds **back into** the
relationship graph as the highest-weight deterministic signal (3.5) during feature grouping.
They are separate data structures serving complementary purposes.

#### 4.8.2 Dependency Graph Construction

`build_dependency_graph()` (`dependency_graph.py`) runs four sequential passes:

1. **Node registration** — All `ScanResult` rows loaded. All added to `all_ids` and
   `_table_names`. Only `modified_ootb` / `net_new_customer` go into `customized_ids`.
2. **Code reference edges** — `CodeReference` rows with resolved targets become `outbound`
   edges (weight 3.0). Each edge auto-creates the reverse `inbound` edge on the target.
   Tracks customized→non-customized pairs for shared dependency detection.
3. **Shared dependency edges** (unique to this graph) — When 2+ customized artifacts both
   reference the same non-customized target, a `bidirectional` edge typed `shared_dependency`
   (weight 2.0) is created between them, with `shared_via` set to the common identifier.
   This edge type has no equivalent in the relationship graph.
4. **Structural relationship edges** — `StructuralRelationship` rows become `bidirectional`
   edges typed `structural` (weight 2.5). Each edge carries a `criticality` rating
   (`high`/`medium`/`low`) based on relationship type.

**Edge criticality** (unique to this graph — the relationship graph has no criticality):
- Code refs: `script_include` → high; `table_query`/`event`/`rest_message` → medium; else low
- Structural: `ui_policy_action`/`dictionary_entry` → high; `dictionary_override` → low; else medium

#### 4.8.3 Dependency Graph Algorithms

**Transitive chain resolution** (`resolve_transitive_chains`):
BFS from each customized node following `outbound` edges to other customized nodes.
Hop 1 preserves original type (weight 3.0), hop 2 becomes `transitive` (weight 2.0),
hop 3 becomes `transitive` (weight 1.0). Max depth configurable (default 3).

**Circular dependency detection** (`detect_circular_dependencies`):
Classic DFS three-color (WHITE/GRAY/BLACK) algorithm on the customized subgraph.
Detects back-edges during DFS to extract cycle paths.

**Connected-component clustering** (`compute_clusters`):
BFS on undirected view of customized nodes. For each component computes:
- `coupling_score` — average sum of edge weights per member
- `impact_radius` — `(outbound_ext * 2) + (inbound_ext * 3) + structural_children`,
  thresholds at 10/25/50
- `change_risk_score` — `coupling*10 + circular_count*15 + high_crit_edges*20 + member_count*2 + avg_type_risk`, capped at 100
- `change_risk_level` — critical ≥70, high ≥50, medium ≥30, else low
- Auto-label from most common `table_name` among members

**Risk propagation to features** (`_propagate_risk_to_features`):
For each `Feature`, finds max `change_risk_score` across its linked scan results' cluster
memberships and writes back to `Feature.change_risk_score` / `Feature.change_risk_level`.
Uses max-wins: highest cluster risk of any member artifact.

#### 4.8.4 Artifact Type Risk Weights

| Type | Weight |
|------|--------|
| `sys_security_acl` | 15 |
| `sys_db_object` | 10 |
| `wf_workflow` | 8 |
| `sys_script`, `sys_script_include` | 6 |
| `sys_ui_policy`, `sys_script_client` | 4 |
| `sys_dictionary` | 3 |
| All others | 3 |

#### 4.8.5 Persisted Output

| Table | Key Fields |
|-------|-----------|
| `dependency_chain` | source/target scan_result_id, dependency_type, direction, hop_count, chain_path_json, chain_weight, criticality |
| `dependency_cluster` | cluster_label, member_ids_json, member_count, internal_edge_count, coupling_score, impact_radius, change_risk_score, change_risk_level, circular_dependencies_json, tables_involved_json |

**Properties:**

| Property | Default | Effect |
|----------|---------|--------|
| `reasoning.dependency.max_transitive_depth` | 3 | Max BFS hops for chain resolution |
| `reasoning.dependency.min_cluster_size` | 2 | Min members per cluster |

### 4.9 How Engine Outputs Feed Downstream (Two-Graph Architecture)

Engine outputs flow through **two separate graphs** that work in tandem:

```
  Engines 1-6 produce signal tables
         │
         ├── dependency_mapper (Engine 7) consumes Phase 1 outputs
         │       │
         │       └── builds DependencyGraph (NEW, separate)
         │           ├── resolve_transitive_chains() → DependencyChain rows
         │           ├── compute_clusters() → DependencyCluster rows
         │           └── propagate_risk_to_features() → Feature.change_risk_*
         │
         └── seed_feature_groups consumes ALL engine outputs
                 │
                 └── builds RelationshipGraph (ORIGINAL)
                     ├── 7 signal sources (including DependencyCluster at weight 3.5)
                     └── used for feature seeding + DFS traversal
```

**Relationship Graph edge weights** (used in feature grouping):

| Signal Source | Edge Weight | Origin |
|---------------|-------------|--------|
| `dependency_cluster` | **3.5** | DependencyGraph output (highest deterministic) |
| `ai_relationship` | **3.5** | AI-derived (highest AI) |
| `update_set_overlap` | **3.0** | Update Set Analyzer |
| `code_reference` | **3.0** | Code Reference Parser |
| `structural_relationship` | **2.5** | Structural Mapper |
| `update_set_artifact_link` | **2.5** | Update Set Analyzer |
| `naming_cluster` | **2.0** | Naming Analyzer |
| `temporal_cluster` | **1.8** | Temporal Clusterer |
| `table_colocation` | **1.2** | Table Co-location (weakest) |

The `dependency_cluster` signal (weight 3.5) is the **strongest deterministic signal** in the
entire feature grouping process — the new dependency graph's cluster output is the
single most influential engine contribution to how features are formed.

---

## 5. Stage 3 — AI Analysis

**Pipeline stage:** `ai_analysis`
**Trigger:** Advance pipeline to `ai_analysis`
**Execution:** CLI subprocess dispatch per artifact (or per batch)
**Handler:** `run_ai_analysis_dispatch()` in `src/services/ai_analysis_dispatch.py`
**Orchestration:** `src/server.py:1709`

### 5.1 Pre-Flight Checks

Before any AI stage runs, two checks execute:
1. **Budget enforcement** (`_enforce_assessment_stage_budget()`): If `ai.budget.stop_on_hard_limit=true`
   and the per-assessment hard limit is hit, a `RuntimeError` is raised.
2. **LLM preflight** (`DispatcherRouter.preflight_check()`): Validates the configured AI provider/model
   is reachable.

### 5.2 Execution Modes

The AI analysis stage has three execution paths:

```
                    ┌─────────────────────────┐
                    │  ai.runtime.mode check  │
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌───────────┐  ┌──────────┐
        │ disabled │  │ connected │  │ api_key  │
        │ (skip)   │  │ (CLI)     │  │ (server) │
        └──────────┘  └─────┬─────┘  └────┬─────┘
                            │              │
                            ▼              ▼
                     ┌──────────────────────────┐
                     │  Per-artifact dispatch    │
                     │  (batch_size, default=1)  │
                     └──────────────────────────┘
```

When `ai.runtime.mode = "disabled"`, the entire AI analysis stage is skipped.

### 5.3 Per-Artifact Processing

For each customized artifact (`modified_ootb` or `net_new_customer`), ordered by ID:

1. **Build stage instructions** (`_build_artifact_stage_instructions()`):
   - Assessment scope context (target app, tables, keywords, file classes)
   - If `pipeline.use_registered_prompts=true`:
     - `tech_assessment_expert` prompt (full methodology reference)
     - `artifact_analyzer` prompt (dynamic — DB context: code snippet, structural rels, update set links)
   - `_AI_ANALYSIS_FALLBACK_GUIDANCE` (inline scope triage + `update_scan_result` schema)

2. **Wrap with batch template** (`build_batch_prompt()` from `ai_stage_tool_sets.py`):
   - Injects `stage_instructions`, `assessment_id`, batch position, artifact list

3. **Dispatch to CLI** with stage-restricted tool set (see §15.1)

4. **Validate output**: Server verifies the artifact now has `review_status=review_in_progress`
   and a non-empty observation. Raises and aborts if not.

5. **Merge dispatch trace** into `ScanResult.ai_observations` with provider/model metadata

### 5.4 Expected AI Output Per Artifact

The AI calls `update_scan_result` with:

| Field | Value |
|-------|-------|
| `review_status` | `"review_in_progress"` (never `"reviewed"`) |
| `observations` | 2-5 sentence functional description |
| `is_adjacent` | `true` if indirectly related |
| `is_out_of_scope` | `true` if not related to assessment target |
| `ai_observations` | JSON: `{ "analysis_stage", "scope_decision", "scope_rationale", "directly_related_result_ids", "directly_related_artifacts" }` |

### 5.5 Context Enrichment Options

The `ai_analysis.context_enrichment` property controls live SN queries:

| Value | Behavior |
|-------|----------|
| `auto` | Query SN only when local context is insufficient |
| `always` | Always query SN for additional context per artifact |
| `never` | No live SN queries — local data only |

### 5.6 Depth-First Traversal (Legacy)

When `ai_analysis.enable_depth_first=true` AND a relationship graph exists, artifacts are
traversed in dependency order rather than by ID. Controlled by:

| Property | Default | Effect |
|----------|---------|--------|
| `ai_analysis.max_rabbit_hole_depth` | 10 | Max depth of graph traversal |
| `ai_analysis.max_neighbors_per_hop` | 20 | Breadth limit per hop |
| `ai_analysis.min_edge_weight_for_traversal` | 2.0 | Minimum edge weight to follow |

### 5.7 Resume Support

If interrupted, the stage resumes from `phase_progress.resume_from_index`, skipping already-
processed artifacts.

---

## 6. Stage 4 — Observations

**Pipeline stage:** `observations`
**Trigger:** Advance pipeline to `observations`
**Execution:** In-process handler (no CLI subprocess, no LLM)
**Handler:** `generate_observations_handle()` in `src/mcp/tools/pipeline/generate_observations.py`

### 6.1 What It Does

This is a **deterministic** baseline generator — no AI model is invoked. For each in-scope
customized artifact:

1. Count update set links → get primary update set name
2. Count structural relationship signals (parent/child)
3. Optionally run `get_usage_count` live SN queries (governed by `observations.include_usage_queries`)
4. Format a plain-English observation sentence
5. Write to `ScanResult.observations` **only if empty** (preserves existing AI/human text)
6. Write structured `deterministic_observation_baseline` into `ai_observations` JSON
7. Advance `review_status` from `pending_review` to `review_in_progress`
8. Increment `ai_pass_count`
9. Upsert a `landscape_summary` `GeneralRecommendation` with aggregate counts

### 6.2 Observation Format

```
This {origin} artifact {name} ({table}) is treated as customized and included
in feature-grouping analysis. It has {N} linked update-set signal(s); primary
context is {US name}. Structural analysis found {N} related parent/child signal(s)...
```

### 6.3 Usage Query Governance

| `observations.include_usage_queries` | Behavior |
|--------------------------------------|----------|
| `auto` (default) | Run usage queries only when references detected and not cached |
| `always` | Force usage queries for every artifact |
| `never` | Skip all usage queries |

### 6.4 Properties

| Property | Default | Effect |
|----------|---------|--------|
| `observations.batch_size` | 10 | Processing batch size |
| `observations.include_usage_queries` | `auto` | See above |
| `observations.max_usage_queries_per_result` | 2 | Cap per artifact |
| `observations.usage_lookback_months` | 6 | Time window for usage counts |

---

## 7. Stage 5 — Review Gate

**Pipeline stage:** `review`
**Trigger:** Advance pipeline to `review`
**Execution:** No heavy computation — pure gate check

### 7.1 Gate Logic

```
┌──────────────────────────────────────┐
│  _assessment_review_gate_summary()   │
│                                      │
│  Counts ScanResult.review_status     │
│  for all customized results:         │
│    reviewed: N                       │
│    pending: N                        │
│    in_progress: N                    │
│                                      │
│  all_reviewed = (reviewed ≥ total)   │
└──────────────┬───────────────────────┘
               │
       ┌───────┴───────┐
       │               │
       ▼               ▼
  all_reviewed     NOT all_reviewed
  = true           = false
       │               │
       ▼               ▼
  ┌─────────┐    ┌─────────────────┐
  │ PASS    │    │ skip_review?    │
  │ (gate   │    │                 │
  │ opens)  │    │  true → bulk    │
  └─────────┘    │    mark all as  │
                 │    "reviewed"   │
                 │                 │
                 │  false → BLOCK  │
                 │    (error 400)  │
                 └─────────────────┘
```

### 7.2 How Artifacts Get Reviewed

- **AI Analysis stage:** Marks artifacts `review_in_progress` (never `reviewed`)
- **Observations stage:** Also marks artifacts `review_in_progress`
- **Human reviewers:** Use the web UI to manually mark individual artifacts as `reviewed`
- **Skip review bypass:** `skip_review=true` on the advance-pipeline call bulk-marks all remaining

### 7.3 Secondary Gate at Grouping Advance

Even after passing the review stage, a secondary check fires when advancing to `grouping`:
if `all_reviewed` is still false and `skip_review` is not set, the API returns 400.

---

## 8. Stage 6 — Grouping

**Pipeline stage:** `grouping`
**Trigger:** Advance pipeline to `grouping` (requires review gate satisfied)
**Execution:** CLI subprocess dispatch (multi-pass)
**Handler:** `run_ai_feature_stage_dispatch()` in `src/services/ai_feature_dispatch.py`
**Orchestration:** `src/server.py:2106`

### 8.1 Pre-Processing

Before AI dispatch, `_reset_ai_feature_graph()` runs:
- Deletes all non-human feature memberships
- Deletes context artifacts and feature recommendations
- Deletes features with no human-locked names or human memberships

### 8.2 Pass Plan

The grouping stage reads `ai.feature.pass_plan_json` and filters to entries with
`stage == "grouping"`. Default plan:

| Pass # | Key | Label | Instructions |
|--------|-----|-------|-------------|
| 1 | `structure` | Structure | Create obvious solution features, use provisional names, set `feature_kind`, `name_status="provisional"` |
| 2 | `coverage` | Coverage | Find every remaining unassigned artifact, place into solution features or bucket features from taxonomy |

Each pass can carry optional `provider`, `model`, and `effort` overrides for staged
multi-LLM execution.

### 8.3 Bucket Taxonomy

The `ai.feature.bucket_taxonomy_json` property defines available bucket categories for
artifacts that don't fit into solution features:

Default buckets: `form_fields`, `acl`, `notifications`, `scheduled_jobs`,
`integration_artifacts`, `data_policies_validations`

### 8.4 Per-Pass Execution

For each pass:
1. Build feature stage prompt with:
   - Assessment scope context
   - Bucket taxonomy text
   - Current feature coverage stats
   - Optionally `tech_assessment_expert` registered prompt text
   - Pass-specific instructions
2. Dispatch to CLI with grouping tool set (see §15.4)
3. After completion, run `refresh_feature_metadata()` to recalculate computed fields

### 8.5 Post-Pass Validation

After all passes complete, the system validates that **zero unassigned artifacts remain**.
If any remain, an error is raised and the stage fails.

A `FeatureGroupingRun` tracking record is created for audit purposes.

### 8.6 Deterministic Seeding (Alternative Path)

The `seed_feature_groups` tool can also run deterministically (without AI), using the
weighted signal graph from all engine outputs. This creates initial feature groups based
purely on engine signals, which the AI passes then refine.

---

## 9. Stage 7 — AI Refinement

**Pipeline stage:** `ai_refinement`
**Trigger:** Advance pipeline to `ai_refinement`
**Execution:** CLI subprocess dispatch + server-side enrichment
**Handler:** `run_ai_feature_stage_dispatch()` with `stage="ai_refinement"`
**Orchestration:** `src/server.py:2178`

### 9.1 AI Passes

Default pass plan entries for `ai_refinement`:

| Pass # | Key | Label | Instructions |
|--------|-----|-------|-------------|
| 1 | `refine` | Refine | Merge features covering same solution; split unrelated bundles; move artifacts from bucket → solution features |
| 2 | `final_name` | Final Naming | Rename all provisional features with solution-based names (e.g., `Pharmacy Incident Solution`). No provisional names should remain. |

### 9.2 Server-Side Enrichment (Post-AI Passes)

After CLI passes complete, the server performs additional enrichment **without another CLI dispatch**:

#### Complex Feature Summaries
For features with **5+ members** that lack `ai_summary`:
- Builds a `summary_payload` with member names, tables, cross-table flags
- If `pipeline.use_registered_prompts=true`: injects `relationship_tracer` prompt context
  (for the first member, direction="both", max_depth=3)

#### Per-Artifact Technical Review
For each non-out-of-scope customized artifact lacking `technical_review` in `ai_observations`:
- Injects a `technical_review` struct with feature memberships
- If `pipeline.use_registered_prompts=true`: injects `technical_architect` **Mode A** prompt
  context (artifact metadata, code snippet up to 200 lines, best practice checklist for the
  artifact's table type)

#### Assessment-Wide Technical Findings Rollup
- Deletes existing `technical_findings` `GeneralRecommendation` rows
- Creates a new one with `mode_b_assessment_wide` rollup payload
- If `pipeline.use_registered_prompts=true`: injects `technical_architect` **Mode B** prompt
  context (aggregate summary, full best practice catalog)

### 9.3 Post-Refinement Validation

Requires **zero unassigned artifacts** AND **zero provisional features** after completion.

---

## 10. Stage 8 — Recommendations

**Pipeline stage:** `recommendations`
**Trigger:** Advance pipeline to `recommendations`
**Execution:** CLI subprocess dispatch
**Handler:** `run_ai_feature_stage_dispatch()` with `stage="recommendations"`
**Orchestration:** `src/server.py:2387`

### 10.1 Pre-Flight Blocking

The stage **blocks** if:
- Any unassigned in-scope customized artifacts remain (`unassigned_count > 0`)
- Any provisional features remain (`provisional_feature_count > 0`)

### 10.2 Setup

Before running, all existing `FeatureRecommendation` rows are deleted (clean slate).

### 10.3 AI Task

The AI reviews the finalized feature graph and, for each feature, calls
`upsert_feature_recommendation` with:

| Field | Type | Description |
|-------|------|-------------|
| `recommendation_type` | enum | `replace` / `refactor` / `keep` / `remove` |
| `ootb_capability_name` | string | Name of the OOTB capability that could replace it |
| `product_name` | string | ServiceNow product (e.g., "ITSM", "CSM") |
| `sku_or_license` | string | Required license/SKU |
| `requires_plugins` | JSON | List of required plugins |
| `fit_confidence` | float | Confidence in the recommendation (0.0–1.0) |
| `rationale` | string | Why this recommendation |
| `evidence` | JSON | Supporting evidence |

### 10.4 Advance Guards

The same blocking checks also fire when trying to advance **from** `recommendations` to
`report` without `manual_override=true`.

---

## 11. Stage 9 — Report

**Pipeline stage:** `report`
**Trigger:** Advance pipeline to `report`
**Execution:** Deterministic data assembly + optional AI narrative
**Orchestration:** `src/server.py:2494`

### 11.1 Pre-Flight Blocking

Same as recommendations — blocks if unassigned artifacts or provisional features exist.

### 11.2 Data Assembly (Deterministic — No LLM)

Six-step aggregation:

1. **Statistics**: Total artifacts by table and origin type
2. **Features**: Feature counts by kind/composition/disposition
3. **Recommendations**: Recommendation counts by type
4. **Review status**: Distribution of review statuses
5. **Build dict**: Assembled into `report_data` structure
6. **Store**: Persisted as `GeneralRecommendation` with `category="assessment_report"`

### 11.3 AI Narrative (Optional)

If `pipeline.use_registered_prompts=true`, the `report_writer` prompt is injected with the
assembled report data. The AI then produces a formal five-section deliverable:

1. **Executive Summary** — High-level findings and recommendations
2. **Customization Landscape** — Volume, complexity, patterns
3. **Feature Analysis** — Feature-by-feature breakdown
4. **Technical Findings** — Technical debt, risk areas
5. **Recommendations** — Per-feature OOTB replacement recommendations

### 11.4 Report Export

`src/services/report_export.py` generates downloadable exports:
- `.xlsx` (via openpyxl) — structured data tables
- `.docx` (via python-docx) — formatted report document

---

## 12. Stage 10 — Complete

**Pipeline stage:** `complete`
**Trigger:** `POST /assessments/{id}/complete` or advance pipeline to `complete`

Sets `assessment.state = completed` and `pipeline_stage = complete`. Terminal state.

---

## 13. Properties Reference

### 13.1 AI Runtime Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `ai.runtime.mode` | select | `local_subscription` | `disabled` = skip all AI; `local_subscription` = MCP client; `api_key` = server-side |
| `ai.runtime.provider` | select | `openai` | Provider: `openai`, `anthropic`, `google_gemini`, `deepseek`, `openai_compatible_custom` |
| `ai.runtime.model` | string | `gpt-5-mini` | Model identifier |
| `ai.runtime.execution_strategy` | select | `single` | `single`, `concurrent`, `swarm` |
| `ai.runtime.max_concurrent_sessions` | int | 1 | Max parallel CLI sessions |

### 13.2 AI Budget Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `ai.budget.assessment_soft_limit_usd` | float | 10.0 | Soft warning threshold per assessment |
| `ai.budget.assessment_hard_limit_usd` | float | 25.0 | Hard stop per assessment |
| `ai.budget.monthly_hard_limit_usd` | float | 200.0 | Monthly global hard stop |
| `ai.budget.stop_on_hard_limit` | bool | true | Whether to enforce hard limits |
| `ai.budget.max_input_tokens_per_call` | int | 200,000 | Per-call input token cap |
| `ai.budget.max_output_tokens_per_call` | int | 40,000 | Per-call output token cap |

### 13.3 AI Analysis Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `ai_analysis.batch_size` | int | 1 | Artifacts per CLI dispatch |
| `ai_analysis.context_enrichment` | select | `auto` | `auto`/`always`/`never` — live SN query governance |
| `ai_analysis.enable_depth_first_traversal` | bool | true | Use relationship graph traversal ordering |
| `ai_analysis.max_rabbit_hole_depth` | int | 10 | DFS traversal depth limit |
| `ai_analysis.max_neighbors_per_hop` | int | 20 | DFS breadth limit |
| `ai_analysis.min_edge_weight_for_traversal` | float | 2.0 | Minimum edge weight to traverse |

### 13.4 AI Feature Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `ai.feature.pass_plan_json` | JSON | *(4 passes)* | Defines multi-pass execution plan |
| `ai.feature.bucket_taxonomy_json` | JSON | *(6 buckets)* | Bucket categories for leftover artifacts |

**Default pass plan:**

| # | Stage | Pass Key | Label |
|---|-------|----------|-------|
| 1 | `grouping` | `structure` | Structure |
| 2 | `grouping` | `coverage` | Coverage |
| 3 | `ai_refinement` | `refine` | Refine |
| 4 | `ai_refinement` | `final_name` | Final Naming |

### 13.5 Pipeline Prompt Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `pipeline.use_registered_prompts` | bool | **false** | Inject MCP prompts into AI dispatches |

**When `true`**, the following prompts are injected by stage:

| Stage | Prompt(s) Injected |
|-------|--------------------|
| `ai_analysis` | `tech_assessment_expert`, `artifact_analyzer` |
| `grouping` | `tech_assessment_expert` |
| `ai_refinement` | `tech_assessment_expert`, `relationship_tracer`, `technical_architect` (A+B) |
| `recommendations` | `tech_assessment_expert` |
| `report` | `report_writer` |

### 13.6 Observation Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `observations.batch_size` | int | 10 | Processing batch size |
| `observations.include_usage_queries` | select | `auto` | `auto`/`always`/`never` |
| `observations.max_usage_queries_per_result` | int | 2 | Cap per artifact |
| `observations.usage_lookback_months` | int | 6 | Usage query time window |

### 13.7 Reasoning Engine Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `reasoning.us.min_shared_records` | int | 1 | Min shared artifacts for US overlap |
| `reasoning.us.name_similarity_min_tokens` | int | 2 | Min shared name tokens |
| `reasoning.us.include_default_sets` | bool | true | Include "Default" update sets |
| `reasoning.us.default_signal_weight` | float | 0.3 | Score multiplier for default sets |
| `reasoning.temporal.gap_threshold_minutes` | int | 60 | Temporal cluster gap threshold |
| `reasoning.temporal.min_cluster_size` | int | 2 | Temporal cluster min size |
| `reasoning.naming.min_cluster_size` | int | 2 | Naming cluster min size |
| `reasoning.naming.min_prefix_tokens` | int | 2 | Min prefix token length |
| `reasoning.dependency.max_transitive_depth` | int | 3 | Max BFS hops |
| `reasoning.dependency.min_cluster_size` | int | 2 | Min cluster size |
| `reasoning.feature.max_iterations` | int | 3 | Feature reasoning convergence loop |
| `reasoning.feature.membership_delta_threshold` | float | 0.02 | Convergence threshold |
| `reasoning.feature.min_assignment_confidence` | float | 0.6 | Min confidence for assignment |

### 13.8 Integration Fetch Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `integration.fetch.default_batch_size` | int | 200 | Records per SN API call |
| `integration.fetch.inter_batch_delay` | float | 0.5 | Delay between batches (seconds) |
| `integration.fetch.request_timeout` | int | 60 | Per-request timeout (seconds) |
| `integration.fetch.max_batches` | int | 5000 | Safety cap on iterations |
| `integration.pull.order_desc` | bool | true | Newest-first pull ordering |
| `integration.pull.max_records` | int | 5000 | Max records per table |
| `integration.pull.bail_unchanged_run` | int | 50 | Re-pull bail-out threshold |

### 13.9 General Properties

| Property Key | Type | Default | Effect |
|-------------|------|---------|--------|
| `general.display_timezone` | select | `America/New_York` | UI display timezone |
| `preflight.concurrent_types` | multiselect | `version_history, customer_update_xml` | Preflight parallel data types |

---

## 14. MCP Prompts Reference

All prompts are defined in `src/mcp/prompts/` and registered in `PROMPT_REGISTRY`.

### 14.1 `tech_assessment_expert`

**File:** `src/mcp/prompts/tech_assessment.py`
**Args:** `assessment_id` (optional)
**Handler:** Static (no DB query)
**Used in:** `ai_analysis`, `grouping`, `ai_refinement`, `recommendations`

Full 9-section methodology reference:
1. Core philosophy (think functionally, not structurally)
2. Depth-first analysis flow (sort by `sys_updated_on`, follow rabbit holes)
3. Scope categories (`in_scope` / `adjacent` / `out_of_scope`)
4. Signal quality hierarchy
5. Origin classification decision tree
6. Common finding patterns
7. Key artifact types
8. Tool usage guide
9. Token efficiency rules

### 14.2 `tech_assessment_reviewer`

**File:** `src/mcp/prompts/tech_assessment.py`
**Args:** None
**Handler:** Static
**Used in:** Human-initiated review workflows

Lighter review checklist: classification accuracy, scope accuracy, observation quality,
feature coherence, completeness, coverage.

### 14.3 `feature_reasoning_orchestrator`

**File:** `src/mcp/prompts/tech_assessment.py`
**Args:** `assessment_id` (required)
**Handler:** Injects assessment context into static text
**Used in:** Standalone AI client invocations

Full 10-section orchestrator specification — drives the complete feature lifecycle:
`grouping/structure` → `grouping/coverage` → `ai_refinement/refine` → `ai_refinement/final_name`
→ `recommendations`

### 14.4 `artifact_analyzer`

**File:** `src/mcp/prompts/artifact_analyzer.py`
**Args:** `result_id` (required), `assessment_id` (required)
**Handler:** **Dynamic — queries DB** to build per-artifact context:
- Artifact metadata
- Code snippet (up to 150 lines from `raw_data_json`)
- Existing observations and `ai_observations`
- Structural relationships (parent/child)
- Update set links
**Used in:** `ai_analysis` (per-artifact injection)

Covers: scope decision table, functional summary format, type-specific analysis guidance,
expected output format, live query governance, structured `ai_observations` schema.

### 14.5 `relationship_tracer`

**File:** `src/mcp/prompts/relationship_tracer.py`
**Args:** `result_id`, `assessment_id`, `max_depth` (default 3), `direction` (default `outward`)
**Handler:** **Dynamic — queries DB** to build:
- Starting artifact metadata + code snippet (100 lines)
- Structural relationships (filtered by direction)
- Update set siblings (grouped by US name)
- Table-level neighbors (up to 20)
- Naming cluster membership
- Feature context with co-member names
**Used in:** `ai_refinement` (complex features with 5+ members)

Instructs: map dependency graph core cluster → adjacent → distant; recommend grouping
narrative; scope re-evaluation rules.

### 14.6 `technical_architect`

**File:** `src/mcp/prompts/technical_architect.py`
**Args:** `result_id` (optional for Mode A), `assessment_id` (required)
**Handler:** **Dynamic — queries DB** with mode dispatch:

| Mode | Trigger | Context Built |
|------|---------|---------------|
| **A** (per-artifact) | `result_id` provided | Artifact metadata, code (200 lines), observations, US links, `BestPractice` checklist for artifact type |
| **B** (assessment-wide) | No `result_id` | Assessment metadata, aggregate summary, all `GeneralRecommendation` records, full `BestPractice` catalog |

**Mode A output:** Code Quality, Issues Found (with BP codes), Suggested Disposition, Rationale
**Mode B output:** Systemic technical debt patterns grouped by severity (CRITICAL/HIGH/MEDIUM)

**Used in:** `ai_refinement` (Mode A per artifact, Mode B for rollup)

### 14.7 `observation_landscape_reviewer`

**File:** `src/mcp/prompts/observation_prompt.py`
**Args:** `assessment_id`
**Handler:** Injects assessment context
**Used in:** Post-observations enrichment (human-initiated or AI-driven)

Reads the `landscape_summary` `GeneralRecommendation` and writes an enriched 3–6 sentence
summary covering volume/complexity, risk areas, strategic patterns, gaps.

### 14.8 `observation_artifact_reviewer`

**File:** `src/mcp/prompts/observation_prompt.py`
**Args:** `assessment_id`
**Handler:** Injects assessment context
**Used in:** Post-observations enrichment

Enriches existing deterministic observations: reads code for scriptable artifacts, calls out
connections, describes behavior. Batch strategy: 10–20 per batch, scriptable first.

### 14.9 `report_writer`

**File:** `src/mcp/prompts/report_writer.py`
**Args:** `assessment_id`, `sections` (optional), `format` (`full`/`executive_only`/`technical_only`)
**Handler:** **Dynamic — queries DB** to build:
- Assessment metadata and statistics
- Conditional sections: landscape summary, feature groups, technical findings, recommendations
**Used in:** `report` stage

Five-section report structure: Executive Summary, Landscape, Feature Analysis, Technical
Findings, Recommendations. Section filtering via `sections` param or `format` preset.

---

## 15. Per-Stage Tool Sets

Defined in `src/services/ai_stage_tool_sets.py`. Each AI CLI dispatch receives **only** the
tools specific to its stage.

### 15.1 `ai_analysis` Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `get_customizations` | read | Browse customized artifacts |
| `get_result_detail` | read | Full detail (code, VH, raw data) |
| `query_instance_live` | read | Live SN queries (governed by `context_enrichment`) |
| `search_servicenow_docs` | read | SN docs search |
| `fetch_web_document` | read | Web fetch for product context |
| `update_scan_result` | write | Write scope flags, observations, `ai_observations` |

### 15.2 `observations` Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `generate_observations` | write | Deterministic baseline generator |
| `get_result_detail` | read | Artifact detail |
| `get_customizations` | read | Browse artifacts |

### 15.3 `review` Tools

No tools — pure gate check.

### 15.4 `grouping` Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `get_feature_detail` | read | Feature with all members |
| `update_feature` | write | Update feature name/description/disposition |
| `create_feature` | write | Create new feature |
| `add_result_to_feature` | write | Add artifact to feature |
| `remove_result_from_feature` | write | Remove artifact from feature |
| `get_result_detail` | read | Artifact detail |
| `feature_grouping_status` | read | Coverage, blocking reasons |
| `get_customizations` | read | Browse artifacts |
| `get_suggested_groupings` | read | Read-only engine evidence |

### 15.5 `ai_refinement` Tools

Same as `grouping` (§15.4).

### 15.6 `recommendations` Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `upsert_feature_recommendation` | write | Persist per-feature recommendation |
| `get_feature_detail` | read | Inspect feature members |
| `get_customizations` | read | Browse artifacts |
| `feature_grouping_status` | read | Coverage check |

### 15.7 `report` Tools

| Tool | Permission | Purpose |
|------|-----------|---------|
| `get_assessment_results` | read | All assessment results |
| `get_feature_detail` | read | Feature data |
| `get_customizations` | read | Browse artifacts |

---

## 16. Scan Modes

Three scan modes control how an assessment's scan data is refreshed:

| Mode | Route | Pipeline Reset | Behavior |
|------|-------|----------------|----------|
| **Full** | `POST /assessments/{id}/run-scans` | Yes → `scans` | Complete rescan of all targets |
| **Delta** | `POST /assessments/{id}/refresh-scans-delta` | **No** | Only pull new/changed records since last scan |
| **Rebuild** | `POST /assessments/{id}/rebuild-scans` | Yes → `scans` | Delete existing results, rebuild from scratch |

**Full** and **Rebuild** reset `pipeline_stage` back to `scans`, requiring all subsequent
stages to re-run. **Delta** preserves the current pipeline position, allowing incremental
data refresh without losing downstream AI analysis, grouping, etc.

### 16.1 Re-Run from Complete

A special path exists: `rerun=true` from `complete` back to `ai_analysis`. This resets
the pipeline to `scans` stage and starts the pipeline job from the beginning.

---

## 17. Assessment Type Branching

Assessment type affects the scan stage only — all downstream stages (engines through report)
are type-agnostic.

### 17.1 Per-Type Scan Drivers

| Type | Driver Source | Example |
|------|-------------|---------|
| `global_app` | `GlobalApp.core_tables_json` + `global_app_overrides` from YAML | Incident → `incident, task, sys_journal_field, ...` |
| `table` | `assessment.target_tables_json` directly | `["incident", "problem"]` |
| `plugin` | `assessment.target_plugins_json` | `["com.snc.change_management"]` |
| `platform_global` | Empty drivers (broadest scope) | Platform-wide configs |

### 17.2 Global App Overrides

11 predefined apps have enriched scan configurations in `scan_rules.yaml`:

`incident`, `change`, `problem`, `request`, `knowledge`, `cmdb`, `asset`, `sla`,
`service_portal`, `hr_case`, `csm_case`

Each override adds extra tables, keywords, and optionally table prefixes. For example,
`cmdb` injects the `cmdb_` prefix to catch all CMDB extension tables.

### 17.3 Scope Filter Effect

| Scope | Meaning |
|-------|---------|
| `global` | Only global-scope artifacts |
| `scoped` | Only scoped-app artifacts |
| `all` | All artifacts regardless of scope |

### 17.4 Branching Summary Diagram

```
                    ┌───────────────────┐
                    │  assessment_type  │
                    └────────┬──────────┘
           ┌────────────┬────┴────┬──────────────┐
           ▼            ▼         ▼              ▼
     ┌───────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
     │global_app │ │ table  │ │plugin  │ │platform_     │
     │           │ │        │ │        │ │global        │
     └─────┬─────┘ └───┬────┘ └───┬────┘ └──────┬───────┘
           │            │          │              │
           ▼            ▼          ▼              ▼
     ┌───────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
     │target_    │ │target_ │ │target_ │ │(no target    │
     │app_id     │ │tables  │ │plugins │ │ fields)      │
     │+ overrides│ │_json   │ │_json   │ │              │
     └─────┬─────┘ └───┬────┘ └───┬────┘ └──────┬───────┘
           │            │          │              │
           └────────────┴────┬─────┴──────────────┘
                             ▼
                  ┌─────────────────────┐
                  │  resolve_assessment │
                  │  _drivers()         │
                  │  → encoded queries  │
                  └─────────┬───────────┘
                            ▼
                  ┌─────────────────────┐
                  │  create_scans_for_  │
                  │  assessment()       │
                  │  → Scan rows        │
                  └─────────────────────┘
```

---

## 18. ASCII Pipeline Diagram

See companion file: [`ASSESSMENT_PIPELINE_DIAGRAM.md`](ASSESSMENT_PIPELINE_DIAGRAM.md)

---

## Appendix A: Key Source Files

| Area | File | Lines of Interest |
|------|------|-------------------|
| Pipeline constants | `src/server.py` | 464–491 |
| Stage execution | `src/server.py` | 1644–2735 |
| Assessment model | `src/models.py` | 258–285 |
| Scan job | `src/server.py` | 403–440 |
| Pipeline job | `src/server.py` | 444–461 |
| Assessment routes | `src/server.py` | 8561–9095 |
| Advance pipeline | `src/server.py` | 9703 |
| Scan executor | `src/services/scan_executor.py` | — |
| Query builder | `src/services/query_builder.py` | — |
| AI analysis dispatch | `src/services/ai_analysis_dispatch.py` | — |
| AI feature dispatch | `src/services/ai_feature_dispatch.py` | — |
| Stage tool sets | `src/services/ai_stage_tool_sets.py` | — |
| Feature governance | `src/services/feature_governance.py` | — |
| Report export | `src/services/report_export.py` | — |
| Integration properties | `src/services/integration_properties.py` | — |
| Relationship graph | `src/services/relationship_graph.py` | 31–41 |
| Dependency graph | `src/services/dependency_graph.py` | — |
| MCP registry | `src/mcp/registry.py` | 159–260 |
| Runtime router | `src/mcp/runtime/router.py` | — |
| JSON-RPC handler | `src/mcp/protocol/jsonrpc.py` | — |
| Scan rules config | `config/scan_rules.yaml` | — |

## Appendix B: Data Model Summary

| Model | Table | Key Fields | Written By Stage |
|-------|-------|-----------|-----------------|
| `Assessment` | `assessment` | type, state, pipeline_stage, targets | Creation |
| `Scan` | `scan` | assessment_id, scan_type, status, encoded_query | Scans |
| `ScanResult` | `scan_result` | scan_id, sys_id, origin_type, review_status, ai_observations | Scans, AI Analysis, Observations |
| `Customization` | `customization` | Mirror of `ScanResult` for customized artifacts | Scans (sync) |
| `StructuralRelationship` | `structural_relationship` | parent/child scan_result_ids | Engines (structural_mapper) |
| `CodeReference` | `code_reference` | source/target, reference_type, line_number | Engines (code_reference_parser) |
| `UpdateSetArtifactLink` | `update_set_artifact_link` | scan_result ↔ update_set, link_source | Engines (update_set_analyzer) |
| `UpdateSetOverlap` | `update_set_overlap` | us_a ↔ us_b, signal_type, overlap_score | Engines (update_set_analyzer) |
| `TemporalCluster` | `temporal_cluster` | developer, start/end, record_ids | Engines (temporal_clusterer) |
| `NamingCluster` | `naming_cluster` | cluster_label, member_ids | Engines (naming_analyzer) |
| `TableColocationSummary` | `table_colocation_summary` | target_table, record_ids | Engines (table_colocation) |
| `DependencyChain` | `dependency_chain` | source/target, hop_count, chain_path | Engines (dependency_mapper) |
| `DependencyCluster` | `dependency_cluster` | member_ids, change_risk_score | Engines (dependency_mapper) |
| `Feature` | `feature` | assessment_id, name, kind, name_status, risk | Grouping, AI Refinement |
| `FeatureScanResult` | `feature_scan_result` | feature_id, scan_result_id, is_primary | Grouping, AI Refinement |
| `FeatureRecommendation` | `feature_recommendation` | feature_id, recommendation_type, fit_confidence | Recommendations |
| `GeneralRecommendation` | `general_recommendation` | category, content_json | Observations, AI Refinement, Report |
| `JobRun` | `job_run` | run_uid, module, status, progress_pct | All stages (tracking) |
| `AssessmentPhaseProgress` | `assessment_phase_progress` | assessment_id, phase, checkpoint | All stages (resumability) |
| `AssessmentRuntimeUsage` | `assessment_runtime_usage` | assessment_id, call_count, token_usage | AI stages (telemetry) |

---

*Generated 2026-04-01. Reflects the 10-stage pipeline as of Phase 7 (496 tests passing).*
