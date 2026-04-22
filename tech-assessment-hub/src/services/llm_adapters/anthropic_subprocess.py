"""Anthropic Claude Code CLI subprocess adapter.

Pipes the SKILL.md + user message into `claude` CLI on stdin. The CLI handles
LLM auth on its own — either a subscription login stored in
~/.claude/.credentials.json or ANTHROPIC_API_KEY if set — so this adapter only
checks that the binary is present. MCP tool calls flow through the .mcp.json
we hand it via --mcp-config; the stream of events comes back on stdout.

Streaming: we always run with --output-format stream-json. If extra
["stream_log_path"] is given we append every stdout line to that file as it
arrives, giving the SSE route a live feed. The final `{"type":"result"}` event
populates SkillRunResult.

Requires the `claude` binary on PATH on the VM.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from . import SkillRunResult


class AnthropicSubprocessAdapter:
    name = "anthropic_cli"

    def __init__(self, claude_binary: str = "claude"):
        self._binary = claude_binary

    def is_available(self) -> bool:
        if shutil.which(self._binary) is None:
            return False
        # Either an API key OR a subscription credential is enough — the CLI
        # resolves auth itself, we just confirm one source exists.
        if os.environ.get("ANTHROPIC_API_KEY"):
            return True
        creds = Path.home() / ".claude" / ".credentials.json"
        return creds.is_file()

    def run(
        self,
        *,
        skill_text: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        timeout_seconds: int = 600,
        mcp_server_url: Optional[str] = None,  # CLI uses .mcp.json instead
        extra: Optional[Dict[str, Any]] = None,
    ) -> SkillRunResult:
        # Compose what the CLI receives on stdin: SKILL is the system prompt,
        # user message is the request.
        prompt = f"{skill_text}\n\n---\n\nUser request:\n{user_message}"

        # Stream format by default. --include-partial-messages causes the CLI
        # to emit assistant text chunks (content_block_delta events) as they
        # stream from the model, so the SSE sees text word-by-word.
        cmd = [
            self._binary,
            "--print",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",  # required by CLI when using stream-json in print mode
        ]
        if model:
            cmd.extend(["--model", model])

        mcp_config_path = (extra or {}).get("mcp_config_path")
        if mcp_config_path:
            cmd.extend(["--mcp-config", str(mcp_config_path)])
            if not (extra and extra.get("allow_user_mcp_configs")):
                cmd.append("--strict-mcp-config")

        default_allowed = "mcp__tech-assessment-hub"
        allowed_tools = (extra or {}).get("allowed_tools") or default_allowed
        if isinstance(allowed_tools, (list, tuple, set)):
            allowed_tools = ",".join(allowed_tools)
        cmd.extend(["--allowed-tools", str(allowed_tools)])

        default_disallowed = (
            "Bash,BashOutput,KillShell,Edit,NotebookEdit,Write,"
            "Read,Glob,Grep,WebFetch,WebSearch,Task,TodoWrite,"
            "ExitPlanMode,SlashCommand"
        )
        disallowed_tools = (extra or {}).get("disallowed_tools") or default_disallowed
        if isinstance(disallowed_tools, (list, tuple, set)):
            disallowed_tools = ",".join(disallowed_tools)
        cmd.extend(["--disallowed-tools", str(disallowed_tools)])

        if not (extra and extra.get("require_permissions")):
            cmd.append("--dangerously-skip-permissions")

        env = os.environ.copy()
        if extra and extra.get("env"):
            env.update(extra["env"])

        stream_path_raw = (extra or {}).get("stream_log_path")
        stream_path = Path(stream_path_raw) if stream_path_raw else None
        if stream_path is not None:
            stream_path.parent.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,  # line-buffered so we see each event immediately
            )
        except FileNotFoundError:
            return SkillRunResult(
                success=False, output="", transport=self.name,
                error=f"claude binary not found at {self._binary!r}",
            )

        # Write the prompt and close stdin so the CLI can start.
        try:
            if proc.stdin:
                proc.stdin.write(prompt)
                proc.stdin.close()
        except Exception:
            # If stdin is already closed (unlikely), carry on.
            pass

        # Hard timeout: kill the process if the CLI hangs.
        def _kill_on_timeout() -> None:
            try:
                proc.kill()
            except Exception:
                pass
        killer = threading.Timer(max(10, int(timeout_seconds)), _kill_on_timeout)
        killer.daemon = True
        killer.start()

        final_result: Dict[str, Any] = {}
        line_count = 0
        stream_fp = None
        if stream_path is not None:
            stream_fp = stream_path.open("a", encoding="utf-8")
            # Preamble so SSE tails have a definite start marker.
            stream_fp.write(json.dumps({
                "type": "_stream_start",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": model,
                "transport": self.name,
            }) + "\n")
            stream_fp.flush()

        try:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                line_count += 1
                if stream_fp is not None:
                    try:
                        stream_fp.write(line + "\n")
                        stream_fp.flush()
                    except Exception:
                        pass
                try:
                    evt = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(evt, dict) and evt.get("type") == "result":
                    final_result = evt
        finally:
            killer.cancel()
            if stream_fp is not None:
                try:
                    stream_fp.write(json.dumps({
                        "type": "_stream_end",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }) + "\n")
                    stream_fp.flush()
                    stream_fp.close()
                except Exception:
                    pass

        # Drain stderr AFTER stdout closes — some CLIs write errors here.
        stderr_text = ""
        try:
            if proc.stderr:
                stderr_text = proc.stderr.read() or ""
        except Exception:
            pass

        rc = proc.poll()
        if rc is None:
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = -9

        duration = time.monotonic() - started

        timed_out = rc == -9 and (duration >= timeout_seconds - 1)
        if timed_out and not final_result:
            return SkillRunResult(
                success=False,
                output="",
                duration_seconds=duration,
                transport=self.name,
                error=f"claude CLI timed out after {timeout_seconds}s "
                      f"({line_count} stream events received)",
                raw={"timeout": True, "stream_events": line_count},
            )

        if rc not in (0, None) and not final_result:
            return SkillRunResult(
                success=False,
                output="",
                duration_seconds=duration,
                transport=self.name,
                error=(stderr_text or f"claude CLI exited rc={rc}").strip()[:2000],
                raw={"returncode": rc, "stream_events": line_count},
            )

        # Pull summary from the final result event.
        output_text = ""
        tool_calls = 0
        in_tokens = 0
        out_tokens = 0
        cache_read = 0
        cache_write = 0
        raw: Dict[str, Any] = final_result or {}

        if final_result:
            output_text = (
                final_result.get("result")
                or final_result.get("text")
                or ""
            )
            usage = final_result.get("usage") or {}
            in_tokens = usage.get("input_tokens", 0) or 0
            out_tokens = usage.get("output_tokens", 0) or 0
            cache_read = usage.get("cache_read_input_tokens", 0) or 0
            cache_write = usage.get("cache_creation_input_tokens", 0) or 0
            tool_calls = final_result.get("num_turns", 0) or 0

        return SkillRunResult(
            success=bool(final_result) and not final_result.get("is_error", False),
            output=output_text,
            tool_call_count=tool_calls,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            duration_seconds=duration,
            transport=self.name,
            error=None if final_result and not final_result.get("is_error") else (stderr_text or None),
            raw=raw,
        )
