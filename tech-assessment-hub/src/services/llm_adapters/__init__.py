"""Provider adapters for the SkillDispatcher.

Each adapter implements `run(skill_text, user_msg, **opts)` and returns a
`SkillRunResult`. The dispatcher loads SKILL.md from disk and hands it to the
selected adapter — the LLM provider is the only thing that varies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol


@dataclass
class SkillRunResult:
    """Standardized result from any adapter."""
    success: bool
    output: str                               # final text response from the LLM
    tool_call_count: int = 0                  # how many MCP tool calls were made
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    duration_seconds: float = 0.0
    transport: str = ""                       # "anthropic_api_mcp" | "anthropic_api_tools" | "claude_cli" | ...
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    """Adapter contract — every provider implements this."""

    name: str  # e.g. "anthropic_api", "anthropic_cli", "openai_api"

    def is_available(self) -> bool:
        """Cheap check: can we use this adapter right now? (key/binary present)"""
        ...

    def run(
        self,
        *,
        skill_text: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        timeout_seconds: int = 600,
        mcp_server_url: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> SkillRunResult:
        ...
