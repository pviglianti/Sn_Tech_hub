"""Tests for GeminiDispatcher."""

import json
import subprocess
from unittest.mock import patch

from src.services.llm.gemini_dispatcher import GeminiDispatcher
from src.services.llm.base_dispatcher import DispatchResult


def test_effort_mapping_returns_none():
    d = GeminiDispatcher()
    assert d.map_effort("low") is None
    assert d.map_effort("max") is None


def test_build_cli_command():
    d = GeminiDispatcher()
    with patch("shutil.which", return_value="/usr/bin/gemini"):
        cmd = d.build_cli_command(
            prompt="test", model="gemini-2.5-pro", effort="high", tools=None,
        )
    assert cmd[0] == "/usr/bin/gemini"
    assert "-p" in cmd
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "gemini-2.5-pro"
    assert "--approval-mode" in cmd
    assert "--effort" not in cmd


def test_parse_cli_output():
    d = GeminiDispatcher()
    stdout = json.dumps({"result": "analysis complete", "processed": 3})
    result = d.parse_cli_output(stdout)
    assert result.success is True
    assert result.artifacts_processed == 3


def test_test_cli_auth_success():
    d = GeminiDispatcher()
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("shutil.which", return_value="/usr/bin/gemini"), \
         patch("subprocess.run", return_value=fake):
        ok, msg = d.test_cli_auth()
    assert ok is True


def test_test_cli_auth_not_installed():
    d = GeminiDispatcher()
    with patch("shutil.which", return_value=None):
        ok, msg = d.test_cli_auth()
    assert ok is False
