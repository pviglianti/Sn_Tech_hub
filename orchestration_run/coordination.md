# Coordination Table — SN API Centralization

**Date:** 2026-03-05
**PM:** PM Agent

---

## Task Assignments

| Task | Owner | Status | Worktree | Cross-Tester | Depends On |
|------|-------|--------|----------|-------------|------------|
| Task 1: Core Infrastructure (DESC + Properties + DB Columns) | Dev-1 | Signed Off | .worktrees/dev_1 | Dev-2 | — |
| Task 2: Consolidation (scan_executor + sn_dictionary) | Dev-2 | Signed Off | .worktrees/dev_2 | Dev-3 | — |
| Task 3: Bail-Out Logic (Upsert Change Detection + Dual-Signal) | Dev-3 | Signed Off | .worktrees/dev_3 | Dev-1 | Task 1 |

**Status values:** Pending → In Progress → Done → Testing → Agreed → Signed Off

**BLOCKED note:** Dev-3 may not begin implementation until Task 1 is fully merged. Gate condition: Task 1 sign-offs complete AND `InstanceDataPull` new columns + `load_pull_*` helpers confirmed importable.

---

## File Ownership Map

**Rule:** No overlaps. Every file is owned by exactly one task. Verified clean below.

| File | Owner | Task |
|------|-------|------|
| `tech-assessment-hub/src/services/sn_client.py` | Dev-1 | Task 1 |
| `tech-assessment-hub/src/services/integration_properties.py` | Dev-1 | Task 1 |
| `tech-assessment-hub/src/models.py` | Dev-1 | Task 1 |
| `tech-assessment-hub/tests/test_sn_client_desc_ordering.py` | Dev-1 | Task 1 (NEW) |
| `tech-assessment-hub/tests/test_integration_properties.py` | Dev-1 | Task 1 (extend) |
| `tech-assessment-hub/src/services/scan_executor.py` | Dev-2 | Task 2 |
| `tech-assessment-hub/src/services/sn_dictionary.py` | Dev-2 | Task 2 |
| `tech-assessment-hub/tests/test_scan_executor_consolidation.py` | Dev-2 | Task 2 (NEW) |
| `tech-assessment-hub/tests/test_sn_dictionary_consolidation.py` | Dev-2 | Task 2 (NEW) |
| `tech-assessment-hub/src/services/data_pull_executor.py` | Dev-3 | Task 3 |
| `tech-assessment-hub/tests/test_data_pull_bailout.py` | Dev-3 | Task 3 (NEW) |
| `tech-assessment-hub/tests/test_data_pull_desc_ordering.py` | Dev-3 | Task 3 (NEW) |

**Overlap audit result:** CLEAN. `server.py` is explicitly OUT of scope for all three tasks (Architect clarification applied — Option A normalization makes no server.py change necessary). No file appears in more than one task.

**Read-only access note:** Dev-3 reads `models.py` and `integration_properties.py` (owned by Task 1) but does NOT modify them.

---

## Cross-Test Matrix

Round-robin assignment: Dev-1 → tests Dev-2, Dev-2 → tests Dev-3, Dev-3 → tests Dev-1.

| Tester | Subject | What to Verify | Worktree |
|--------|---------|----------------|----------|
| Dev-2 | Task 1 (Dev-1's work) | DESC ordering in `_iterate_batches()`, all 11 `pull_*()` methods accept `order_desc`, 3 new PropertyDefs + helpers, 6 new `InstanceDataPull` columns default to None | .worktrees/dev_1 |
| Dev-3 | Task 2 (Dev-2's work) | `scan_executor._apply_since_filter` + `_iterate_batches` deleted, both call sites use `client.*` equivalents, all 3 `sn_dictionary` functions use `client.get_records()`, no raw `session.get()` calls remain | .worktrees/dev_2 |
| Dev-1 | Task 3 (Dev-3's work) | Bail-out fires only on dual signal (count AND content), safety cap fires independently, bail skipped on first-time load, `consecutive_unchanged` resets correctly, all 6 new columns populated, `inclusive=False` removed at line 299 | .worktrees/dev_3 |

**Test command (all cross-testers):**
```
./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short -x
```

**Baseline:** 496 tests passing. All tasks must maintain or exceed this count. No existing test may be deleted.

---

## Dev Assignment Blocks

### Dev-1 Assignment

**Build:** Task 1 — Core Infrastructure

**Files to modify/create:**
- `tech-assessment-hub/src/services/sn_client.py` — add `order_desc: bool = False` to `_iterate_batches()` AND to all 11 `pull_*()` methods (pass-through to `_iterate_batches`)
- `tech-assessment-hub/src/services/integration_properties.py` — add 3 new `PropertyDef` entries + 3 `load_*` helpers
- `tech-assessment-hub/src/models.py` — add 6 new `Optional` columns to `InstanceDataPull`
- `tech-assessment-hub/tests/test_sn_client_desc_ordering.py` — NEW, minimum 6 test cases
- `tech-assessment-hub/tests/test_integration_properties.py` — extend with 3 new property tests

**Acceptance criteria (measurable):**

| # | Criterion | Measurement |
|---|-----------|-------------|
| 1 | `_iterate_batches(order_desc=True)` appends `ORDERBYDESC{order_by}` to query | Unit test: mock verifies URL param contains `ORDERBYDESC` |
| 2 | `_iterate_batches(order_desc=False)` (default) appends `ORDERBY{order_by}` | Unit test: existing behavior preserved, URL param contains `ORDERBY` not `ORDERBYDESC` |
| 3 | `_iterate_batches` with `order_desc=True` and query already containing ORDER clause does NOT duplicate the clause | Unit test: assert ORDER clause appears exactly once in outgoing URL |
| 4 | All 11 `pull_*()` methods accept `order_desc: bool = False` and pass it to `_iterate_batches()` | Import + call test: call each method with `order_desc=True`, verify mock `_iterate_batches` receives `order_desc=True` |
| 5 | `integration.pull.order_desc` PropertyDef exists with select type, options ["true","false"], default "true", section SECTION_FETCH | Assert `PropertyDef` in `PROPERTY_DEFINITIONS` with exact key and default |
| 6 | `integration.pull.max_records` PropertyDef exists with int type, default "5000", section SECTION_FETCH | Assert `PropertyDef` in `PROPERTY_DEFINITIONS` |
| 7 | `integration.pull.bail_unchanged_run` PropertyDef exists with int type, default "50", section SECTION_FETCH | Assert `PropertyDef` in `PROPERTY_DEFINITIONS` |
| 8 | `load_pull_order_desc(session)` returns `True` when no override set | Unit test with mock session returning default |
| 9 | `load_pull_max_records(session)` returns `5000` when no override set | Unit test with mock session returning default |
| 10 | `load_pull_bail_unchanged_run(session)` returns `50` when no override set | Unit test with mock session returning default |
| 11 | Six new columns on `InstanceDataPull` default to `None` and accept correct types | Instantiate model with no kwargs, assert all 6 are None; set each, assert value round-trips |
| 12 | All 496+ existing tests pass; at least 6 new tests added | `pytest` exit code 0, `collected N items` where N >= 502 |

**Cross-test duty:** After Task 1 is merged, check out `.worktrees/dev_2` and run full suite. Verify bail-out logic, upsert change detection, `consecutive_unchanged` reset, and 6 column population. Post findings in Task 3 Cross-Test Thread.

---

### Dev-2 Assignment

**Build:** Task 2 — Consolidation

**Files to modify/create:**
- `tech-assessment-hub/src/services/scan_executor.py` — delete `_apply_since_filter()` and `_iterate_batches()`, replace both call sites with shared `sn_client` equivalents
- `tech-assessment-hub/src/services/sn_dictionary.py` — replace 3 raw `session.get()` calls with `client.get_records()`
- `tech-assessment-hub/tests/test_scan_executor_consolidation.py` — NEW, minimum 4 test cases
- `tech-assessment-hub/tests/test_sn_dictionary_consolidation.py` — NEW, minimum 4 test cases

**Acceptance criteria (measurable):**

| # | Criterion | Measurement |
|---|-----------|-------------|
| 1 | `scan_executor._apply_since_filter` is not importable from module | `from scan_executor import _apply_since_filter` raises `ImportError` |
| 2 | `scan_executor._iterate_batches` is not importable from module | `from scan_executor import _iterate_batches` raises `ImportError` |
| 3 | Metadata scan call site (~line 718) uses `client._iterate_batches(...)` | Mock test: assert `client._iterate_batches` called with correct `table`, `query`, `fields` args |
| 4 | Update_xml scan call site (~line 903) uses `client._iterate_batches(...)` | Mock test: assert `client._iterate_batches` called with correct args |
| 5 | Both scan since-filters use `client._watermark_filter(since, inclusive=True)` | Mock test: assert `_watermark_filter` called with `inclusive=True` at both sites |
| 6 | `sn_dictionary.validate_table_exists()` calls `client.get_records()` not `session.get()` | Mock test: assert `session.get` never called; `client.get_records` called with `table="sys_db_object"` |
| 7 | `sn_dictionary._resolve_table_name_by_sys_id()` calls `client.get_records()`, returns `None` on empty result | Mock test: empty list response → function returns None; populated response → returns name |
| 8 | `sn_dictionary._fetch_fields_for_table()` calls `client.get_records()` with since filter via `_watermark_filter()` | Mock test: assert `_watermark_filter` called; `client.get_records` called with `table="sys_dictionary"` |
| 9 | All 3 sn_dictionary functions gain retry logic via `get_records` | Mock `_fetch_with_retry` path: verify it is exercised on transient failure simulation |
| 10 | All 496+ existing tests pass; at least 8 new tests added | `pytest` exit code 0, `collected N items` where N >= 504 |

**Cross-test duty:** After Task 3 is complete and Dev-3 signals Done, check out `.worktrees/dev_3` and run full suite. Verify bail-out fires on dual signal, does NOT fire on single signal, safety cap fires independently, `bail_out_reason` set correctly. Post findings in Task 2 Cross-Test Thread.

---

### Dev-3 Assignment

**Build:** Task 3 — Bail-Out Logic (BLOCKED until Task 1 merges)

**BLOCKED:** Do NOT begin implementation until Task 1 sign-offs are complete and Dev-1 confirms `InstanceDataPull` columns + `load_pull_*` helpers are importable. Poll coordination.md Checkpoint 1 status.

**Files to modify/create:**
- `tech-assessment-hub/src/services/data_pull_executor.py` — wire `order_desc`, fix `inclusive=False` at line 299, implement upsert change detection, implement dual-signal bail-out, populate 6 new columns
- `tech-assessment-hub/tests/test_data_pull_bailout.py` — NEW, minimum 7 test cases
- `tech-assessment-hub/tests/test_data_pull_desc_ordering.py` — NEW, minimum 3 test cases

**Acceptance criteria (measurable):**

| # | Criterion | Measurement |
|---|-----------|-------------|
| 1 | `inclusive=False` removed from `data_pull_executor.py` line 299 | Code search: `inclusive=False` does not appear in `data_pull_executor.py`; delta probe uses `>=` |
| 2 | All 11 per-type handlers pass `order_desc=load_pull_order_desc(session)` to their `pull_*()` calls | Grep: all 11 call sites contain `order_desc=` argument |
| 3 | Bail-out fires when count gate AND content gate are BOTH met | Unit test: mock batch where `local >= remote_count` and `consecutive_unchanged >= bail_threshold` → assert `bail_out_reason == "count_and_content"` |
| 4 | Bail-out does NOT fire when only count gate is met | Unit test: `local >= remote_count` but `consecutive_unchanged < bail_threshold` → assert bail not triggered |
| 5 | Bail-out does NOT fire when only content gate is met | Unit test: `consecutive_unchanged >= bail_threshold` but `local < remote_count` → assert bail not triggered |
| 6 | Safety cap fires independently regardless of count/content gates | Unit test: `records_processed >= max_records` → assert `bail_out_reason == "safety_cap"` even when gates not met |
| 7 | Bail-out skipped entirely when `local_count_pre_pull == 0` | Unit test: first-time load scenario → no bail logic evaluated; pull completes normally |
| 8 | `bail_out_reason` set to "count_and_content" vs "safety_cap" correctly | Assert exact string values in both bail scenarios |
| 9 | `consecutive_unchanged` resets to 0 on any record where `changed=True` | Unit test: inject changed record mid-sequence, assert counter resets |
| 10 | `local_count_pre_pull` and `local_count_post_pull` populated on every pull (full/delta/smart) | Unit test all three modes: assert both columns non-None after pull |
| 11 | `remote_count_at_probe` populated from unfiltered count probe (`since=None`) | Mock test: assert probe called with `since=None`; assert column set to result |
| 12 | `order_desc` passed through to pull methods and verifiable via DESC ordering test | Mock test: `_iterate_batches` receives `order_desc=True` when property returns True |
| 13 | All 496+ existing tests pass; at least 10 new tests added | `pytest` exit code 0, `collected N items` where N >= 506 |

**Cross-test duty:** After Task 1 sign-offs, check out `.worktrees/dev_1` and run full suite. Verify DESC ordering behavior, all 11 `pull_*()` accept `order_desc`, PropertyDef defaults, and `InstanceDataPull` column nullability. Post findings in Task 3 Cross-Test Thread in plan.md.

---

## Runtime Registry

| Role | Model | Effort | PID | Log Path | Started At | Stopped At |
|------|-------|--------|-----|----------|------------|------------|
| Architect | claude-opus-4-6 | high | — | orchestration_run/logs/architect_stream.jsonl | — | — |
| PM | claude-sonnet-4-6 | medium | — | orchestration_run/logs/pm_stream.jsonl | — | — |
| Dev-1 | claude-sonnet-4-6 | medium | — | orchestration_run/logs/dev_1_stream.jsonl | — | — |
| Dev-2 | claude-sonnet-4-6 | medium | — | orchestration_run/logs/dev_2_stream.jsonl | — | — |
| Dev-3 | claude-opus-4-6 | high | — | orchestration_run/logs/dev_3_stream.jsonl | — | — |
| Reviewer | claude-sonnet-4-6 | medium | — | orchestration_run/logs/reviewer_stream.jsonl | — | — |

**Model rationale:** Dev-3 uses opus/high due to complex interdependent logic (dual-signal bail-out, upsert change detection across 11 handlers, column population across all pull modes). All other devs and the Reviewer use sonnet/medium for standard implementation and review work.

---

## Checkpoint Status

| Checkpoint | Gate Condition | Status | Passed At |
|-----------|----------------|--------|-----------|
| 0 — Plan Locked | `plan.md` + `coordination.md` both exist and contain no placeholder text; Architect clarifications applied (server.py removed from all tasks, Option A normalization confirmed, Task 1 addendum for 11 pull methods captured) | [x] | 2026-03-05 |
| 1 — Devs Launched | All three dev roles acknowledge their assignment blocks; Dev-3 ACK notes BLOCKED state; Dev-1 and Dev-2 ACKs confirm parallel start | [x] | 2026-03-05 |
| 2 — Task 1 + Task 2 Implementation Complete | Dev-1 posts `[DONE]` in Task 1 Dev-1 Notes; Dev-2 posts `[DONE]` in Task 2 Dev-2 Notes; both report `pytest` exit 0 with >= baseline test count; Task 1 sign-offs complete before Dev-3 unblocked | [x] | 2026-03-05 |
| 3 — Task 3 Unblocked + Implementation Complete | Dev-3 unblocked after Checkpoint 2 Task 1 gate passes; Dev-3 posts `[DONE]` in Task 3 Dev-3 Notes with pytest exit 0 and >= 506 tests | [x] | 2026-03-05 |
| 4 — Cross-Test Complete | All three cross-test threads in plan.md contain tester findings; all sign-off checkboxes checked (author + cross-tester + reviewer per task) | [x] | 2026-03-05 |
| 5 — Session Memory | `run_log.md` updated with sprint row; `context.md` updated with new baseline test count; `insights.md` updated with bail-out pattern and API centralization decisions; `todos.md` backlog updated with csdm_ingestion future consolidation debt; `architect_memory.md` and `pm_memory.md` created with role-specific cross-session continuity | [x] | 2026-03-05 |

---

## Overlap Verification Summary

```
sn_client.py             → Task 1 (Dev-1) ONLY
integration_properties.py → Task 1 (Dev-1) ONLY
models.py                → Task 1 (Dev-1) ONLY
scan_executor.py         → Task 2 (Dev-2) ONLY
sn_dictionary.py         → Task 2 (Dev-2) ONLY
data_pull_executor.py    → Task 3 (Dev-3) ONLY
server.py                → OUT OF SCOPE (no task touches it)

VERDICT: NO OVERLAPS. Clean ownership. Safe for parallel execution of Tasks 1 and 2.
```

---

## Dependency Chain Diagram

```
T+0h  ──► [Dev-1] Task 1: Core Infra ─────────────────────────────────────► sign-off
           [Dev-2] Task 2: Consolidation ──────────────────► sign-off         │
                                                                               │
T+3h  ─────────────────────────────────────────────────────────────────────► [Dev-3] UNBLOCKED
                                                                               Task 3: Bail-Out
T+4h  ──────────────────────────────── [Dev-2] Task 2 sign-off                │
                                        Dev-2 begins cross-test of Task 3 ──► │
T+6h  ────────────────────────────────────────────────────────────────────── Task 3 sign-off
T+7h  ──► Cross-testing complete → Reviewer pass → Checkpoint 4
```

---

## Backlog Items (Acknowledged Refactor Debt — Out of Scope This Sprint)

- `csdm_ingestion.py` still has its own `build_delta_query()` and `fetch_batch_with_retry()` — future consolidation sprint
- `scan_executor` edge cases for `inter_batch_delay` and `max_batches` lack prior test coverage — new tests in Task 2 must add these paths
- Dictionary call logging (`sn_dictionary.py`) — after Task 2, retry/error normalization is gained via `get_records()`, but dedicated per-call logging remains a Tier 3 gap

---

[2026-03-05 00:00] [PM] [COORD] — Coordination table written. File ownership verified clean (12 files, 3 tasks, zero overlaps). Server.py confirmed out of scope per Architect Option A clarification. Task 1 addendum captured (11 pull_* methods). Dev-3 BLOCKED state formalized with gate condition tied to Task 1 sign-off. Runtime registry populated with correct model assignments (Dev-3: opus/high). Checkpoint gates written with measurable conditions.

---

## Orchestrator Reconciliation

[2026-03-05 17:23] [ORCHESTRATOR] [STATUS] — Run artifacts reconciled against current files. Facts confirmed:
- Dev-1 and Dev-2 posted `[DONE]` in `plan.md`.
- Reviewer findings exist in `findings.md` for Tasks 1, 2, and 3.
- Cross-test PASS reports exist in `crosstest_task1_by_dev2.md`, `crosstest_task2_by_dev3.md`, and `crosstest_task3_by_dev1.md`.
- `plan.md` still has empty `Architect Feedback` and `PM Feedback` sections.
- Root `orchestration_run/logs/` does not contain reviewer/architect/pm feedback logs, so the feedback handoff is not evidenced.

Next required action: re-prompt Architect and PM against the existing `findings.md`, or explicitly close the run without feedback and record that omission.
