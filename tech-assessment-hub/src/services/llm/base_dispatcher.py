"""Abstract base dispatcher for LLM CLI invocation."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    """Outcome of one batch dispatched to an LLM CLI."""

    success: bool
    batch_index: int
    total_batches: int
    artifacts_processed: int
    provider_kind: str
    model_name: str
    llm_output: Optional[dict] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0
    budget_used_usd: Optional[float] = None


class BaseDispatcher(ABC):
    """Abstract base class for LLM provider dispatchers.

    Each concrete subclass handles one provider's CLI command format,
    output parsing, auth testing, and model fetching.
    """

    provider_kind: str

    def resolve_api_key(
        self,
        auth_slot: Any,
        *,
        fallback_env_vars: Optional[List[str]] = None,
    ) -> str:
        """Resolve an API key from the auth slot or a provider fallback env var."""
        env_var_name = str(getattr(auth_slot, "env_var_name", "") or "").strip()
        if env_var_name:
            value = str(os.environ.get(env_var_name) or "").strip()
            if value:
                return value

        slot_key = str(getattr(auth_slot, "api_key", "") or "").strip()
        if slot_key:
            return slot_key

        for env_name in fallback_env_vars or []:
            value = str(os.environ.get(env_name) or "").strip()
            if value:
                return value

        raise RuntimeError("No API key configured for live model refresh")

    @abstractmethod
    def build_cli_command(
        self,
        prompt: str,
        model: str,
        effort: Optional[str],
        tools: Optional[List[str]],
    ) -> List[str]:
        """Build CLI argument list for subprocess invocation."""

    @abstractmethod
    def parse_cli_output(self, stdout: str) -> DispatchResult:
        """Normalize provider-specific output to DispatchResult."""

    @abstractmethod
    def test_cli_auth(self) -> tuple[bool, str]:
        """Quick CLI auth check. Returns (success, message)."""

    @abstractmethod
    def test_api_key(self, api_key: str) -> tuple[bool, str]:
        """Validate API key against provider endpoint. Returns (success, message)."""

    @abstractmethod
    def fetch_models(self, auth_slot: Any) -> List[Dict[str, Any]]:
        """Live-fetch available models from provider API."""

    def map_effort(self, unified_level: str) -> Optional[str]:
        """Map unified effort level to provider-native value.

        Override in subclass. Default returns None (effort not supported).
        """
        return None

    def dispatch_batch(
        self,
        prompt: str,
        *,
        model: str,
        effort: Optional[str],
        stage: str,
        assessment_id: int,
        batch_index: int,
        total_batches: int,
        allowed_tools: Optional[List[str]] = None,
        mcp_config_path: Optional[str] = None,
        timeout_seconds: int = 300,
        budget_usd: float = 5.0,
    ) -> DispatchResult:
        """Run one batch through the provider's CLI.

        Builds the CLI command, pipes prompt via stdin, parses output.
        """
        cmd = self.build_cli_command(prompt, model, effort, allowed_tools)
        start = time.monotonic()

        try:
            completed = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            duration = time.monotonic() - start

            if completed.returncode != 0:
                return DispatchResult(
                    success=False,
                    batch_index=batch_index,
                    total_batches=total_batches,
                    artifacts_processed=0,
                    provider_kind=self.provider_kind,
                    model_name=model,
                    error=f"CLI exited {completed.returncode}: {completed.stderr[:500]}",
                    duration_seconds=duration,
                )

            result = self.parse_cli_output(completed.stdout)
            result.batch_index = batch_index
            result.total_batches = total_batches
            result.duration_seconds = duration
            return result

        except subprocess.TimeoutExpired:
            return DispatchResult(
                success=False,
                batch_index=batch_index,
                total_batches=total_batches,
                artifacts_processed=0,
                provider_kind=self.provider_kind,
                model_name=model,
                error=f"Timeout after {timeout_seconds}s",
                duration_seconds=time.monotonic() - start,
            )
        except Exception as exc:
            return DispatchResult(
                success=False,
                batch_index=batch_index,
                total_batches=total_batches,
                artifacts_processed=0,
                provider_kind=self.provider_kind,
                model_name=model,
                error=str(exc),
                duration_seconds=time.monotonic() - start,
            )
