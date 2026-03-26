"""Tests for ClaudeDispatcher — CLI command building, output parsing, effort mapping."""

import json
import subprocess
from unittest.mock import patch, MagicMock

from src.services.llm.claude_dispatcher import ClaudeDispatcher
from src.services.llm.base_dispatcher import DispatchResult


def test_effort_mapping():
    d = ClaudeDispatcher()
    assert d.map_effort("low") == "low"
    assert d.map_effort("medium") == "medium"
    assert d.map_effort("high") == "high"
    assert d.map_effort("max") == "max"


def test_build_cli_command_basic():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = d.build_cli_command(
            prompt="test",
            model="sonnet",
            effort="medium",
            tools=None,
        )
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "sonnet"
    assert "--effort" in cmd
    eidx = cmd.index("--effort")
    assert cmd[eidx + 1] == "medium"


def test_build_cli_command_with_tools():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = d.build_cli_command(
            prompt="test",
            model="opus",
            effort=None,
            tools=["mcp__hub__tool_a", "mcp__hub__tool_b"],
        )
    assert "--allowedTools" in cmd
    tidx = cmd.index("--allowedTools")
    assert "mcp__hub__tool_a,mcp__hub__tool_b" in cmd[tidx + 1]


def test_build_cli_command_no_effort_when_none():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = d.build_cli_command(
            prompt="test", model="sonnet", effort=None, tools=None,
        )
    assert "--effort" not in cmd


def test_parse_cli_output_json():
    d = ClaudeDispatcher()
    stdout = json.dumps({
        "type": "result",
        "result": "done",
        "cost_usd": 0.12,
        "processed": 5,
    })
    result = d.parse_cli_output(stdout)
    assert result.success is True
    assert result.artifacts_processed == 5
    assert result.budget_used_usd == 0.12


def test_parse_cli_output_empty():
    d = ClaudeDispatcher()
    result = d.parse_cli_output("")
    assert result.success is True
    assert result.artifacts_processed == 0


def test_test_cli_auth_success():
    d = ClaudeDispatcher()
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("shutil.which", return_value="/usr/bin/claude"), \
         patch("subprocess.run", return_value=fake):
        ok, msg = d.test_cli_auth()
    assert ok is True
    assert msg == "ok"


def test_test_cli_auth_not_installed():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value=None):
        ok, msg = d.test_cli_auth()
    assert ok is False
    assert "not found" in msg.lower()
