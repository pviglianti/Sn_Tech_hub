# Phase 5 — Pipeline Orchestration UI + AI Observation Pipeline

## Status: APPROVED — Both agents approved. Execution in progress.

## Addendums (A6–A10, from Codex review)

- **A6:** Plural route naming: `/api/assessments/{assessment_id}/advance-pipeline`, `/api/results/{result_id}/review-status`
- **A7:** Separate `pipeline` object in polling response (stage, stage_updated_at, active_run with status/message/progress_percent/started_at/finished_at/job_type) — does not overload scan job semantics
- **A8:** Replace `observations.usage_query_limit` with `observations.max_usage_queries_per_result` (int, default 2) to cap query fanout per artifact
- **A9:** P5E recommendation button runs `run_feature_reasoning` as verification/refinement pass; actual recommendation records come from AI/orchestrator calling `upsert_feature_recommendation`; stage advances to `complete` only when pass succeeds
- **A10:** `generate_observations` = deterministic baseline observation synthesis + optional usage-count enrichment; no embedded LLM runtime; prompts/resources remain orchestration guidance for external MCP clients

## Context

Phase 3/4 delivered the reasoning layer: 6 engines, grouping signals, feature hierarchy, and OOTB recommendation rendering (320 tests passing). However, the pipeline currently requires manual MCP tool invocations with no visual orchestration. The user identified critical gaps:

- **No process flow visualization** — users can't see where they are in the assessment lifecycle
- **No button-triggered stage progression** — each post-scan step requires manual MCP calls
- **No pre-grouping AI observations** — no automated landscape summary or per-artifact analysis
- **No supplemental instance queries** — no efficient way to check usage data (e.g., "is this custom field still used?")
- **No human review gate** — no way for humans to review/edit AI observations before grouping

**Goal:** Add a human-gated, button-driven pipeline UI with process flow bar, deterministic observation generation (with optional live instance usage queries), and human review gates — all reusing existing infrastructure.

---

## Phase 5A — Process Flow Bar + Engine Trigger Button

### What changes
Add a `PipelineStage` enum and 2 new Assessment fields to track extended pipeline state. Render a horizontal process flow bar on the assessment detail page. Add a "Run Engines" button that triggers engines via background job.

### Files to modify

| File | Change |
|------|--------|
| `src/models.py` | Add `PipelineStage` enum, add `pipeline_stage` + `pipeline_stage_updated_at` fields to Assessment |
| `src/server.py` | Add `POST /api/assessments/{assessment_id}/advance-pipeline` endpoint, add pipeline status to scan-status polling response |
| `src/web/templates/assessment_detail.html` | Add process flow bar HTML above existing content, add "Run Engines" button, add JS polling for pipeline state |
| `src/web/static/css/style.css` | Add flow bar CSS (horizontal step indicator with active/completed/pending states) |

### Implementation details

**PipelineStage enum** (add after `AssessmentState` at line ~27 in models.py):
```python
class PipelineStage(str, Enum):
    """Extended pipeline stages beyond scan lifecycle."""
    scans = "scans"              # Preflight → Scans → Postflight (existing)
    engines = "engines"          # Preprocessing engines
    observations = "observations" # Deterministic observation generation
    review = "review"            # Human review gate
    grouping = "grouping"        # Feature grouping
    recommendations = "recommendations"  # Group/refinement verification pass
    complete = "complete"        # Pipeline finished
```

**Assessment model additions** (add after `completed_at` field):
```python
pipeline_stage: PipelineStage = PipelineStage.scans
pipeline_stage_updated_at: Optional[datetime] = None
```

**Process flow bar** — horizontal step indicator rendered above the existing assessment content:
- 7 steps: Scans → Engines → Observations → Review → Grouping → Recommendations → Complete
- Each step shows: icon, label, status badge (pending/active/completed)
- Active step is highlighted; completed steps show checkmark
- "Advance" button appears on the currently active step when prerequisites are met

**Engine trigger endpoint** — `POST /api/assessments/{assessment_id}/advance-pipeline` (A6: plural route):
- Accepts `{"target_stage": "engines"}` (or other stages)
- For "engines": spawns background thread calling `run_preprocessing_engines`
- Reuses existing `_AssessmentScanJob` pattern (in-memory dict + JobRun + polling)
- Updates `pipeline_stage` on Assessment model
- Returns job status for polling

**Polling extension** (A7) — extend existing `/api/assessments/{assessment_id}/scan-status` response:
- Add separate `pipeline` object (does NOT overload scan job semantics):
  ```json
  {
    "run_status": { /* existing scan job fields unchanged */ },
    "pipeline": {
      "stage": "engines",
      "stage_updated_at": "2026-03-04T22:30:00Z",
      "active_run": {
        "status": "running",
        "message": "Running 6 engines...",
        "progress_percent": 45,
        "started_at": "2026-03-04T22:29:00Z",
        "finished_at": null,
        "job_type": "engines"
      }
    }
  }
  ```
- JS polls same endpoint, reads `response.pipeline.stage` to update flow bar

### Migration
```sql
ALTER TABLE assessment ADD COLUMN pipeline_stage VARCHAR(20) NOT NULL DEFAULT 'scans';
ALTER TABLE assessment ADD COLUMN pipeline_stage_updated_at DATETIME;
```

### Verification
- Flow bar renders with 7 steps on assessment detail page
- "Run Engines" button appears after scans complete
- Clicking button triggers engines in background, flow bar updates via polling
- All existing 320 tests still pass

---

## Phase 5B — Usage Analysis Properties + Efficient Query Tool

### What changes
Add 4 new properties for observation configuration. Create a `get_usage_count` MCP tool that efficiently queries ServiceNow for record counts using the existing `get_record_count()` method (X-Total-Count header — fetches only 1 row).

### Files to modify

| File | Change |
|------|--------|
| `src/services/integration_properties.py` | Add `SECTION_OBSERVATIONS` + 4 new property definitions + `ObservationProperties` frozen dataclass |
| `src/mcp/tools/core/get_usage_count.py` | **NEW** — MCP tool for efficient record count queries with date filtering |
| `src/mcp/registry.py` | Register `get_usage_count` tool |
| `tests/test_usage_count.py` | **NEW** — Tests for the usage count tool |

### Implementation details

**New properties** (add `SECTION_OBSERVATIONS` after `SECTION_REASONING`):

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `observations.usage_lookback_months` | int | 6 | How far back to look for usage data (3, 6, or 12 months) |
| `observations.max_usage_queries_per_result` | int | 2 | Max usage count queries per artifact (A8: caps query fanout) |
| `observations.batch_size` | int | 10 | How many ScanResults to process per observation batch |
| `observations.include_usage_queries` | select | "auto" | When to query instance for usage: "always", "auto", "never" |

**ObservationProperties frozen dataclass:**
```python
@dataclass(frozen=True)
class ObservationProperties:
    usage_lookback_months: int = 6
    max_usage_queries_per_result: int = 2  # A8: replaces usage_query_limit
    batch_size: int = 10
    include_usage_queries: str = "auto"
```

**get_usage_count tool** — efficiently checks if a ServiceNow artifact is still in use:
- **Input**: `instance_id`, `table` (e.g., "incident"), `query` (encoded query with date filter), `description` (what we're checking)
- **Behavior**:
  1. Loads ObservationProperties to get `usage_lookback_months`
  2. Appends date filter: `^sys_created_on>=javascript:gs.monthsAgo({months})` to query
  3. Calls existing `sn_client.get_record_count(table, query)` — uses X-Total-Count header (1 row fetched)
  4. Saves result as a `Fact` via existing facts system (for caching/reuse)
  5. Returns `{"count": int, "table": str, "query": str, "lookback_months": int, "cached": bool}`
- **Reuses**: `ServiceNowClient.get_record_count()` (sn_client.py line ~210), `Fact` model for caching

### Verification
- Properties appear in admin settings UI under "Observations" section
- `get_usage_count` returns accurate counts from test instance
- Facts are persisted after usage queries
- Subsequent calls return cached results

---

## Phase 5C — AI Observation Pipeline Tool + Background Job

### What changes
Create the `generate_observations` MCP pipeline tool that produces a landscape summary and per-artifact observations. Wire it into a background job triggered by the flow bar "Observations" button.

### Files to modify

| File | Change |
|------|--------|
| `src/mcp/tools/pipeline/generate_observations.py` | **NEW** — Main observation generation pipeline tool |
| `src/mcp/prompts/observation_prompt.py` | **NEW** — Prompt templates for landscape summary + per-artifact observations |
| `src/mcp/registry.py` | Register `generate_observations` tool + observation prompt |
| `src/server.py` | Add observation background job handler in `advance-pipeline` endpoint for `target_stage: "observations"` |
| `tests/test_generate_observations.py` | **NEW** — Tests for observation pipeline |

### Implementation details

**generate_observations tool** (A10: deterministic baseline + usage enrichment, no embedded LLM) — two-phase pipeline:

**Phase 1 — Landscape Summary:**
1. Load all customized ScanResults for the assessment (is_customized=True)
2. Group by scan_type for a summary view (counts per type, common patterns)
3. Build deterministic landscape summary from aggregated metadata (type distribution, update set overlap, common tables)
4. Store as a `GeneralRecommendation` (existing model) with category="landscape_summary"

**Phase 2 — Per-Artifact Observations (batched):**
1. Load ScanResults in batches (size from `observations.batch_size` property)
2. For each result:
   - Build context: type, name, table, update sets, code snippets
   - If `include_usage_queries` is "auto" or "always", check usage via `get_usage_count` (capped at `max_usage_queries_per_result` per A8)
   - Synthesize deterministic baseline observation from metadata + usage counts
   - Write to `ScanResult.observations` + `ai_observations` fields using existing `update_scan_result` tool logic
   - Set `review_status` to `pending_review`
3. Track progress via JobRun (queue_total = result count, queue_completed increments)

**Prompt design** (observation_prompt.py) — (A10: reference materials for external MCP clients, not runtime dependencies):
- `LANDSCAPE_SUMMARY_PROMPT` — orchestration guidance for AI-enhanced landscape analysis
- `ARTIFACT_OBSERVATION_PROMPT` — orchestration guidance for AI-enhanced per-artifact observations
  - Includes context about the artifact, its update sets, related code
  - If usage data available, includes count information
  - Output guidance: 2-4 sentence observation about relevance, risk, and potential disposition

**Background job integration:**
- When flow bar "Observations" button clicked → `POST /api/assessments/{assessment_id}/advance-pipeline` with `{"target_stage": "observations"}`
- Server spawns thread running `generate_observations`
- Reuses `_create_assessment_scan_run_record()` pattern for JobRun tracking
- Polling endpoint returns observation progress (X of Y results processed)

### Verification
- Landscape summary generated and stored as GeneralRecommendation
- Each customized ScanResult gets observations written
- Progress updates via polling during generation
- Usage count queries fire only when properties allow
- Flow bar advances to "observations" stage during processing

---

## Phase 5D — Observation UI Rendering + Human Review Gate

### What changes
Add observation display cards on the result detail page. Add review status controls (approve/edit buttons). Add a review gate on the flow bar that shows reviewed/pending counts and blocks advancement until review threshold met.

### Files to modify

| File | Change |
|------|--------|
| `src/web/templates/result_detail.html` | Add observations card with review controls in the main content area |
| `src/server.py` | Add `POST /api/result/{id}/review-status` endpoint for updating review status |
| `src/web/templates/assessment_detail.html` | Add review gate UI in flow bar (reviewed/pending counts, "Skip Review" option) |
| `src/web/static/css/style.css` | Add observation card + review control styles |
| `src/web/static/js/observation-review.js` | **NEW** — JS for inline observation editing + review status toggling |
| `tests/test_observation_ui.py` | **NEW** — Tests for observation rendering and review endpoints |

### Implementation details

**Observation card on result_detail.html:**
- Displayed in the main content area (not a tab — always visible for customized results)
- Shows: `observations` text, `ai_summary` if present, `review_status` badge
- Inline edit button → textarea for human edits to observations
- "Mark Reviewed" button → sets `review_status` to `reviewed`
- Uses existing `update_scan_result` tool's field set (observations, review_status)

**Review status endpoint** (A6: plural route):
```
POST /api/results/{result_id}/review-status
Body: {"review_status": "reviewed"} or {"review_status": "pending_review", "observations": "updated text"}
```
- Updates ScanResult.review_status (and optionally observations text)
- Returns updated result summary

**Review gate in flow bar:**
- When `pipeline_stage == "review"`:
  - Query: count of customized results with `review_status == "reviewed"` vs total customized
  - Display: "Reviewed: 45/62" with progress bar
  - "Proceed to Grouping" button enabled when all reviewed (or "Skip Review" to bypass)
  - "Skip Review" sets all remaining to `review_status = "reviewed"` in bulk

**observation-review.js:**
- Handles inline editing toggle (view mode ↔ edit mode)
- AJAX calls to review-status endpoint
- Updates badge and card state without full page reload

### Verification
- Observation text renders on result detail page for customized results
- Inline editing works — saves via AJAX
- "Mark Reviewed" updates status badge
- Flow bar shows accurate reviewed/pending counts
- "Proceed to Grouping" only enabled when gate criteria met
- "Skip Review" bulk-updates remaining results

---

## Phase 5E — Grouping + Recommendation Trigger Buttons

### What changes
Wire the existing `seed_feature_groups` and `run_feature_reasoning` tools into the flow bar buttons for the "grouping" and "recommendations" stages. These tools already exist from Phase 3/4 — this phase just adds the UI triggers and background job wrappers.

### Files to modify

| File | Change |
|------|--------|
| `src/server.py` | Add grouping + recommendation handlers in `advance-pipeline` endpoint |
| `src/web/templates/assessment_detail.html` | Wire flow bar buttons for grouping and recommendations stages |

### Implementation details

**Grouping trigger** (`target_stage: "grouping"`):
1. Spawns background thread
2. Calls existing `seed_feature_groups` tool (from P3D)
3. Updates pipeline_stage to "grouping" → "recommendations" on completion
4. JobRun tracks progress

**Recommendation trigger** (`target_stage: "recommendations"`) (A9):
1. Spawns background thread
2. Calls existing `run_feature_reasoning` tool (from P4A) as verification/refinement pass
3. Note: Actual recommendation records come from AI/orchestrator calling `upsert_feature_recommendation` — `run_feature_reasoning` does group refinement/verification
4. Updates pipeline_stage to "recommendations" → "complete" only when pass succeeds
5. JobRun tracks progress

**Flow bar final state:**
- "Complete" step shows summary: total features, total recommendations, total observations
- Links to features tab and grouping signals tab for detailed review

### Verification
- Grouping button triggers seed_feature_groups in background
- Recommendation button triggers run_feature_reasoning in background
- Flow bar advances through all stages
- End-to-end: Scans → Engines → Observations → Review → Grouping → Recommendations → Complete

---

## Implementation Order & Dependencies

```
5A (flow bar + engines) ──→ 5B (properties + usage tool) ──→ 5C (observation pipeline)
                                                                      │
                                                               5D (observation UI + review gate)
                                                                      │
                                                               5E (grouping + reco triggers)
```

**Batch 1:** 5A — Process flow bar + engine trigger (foundation for all subsequent phases)
**Batch 2:** 5B — Properties + usage count tool (needed by 5C)
**Batch 3:** 5C — Observation pipeline (core AI functionality)
**Batch 4:** 5D — Observation UI + review gate (human interaction layer)
**Batch 5:** 5E — Grouping + recommendation triggers (wiring existing tools)

---

## Key Reuse Points

| Existing Infrastructure | Reused In |
|------------------------|-----------|
| `_AssessmentScanJob` + `JobRun` + threading pattern | 5A, 5C, 5E background jobs |
| `integration_properties.py` frozen dataclass pattern | 5B observation properties |
| `sn_client.get_record_count()` (X-Total-Count header) | 5B get_usage_count tool |
| `Fact` model + `save_fact` upsert | 5B usage count caching |
| `ScanResult.observations` + `review_status` fields | 5C writes, 5D renders |
| `update_scan_result` tool field support | 5C observation writes, 5D review updates |
| `GeneralRecommendation` model | 5C landscape summary storage |
| `seed_feature_groups` tool (P3D) | 5E grouping trigger |
| `run_feature_reasoning` tool (P4A) | 5E recommendation trigger |
| Assessment detail page polling pattern | 5A flow bar polling |

---

## Verification Plan

After each phase:
1. Run full test suite — must stay green (currently 320)
2. Visual check: load assessment detail page, verify flow bar renders
3. After 5C: verify observations written to ScanResult records in DB
4. After 5D: verify inline editing and review gate logic
5. After 5E: full end-to-end pipeline walkthrough with test assessment

**End-to-end test:**
1. Open assessment detail page
2. Flow bar shows "Scans" as completed (assuming scans already done)
3. Click "Run Engines" → engines execute in background, flow bar advances
4. Click "Generate Observations" → deterministic baseline observations created, progress shown
5. Review observations on individual result pages, mark as reviewed
6. Flow bar shows review progress, enable "Proceed to Grouping"
7. Click grouping → features created
8. Click recommendations → AI recommendations generated
9. Flow bar shows "Complete"
