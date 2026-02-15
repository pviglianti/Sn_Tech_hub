# 00_admin/deliverables_spec.md

## Purpose
Define concise acceptance criteria for active and planned deliverables.

## Rules
- Deliverables live in `03_outputs/`.
- `03_outputs/00_delivery_index.md` is the status source of truth.
- Every major claim in a deliverable must point to source or working artifacts.

## Deliverable Set
### Active
- `03_outputs/00_delivery_index.md`
  - Acceptance: paths valid, status current, archive links maintained.
- `03_outputs/13_csdm_data_foundations_spec.md`
  - Acceptance: architecture/schema/API sections remain coherent with current code direction.
- `03_outputs/api_standardization_plan_codex_2026-02-13.md`
  - Acceptance: standardization decisions remain actionable and testable.

### Planned
- `03_outputs/01_solution_vision_and_scope.md`
  - Acceptance: clear goals, phase boundaries, measurable outcomes.
- `03_outputs/02_mcp_architecture_and_data_contracts.md`
  - Acceptance: tool/resource contracts with explicit input/output expectations.
- `03_outputs/03_servicenow_data_model_relationships.md`
  - Acceptance: key tables and relationships documented with extraction notes.
- `03_outputs/04_instance_data_extraction_plan.md`
  - Acceptance: full vs delta approach, error handling, and storage plan defined.
- `03_outputs/05_feature_grouping_heuristics_and_clustering_rules.md`
  - Acceptance: deterministic grouping rules and confidence model.
- `03_outputs/06_assessment_rubric_ootb_gap_and_recommendations.md`
  - Acceptance: scorable rubric with actionable recommendation templates.
- `03_outputs/07_revert_deactivate_automation_safety_plan.md`
  - Acceptance: risk tiers, guardrails, rollback strategy.
- `03_outputs/08_roadmap_phases_and_backlog.md`
  - Acceptance: sequenced phases, dependencies, risks.
- `03_outputs/09_open_questions_and_validation_plan.md`
  - Acceptance: open questions mapped to concrete validation actions.

## Traceability Requirement
Each deliverable should cite at least one of:
- `01_source_data/01_reference_docs/*`
- `02_working/01_notes/*`
- Implementation artifacts in `tech-assessment-hub/`

## Compression Note
Legacy full-form deliverable criteria were archived on 2026-02-14:
`/Users/pviglianti/Library/Mobile Documents/com~apple~CloudDocs/Cloud Archive/2026-02-14_core_md_compression_round4/servicenow_global_tech_assessment_mcp/00_admin/deliverables_spec.md`
