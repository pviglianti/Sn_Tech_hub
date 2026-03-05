# Architect Memory

> This file is read on every Architect launch for cross-session continuity.
> Keep it focused: patterns, debt, decisions, and next-sprint prep only.

---

## Last Sprint: SN API Centralization (2026-03-05)

**Commit:** `967161a` on `feature/sn-api-centralization`
**Tests:** 496 → 713 (+217 net-new, +44%)
**Files:** 12 changed (2,760 ins / 206 del)
**Review verdict:** 3/3 APPROVED, 0 changes requested
**Cross-test verdict:** 3/3 PASS

### Architecture Patterns That Worked

1. **Zero-overlap file ownership** — 12 files across 3 tasks, no file shared between tasks. Eliminated merge conflicts entirely. Design rule: max 3-5 files per task, explicit ownership map in coordination table.
2. **Property system scalability** — `PropertyDef` + `load_*` helpers absorbed 3 new properties (`sn_pull_order_desc`, `sn_pull_bail_out_enabled`, `sn_pull_bail_out_threshold`) with zero friction. Frozen-dataclass pattern continues to prove its worth.
3. **Introspection-based signature tests** — `inspect.signature` across all 11 `pull_*` methods verified `order_desc` acceptance in one test. Worth standardizing for future bulk-API changes.
4. **`inclusive=True` normalization (Option A)** — one rule (`>=` everywhere) replaced context-dependent `>` vs `>=`. Simpler, zero regressions. Confirmed as the right call.
5. **Dual-signal bail-out** — `bail_out_reason` + `bail_out_after_key` provide both a human-readable explanation and a machine-resumable watermark. Good separation of concerns.
6. **`PullHandler` type alias** — loosened to `Callable[..., Tuple[int, Optional[datetime]]]` for 5 new keyword params. Pragmatic, but watch for divergence — if handler signatures grow further, bundle into a `BailOutParams` dataclass.

### Refactor Debt Carried Forward

| Debt Item | Severity | Notes |
|-----------|----------|-------|
| Bail-out boilerplate (~25 lines × 11 handlers) | Medium | All reviewers flagged. Extract `_run_bail_out_loop()` or `_bail_out_context()` helper. Careful: per-handler field-mapping differences. |
| `csdm_ingestion.py` still has own `build_delta_query()` / `fetch_batch_with_retry()` | Low | Intentionally scoped out. Last holdout for centralized client. Single-task sprint. |
| `display_value=False` silently dropped in Task 2 modules | Low | SN defaults to `false` when omitted — behaviorally safe. Add explicit `display_value` param to `get_records()` for self-documenting contract. |
| Lost inline comments in Task 3 (handler docstrings) | Low | `_pull_packages` admin note, `_pull_plugins` field-mapping note. Restore in follow-up. |
| 5/11 pull methods lack explicit pass-through tests | Low | Covered by introspection, but mock-based tests would be more rigorous. |
| ORDER direction dedup in `_iterate_batches` | Low | Detects same-direction duplicates but not conflicting directions (ASC vs DESC for same field). Latent risk if SN changes precedence rules. |

### Cross-Cutting Concerns to Monitor

- **Property loading order in `execute_data_pull`:** Three new properties are eager-loaded at function top. If property loading ever becomes async/session-scoped, preserve this pattern to avoid mid-pull config drift.
- **Orphan cleanup gating:** `bail_out_reason is None` guard prevents orphan deletion on early termination. Any code path that sets `bail_out_reason` must respect this invariant. Document at guard site.

### Next-Sprint Architectural Prep

1. **Bail-out helper extraction** — first item in next cleanup sprint. Reduces 11 × 25 lines to 11 × 5 lines.
2. **`csdm_ingestion.py` consolidation** — centralized client is proven. CSDM module is the last holdout. Single-task sprint.
3. **`display_value` parameter** — add to `get_records()` API surface.
4. **ORDER direction conflict detection** — harden `_iterate_batches` dedup guard.
5. **Bail-out telemetry dashboard** — 6 new `InstanceDataPull` columns enable analytics (frequency, reason distribution, records-saved-per-pull).

---

## Process Notes for Future Plans

- **Task decomposition rule:** max 3-5 files per task, zero overlap. This sprint proved the pattern at scale (12 files, 3 tasks, 0 conflicts).
- **Dependency gating works:** Task 3 blocked on Task 1 sign-off was cleanly managed. No wasted work from Dev-3.
- **Round-robin cross-testing** caught implicit assumptions. Each dev verified another dev's work in a different worktree — independent validation.
- **Reviewer thoroughness:** spec compliance tables + coverage gap analysis + architecture notes (not just pass/fail) is the right bar.
