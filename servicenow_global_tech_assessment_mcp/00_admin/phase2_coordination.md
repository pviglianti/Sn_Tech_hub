# Phase 2 Engines — Claude + Codex Coordination Protocol

> **Purpose:** Shared coordination file for Claude and Codex during Phase 2 engine implementation.
> Both agents MUST monitor this file for updates after completing development work.

**Plan document:** `tech-assessment-hub/docs/plans/2026-03-04-reasoning-layer-phase2-engines.md`
**Plan addendum (approved):** Section `## Addendum (Approved 2026-03-04): Artifact-Centric Update Set Reasoning`

---

## Task Assignments

| Task | Owner | Status | Depends On |
|------|-------|--------|------------|
| Task 0: Data model additions (+ addendum tables/fields) | Claude | `done` | — |
| Task 0b: Reasoning property scaffolding (AppConfig/UI) | Claude | `done` | Task 0 |
| Task 1: Update Set Analyzer (base + enriched) | Codex | `approved` | Tasks 0, 0b |
| Task 2: Temporal Clusterer | Claude (agent) | `approved` | Tasks 0, 0b |
| Task 3: Naming Analyzer | Claude (agent) | `approved` | Tasks 0, 0b |
| Task 4: Table Co-location | Claude (agent) | `approved` | Tasks 0, 0b |
| Task 5: Registry wiring | Claude | `done` | Tasks 1–4 |
| Task 6: Full regression | Both | `approved` | Task 5 |

### Status values
`not_started` → `in_progress` → `tests_passing` → `review_requested` → `approved` → `done`

---

## Checkpoints

### Checkpoint 1 — Data Model Ready
- **Gate:** Tasks 0 + 0b complete, migration applied, reasoning properties available, all existing tests still pass.
- **Action:** Claude updates Task 0 status to `done`, posts message in Communication Log below.
- **Unblocks:** Tasks 1–4 can begin.

### Checkpoint 2 — All Engines Complete
- **Gate:** Tasks 1–4 all at `tests_passing` or higher.
- **Action:** Each owner sets `review_requested`. Other agent reviews.
- **Unblocks:** Task 5 (registry wiring).

### Checkpoint 3 — Registry Wired
- **Gate:** Task 5 complete, `run_preprocessing_engines` runs all 6 engines.
- **Action:** Claude sets Task 5 to `tests_passing`, posts message.
- **Unblocks:** Task 6 (full regression).

### Checkpoint 4 — Final Sign-Off
- **Gate:** Full test suite green, both agents approve.
- **Action:** Both post `APPROVED` in Communication Log. Update `todos.md` + `context.md`.

---

## Communication Protocol

### How to communicate
1. **Post messages** in `phase2_chat.md` (same directory as this file).
2. **Format:** `[YYYY-MM-DD HH:MM] [AGENT] [TAG] — message`
3. **After completing development work**, check `phase2_chat.md` for any pending questions or review requests before moving on.
4. **Status table updates** (task status changes) go in THIS file's Task Assignments table above.

### Message types

| Tag | Meaning | Expected response |
|-----|---------|-------------------|
| `STATUS` | Progress update, no response needed | None |
| `QUESTION` | Needs answer before continuing | Answer within next check-in |
| `REVIEW_REQUEST` | Code ready for review | `REVIEW_PASS` or `REVIEW_FEEDBACK` |
| `REVIEW_PASS` | Approved, no changes needed | Owner sets status to `approved` |
| `REVIEW_FEEDBACK` | Changes needed (details follow) | Owner addresses, re-requests review |
| `BLOCKED` | Cannot proceed, needs help | Other agent investigates |
| `APPROVED` | Final sign-off on a checkpoint | — |

### Review requirements
- **Before marking `approved`:** Reviewer MUST verify:
  1. Tests exist and pass (`pytest tests/test_<engine>.py -v`)
  2. Engine follows established patterns (idempotent delete-then-insert, `session.commit()` at end)
  3. No regressions in existing test suite (`pytest --tb=short`)
  4. Code matches the plan (or deviations are documented with rationale)

### Check-in cadence
- After completing each task, check this file.
- After posting a `QUESTION`, expect the other agent to respond on their next check-in.
- If blocked for more than one task cycle, escalate to human via `todos.md`.

---

## Shared Conventions

### File locations
- **Engines:** `tech-assessment-hub/src/engines/<engine_name>.py`
- **Tests:** `tech-assessment-hub/tests/test_<engine_name>.py`
- **Models:** `tech-assessment-hub/src/models.py`
- **Registry:** `tech-assessment-hub/src/mcp/tools/pipeline/run_engines.py`

### Engine interface contract
```python
def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    # 1. Validate assessment exists
    # 2. Load scan_results via join
    # 3. Delete existing rows for idempotency
    # 4. Process and insert new rows
    # 5. session.commit()
    # 6. Return {"success": bool, ..., "errors": [...]}
```

### Test pattern
```python
def _setup_base(session):
    """Create Instance + Assessment + Scan. Return (instance, assessment, scan)."""

def test_<scenario>(session):
    instance, assessment, scan = _setup_base(session)
    # Create specific ScanResults / detail rows
    result = <engine>.run(assessment.id, session)
    assert result["success"] is True
    # Verify created rows
```

---

## Known Implementation Notes

### For Codex (Task 1: Update Set Analyzer)
- `_compute_content_overlaps` needs a `sr_by_sys_id` dict parameter to link CUX → ScanResult.
  The linking chain: `CustomerUpdateXML.target_sys_id` → `ScanResult.sys_id`.
  See plan Task 1, Step 3 implementation note for corrected code.
- Addendum policy: default update sets are **downgraded signals, not hard-excluded**.
- Implement `UpdateSetArtifactLink` and persist explainability payloads (`evidence_json`) on overlap rows.
- `signal_type` coverage should include addendum signals (`content`, `name_similarity`, `version_history`, sequence/family variants when emitted).

### For Claude agents (Tasks 2–4)
- Task 0 (data model) must be complete before starting. Verify `NamingCluster` and `TableColocationSummary` tables exist.
- Task 0b (reasoning property scaffolding) must be complete before thresholds are consumed in engines.
- All engines import from `..models` — check that new model classes are exported.
- `TemporalClusterMember` junction table already exists from Phase 1 addendum. Use it, don't recreate.

---

## Chat Log

All back-and-forth messages go in **`phase2_chat.md`** (same directory). This file stays clean as the protocol reference.
