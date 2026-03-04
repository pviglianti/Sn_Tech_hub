# ServiceNow Tech Assessment — Reasoning Layer & Feature Grouping Implementation Plan

**Author**: Claude (for Pat Viglianti / Bridgeview Partners)
**Date**: March 4, 2026
**Project**: `tech-assessment-hub` on `/Volumes/SN_TA_MCP`
**Status**: Planning — ready for implementation sequencing

---

## Executive Summary

This plan covers everything needed to get from the current state (data ingestion complete, basic MCP read/write tools done, design docs ~80-90%) to a working AI-powered reasoning and grouping pipeline. It's organized into **5 phases** with clear dependencies, specific file paths for new modules, data model additions, and the AI skills needed to drive the whole thing.

The core principle: **Engines Before AI**. Build deterministic pre-processing engines first to stage/group data cheaply, then let the AI focus on judgment — interpreting clusters, writing observations, making disposition recommendations, and spotting patterns that code can't.

---

## Current State Assessment

| Component | Status | Location |
|-----------|--------|----------|
| Data ingestion (SN → SQLite) | ✅ Done | `src/services/` |
| Artifact detail definitions (25+ types) | ✅ Done | `src/artifact_detail_defs.py` |
| Data model (ScanResult, Feature, etc.) | ✅ Done | `src/models.py` |
| MCP read tools (db_reader, customizations, feature_detail) | ✅ Done | `src/mcp/tools/core/` |
| MCP write tools (update_result, update_feature, general_recommendation) | ✅ Done | `src/mcp/tools/core/` |
| Customization summary (token-efficient aggregation) | ✅ Done | `src/mcp/tools/pipeline/customization_summary.py` |
| Feature grouping (basic update_set + creator only) | 🟡 ~15-20% | `src/mcp/tools/pipeline/feature_grouping.py` |
| Grouping signals design doc | 🟡 ~80% | `02_working/01_notes/grouping_signals.md` |
| AI reasoning pipeline design doc | 🟡 ~90% | `02_working/01_notes/ai_reasoning_pipeline_domain_knowledge.md` |
| Pre-processing engines | ❌ Not started | — |
| AI pass orchestration | ❌ Not started | — |
| AI skills (observation, grouping, disposition) | ❌ Not started | — |

---

## Phase 1: Data Model Additions

**Goal**: Add the tables and fields needed to store engine outputs and AI reasoning artifacts.
**Dependency**: None — can start immediately.
**Estimated effort**: 1-2 sessions

### 1.1 New Table: `code_reference`

Stores parsed cross-references found inside script fields. This is the output of the Code Reference Parser engine.

**File**: `src/models.py` — add new model class

```
class CodeReference(SQLModel, table=True):
    """Cross-reference discovered by parsing script/code fields."""
    __tablename__ = "code_reference"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    # Source: which scan result contains the code
    source_scan_result_id: int = Field(foreign_key="scanresult.id", index=True)
    source_table: str          # e.g., "sys_script"
    source_field: str          # e.g., "script"
    source_name: str           # e.g., "BR - Approval Check"

    # Target: what the code references
    reference_type: str        # "script_include", "table_query", "event", "workflow",
                               # "field_reference", "sys_id_reference", "rest_message",
                               # "ui_page", "angular_provider", "css_include"
    target_identifier: str     # The actual string found: class name, table name, sys_id, etc.
    target_scan_result_id: Optional[int] = Field(default=None, foreign_key="scanresult.id")
                               # Resolved link to actual scan result (if found in DB)

    # Context
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None   # Short snippet around the reference
    confidence: float = 1.0              # 1.0 = exact match, 0.7 = fuzzy/inferred

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 1.2 New Table: `update_set_overlap`

Stores cross-update-set record overlap — one of the strongest grouping signals.

**File**: `src/models.py` — add new model class

```
class UpdateSetOverlap(SQLModel, table=True):
    """Records shared between two update sets (cross-US version history)."""
    __tablename__ = "update_set_overlap"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    update_set_a_id: int = Field(foreign_key="updateset.id", index=True)
    update_set_b_id: int = Field(foreign_key="updateset.id", index=True)

    shared_record_count: int         # How many records appear in both
    shared_records_json: str         # JSON list of {scan_result_id, name, table}
    overlap_score: float             # Normalized score (shared / min(a_count, b_count))

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 1.3 New Table: `temporal_cluster`

Stores developer activity windows discovered by the temporal clustering engine.

**File**: `src/models.py` — add new model class

```
class TemporalCluster(SQLModel, table=True):
    """Cluster of records created/updated in close time proximity by same developer."""
    __tablename__ = "temporal_cluster"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    developer: str                    # sys_created_by or sys_updated_by
    cluster_start: datetime           # Earliest record timestamp in cluster
    cluster_end: datetime             # Latest record timestamp in cluster
    record_count: int
    record_ids_json: str              # JSON list of scan_result_ids
    avg_gap_minutes: float            # Average time between records
    tables_involved_json: str         # JSON list of distinct tables

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 1.4 New Table: `structural_relationship`

Stores parent/child metadata relationships (Signal #5).

**File**: `src/models.py` — add new model class

```
class StructuralRelationship(SQLModel, table=True):
    """Explicit parent/child or structural relationship between artifacts."""
    __tablename__ = "structural_relationship"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    parent_scan_result_id: int = Field(foreign_key="scanresult.id", index=True)
    child_scan_result_id: int = Field(foreign_key="scanresult.id", index=True)

    relationship_type: str     # "ui_policy_action", "workflow_activity",
                               # "dictionary_entry", "dictionary_override",
                               # "catalog_variable", "rest_resource",
                               # "table_child"
    parent_field: str          # The field that establishes the link (e.g., "ui_policy")
    confidence: float = 1.0

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 1.5 New Fields on Existing `Feature` Model

Add confidence scoring and signal tracking to the Feature model:

```
# Add to Feature class in models.py:
confidence_score: Optional[float] = None        # Weighted confidence (0-15+)
confidence_level: Optional[str] = None           # "high" / "medium" / "low"
signals_json: Optional[str] = None               # JSON array of contributing signals
                                                  # e.g., [{"type":"update_set","weight":3}, ...]
primary_table: Optional[str] = None              # Most common target table
primary_developer: Optional[str] = None          # Dominant creator
date_range_start: Optional[datetime] = None
date_range_end: Optional[datetime] = None
pass_number: Optional[int] = None                # Which AI pass created/last updated this
```

### 1.6 New Fields on Existing `ScanResult` Model

Support iterative observations and AI pass tracking:

```
# Add to ScanResult class in models.py:
ai_summary: Optional[str] = None                 # Short description of what this artifact does
ai_observations: Optional[str] = None            # Iterative observations (appended per pass)
ai_pass_count: Optional[int] = 0                 # How many AI passes have touched this
related_result_ids_json: Optional[str] = None     # JSON array of related ScanResult IDs
```

### 1.7 New Enum: `GroupingSignalType`

```
class GroupingSignalType(str, Enum):
    update_set = "update_set"
    table_affinity = "table_affinity"
    naming_convention = "naming_convention"
    code_reference = "code_reference"
    structural_parent_child = "structural_parent_child"
    temporal_proximity = "temporal_proximity"
    reference_field = "reference_field"
    application_package = "application_package"
    ai_judgment = "ai_judgment"                     # AI-discovered relationship
```

### 1.8 Migration

Run `create_db_and_tables()` — since the project uses SQLModel with `create_all`, new tables will be created automatically. For new columns on existing tables, add a lightweight migration in `src/database.py` using `ALTER TABLE ADD COLUMN IF NOT EXISTS` patterns already established there.

---

## Phase 2: Pre-Processing Engines

**Goal**: Build the deterministic engines that analyze ingested data and populate the Phase 1 tables. These run BEFORE the AI touches anything — they're fast, cheap, and repeatable.
**Dependency**: Phase 1 (data model).
**Estimated effort**: 3-5 sessions

**New directory**: `src/engines/`

```
src/engines/
    __init__.py
    code_reference_parser.py      # Engine 1
    update_set_analyzer.py        # Engine 2
    temporal_clusterer.py         # Engine 3
    structural_mapper.py          # Engine 4
    naming_analyzer.py            # Engine 5
    table_colocation.py           # Engine 6
    engine_orchestrator.py        # Runs all engines in sequence
```

### Engine 1: Code Reference Parser (`code_reference_parser.py`)

**Priority**: HIGH — this is the strongest signal for understanding what artifacts do together.
**Input**: All ScanResult records that have code_fields (identified via `ARTIFACT_DETAIL_DEFS`)
**Output**: Rows in `code_reference` table

**What it parses** (regex-based, not AST — good enough for SN scripts):

| Pattern | Reference Type | Example |
|---------|---------------|---------|
| `new ClassName()` | `script_include` | `new ApprovalHelper()` |
| `GlideRecord('table')` | `table_query` | `GlideRecord('incident')` |
| `gs.include('name')` | `script_include` | `gs.include('ApprovalUtils')` |
| `gs.eventQueue('event')` | `event` | `gs.eventQueue('custom.approval')` |
| `workflow.start('name')` | `workflow` | `workflow.start('approval_flow')` |
| `sn_ws.RESTMessageV2('name')` | `rest_message` | `sn_ws.RESTMessageV2('MyAPI')` |
| `current.field_name` / `current.getValue('field')` | `field_reference` | `current.u_custom_field` |
| `GlideAjax('name')` | `script_include` | `GlideAjax('MyAjaxUtil')` |
| `$sp.getWidget('id')` | `sp_widget` | `$sp.getWidget('my-widget')` |
| Sys ID patterns (32-char hex) | `sys_id_reference` | Direct sys_id references |
| `g_form.setValue('field')` (client) | `field_reference` | `g_form.setValue('state', '6')` |

**Resolution step**: After parsing, attempt to match `target_identifier` to actual ScanResult records in the DB. If `new ApprovalHelper()` is found and there's a sys_script_include with `api_name = 'ApprovalHelper'`, set `target_scan_result_id`.

**Implementation approach**:
1. Query all artifact detail tables that have `code_fields` defined
2. For each record, extract script content from each code_field
3. Run regex patterns against the script
4. Write CodeReference rows
5. Run resolution pass to link to existing ScanResults

### Engine 2: Update Set Analyzer (`update_set_analyzer.py`)

**Priority**: HIGH — update set overlap is the strongest deterministic grouping signal.
**Input**: `UpdateSet`, `CustomerUpdateXML`, `VersionHistory` tables
**Output**: Rows in `update_set_overlap` table

**What it computes**:

1. **Update set content mapping**: For each update set, which ScanResult records have updates in it (via `customer_update_xml` → `update_set_id` → target record matching)
2. **Cross-update-set overlap**: For every pair of update sets that share records, compute:
   - Number of shared records
   - Overlap score (shared / min(count_a, count_b))
   - List of shared record identifiers
3. **Update set name clustering**: Group update sets whose names share significant tokens (e.g., "RITM_Approval_v1" and "RITM_Approval_Enhancement" → same family)
4. **Default update set analysis**: For records in "Default" update set, flag those created in sequence by the same developer as likely-related

**Key queries**:
- Join `customer_update_xml` → `update_set` to map update_set → records
- Join `version_history` to see which update sets touched the same record across its lifecycle
- Group by developer + time window within Default update set

### Engine 3: Temporal Clusterer (`temporal_clusterer.py`)

**Priority**: MEDIUM — useful but needs other signals to confirm.
**Input**: All ScanResult records with `sys_created_on`, `sys_updated_on`, `sys_created_by`, `sys_updated_by`
**Output**: Rows in `temporal_cluster` table

**Algorithm**:
1. Sort all customized results by `sys_updated_on` (or `sys_created_on` as fallback)
2. Partition by developer (`sys_updated_by`)
3. Within each developer's records, use a sliding window (configurable, default 30 minutes) to find activity bursts
4. If gap between consecutive records by same developer exceeds threshold → new cluster
5. Write cluster records with member lists

**Tunable parameters**:
- `gap_threshold_minutes`: Maximum gap between records to stay in same cluster (default: 30)
- `min_cluster_size`: Minimum records to form a cluster (default: 2)
- `weight_admin`: Lower confidence for "admin" user vs named developers

### Engine 4: Structural Relationship Mapper (`structural_mapper.py`)

**Priority**: HIGH — these are definitive parent/child relationships.
**Input**: Artifact detail tables (queried dynamically)
**Output**: Rows in `structural_relationship` table

**Known relationship mappings to implement**:

| Parent Type | Child Type | Link Field on Child | Relationship Type |
|-------------|-----------|--------------------|--------------------|
| `sys_ui_policy` | `sys_ui_policy_action` | `ui_policy` reference field | `ui_policy_action` |
| `wf_workflow` | `wf_workflow_activity` (if pulled) | `workflow_version` | `workflow_activity` |
| `sys_db_object` (table) | `sys_dictionary` | `name` (= table name) | `dictionary_entry` |
| `sys_dictionary` | `sys_dictionary_override` | `name` + `element` match | `dictionary_override` |
| `sys_hub_flow` | flow actions/subflows | reference fields | `flow_action` |
| `sp_page` | `sp_widget` instances | page reference | `portal_widget` |
| `sys_transform_map` | transform map fields | `map` reference | `transform_field` |
| `sys_web_service` | `sys_ws_operation` (if pulled) | `web_service` | `web_service_op` |
| `sc_cat_item` (if pulled) | `item_option_new` (variables) | `cat_item` | `catalog_variable` |

**Implementation**:
1. For each known relationship type, query the child artifact detail table
2. Match the reference field value to a parent record's sys_id or name
3. Look up both parent and child in ScanResult (by `sn_sys_id`)
4. Write StructuralRelationship rows

### Engine 5: Naming Analyzer (`naming_analyzer.py`)

**Priority**: MEDIUM — strong when developers follow conventions, useless when they don't.
**Input**: All ScanResult records (name field)
**Output**: Enrichment on ScanResult records (or a lightweight naming_cluster table)

**Algorithm**:
1. Tokenize all artifact names (split on `_`, `-`, spaces, camelCase boundaries)
2. Build token frequency map
3. Identify common prefixes/suffixes that appear across 3+ records (excluding generic ones like "br", "cs", "si")
4. Cluster records sharing significant prefixes (length 3+ tokens)
5. Score by prefix specificity (longer prefix = stronger signal)

**Output format**: JSON stored on each ScanResult or as a separate lookup table. Primary use is as an input signal to the feature grouping algorithm, not a standalone table.

### Engine 6: Table Co-location (`table_colocation.py`)

**Priority**: LOW (simple, but needed as an input signal).
**Input**: All ScanResult records
**Output**: Lightweight grouping data (can be computed on-the-fly by the grouping algorithm)

**Logic**: Group all artifacts by their target table. For each table, list all customized artifacts operating on it. This is really just a `GROUP BY table_name` query, but having it pre-computed with counts helps the AI skip tables with only 1-2 customizations and focus on heavily-customized tables.

### Engine Orchestrator (`engine_orchestrator.py`)

**Purpose**: Runs all engines in dependency order for a given assessment.

**Execution order**:
1. Structural Mapper (no dependencies)
2. Code Reference Parser (no dependencies)
3. Update Set Analyzer (no dependencies)
4. Temporal Clusterer (no dependencies)
5. Naming Analyzer (no dependencies)
6. Table Co-location (no dependencies — can skip since it's just a query)

All 5 can actually run in parallel since they read from the same source data and write to different tables. Sequential is fine for v1.

**MCP Tool**: Create `src/mcp/tools/pipeline/run_engines.py`

```
TOOL_SPEC = ToolSpec(
    name="run_preprocessing_engines",
    description="Run all pre-processing engines for an assessment. Populates code_reference, "
                "update_set_overlap, temporal_cluster, structural_relationship tables. "
                "Must be run BEFORE AI analysis passes.",
    input_schema={...},  # assessment_id, optional engine list to run
    handler=handle,
    permission="write",
)
```

---

## Phase 3: Enhanced Feature Grouping Algorithm

**Goal**: Replace the current simple update_set + creator grouping with the full 4-phase clustering algorithm from `grouping_signals.md`.
**Dependency**: Phase 2 (engine outputs are the inputs).
**Estimated effort**: 2-3 sessions
**File**: Rewrite `src/mcp/tools/pipeline/feature_grouping.py`

### 3.1 Architecture

The enhanced grouping algorithm consumes all engine outputs and applies the 4-phase clustering design:

```
Phase 1: Initial Clusters (high-confidence)
    → Update set clusters (exclude Default)
    → Scoped app clusters (sys_scope != global)
    → Structural parent/child groups
    → Strong code reference pairs

Phase 2: Merge by Strong Signals
    → Code reference merge (if cluster A refs cluster B, merge)
    → Naming convention merge (significant shared prefix)
    → Update set name family merge (similar US names)
    → Update set overlap merge (cross-US version history)

Phase 3: Split by Weak Signals
    → Table diversity split (cluster spans 5+ unrelated tables → split)
    → Time span split (cluster spans 2+ years with no interim updates → split)
    → Developer diversity split (5+ distinct authors → consider splitting)

Phase 4: Orphan Assignment
    → Assign by code references (strongest)
    → Assign by table affinity + naming
    → Assign by temporal proximity
    → Remaining → "Unclustered Customizations" bucket
```

### 3.2 Confidence Scoring

Each feature gets a weighted confidence score based on which signals contributed:

| Signal | Weight |
|--------|--------|
| Same scoped app (`sys_scope`) | +5 |
| Direct code reference | +4 |
| Same update set | +3 |
| Update set overlap (cross-US version history) | +3 |
| Structural parent/child | +3 |
| Naming convention match (strong prefix) | +2 |
| Transitive code reference | +2 |
| Table affinity (same target table) | +1 |
| Temporal proximity (same dev + tight window) | +1 |
| Multiple signals align (3+ distinct types) | +2 bonus |

**Confidence levels**:
- **High** (8+): Strong cluster, very likely a real feature
- **Medium** (4-7): Probable cluster, AI should validate
- **Low** (1-3): Weak cluster, may be coincidental — AI decides

### 3.3 Output Format

Each Feature record created by the algorithm stores:
- `name`: Auto-generated from dominant signal (e.g., "Update Set: RITM Approval" or "Table: incident — Custom Fields & Logic")
- `confidence_score`: Numeric score
- `confidence_level`: "high" / "medium" / "low"
- `signals_json`: Full breakdown of contributing signals
- `primary_table`: Most common target table
- `primary_developer`: Dominant creator
- `date_range_start` / `date_range_end`: Activity window

### 3.4 MCP Tool Update

The existing `group_by_feature` tool gets rewritten with new strategies:

```python
INPUT_SCHEMA = {
    "properties": {
        "assessment_id": {"type": "integer"},
        "strategy": {
            "type": "string",
            "enum": ["full", "update_set_only", "code_refs_only", "structural_only"],
            "default": "full",
        },
        "min_confidence": {
            "type": "number",
            "description": "Minimum confidence score to form a feature (default 2.0)",
            "default": 2.0,
        },
        "allow_overlap": {
            "type": "boolean",
            "description": "Allow a scan result to belong to multiple features",
            "default": True,
        },
    },
    "required": ["assessment_id"],
}
```

---

## Phase 4: AI Skills & MCP Tools

**Goal**: Build the AI-facing tools that drive the multi-pass reasoning pipeline.
**Dependency**: Phase 3 (feature grouping must produce initial clusters for AI to refine).
**Estimated effort**: 3-5 sessions

### 4.1 New MCP Tools Needed

These are the tools the AI agent/skill will call during its reasoning passes:

#### Tool: `get_engine_summary` (read)

**File**: `src/mcp/tools/pipeline/engine_summary.py`

Returns a token-efficient overview of all engine outputs for an assessment:
- Code reference graph summary (top N most-referenced artifacts, count of total references)
- Update set overlap summary (which update sets overlap, overlap scores)
- Temporal cluster summary (developer activity bursts with record counts)
- Structural relationship counts by type
- Naming pattern clusters

This is the AI's "map" before it dives into individual artifacts.

#### Tool: `get_artifact_detail` (read)

**File**: `src/mcp/tools/core/artifact_detail.py`

Given a scan_result_id, returns:
- The full artifact detail record (from the appropriate `asmt_*` table)
- All code references FROM this artifact (what it calls)
- All code references TO this artifact (what calls it)
- Structural relationships (parent/child)
- Update set info
- Version history summary
- Temporal cluster membership
- Current feature assignments

This is the AI's "deep dive" into a single artifact — the equivalent of Pat opening a business rule, reading the script, following the rabbit hole.

#### Tool: `get_feature_context` (read)

**File**: `src/mcp/tools/pipeline/feature_context.py`

Given a feature_id, returns:
- All member ScanResults with their summaries and observations
- Code reference graph WITHIN the feature (internal dependencies)
- Code references LEAVING the feature (external dependencies — may indicate merge candidates)
- Contributing signals breakdown
- Update set timeline
- Developer activity summary

#### Tool: `merge_features` (write)

**File**: `src/mcp/tools/pipeline/feature_merge.py`

AI-driven merge: combine two features into one. Recalculates confidence, combines signals, re-links ScanResults. Used when AI discovers that two algorithmically-created features are actually the same thing.

#### Tool: `split_feature` (write)

**File**: `src/mcp/tools/pipeline/feature_split.py`

AI-driven split: break a feature into two or more sub-features. Used when AI determines a feature is actually two unrelated things grouped together by coincidence.

#### Tool: `assign_orphan` (write)

**File**: `src/mcp/tools/pipeline/orphan_assignment.py`

Move an ungrouped ScanResult into an existing feature, or create a new single-record feature for it. Used during the orphan resolution pass.

#### Tool: `update_observations` (write)

**File**: Enhancement to existing `src/mcp/tools/core/update_result.py`

Add support for appending to `ai_observations` (not just overwriting) and incrementing `ai_pass_count`. This supports the iterative refinement model where each pass adds context.

### 4.2 AI Skills Architecture

Skills are the high-level "playbooks" that the AI agent follows. Each skill calls MCP tools to read data, reason about it, and write findings back.

**New directory**: `src/skills/` (or delivered as standalone skill files in the ServiceNow Knowledge Database)

#### Skill 1: `observation_skill` — Individual Artifact Analysis

**Purpose**: Pass 1 — Go through each customized scan result and write initial observations.

**What it does**:
1. Call `customization_summary` to get the lay of the land
2. Call `get_engine_summary` to see the pre-processed signals
3. For each artifact (sorted by `sys_updated_on` oldest-first, matching Pat's methodology):
   a. Call `get_artifact_detail` to read the full record including script
   b. Analyze what the artifact does (using SN domain knowledge)
   c. Check for common patterns: OOTB alternatives, deprecated APIs, broken logic, dead code
   d. Note any references to other artifacts discovered by the code reference engine
   e. Call `update_scan_result` to write: `ai_summary`, initial `ai_observations`, `finding_category`, initial `severity`
4. Track which artifacts have been analyzed (via `ai_pass_count`)

**Token management**: Process artifacts in batches (e.g., 20-30 per invocation). The skill is designed to be called repeatedly until all artifacts are processed.

**ServiceNow domain knowledge needed**:
- What each artifact type does (business rules vs client scripts vs UI policies vs etc.)
- Common OOTB alternatives (UI policies for mandatory fields, dictionary attributes for dependent values)
- Deprecated API patterns (`getXML()`, `GlideAjax` legacy patterns, synchronous GlideRecord in client scripts)
- Code quality signals (try/catch usage, logging, hardcoded sys_ids, current.update() in business rules)

#### Skill 2: `grouping_skill` — Feature Formation & Refinement

**Purpose**: Pass 2+ — Review algorithmically-created features, merge/split as needed, assign orphans.

**What it does**:
1. Call `get_engine_summary` for the signal overview
2. Call `customization_summary` filtered to ungrouped records
3. For each feature:
   a. Call `get_feature_context` to read all members and signals
   b. Evaluate: Does this cluster make sense as a business feature?
   c. If yes: Write feature `description`, `ai_summary`
   d. If it should be merged with another feature: Call `merge_features`
   e. If it should be split: Call `split_feature`
4. For orphan records:
   a. Call `get_artifact_detail` for each orphan
   b. Check code references — does it belong to an existing feature?
   c. Check table affinity and naming — any obvious home?
   d. Call `assign_orphan` or leave as ungrouped
5. Update feature-level observations that weren't visible at the individual level
6. Log any cross-feature patterns (competing features, duplicated logic)

#### Skill 3: `disposition_skill` — Recommendation & Disposition

**Purpose**: Pass 3+ — Assign dispositions (keep/refactor/replace/remove) with supporting evidence.

**What it does**:
1. For each feature:
   a. Call `get_feature_context` to review all members
   b. Evaluate against the 5 common finding patterns:
      - OOTB alternative exists?
      - Platform maturity gap? (was custom, now OOTB)
      - Bad implementation, good intent? (needs refactoring)
      - Dead or broken? (abandoned, errors, references nothing)
      - Competing/conflicting? (multiple solutions for same problem)
   c. Assign feature disposition: `keep_as_is`, `keep_and_refactor`, `remove`, `needs_analysis`
   d. Write recommendation with evidence
   e. Call `update_feature` with disposition + recommendation
2. For individual results within features:
   a. Inherit feature disposition as default
   b. Override where individual result differs (e.g., feature is "keep" but one script within it is broken → that script is "refactor")
   c. Call `update_scan_result` with individual dispositions
3. Generate general technical recommendations:
   a. Look for cross-cutting patterns (e.g., "heavy client script usage where UI policies would work")
   b. Call `save_general_recommendation` for each

#### Skill 4: `refinement_skill` — Cross-Reference & Iteration

**Purpose**: Pass N — Revisit all findings with full context, update observations, catch things missed in earlier passes.

**What it does**:
1. Review ALL features and their dispositions holistically
2. Look for conflicts: Feature A is "remove" but Feature B (which is "keep") depends on it
3. Look for consolidation opportunities: Two features doing similar things
4. Update observations on individual results with cross-feature context (e.g., "This script include is shared between Feature X and Feature Y — if Feature X is removed, this script still needs to stay for Feature Y")
5. Refine general recommendations based on the full picture
6. Mark assessment as ready for review when satisfied

### 4.3 AI Pass Orchestration

**File**: `src/mcp/tools/pipeline/ai_orchestrator.py`

This is the MCP tool that kicks off and manages the multi-pass AI analysis.

```python
TOOL_SPEC = ToolSpec(
    name="run_ai_analysis",
    description="Orchestrate multi-pass AI analysis for an assessment. "
                "Runs: engines → initial grouping → observation pass → "
                "grouping refinement → disposition → cross-reference refinement. "
                "Can be run incrementally (resume from last completed pass).",
    input_schema={
        "properties": {
            "assessment_id": {"type": "integer"},
            "start_from_pass": {
                "type": "integer",
                "description": "Resume from this pass number (default: 0 = start fresh)",
                "default": 0,
            },
            "max_passes": {
                "type": "integer",
                "description": "Maximum refinement passes (default: 3)",
                "default": 3,
            },
        },
        "required": ["assessment_id"],
    },
    handler=handle,
    permission="write",
)
```

**Orchestration flow**:
```
Pass 0: Run pre-processing engines (Phase 2)
Pass 1: Run initial feature grouping (Phase 3)
Pass 2: Run observation_skill on all unanalyzed artifacts
Pass 3: Run grouping_skill to refine features
Pass 4: Run disposition_skill to assign recommendations
Pass 5+: Run refinement_skill until stable (or max_passes reached)
```

**Stability check**: Compare feature count, disposition distribution, and observation word count between passes. If delta < threshold, analysis is stable.

---

## Phase 5: Skill Files & Domain Knowledge

**Goal**: Package the ServiceNow domain knowledge that the AI needs into reusable skill files.
**Dependency**: Phase 4 (skills need to exist before knowledge is useful).
**Estimated effort**: 2-3 sessions
**Location**: `/Volumes/SN_TA_MCP/ServiceNow Knowledge Database/` or embedded in skill prompts

### 5.1 ServiceNow Artifact Type Knowledge

Create a reference document the AI can consult that maps each artifact type to:
- What it does in plain English
- When it fires (for event-driven types like business rules, client scripts)
- Common OOTB alternatives
- Code quality red flags specific to this type
- How it relates to other artifact types

Example for Business Rules:
```
sys_script (Business Rule):
  - Server-side script triggered on record insert/update/delete/query
  - Fires in order specified by 'order' field (lower = earlier)
  - 'before' rules run before DB write, 'after' rules after, 'async' runs in background
  - Common OOTB alternatives:
    - Making fields mandatory → use dictionary 'mandatory' attribute instead
    - Setting field values → use 'template' (Set field values) instead of script
    - Simple conditions → use condition builder instead of advanced script
  - Red flags:
    - current.update() inside a business rule (causes recursion risk)
    - GlideRecord queries without addQuery (full table scan)
    - No condition set (fires on every operation)
    - Order 0 or 1 (conflicts with OOTB rules)
```

### 5.2 OOTB Comparison Knowledge

A reference of platform capabilities by version that the AI uses to determine if a custom solution has an OOTB alternative. Organized by:
- Version introduced (e.g., "Flow Designer replaced legacy workflows in Orlando")
- Capability category (approval management, notification framework, etc.)
- How to identify when a custom solution is doing what OOTB now handles

### 5.3 Finding Template Library

Pre-built finding templates for common assessment scenarios:

```
Finding: "Client Script Enforcing Mandatory Fields"
  Summary: Client script on {table} making {fields} mandatory via g_form.setMandatory()
  OOTB Alternative: Set mandatory=true on dictionary entry or use UI Policy (declarative)
  Recommendation: Remove client script, configure dictionary attribute or UI Policy
  Severity: Medium
  Category: best_practice
  Disposition: remove (if OOTB covers it) or keep_and_refactor (if complex conditional logic)
```

### 5.4 Assessment Prompt Templates

Reusable prompt templates for each skill that include:
- Role definition (you are a ServiceNow technical assessor)
- Methodology (iterative, multi-pass, follow the rabbit hole)
- Output format expectations
- Quality criteria (evidence-based recommendations, no vague suggestions)

---

## Implementation Sequencing & Dependencies

```
Week 1-2: Phase 1 (Data Model)
    ↓
Week 2-4: Phase 2 (Engines) — can start engines as soon as their tables exist
    ↓
Week 4-5: Phase 3 (Enhanced Grouping) — needs engine outputs
    ↓
Week 5-7: Phase 4 (AI Skills & Tools) — needs grouping + engine outputs
    ↓
Week 7-8: Phase 5 (Domain Knowledge) — can partially overlap with Phase 4
```

**Critical path**: Phase 1 → Engine 1 (Code Reference Parser) → Phase 3 (Enhanced Grouping) → Phase 4 (Skills)

**Parallel work opportunities**:
- Phase 2 engines are all independent of each other
- Phase 5 domain knowledge docs can be written alongside Phase 4
- MCP read tools (get_engine_summary, get_artifact_detail) can be built while engines are being developed

---

## File Summary: What Gets Created

### New Files

| File | Phase | Purpose |
|------|-------|---------|
| `src/engines/__init__.py` | 2 | Package init |
| `src/engines/code_reference_parser.py` | 2 | Parse scripts for cross-references |
| `src/engines/update_set_analyzer.py` | 2 | Compute update set overlaps |
| `src/engines/temporal_clusterer.py` | 2 | Find developer activity bursts |
| `src/engines/structural_mapper.py` | 2 | Map parent/child relationships |
| `src/engines/naming_analyzer.py` | 2 | Cluster by naming conventions |
| `src/engines/table_colocation.py` | 2 | Group by target table |
| `src/engines/engine_orchestrator.py` | 2 | Run all engines in sequence |
| `src/mcp/tools/pipeline/run_engines.py` | 2 | MCP tool to trigger engines |
| `src/mcp/tools/pipeline/engine_summary.py` | 4 | Token-efficient engine output summary |
| `src/mcp/tools/core/artifact_detail.py` | 4 | Deep-dive artifact reader |
| `src/mcp/tools/pipeline/feature_context.py` | 4 | Feature context reader |
| `src/mcp/tools/pipeline/feature_merge.py` | 4 | AI-driven feature merge |
| `src/mcp/tools/pipeline/feature_split.py` | 4 | AI-driven feature split |
| `src/mcp/tools/pipeline/orphan_assignment.py` | 4 | Assign ungrouped records |
| `src/mcp/tools/pipeline/ai_orchestrator.py` | 4 | Multi-pass orchestration |

### Modified Files

| File | Phase | Changes |
|------|-------|---------|
| `src/models.py` | 1 | Add 4 new tables + new fields on Feature and ScanResult + new enum |
| `src/database.py` | 1 | Register new tables, add ALTER TABLE migrations for new columns |
| `src/mcp/tools/pipeline/feature_grouping.py` | 3 | Full rewrite with 4-phase algorithm + confidence scoring |
| `src/mcp/tools/core/update_result.py` | 4 | Add append-mode for observations, increment pass count |
| `src/mcp/tools/pipeline/customization_summary.py` | 4 | Add engine output summary section |

---

## Open Questions to Resolve

1. **Skill delivery mechanism**: Will skills run as Claude Code skills (markdown prompts), as MCP tool chains, or as autonomous agents? This affects how the orchestrator invokes them.

2. **Batch size for AI passes**: How many artifacts per AI invocation? Need to balance token usage vs. context continuity. Recommend starting with 20-30 per batch.

3. **Feature overlap policy**: Should a ScanResult be allowed in multiple Features? The design says yes (e.g., a shared script include used by multiple features). The `FeatureScanResult` join table already supports this. Need to decide if the grouping algorithm defaults to allowing it.

4. **Version history depth**: How far back in version history should the update set analyzer go? All versions? Only versions that are still "current"? Recommend: all versions for grouping signals, but flag which version is current.

5. **Minimum viable test**: Which real assessment data will be used to validate the pipeline? Recommend running against a smaller instance first (e.g., just Incident app file types) before tackling a full global scope assessment.

6. **UI updates**: The web UI will need views for engine outputs (code reference graph visualization, update set overlap matrix). This plan doesn't cover UI work — it's a separate effort but should be planned.

---

## Getting Started: First 3 Things to Build

If you want to start coding tomorrow, here's the priority order:

1. **Add the data model** (Phase 1) — 1 session. Add the 4 new tables and new fields to `models.py`, run the migration. Everything else depends on this.

2. **Build the Code Reference Parser** (Engine 1) — 1-2 sessions. This is the highest-value engine. Once you can see "Business Rule X calls Script Include Y which queries Table Z", the grouping problem gets dramatically easier.

3. **Build the Structural Mapper** (Engine 4) — 1 session. This is the easiest engine (it's just reference field lookups) and gives you definitive parent/child groups for free.

After those three, you'll have enough data to test an enhanced grouping algorithm and start building AI skills on top of real pre-processed data.
