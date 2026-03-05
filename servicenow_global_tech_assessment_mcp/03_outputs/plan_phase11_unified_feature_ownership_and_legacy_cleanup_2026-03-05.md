# Phase 11 Unified Plan — AI-Owned Features + Legacy Data Cleanup

Date: 2026-03-05  
Status: Draft for execution (Codex + Claude aligned)  
Primary Goal: Make feature creation AI-owned, keep engines evidence-only, and clean legacy feature/scan duplication safely.

## Inputs Consolidated
- `tech-assessment-hub/docs/plans/2026-03-05-phase11-ai-driven-feature-architecture-design.md`
- `tech-assessment-hub/docs/plans/2026-03-05-phase11-implementation-plan.md`
- `00_admin/phase3_planning_chat.md` entries from 2026-03-05 08:00 through 20:08
- Live DB findings for assessment 1 (duplicate scan rows + non-customized feature memberships)

## Non-Negotiable Architecture Rules
1. Engines compute signals only. They do not own `Feature` / `FeatureScanResult` in local subscription mode.
2. AI owns feature authoring (`create_feature`, membership add/remove, `update_feature`) with explicit write paths.
3. Feature membership must be customized-only (server-side guard).
4. Unique `(feature_id, scan_result_id)` must be enforced at DB and write-path levels.
5. Legacy cleanup must preserve human-authored memberships (`assignment_source='human'`).

## Execution Tracks

### Track A — Foundation + Contracts
Owner: Claude (implementation) + Codex (review)
- Remove `analysis_mode` drift where it conflicts with runtime-mode architecture.
- Finalize mode contract:
  - `local_subscription`: AI-driven feature creation path.
  - `api`: deterministic fallback allowed.
- Refactor grouping seed path to support read-first suggestions (`dry_run`/`get_suggested_groupings`) for AI usage.
Done when:
- Target tests pass for stage behavior and grouping APIs.
- Contract documented in admin memory + coordination files.

### Track B — AI Feature Authoring Surface
Owner: Claude (implementation) + Codex (review)
- Deliver MCP tools:
  - `create_feature`
  - `add_result_to_feature`
  - `remove_result_from_feature`
- Ensure all writes stamp `assignment_source='ai'` for AI-created links.
- Ensure write-path rejects non-customized result membership.
Done when:
- New tool tests pass.
- Reviewer verifies tool behavior against custom/non-customized cases.

### Track C — Data Integrity Hardening
Owner: Codex (implementation) + Claude (review)
- Add unique protection for `(feature_id, scan_result_id)`.
- Add centralized customized-only validation used by all feature membership writes.
- Add regression tests for duplicate-protection and guardrails.
Done when:
- Integrity tests pass.
- Existing feature workflows remain green.

### Track D — Legacy Cleanup Utility + Controlled Run
Owner: Codex (implementation) + Human (run approval) + Claude (review)
- Add assessment-scoped cleanup utility with `--dry-run` and `--apply`.
- Cleanup operations:
  - remove non-customized feature memberships,
  - dedupe duplicate scan-result artifacts per assessment using deterministic canonical selection,
  - remove empty/engine-only legacy feature groupings where safe,
  - preserve human-authored memberships.
- Generate before/after report table (counts + impacted IDs).
Done when:
- Dry-run output reviewed.
- Human approves apply run.
- Post-run validation query confirms expected reductions with no custom data loss.

### Track E — Validation + Rollout Gate
Owner: Both + Human
- Targeted test suites for new tools, pipeline behavior, integrity constraints, cleanup utility.
- Full regression before final approval.
- Human live QA on one clean assessment + one legacy assessment.
Done when:
- Both agents post `APPROVED` in phase chat.
- Human validates pipeline and customizations/feature views.

## Commit Strategy
- Human will perform commits.
- Commit order:
1. Claude independent tranche (Tracks A/B pieces completed by Claude).
2. Codex integrity tranche (Track C).
3. Codex cleanup utility tranche (Track D code).
4. Post-cleanup docs/admin sync + final validation updates.

## Test Gate Matrix
1. New tool suites: `tests/test_create_feature_tool.py`, `tests/test_feature_membership_tools.py`.
2. Integrity suites: feature grouping/membership + duplicate protection tests.
3. Pipeline suites: stage-order + mode-aware behavior.
4. Cleanup suite: dry-run/apply behavior + preservation rules.
5. Full regression: `pytest --tb=short -q`.

## Deliverables
1. Mode-aware, AI-owned feature authoring workflow.
2. Integrity-protected feature membership model.
3. Assessment-scoped legacy cleanup utility + report output.
4. Updated coordination/admin memory (todos, insights, run log, context as needed).

## Open Decisions Needed from Human
1. Cleanup scope default: run only on assessment `1` first, or batch all flagged legacy assessments?
2. In `api` mode, keep deterministic feature creation fallback enabled now, or disable globally and force AI-only?
3. For duplicate scan-result collapse, should non-canonical rows be hard-deleted or soft-archived to a backup table first?
4. Preferred maintenance window for cleanup apply run (to avoid active assessment edits).
