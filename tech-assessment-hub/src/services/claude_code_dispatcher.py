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
