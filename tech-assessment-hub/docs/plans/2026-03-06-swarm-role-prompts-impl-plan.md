# Assessment Swarm Role Prompts — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the generic `_BATCH_PROMPT_TEMPLATE` with role-based prompt templates
(Team A Artifact Analyst, Team B Feature Builder, Validation Pass) and wire them into
the pipeline stage handlers for `local_subscription` mode.

**Architecture:** New `swarm_role_prompts.py` module holds the 3 role prompt templates
plus builders that inject domain knowledge from existing MCP prompts. The dispatcher gets
a `dispatch_stage_with_validation()` method that runs worker batches then a validation
pass. Pipeline stage handlers in `server.py` branch on `runtime_props.mode` to use either
the existing per-artifact loop or the role-based batch dispatch.

**Tech Stack:** Python, existing `ClaudeCodeDispatcher`, existing MCP prompt library,
existing properties system.

**Design Doc:** `docs/plans/2026-03-06-assessment-swarm-prompt-design.md`
**Prior Plan (Tasks 1-4 done):** `docs/plans/2026-03-06-claude-code-dispatch-impl-plan.md`

---

### Task 1: Shared rules block and Team A Worker prompt template

**Files:**
- Create: `tech-assessment-hub/src/services/swarm_role_prompts.py`
- Test: `tech-assessment-hub/tests/test_swarm_role_prompts.py`

**Step 1: Write failing tests for shared rules and Team A prompt builder**

```python
# tests/test_swarm_role_prompts.py
"""Tests for assessment swarm role prompt templates."""

import pytest

from src.services.swarm_role_prompts import (
    SHARED_RULES_BLOCK,
    build_team_a_prompt,
)


def test_shared_rules_block_has_scope_triage():
    """Shared rules block includes scope triage and disposition rules."""
    assert "SCOPE TRIAGE" in SHARED_RULES_BLOCK
    assert "disposition" in SHARED_RULES_BLOCK.lower()
    assert "review_in_progress" in SHARED_RULES_BLOCK
    assert "NEVER" in SHARED_RULES_BLOCK


def test_build_team_a_prompt_basic():
    """build_team_a_prompt produces a prompt with role identity and assessment context."""
    prompt = build_team_a_prompt(
        assessment_id=42,
        batch_index=0,
        total_batches=4,
        artifact_ids=[101, 102, 103],
    )
    assert "Artifact Analyst" in prompt
    assert "Team A" in prompt or "Functional Analysis" in prompt
    assert "Assessment ID: 42" in prompt
    assert "Batch: 1 of 4" in prompt
    assert "101" in prompt


def test_build_team_a_prompt_injects_domain_knowledge():
    """build_team_a_prompt injects artifact_analyzer domain knowledge."""
    prompt = build_team_a_prompt(
        assessment_id=1,
        batch_index=0,
        total_batches=1,
        artifact_ids=[1],
    )
    # Should contain content from ARTIFACT_ANALYZER_TEXT
    assert "scope" in prompt.lower()
    assert "get_result_detail" in prompt


def test_build_team_a_prompt_with_artifact_names():
    """build_team_a_prompt includes artifact names when provided."""
    prompt = build_team_a_prompt(
        assessment_id=1,
        batch_index=0,
        total_batches=1,
        artifact_ids=[101, 102],
        artifact_names=["My Script Include", "My Business Rule"],
    )
    assert "ID 101: My Script Include" in prompt
    assert "ID 102: My Business Rule" in prompt
```

**Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_swarm_role_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement shared rules block and Team A prompt**

```python
# src/services/swarm_role_prompts.py
"""Assessment swarm role prompt templates and builders.

V1 of the two-team swarm design (design doc: assessment-swarm-prompt-design.md).
Each dispatched `claude -p` agent gets a role identity, domain knowledge from existing
MCP prompts, and structured output format.

Roles:
- Team A Worker: Artifact Analyst (functional analysis)
- Team B Worker: Feature Builder (relationship & grouping)
- Validation Pass: Analysis Validator (quality gate)
"""

from __future__ import annotations

from typing import List, Optional

from src.mcp.prompts.artifact_analyzer import ARTIFACT_ANALYZER_TEXT
from src.mcp.prompts.tech_assessment import (
    FEATURE_REASONING_ORCHESTRATOR_TEXT,
)

# ── Shared rules injected into every role ──────────────────────────────

SHARED_RULES_BLOCK = """\
## Scope, Disposition & Review Rules (mandatory for all roles)

1. **SCOPE TRIAGE is FIRST STEP** for every artifact you process.
2. Scope decisions: in_scope | adjacent | out_of_scope | needs_review
3. Scope decisions are **preliminary** — may be revised in later stages.
4. **out_of_scope** artifacts are excluded from feature grouping AND deliverables.
5. **adjacent** means related but not a direct customization.
6. **review_status** stays `review_in_progress` throughout the pipeline.
   It only transitions to `reviewed` at the report stage after human confirmation.
7. **disposition** is NEVER set by AI agents. You may SUGGEST a disposition in
   observation text or recommendation text. The disposition field is only confirmed
   by a human reviewer.
"""

# ── Team A Worker: Artifact Analyst ────────────────────────────────────

_TEAM_A_WORKER_TEMPLATE = """\
# Role: Artifact Analyst (Team A — Functional Analysis)

**Identity:** You are an Artifact Analyst on a ServiceNow technical
assessment team. Your job is first-pass analysis: determine what each
artifact does and whether it is in scope.

**Authority:**
- You SET: scope flags (is_out_of_scope, is_adjacent), observations,
  review_status=review_in_progress
- You SUGGEST: disposition (in observation text only)
- You NEVER SET: disposition field, review_status=reviewed

## Domain Knowledge
{domain_knowledge}

{shared_rules}

## Assessment Context
- Assessment ID: {assessment_id}
- Batch: {batch_display} of {total_batches}

## Artifacts to Process
{artifact_list}

## Process (for each artifact)

1. **Read** artifact detail via `get_result_detail`
2. **SCOPE TRIAGE** (first step, always):
   - `in_scope` → directly customized. Proceed to full analysis.
   - `adjacent` → references assessed tables/data but not a direct
     customization. Set `is_adjacent=true`, write lighter observation.
   - `out_of_scope` → no relation or trivial OOTB mod.
     Set `is_out_of_scope=true`, brief reason, move on.
   - `needs_review` → unclear scope. Note uncertainty, skip deep analysis.
3. **If in_scope:** Write 2-4 sentence functional observation:
   - What does it do? What table? What trigger/condition?
   - If scriptable: summarize code behavior in plain English
   - Complexity: Simple / Moderate / Complex
   - Note grouping hints (update set name, naming pattern, etc.)
4. **If adjacent:** Write 1-2 sentence lighter observation
5. **If out_of_scope:** 1 sentence reason, move on
6. **Update** via `update_scan_result` with observations and scope flags

## Context Management

You are processing {artifact_count} artifacts in this batch.
- Read each artifact's detail — that is your context for THIS artifact
- After analyzing and writing your observation, **CLEAR mental context**
- Do NOT carry assumptions from one artifact to the next
- If you notice a relationship, note it in the observation but do NOT
  follow the rabbit hole — Team B handles relationships
- Token budget: ~500 tokens of context per artifact

## Output Format

After processing all artifacts, return a JSON summary:
{{"team": "functional_analysis", "batch": {batch_index},
  "total_batches": {total_batches}, "processed": <count>,
  "results": [
    {{"id": <id>, "name": "<name>", "scope": "<decision>",
      "complexity": "<level>", "observation_written": true,
      "grouping_hint": "<hint or null>"}}
  ],
  "summary": {{
    "in_scope": <n>, "adjacent": <n>, "out_of_scope": <n>,
    "patterns_noticed": ["<pattern>"]
  }}
}}
"""


def _build_artifact_list(
    artifact_ids: List[int],
    artifact_names: Optional[List[str]] = None,
) -> str:
    """Build the artifact list section for a prompt."""
    if artifact_names and len(artifact_names) == len(artifact_ids):
        return "\n".join(
            f"- ID {aid}: {name}"
            for aid, name in zip(artifact_ids, artifact_names)
        )
    return "\n".join(f"- ID {aid}" for aid in artifact_ids)


def build_team_a_prompt(
    *,
    assessment_id: int,
    batch_index: int,
    total_batches: int,
    artifact_ids: List[int],
    artifact_names: Optional[List[str]] = None,
) -> str:
    """Build prompt for a Team A Worker (Artifact Analyst) batch."""
    return _TEAM_A_WORKER_TEMPLATE.format(
        domain_knowledge=ARTIFACT_ANALYZER_TEXT,
        shared_rules=SHARED_RULES_BLOCK,
        assessment_id=assessment_id,
        batch_display=batch_index + 1,
        batch_index=batch_index,
        total_batches=total_batches,
        artifact_list=_build_artifact_list(artifact_ids, artifact_names),
        artifact_count=len(artifact_ids),
    )
```

**Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_swarm_role_prompts.py -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/swarm_role_prompts.py tech-assessment-hub/tests/test_swarm_role_prompts.py
git commit -m "feat: add Team A Worker (Artifact Analyst) role prompt template"
```

---

### Task 2: Team B Worker and Validation Pass prompt templates

**Files:**
- Modify: `tech-assessment-hub/src/services/swarm_role_prompts.py`
- Modify: `tech-assessment-hub/tests/test_swarm_role_prompts.py`

**Step 1: Write failing tests for Team B and Validation**

```python
# Append to tests/test_swarm_role_prompts.py

from src.services.swarm_role_prompts import (
    build_team_b_prompt,
    build_validation_prompt,
)


def test_build_team_b_prompt_basic():
    """build_team_b_prompt produces a prompt with Feature Builder role identity."""
    prompt = build_team_b_prompt(
        assessment_id=42,
        batch_index=0,
        total_batches=2,
        artifact_ids=[201, 202],
    )
    assert "Feature Builder" in prompt
    assert "Team B" in prompt or "Relationship" in prompt
    assert "Assessment ID: 42" in prompt
    assert "create_feature" in prompt


def test_build_team_b_prompt_injects_domain_knowledge():
    """build_team_b_prompt injects feature reasoning domain knowledge."""
    prompt = build_team_b_prompt(
        assessment_id=1,
        batch_index=0,
        total_batches=1,
        artifact_ids=[1],
    )
    # Should contain content from FEATURE_REASONING_ORCHESTRATOR_TEXT
    assert "feature" in prompt.lower()


def test_build_team_b_prompt_with_team_a_summary():
    """build_team_b_prompt includes Team A summary when provided."""
    prompt = build_team_b_prompt(
        assessment_id=1,
        batch_index=0,
        total_batches=1,
        artifact_ids=[1],
        team_a_summary="Found 15 in-scope artifacts with invoicing patterns.",
    )
    assert "invoicing patterns" in prompt


def test_build_validation_prompt_basic():
    """build_validation_prompt produces a validator role prompt."""
    prompt = build_validation_prompt(
        assessment_id=42,
        stage="ai_analysis",
    )
    assert "Validator" in prompt or "validator" in prompt
    assert "Assessment ID: 42" in prompt
    assert "ai_analysis" in prompt


def test_build_validation_prompt_includes_quality_checks():
    """Validation prompt includes scope consistency and observation quality checks."""
    prompt = build_validation_prompt(
        assessment_id=1,
        stage="ai_analysis",
    )
    assert "consistency" in prompt.lower() or "quality" in prompt.lower()
    assert "GeneralRecommendation" in prompt or "stage_validation" in prompt
```

**Step 2: Run tests, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_swarm_role_prompts.py -v`
Expected: FAIL with `ImportError`

**Step 3: Add Team B and Validation templates to swarm_role_prompts.py**

Append the following to `src/services/swarm_role_prompts.py`:

```python
# ── Team B Worker: Feature Builder ─────────────────────────────────────

_TEAM_B_WORKER_TEMPLATE = """\
# Role: Feature Builder (Team B — Relationship & Grouping)

**Identity:** You are a Feature Builder on a ServiceNow technical
assessment team. Team A has already analyzed these artifacts — you can
read their observations. Your job is to trace relationships and form
features.

**Authority:**
- You CREATE: features via `create_feature`, `add_result_to_feature`
- You UPDATE: feature names, descriptions, member lists
- You READ: Team A's observations from `ai_observations` field
- You NEVER SET: disposition field, review_status=reviewed

## Domain Knowledge
{domain_knowledge}

{shared_rules}

## Assessment Context
- Assessment ID: {assessment_id}
- Batch: {batch_display} of {total_batches}
{team_a_summary_section}

## Artifacts to Process
{artifact_list}

## Process

For each artifact in this batch:

1. **Read Team A's observation** (from `ai_observations` field) — this
   tells you what it does. Do not re-analyze functionality.
2. **Check grouping signals** (in priority order):
   a. **Update set siblings** (strongest) — artifacts captured together
   b. **Code cross-references** — Script A calls Script Include B
   c. **Naming patterns** — common prefixes/suffixes (e.g., `ACME_*`)
   d. **Table co-location** — multiple customizations on same table
   e. **Temporal proximity** — same author + close timestamp
3. **Decision tree:**
   a. OBVIOUS GROUPING — descriptive update set name or clear naming
      pattern → create feature immediately
   b. SIGNALS PRESENT but unclear — trace deeper via
      `get_update_set_contents`, check sibling artifacts
   c. STILL UNCLEAR — check non-customized records for evidence
   d. ISOLATED UTILITY — ACL, role, field with no signals →
      mark ungrouped
4. **For each feature formed/updated:**
   - Name based on what members DELIVER to users (not implementation)
   - Write 2-3 sentence summary of capability
   - List all member artifacts with their functional role

## Context Management

You ARE the relationship team — you NEED cross-artifact context.
Keep it structured:
- Keep a **RUNNING FEATURE MAP**: {{feature_name: [member_ids]}}
- Clear detailed artifact context after grouping it
- Carry forward only: feature names, member lists, 1-sentence summaries
- If a feature exceeds 15 members, consider splitting
- If you can't determine grouping after checking signals, mark
  "ungrouped" and move on — don't burn context forcing a grouping
- **Between iterations**: clear accumulated detail. Retain only the
  feature map and summaries.

## Output Format

{{"team": "relationship_grouping", "batch": {batch_index},
  "total_batches": {total_batches},
  "features_created": <n>, "features_updated": <n>, "ungrouped": <n>,
  "features": [
    {{"feature_id": <id>, "name": "<name>", "action": "created|updated",
      "members": [<ids>],
      "summary": "<what this feature delivers>"}}
  ],
  "ungrouped_artifacts": [<ids>],
  "ungrouped_reason": "<why no grouping>"
}}
"""


def build_team_b_prompt(
    *,
    assessment_id: int,
    batch_index: int,
    total_batches: int,
    artifact_ids: List[int],
    artifact_names: Optional[List[str]] = None,
    team_a_summary: Optional[str] = None,
) -> str:
    """Build prompt for a Team B Worker (Feature Builder) batch."""
    summary_section = ""
    if team_a_summary:
        summary_section = f"- Team A Summary: {team_a_summary}"

    return _TEAM_B_WORKER_TEMPLATE.format(
        domain_knowledge=FEATURE_REASONING_ORCHESTRATOR_TEXT,
        shared_rules=SHARED_RULES_BLOCK,
        assessment_id=assessment_id,
        batch_display=batch_index + 1,
        batch_index=batch_index,
        total_batches=total_batches,
        artifact_list=_build_artifact_list(artifact_ids, artifact_names),
        team_a_summary_section=summary_section,
    )


# ── Validation Pass: Analysis Validator ────────────────────────────────

_VALIDATION_PASS_TEMPLATE = """\
# Role: Analysis Validator (Post-Worker Quality Gate)

**Identity:** You are a senior reviewer validating worker outputs for
an assessment. You check quality, catch conflicts, and produce a
summary for the next team or stage.

**Authority:**
- You READ: all worker outputs from the DB
- You UPDATE: scope flags and observations if conflicts found
- You WRITE: summary as a GeneralRecommendation record (category:
  "stage_validation")
- You NEVER SET: disposition field, review_status=reviewed

{shared_rules}

## Assessment Context
- Assessment ID: {assessment_id}
- Stage being validated: {stage}

## Validation Checks

### If validating Team A (ai_analysis / observations):
1. **Scope consistency:** Same-table artifacts getting consistent scope?
2. **Observation quality:** Grounded in evidence? Code summaries present?
3. **Coverage:** Any artifacts skipped or with empty observations?

### If validating Team B (grouping / ai_refinement):
1. **Feature coherence:** Do features make functional sense?
2. **Orphan check:** In-scope artifacts not assigned to any feature?
3. **Over-merge check:** Features with >20 members likely need splitting

## Process
1. Use `get_customizations` to list all customized results
2. Sample-check observations/features for quality
3. Flag any conflicts or gaps
4. Write summary as GeneralRecommendation (category: "stage_validation")

## Output

{{"team": "validation", "stage_validated": "{stage}",
  "quality_score": <0.0-1.0>,
  "issues_found": <n>,
  "issues": [
    {{"type": "<scope_conflict|missing_observation|over_merged|...>",
      "artifacts": [<ids>],
      "description": "<what's wrong>"}}
  ],
  "summary_for_next_team": {{
    "total_customized": <n>,
    "in_scope": <n>,
    "adjacent": <n>,
    "out_of_scope": <n>,
    "key_patterns": ["<pattern>"],
    "features_formed": <n>,
    "coverage_pct": <0-100>
  }}
}}
"""


def build_validation_prompt(
    *,
    assessment_id: int,
    stage: str,
) -> str:
    """Build prompt for a Validation Pass (V1 Lead substitute)."""
    return _VALIDATION_PASS_TEMPLATE.format(
        shared_rules=SHARED_RULES_BLOCK,
        assessment_id=assessment_id,
        stage=stage,
    )
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_swarm_role_prompts.py -v`
Expected: 9 PASS

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/swarm_role_prompts.py tech-assessment-hub/tests/test_swarm_role_prompts.py
git commit -m "feat: add Team B Worker and Validation Pass role prompt templates"
```

---

### Task 3: Context budgets and validation tool set

**Files:**
- Modify: `tech-assessment-hub/src/services/ai_stage_tool_sets.py`
- Modify: `tech-assessment-hub/tests/test_ai_stage_tool_sets.py`

**Step 1: Write failing tests**

```python
# Append to tests/test_ai_stage_tool_sets.py

from src.services.ai_stage_tool_sets import CONTEXT_BUDGETS, VALIDATION_TOOL_SET


def test_context_budgets_has_all_stages():
    """Every AI stage has a context budget defined."""
    expected = {"ai_analysis", "observations", "ai_refinement", "grouping",
                "recommendations", "report"}
    assert expected == set(CONTEXT_BUDGETS.keys())


def test_context_budgets_have_batch_size():
    """Each budget defines batch_size and max_output_tokens."""
    for stage, budget in CONTEXT_BUDGETS.items():
        assert "batch_size" in budget, f"{stage} missing batch_size"
        assert "max_output_tokens" in budget, f"{stage} missing max_output_tokens"
        assert budget["batch_size"] > 0


def test_validation_tool_set_is_read_heavy():
    """Validation tool set focuses on reading + writing recommendations."""
    assert any("get_customizations" in t for t in VALIDATION_TOOL_SET)
    assert any("save_general_recommendation" in t or "get_assessment_results" in t
               for t in VALIDATION_TOOL_SET)
```

**Step 2: Run tests, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_ai_stage_tool_sets.py -v`
Expected: FAIL with `ImportError`

**Step 3: Add CONTEXT_BUDGETS and VALIDATION_TOOL_SET**

Append to `src/services/ai_stage_tool_sets.py`:

```python
CONTEXT_BUDGETS: Dict[str, Dict[str, int]] = {
    "ai_analysis": {
        "batch_size": 20,
        "max_output_tokens": 8000,
    },
    "observations": {
        "batch_size": 15,
        "max_output_tokens": 10000,
    },
    "grouping": {
        "batch_size": 10,
        "max_output_tokens": 12000,
    },
    "ai_refinement": {
        "batch_size": 10,
        "max_output_tokens": 12000,
    },
    "recommendations": {
        "batch_size": 8,
        "max_output_tokens": 15000,
    },
    "report": {
        "batch_size": 5,
        "max_output_tokens": 20000,
    },
}

VALIDATION_TOOL_SET: List[str] = [
    f"{_PREFIX}get_customizations",
    f"{_PREFIX}get_assessment_results",
    f"{_PREFIX}get_result_detail",
    f"{_PREFIX}save_general_recommendation",
    f"{_PREFIX}feature_grouping_status",
    f"{_PREFIX}get_feature_detail",
    f"{_PREFIX}update_scan_result",
]
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_ai_stage_tool_sets.py -v`
Expected: 7 PASS (4 existing + 3 new)

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/ai_stage_tool_sets.py tech-assessment-hub/tests/test_ai_stage_tool_sets.py
git commit -m "feat: add context budgets and validation tool set"
```

---

### Task 4: dispatch_stage_with_validation on ClaudeCodeDispatcher

**Files:**
- Modify: `tech-assessment-hub/src/services/claude_code_dispatcher.py`
- Modify: `tech-assessment-hub/tests/test_claude_code_dispatcher.py`

**Step 1: Write failing test**

```python
# Append to tests/test_claude_code_dispatcher.py

def test_dispatch_stage_with_validation():
    """dispatch_stage_with_validation runs workers then a validation pass."""
    worker_calls = []
    validation_calls = []

    with patch("src.services.claude_code_dispatcher._find_claude_binary",
               return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")

    def fake_dispatch_batch(prompt, *, stage, assessment_id, batch_index,
                            total_batches, allowed_tools=None):
        if "Validator" in prompt or "validation" in prompt.lower():
            validation_calls.append(batch_index)
        else:
            worker_calls.append(batch_index)
        return DispatchResult(
            success=True, batch_index=batch_index,
            total_batches=total_batches,
            artifacts_processed=5, duration_seconds=1.0,
        )

    with patch.object(d, "dispatch_batch", side_effect=fake_dispatch_batch):
        results = d.dispatch_stage_with_validation(
            worker_prompt_builder=lambda ids: f"Worker batch {ids}",
            validation_prompt_builder=lambda: "Validator prompt",
            artifact_ids=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            stage="ai_analysis",
            assessment_id=42,
            batch_size=5,
        )

    assert len(worker_calls) == 2  # 10 / 5
    assert len(validation_calls) == 1  # validation pass
    assert len(results["worker_results"]) == 2
    assert results["validation_result"].success is True


def test_dispatch_stage_with_validation_skips_validation_on_failure():
    """If all worker batches fail, validation is skipped."""
    with patch("src.services.claude_code_dispatcher._find_claude_binary",
               return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")

    with patch.object(d, "dispatch_batch", return_value=DispatchResult(
        success=False, batch_index=0, total_batches=1,
        artifacts_processed=0, error="all failed",
    )):
        results = d.dispatch_stage_with_validation(
            worker_prompt_builder=lambda ids: "worker",
            validation_prompt_builder=lambda: "validator",
            artifact_ids=[1, 2],
            stage="ai_analysis",
            assessment_id=1,
            batch_size=2,
        )

    assert results["validation_result"] is None
    assert results["worker_results"][0].success is False
```

**Step 2: Run test, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py::test_dispatch_stage_with_validation -v`
Expected: FAIL with `AttributeError`

**Step 3: Implement dispatch_stage_with_validation**

Add to `ClaudeCodeDispatcher` class in `claude_code_dispatcher.py`:

```python
    def dispatch_stage_with_validation(
        self,
        worker_prompt_builder: Callable[[List[int]], str],
        validation_prompt_builder: Callable[[], str],
        artifact_ids: List[int],
        *,
        stage: str,
        assessment_id: int,
        batch_size: int,
        worker_tools: Optional[List[str]] = None,
        validation_tools: Optional[List[str]] = None,
        on_batch_complete: Optional[Callable[["DispatchResult"], None]] = None,
    ) -> dict:
        """Run worker batches then a validation pass.

        Returns dict with "worker_results" (List[DispatchResult]) and
        "validation_result" (DispatchResult or None if skipped).
        """
        # Phase 1: Worker batches
        worker_results = self.dispatch_stage(
            prompt_builder=worker_prompt_builder,
            artifact_ids=artifact_ids,
            stage=stage,
            assessment_id=assessment_id,
            batch_size=batch_size,
            allowed_tools=worker_tools,
            on_batch_complete=on_batch_complete,
        )

        # Phase 2: Validation pass (only if at least one worker succeeded)
        any_success = any(r.success for r in worker_results)
        validation_result = None
        if any_success:
            validation_prompt = validation_prompt_builder()
            validation_result = self.dispatch_batch(
                validation_prompt,
                stage=stage,
                assessment_id=assessment_id,
                batch_index=0,
                total_batches=1,
                allowed_tools=validation_tools,
            )
            if on_batch_complete and validation_result:
                on_batch_complete(validation_result)

        return {
            "worker_results": worker_results,
            "validation_result": validation_result,
        }
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py -v`
Expected: 13 PASS (11 existing + 2 new)

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/claude_code_dispatcher.py tech-assessment-hub/tests/test_claude_code_dispatcher.py
git commit -m "feat: add dispatch_stage_with_validation for worker + validation pass flow"
```

---

### Task 5: Stage-to-role mapping and prompt router

**Files:**
- Modify: `tech-assessment-hub/src/services/swarm_role_prompts.py`
- Modify: `tech-assessment-hub/tests/test_swarm_role_prompts.py`

**Step 1: Write failing test for prompt router**

```python
# Append to tests/test_swarm_role_prompts.py

from src.services.swarm_role_prompts import get_worker_prompt_builder


def test_get_worker_prompt_builder_ai_analysis():
    """ai_analysis stage returns Team A prompt builder."""
    builder = get_worker_prompt_builder("ai_analysis")
    prompt = builder(assessment_id=1, batch_index=0, total_batches=1, artifact_ids=[1])
    assert "Artifact Analyst" in prompt


def test_get_worker_prompt_builder_grouping():
    """grouping stage returns Team B prompt builder."""
    builder = get_worker_prompt_builder("grouping")
    prompt = builder(assessment_id=1, batch_index=0, total_batches=1, artifact_ids=[1])
    assert "Feature Builder" in prompt


def test_get_worker_prompt_builder_unknown_raises():
    """Unknown stage raises ValueError."""
    with pytest.raises(ValueError, match="No worker prompt"):
        get_worker_prompt_builder("unknown_stage")
```

**Step 2: Run tests, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_swarm_role_prompts.py -v -k "prompt_builder"`
Expected: FAIL

**Step 3: Implement prompt router**

Append to `src/services/swarm_role_prompts.py`:

```python
# ── Stage → Role Mapping ──────────────────────────────────────────────

# Maps pipeline stage names to the builder function for worker prompts.
# Team A stages use Artifact Analyst; Team B stages use Feature Builder.
_STAGE_TO_TEAM = {
    "ai_analysis": "team_a",
    "observations": "team_a",
    "grouping": "team_b",
    "ai_refinement": "team_b",
    "recommendations": "team_b",
    "report": "team_a",  # report workers do functional assembly
}


def get_worker_prompt_builder(stage: str):
    """Return the correct prompt builder function for a pipeline stage.

    Returns a callable with signature:
        (assessment_id, batch_index, total_batches, artifact_ids, **kwargs) -> str
    """
    team = _STAGE_TO_TEAM.get(stage)
    if team == "team_a":
        return build_team_a_prompt
    elif team == "team_b":
        return build_team_b_prompt
    else:
        raise ValueError(f"No worker prompt defined for stage '{stage}'")
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_swarm_role_prompts.py -v`
Expected: 12 PASS

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/swarm_role_prompts.py tech-assessment-hub/tests/test_swarm_role_prompts.py
git commit -m "feat: add stage-to-role mapping and prompt router"
```

---

### Task 6: Wire dispatcher into server.py ai_analysis stage

This integrates the role-based dispatch into the `ai_analysis` stage handler.
When `runtime_props.mode == "local_subscription"`, the per-artifact loop is
replaced with a batched `dispatch_stage_with_validation()` call.

**Files:**
- Modify: `tech-assessment-hub/src/server.py` (~lines 1613-1791)
- Modify: `tech-assessment-hub/tests/test_phase11c_pipeline_integration.py`

**Step 1: Write failing integration test**

```python
# Append to tests/test_phase11c_pipeline_integration.py

def test_ai_analysis_dispatches_with_role_prompts(db_session):
    """When mode=local_subscription, ai_analysis uses role-based batch dispatch."""
    inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage="ai_analysis")
    # Seed a customized scan result
    scan = Scan(
        instance_id=inst.id, assessment_id=asmt.id,
        scan_type=ScanType.table_scan, status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()
    sr = ScanResult(
        scan_id=scan.id, name="test_br",
        table_name="sys_script", origin_type=OriginType.modified_ootb,
    )
    db_session.add(sr)
    db_session.commit()

    dispatch_calls = []

    mock_worker_result = DispatchResult(
        success=True, batch_index=0, total_batches=1,
        artifacts_processed=1, duration_seconds=1.0,
    )
    mock_validation_result = DispatchResult(
        success=True, batch_index=0, total_batches=1,
        artifacts_processed=0, duration_seconds=0.5,
    )

    def fake_dispatch_batch(prompt, *, stage, assessment_id, batch_index,
                            total_batches, allowed_tools=None):
        dispatch_calls.append({"stage": stage, "batch_index": batch_index})
        if "Validator" in prompt:
            return mock_validation_result
        return mock_worker_result

    with patch("src.server.load_ai_runtime_properties") as mock_rt, \
         patch("src.server.ClaudeCodeDispatcher") as mock_cls:
        from src.services.integration_properties import AIRuntimeProperties
        mock_rt.return_value = AIRuntimeProperties(mode="local_subscription", model="opus")
        mock_instance = mock_cls.return_value
        mock_instance.dispatch_batch.side_effect = fake_dispatch_batch
        mock_instance.dispatch_stage.side_effect = (
            ClaudeCodeDispatcher.dispatch_stage.__get__(mock_instance)
        )
        mock_instance.dispatch_stage_with_validation.side_effect = (
            ClaudeCodeDispatcher.dispatch_stage_with_validation.__get__(mock_instance)
        )

        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    # Should have dispatched worker + validation batches
    assert len(dispatch_calls) >= 1
```

**Step 2: Run test, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_phase11c_pipeline_integration.py::test_ai_analysis_dispatches_with_role_prompts -v`
Expected: FAIL (ClaudeCodeDispatcher not imported, dispatch branch not in code)

**Step 3: Add local_subscription dispatch branch to ai_analysis**

In `server.py`, add imports near the top (with other service imports):
```python
from .services.claude_code_dispatcher import ClaudeCodeDispatcher
from .services.ai_stage_tool_sets import STAGE_TOOL_SETS, CONTEXT_BUDGETS, VALIDATION_TOOL_SET
from .services.swarm_role_prompts import get_worker_prompt_builder, build_validation_prompt
```

Add a helper near `_try_registered_prompt_text` (~line 1520):
```python
def _resolve_mcp_config_path() -> str:
    """Resolve path to .mcp.json for Claude Code dispatch."""
    here = Path(__file__).resolve().parent  # src/
    for candidate in [here.parent / ".mcp.json", here.parent.parent / ".mcp.json"]:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "No .mcp.json found. Required for local_subscription Claude Code dispatch."
    )
```

In the `ai_analysis` stage handler, after loading `ai_props` and `pipeline_prompt_props`
(~line 1617), add a mode check BEFORE the DFS/sequential branch:

```python
            runtime_props = load_ai_runtime_properties(
                session, instance_id=assessment.instance_id
            )

            if runtime_props.mode == "local_subscription":
                # ---- Local subscription: role-based batch dispatch ----
                customized = session.exec(
                    select(ScanResult)
                    .join(Scan, ScanResult.scan_id == Scan.id)
                    .where(Scan.assessment_id == assessment_id)
                    .where(ScanResult.origin_type.in_(list(_CUSTOMIZED_ORIGIN_VALUES)))
                    .order_by(ScanResult.id.asc())
                ).all()
                total = len(customized)
                if total == 0:
                    success_message = "AI Analysis stage completed (0 customized artifacts)."
                else:
                    artifact_ids = [sr.id for sr in customized]
                    artifact_names = [sr.name or "" for sr in customized]
                    budget = CONTEXT_BUDGETS.get(stage, {})
                    batch_size = budget.get("batch_size", 20)

                    prompt_builder_fn = get_worker_prompt_builder(stage)

                    def worker_prompt_builder(ids):
                        names = []
                        for aid in ids:
                            match = next((sr for sr in customized if sr.id == aid), None)
                            names.append(match.name if match else "")
                        return prompt_builder_fn(
                            assessment_id=assessment_id,
                            batch_index=0,  # overridden by dispatcher
                            total_batches=1,  # overridden by dispatcher
                            artifact_ids=ids,
                            artifact_names=names,
                        )

                    dispatcher = ClaudeCodeDispatcher(
                        mcp_config_path=_resolve_mcp_config_path(),
                        model=runtime_props.model,
                        per_batch_budget_usd=min(
                            runtime_props.assessment_soft_limit_usd / max(total, 1),
                            runtime_props.assessment_hard_limit_usd,
                        ),
                    )

                    def on_batch_done(result):
                        pct = 15 + int((result.batch_index + 1)
                                       / result.total_batches * 80)
                        _set_assessment_pipeline_job_state(
                            assessment_id, stage=stage, status="running",
                            message=f"Batch {result.batch_index + 1}/{result.total_batches} done.",
                            progress_percent=pct,
                        )

                    stage_result = dispatcher.dispatch_stage_with_validation(
                        worker_prompt_builder=worker_prompt_builder,
                        validation_prompt_builder=lambda: build_validation_prompt(
                            assessment_id=assessment_id, stage=stage,
                        ),
                        artifact_ids=artifact_ids,
                        stage=stage,
                        assessment_id=assessment_id,
                        batch_size=batch_size,
                        worker_tools=STAGE_TOOL_SETS.get(stage),
                        validation_tools=VALIDATION_TOOL_SET,
                        on_batch_complete=on_batch_done,
                    )

                    worker_ok = sum(1 for r in stage_result["worker_results"]
                                    if r.success)
                    success_message = (
                        f"AI Analysis dispatched: {worker_ok}/{len(stage_result['worker_results'])} "
                        f"batches succeeded, validation={'passed' if stage_result['validation_result'] and stage_result['validation_result'].success else 'skipped/failed'}."
                    )
                    telemetry_details["ai_analysis"] = {
                        "mode": "local_subscription",
                        "customized_total": total,
                        "batches": len(stage_result["worker_results"]),
                        "batches_succeeded": worker_ok,
                    }

            elif ai_props.enable_depth_first and graph and len(graph.adjacency) > 0:
                # ... existing DFS code unchanged ...
```

Note: The `elif` replaces the existing `if` for the DFS branch. The sequential `else`
branch remains unchanged.

**Step 4: Run integration test**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_phase11c_pipeline_integration.py::test_ai_analysis_dispatches_with_role_prompts -v`
Expected: PASS

**Step 5: Run full test suite to verify no regressions**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`
Expected: All tests PASS (existing tests run the non-local_subscription path)

**Step 6: Commit**

```bash
git add tech-assessment-hub/src/server.py tech-assessment-hub/tests/test_phase11c_pipeline_integration.py
git commit -m "feat: wire role-based swarm dispatch into ai_analysis pipeline stage"
```

---

### Task 7: Wire remaining AI stages

**Files:**
- Modify: `tech-assessment-hub/src/server.py`
- Modify: `tech-assessment-hub/tests/test_phase11c_pipeline_integration.py`

Each remaining AI stage needs the same `local_subscription` branch at the top of its
handler. The pattern is identical to Task 6:

1. Load `runtime_props`
2. Check `runtime_props.mode == "local_subscription"`
3. Query customized artifacts (or features for Team B stages)
4. Create `ClaudeCodeDispatcher`
5. Call `dispatch_stage_with_validation()` with appropriate prompt builders
6. Track results in telemetry_details

**Step 1: Add local_subscription branch to observations stage handler**

In the `observations` stage handler (~line 1819), add the branch before the existing
`generate_observations_handle()` call. The observations stage uses Team A Workers in
enrichment mode — same `build_team_a_prompt` but the stage name signals enrichment.

**Step 2: Add local_subscription branch to grouping stage handler**

In the `grouping` stage handler (~line 1898), add before `seed_feature_groups_handle()`.
Uses Team B Workers via `build_team_b_prompt`.

**Step 3: Add local_subscription branch to ai_refinement stage handler**

In the `ai_refinement` stage handler (~line 1948), add before the 3 sub-steps.
Uses Team B Workers in refinement mode.

**Step 4: Add local_subscription branch to recommendations stage handler**

In the `recommendations` stage handler (~line 2239), add before
`run_feature_reasoning_handle()`. Uses Team B Workers.

**Step 5: Add local_subscription branch to report stage handler**

In the `report` stage handler (~line 2368), add before the report data aggregation.
Uses Team A Workers for narrative assembly.

**Step 6: Write parameterized integration test**

```python
# Append to tests/test_phase11c_pipeline_integration.py

@pytest.mark.parametrize("stage", [
    "observations", "grouping", "ai_refinement", "recommendations", "report",
])
def test_remaining_stages_dispatch_when_local_subscription(db_session, stage):
    """All AI stages dispatch to Claude Code when mode=local_subscription."""
    inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage=stage)
    # Seed minimal data
    scan = Scan(
        instance_id=inst.id, assessment_id=asmt.id,
        scan_type=ScanType.table_scan, status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()
    sr = ScanResult(
        scan_id=scan.id, name="test_artifact",
        table_name="sys_script", origin_type=OriginType.modified_ootb,
    )
    db_session.add(sr)
    db_session.commit()

    with patch("src.server.load_ai_runtime_properties") as mock_rt, \
         patch("src.server.ClaudeCodeDispatcher") as mock_cls:
        from src.services.integration_properties import AIRuntimeProperties
        mock_rt.return_value = AIRuntimeProperties(
            mode="local_subscription", model="opus"
        )
        mock_instance = mock_cls.return_value
        mock_instance.dispatch_stage_with_validation.return_value = {
            "worker_results": [DispatchResult(
                success=True, batch_index=0, total_batches=1,
                artifacts_processed=1, duration_seconds=1.0,
            )],
            "validation_result": None,
        }

        _run_assessment_pipeline_stage(asmt.id, target_stage=stage)

    mock_cls.assert_called_once()
    mock_instance.dispatch_stage_with_validation.assert_called_once()
```

**Step 7: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`
Expected: All tests PASS

**Step 8: Commit**

```bash
git add tech-assessment-hub/src/server.py tech-assessment-hub/tests/test_phase11c_pipeline_integration.py
git commit -m "feat: wire role-based swarm dispatch into all AI pipeline stages"
```

---

### Task 8: End-to-end manual verification

This is a manual verification step — no automated test.

**Step 1: Verify web app is running**

Run: `curl -s http://localhost:8080/health | head -1`

**Step 2: Verify .mcp.json exists**

Check: `cat /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/.mcp.json | head -5`

**Step 3: Test Claude Code CLI directly with a role prompt**

```bash
echo "Use the tech-assessment-hub tools. Call get_customizations with assessment_id=1 and return the count." | \
  claude -p \
    --output-format json \
    --mcp-config /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/.mcp.json \
    --permission-mode bypassPermissions \
    --no-session-persistence \
    --max-budget-usd 1.00
```

**Step 4: Set local_subscription mode and run a pipeline stage**

1. Open http://localhost:8080
2. Set `ai_runtime.mode` to `local_subscription` in properties
3. Navigate to an assessment at the `ai_analysis` stage
4. Click "Run Stage"
5. Watch progress — should show batch progress, not per-artifact
6. Check `ScanResult.ai_observations` for worker-written observations
7. Check `GeneralRecommendation` for `stage_validation` records

**Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: adjustments from end-to-end swarm dispatch testing"
```

---

## Summary

| Task | Description | Files | New Tests |
|------|-------------|-------|-----------|
| 1 | Shared rules + Team A Worker prompt | Create `swarm_role_prompts.py` | 4 |
| 2 | Team B Worker + Validation Pass prompts | Modify `swarm_role_prompts.py` | 5 |
| 3 | Context budgets + validation tool set | Modify `ai_stage_tool_sets.py` | 3 |
| 4 | `dispatch_stage_with_validation()` method | Modify `claude_code_dispatcher.py` | 2 |
| 5 | Stage-to-role mapping + prompt router | Modify `swarm_role_prompts.py` | 3 |
| 6 | Wire ai_analysis stage | Modify `server.py` | 1 |
| 7 | Wire remaining AI stages | Modify `server.py` | 5 (parameterized) |
| 8 | Manual end-to-end verification | — | — |

**Total: ~23 new automated tests, 1 new file, 4 modified files**
