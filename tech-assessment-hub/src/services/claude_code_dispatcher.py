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
