# Dependency Mapper Engine — Design Spec

**Date:** 2026-03-28
**Purpose:** Build a standalone dependency mapping engine within the tech-assessment-hub app that discovers pure dependency relationships between customized scan results, computes transitive chains, detects circular dependencies, and produces dependency clusters to strengthen feature grouping.

---

## 1. Motivation

The existing 6 preprocessing engines produce relationship signals (code references, structural links, temporal clusters, naming patterns, update set overlaps, table colocation) that feed into a weighted `RelationshipGraph`. However, the graph mixes true dependency signals with proximity/behavioral signals. Feature grouping needs a **pure dependency view** — "these artifacts directly or transitively depend on each other" — separate from "these artifacts were edited around the same time" or "these artifacts share a name prefix."

Additionally, snow-flow's dependency analysis includes coupling, impact radius, and change risk scoring that we can adapt. Change risk is valuable for disposition decisions: knowing "this feature has high change risk due to deep dependencies" helps reviewers decide keep+refactor vs retire.

## 2. Scope

- New standalone `DependencyGraph` class (separate from `RelationshipGraph`)
- New preprocessing engine: `dependency_mapper.py` (7th engine)
- Two new database tables: `DependencyChain`, `DependencyCluster`
- New fields on `Feature` model: `change_risk_score`, `change_risk_level`
- Integration as a high-weight signal (3.5) for feature grouping
- Only operates on **customized** scan results (`origin_type` in `modified_ootb`, `net_new_customer`) for a given assessment scan

## 3. Data Model

### 3.1 DependencyChain

Stores resolved dependency paths between customized scan results.

| Field | Type | Description |
|-------|------|-------------|
| id | int PK | Auto-increment |
| scan_id | int FK → Scan | Assessment this belongs to |
| source_scan_result_id | int FK → ScanResult | Starting artifact |
| target_scan_result_id | int FK → ScanResult | Ending artifact |
| dependency_type | str | `code_reference`, `structural`, `transitive`, `shared_dependency` |
| direction | str | `outbound` (source depends on target), `inbound` (target depends on source) |
| hop_count | int | 1 = direct, 2-3 = transitive |
| chain_path_json | str (JSON) | Array of intermediate scan_result IDs, e.g. `[A, B, C]` |
| chain_weight | float | Diminishing per hop: 3.0 (hop 1), 2.0 (hop 2), 1.0 (hop 3) |
| criticality | str | `high`, `medium`, `low` |
| shared_via_identifier | str, nullable | For `shared_dependency` type: name/sys_id of the shared non-customized artifact |

### 3.2 DependencyCluster

Groups of customized artifacts forming connected dependency subgraphs.

| Field | Type | Description |
|-------|------|-------------|
| id | int PK | Auto-increment |
| scan_id | int FK → Scan | Assessment this belongs to |
| cluster_label | str | Auto-generated descriptive label |
| member_ids_json | str (JSON) | Array of scan_result IDs |
| member_count | int | Count of members |
| internal_edge_count | int | Dependency edges within the cluster |
| coupling_score | float | Weighted degree density |
| impact_radius | str | `very_high`, `high`, `medium`, `low` |
| change_risk_score | float | 0-100 |
| change_risk_level | str | `critical`, `high`, `medium`, `low` |
| circular_dependencies_json | str (JSON) | Array of cycle paths, e.g. `[[A, B, C, A]]` |
| tables_involved_json | str (JSON) | Distinct `table_name` values of members |

### 3.3 Feature Model Additions

| Field | Type | Description |
|-------|------|-------------|
| change_risk_score | float, nullable | Aggregated from overlapping dependency clusters |
| change_risk_level | str, nullable | Derived: critical (>=70), high (>=50), medium (>=30), low |

## 4. DependencyGraph

### 4.1 Structure

New standalone class in `src/services/dependency_graph.py`.

```python
@dataclass
class DependencyEdge:
    target_id: int
    dependency_type: str      # code_reference, structural, shared_dependency
    direction: str            # outbound, inbound
    weight: float             # 3.0 (code_ref), 2.5 (structural), 2.0 (shared_dep)
    criticality: str          # high, medium, low
    shared_via: Optional[str] # For shared_dependency: identifier of shared artifact

@dataclass
class DependencyGraph:
    adjacency: Dict[int, List[DependencyEdge]]
    customized_ids: Set[int]
```

### 4.2 Edge Sources

Only two source tables, filtered to customized scan results for the assessment:

**CodeReference** → directional edges
- source_scan_result_id → target_scan_result_id (outbound)
- Both must be customized, OR target is non-customized (for shared_dependency detection)
- Weight: 3.0

**StructuralRelationship** → directional edges
- parent_scan_result_id → child_scan_result_id
- Both must be customized
- Weight: 2.5

### 4.3 Shared Dependency Detection

For transitive links through non-customized artifacts:
1. Query CodeReference where source is customized but target is NOT customized
2. Group by target_identifier
3. Where 2+ customized sources share the same non-customized target, create `shared_dependency` edges between all pairs
4. Weight: 2.0
5. Store the shared artifact identifier in `shared_via`

### 4.4 Criticality Assignment

Adapted from snow-flow's criticality model:

| Condition | Criticality |
|-----------|-------------|
| code_reference to sys_script_include | high |
| code_reference type = table_query (GlideRecord) | medium |
| code_reference type = event, rest_message | medium |
| code_reference type = sys_id_reference, field_reference | low |
| structural parent→child | high |
| structural dictionary_override | low |
| shared_dependency | medium |

### 4.5 Key Methods

```python
def build(scan_id: int, session) -> DependencyGraph
def outbound(node_id: int) -> List[DependencyEdge]
def inbound(node_id: int) -> List[DependencyEdge]
def all_neighbors(node_id: int) -> List[DependencyEdge]
def dependency_chain(source_id: int, max_depth: int = 3) -> List[ChainResult]
def reverse_dependencies(target_id: int, max_depth: int = 3) -> List[ChainResult]
def detect_circular() -> List[List[int]]
def compute_clusters() -> List[ClusterResult]
def coupling_score(node_id: int) -> float
def impact_radius(node_id: int) -> str
```

## 5. Engine Logic

### 5.1 File Location

`src/engines/dependency_mapper.py` — follows existing engine patterns (idempotent, clears and regenerates).

### 5.2 Execution Flow

```
run_dependency_mapper(scan_id, session, max_depth=3):
  1. Clear existing DependencyChain + DependencyCluster for this scan_id
  2. Load customized scan_result IDs for this scan
     (origin_type IN ('modified_ootb', 'net_new_customer'))
  3. Load CodeReference rows where source OR target is in customized set
  4. Load StructuralRelationship rows where both parent and child are in customized set
  5. Build DependencyGraph
     a. Add direct edges (code_reference, structural) between customized nodes
     b. Detect shared dependencies (non-customized intermediaries)
     c. Add shared_dependency edges between customized pairs
  6. Resolve transitive chains (BFS per node, configurable max_depth)
  7. Persist DependencyChain rows
  8. Detect circular dependencies (DFS coloring)
  9. Compute clusters (connected components, min 2 members)
  10. Score each cluster (coupling, impact radius, change risk)
  11. Persist DependencyCluster rows
  12. Propagate change_risk_score to Features whose members overlap with clusters
```

### 5.3 Transitive Chain Resolution

BFS from each customized node:

```
For each customized artifact A:
  BFS queue = [(A, depth=0, path=[A])]
  visited = {A}
  while queue:
    current, depth, path = queue.pop()
    if depth >= max_depth: continue
    for edge in graph.outbound(current):
      if edge.target_id not in visited and edge.target_id in customized_ids:
        new_path = path + [edge.target_id]
        hop = depth + 1
        weight = {1: 3.0, 2: 2.0, 3: 1.0}[hop]
        yield DependencyChain(
          source=A, target=edge.target_id,
          type='transitive' if hop > 1 else edge.dependency_type,
          hop_count=hop, path=new_path, weight=weight
        )
        visited.add(edge.target_id)
        queue.append((edge.target_id, hop, new_path))
```

### 5.4 Circular Dependency Detection

DFS with three-color marking:
- WHITE (0) = unvisited
- GRAY (1) = in current DFS path
- BLACK (2) = fully explored

When a GRAY node is encountered during traversal, extract the cycle path from the recursion stack. Collect all cycles for the cluster.

### 5.5 Cluster Computation

Connected components via BFS/union-find on the undirected version of the dependency graph. Only clusters with member_count >= 2 are persisted.

Auto-label generation: use the most common `table_name` among members + count, e.g. "sys_script_include cluster (5 artifacts)" or "incident customizations (8 artifacts)".

### 5.6 Scoring Formulas

**Coupling score** (per cluster):
```
For each member: degree = len(outbound_edges) + len(inbound_edges)
coupling = sum(all member degrees) / member_count
```

**Impact radius** (adapted from snow-flow):
```
outbound = total outbound edges from cluster to outside cluster
inbound = total inbound edges into cluster from outside
children = structural child relationships within cluster
impact = outbound * 2 + inbound * 3 + children * 1
→ very_high (>50), high (>25), medium (>10), low
```

**Change risk score** (adapted from snow-flow multi-factor):
```
risk = 0
risk += coupling_score * 10           # coupling factor
risk += len(circular_deps) * 15       # circular dependency penalty
risk += len(critical_deps) * 20       # critical dependency penalty
risk += member_count * 2              # size factor
risk += sum(artifact_type_risk(t) for t in tables_involved) / len(tables_involved)

artifact_type_risk:
  sys_security_acl → 15
  sys_db_object → 10
  wf_workflow → 8
  sys_script → 6
  sys_script_include → 6
  sys_ui_policy → 4
  sys_script_client → 4
  sys_dictionary → 3
  default → 3

risk capped at 100
→ critical (>=70), high (>=50), medium (>=30), low (<30)
```

**Feature risk propagation:**
```
For each feature with members overlapping dependency clusters:
  feature.change_risk_score = max(overlapping cluster scores)
  feature.change_risk_level = derived from score
```

## 6. Integration with Feature Grouping

### 6.1 Pipeline Stage

Runs in the `engines` stage, after the existing 6 engines (depends on CodeReference and StructuralRelationship being populated first).

Execution order within engines stage:
1. code_reference_parser
2. structural_mapper
3. update_set_analyzer
4. temporal_clusterer
5. naming_analyzer
6. table_colocation
7. **dependency_mapper** (new)

### 6.2 Grouping Signal Weight

Dependency clusters are the strongest grouping signal at weight **3.5** (above code_reference and update_set_overlap at 3.0). Rationale: direct and transitive code dependencies are the most definitive evidence that artifacts belong in the same feature.

### 6.3 Consumption by AI/Grouping Stages

The AI analysis and grouping stages can query:
- `DependencyCluster` — "which artifacts form tightly coupled groups?"
- `DependencyChain` — "what is the dependency path between artifact A and B?"
- `Feature.change_risk_score` — "how risky is this feature to modify?"

These inform feature creation, merging decisions, and disposition recommendations.

## 7. Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| max_transitive_depth | 3 | Maximum hops for transitive chain resolution |
| min_cluster_size | 2 | Minimum members for a persisted cluster |
| shared_dependency_enabled | True | Whether to detect shared non-customized intermediaries |
| grouping_signal_weight | 3.5 | Weight when used as a feature grouping signal |

Configurable via the existing properties system (`integration_properties.py`).

## 8. Testing Strategy

- Unit tests for DependencyGraph construction and methods
- Unit tests for transitive chain BFS (verify depth limiting, weight diminishing)
- Unit tests for circular dependency detection (simple cycles, complex cycles, no cycles)
- Unit tests for cluster computation (connected components, singleton filtering)
- Unit tests for scoring formulas (coupling, impact radius, change risk)
- Unit tests for shared dependency detection (non-customized intermediary linking)
- Integration test: full engine run on a scan with known relationships, verify DependencyChain and DependencyCluster rows
- Edge cases: scan with no code references, scan with all artifacts in one cluster, scan with no customized artifacts
