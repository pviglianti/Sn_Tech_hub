# Reasoning Layer Phase 3: UI Signal Surfacing + Iterative AI Feature Orchestration

**Date:** 2026-03-04  
**Status:** Draft for Claude/Codex joint execution  
**Depends on:** Phase 1 + Phase 2 complete (data model + six deterministic engines)

---

## 1. Purpose

Add the missing product layer between engine outputs and final feature decisions:

1. Surface grouping indicators directly in Assessment, Scan, and Result views.
2. Show feature grouping as an expandable hierarchical view (feature -> related customized records -> evidence).
3. Run iterative AI reasoning that starts from customized records, uses engine signals plus artifact context, and converges on best-possible feature grouping.
4. Write back feature assignments for customized records only.
5. Add feature-level OOTB replacement recommendations that include product/SKU provenance.

---

## 2. Scope Boundary (Now vs Later)

### 2.1 Can be built now (no new AI runtime dependency)

- UI tabs and APIs that expose deterministic engine outputs.
- Expand/collapse feature hierarchy view in assessment/scan pages.
- Result-level grouping evidence panel.
- Seed feature generation from existing deterministic outputs.

### 2.2 Requires AI orchestration work (next phase dependency)

- Iterative AI observation and grouping refinement loop.
- Confidence-driven merge/split decisions.
- Automatic write-back of feature assignments.
- OOTB replacement recommendation logic with SKU/product attribution.

---

## 3. Non-Negotiable Rules

1. **Feature membership target set:** only customized records (`origin_type in {modified_ootb, net_new_customer}`) may be linked as feature members.
2. **Context allowed:** non-customized records may be used as supporting evidence for reasoning but cannot be final feature members.
3. **Explainability required:** all feature membership and merge/split decisions must include source/evidence payloads.
4. **Deterministic first:** engines run first; AI refines, it does not bypass deterministic signals.
5. **Human override preserved:** manual result detail feature assignment remains available and wins over auto-assignment when explicitly set.

---

## 4. Data Model Additions

### 4.1 Extend `FeatureScanResult` (membership provenance)

**File:** `src/models.py`

Add fields:
- `membership_type: str = "primary"` (`primary|supporting`)
- `assignment_source: str = "engine"` (`engine|ai|human`)
- `assignment_confidence: Optional[float]`
- `evidence_json: Optional[str]`
- `iteration_number: int = 0`

Purpose:
- Capture whether link came from deterministic engine seed, AI refinement, or human action.
- Preserve evidence needed for UI grouping tabs and auditability.

### 4.2 New `FeatureContextArtifact` (non-member context links)

**File:** `src/models.py`

Stores non-customized artifacts used as supporting context:
- `feature_id`, `scan_result_id`, `context_type`, `confidence`, `evidence_json`, `iteration_number`.

Purpose:
- Respect rule that only customized results are members while still showing context artifacts in reasoning evidence.

### 4.3 New `FeatureGroupingRun` (iteration control)

**File:** `src/models.py`

Stores each orchestration run:
- `assessment_id`, `status`, `started_at`, `completed_at`, `max_iterations`, `iterations_completed`, `converged`, `summary_json`.

Purpose:
- Resume/retry support and deterministic stop conditions.

### 4.4 New `FeatureRecommendation` (OOTB replacement analysis)

**File:** `src/models.py`

Stores feature-level replacement guidance:
- `feature_id`, `recommendation_type` (`replace|refactor|keep|remove`)
- `ootb_capability_name`
- `product_name`
- `sku_or_license`
- `requires_plugins_json`
- `fit_confidence`
- `rationale`
- `evidence_json`

Purpose:
- Capture the required "what replaces this and which product/SKU owns it" output.

### 4.5 Migration registration

**File:** `src/database.py`

- Register all new tables/columns in `_ensure_model_table_columns` with idempotent `ALTER TABLE ... ADD COLUMN` pattern.

---

## 5. API and MCP Additions

### 5.1 Web APIs for tabs and hierarchy

**Files:** `src/server.py` (or extracted route module if preferred)

Add endpoints:
- `GET /api/assessments/{assessment_id}/grouping-signals`
- `GET /api/scans/{scan_id}/grouping-signals`
- `GET /api/results/{result_id}/grouping-evidence`
- `GET /api/assessments/{assessment_id}/feature-hierarchy`
- `GET /api/scans/{scan_id}/feature-hierarchy`

Payload requirements:
- Signal counts by source (update set overlap, code refs, structural, temporal, naming, table colocation).
- Feature tree nodes with expandable children.
- For each member/customized result: why it belongs (`evidence_json`, source, confidence, iteration).
- Context artifacts emitted separately from members.
- Endpoint contract should support a unified fetch model:
  - `signal_counts` object for top cards.
  - `signals[]` array with normalized rows (`type`, `id`, `label`, `member_count`, `confidence`, `links`).

### 5.2 MCP pipeline tools

**Files:** `src/mcp/tools/pipeline/`

Add:
- `seed_feature_groups.py` (deterministic seed from engine outputs)
- `run_feature_reasoning.py` (iterative AI loop)
- `feature_grouping_status.py` (run state/convergence)

Update registry:
- `src/mcp/registry.py`

Deprecation/replace rule:
- Existing `src/mcp/tools/pipeline/feature_grouping.py` (basic update_set/creator grouping) is replaced by `seed_feature_groups.py` once parity tests pass.

---

## 6. UI Changes

### 6.1 Assessment detail page

**File:** `src/web/templates/assessment_detail.html`

Add tabs:
- `Grouping Signals`
- `Feature Hierarchy`

Feature hierarchy view requirements:
- Expand/collapse feature rows.
- Child rows show customized records only.
- Secondary child area shows context artifacts and evidence chips.
- Badges for assignment source (`engine`, `ai`, `human`) and confidence level.
- Include an `Ungrouped Customizations` bucket at the bottom, grouped by app file class.

### 6.2 Scan detail page

**File:** `src/web/templates/scan_detail.html`

Add tabs:
- `Grouping Signals`
- `Feature Hierarchy` (scan-scoped subset)

### 6.3 Result detail page

**File:** `src/web/templates/result_detail.html`

Add section/tab:
- `Grouping Evidence`

Contents:
- Current feature assignment(s) and source.
- Deterministic signals touching this result.
- Related update sets / overlaps.
- Related artifacts (customized + context split).
- Iteration history (if AI changed grouping).

### 6.4 Reusable JS component

**Files:**
- New `src/web/static/js/FeatureHierarchyTree.js`
- Load in `base.html`

Constraints:
- Reuse existing patterns (`DataTable.js`, `ConditionBuilder.js`) where tabular filtering is needed.
- Tree component handles expand/collapse and evidence rendering.
- Grouping Signals tab layout: summary cards (counts by signal type) + unified DataTable for all signals.

---

## 7. Iterative AI Reasoning Workflow

### 7.1 Pass order

1. `run_preprocessing_engines` (already complete).
2. `seed_feature_groups` deterministic pass.
3. AI observation pass on customized records (plus obvious relationship notes).
4. AI grouping refinement pass (merge/split/reassign).
5. AI verification pass (re-check conflicts, dependencies, outliers).
6. Repeat 4-5 until convergence or max iterations.
7. Persist final feature assignments + recommendations.

Tool orchestration contract:
- `run_feature_reasoning` executes one pass per call and returns pass result + deltas.
- The AI client/prompt loop decides whether to call again based on convergence status.

### 7.2 Convergence criteria

Stop when both hold:
- Membership delta < configured threshold (default 2%) between iterations.
- No new high-confidence merges/splits in latest pass.

Config keys to add:
- `reasoning.feature.max_iterations`
- `reasoning.feature.membership_delta_threshold`
- `reasoning.feature.min_assignment_confidence`

### 7.3 Write-back behavior

On finalization:
- Ensure each customized result has a feature link (or explicit ungrouped bucket).
- For new features, create `Feature.name` + `Feature.description` from AI summary.
- Update existing `Feature.ai_summary`, confidence fields, and signals.
- Persist membership provenance and evidence.

---

## 8. OOTB Replacement Recommendation Phase

After grouping converges:

1. Evaluate each feature for OOTB replacement/refactor opportunities.
2. Persist recommendation with:
- capability being replaced,
- owning product,
- SKU/license dependency,
- plugin prerequisites,
- confidence and rationale.
3. Show this directly in feature hierarchy and feature summary tabs.

Data dependencies:
- Existing local data pulls (`plugins`, `applications`, `packages`, `update_sets`).
- New optional capability map file/table for product-to-capability mapping.

---

## 9. Implementation Phases and Ownership

| Phase | Scope | Owner | Dependency |
|---|---|---|---|
| P3A | Data model extensions + migrations for hierarchy/provenance/recommendations | Codex | Phase 2 done |
| P3B | APIs for grouping signals/evidence/hierarchy | Codex | P3A |
| P3C | UI tabs + hierarchy component in assessment/scan/result pages | Claude | P3B contracts |
| P3D | Deterministic seed grouping tool | Codex | P3A |
| P4A | AI iterative reasoning orchestration tooling | Codex | P3D |
| P4B | Prompt/skill updates for observation + merge/split + verification loop | Claude | P4A |
| P4C | OOTB replacement recommendation persistence + rendering | Codex + Claude | P4A/P4B |
| P4D | End-to-end validation + human QA checklist | Both + Human | P3C/P4C |

---

## 10. Test Plan

1. Model tests
- new tables/columns exist and round-trip.
- membership provenance persisted.

2. API tests
- assessment/scan/result grouping endpoints return expected shape.
- only customized results appear as feature members.
- context artifacts are present but separated.

3. Engine + orchestration tests
- deterministic seed idempotency.
- AI iteration stop conditions.
- membership delta calculation.

4. UI tests
- tabs load and badges/counts match API.
- hierarchy expand/collapse works on desktop/mobile.
- evidence chips and assignment-source badges render correctly.

5. Regression
- full `pytest --tb=short -q` stays green.

---

## 11. Acceptance Criteria

1. Assessment/Scan/Result pages expose grouping signals and feature evidence through dedicated tabs.
2. Features tab displays expandable hierarchy with customized members and separate context artifacts.
3. AI can iterate grouping decisions and stop on deterministic convergence rules.
4. Final feature assignments are written for customized records and visible in UI.
5. Feature recommendations include OOTB replacement details with product/SKU attribution.

---

## 12. Relationship to Existing Plans

- This plan is the execution extension for:
  - `docs/plans/SN_TA_Reasoning_Layer_Implementation_Plan.md` (Phase 3/4 intent)
  - `docs/plans/2026-03-04-reasoning-layer-phase2-engines.md` (engine outputs now available)

It breaks prior high-level Phase 3/4 goals into concrete UI + orchestration deliverables and dependency-gated tasks.
