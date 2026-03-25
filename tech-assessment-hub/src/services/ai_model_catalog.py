"""Live provider model-catalog lookups for the AI setup wizard."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

import requests
from sqlmodel import Session

from ..mcp.bridge import load_bridge_config
from .integration_properties import (
    AI_RUNTIME_PROVIDER_OPTIONS,
    load_ai_runtime_model_catalog_timeout_seconds,
)

_PROVIDER_LABELS = {value: label for value, label in AI_RUNTIME_PROVIDER_OPTIONS}


class ModelCatalogError(RuntimeError):
    """Raised when a provider catalog request cannot be completed."""


def _combined_env(session: Session) -> Dict[str, str]:
    env = dict(os.environ)
    bridge_cfg = load_bridge_config(session)
    bridge_env = bridge_cfg.get("env") or {}
    if isinstance(bridge_env, dict):
        env.update(
            {
                str(key): str(value)
                for key, value in bridge_env.items()
                if str(key).strip() and str(value).strip()
            }
        )
    return env


def _first_nonempty(env: Dict[str, str], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = str(env.get(key) or "").strip()
        if value:
            return value
    return None


def _request_json(
    url: str,
    *,
    timeout_seconds: int,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        response = requests.get(
            url,
            headers=headers or {},
            params=params or {},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise ModelCatalogError(str(exc)) from exc

    if response.status_code >= 400:
        detail = response.text.strip()
        if len(detail) > 200:
            detail = detail[:200] + "..."
        raise ModelCatalogError(f"HTTP {response.status_code}: {detail or 'request failed'}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ModelCatalogError("Provider returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise ModelCatalogError("Provider returned unexpected response shape")
    return payload


def _sort_models(models: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(models, key=lambda item: (item.get("label") or item.get("value") or "").lower())


def _openai_compatible_urls(base_url: str) -> List[str]:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return []
    candidates = [base + "/models"]
    if not base.endswith("/v1"):
        candidates.append(base + "/v1/models")
    seen = set()
    urls: List[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _fetch_openai_compatible_catalog(
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: int,
) -> List[Dict[str, str]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    last_error: Optional[Exception] = None
    for url in _openai_compatible_urls(base_url):
        try:
            payload = _request_json(url, timeout_seconds=timeout_seconds, headers=headers)
        except ModelCatalogError as exc:
            last_error = exc
            continue
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ModelCatalogError("Provider returned no model list")
        models = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            if not model_id:
                continue
            models.append({"value": model_id, "label": model_id})
        return _sort_models(models)
    if last_error:
        raise ModelCatalogError(str(last_error))
    raise ModelCatalogError("Provider base URL is not configured")


def _fetch_openai_catalog(env: Dict[str, str], timeout_seconds: int) -> List[Dict[str, str]]:
    api_key = _first_nonempty(env, ["OPENAI_API_KEY"])
    if not api_key:
        raise ModelCatalogError("OPENAI_API_KEY is not configured")
    base_url = _first_nonempty(env, ["OPENAI_BASE_URL"]) or "https://api.openai.com/v1"
    return _fetch_openai_compatible_catalog(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def _fetch_deepseek_catalog(env: Dict[str, str], timeout_seconds: int) -> List[Dict[str, str]]:
    api_key = _first_nonempty(env, ["DEEPSEEK_API_KEY"])
    if not api_key:
        raise ModelCatalogError("DEEPSEEK_API_KEY is not configured")
    base_url = _first_nonempty(env, ["DEEPSEEK_BASE_URL"]) or "https://api.deepseek.com"
    return _fetch_openai_compatible_catalog(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def _fetch_openai_compatible_custom_catalog(
    env: Dict[str, str],
    timeout_seconds: int,
) -> List[Dict[str, str]]:
    api_key = _first_nonempty(env, ["OPENAI_COMPATIBLE_API_KEY", "OPENAI_API_KEY"])
    if not api_key:
        raise ModelCatalogError(
            "OPENAI_COMPATIBLE_API_KEY (or OPENAI_API_KEY) is not configured"
        )
    base_url = _first_nonempty(env, ["OPENAI_COMPATIBLE_BASE_URL", "OPENAI_BASE_URL"])
    if not base_url:
        raise ModelCatalogError("OPENAI_COMPATIBLE_BASE_URL is not configured")
    return _fetch_openai_compatible_catalog(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def _anthropic_model_urls(base_url: str) -> List[str]:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return []
    candidates = [base + "/models"]
    if not base.endswith("/v1"):
        candidates.append(base + "/v1/models")
    return list(dict.fromkeys(candidates))


def _fetch_anthropic_catalog(env: Dict[str, str], timeout_seconds: int) -> List[Dict[str, str]]:
    api_key = _first_nonempty(env, ["ANTHROPIC_API_KEY"])
    if not api_key:
        raise ModelCatalogError("ANTHROPIC_API_KEY is not configured")
    base_url = _first_nonempty(env, ["ANTHROPIC_BASE_URL"]) or "https://api.anthropic.com/v1"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": _first_nonempty(env, ["ANTHROPIC_VERSION"]) or "2023-06-01",
    }
    last_error: Optional[Exception] = None
    for url in _anthropic_model_urls(base_url):
        try:
            payload = _request_json(url, timeout_seconds=timeout_seconds, headers=headers)
        except ModelCatalogError as exc:
            last_error = exc
            continue
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ModelCatalogError("Anthropic returned no model list")
        models = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            if not model_id:
                continue
            label = str(row.get("display_name") or model_id).strip()
            models.append({"value": model_id, "label": label})
        return _sort_models(models)
    if last_error:
        raise ModelCatalogError(str(last_error))
    raise ModelCatalogError("Anthropic base URL is not configured")


def _gemini_models_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return "https://generativelanguage.googleapis.com/v1beta/models"
    if base.endswith("/models"):
        return base
    if "/v1" in base:
        return base + "/models"
    return base + "/v1beta/models"


def _fetch_gemini_catalog(env: Dict[str, str], timeout_seconds: int) -> List[Dict[str, str]]:
    api_key = _first_nonempty(env, ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
    if not api_key:
        raise ModelCatalogError("GEMINI_API_KEY or GOOGLE_API_KEY is not configured")

    url = _gemini_models_url(
        _first_nonempty(env, ["GEMINI_BASE_URL", "GOOGLE_GENERATIVE_LANGUAGE_BASE_URL"]) or ""
    )
    models: List[Dict[str, str]] = []
    page_token: Optional[str] = None

    while True:
        params: Dict[str, Any] = {"key": api_key, "pageSize": 1000}
        if page_token:
            params["pageToken"] = page_token
        payload = _request_json(url, timeout_seconds=timeout_seconds, params=params)
        rows = payload.get("models")
        if not isinstance(rows, list):
            raise ModelCatalogError("Gemini returned no model list")
        for row in rows:
            if not isinstance(row, dict):
                continue
            methods = row.get("supportedGenerationMethods") or []
            if isinstance(methods, list) and methods and "generateContent" not in methods:
                continue
            raw_name = str(row.get("name") or "").strip()
            if not raw_name:
                continue
            model_id = raw_name.split("/", 1)[-1]
            label = str(row.get("displayName") or model_id).strip()
            models.append({"value": model_id, "label": label})
        next_token = str(payload.get("nextPageToken") or "").strip()
        if not next_token:
            break
        page_token = next_token

    return _sort_models(models)


def fetch_provider_model_catalog(
    session: Session,
    provider: str,
    instance_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Return live provider model suggestions for the AI setup wizard."""
    normalized_provider = str(provider or "").strip().lower()
    timeout_seconds = load_ai_runtime_model_catalog_timeout_seconds(
        session,
        instance_id=instance_id,
    )
    env = _combined_env(session)

    fetchers = {
        "openai": _fetch_openai_catalog,
        "anthropic": _fetch_anthropic_catalog,
        "google_gemini": _fetch_gemini_catalog,
        "deepseek": _fetch_deepseek_catalog,
        "openai_compatible_custom": _fetch_openai_compatible_custom_catalog,
    }

    payload: Dict[str, Any] = {
        "provider": normalized_provider,
        "provider_label": _PROVIDER_LABELS.get(normalized_provider, normalized_provider),
        "instance_id": instance_id,
        "models": [],
        "source": "unavailable",
        "dynamic": False,
        "custom_model_supported": True,
        "provider_default_supported": True,
        "timeout_seconds": timeout_seconds,
    }

    fetcher = fetchers.get(normalized_provider)
    if fetcher is None:
        payload["error"] = f"Unsupported provider: {normalized_provider}"
        return payload

    try:
        models = fetcher(env, timeout_seconds)
    except ModelCatalogError as exc:
        payload["error"] = str(exc)
        return payload

    payload["models"] = models
    payload["source"] = "provider_api"
    payload["dynamic"] = True
    return payload
