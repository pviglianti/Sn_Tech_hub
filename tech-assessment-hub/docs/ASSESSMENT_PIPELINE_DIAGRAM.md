# Assessment Pipeline — Full ASCII Diagram

> Companion to [ASSESSMENT_WORKFLOW_COMPLETE.md](ASSESSMENT_WORKFLOW_COMPLETE.md)

---

## Master Pipeline Flow

```
╔═══════════════════════════════════════════════════════════════════════════════════════╗
║                    ASSESSMENT LIFECYCLE — 10-STAGE PIPELINE                           ║
║                    Every transition is MANUAL (no auto-advance)                       ║
╠═══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                       ║
║  ┌─────────────────┐         ┌─────────────────────────────────────────────────┐      ║
║  │ USER CREATES    │         │            STAGE 1: SCANS                       │      ║
║  │ ASSESSMENT      │────────▶│  Preflight → SN Queries → Postflight           │      ║
║  │                 │  START  │  (Background thread: _AssessmentScanJob)        │      ║
║  │ - name          │         │                                                 │      ║
║  │ - instance      │         │  Properties: fetch.batch_size,                  │      ║
║  │ - type          │         │    pull.max_records, preflight.concurrent_types  │      ║
║  │ - scope_filter  │         │                                                 │      ║
║  │ - file_classes  │         │  Output: ScanResult rows classified by origin   │      ║
║  └─────────────────┘         └──────────────────────┬──────────────────────────┘      ║
║                                                      │ ADVANCE                        ║
║                                                      ▼                                ║
║  ┌───────────────────────────────────────────────────────────────────────────────┐    ║
║  │                         STAGE 2: ENGINES                                      │    ║
║  │  (Background thread: _AssessmentPipelineJob)                                  │    ║
║  │                                                                               │    ║
║  │  Phase 1 ─────────────────────────────────────────────────────────────────    │    ║
║  │  │ structural_mapper          │ code_reference_parser                    │    │    ║
║  │  │ (parent/child rels)        │ (regex cross-refs in scripts)           │    │    ║
║  │  └────────────────────────────┴─────────────────────────────────────────│    │    ║
║  │                                                                         │    │    ║
║  │  Phase 2 ──────────────────────────────────────────────────────────     │    │    ║
║  │  │ update_set_analyzer  │ temporal_clusterer │ naming_analyzer │  │     │    │    ║
║  │  │ (US overlap signals) │ (time proximity)   │ (prefix groups) │  │     │    │    ║
║  │  └──────────────────────┴────────────────────┴────────────────┘  │     │    │    ║
║  │  │ table_colocation                                               │     │    │    ║
║  │  │ (same-table groups)                                            │     │    │    ║
║  │  └────────────────────────────────────────────────────────────────│     │    │    ║
║  │                                                                   │     │    │    ║
║  │  Phase 3 (depends on Phase 1) ────────────────────────────────   │     │    │    ║
║  │  │ dependency_mapper                                          │  │     │    │    ║
║  │  │ (graph, chains, clusters, risk scoring)                    │  │     │    │    ║
║  │  └────────────────────────────────────────────────────────────│  │     │    │    ║
║  │                                                                         │    │    ║
║  │  Properties: reasoning.us.*, reasoning.temporal.*, reasoning.naming.*,   │    │    ║
║  │    reasoning.dependency.*                                                │    │    ║
║  │  Output: 7 signal tables feeding weighted relationship graph             │    │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 3: AI ANALYSIS                                   │    ║
║  │  (CLI subprocess dispatch per artifact)                                   │    ║
║  │                                                                           │    ║
║  │  ┌─────────────────────────┐    ┌──────────────────────────────────────┐  │    ║
║  │  │ ai.runtime.mode check   │    │ Per artifact (batch_size=1):        │  │    ║
║  │  │                         │    │                                      │  │    ║
║  │  │  disabled ──▶ SKIP      │    │  1. Build stage instructions         │  │    ║
║  │  │  local_subscription ──┐ │    │  2. Inject prompts (if enabled):     │  │    ║
║  │  │  api_key ────────────┐│ │    │     - tech_assessment_expert         │  │    ║
║  │  │                      ││ │    │     - artifact_analyzer (dynamic)    │  │    ║
║  │  └──────────────────────┘│ │    │  3. Dispatch to CLI with tool set    │  │    ║
║  │                          │ │    │  4. Validate: review_in_progress set │  │    ║
║  │                          └─┼───▶│  5. Merge dispatch trace             │  │    ║
║  │                            │    └──────────────────────────────────────┘  │    ║
║  │                            │                                              │    ║
║  │  context_enrichment: auto/always/never (controls live SN queries)         │    ║
║  │  enable_depth_first: graph-ordered vs ID-ordered traversal                │    ║
║  │  Supports resume from checkpoint on interruption                          │    ║
║  │                                                                           │    ║
║  │  Output: ScanResult.ai_observations, scope decisions, observations        │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 4: OBSERVATIONS                                  │    ║
║  │  (Deterministic — NO LLM involved)                                        │    ║
║  │                                                                           │    ║
║  │  For each in-scope customized artifact:                                   │    ║
║  │    1. Count update set links → primary US name                            │    ║
║  │    2. Count structural relationship signals                               │    ║
║  │    3. Optional: get_usage_count (auto/always/never)                       │    ║
║  │    4. Write observations text (only if empty)                             │    ║
║  │    5. Write deterministic_observation_baseline to ai_observations         │    ║
║  │    6. Advance review_status → review_in_progress                          │    ║
║  │    7. Upsert landscape_summary GeneralRecommendation                      │    ║
║  │                                                                           │    ║
║  │  Properties: observations.batch_size, observations.include_usage_queries  │    ║
║  │  Output: Baseline observations on all customized artifacts                │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 5: REVIEW GATE                                   │    ║
║  │  (Human checkpoint — no computation)                                      │    ║
║  │                                                                           │    ║
║  │           all ScanResults       ┌────────────────────┐                    │    ║
║  │           reviewed?             │  YES → GATE OPENS  │                    │    ║
║  │                ├───────────────▶│  (advance allowed)  │                    │    ║
║  │                │                └────────────────────┘                    │    ║
║  │                │  NO                                                      │    ║
║  │                │     ┌──────────────────────────────┐                     │    ║
║  │                ├────▶│ skip_review=true?             │                     │    ║
║  │                │     │  YES → bulk mark all reviewed │                     │    ║
║  │                │     │  NO  → BLOCKED (400 error)   │                     │    ║
║  │                │     └──────────────────────────────┘                     │    ║
║  │                                                                           │    ║
║  │  How artifacts reach "reviewed":                                          │    ║
║  │    - AI Analysis sets → review_in_progress                                │    ║
║  │    - Observations sets → review_in_progress                               │    ║
║  │    - Human reviewer via UI → reviewed                                     │    ║
║  │    - skip_review bypass → bulk reviewed                                   │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 6: GROUPING                                      │    ║
║  │  (CLI subprocess dispatch — multi-pass)                                   │    ║
║  │                                                                           │    ║
║  │  Pre: _reset_ai_feature_graph() — clear non-human features               │    ║
║  │                                                                           │    ║
║  │  Pass Plan (from ai.feature.pass_plan_json):                              │    ║
║  │  ┌─────────────────────────────────────────────────────────────────┐      │    ║
║  │  │  Pass 1: STRUCTURE                                              │      │    ║
║  │  │  → Create obvious solution features with provisional names      │      │    ║
║  │  │  → Set feature_kind (functional/bucket), name_status=provisional│      │    ║
║  │  ├─────────────────────────────────────────────────────────────────┤      │    ║
║  │  │  Pass 2: COVERAGE                                               │      │    ║
║  │  │  → Assign every remaining unassigned artifact                   │      │    ║
║  │  │  → Place into solution features or bucket taxonomy categories   │      │    ║
║  │  └─────────────────────────────────────────────────────────────────┘      │    ║
║  │                                                                           │    ║
║  │  Bucket taxonomy: form_fields, acl, notifications, scheduled_jobs,        │    ║
║  │    integration_artifacts, data_policies_validations                        │    ║
║  │                                                                           │    ║
║  │  Post: Validate 0 unassigned artifacts remain                             │    ║
║  │  Output: Feature rows with ScanResult memberships                         │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 7: AI REFINEMENT                                 │    ║
║  │  (CLI subprocess + server-side enrichment)                                │    ║
║  │                                                                           │    ║
║  │  AI Passes:                                                               │    ║
║  │  ┌─────────────────────────────────────────────────────────────────┐      │    ║
║  │  │  Pass 3: REFINE                                                 │      │    ║
║  │  │  → Merge features covering same solution                        │      │    ║
║  │  │  → Split unrelated bundles                                      │      │    ║
║  │  │  → Move artifacts from bucket → solution features               │      │    ║
║  │  ├─────────────────────────────────────────────────────────────────┤      │    ║
║  │  │  Pass 4: FINAL NAMING                                           │      │    ║
║  │  │  → Rename all provisional features                              │      │    ║
║  │  │  → Solution-based names (e.g., "Pharmacy Incident Solution")    │      │    ║
║  │  └─────────────────────────────────────────────────────────────────┘      │    ║
║  │                                                                           │    ║
║  │  Server-Side Enrichment (no CLI):                                         │    ║
║  │  ┌─────────────────────────────────────────────────────────────────┐      │    ║
║  │  │  A. Complex Feature Summaries (5+ members, no ai_summary)       │      │    ║
║  │  │     → Prompt: relationship_tracer (if use_registered_prompts)   │      │    ║
║  │  │                                                                 │      │    ║
║  │  │  B. Per-Artifact Technical Review                               │      │    ║
║  │  │     → Prompt: technical_architect Mode A (per artifact)         │      │    ║
║  │  │     → Checks against BestPractice catalog for artifact type     │      │    ║
║  │  │                                                                 │      │    ║
║  │  │  C. Assessment-Wide Technical Findings Rollup                   │      │    ║
║  │  │     → Prompt: technical_architect Mode B (assessment-wide)      │      │    ║
║  │  │     → Stored as GeneralRecommendation (technical_findings)      │      │    ║
║  │  └─────────────────────────────────────────────────────────────────┘      │    ║
║  │                                                                           │    ║
║  │  Post: Validate 0 unassigned AND 0 provisional features                  │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 8: RECOMMENDATIONS                               │    ║
║  │  (CLI subprocess dispatch)                                                │    ║
║  │                                                                           │    ║
║  │  Pre-flight: BLOCKS if unassigned artifacts OR provisional features       │    ║
║  │  Pre: Delete all existing FeatureRecommendation rows                      │    ║
║  │                                                                           │    ║
║  │  AI reviews finalized feature graph and for each feature writes:          │    ║
║  │  ┌─────────────────────────────────────────────────────────────────┐      │    ║
║  │  │  upsert_feature_recommendation:                                 │      │    ║
║  │  │    recommendation_type: replace / refactor / keep / remove      │      │    ║
║  │  │    ootb_capability_name: "Agent Workspace"                      │      │    ║
║  │  │    product_name: "ITSM"                                         │      │    ║
║  │  │    sku_or_license: "ITSM Professional"                          │      │    ║
║  │  │    requires_plugins: ["com.sn_agent_workspace"]                 │      │    ║
║  │  │    fit_confidence: 0.85                                         │      │    ║
║  │  │    rationale: "..."                                             │      │    ║
║  │  │    evidence: [...]                                              │      │    ║
║  │  └─────────────────────────────────────────────────────────────────┘      │    ║
║  │                                                                           │    ║
║  │  Output: FeatureRecommendation rows per feature                           │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 9: REPORT                                        │    ║
║  │  (Deterministic assembly + optional AI narrative)                         │    ║
║  │                                                                           │    ║
║  │  Pre-flight: BLOCKS if unassigned artifacts OR provisional features       │    ║
║  │                                                                           │    ║
║  │  Data Assembly (deterministic):                                           │    ║
║  │  ┌─────────────────────────────────────────────────────────────────┐      │    ║
║  │  │  1. Statistics: artifacts by table and origin type              │      │    ║
║  │  │  2. Features: counts by kind/composition/disposition            │      │    ║
║  │  │  3. Recommendations: counts by type                             │      │    ║
║  │  │  4. Review status: distribution                                 │      │    ║
║  │  │  5. Build report_data dict                                      │      │    ║
║  │  │  6. Store as GeneralRecommendation (assessment_report)          │      │    ║
║  │  └─────────────────────────────────────────────────────────────────┘      │    ║
║  │                                                                           │    ║
║  │  AI Narrative (if pipeline.use_registered_prompts=true):                  │    ║
║  │  ┌─────────────────────────────────────────────────────────────────┐      │    ║
║  │  │  report_writer prompt → 5-section deliverable:                  │      │    ║
║  │  │    1. Executive Summary                                         │      │    ║
║  │  │    2. Customization Landscape                                   │      │    ║
║  │  │    3. Feature Analysis                                          │      │    ║
║  │  │    4. Technical Findings                                        │      │    ║
║  │  │    5. Recommendations                                           │      │    ║
║  │  └─────────────────────────────────────────────────────────────────┘      │    ║
║  │                                                                           │    ║
║  │  Export: report_export.py → .xlsx (openpyxl) + .docx (python-docx)        │    ║
║  └──────────────────────────────────┬────────────────────────────────────────┘    ║
║                                      │ ADVANCE                                    ║
║                                      ▼                                            ║
║  ┌───────────────────────────────────────────────────────────────────────────┐    ║
║  │                    STAGE 10: COMPLETE                                      │    ║
║  │                                                                           │    ║
║  │  state = completed, pipeline_stage = complete                             │    ║
║  │  Assessment is finalized.                                                 │    ║
║  │                                                                           │    ║
║  │  Re-run path: rerun=true → resets to scans → restarts pipeline            │    ║
║  └───────────────────────────────────────────────────────────────────────────┘    ║
║                                                                                       ║
╚═══════════════════════════════════════════════════════════════════════════════════════╝
```

---

## Two-Graph Architecture: Dependency Graph vs. Relationship Graph

These are **two architecturally separate graphs** that serve complementary purposes.
The Dependency Graph's output feeds into the Relationship Graph as its strongest signal.

```
╔══════════════════════════════════════════════════════════════════════════╗
║                    GRAPH 1: DEPENDENCY GRAPH (NEW)                      ║
║                    File: src/services/dependency_graph.py               ║
║                    Built by: Engine 7 (dependency_mapper)               ║
║                                                                         ║
║  Input: Phase 1 engine outputs ONLY                                     ║
║  ┌─────────────────────────┐    ┌────────────────────────────┐         ║
║  │ CodeReference rows      │    │ StructuralRelationship rows│         ║
║  │ (code_reference_parser) │    │ (structural_mapper)        │         ║
║  └───────────┬─────────────┘    └──────────────┬─────────────┘         ║
║              │                                  │                       ║
║              └──────────────┬───────────────────┘                       ║
║                             ▼                                           ║
║  ┌─────────────────────────────────────────────────────────────────┐   ║
║  │ build_dependency_graph()                                        │   ║
║  │                                                                 │   ║
║  │  Pass 1: Register ALL nodes (all_ids + customized_ids +         │   ║
║  │          _table_names for type-aware risk)                      │   ║
║  │                                                                 │   ║
║  │  Pass 2: code_reference edges (outbound, wt 3.0)               │   ║
║  │          + auto-creates reverse inbound edges                   │   ║
║  │          + tracks customized→non-customized for shared deps     │   ║
║  │                                                                 │   ║
║  │  Pass 3: shared_dependency edges (bidirectional, wt 2.0)       │   ║
║  │          UNIQUE to this graph — no equivalent in RelGraph       │   ║
║  │          When 2+ customized artifacts reference same            │   ║
║  │          non-customized target                                  │   ║
║  │                                                                 │   ║
║  │  Pass 4: structural edges (bidirectional, wt 2.5)              │   ║
║  │          Each edge carries criticality (high/med/low)           │   ║
║  └───────────────────────────┬─────────────────────────────────────┘   ║
║                              │                                         ║
║         ┌────────────────────┼────────────────────┐                    ║
║         ▼                    ▼                    ▼                    ║
║  ┌─────────────────┐ ┌─────────────────┐ ┌──────────────────┐        ║
║  │ resolve_        │ │ detect_circular │ │ compute_         │        ║
║  │ transitive_     │ │ _dependencies() │ │ clusters()       │        ║
║  │ chains()        │ │                 │ │                  │        ║
║  │ BFS, max 3 hops │ │ DFS 3-color    │ │ BFS connected    │        ║
║  │ weight decay:   │ │ cycle detection │ │ components +     │        ║
║  │ 3.0→2.0→1.0    │ │                 │ │ risk scoring     │        ║
║  └────────┬────────┘ └────────┬────────┘ └────────┬─────────┘        ║
║           │                   │                    │                   ║
║           ▼                   │                    ▼                   ║
║  ┌─────────────────┐         │           ┌──────────────────┐        ║
║  │ DependencyChain │         │           │ DependencyCluster│        ║
║  │ (DB rows)       │         │           │ (DB rows)        │        ║
║  │                 │         │           │ + risk scores    │        ║
║  │ Persisted:      │         │           │ + circular deps  │──┐     ║
║  │ hop_count,      │         │           │                  │  │     ║
║  │ chain_weight,   │         └──────────▶│ coupling_score,  │  │     ║
║  │ criticality     │                     │ impact_radius,   │  │     ║
║  └─────────────────┘                     │ change_risk_*    │  │     ║
║                                          └──────────────────┘  │     ║
║                                                                │     ║
║  Side effect: propagate_risk_to_features()                     │     ║
║    → writes Feature.change_risk_score / change_risk_level      │     ║
║    → max-wins across cluster memberships                       │     ║
║                                                                │     ║
╚════════════════════════════════════════════════════════════════╪═════╝
                                                                 │
                   DependencyCluster rows (weight 3.5)           │
                   STRONGEST deterministic signal ───────────────┘
                                                                 │
╔════════════════════════════════════════════════════════════════╪═════╗
║                    GRAPH 2: RELATIONSHIP GRAPH (ORIGINAL)      │     ║
║                    File: src/services/relationship_graph.py    │     ║
║                    Built by: seed_feature_groups tool           │     ║
║                                                                │     ║
║  Input: ALL engine outputs (7 signal sources)                  │     ║
║                                                                │     ║
║  ┌────────────────────────────────────────────────────────┐    │     ║
║  │  Signal Source              │  Weight  │  Engine       │    │     ║
║  │─────────────────────────────┼──────────┼──────────────│    │     ║
║  │  dependency_cluster ◀───────┼── 3.5 ───┼── FROM ABOVE │◀───┘     ║
║  │  ai_relationship            │   3.5    │  AI-derived   │          ║
║  │  update_set_overlap         │   3.0    │  US Analyzer  │          ║
║  │  code_reference             │   3.0    │  Code Parser  │          ║
║  │  structural_relationship    │   2.5    │  Struct Mapper│          ║
║  │  update_set_artifact_link   │   2.5    │  US Analyzer  │          ║
║  │  naming_cluster             │   2.0    │  Naming Anlzr │          ║
║  │  temporal_cluster           │   1.8    │  Temporal Clst│          ║
║  │  table_colocation           │   1.2    │  Table Coloc  │          ║
║  └────────────────────────────────────────────────────────┘          ║
║                              │                                       ║
║                              ▼                                       ║
║  ┌────────────────────────────────────────────────────────┐          ║
║  │ build_relationship_graph()                              │          ║
║  │ → In-memory only (NOT persisted to DB)                  │          ║
║  │ → No algorithms (read-only traversal lookups)           │          ║
║  │ → No criticality, no risk scoring                       │          ║
║  └───────────────────────┬────────────────────────────────┘          ║
║                          │                                           ║
║                          ▼                                           ║
║  ┌────────────────────────────────────────────────────────┐          ║
║  │ seed_feature_groups()                                   │          ║
║  │ (union-find on pairwise signals)                        │          ║
║  └───────────────────────┬────────────────────────────────┘          ║
║                          │                                           ║
║                          ▼                                           ║
║  ┌────────────────────────────────────────────────────────┐          ║
║  │ Initial Feature Groups (seeded)                         │          ║
║  └───────────────────────┬────────────────────────────────┘          ║
║                          │                                           ║
║               ┌──────────┴──────────┐                                ║
║               ▼                     ▼                                ║
║        ┌────────────┐        ┌────────────┐                          ║
║        │ AI Pass:   │        │ AI Pass:   │                          ║
║        │ STRUCTURE  │───────▶│ COVERAGE   │                          ║
║        └────────────┘        └────────────┘                          ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## AI Analysis Dispatch Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                    AI ANALYSIS DISPATCH                               │
│                    (per artifact)                                     │
└──────────────────────────────────────────────────────────────────────┘

  ┌────────────────────┐
  │ Check ai.runtime.  │
  │ mode property      │
  └────────┬───────────┘
           │
    ┌──────┴──────┬───────────────┐
    ▼             ▼               ▼
 disabled    local_sub       api_key
 (SKIP)      scription       (server-side)
              │                    │
              └────────┬───────────┘
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │ Budget check: _enforce_assessment_stage_budget()           │
  │   soft_limit → warning   |   hard_limit → RuntimeError    │
  └────────────────────┬───────────────────────────────────────┘
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │ LLM preflight: DispatcherRouter.preflight_check()          │
  │   Validates provider/model reachability                    │
  └────────────────────┬───────────────────────────────────────┘
                       ▼
  ┌────────────────────────────────────────────────────────────┐
  │ For each customized artifact (ordered by ID or DFS):       │
  │                                                            │
  │   ┌──────────────────────────────────────────────────────┐ │
  │   │ _build_artifact_stage_instructions()                 │ │
  │   │                                                      │ │
  │   │  ┌─ Assessment scope context (target, tables, etc.)  │ │
  │   │  │                                                   │ │
  │   │  ├─ pipeline.use_registered_prompts = true?          │ │
  │   │  │   YES ──▶ + tech_assessment_expert (static)       │ │
  │   │  │          + artifact_analyzer (dynamic DB context)  │ │
  │   │  │   NO  ──▶ (skip prompt injection)                 │ │
  │   │  │                                                   │ │
  │   │  └─ + _AI_ANALYSIS_FALLBACK_GUIDANCE (always)        │ │
  │   └──────────────────────────────────────────────────────┘ │
  │                          │                                  │
  │                          ▼                                  │
  │   ┌──────────────────────────────────────────────────────┐ │
  │   │ build_batch_prompt() — wraps instructions + artifact │ │
  │   │ list into _BATCH_PROMPT_TEMPLATE                     │ │
  │   └──────────────────────┬───────────────────────────────┘ │
  │                          ▼                                  │
  │   ┌──────────────────────────────────────────────────────┐ │
  │   │ Dispatch to CLI with STAGE_TOOL_SETS["ai_analysis"]  │ │
  │   │ Tools: get_customizations, get_result_detail,        │ │
  │   │   query_instance_live, search_servicenow_docs,       │ │
  │   │   fetch_web_document, update_scan_result             │ │
  │   └──────────────────────┬───────────────────────────────┘ │
  │                          ▼                                  │
  │   ┌──────────────────────────────────────────────────────┐ │
  │   │ Validate: review_status=review_in_progress set?      │ │
  │   │           non-empty observation written?              │ │
  │   │   FAIL → abort   |   PASS → merge dispatch trace     │ │
  │   └──────────────────────────────────────────────────────┘ │
  │                          │                                  │
  │              ┌───────────┘                                  │
  │              ▼                                              │
  │   checkpoint_phase_progress (resumable)                     │
  │   ──── next artifact ────                                   │
  └────────────────────────────────────────────────────────────┘
```

---

## AI Feature Stage Dispatch (Grouping / Refinement / Recommendations)

```
┌──────────────────────────────────────────────────────────────────────┐
│              AI FEATURE STAGE DISPATCH                                │
│              (grouping, ai_refinement, recommendations)              │
└──────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────┐
  │ Read ai.feature.pass_plan_json                               │
  │ Filter entries matching target stage                         │
  └────────────────────────┬─────────────────────────────────────┘
                           ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ For each pass in plan:                                       │
  │                                                              │
  │   pass = { stage, pass_key, label,                           │
  │            ?provider, ?model, ?effort }                      │
  │                                                              │
  │   ┌────────────────────────────────────────────────────────┐ │
  │   │ _build_feature_stage_prompt()                          │ │
  │   │  - Assessment scope context                            │ │
  │   │  - Bucket taxonomy text                                │ │
  │   │  - Current feature coverage stats                      │ │
  │   │  - Pass-specific instructions:                         │ │
  │   │      structure: create obvious features                │ │
  │   │      coverage: assign all remaining                    │ │
  │   │      refine: merge/split/move                          │ │
  │   │      final_name: rename provisionals                   │ │
  │   │      recommend: write OOTB recs                        │ │
  │   │  - Optionally: tech_assessment_expert prompt           │ │
  │   └────────────────────────────┬───────────────────────────┘ │
  │                                ▼                              │
  │   ┌────────────────────────────────────────────────────────┐ │
  │   │ Dispatch to CLI with stage-specific tool set           │ │
  │   │ Optional per-pass provider/model override              │ │
  │   └────────────────────────────┬───────────────────────────┘ │
  │                                ▼                              │
  │   ┌────────────────────────────────────────────────────────┐ │
  │   │ refresh_feature_metadata() — recalculate computed flds │ │
  │   └────────────────────────────────────────────────────────┘ │
  │                                                              │
  │   ──── next pass ────                                        │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ Post-pass validation:                                        │
  │   grouping      → 0 unassigned artifacts                     │
  │   ai_refinement → 0 unassigned + 0 provisional features     │
  │   recommendations → FeatureRecommendation rows created       │
  └──────────────────────────────────────────────────────────────┘
```

---

## Scan Sub-Workflow Detail

```
┌──────────────────────────────────────────────────────────────────────┐
│                    SCAN SUB-WORKFLOW                                  │
│                    (_run_scans_background)                            │
└──────────────────────────────────────────────────────────────────────┘

  ┌────────┐      ┌─────────────────────────────────────────────┐
  │ QUEUED │─────▶│ VALIDATING INSTANCE CONNECTION               │
  └────────┘      │ Tests SN API connectivity                    │
                  └──────────────────┬──────────────────────────┘
                                     ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ PREFLIGHT: REQUIRED SYNC                                     │
  │                                                              │
  │  Required types (must succeed):                              │
  │    metadata_customization, app_file_types,                   │
  │    version_history, customer_update_xml, update_sets          │
  │                                                              │
  │  Concurrent types (background threads):                      │
  │    version_history, customer_update_xml                       │
  │    (configurable via preflight.concurrent_types)             │
  │                                                              │
  │  Sequential types: complete in main thread                   │
  │  Staleness check: skip if data < 10 min old                 │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ RUNNING SCANS                                                │
  │                                                              │
  │  scan_executor.run_scans_for_assessment()                    │
  │    1. resolve_assessment_drivers() — build encoded queries   │
  │    2. create_scans_for_assessment() — Scan rows from YAML   │
  │    3. Execute queries against SN sys_metadata               │
  │    4. Classify results by origin type                        │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ POSTFLIGHT: ARTIFACT DETAIL PULL                             │
  │                                                              │
  │  pull_artifact_details_for_assessment()                      │
  │  → Fetches script bodies, conditions, etc. from SN          │
  │  → Separate JobRun (module="postflight")                    │
  │  → NON-FATAL: failure logged but doesn't abort              │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ WAITING FOR CONCURRENT PREFLIGHT                             │
  │  → Join background threads (VH + customer_update_xml)       │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ VERSION HISTORY CATCH-UP                                     │
  │  → Complete any remaining VH data pull                       │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
  ┌──────────────────────────────────────────────────────────────┐
  │ CLASSIFYING RESULTS                                          │
  │                                                              │
  │  classify_scan_results() with full VH data                   │
  │                                                              │
  │  Origin types assigned:                                      │
  │    ootb             — unmodified OOTB artifact               │
  │    modified_ootb    — OOTB with customer changes             │
  │    net_new_customer — entirely customer-created              │
  │    skipped          — excluded by filters                    │
  └──────────────────────────────┬───────────────────────────────┘
                                 ▼
                          ┌───────────┐
                          │ COMPLETED │
                          └───────────┘
```

---

## Property Scope Resolution

```
  ┌─────────────────────────────────────────────────────────────┐
  │  Property Value Resolution Order                             │
  │  (from integration_properties.py)                            │
  └─────────────────────────────────────────────────────────────┘

     1. Instance-scoped row                    ← highest priority
        (AppConfig where instance_id = X)
        effective_source = "instance"
                    │
                    │ (if NULL or not found)
                    ▼
     2. Global row
        (AppConfig where instance_id = NULL)
        effective_source = "global"
                    │
                    │ (if NULL or not found)
                    ▼
     3. Hardcoded PROPERTY_DEFAULTS
        effective_source = "default"           ← lowest priority
```

---

## Assessment Type → Scan Query Branching

```
  ┌──────────────┐
  │ assessment   │
  │ .type        │
  └──────┬───────┘
         │
  ┌──────┴──────┬──────────────┬──────────────┬──────────────────┐
  │             │              │              │                  │
  ▼             ▼              ▼              ▼                  ▼
global_app    table          plugin       platform_global    scoped_app
  │             │              │              │               (future)
  │             │              │              │
  ▼             ▼              ▼              ▼
┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────┐
│GlobalApp  │ │target_    │ │target_    │ │Empty drivers  │
│.core_     │ │tables_    │ │plugins_   │ │(broadest      │
│tables +   │ │json       │ │json       │ │ scope)        │
│overrides  │ │           │ │           │ │               │
│from YAML  │ │           │ │           │ │               │
└─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └───────┬───────┘
      │              │              │                │
      └──────────────┴──────┬───────┴────────────────┘
                            ▼
               ┌──────────────────────┐
               │ query_builder.py     │
               │ resolve_assessment_  │
               │ drivers()            │
               │                      │
               │ → core_tables        │
               │ → keywords           │
               │ → table_prefixes     │
               │ → plugins            │
               └──────────┬───────────┘
                          ▼
               ┌──────────────────────┐
               │ scan_executor.py     │
               │ create_scans_for_    │
               │ assessment()         │
               │                      │
               │ → Reads scan_rules   │
               │   .yaml for type     │
               │ → Creates Scan rows  │
               │   per scan_kind      │
               └──────────────────────┘
```

---

## Prompt Injection Decision Tree

```
  ┌────────────────────────────────────────────────────────┐
  │  pipeline.use_registered_prompts = ?                   │
  └───────────────────────┬────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
           FALSE                    TRUE
              │                       │
              ▼                       ▼
  ┌──────────────────┐    ┌──────────────────────────────────────────────────┐
  │ Fallback guidance │    │ Full prompt injection by stage:                 │
  │ only (inline      │    │                                                 │
  │ instructions)     │    │ ai_analysis:                                    │
  │                   │    │   + tech_assessment_expert (static)             │
  │                   │    │   + artifact_analyzer (dynamic per artifact)    │
  │                   │    │                                                 │
  │                   │    │ grouping:                                       │
  │                   │    │   + tech_assessment_expert                      │
  │                   │    │                                                 │
  │                   │    │ ai_refinement:                                  │
  │                   │    │   + tech_assessment_expert                      │
  │                   │    │   + relationship_tracer (5+ member features)    │
  │                   │    │   + technical_architect Mode A (per artifact)   │
  │                   │    │   + technical_architect Mode B (rollup)         │
  │                   │    │                                                 │
  │                   │    │ recommendations:                                │
  │                   │    │   + tech_assessment_expert                      │
  │                   │    │                                                 │
  │                   │    │ report:                                         │
  │                   │    │   + report_writer (dynamic with DB data)        │
  └──────────────────┘    └──────────────────────────────────────────────────┘
```

---

*Generated 2026-04-01. Companion to ASSESSMENT_WORKFLOW_COMPLETE.md.*
