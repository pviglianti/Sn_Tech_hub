"""LLM provider catalog — default seeding and CRUD operations."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session, select

from .models import LLMProvider, LLMModel

DEFAULT_CATALOG: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "cli_command": "claude",
        "api_base_url": "https://api.anthropic.com/v1",
        "models": [
            {"name": "claude-opus-4-6", "display": "Claude Opus 4.6", "ctx": 1_000_000, "effort": True, "default": False},
            {"name": "claude-sonnet-4-6", "display": "Claude Sonnet 4.6", "ctx": 1_000_000, "effort": True, "default": True},
            {"name": "claude-haiku-4-5-20251001", "display": "Claude Haiku 4.5", "ctx": 200_000, "effort": True, "default": False},
        ],
    },
    "google": {
        "name": "Google (Gemini)",
        "cli_command": "gemini",
        "api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": [
            {"name": "gemini-2.5-pro", "display": "Gemini 2.5 Pro", "ctx": 1_000_000, "effort": False, "default": True},
            {"name": "gemini-2.5-flash", "display": "Gemini 2.5 Flash", "ctx": 1_000_000, "effort": False, "default": False},
        ],
    },
    "openai": {
        "name": "OpenAI (GPT/Codex)",
        "cli_command": "codex",
        "api_base_url": "https://api.openai.com/v1",
        "models": [
            {"name": "gpt-4.1", "display": "GPT-4.1", "ctx": 1_000_000, "effort": False, "default": True},
            {"name": "o3", "display": "O3", "ctx": 200_000, "effort": True, "default": False},
            {"name": "codex-mini", "display": "Codex Mini", "ctx": 1_000_000, "effort": False, "default": False},
        ],
    },
}


def seed_default_catalog(session: Session) -> None:
    """Seed providers and models if they don't already exist. Idempotent."""
    for kind, info in DEFAULT_CATALOG.items():
        existing = session.exec(
            select(LLMProvider).where(LLMProvider.provider_kind == kind)
        ).first()
        if existing:
            continue

        provider = LLMProvider(
            provider_kind=kind,
            name=info["name"],
            cli_command=info.get("cli_command"),
            api_base_url=info.get("api_base_url"),
        )
        session.add(provider)
        session.flush()  # Get provider.id

        for m in info["models"]:
            model = LLMModel(
                provider_id=provider.id,
                model_name=m["name"],
                display_name=m.get("display", m["name"]),
                context_window=m.get("ctx"),
                supports_effort=m.get("effort", False),
                is_default=m.get("default", False),
                source="builtin",
            )
            session.add(model)

    session.commit()


def get_providers_with_models(
    session: Session, *, active_only: bool = True
) -> List[Dict[str, Any]]:
    """Return all providers with their models. Used by the settings UI."""
    query = select(LLMProvider)
    if active_only:
        query = query.where(LLMProvider.is_active == True)  # noqa: E712
    providers = session.exec(query).all()

    result = []
    for p in providers:
        models = session.exec(
            select(LLMModel).where(LLMModel.provider_id == p.id)
        ).all()
        result.append({
            "provider": {
                "id": p.id,
                "provider_kind": p.provider_kind,
                "name": p.name,
                "cli_command": p.cli_command,
                "api_base_url": p.api_base_url,
                "is_active": p.is_active,
            },
            "models": [
                {
                    "id": m.id,
                    "model_name": m.model_name,
                    "display_name": m.display_name,
                    "context_window": m.context_window,
                    "supports_effort": m.supports_effort,
                    "is_default": m.is_default,
                    "source": m.source,
                }
                for m in models
            ],
        })
    return result
