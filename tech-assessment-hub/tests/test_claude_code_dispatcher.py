"""Tests for ClaudeCodeDispatcher -- Claude CLI dispatch for local_subscription mode."""

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
