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
