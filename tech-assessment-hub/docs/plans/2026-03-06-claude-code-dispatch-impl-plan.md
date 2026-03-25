# Claude Code Pipeline Dispatch — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When `AIRuntimeProperties.mode == "local_subscription"`, pipeline AI stages
automatically invoke `claude -p` to process artifacts in batches via MCP tools.

**Architecture:** New `ClaudeCodeDispatcher` service calls the Claude CLI as a
one-shot process per batch. Each batch gets a prompt (from the existing prompt registry)
plus a batch header with artifact IDs and instructions. Claude reads/writes assessment
data through MCP tools. Pipeline verifies results and tracks progress.

**Tech Stack:** Python `subprocess`, Claude Code CLI (`/opt/homebrew/bin/claude`),
existing MCP tool registry, existing properties system.

**Design Doc:** `docs/plans/2026-03-06-claude-code-pipeline-dispatch.md`

---

### Task 1: DispatchResult dataclass and CLI command builder

**Files:**
- Create: `tech-assessment-hub/src/services/claude_code_dispatcher.py`
- Test: `tech-assessment-hub/tests/test_claude_code_dispatcher.py`

**Step 1: Write the failing test for DispatchResult**

```python
# tests/test_claude_code_dispatcher.py
"""Tests for ClaudeCodeDispatcher — Claude CLI dispatch for local_subscription mode."""

import json
import subprocess
from dataclasses import asdict
from unittest.mock import patch, MagicMock

import pytest

from src.services.claude_code_dispatcher import (
    DispatchResult,
    ClaudeCodeDispatcher,
)


def test_dispatch_result_dataclass():
    """DispatchResult holds batch outcome with all required fields."""
    r = DispatchResult(
        success=True,
        batch_index=0,
        total_batches=4,
        artifacts_processed=50,
        claude_output={"processed": 50},
        error=None,
        duration_seconds=12.3,
        budget_used_usd=0.42,
    )
    d = asdict(r)
    assert d["success"] is True
    assert d["batch_index"] == 0
    assert d["artifacts_processed"] == 50
    assert d["budget_used_usd"] == 0.42
```

**Step 2: Run test to verify it fails**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py::test_dispatch_result_dataclass -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.claude_code_dispatcher'`

**Step 3: Write DispatchResult and the init of ClaudeCodeDispatcher**

```python
# src/services/claude_code_dispatcher.py
"""Claude Code CLI dispatcher for local_subscription AI mode.

Spawns `claude -p` one batch at a time. Each batch is a one-shot CLI call
that reads/writes assessment data through MCP tools, then exits.

Future strategies (parallel, swarm) plug in via the `strategy` parameter
on `dispatch_stage()` without changing the pipeline integration in server.py.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

_CLAUDE_BIN: Optional[str] = None


def _find_claude_binary() -> str:
    """Locate the claude CLI. Cached after first call."""
    global _CLAUDE_BIN
    if _CLAUDE_BIN is None:
        path = shutil.which("claude")
        if not path:
            raise RuntimeError(
                "Claude Code CLI not found on PATH. "
                "Install from https://claude.ai/download or ensure 'claude' is in PATH."
            )
        _CLAUDE_BIN = path
    return _CLAUDE_BIN


@dataclass
class DispatchResult:
    """Outcome of one batch dispatched to Claude Code CLI."""
    success: bool
    batch_index: int
    total_batches: int
    artifacts_processed: int
    claude_output: Optional[dict] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    budget_used_usd: Optional[float] = None


class ClaudeCodeDispatcher:
    """Dispatches AI work to Claude Code CLI for local_subscription mode.

    Each batch is a single `claude -p` call that starts, does its work, and exits.
    In V1 (single strategy), batches run one at a time.

    Future: `dispatch_stage(strategy="concurrent")` will use ThreadPoolExecutor.
    Future: `dispatch_stage(strategy="swarm")` will use multi-role coordination.
    """

    def __init__(
        self,
        mcp_config_path: str,
        model: str = "opus",
        per_batch_budget_usd: float = 5.0,
        stage_timeout_seconds: int = 300,
    ) -> None:
        self.mcp_config_path = mcp_config_path
        self.model = model
        self.per_batch_budget_usd = per_batch_budget_usd
        self.stage_timeout_seconds = stage_timeout_seconds
        self._claude_bin = _find_claude_binary()

    def _build_command(self, allowed_tools: Optional[List[str]] = None) -> List[str]:
        """Build the claude CLI command list. Prompt is piped via stdin."""
        cmd = [
            self._claude_bin, "-p",
            "--output-format", "json",
            "--model", self.model,
            "--max-budget-usd", str(self.per_batch_budget_usd),
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--mcp-config", self.mcp_config_path,
        ]
        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])
        return cmd
```

**Step 4: Run test to verify it passes**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py::test_dispatch_result_dataclass -v`
Expected: PASS

**Step 5: Write test for _build_command**

```python
# Append to tests/test_claude_code_dispatcher.py

def test_build_command_basic():
    """_build_command produces correct CLI flags."""
    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(
            mcp_config_path="/tmp/.mcp.json",
            model="sonnet",
            per_batch_budget_usd=2.5,
        )
    cmd = d._build_command()
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd
    assert "--output-format" in cmd
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "json"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert "--max-budget-usd" in cmd
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2.5"
    assert "--mcp-config" in cmd
    assert cmd[cmd.index("--mcp-config") + 1] == "/tmp/.mcp.json"
    assert "--allowedTools" not in cmd


def test_build_command_with_allowed_tools():
    """_build_command appends --allowedTools when provided."""
    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")
    cmd = d._build_command(allowed_tools=[
        "mcp__tech-assessment-hub__get_result_detail",
        "mcp__tech-assessment-hub__update_scan_result",
    ])
    assert "--allowedTools" in cmd
    idx = cmd.index("--allowedTools")
    assert "mcp__tech-assessment-hub__get_result_detail" in cmd[idx + 1]
    assert "mcp__tech-assessment-hub__update_scan_result" in cmd[idx + 1]
```

**Step 6: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py -v`
Expected: 3 PASS

**Step 7: Commit**

```bash
git add tech-assessment-hub/src/services/claude_code_dispatcher.py tech-assessment-hub/tests/test_claude_code_dispatcher.py
git commit -m "feat: add ClaudeCodeDispatcher skeleton with DispatchResult and command builder"
```

---

### Task 2: dispatch_batch — run one batch through Claude CLI

**Files:**
- Modify: `tech-assessment-hub/src/services/claude_code_dispatcher.py`
- Modify: `tech-assessment-hub/tests/test_claude_code_dispatcher.py`

**Step 1: Write failing test for dispatch_batch success path**

```python
# Append to tests/test_claude_code_dispatcher.py

def test_dispatch_batch_success():
    """dispatch_batch calls subprocess and returns parsed result."""
    mock_output = json.dumps({
        "result": "some analysis",
        "cost_usd": 0.15,
    })
    fake_completed = subprocess.CompletedProcess(
        args=["claude"], returncode=0,
        stdout=mock_output, stderr="",
    )
    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"), \
         patch("subprocess.run", return_value=fake_completed) as mock_run:
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")
        result = d.dispatch_batch(
            prompt="Analyze these artifacts",
            stage="ai_analysis",
            assessment_id=42,
            batch_index=0,
            total_batches=4,
        )
    assert result.success is True
    assert result.batch_index == 0
    assert result.total_batches == 4
    assert result.error is None
    assert result.claude_output is not None
    # Verify subprocess was called with prompt on stdin
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("input") == "Analyze these artifacts"
```

**Step 2: Run test, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py::test_dispatch_batch_success -v`
Expected: FAIL with `AttributeError: 'ClaudeCodeDispatcher' object has no attribute 'dispatch_batch'`

**Step 3: Implement dispatch_batch**

Add to `ClaudeCodeDispatcher` class in `claude_code_dispatcher.py`:

```python
    def dispatch_batch(
        self,
        prompt: str,
        *,
        stage: str,
        assessment_id: int,
        batch_index: int,
        total_batches: int,
        allowed_tools: Optional[List[str]] = None,
    ) -> DispatchResult:
        """Run one batch through Claude Code CLI.

        Pipes the prompt via stdin, captures JSON output from stdout.
        """
        cmd = self._build_command(allowed_tools=allowed_tools)
        start = time.monotonic()
        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.stage_timeout_seconds,
            )
            duration = time.monotonic() - start
            if completed.returncode != 0:
                return DispatchResult(
                    success=False,
                    batch_index=batch_index,
                    total_batches=total_batches,
                    artifacts_processed=0,
                    error=f"CLI exited {completed.returncode}: {completed.stderr[:500]}",
                    duration_seconds=duration,
                )
            # Parse JSON output
            claude_output = self._parse_output(completed.stdout)
            return DispatchResult(
                success=True,
                batch_index=batch_index,
                total_batches=total_batches,
                artifacts_processed=claude_output.get("processed", 0) if claude_output else 0,
                claude_output=claude_output,
                duration_seconds=duration,
                budget_used_usd=claude_output.get("cost_usd") if claude_output else None,
            )
        except subprocess.TimeoutExpired:
            return DispatchResult(
                success=False,
                batch_index=batch_index,
                total_batches=total_batches,
                artifacts_processed=0,
                error=f"Timeout after {self.stage_timeout_seconds}s",
                duration_seconds=time.monotonic() - start,
            )
        except Exception as exc:
            return DispatchResult(
                success=False,
                batch_index=batch_index,
                total_batches=total_batches,
                artifacts_processed=0,
                error=str(exc),
                duration_seconds=time.monotonic() - start,
            )

    @staticmethod
    def _parse_output(stdout: str) -> Optional[dict]:
        """Parse Claude CLI JSON output. Tolerates non-JSON preamble."""
        stdout = stdout.strip()
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # Claude --output-format json wraps in {"type":"result","result":"..."}
            # Try to find the last JSON object in stdout
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        continue
            logger.warning("Could not parse Claude output as JSON (len=%d)", len(stdout))
            return {"raw_output": stdout[:2000]}
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py -v`
Expected: 4 PASS

**Step 5: Write test for timeout and error paths**

```python
# Append to tests/test_claude_code_dispatcher.py

def test_dispatch_batch_timeout():
    """dispatch_batch handles subprocess timeout."""
    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=300)):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")
        result = d.dispatch_batch(
            prompt="test", stage="ai_analysis",
            assessment_id=1, batch_index=0, total_batches=1,
        )
    assert result.success is False
    assert "Timeout" in result.error


def test_dispatch_batch_nonzero_exit():
    """dispatch_batch handles non-zero exit code."""
    fake = subprocess.CompletedProcess(
        args=["claude"], returncode=1,
        stdout="", stderr="Error: budget exceeded",
    )
    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"), \
         patch("subprocess.run", return_value=fake):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")
        result = d.dispatch_batch(
            prompt="test", stage="ai_analysis",
            assessment_id=1, batch_index=2, total_batches=4,
        )
    assert result.success is False
    assert "budget exceeded" in result.error
    assert result.batch_index == 2
```

**Step 6: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py -v`
Expected: 6 PASS

**Step 7: Commit**

```bash
git add tech-assessment-hub/src/services/claude_code_dispatcher.py tech-assessment-hub/tests/test_claude_code_dispatcher.py
git commit -m "feat: implement dispatch_batch with timeout and error handling"
```

---

### Task 3: dispatch_stage — single-session batch orchestration

**Files:**
- Modify: `tech-assessment-hub/src/services/claude_code_dispatcher.py`
- Modify: `tech-assessment-hub/tests/test_claude_code_dispatcher.py`

**Step 1: Write failing test**

```python
# Append to tests/test_claude_code_dispatcher.py

def test_dispatch_stage_single_session_batches():
    """dispatch_stage splits artifact_ids into batches and calls dispatch_batch per batch."""
    calls = []

    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")

    def fake_dispatch_batch(prompt, *, stage, assessment_id, batch_index, total_batches, allowed_tools=None):
        calls.append(batch_index)
        return DispatchResult(
            success=True, batch_index=batch_index, total_batches=total_batches,
            artifacts_processed=3, duration_seconds=1.0,
        )

    with patch.object(d, "dispatch_batch", side_effect=fake_dispatch_batch):
        results = d.dispatch_stage(
            prompt_builder=lambda ids: f"Analyze {ids}",
            artifact_ids=[1, 2, 3, 4, 5, 6, 7, 8, 9],
            stage="ai_analysis",
            assessment_id=42,
            batch_size=3,
        )
    assert len(results) == 3  # 9 artifacts / 3 per batch
    assert calls == [0, 1, 2]
    assert all(r.success for r in results)
```

**Step 2: Run test, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py::test_dispatch_stage_sequential_batches -v`
Expected: FAIL

**Step 3: Implement dispatch_stage**

Add to `ClaudeCodeDispatcher` class:

```python
    def dispatch_stage(
        self,
        prompt_builder: Callable[[List[int]], str],
        artifact_ids: List[int],
        *,
        stage: str,
        assessment_id: int,
        batch_size: int,
        strategy: str = "single",
        max_concurrent: int = 1,
        allowed_tools: Optional[List[str]] = None,
        on_batch_complete: Optional[Callable[[DispatchResult], None]] = None,
    ) -> List[DispatchResult]:
        """Run a full stage in batches.

        V1: strategy="single" — one batch at a time.
        V2+: strategy="concurrent" — up to max_concurrent via ThreadPoolExecutor.
        V3+: strategy="swarm" — coordinated multi-role sessions.
        """
        if strategy not in ("single",):
            raise NotImplementedError(f"Strategy '{strategy}' not yet implemented (V2+)")

        if batch_size <= 0:
            batch_size = len(artifact_ids) or 1

        batches = [
            artifact_ids[i:i + batch_size]
            for i in range(0, max(len(artifact_ids), 1), batch_size)
        ]
        total_batches = len(batches)
        results: List[DispatchResult] = []

        for batch_index, batch_ids in enumerate(batches):
            prompt = prompt_builder(batch_ids)
            result = self.dispatch_batch(
                prompt,
                stage=stage,
                assessment_id=assessment_id,
                batch_index=batch_index,
                total_batches=total_batches,
                allowed_tools=allowed_tools,
            )
            results.append(result)
            if on_batch_complete:
                on_batch_complete(result)

            if not result.success:
                logger.warning(
                    "Batch %d/%d failed for stage=%s assessment=%d: %s",
                    batch_index + 1, total_batches, stage, assessment_id, result.error,
                )

        return results
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py -v`
Expected: 7 PASS

**Step 5: Write test for on_batch_complete callback and batch_size=0**

```python
# Append to tests/test_claude_code_dispatcher.py

def test_dispatch_stage_callback():
    """on_batch_complete is called after each batch."""
    callback_results = []

    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")

    with patch.object(d, "dispatch_batch", return_value=DispatchResult(
        success=True, batch_index=0, total_batches=1,
        artifacts_processed=5, duration_seconds=1.0,
    )):
        d.dispatch_stage(
            prompt_builder=lambda ids: "test",
            artifact_ids=[1, 2, 3, 4, 5],
            stage="ai_analysis", assessment_id=1, batch_size=5,
            on_batch_complete=lambda r: callback_results.append(r),
        )
    assert len(callback_results) == 1


def test_dispatch_stage_batch_size_zero_means_all():
    """batch_size=0 processes all artifacts in one batch."""
    with patch("src.services.claude_code_dispatcher._find_claude_binary", return_value="/usr/bin/claude"):
        d = ClaudeCodeDispatcher(mcp_config_path="/tmp/.mcp.json")

    with patch.object(d, "dispatch_batch", return_value=DispatchResult(
        success=True, batch_index=0, total_batches=1,
        artifacts_processed=10, duration_seconds=1.0,
    )):
        results = d.dispatch_stage(
            prompt_builder=lambda ids: f"all {len(ids)}",
            artifact_ids=list(range(10)),
            stage="grouping", assessment_id=1, batch_size=0,
        )
    assert len(results) == 1
```

**Step 6: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_claude_code_dispatcher.py -v`
Expected: 9 PASS

**Step 7: Commit**

```bash
git add tech-assessment-hub/src/services/claude_code_dispatcher.py tech-assessment-hub/tests/test_claude_code_dispatcher.py
git commit -m "feat: implement dispatch_stage with single-session batching and callbacks"
```

---

### Task 4: Stage tool sets and prompt template builder

**Files:**
- Create: `tech-assessment-hub/src/services/ai_stage_tool_sets.py`
- Test: `tech-assessment-hub/tests/test_ai_stage_tool_sets.py`

**Step 1: Write failing test**

```python
# tests/test_ai_stage_tool_sets.py
"""Tests for per-stage tool set definitions and prompt template builder."""

import pytest

from src.services.ai_stage_tool_sets import (
    STAGE_TOOL_SETS,
    build_batch_prompt,
)


def test_stage_tool_sets_has_all_ai_stages():
    """Every AI stage has a tool set defined."""
    expected = {"ai_analysis", "observations", "ai_refinement", "grouping", "recommendations", "report"}
    assert expected == set(STAGE_TOOL_SETS.keys())


def test_stage_tool_sets_are_prefixed():
    """All tool names use the mcp__tech-assessment-hub__ prefix."""
    for stage, tools in STAGE_TOOL_SETS.items():
        for tool in tools:
            assert tool.startswith("mcp__tech-assessment-hub__"), f"{stage}: {tool}"


def test_build_batch_prompt_basic():
    """build_batch_prompt produces a prompt with assessment and batch metadata."""
    prompt = build_batch_prompt(
        stage_instructions="Analyze each artifact for complexity.",
        assessment_id=42,
        stage="ai_analysis",
        batch_index=0,
        total_batches=4,
        artifact_ids=[101, 102, 103],
    )
    assert "Assessment ID: 42" in prompt
    assert "ai_analysis" in prompt
    assert "Batch: 1 of 4" in prompt
    assert "101" in prompt
    assert "Analyze each artifact for complexity." in prompt
```

**Step 2: Run test, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_ai_stage_tool_sets.py -v`
Expected: FAIL

**Step 3: Implement ai_stage_tool_sets.py**

```python
# src/services/ai_stage_tool_sets.py
"""Per-stage tool restrictions and prompt template for Claude Code dispatch.

Each AI pipeline stage gets only the MCP tools it needs. This is safer
(limits blast radius) and cheaper (less tool schema in context window).
"""

from __future__ import annotations

from typing import Dict, List, Optional

_PREFIX = "mcp__tech-assessment-hub__"

STAGE_TOOL_SETS: Dict[str, List[str]] = {
    "ai_analysis": [
        f"{_PREFIX}get_customizations",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}update_scan_result",
    ],
    "observations": [
        f"{_PREFIX}generate_observations",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}get_customizations",
    ],
    "ai_refinement": [
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_result_detail",
        f"{_PREFIX}feature_grouping_status",
    ],
    "grouping": [
        f"{_PREFIX}create_feature",
        f"{_PREFIX}add_result_to_feature",
        f"{_PREFIX}feature_grouping_status",
        f"{_PREFIX}get_customizations",
    ],
    "recommendations": [
        f"{_PREFIX}feature_recommendation",
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_customizations",
    ],
    "report": [
        f"{_PREFIX}assessment_results",
        f"{_PREFIX}feature_detail",
        f"{_PREFIX}get_customizations",
    ],
}

_BATCH_PROMPT_TEMPLATE = """\
You are a ServiceNow technical assessment AI. You have access to the
tech-assessment-hub MCP tools to read and write assessment data.

## Task
{stage_instructions}

## Assessment
- Assessment ID: {assessment_id}
- Stage: {stage}
- Batch: {batch_display} of {total_batches}

## Artifacts to Process
{artifact_list}

## Instructions
1. SCOPE TRIAGE FIRST: For each artifact, read its basic details and decide:
   - "in_scope" → proceed to full analysis
   - "adjacent" → related but not a direct customization (e.g., references assessed
     tables/data); set is_adjacent=true, lighter analysis
   - "out_of_scope" → no relation to the assessed app or trivial OOTB modification;
     set is_out_of_scope=true with brief observation, skip deep analysis
   - "needs_review" → unclear scope; set observation noting uncertainty, skip deep analysis
2. For in-scope artifacts, analyze according to the stage requirements above.
3. Write your findings back using the update/write tools.
4. Set review_status to "review_in_progress" — NEVER set it to "reviewed".
   Review status only transitions to "reviewed" at the report stage after human confirmation.
5. Do NOT set a final disposition. You may suggest a disposition in your observations
   or recommendation text, but the disposition field is only confirmed by a human reviewer.
6. Be thorough but efficient — stay within your tool set.
7. Scope decisions are preliminary and may be revised in later pipeline stages
   as more context is uncovered (relationships, feature groupings, usage data).
   Out-of-scope artifacts are excluded from feature grouping and final deliverables.

## Output
After processing all artifacts, summarize what you did as a JSON object:
{{"processed": <count>, "findings": [<brief summary per artifact>]}}
"""


def build_batch_prompt(
    *,
    stage_instructions: str,
    assessment_id: int,
    stage: str,
    batch_index: int,
    total_batches: int,
    artifact_ids: List[int],
    artifact_names: Optional[List[str]] = None,
) -> str:
    """Build the full prompt for one batch dispatch."""
    if artifact_names and len(artifact_names) == len(artifact_ids):
        artifact_list = "\n".join(
            f"- ID {aid}: {name}" for aid, name in zip(artifact_ids, artifact_names)
        )
    else:
        artifact_list = "\n".join(f"- ID {aid}" for aid in artifact_ids)

    return _BATCH_PROMPT_TEMPLATE.format(
        stage_instructions=stage_instructions,
        assessment_id=assessment_id,
        stage=stage,
        batch_display=batch_index + 1,
        total_batches=total_batches,
        artifact_list=artifact_list,
    )
```

**Step 4: Run tests**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_ai_stage_tool_sets.py -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/ai_stage_tool_sets.py tech-assessment-hub/tests/test_ai_stage_tool_sets.py
git commit -m "feat: add per-stage tool sets and batch prompt template builder"
```

---

### Task 5: Integrate dispatcher into pipeline ai_analysis stage

This is the surgical change to `server.py` that wires up the dispatcher for the
`ai_analysis` stage. Other stages follow the same pattern in Task 6.

**Files:**
- Modify: `tech-assessment-hub/src/server.py` (lines ~1605-1780)
- Modify: `tech-assessment-hub/tests/test_phase11c_pipeline_integration.py`

**Step 1: Write failing integration test**

```python
# Append to tests/test_phase11c_pipeline_integration.py

def test_ai_analysis_dispatches_to_claude_code_when_local_subscription(db_session):
    """When mode=local_subscription and use_registered_prompts=True,
    ai_analysis stage dispatches each batch to Claude Code CLI."""
    inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage="ai_analysis")

    # Create a customized scan result
    scan = Scan(
        instance_id=inst.id, assessment_id=asmt.id,
        scan_type=ScanType.table_scan, status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()
    sr = ScanResult(
        scan_id=scan.id, name="test_script_include",
        table_name="sys_script_include", origin_type=OriginType.modified_ootb,
    )
    db_session.add(sr)
    db_session.commit()

    mock_dispatch_result = MagicMock()
    mock_dispatch_result.success = True
    mock_dispatch_result.batch_index = 0
    mock_dispatch_result.total_batches = 1

    with patch("src.server.load_ai_runtime_properties") as mock_rt, \
         patch("src.server.load_pipeline_prompt_properties") as mock_pp, \
         patch("src.server.load_ai_analysis_properties") as mock_ai, \
         patch("src.server._try_registered_prompt_text", return_value=("Test prompt", None)), \
         patch("src.server.ClaudeCodeDispatcher") as mock_dispatcher_cls:

        from src.services.integration_properties import (
            AIRuntimeProperties, AIAnalysisProperties, PipelinePromptProperties,
        )
        mock_rt.return_value = AIRuntimeProperties(mode="local_subscription", model="opus")
        mock_pp.return_value = PipelinePromptProperties(use_registered_prompts=True)
        mock_ai.return_value = AIAnalysisProperties(batch_size=50, enable_depth_first=False)

        mock_instance = mock_dispatcher_cls.return_value
        mock_instance.dispatch_batch.return_value = mock_dispatch_result

        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    # Verify dispatcher was created and called
    mock_dispatcher_cls.assert_called_once()
    mock_instance.dispatch_batch.assert_called_once()
```

**Step 2: Run test, verify FAIL**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_phase11c_pipeline_integration.py::test_ai_analysis_dispatches_to_claude_code_when_local_subscription -v`
Expected: FAIL (ClaudeCodeDispatcher not imported in server.py)

**Step 3: Integrate into server.py**

Add import at top of `server.py` (near line 25, with other service imports):
```python
from .services.claude_code_dispatcher import ClaudeCodeDispatcher
from .services.ai_stage_tool_sets import STAGE_TOOL_SETS, build_batch_prompt
```

Add a helper function (near `_try_registered_prompt_text` around line 1520):
```python
def _resolve_mcp_config_path() -> str:
    """Resolve path to .mcp.json for Claude Code dispatch."""
    # Walk up from this file to find .mcp.json
    here = Path(__file__).resolve().parent  # src/
    for candidate in [here.parent / ".mcp.json", here.parent.parent / ".mcp.json"]:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "No .mcp.json found. Create one from .mcp.json.template for Claude Code dispatch."
    )
```

In the `ai_analysis` stage handler, after the existing `_try_registered_prompt_text` block
(around line 1738), add the dispatch call:

```python
                        # --- Dispatch to Claude Code if local_subscription ---
                        if runtime_props.mode == "local_subscription" and prompt_text:
                            dispatcher = ClaudeCodeDispatcher(
                                mcp_config_path=_resolve_mcp_config_path(),
                                model=runtime_props.model,
                                per_batch_budget_usd=min(
                                    runtime_props.assessment_soft_limit_usd / max(total, 1),
                                    runtime_props.assessment_hard_limit_usd,
                                ),
                            )
                            dispatch_result = dispatcher.dispatch_batch(
                                prompt_text,
                                stage=stage,
                                assessment_id=assessment_id,
                                batch_index=i,
                                total_batches=total,
                                allowed_tools=STAGE_TOOL_SETS.get(stage),
                            )
                            analysis_result["dispatch_result"] = {
                                "success": dispatch_result.success,
                                "duration_seconds": dispatch_result.duration_seconds,
                                "error": dispatch_result.error,
                            }
```

Note: `runtime_props` must be loaded before the artifact loop. Add this near line 1607
(where `ai_props` is loaded):
```python
            runtime_props = load_ai_runtime_properties(session, instance_id=assessment.instance_id)
```

**Step 4: Run the integration test**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_phase11c_pipeline_integration.py::test_ai_analysis_dispatches_to_claude_code_when_local_subscription -v`
Expected: PASS

**Step 5: Run full test suite to check for regressions**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`
Expected: All ~496+ tests PASS

**Step 6: Commit**

```bash
git add tech-assessment-hub/src/server.py tech-assessment-hub/tests/test_phase11c_pipeline_integration.py
git commit -m "feat: wire ClaudeCodeDispatcher into ai_analysis pipeline stage"
```

---

### Task 6: Wire remaining AI stages (observations, ai_refinement, recommendations, report)

**Files:**
- Modify: `tech-assessment-hub/src/server.py`
- Modify: `tech-assessment-hub/tests/test_phase11c_pipeline_integration.py`

Each remaining AI stage follows the same pattern as Task 5. The dispatch call is added
after the existing `_try_registered_prompt_text()` block in each stage handler.

**Step 1: Identify the insertion points in server.py**

Read each stage handler in `_run_assessment_pipeline_stage()` and find where
`_try_registered_prompt_text` is called. Add the same dispatch pattern after each.

Stages to wire:
- `observations` — uses `observation_artifact_reviewer` prompt
- `ai_refinement` — uses `relationship_tracer` prompt
- `grouping` — uses `feature_reasoning_orchestrator` prompt
- `recommendations` — uses `technical_architect` prompt
- `report` — uses `report_writer` prompt

**Step 2: For each stage, add the dispatch block**

The pattern is identical to Task 5 Step 3 — after prompt_text is obtained:
```python
if runtime_props.mode == "local_subscription" and prompt_text:
    dispatcher = ClaudeCodeDispatcher(
        mcp_config_path=_resolve_mcp_config_path(),
        model=runtime_props.model,
        per_batch_budget_usd=<calculated>,
    )
    dispatch_result = dispatcher.dispatch_batch(
        prompt_text,
        stage=stage,
        assessment_id=assessment_id,
        batch_index=<current_index>,
        total_batches=<total>,
        allowed_tools=STAGE_TOOL_SETS.get(stage),
    )
    summary["dispatch_result"] = {
        "success": dispatch_result.success,
        "duration_seconds": dispatch_result.duration_seconds,
        "error": dispatch_result.error,
    }
```

Note: Each stage has slightly different variable names for its summary dict.
Read the stage handler first to match the variable names.

**Step 3: Add a test per stage (parameterized)**

```python
# Append to tests/test_phase11c_pipeline_integration.py

@pytest.mark.parametrize("stage", [
    "observations", "ai_refinement", "recommendations", "report",
])
def test_ai_stages_dispatch_when_local_subscription(db_session, stage):
    """All AI stages dispatch to Claude Code when mode=local_subscription."""
    inst, asmt = _seed_instance_and_assessment(db_session, pipeline_stage=stage)
    # ... seed minimal data for each stage ...
    # Verify ClaudeCodeDispatcher.dispatch_batch is called
```

**Step 4: Run full test suite**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -x -q`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add tech-assessment-hub/src/server.py tech-assessment-hub/tests/test_phase11c_pipeline_integration.py
git commit -m "feat: wire ClaudeCodeDispatcher into all AI pipeline stages"
```

---

### Task 7: Verify end-to-end with running MCP server

This is a manual verification step — no automated test.

**Step 1: Ensure web app is running**

Run: `curl -s -X POST http://localhost:8080/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -m json.tool | head -5`
Expected: JSON response with tools list

**Step 2: Verify .mcp.json exists at project root**

Check: `cat /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/.mcp.json`
Expected: JSON with `tech-assessment-hub` server config

**Step 3: Test Claude Code CLI directly**

Run:
```bash
echo "Use the tech-assessment-hub tools. Call get_customizations with assessment_id=1 and return the count." | \
  claude -p \
    --output-format json \
    --mcp-config /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/.mcp.json \
    --permission-mode bypassPermissions \
    --no-session-persistence \
    --max-budget-usd 1.00
```
Expected: Claude connects to MCP server, calls the tool, returns a JSON result

**Step 4: If Step 3 works, trigger a pipeline stage from the UI**

1. Open the web app at http://localhost:8080
2. Set `ai_runtime.mode` to `local_subscription` in properties
3. Set `pipeline_prompts.use_registered_prompts` to `true`
4. Navigate to an assessment at the `ai_analysis` stage
5. Click "Run Stage"
6. Watch the progress bar — it should show batch progress
7. Check `ScanResult.ai_observations` for `dispatch_result` entries

**Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: adjustments from end-to-end Claude Code dispatch testing"
```

---

## Summary

| Task | Description | New Files | Tests |
|------|-------------|-----------|-------|
| 1 | DispatchResult + command builder | `claude_code_dispatcher.py` | 3 |
| 2 | dispatch_batch implementation | (modify) | 3 |
| 3 | dispatch_stage sequential orchestration | (modify) | 3 |
| 4 | Stage tool sets + prompt template | `ai_stage_tool_sets.py` | 3 |
| 5 | Wire into ai_analysis stage | (modify server.py) | 1 |
| 6 | Wire remaining 5 AI stages | (modify server.py) | 5 |
| 7 | Manual end-to-end verification | — | — |

**Total: ~18 automated tests, 2 new files, 1 modified file**
