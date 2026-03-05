# Phase 11 — AI-Driven Iterative Feature Architecture

**Date:** 2026-03-05
**Status:** Approved
**Owner:** Claude (11A–11D), Codex (11E)

---

## Problem

The current pipeline treats feature creation as a deterministic engine output. `seed_feature_groups` clusters scan results using engine signals (code references, structural relationships, update set overlaps, etc.) and writes Feature + FeatureScanResult records directly. AI refines these later.

This is backwards. Features are a reasoning artifact — they represent a human consultant's judgment about what customizations belong together and why. Engine signals are indicators that feed reasoning, not conclusions in themselves. The engine-written features also cause artifact tab duplication (multiple signal paths create redundant FeatureContextArtifact entries for the same artifact).

## Design

### Core Principle: AI Owns Features

There are two core record types that AI fills in:

1. **Results** (ScanResult) — observations, ai_observations, review fields. Each result maps 1:1 to an artifact (app metadata file referencing the actual config record).
2. **Features** — name, description, ai_summary. Features group related customized results together.

**Everything else is discovery context.** Code references, structural relationships, update set overlaps, temporal clusters, naming patterns, table colocations — all of these exist solely to help the AI find other customized results that belong in the same feature. They are pathways, not conclusions.

Engines compute relationship indicators. AI reads those indicators, reasons about them using domain methodology, and creates features. This mirrors how a human consultant works through an assessment.

### The Assessment Workflow (How AI Reasons)

The AI works exactly like a human consultant:

1. **Pick up a result** — a customized scan result (= app metadata file referencing the actual config record: business rule, client script, etc.)
2. **Gather context** — update sets it's in, code references, parent/child structures, version history, related artifacts (both customized and non-customized)
3. **Write observations** — what this customization does, what it references, what it interacts with. Non-customized records provide context ("this BR queries the incident table and calls OOB script AjaxUtils") but are never grouped.
4. **Check for related customizations** — engine signals reveal which other scan results in this assessment are related. The AI asks: "do any of those related things have their OWN result in this assessment?"
5. **Tag and jump** — if a related customization is found, immediately: document both, tag them into a feature (or temp feature), jump to that artifact, add observations, check ITS relationships
6. **Follow the rabbit hole** — keep going depth-first until no more unvisited related customizations exist in this chain
7. **Return to the list** — when the rabbit hole is exhausted, move to the next open (unanalyzed) item on the main list
8. **Iterate** — repeat until every customized result is analyzed and either grouped into a feature or explicitly left ungrouped

Features evolve as understanding grows. A feature created with 2 members gets its name and description updated when a 3rd member is discovered. Observations on earlier members get back-updated to note newly discovered relationships.

### What Changes

#### 1. Engine → AI Separation

| Before | After |
|--------|-------|
| `seed_feature_groups` writes Feature + FeatureScanResult records | `get_suggested_groupings` returns suggested result groupings as JSON, writes nothing |
| Engines create FeatureContextArtifact entries | Engines only write to their own signal tables (CodeReference, StructuralRelationship, etc.) |
| AI refines engine-created features | AI creates features from scratch using engine data as hints |

#### 2. New AI Authoring Tools (MCP)

| Tool | Purpose |
|------|---------|
| `create_feature(name, description)` | Creates a Feature record, returns feature_id |
| `add_result_to_feature(feature_id, scan_result_id)` | Adds customized scan result as feature member |
| `remove_result_from_feature(feature_id, scan_result_id)` | Removes a membership |
| `update_feature(feature_id, ...)` | Updates name, description, ai_summary as understanding grows |
| `update_scan_result(...)` | Already exists — used for writing observations, ai_observations |

Enforcement: `add_result_to_feature` validates the scan result is customized. Non-customized results are rejected.

#### 3. Pipeline Mode Drives Behavior (Not a Property Toggle)

There is no `analysis_mode = sequential vs depth_first` toggle. When AI is present, it always works depth-first — that's just how assessment reasoning works.

| Pipeline mode | Behavior |
|---------------|----------|
| `local_subscription` (AI connected via MCP) | AI drives everything iteratively using tools + prompts. Depth-first rabbit-hole following is baked into the prompts. |
| `api` (no AI, fully automated) | Deterministic fallback: sequential handler + `seed_feature_groups` clustering as legacy best-effort. |

The `ai_analysis` handler detects the pipeline mode. If `local_subscription`, the AI drives via MCP. If `api`, deterministic fallback runs.

The `analysis_mode` field previously added to the Assessment model (commit `6cb7399`) will be removed — it was premature. Pipeline mode already determines behavior.

#### 4. MCP Prompts Define the Methodology

The AI loads prompts that instruct it how to reason:

| Prompt | When used | What it teaches |
|--------|-----------|-----------------|
| `artifact_analyzer` | Per-artifact analysis | Deep analysis methodology: gather context, write observations, check relationships |
| `relationship_tracer` | Cross-artifact dependency tracing | How to follow rabbit holes: find related customizations, group them, tag features |
| `technical_architect` | Full/focused review | Dual-mode review: comprehensive assessment or targeted deep-dive |
| `report_writer` | Report generation | Assessment deliverable structure |

The prompts tell the AI: "when you find a related customization while analyzing an artifact, document both, tag them to the feature, jump to that artifact, check its relationships, and keep going until the rabbit hole is exhausted."

#### 5. RelationshipGraph Service

A shared service extracts engine outputs into a traversal-friendly graph:

```
RelationshipGraph:
  nodes: Set[int]              # scan_result IDs
  adjacency: Dict[int, List[RelationshipEdge]]

  neighbors(sr_id, min_weight) → List[int]
  customized_neighbors(sr_id, min_weight) → List[int]
  edge_weight(a, b) → float
```

Edge weights from engine signal types:

| Signal | Weight |
|--------|--------|
| Code reference (direct call/import) | 3.0 |
| Structural parent/child | 2.5 |
| Update set overlap (shared US) | 2.0 |
| Temporal cluster (same developer, close in time) | 1.5 |
| Naming cluster (shared prefix) | 1.0 |
| Table colocation (same target table) | 0.5 |

Properties control traversal behavior:
- `ai_analysis.max_rabbit_hole_depth` (default 10) — max DFS depth from seed artifact
- `ai_analysis.max_neighbors_per_hop` (default 20) — cap on neighbors followed per artifact
- `ai_analysis.min_edge_weight_for_traversal` (default 2.0) — minimum relationship weight to follow

#### 6. Checkpoint + Resume

The depth-first analyzer writes a checkpoint after each artifact:

```json
{
  "visited_ids": [1, 5, 3, 7, 2],
  "seed_queue_index": 4,
  "features_created": 3,
  "total_customized": 50
}
```

If interrupted, resume rebuilds visited set and feature map from DB, continues from saved position. Never re-analyzes completed work.

#### 7. Feature Color Coding + Customization Highlighting

**Feature colors:** 20-color palette. Each Feature gets `color_index = feature.id % 20`. Results list shows colored left-borders. Assessment page shows feature color legend.

**Customization badges in related lists:** When viewing a result's code references, structural relationships, update set contents — any referenced item that is ALSO a customization in this assessment gets:
- `[Customization]` badge
- Clickable link to its result detail page
- Feature color dot if it belongs to a feature

**Graph API:** `GET /api/assessments/{id}/relationship-graph` returns nodes/edges/features JSON for Codex's D3 graph visualization.

### Stage Order

No change from current:
```
scans → engines → ai_analysis → observations → review → grouping → ai_refinement → recommendations → report → complete
```

Engines MUST run before ai_analysis because the AI needs engine relationship data to build the traversal graph.

When AI is connected (`local_subscription`), the `ai_analysis` stage is where the bulk of the work happens — the AI iterates through all customizations, writes observations, creates features, groups results. Subsequent stages (`observations`, `grouping`, etc.) become validation/merge passes rather than primary work.

---

## Implementation Phases

### Phase 11A — Stage Properties + RelationshipGraph Builder

**What:** Add DFS traversal properties. Extract the relationship graph builder from `seed_feature_groups` into a shared service. Refactor `seed_feature_groups` to import shared edge weights.

**Files:**
- `src/services/integration_properties.py` — Add 3 new properties (max_rabbit_hole_depth, max_neighbors_per_hop, min_edge_weight_for_traversal)
- `src/services/relationship_graph.py` — **NEW** — `RelationshipGraph` dataclass + `build_relationship_graph()` builder
- `src/mcp/tools/pipeline/seed_feature_groups.py` — Import shared `EDGE_WEIGHTS` from relationship_graph.py
- `src/models.py` — Remove `analysis_mode` from Assessment model
- `tests/test_relationship_graph.py` — **NEW**

**Migration:** Remove `analysis_mode` column from assessment table.

**Verification:** All existing tests pass. Graph builder unit tests pass. Properties visible in admin.

### Phase 11B — Depth-First Analyzer Service + AI Authoring Tools

**What:** Create the core DFS traversal algorithm. Add MCP tools for AI feature authoring. Refactor `seed_feature_groups` to read-only `get_suggested_groupings`.

**Files:**
- `src/services/depth_first_analyzer.py` — **NEW** — DFS traversal, progressive grouping, checkpoint support
- `src/services/contextual_lookup.py` — Extend `gather_artifact_context()` with optional graph param for enriched cross-reference data
- `src/mcp/tools/pipeline/seed_feature_groups.py` → refactor to `get_suggested_groupings` (read-only)
- `src/mcp/tools/` — **NEW** AI authoring tools: `create_feature`, `add_result_to_feature`, `remove_result_from_feature`, `update_feature`
- `src/mcp/registry.py` — Register new tools
- `tests/test_depth_first_analyzer.py` — **NEW**
- `tests/test_ai_authoring_tools.py` — **NEW**

**Verification:** DFS unit tests (chain, cycle, depth-limit, fan-out, progressive grouping, resume). AI tool tests (create, add, remove, non-customized rejection).

### Phase 11C — Pipeline Integration

**What:** Wire the depth-first analyzer into the ai_analysis stage handler. Make grouping stage aware of pre-existing features. Remove analysis_mode detection, use pipeline mode instead.

**Files:**
- `src/server.py` — Branch ai_analysis handler by pipeline mode; update grouping stage to handle pre-existing features

**Verification:** Full pipeline end-to-end in both modes. Sequential (api) mode unchanged. AI-connected mode runs DFS.

### Phase 11D — Feature Color Coding + Customization Badges + Graph API

**What:** Visual layer for grouped results and cross-customization visibility.

**Files:**
- `src/models.py` — Add `color_index: Optional[int]` to Feature
- `src/server.py` — Assign color_index on Feature creation; add `GET /api/assessments/{id}/relationship-graph` endpoint; include `is_customized` + `feature_info` in related-item API payloads
- `src/web/static/css/style.css` — 20 feature color classes, customization highlight class
- `src/web/templates/assessment_detail.html` — Feature color legend
- `src/web/templates/result_detail.html` — Customization badges in related lists, feature color chips

**Migration:** `ALTER TABLE feature ADD COLUMN color_index INTEGER;`

**Verification:** Results list shows color-coded rows. Detail pages show feature chips. Legend renders. Customized items in related lists show badges. Graph API returns valid JSON.

### Phase 11E — Interactive D3 Graph Visualization (Codex)

**What:** Codex builds the interactive D3.js relationship graph consuming the API from 11D.

**Integration point:** `GET /api/assessments/{id}/relationship-graph` returns:
```json
{
  "nodes": [{"id": 42, "name": "ApprovalBR", "table": "sys_business_rule",
             "feature_id": 3, "color_hex": "#4A90D9", "has_observations": true}],
  "edges": [{"source": 42, "target": 55, "signal_type": "code_reference", "weight": 3.0}],
  "features": [{"id": 3, "name": "Approval Workflow", "color_hex": "#4A90D9", "member_count": 5}]
}
```

---

## Verification Plan

1. After 11A: Graph builder tests pass, properties visible, existing 585+ tests pass
2. After 11B: DFS tests pass (chain, cycle, depth-limit, fan-out, progressive grouping, resume). AI authoring tool tests pass. `get_suggested_groupings` returns JSON without writing.
3. After 11C: Full pipeline in api mode unchanged. Full pipeline with AI connected runs DFS.
4. After 11D: Color-coded results list, customization badges in detail pages, feature legend, graph API returns valid JSON.
5. After 11E (Codex): Interactive graph renders with feature colors.
6. Full regression: all tests pass in both pipeline modes.
