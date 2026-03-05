# Phase 7 — Pipeline Buttons + Re-run Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the 7-stage pipeline to 10 stages with 3 new AI stages (ai_analysis, ai_refinement, report), add human-triggered buttons for each stage, and implement re-run capability after completion.

**Architecture:** Extend the existing `PipelineStage` enum, `_PIPELINE_STAGE_ORDER` list, stage handler dispatch, and flow bar UI. New AI stage handlers will be placeholder stubs that call existing MCP prompts with DB context. The re-run button resets `pipeline_stage` to `ai_analysis` while preserving all human edits. A new `ai_analysis.batch_size` property controls batch processing.

**Tech Stack:** Python/SQLModel (models), FastAPI (server), Jinja2/HTML/JS (UI), SQLite (DB), pytest (tests)

**Design Doc:** `docs/plans/2026-03-05-phase7-pipeline-buttons-design.md`

---

## Task 1: Extend PipelineStage Enum

**Files:**
- Modify: `src/models.py:30-38` (PipelineStage enum)
- Test: `tests/test_phase7_pipeline_stages.py` (NEW)

**Step 1: Write the failing test**

Create `tests/test_phase7_pipeline_stages.py`:

```python
"""Tests for Phase 7 extended pipeline stages."""
from src.models import PipelineStage


def test_pipeline_stage_has_10_members():
    """Phase 7 adds ai_analysis, ai_refinement, report = 10 total."""
    assert len(PipelineStage) == 10


def test_pipeline_stage_ai_analysis_exists():
    assert PipelineStage.ai_analysis.value == "ai_analysis"


def test_pipeline_stage_ai_refinement_exists():
    assert PipelineStage.ai_refinement.value == "ai_refinement"


def test_pipeline_stage_report_exists():
    assert PipelineStage.report.value == "report"
```

**Step 2: Run test to verify it fails**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py -v`
Expected: FAIL — `PipelineStage` has 7 members, no `ai_analysis` attribute

**Step 3: Add 3 new enum members to PipelineStage**

Modify `src/models.py` lines 30-38. Replace the enum with:

```python
class PipelineStage(str, Enum):
    """Assessment reasoning pipeline stages after scans complete."""
    scans = "scans"
    ai_analysis = "ai_analysis"          # NEW: artifact_analyzer on customized results
    engines = "engines"
    observations = "observations"
    review = "review"
    grouping = "grouping"
    ai_refinement = "ai_refinement"      # NEW: relationship_tracer + technical_architect
    recommendations = "recommendations"
    report = "report"                     # NEW: report_writer generates deliverable
    complete = "complete"
```

Note the ORDER matters — `ai_analysis` comes after `scans` (before engines), `ai_refinement` after `grouping` (before recommendations), `report` after `recommendations` (before complete).

**Step 4: Run test to verify it passes**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py -v`
Expected: 4 PASS

**Step 5: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass (currently 396). Some tests may reference `_PIPELINE_STAGE_ORDER` length — fix in Task 2.

**Step 6: Commit**

```bash
cd tech-assessment-hub
git add src/models.py tests/test_phase7_pipeline_stages.py
git commit -m "feat: extend PipelineStage enum with ai_analysis, ai_refinement, report"
```

---

## Task 2: Update Pipeline Stage Configuration (server.py)

**Files:**
- Modify: `src/server.py:381-404` (`_PIPELINE_STAGE_ORDER`, `_PIPELINE_STAGE_LABELS`, `_PIPELINE_STAGE_AUTONEXT`)
- Test: `tests/test_phase7_pipeline_stages.py` (extend)

**Step 1: Write the failing tests**

Append to `tests/test_phase7_pipeline_stages.py`:

```python
from src.server import (
    _PIPELINE_STAGE_ORDER,
    _PIPELINE_STAGE_LABELS,
    _PIPELINE_STAGE_AUTONEXT,
)


def test_pipeline_stage_order_has_10_entries():
    assert len(_PIPELINE_STAGE_ORDER) == 10


def test_pipeline_stage_order_correct_sequence():
    expected = [
        "scans", "ai_analysis", "engines", "observations", "review",
        "grouping", "ai_refinement", "recommendations", "report", "complete",
    ]
    assert _PIPELINE_STAGE_ORDER == expected


def test_pipeline_stage_labels_has_all_10():
    assert len(_PIPELINE_STAGE_LABELS) == 10
    assert _PIPELINE_STAGE_LABELS["ai_analysis"] == "AI Analysis"
    assert _PIPELINE_STAGE_LABELS["ai_refinement"] == "AI Refinement"
    assert _PIPELINE_STAGE_LABELS["report"] == "Report"


def test_pipeline_stage_autonext_includes_new_stages():
    # ai_analysis auto-advances to engines (no human pause needed for engine run)
    assert _PIPELINE_STAGE_AUTONEXT.get("ai_analysis") == "engines"
    # ai_refinement auto-advances to recommendations
    assert _PIPELINE_STAGE_AUTONEXT.get("ai_refinement") == "recommendations"
    # report auto-advances to complete
    assert _PIPELINE_STAGE_AUTONEXT.get("report") == "complete"
```

**Step 2: Run test to verify it fails**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py -v`
Expected: FAIL on `_PIPELINE_STAGE_ORDER` length (7, not 10)

**Step 3: Update the 3 server.py config dicts**

Modify `src/server.py` lines 381-404. Replace the three dicts:

```python
_PIPELINE_STAGE_ORDER: List[str] = [
    PipelineStage.scans.value,
    PipelineStage.ai_analysis.value,
    PipelineStage.engines.value,
    PipelineStage.observations.value,
    PipelineStage.review.value,
    PipelineStage.grouping.value,
    PipelineStage.ai_refinement.value,
    PipelineStage.recommendations.value,
    PipelineStage.report.value,
    PipelineStage.complete.value,
]
_PIPELINE_STAGE_LABELS: Dict[str, str] = {
    PipelineStage.scans.value: "Scans",
    PipelineStage.ai_analysis.value: "AI Analysis",
    PipelineStage.engines.value: "Engines",
    PipelineStage.observations.value: "Observations",
    PipelineStage.review.value: "Review",
    PipelineStage.grouping.value: "Grouping",
    PipelineStage.ai_refinement.value: "AI Refinement",
    PipelineStage.recommendations.value: "Recommendations",
    PipelineStage.report.value: "Report",
    PipelineStage.complete.value: "Complete",
}
_PIPELINE_STAGE_AUTONEXT: Dict[str, str] = {
    PipelineStage.ai_analysis.value: PipelineStage.engines.value,
    PipelineStage.engines.value: PipelineStage.observations.value,
    PipelineStage.observations.value: PipelineStage.review.value,
    PipelineStage.grouping.value: PipelineStage.ai_refinement.value,
    PipelineStage.ai_refinement.value: PipelineStage.recommendations.value,
    PipelineStage.recommendations.value: PipelineStage.report.value,
    PipelineStage.report.value: PipelineStage.complete.value,
}
```

**Step 4: Run test to verify it passes**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
cd tech-assessment-hub
git add src/server.py tests/test_phase7_pipeline_stages.py
git commit -m "feat: update pipeline stage order, labels, and autonext for 10-stage pipeline"
```

---

## Task 3: Update advance-pipeline Endpoint (allowed_targets + re-run)

**Files:**
- Modify: `src/server.py:5987-6071` (`api_advance_pipeline_stage`)
- Test: `tests/test_phase7_pipeline_stages.py` (extend)

**Step 1: Write the failing tests**

Append to `tests/test_phase7_pipeline_stages.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.server import app
from src.models import Assessment, AssessmentState, AssessmentType, Instance


@pytest.fixture
def client():
    return TestClient(app)


def _seed_assessment_at_stage(db_session, stage_value):
    """Helper to create an assessment at a specific pipeline stage."""
    inst = Instance(
        name="p7-inst",
        url="https://p7.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()
    asmt = Assessment(
        instance_id=inst.id,
        name="P7 Test Assessment",
        number="ASMT0077700",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=stage_value,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    return asmt


def test_advance_pipeline_accepts_ai_analysis_target(db_session, client):
    """ai_analysis is a valid target_stage."""
    asmt = _seed_assessment_at_stage(db_session, "scans")
    with patch("src.server._start_assessment_pipeline_job", return_value=True):
        with patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None):
            res = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": "ai_analysis"},
            )
    assert res.status_code == 200


def test_advance_pipeline_accepts_ai_refinement_target(db_session, client):
    """ai_refinement is a valid target_stage."""
    asmt = _seed_assessment_at_stage(db_session, "grouping")
    with patch("src.server._start_assessment_pipeline_job", return_value=True):
        with patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None):
            res = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": "ai_refinement"},
            )
    assert res.status_code == 200


def test_advance_pipeline_accepts_report_target(db_session, client):
    """report is a valid target_stage."""
    asmt = _seed_assessment_at_stage(db_session, "recommendations")
    with patch("src.server._start_assessment_pipeline_job", return_value=True):
        with patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None):
            res = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": "report"},
            )
    assert res.status_code == 200


def test_advance_pipeline_rerun_resets_to_ai_analysis(db_session, client):
    """Re-run from complete resets to ai_analysis."""
    asmt = _seed_assessment_at_stage(db_session, "complete")
    with patch("src.server._start_assessment_pipeline_job", return_value=True):
        with patch("src.server._get_assessment_pipeline_job_snapshot", return_value=None):
            res = client.post(
                f"/api/assessments/{asmt.id}/advance-pipeline",
                json={"target_stage": "ai_analysis", "rerun": True},
            )
    assert res.status_code == 200
    result = res.json()
    assert result["success"] is True


def test_advance_pipeline_rerun_blocked_without_flag(db_session, client):
    """Cannot move backwards from complete to ai_analysis without rerun flag."""
    asmt = _seed_assessment_at_stage(db_session, "complete")
    res = client.post(
        f"/api/assessments/{asmt.id}/advance-pipeline",
        json={"target_stage": "ai_analysis"},
    )
    assert res.status_code == 409
```

**Step 2: Run test to verify it fails**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py::test_advance_pipeline_accepts_ai_analysis_target -v`
Expected: FAIL — `ai_analysis` not in `allowed_targets`

**Step 3: Update api_advance_pipeline_stage**

Modify `src/server.py` in the `api_advance_pipeline_stage` function:

1. Add new stages to `allowed_targets`:
```python
allowed_targets = {
    PipelineStage.ai_analysis.value,
    PipelineStage.engines.value,
    PipelineStage.observations.value,
    PipelineStage.review.value,
    PipelineStage.grouping.value,
    PipelineStage.ai_refinement.value,
    PipelineStage.recommendations.value,
    PipelineStage.report.value,
}
```

2. Add re-run logic BEFORE the backwards check. After `skip_review` and `force` parsing:
```python
rerun = bool(payload.get("rerun", False))

# Re-run: allow reset from complete back to ai_analysis
if rerun and current_stage == PipelineStage.complete.value and target_stage == PipelineStage.ai_analysis.value:
    # Reset pipeline stage to scans first, then start ai_analysis
    _set_assessment_pipeline_stage(assessment_id, PipelineStage.scans.value, session=session)
    started = _start_assessment_pipeline_job(
        assessment_id,
        target_stage=target_stage,
        skip_review=skip_review,
    )
    if not started:
        raise HTTPException(
            status_code=409,
            detail="A pipeline stage run is already active for this assessment.",
        )
    pipeline_run = _get_assessment_pipeline_job_snapshot(assessment_id, session=session)
    refreshed = session.get(Assessment, assessment_id)
    return {
        "success": True,
        "assessment_id": assessment_id,
        "requested_stage": target_stage,
        "current_stage": _pipeline_stage_value(refreshed.pipeline_stage if refreshed else assessment.pipeline_stage),
        "rerun": True,
        "pipeline_run": pipeline_run,
        "review_gate": _assessment_review_gate_summary(session, assessment_id),
    }
```

**Step 4: Run test to verify it passes**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
cd tech-assessment-hub
git add src/server.py tests/test_phase7_pipeline_stages.py
git commit -m "feat: add ai_analysis, ai_refinement, report to allowed_targets + re-run logic"
```

---

## Task 4: Add AI Stage Handlers (stub implementations)

**Files:**
- Modify: `src/server.py:1368-1470` (`_run_assessment_pipeline_stage`)
- Test: `tests/test_phase7_pipeline_stages.py` (extend)

**Step 1: Write the failing tests**

Append to `tests/test_phase7_pipeline_stages.py`:

```python
def test_ai_analysis_handler_runs_without_error(db_session):
    """ai_analysis stage handler executes successfully (stub)."""
    from src.server import _run_assessment_pipeline_stage
    asmt = _seed_assessment_at_stage(db_session, "scans")
    # Stub: should succeed even with no customized results
    _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")
    db_session.refresh(asmt)
    # Should auto-advance to engines
    assert asmt.pipeline_stage in ("ai_analysis", "engines", PipelineStage.engines.value)


def test_ai_refinement_handler_runs_without_error(db_session):
    """ai_refinement stage handler executes successfully (stub)."""
    from src.server import _run_assessment_pipeline_stage
    asmt = _seed_assessment_at_stage(db_session, "grouping")
    _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")
    db_session.refresh(asmt)
    assert asmt.pipeline_stage in ("ai_refinement", "recommendations", PipelineStage.recommendations.value)


def test_report_handler_runs_without_error(db_session):
    """report stage handler executes successfully (stub)."""
    from src.server import _run_assessment_pipeline_stage
    asmt = _seed_assessment_at_stage(db_session, "recommendations")
    _run_assessment_pipeline_stage(asmt.id, target_stage="report")
    db_session.refresh(asmt)
    assert asmt.pipeline_stage in ("report", "complete", PipelineStage.complete.value)
```

**Step 2: Run test to verify it fails**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py::test_ai_analysis_handler_runs_without_error -v`
Expected: FAIL — no handler branch for `ai_analysis`

**Step 3: Add stage handler branches**

In `_run_assessment_pipeline_stage()` (after the existing `elif stage == PipelineStage.review.value:` block), add new handler branches. Insert BEFORE the `next_stage = _PIPELINE_STAGE_AUTONEXT.get(stage)` line:

```python
        elif stage == PipelineStage.ai_analysis.value:
            # Phase 7 stub: AI analysis on customized artifacts
            # Future: calls artifact_analyzer MCP prompt per result
            from sqlmodel import select as sel
            customized_count = session.exec(
                sel(ScanResult).where(
                    ScanResult.scan_id.in_(
                        sel(Scan.id).where(Scan.assessment_id == assessment_id)
                    ),
                    ScanResult.is_customized == True,
                )
            ).all()
            processed = len(customized_count)
            success_message = f"AI Analysis stage completed ({processed} customized artifact(s) analyzed)."

        elif stage == PipelineStage.ai_refinement.value:
            # Phase 7 stub: relationship_tracer + technical_architect
            # Future: calls MCP prompts on complex clusters and flagged artifacts
            success_message = "AI Refinement stage completed."

        elif stage == PipelineStage.report.value:
            # Phase 7 stub: report_writer generates assessment deliverable
            # Future: calls report_writer MCP prompt with full assessment data
            success_message = "Report stage completed."
```

Note: These are intentionally stubs. The actual MCP prompt invocations will be wired in when the AI orchestration layer is built. The stubs allow the pipeline UI to work end-to-end now.

**Step 4: Run test to verify it passes**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
cd tech-assessment-hub
git add src/server.py tests/test_phase7_pipeline_stages.py
git commit -m "feat: add stub handlers for ai_analysis, ai_refinement, report pipeline stages"
```

---

## Task 5: Add ai_analysis.batch_size Property

**Files:**
- Modify: `src/services/integration_properties.py` (add property key + registration)
- Test: `tests/test_phase7_pipeline_stages.py` (extend)

**Step 1: Write the failing test**

Append to `tests/test_phase7_pipeline_stages.py`:

```python
def test_ai_analysis_batch_size_property_registered():
    """ai_analysis.batch_size property is in the property registry."""
    from src.services.integration_properties import (
        AI_ANALYSIS_BATCH_SIZE,
        SECTION_AI_ANALYSIS,
        _PROPERTY_REGISTRY,
    )
    assert AI_ANALYSIS_BATCH_SIZE == "ai_analysis.batch_size"
    # Find it in registry
    found = [p for p in _PROPERTY_REGISTRY if p.key == AI_ANALYSIS_BATCH_SIZE]
    assert len(found) == 1
    prop = found[0]
    assert prop.section == SECTION_AI_ANALYSIS
    assert prop.default == 0  # 0 = all at once
```

**Step 2: Run test to verify it fails**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py::test_ai_analysis_batch_size_property_registered -v`
Expected: FAIL — `AI_ANALYSIS_BATCH_SIZE` not found

**Step 3: Add the property**

In `src/services/integration_properties.py`:

1. Add section constant after `SECTION_OBSERVATIONS`:
```python
SECTION_AI_ANALYSIS = "AI Analysis"
```

2. Add it to `SECTION_ORDER` list (after SECTION_OBSERVATIONS):
```python
SECTION_ORDER: List[str] = [
    SECTION_GENERAL,
    SECTION_PREFLIGHT,
    SECTION_FETCH,
    SECTION_REASONING,
    SECTION_OBSERVATIONS,
    SECTION_AI_ANALYSIS,
]
```

3. Add property key after observation keys:
```python
# AI Analysis pipeline keys
AI_ANALYSIS_BATCH_SIZE = "ai_analysis.batch_size"
```

4. Add to `_PROPERTY_REGISTRY` list (find the list and add a new `PropertyDefinition`):
```python
PropertyDefinition(
    key=AI_ANALYSIS_BATCH_SIZE,
    label="AI Analysis Batch Size",
    section=SECTION_AI_ANALYSIS,
    prop_type="int",
    default=0,
    description="Number of artifacts to process per AI analysis batch. 0 = all at once. Set to 50+ for large assessments.",
),
```

**Step 4: Run test to verify it passes**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py::test_ai_analysis_batch_size_property_registered -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 6: Commit**

```bash
cd tech-assessment-hub
git add src/services/integration_properties.py tests/test_phase7_pipeline_stages.py
git commit -m "feat: add ai_analysis.batch_size property (default 0=all)"
```

---

## Task 6: Update Flow Bar HTML (10 steps)

**Files:**
- Modify: `src/web/templates/assessment_detail.html:127-178` (pipeline flow bar HTML)

**Step 1: Plan the HTML changes**

The flow bar currently has 7 `pipeline-step` divs. We need 10, inserted at the correct positions:
- After `scans` (step 1): insert `ai_analysis` (step 2)
- After `grouping` (step 6): insert `ai_refinement` (step 7)
- After `recommendations` (step 8): insert `report` (step 9)
- `complete` becomes step 10

**Step 2: Update the flow bar HTML**

Replace the entire `pipeline-flow-bar` div (lines 127-178) with:

```html
<div class="pipeline-flow-bar" id="pipelineFlowBar">
    <div class="pipeline-step" data-pipeline-step="scans">
        <div class="pipeline-step-circle" data-step-circle>1</div>
        <div class="pipeline-step-label">Scans</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="ai_analysis">
        <div class="pipeline-step-circle" data-step-circle>2</div>
        <div class="pipeline-step-label">AI Analysis</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="engines">
        <div class="pipeline-step-circle" data-step-circle>3</div>
        <div class="pipeline-step-label">Engines</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="observations">
        <div class="pipeline-step-circle" data-step-circle>4</div>
        <div class="pipeline-step-label">Observations</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="review">
        <div class="pipeline-step-circle" data-step-circle>5</div>
        <div class="pipeline-step-label">Review</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
        <div class="pipeline-review-progress" data-review-progress style="display:none;">
            <div class="pipeline-review-bar"><div class="pipeline-review-fill" data-review-fill></div></div>
            <div class="pipeline-review-count" data-review-count></div>
        </div>
    </div>
    <div class="pipeline-step" data-pipeline-step="grouping">
        <div class="pipeline-step-circle" data-step-circle>6</div>
        <div class="pipeline-step-label">Grouping</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="ai_refinement">
        <div class="pipeline-step-circle" data-step-circle>7</div>
        <div class="pipeline-step-label">AI Refinement</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="recommendations">
        <div class="pipeline-step-circle" data-step-circle>8</div>
        <div class="pipeline-step-label">Recommendations</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="report">
        <div class="pipeline-step-circle" data-step-circle>9</div>
        <div class="pipeline-step-label">Report</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
    </div>
    <div class="pipeline-step" data-pipeline-step="complete">
        <div class="pipeline-step-circle" data-step-circle>10</div>
        <div class="pipeline-step-label">Complete</div>
        <div class="pipeline-step-status" data-step-status></div>
        <div class="pipeline-step-action" data-step-action></div>
        <div class="pipeline-complete-links" data-complete-links style="display:none;">
            <a href="#features" class="pipeline-link" onclick="document.querySelector('[data-tab-btn=features]').click()">Features</a>
            <a href="#grouping-signals" class="pipeline-link" onclick="document.querySelector('[data-tab-btn=grouping-signals]').click()">Signals</a>
        </div>
    </div>
</div>
```

**Step 3: Run full test suite** (HTML changes are visual — tests verify server-side)

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 4: Commit**

```bash
cd tech-assessment-hub
git add src/web/templates/assessment_detail.html
git commit -m "feat: update flow bar HTML from 7 to 10 pipeline steps"
```

---

## Task 7: Update Flow Bar JavaScript (stages, actions, re-run button)

**Files:**
- Modify: `src/web/templates/assessment_detail.html:1452-1621` (JavaScript section)

**Step 1: Update _PIPELINE_STAGES array**

Replace line 1454:
```javascript
const _PIPELINE_STAGES = ['scans', 'ai_analysis', 'engines', 'observations', 'review', 'grouping', 'ai_refinement', 'recommendations', 'report', 'complete'];
```

**Step 2: Update _PIPELINE_LABELS**

Replace lines 1455-1459:
```javascript
const _PIPELINE_LABELS = {
    scans: 'Scans', ai_analysis: 'AI Analysis', engines: 'Engines',
    observations: 'Observations', review: 'Review', grouping: 'Grouping',
    ai_refinement: 'AI Refinement', recommendations: 'Recommendations',
    report: 'Report', complete: 'Complete',
};
```

**Step 3: Update _PIPELINE_ACTIONS**

Replace lines 1461-1467:
```javascript
const _PIPELINE_ACTIONS = {
    ai_analysis: { label: 'Run AI Analysis', target: 'ai_analysis' },
    engines: { label: 'Run Engines', target: 'engines' },
    observations: { label: 'Generate Observations', target: 'observations' },
    review: { label: 'Enter Review', target: 'review' },
    grouping: { label: 'Run Grouping', target: 'grouping' },
    ai_refinement: { label: 'Run AI Refinement', target: 'ai_refinement' },
    recommendations: { label: 'Run Recommendations', target: 'recommendations' },
    report: { label: 'Generate Report', target: 'report' },
};
```

**Step 4: Add re-run button in _renderStepActions**

In the `_renderStepActions` function, add handling for the `complete` stage. Currently line 1561 returns early for complete. Replace:

```javascript
if (!nextStage || nextStage === 'complete') return;
if (currentStage === 'complete') return;
```

With:

```javascript
if (currentStage === 'complete' && stage === 'complete') {
    // Re-run button
    const rerunBtn = document.createElement('button');
    rerunBtn.className = 'btn-pipeline btn-pipeline-rerun';
    rerunBtn.textContent = 'Re-run Analysis';
    rerunBtn.disabled = _pipelineAdvancing;
    rerunBtn.addEventListener('click', () => advancePipelineStageRerun());
    actionEl.appendChild(rerunBtn);
    return;
}
if (!nextStage) return;
```

**Step 5: Add advancePipelineStageRerun function**

After the `advancePipelineStage` function, add:

```javascript
async function advancePipelineStageRerun() {
    if (_pipelineAdvancing) return;
    if (!confirm('Re-run the full post-scan analysis pipeline? All human edits will be preserved as context.')) return;
    _pipelineAdvancing = true;

    try {
        const res = await fetch(`/api/assessments/${assessmentId}/advance-pipeline`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_stage: 'ai_analysis', rerun: true }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Request failed' }));
            alert('Re-run error: ' + (err.detail || 'Unknown error'));
            return;
        }

        refreshScanStatus();
    } catch (err) {
        alert('Re-run failed: ' + err.message);
    } finally {
        _pipelineAdvancing = false;
    }
}
```

**Step 6: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 7: Commit**

```bash
cd tech-assessment-hub
git add src/web/templates/assessment_detail.html
git commit -m "feat: update flow bar JS for 10 stages + re-run button"
```

---

## Task 8: Database Migration for Existing Assessments

**Files:**
- Create: `src/migrations/phase7_pipeline_stages.py` (NEW, if migration pattern exists) OR inline in models
- Test: `tests/test_phase7_pipeline_stages.py` (extend)

**Step 1: Write a test for existing assessment migration**

Append to `tests/test_phase7_pipeline_stages.py`:

```python
def test_existing_assessment_defaults_to_scans_pipeline_stage(db_session):
    """Assessments created before Phase 7 still have valid pipeline_stage."""
    inst = Instance(
        name="legacy-inst",
        url="https://legacy.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()
    asmt = Assessment(
        instance_id=inst.id,
        name="Legacy Assessment",
        number="ASMT0088800",
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    # Default should be "scans" — valid in new 10-stage enum
    assert asmt.pipeline_stage in (PipelineStage.scans, PipelineStage.scans.value, "scans")
```

**Step 2: Run test to verify it passes**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_pipeline_stages.py::test_existing_assessment_defaults_to_scans_pipeline_stage -v`
Expected: PASS (default is "scans" which is valid in both old and new enums)

Note: Since we're using SQLite with `create_all` and the PipelineStage enum is stored as a string, no explicit migration is needed. The old 7-value enum strings are all valid in the new 10-value enum. Any assessment at "engines" stays at "engines" — it just now has "ai_analysis" as a prior step rather than "scans".

**Step 3: Commit**

```bash
cd tech-assessment-hub
git add tests/test_phase7_pipeline_stages.py
git commit -m "test: verify existing assessments compatible with 10-stage pipeline"
```

---

## Task 9: Integration Test — Full Pipeline Flow

**Files:**
- Test: `tests/test_phase7_integration.py` (NEW)

**Step 1: Write integration tests**

Create `tests/test_phase7_integration.py`:

```python
"""Phase 7 integration tests — full pipeline stage progression."""
import pytest
from unittest.mock import patch

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    PipelineStage,
)
from src.server import (
    _PIPELINE_STAGE_ORDER,
    _PIPELINE_STAGE_LABELS,
    _PIPELINE_STAGE_AUTONEXT,
    _run_assessment_pipeline_stage,
)


def test_pipeline_10_stages_all_have_labels():
    """Every stage in _PIPELINE_STAGE_ORDER has a label."""
    for stage in _PIPELINE_STAGE_ORDER:
        assert stage in _PIPELINE_STAGE_LABELS, f"Missing label for stage: {stage}"


def test_pipeline_autonext_targets_are_valid_stages():
    """Every autonext target is a valid stage."""
    for source, target in _PIPELINE_STAGE_AUTONEXT.items():
        assert source in _PIPELINE_STAGE_ORDER, f"autonext source {source} not in stage order"
        assert target in _PIPELINE_STAGE_ORDER, f"autonext target {target} not in stage order"


def test_pipeline_autonext_target_follows_source():
    """Each autonext target must be the next stage after source."""
    for source, target in _PIPELINE_STAGE_AUTONEXT.items():
        source_idx = _PIPELINE_STAGE_ORDER.index(source)
        target_idx = _PIPELINE_STAGE_ORDER.index(target)
        assert target_idx == source_idx + 1, (
            f"autonext {source} -> {target}: target should be at index {source_idx + 1}, got {target_idx}"
        )


def test_enum_values_match_stage_order():
    """PipelineStage enum values should match _PIPELINE_STAGE_ORDER."""
    enum_values = [s.value for s in PipelineStage]
    assert enum_values == _PIPELINE_STAGE_ORDER


def test_new_ai_stages_present_in_enum():
    """Verify the 3 new Phase 7 stages exist."""
    assert hasattr(PipelineStage, "ai_analysis")
    assert hasattr(PipelineStage, "ai_refinement")
    assert hasattr(PipelineStage, "report")
```

**Step 2: Run integration tests**

Run: `cd tech-assessment-hub && python -m pytest tests/test_phase7_integration.py -v`
Expected: All PASS

**Step 3: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass

**Step 4: Commit**

```bash
cd tech-assessment-hub
git add tests/test_phase7_integration.py
git commit -m "test: add Phase 7 integration tests for 10-stage pipeline"
```

---

## Task 10: CSS Adjustments for 10-Step Flow Bar

**Files:**
- Modify: `src/web/static/css/style.css` (flow bar styles)

**Step 1: Check existing flow bar CSS**

The flow bar needs to fit 10 steps instead of 7. The steps are likely flex items. May need:
- Smaller font for step labels
- Narrower step width
- Compact layout for smaller screens

**Step 2: Add/update CSS**

Find the `.pipeline-flow-bar` and `.pipeline-step` rules in `style.css`. Add or update:

```css
/* Phase 7: 10-step flow bar — tighter spacing */
.pipeline-flow-bar {
    gap: 2px;  /* reduce from whatever current gap is */
}
.pipeline-step-label {
    font-size: 0.7rem;  /* slightly smaller for 10 labels */
}
/* Re-run button styling */
.btn-pipeline-rerun {
    background-color: #6366f1;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 0.75rem;
    cursor: pointer;
    margin-top: 4px;
}
.btn-pipeline-rerun:hover {
    background-color: #4f46e5;
}
```

**Step 3: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass (CSS-only change)

**Step 4: Commit**

```bash
cd tech-assessment-hub
git add src/web/static/css/style.css
git commit -m "style: adjust flow bar CSS for 10 steps + re-run button"
```

---

## Task 11: Final Verification + Summary Commit

**Step 1: Run full test suite**

Run: `cd tech-assessment-hub && python -m pytest --tb=short -q`
Expected: All tests pass (396 existing + new Phase 7 tests)

**Step 2: Verify flow bar renders**

Open assessment detail page in browser:
- Flow bar shows 10 steps: Scans → AI Analysis → Engines → Observations → Review → Grouping → AI Refinement → Recommendations → Report → Complete
- Each step has correct label and number
- Buttons appear on the active step
- "Re-run Analysis" button appears when at complete stage

**Step 3: Git status check**

Run: `cd tech-assessment-hub && git log --oneline -10`
Expected: See all Phase 7 commits

---

## Summary of Changes

| File | Change Type | Description |
|------|------------|-------------|
| `src/models.py` | Modified | Added 3 new PipelineStage enum members |
| `src/server.py` | Modified | Updated stage order/labels/autonext, added AI stage handlers, added re-run logic |
| `src/services/integration_properties.py` | Modified | Added `ai_analysis.batch_size` property |
| `src/web/templates/assessment_detail.html` | Modified | Updated flow bar HTML (10 steps) + JS (stages, actions, re-run) |
| `src/web/static/css/style.css` | Modified | Adjusted spacing for 10 steps + re-run button style |
| `tests/test_phase7_pipeline_stages.py` | Created | Unit tests for stage enum, config, endpoint, handlers |
| `tests/test_phase7_integration.py` | Created | Integration tests for pipeline consistency |

## Key Design Decisions

1. **Stub handlers** — AI stage handlers are stubs that complete immediately. Actual MCP prompt invocations will be wired later when the AI orchestration layer is built.
2. **Re-run via flag** — The `rerun: true` flag bypasses the backwards-movement guard. Only allowed from `complete` → `ai_analysis`.
3. **Auto-advance** — `ai_analysis` → `engines`, `ai_refinement` → `recommendations`, `report` → `complete` all auto-advance since they're background jobs.
4. **Human edits preserved** — Re-run doesn't clear any human edits. AI stubs will check for existing content when real handlers are implemented.
5. **AI rewriting** — When AI encounters human-written content, it MAY rewrite for flow/grammar/spelling but MUST preserve the human's core point.
