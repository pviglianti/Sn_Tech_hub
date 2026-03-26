"""LLM provider authentication and multi-provider dispatch."""

from .models import LLMProvider, LLMModel, LLMAuthSlot
from .base_dispatcher import BaseDispatcher, DispatchResult
from .claude_dispatcher import ClaudeDispatcher
from .gemini_dispatcher import GeminiDispatcher
from .codex_dispatcher import CodexDispatcher
from .dispatcher_router import DispatcherRouter, ResolvedConfig
from .provider_catalog import seed_default_catalog, get_providers_with_models
from .auth_manager import AuthManager

__all__ = [
    "LLMProvider", "LLMModel", "LLMAuthSlot",
    "BaseDispatcher", "DispatchResult",
    "ClaudeDispatcher", "GeminiDispatcher", "CodexDispatcher",
    "DispatcherRouter", "ResolvedConfig",
    "seed_default_catalog", "get_providers_with_models",
    "AuthManager",
]
