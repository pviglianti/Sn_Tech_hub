# Dependency Data AI Integration Design

**Date:** 2026-03-28
**Status:** Approved
**Approach:** Hybrid (embedded summaries + deep-dive tool)

## Problem

The dependency mapper engine produces `DependencyChain` and `DependencyCluster` data, feeds feature grouping with high-weight edges, and propagates risk scores to Features. However, the AI reasoning loop is almost completely blind to this data:

1. Prompts don't mention dependencies
2. No MCP tool to query dependency data
3. Deterministic observations don't include dependency context
4. `feature_detail` shows risk score but not why
5. Circular dependency detection results are unused

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Depth of dependency context | Full chain + cluster-centric | AI needs both per-artifact chain detail and feature-group-level cluster reasoning |
| Which stages get enrichment | Both ai_analysis and ai_refinement | Per-artifact dependency awareness improves observations; feature-group cluster context enables OOTB/refactor reasoning |
| OOTB alternative lookup | On-demand via search tool + internet | AI is best positioned to decide what to search; pre-computing would be wasteful |
| Observation detail level | Contextual (counts + risk signals) | Give AI structured facts; don't pre-interpret meaning |
| Integration approach | Hybrid: embedded basics + deep-dive tool | Lightweight summaries ensure AI always sees dependency data; deep-dive tool handles detailed analysis |

## Architecture

```
ENGINES STAGE (already done)
  dependency_mapper -> DependencyChain + DependencyCluster
                    -> Feature.change_risk_score/level
                           |
          +----------------+----------------+
          v                v                v
  OBSERVATIONS      AI_ANALYSIS       AI_REFINEMENT
  (deterministic)   (per-artifact)    (per-feature)

  generate_obs      get_result_       feature_detail
  adds dependency   detail adds       adds cluster
  section:          dependency_       payload:
  - chain counts    summary:          - coupling_score
  - cluster info    - counts          - impact_radius
  - coupling        - cluster label   - circular_deps
  - risk level      - risk level      - change_risk_*
                                      - overlap members

                    NEW: get_dependency_context (deep-dive, both stages)
                    NEW: search tool added to ai_refinement (OOTB lookup)
```

**Key principle:** Lightweight dependency summaries are embedded in existing tool responses (always visible). The deep-dive `get_dependency_context` tool and internet search are available on-demand.

## Component Details

### 1. `get_result_detail` Enrichment

Add `dependency_summary` key to response:

```json
{
    "dependency_summary": {
        "inbound_count": 5,
        "outbound_count": 2,
        "direct_inbound": 3,
        "direct_outbound": 1,
        "cluster_id": 42,
        "cluster_label": "Incident table cluster (8 artifacts)",
        "cluster_coupling_score": 0.85,
        "cluster_impact_radius": "very_high",
        "cluster_change_risk_level": "high",
        "has_circular_dependencies": true
    }
}
```

Returns `null` when no dependency data exists for the artifact.

**Implementation:** Query `DependencyChain` by `source_scan_result_id` (outbound) and `target_scan_result_id` (inbound). Find cluster membership by checking `DependencyCluster.member_ids_json` for the artifact's ID. Requires joining through `Scan` to get `assessment_id` for scoping.

### 2. `feature_detail` Enrichment

Add two new keys:

```json
{
    "dependency_risk": {
        "change_risk_score": 72.5,
        "change_risk_level": "high"
    },
    "dependency_clusters": [
        {
            "cluster_id": 42,
            "cluster_label": "Incident table cluster (8 artifacts)",
            "member_count": 8,
            "coupling_score": 0.85,
            "impact_radius": "very_high",
            "change_risk_score": 72.5,
            "change_risk_level": "high",
            "circular_dependency_count": 1,
            "tables_involved": ["incident", "task"],
            "overlap_member_ids": [101, 102, 105]
        }
    ]
}
```

`overlap_member_ids` identifies which of the feature's scan results are in each cluster, so the AI knows how much of the feature is tangled.

**Implementation:** Read `Feature.change_risk_score` and `change_risk_level` for the risk block. Query `DependencyCluster` by `assessment_id`, then filter to clusters whose `member_ids_json` overlaps with the feature's scan result IDs.

### 3. New Tool: `get_dependency_context`

**File:** `tech-assessment-hub/src/mcp/tools/core/dependency_context.py`

**Input schema:**
```json
{
    "scan_result_id": "integer (optional)",
    "cluster_id": "integer (optional)",
    "assessment_id": "integer (required)"
}
```

At least one of `scan_result_id` or `cluster_id` must be provided.

**Response by `scan_result_id`:**
```json
{
    "artifact": {"id": 101, "name": "...", "table_name": "..."},
    "inbound_chains": [
        {
            "source_id": 105,
            "source_name": "UI Policy: setMandatory",
            "dependency_type": "code_reference",
            "hop_count": 1,
            "chain_weight": 3.0,
            "criticality": "high",
            "chain_path": [105, 101]
        }
    ],
    "outbound_chains": [...],
    "cluster_memberships": [
        {
            "cluster_id": 42,
            "cluster_label": "...",
            "coupling_score": 0.85,
            "impact_radius": "very_high",
            "circular_dependencies": [[101, 105, 101]],
            "change_risk_level": "high"
        }
    ]
}
```

**Response by `cluster_id`:**
```json
{
    "cluster": {
        "id": 42,
        "cluster_label": "...",
        "member_count": 8,
        "coupling_score": 0.85,
        "impact_radius": "very_high",
        "change_risk_score": 72.5,
        "change_risk_level": "high",
        "tables_involved": ["incident", "task"],
        "circular_dependencies": [[101, 105, 101]]
    },
    "members": [
        {"id": 101, "name": "...", "table_name": "...", "origin_type": "customized"}
    ],
    "internal_edges": [
        {"source_id": 101, "target_id": 105, "dependency_type": "code_reference", "criticality": "high"}
    ]
}
```

### 4. Observation Enrichment (`generate_observations.py`)

**Human-readable observation block** (appended per artifact when dependency data exists):

```
--- Dependency Context ---
Inbound dependencies: 5 (3 direct, 2 transitive)
Outbound dependencies: 2 (1 direct, 1 transitive)
Cluster membership: "Incident table cluster" (8 members, coupling: 0.85, impact_radius: very_high)
Change risk level: high
Circular dependencies: 1 detected
```

Omitted entirely when artifact has no dependency data.

**Structured `ai_observations` block:**

```json
{
    "dependency_context": {
        "inbound_total": 5,
        "inbound_direct": 3,
        "outbound_total": 2,
        "outbound_direct": 1,
        "cluster_id": 42,
        "cluster_label": "Incident table cluster (8 artifacts)",
        "coupling_score": 0.85,
        "impact_radius": "very_high",
        "change_risk_level": "high",
        "circular_dependency_count": 1
    }
}
```

### 5. Prompt Updates

#### 5a. AI Analysis guidance (`_AI_ANALYSIS_FALLBACK_GUIDANCE` in `ai_analysis_dispatch.py`)

Append:

```
Dependency Awareness:
- When you read an artifact with `get_result_detail`, check the `dependency_summary`.
- If the artifact has high coupling, circular dependencies, or is in a cluster with
  impact_radius "high" or "very_high", note this in your observations.
- If you need full chain details, use `get_dependency_context` with the scan_result_id.
- Factor dependency data into scope decisions: artifacts with many inbound dependencies
  are harder to safely revert -- they are load-bearing customizations.
- Include dependency awareness in `ai_observations.directly_related_result_ids` --
  dependency chains ARE direct relationships.
```

#### 5b. AI Refinement guidance

```
Dependency-Informed Feature Analysis:
- Check the `dependency_clusters` in feature_detail. High coupling + high impact_radius
  means this feature's artifacts are tightly interwoven -- changing one affects many.
- For tightly-coupled clusters: ask whether ServiceNow provides an OOTB solution that
  replaces the whole cluster, not just individual artifacts. Use the `search` tool to
  check local knowledge base first, then use the CLI's native web search capability
  to look up OOTB alternatives on the internet (e.g., "ServiceNow OOTB [table/process]
  [what the cluster does]").
- For clusters with circular dependencies: flag as high-risk refactoring candidates.
  These cannot be safely modified piecemeal.
- When recommending "revert to OOTB": consider the blast radius. If this feature has
  change_risk_level "high" or "critical", reverting requires a coordinated plan --
  call this out in the recommendation.
- When recommending "keep but refactor": use dependency data to identify which artifacts
  are the coupling hubs (most inbound chains) and suggest refactoring those first.
```

### 6. Stage Tool Set Updates (`ai_stage_tool_sets.py`)

```python
"ai_analysis": [
    f"{_PREFIX}get_customizations",
    f"{_PREFIX}get_result_detail",
    f"{_PREFIX}update_scan_result",
    f"{_PREFIX}get_dependency_context",      # NEW
],
"ai_refinement": [
    f"{_PREFIX}feature_detail",
    f"{_PREFIX}get_result_detail",
    f"{_PREFIX}feature_grouping_status",
    f"{_PREFIX}get_dependency_context",      # NEW
    f"{_PREFIX}search",                      # NEW -- OOTB lookup
],
```

## What Is NOT Changing

- **Pipeline stage order** -- no new stages
- **`seed_feature_groups.py`** -- already consumes `DependencyCluster` for grouping
- **`search_fetch.py`** -- already built, just added to ai_refinement tool set
- **Models** -- `DependencyChain`, `DependencyCluster`, `Feature.change_risk_*` already exist
- **Dependency mapper engine** -- already runs during engines stage

## Testing

| Test | Scope | File |
|------|-------|------|
| `get_dependency_context` by scan_result_id | Verify chains and cluster membership returned | `test_dependency_context.py` |
| `get_dependency_context` by cluster_id | Verify cluster detail with members and edges | `test_dependency_context.py` |
| `get_dependency_context` missing data | Verify empty/null responses, error on invalid IDs | `test_dependency_context.py` |
| `get_result_detail` enrichment | Verify `dependency_summary` present when data exists, null when not | `test_result_detail.py` (extend) |
| `feature_detail` enrichment | Verify `dependency_risk` and `dependency_clusters` keys | `test_feature_detail.py` (extend) |
| Observation dependency section | Verify text block and `ai_observations` JSON include dependency context | `test_generate_observations.py` (extend) |
| Integration: mapper -> result_detail | End-to-end: run mapper, call get_result_detail, verify summary reflects computed chains | `test_dependency_integration.py` |
