"""LLM provider catalog — default seeding and CRUD operations."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session, select

from src.models import AppConfig

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
            {"name": "gpt-5.4", "display": "GPT-5.4", "effort": True, "default": True},
            {"name": "gpt-5.4-mini", "display": "GPT-5.4-Mini", "effort": True, "default": False},
            {"name": "gpt-5.3-codex", "display": "GPT-5.3-Codex", "effort": True, "default": False},
            {"name": "gpt-5.2-codex", "display": "GPT-5.2-Codex", "effort": True, "default": False},
            {"name": "gpt-5.2", "display": "GPT-5.2", "effort": True, "default": False},
            {"name": "gpt-5.1-codex-max", "display": "GPT-5.1-Codex-Max", "effort": True, "default": False},
            {"name": "gpt-5.1-codex-mini", "display": "GPT-5.1-Codex-Mini", "effort": True, "default": False},
        ],
    },
}


def _catalog_model_names(provider_kind: str) -> set[str]:
    return {
        model["name"]
        for model in DEFAULT_CATALOG.get(provider_kind, {}).get("models", [])
    }


def _repair_model_config_references(session: Session) -> None:
    """Upgrade stale builtin model IDs in AppConfig to the current provider default."""
    providers = session.exec(select(LLMProvider)).all()
    default_model_id_by_provider: Dict[int, int] = {}

    for provider in providers:
        default_name = next(
            (
                model["name"]
                for model in DEFAULT_CATALOG.get(provider.provider_kind, {}).get("models", [])
                if model.get("default")
            ),
            None,
        )
        if not default_name:
            continue
        default_model = session.exec(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.model_name == default_name,
            )
        ).first()
        if default_model is not None and default_model.id is not None:
            default_model_id_by_provider[provider.id] = default_model.id

    config_rows = session.exec(
        select(AppConfig).where(AppConfig.key.startswith("ai."))
    ).all()

    for row in config_rows:
        if row.key != "ai.default_model_id" and not (
            row.key.startswith("ai.stage.") and row.key.endswith(".model_id")
        ):
            continue
        try:
            model_id = int(row.value)
        except (TypeError, ValueError):
            continue

        model = session.get(LLMModel, model_id)
        if model is None or model.source != "builtin":
            continue
        provider = session.get(LLMProvider, model.provider_id)
        if provider is None:
            continue
        if model.model_name in _catalog_model_names(provider.provider_kind):
            continue

        default_model_id = default_model_id_by_provider.get(provider.id)
        if default_model_id is None:
            continue

        row.value = str(default_model_id)
        session.add(row)


def seed_default_catalog(session: Session) -> None:
    """Seed or refresh builtin providers and models. Idempotent."""
    for kind, info in DEFAULT_CATALOG.items():
        provider = session.exec(
            select(LLMProvider).where(LLMProvider.provider_kind == kind)
        ).first()
        if provider is None:
            provider = LLMProvider(provider_kind=kind, name=info["name"])

        provider.name = info["name"]
        provider.cli_command = info.get("cli_command")
        provider.api_base_url = info.get("api_base_url")
        session.add(provider)
        session.flush()

        existing_models = session.exec(
            select(LLMModel).where(LLMModel.provider_id == provider.id)
        ).all()
        existing_by_name = {model.model_name: model for model in existing_models}

        for model in existing_models:
            if model.source == "builtin":
                model.is_default = False
                session.add(model)

        for model_info in info["models"]:
            model = existing_by_name.get(model_info["name"])
            if model is None:
                model = LLMModel(
                    provider_id=provider.id,
                    model_name=model_info["name"],
                    source="builtin",
                )

            model.display_name = model_info.get("display", model_info["name"])
            model.context_window = model_info.get("ctx")
            model.supports_effort = model_info.get("effort", False)
            model.is_default = model_info.get("default", False)
            model.source = "builtin"
            session.add(model)

    _repair_model_config_references(session)
    session.commit()


def sync_fetched_provider_models(
    session: Session,
    provider: LLMProvider,
    fetched_models: List[Dict[str, Any]],
) -> List[LLMModel]:
    """Upsert dynamically fetched provider models for later legacy use."""
    existing_models = session.exec(
        select(LLMModel).where(LLMModel.provider_id == provider.id)
    ).all()
    existing_by_name = {model.model_name: model for model in existing_models}

    fetched_default_present = any(bool(model.get("default")) for model in fetched_models)

    for model in existing_models:
        if model.source == "fetched":
            model.is_default = False
            session.add(model)

    for model_info in fetched_models:
        model_name = str(model_info.get("name") or "").strip()
        if not model_name:
            continue

        model = existing_by_name.get(model_name)
        if model is None:
            model = LLMModel(
                provider_id=provider.id,
                model_name=model_name,
                source="fetched",
            )

        model.display_name = str(
            model_info.get("display")
            or model_info.get("display_name")
            or model_name
        ).strip()

        context_window = model_info.get("ctx", model_info.get("context_window"))
        try:
            model.context_window = int(context_window) if context_window is not None else None
        except (TypeError, ValueError):
            model.context_window = None

        model.supports_effort = bool(
            model_info.get("effort", model_info.get("supports_effort", False))
        )
        model.is_default = bool(model_info.get("default", False)) if fetched_default_present else False
        model.source = "fetched"
        session.add(model)

    session.flush()
    return get_provider_models(session, provider)


def get_provider_models(
    session: Session, provider: LLMProvider
) -> List[LLMModel]:
    """Return visible provider models in catalog order."""
    models = session.exec(
        select(LLMModel).where(LLMModel.provider_id == provider.id)
    ).all()

    catalog_models = DEFAULT_CATALOG.get(provider.provider_kind, {}).get("models", [])
    catalog_order = {
        model["name"]: idx for idx, model in enumerate(catalog_models)
    }

    visible_models = [
        model
        for model in models
        if model.source != "builtin" or model.model_name in catalog_order
    ]

    return sorted(
        visible_models,
        key=lambda model: (
            0 if model.model_name in catalog_order else 1,
            catalog_order.get(model.model_name, 10_000),
            (model.display_name or model.model_name).lower(),
        ),
    )


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
        models = get_provider_models(session, p)
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
