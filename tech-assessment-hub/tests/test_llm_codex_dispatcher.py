"""Tests for CodexDispatcher (OpenAI)."""

import json
import subprocess
from unittest.mock import patch

from src.services.llm.codex_dispatcher import CodexDispatcher
from src.services.llm.base_dispatcher import DispatchResult


def test_effort_mapping():
    d = CodexDispatcher()
    assert d.map_effort("low") == "low"
    assert d.map_effort("medium") == "medium"
    assert d.map_effort("high") == "high"
    assert d.map_effort("max") == "high"  # capped


def test_build_cli_command():
    d = CodexDispatcher()
    with patch("shutil.which", return_value="/usr/bin/codex"):
        cmd = d.build_cli_command(
            prompt="test", model="gpt-4.1", effort=None, tools=None,
        )
    assert cmd[0] == "/usr/bin/codex"
    assert "exec" in cmd
    assert "--model" in cmd
    assert "--json" in cmd


def test_parse_cli_output():
    d = CodexDispatcher()
    stdout = json.dumps({"result": "done", "processed": 7})
    result = d.parse_cli_output(stdout)
    assert result.success is True
    assert result.artifacts_processed == 7


def test_test_cli_auth_success():
    d = CodexDispatcher()
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="authenticated", stderr="")
    with patch("shutil.which", return_value="/usr/bin/codex"), \
         patch("subprocess.run", return_value=fake):
        ok, msg = d.test_cli_auth()
    assert ok is True


def test_test_cli_auth_not_installed():
    d = CodexDispatcher()
    with patch("shutil.which", return_value=None):
        ok, msg = d.test_cli_auth()
    assert ok is False
