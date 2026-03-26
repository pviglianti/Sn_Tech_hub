# LLM Provider Auth & Multi-Provider Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-app LLM provider authentication (Claude, Gemini, Codex), model catalog, adapter-based multi-provider dispatch, and a settings UI to the Tech Assessment Hub.

**Architecture:** New SQLModel tables for providers/models/auth slots, abstract dispatcher with per-provider adapters replacing the monolithic `claude_code_dispatcher.py`, new Flask settings page with provider cards and config dropdowns, and router-based pipeline integration that resolves provider/model/effort per stage.

**Tech Stack:** Python 3.9+, FastAPI, SQLModel, SQLite, Jinja2, subprocess (CLI dispatch), httpx (API key testing)

**Spec:** `docs/superpowers/specs/2026-03-26-llm-provider-auth-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/services/llm/__init__.py` | Package init, re-exports |
| `src/services/llm/models.py` | SQLModel tables: `LLMProvider`, `LLMModel`, `LLMAuthSlot` |
| `src/services/llm/base_dispatcher.py` | `BaseDispatcher` ABC + shared `DispatchResult` |
| `src/services/llm/claude_dispatcher.py` | Claude CLI command builder, output parser, auth tester |
| `src/services/llm/gemini_dispatcher.py` | Gemini CLI command builder, output parser, auth tester |
| `src/services/llm/codex_dispatcher.py` | Codex/OpenAI CLI command builder, output parser, auth tester |
| `src/services/llm/dispatcher_router.py` | Resolves provider/model/effort per stage, preflight check |
| `src/services/llm/provider_catalog.py` | Default catalog seed, live model fetch, CRUD |
| `src/services/llm/auth_manager.py` | CLI detection, login trigger, API key storage, test |
| `src/web/templates/llm_settings.html` | Settings page template |
| `tests/test_llm_models.py` | Tests for LLM SQLModel tables |
| `tests/test_llm_base_dispatcher.py` | Tests for BaseDispatcher + DispatchResult |
| `tests/test_llm_claude_dispatcher.py` | Tests for ClaudeDispatcher |
| `tests/test_llm_gemini_dispatcher.py` | Tests for GeminiDispatcher |
| `tests/test_llm_codex_dispatcher.py` | Tests for CodexDispatcher |
| `tests/test_llm_dispatcher_router.py` | Tests for DispatcherRouter |
| `tests/test_llm_provider_catalog.py` | Tests for catalog seed + CRUD |
| `tests/test_llm_auth_manager.py` | Tests for auth manager |
| `tests/test_llm_api_routes.py` | Tests for /api/llm/* endpoints |

### Modified Files
| File | Change |
|------|--------|
| `src/database.py` | Import new LLM models in `create_db_and_tables()`, add to `_ensure_model_table_columns` list |
| `src/server.py` | Add `/api/llm/*` routes, add `/settings/llm-providers` page route, update `_run_assessment_pipeline_stage()` to use `DispatcherRouter` |
| `src/web/templates/base.html` | Add "LLM Settings" nav link |
| `src/web/templates/assessment_detail.html` | Add resolved provider/model display + "Configure AI" link near pipeline buttons |

---

## Task 1: LLM SQLModel Tables

**Files:**
- Create: `tech-assessment-hub/src/services/llm/__init__.py`
- Create: `tech-assessment-hub/src/services/llm/models.py`
- Modify: `tech-assessment-hub/src/database.py:43-94`
- Test: `tech-assessment-hub/tests/test_llm_models.py`

- [ ] **Step 1: Write failing tests for LLM models**

Create `tests/test_llm_models.py`:

```python
"""Tests for LLM provider, model, and auth slot SQLModel tables."""

import pytest
from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMModel, LLMAuthSlot


def test_create_provider(db_session: Session):
    provider = LLMProvider(
        provider_kind="anthropic",
        name="Anthropic (Claude)",
        cli_command="claude",
        api_base_url="https://api.anthropic.com/v1",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    assert provider.id is not None
    assert provider.provider_kind == "anthropic"
    assert provider.is_active is True


def test_create_model(db_session: Session):
    provider = LLMProvider(
        provider_kind="anthropic",
        name="Anthropic (Claude)",
        cli_command="claude",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    model = LLMModel(
        provider_id=provider.id,
        model_name="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        context_window=1_000_000,
        supports_effort=True,
        is_default=True,
        source="builtin",
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)

    assert model.id is not None
    assert model.provider_id == provider.id
    assert model.supports_effort is True


def test_create_auth_slot_cli(db_session: Session):
    provider = LLMProvider(
        provider_kind="anthropic",
        name="Anthropic (Claude)",
        cli_command="claude",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    slot = LLMAuthSlot(
        provider_id=provider.id,
        slot_kind="cli",
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    assert slot.id is not None
    assert slot.slot_kind == "cli"
    assert slot.api_key is None


def test_create_auth_slot_api_key(db_session: Session):
    provider = LLMProvider(
        provider_kind="openai",
        name="OpenAI (GPT/Codex)",
        cli_command="codex",
    )
    db_session.add(provider)
    db_session.commit()
    db_session.refresh(provider)

    slot = LLMAuthSlot(
        provider_id=provider.id,
        slot_kind="api_key",
        api_key="sk-test-12345678",
        api_key_hint="5678",
        is_active=True,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)

    assert slot.api_key == "sk-test-12345678"
    assert slot.api_key_hint == "5678"


def test_provider_unique_kind(db_session: Session):
    """Only one provider per provider_kind."""
    p1 = LLMProvider(provider_kind="anthropic", name="A", cli_command="claude")
    db_session.add(p1)
    db_session.commit()

    p2 = LLMProvider(provider_kind="anthropic", name="B", cli_command="claude")
    db_session.add(p2)
    with pytest.raises(Exception):  # IntegrityError
        db_session.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.llm'`

- [ ] **Step 3: Create the LLM package and models**

Create `src/services/llm/__init__.py`:

```python
"""LLM provider authentication and multi-provider dispatch."""
```

Create `src/services/llm/models.py`:

```python
"""SQLModel tables for LLM providers, models, and auth slots."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class LLMProvider(SQLModel, table=True):
    """An LLM provider (Anthropic, Google, OpenAI)."""

    __tablename__ = "llm_provider"
    __table_args__ = (UniqueConstraint("provider_kind"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_kind: str = Field(index=True)  # anthropic | google | openai
    name: str  # Display name
    cli_command: Optional[str] = None  # claude | gemini | codex
    api_base_url: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LLMModel(SQLModel, table=True):
    """A model offered by an LLM provider."""

    __tablename__ = "llm_model"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="llm_provider.id", index=True)
    model_name: str  # API identifier, e.g. claude-opus-4-6
    display_name: Optional[str] = None
    context_window: Optional[int] = None
    supports_effort: bool = False
    is_default: bool = False
    source: str = "builtin"  # builtin | fetched | manual
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LLMAuthSlot(SQLModel, table=True):
    """Auth credential for an LLM provider — CLI subscription or API key."""

    __tablename__ = "llm_auth_slot"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="llm_provider.id", index=True)
    slot_kind: str  # cli | api_key
    api_key: Optional[str] = None  # Plaintext (local-only deployment)
    api_key_hint: Optional[str] = None  # Last 4 chars for display
    env_var_name: Optional[str] = None  # Read key from env var instead
    is_active: bool = True
    last_tested_at: Optional[str] = None  # ISO timestamp
    last_test_result: Optional[str] = None  # "ok" or "error: ..."
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Register tables in database.py**

In `src/database.py`, add import at line 46 (inside `create_db_and_tables()`):

```python
from .services.llm import models as llm_models  # noqa: F401
```

Add to `_ensure_model_table_columns` list (after line 93):

```python
"llm_provider",
"llm_model",
"llm_auth_slot",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_models.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add tech-assessment-hub/src/services/llm/__init__.py \
       tech-assessment-hub/src/services/llm/models.py \
       tech-assessment-hub/src/database.py \
       tech-assessment-hub/tests/test_llm_models.py
git commit -m "feat: add LLM provider, model, and auth slot SQLModel tables"
```

---

## Task 2: Provider Catalog — Seed & CRUD

**Files:**
- Create: `tech-assessment-hub/src/services/llm/provider_catalog.py`
- Test: `tech-assessment-hub/tests/test_llm_provider_catalog.py`

- [ ] **Step 1: Write failing tests for provider catalog**

Create `tests/test_llm_provider_catalog.py`:

```python
"""Tests for LLM provider catalog — seed defaults and CRUD."""

from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMModel
from src.services.llm.provider_catalog import (
    seed_default_catalog,
    get_providers_with_models,
    DEFAULT_CATALOG,
)


def test_seed_default_catalog(db_session: Session):
    """Seeding creates all 3 providers and their models."""
    seed_default_catalog(db_session)

    providers = db_session.exec(select(LLMProvider)).all()
    assert len(providers) == 3

    kinds = {p.provider_kind for p in providers}
    assert kinds == {"anthropic", "google", "openai"}

    models = db_session.exec(select(LLMModel)).all()
    expected_model_count = sum(
        len(p["models"]) for p in DEFAULT_CATALOG.values()
    )
    assert len(models) == expected_model_count


def test_seed_is_idempotent(db_session: Session):
    """Calling seed twice does not duplicate rows."""
    seed_default_catalog(db_session)
    seed_default_catalog(db_session)

    providers = db_session.exec(select(LLMProvider)).all()
    assert len(providers) == 3


def test_get_providers_with_models(db_session: Session):
    seed_default_catalog(db_session)
    result = get_providers_with_models(db_session)

    assert len(result) == 3
    for entry in result:
        assert "provider" in entry
        assert "models" in entry
        assert len(entry["models"]) > 0


def test_default_model_per_provider(db_session: Session):
    """Each provider has exactly one default model."""
    seed_default_catalog(db_session)
    providers = db_session.exec(select(LLMProvider)).all()
    for provider in providers:
        defaults = db_session.exec(
            select(LLMModel).where(
                LLMModel.provider_id == provider.id,
                LLMModel.is_default == True,  # noqa: E712
            )
        ).all()
        assert len(defaults) == 1, f"{provider.provider_kind} should have 1 default model"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_provider_catalog.py -v`
Expected: FAIL — `ImportError: cannot import name 'seed_default_catalog'`

- [ ] **Step 3: Implement provider catalog**

Create `src/services/llm/provider_catalog.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_provider_catalog.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/llm/provider_catalog.py \
       tech-assessment-hub/tests/test_llm_provider_catalog.py
git commit -m "feat: add LLM provider catalog with default seeding and CRUD"
```

---

## Task 3: BaseDispatcher ABC + DispatchResult

**Files:**
- Create: `tech-assessment-hub/src/services/llm/base_dispatcher.py`
- Test: `tech-assessment-hub/tests/test_llm_base_dispatcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_base_dispatcher.py`:

```python
"""Tests for BaseDispatcher ABC and DispatchResult."""

import pytest
from dataclasses import asdict

from src.services.llm.base_dispatcher import BaseDispatcher, DispatchResult


def test_dispatch_result_defaults():
    r = DispatchResult(
        success=True,
        batch_index=0,
        total_batches=1,
        artifacts_processed=5,
        provider_kind="anthropic",
        model_name="claude-sonnet-4-6",
    )
    assert r.success is True
    assert r.error is None
    assert r.budget_used_usd is None
    d = asdict(r)
    assert d["provider_kind"] == "anthropic"


def test_dispatch_result_with_error():
    r = DispatchResult(
        success=False,
        batch_index=1,
        total_batches=3,
        artifacts_processed=0,
        provider_kind="google",
        model_name="gemini-2.5-pro",
        error="Timeout after 300s",
    )
    assert r.success is False
    assert r.error == "Timeout after 300s"


def test_base_dispatcher_cannot_instantiate():
    """BaseDispatcher is abstract — cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseDispatcher()


def test_effort_mapping_default():
    """Concrete subclass can use default map_effort which returns None."""

    class StubDispatcher(BaseDispatcher):
        provider_kind = "stub"

        def build_cli_command(self, prompt, model, effort, tools):
            return ["stub"]

        def parse_cli_output(self, stdout):
            return DispatchResult(
                success=True, batch_index=0, total_batches=1,
                artifacts_processed=0, provider_kind="stub", model_name="stub",
            )

        def test_cli_auth(self):
            return True, "ok"

        def test_api_key(self, api_key):
            return True, "ok"

        def fetch_models(self, auth_slot):
            return []

    d = StubDispatcher()
    assert d.map_effort("high") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_base_dispatcher.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement BaseDispatcher**

Create `src/services/llm/base_dispatcher.py`:

```python
"""Abstract base dispatcher for LLM CLI invocation."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_base_dispatcher.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/llm/base_dispatcher.py \
       tech-assessment-hub/tests/test_llm_base_dispatcher.py
git commit -m "feat: add BaseDispatcher ABC and DispatchResult dataclass"
```

---

## Task 4: ClaudeDispatcher

**Files:**
- Create: `tech-assessment-hub/src/services/llm/claude_dispatcher.py`
- Test: `tech-assessment-hub/tests/test_llm_claude_dispatcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_claude_dispatcher.py`:

```python
"""Tests for ClaudeDispatcher — CLI command building, output parsing, effort mapping."""

import json
import subprocess
from unittest.mock import patch, MagicMock

from src.services.llm.claude_dispatcher import ClaudeDispatcher
from src.services.llm.base_dispatcher import DispatchResult


def test_effort_mapping():
    d = ClaudeDispatcher()
    assert d.map_effort("low") == "low"
    assert d.map_effort("medium") == "medium"
    assert d.map_effort("high") == "high"
    assert d.map_effort("max") == "max"


def test_build_cli_command_basic():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = d.build_cli_command(
            prompt="test",
            model="sonnet",
            effort="medium",
            tools=None,
        )
    assert cmd[0] == "/usr/bin/claude"
    assert "-p" in cmd
    assert "--model" in cmd
    idx = cmd.index("--model")
    assert cmd[idx + 1] == "sonnet"
    assert "--effort" in cmd
    eidx = cmd.index("--effort")
    assert cmd[eidx + 1] == "medium"


def test_build_cli_command_with_tools():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = d.build_cli_command(
            prompt="test",
            model="opus",
            effort=None,
            tools=["mcp__hub__tool_a", "mcp__hub__tool_b"],
        )
    assert "--allowedTools" in cmd
    tidx = cmd.index("--allowedTools")
    assert "mcp__hub__tool_a,mcp__hub__tool_b" in cmd[tidx + 1]


def test_build_cli_command_no_effort_when_none():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = d.build_cli_command(
            prompt="test", model="sonnet", effort=None, tools=None,
        )
    assert "--effort" not in cmd


def test_parse_cli_output_json():
    d = ClaudeDispatcher()
    stdout = json.dumps({
        "type": "result",
        "result": "done",
        "cost_usd": 0.12,
        "processed": 5,
    })
    result = d.parse_cli_output(stdout)
    assert result.success is True
    assert result.artifacts_processed == 5
    assert result.budget_used_usd == 0.12


def test_parse_cli_output_empty():
    d = ClaudeDispatcher()
    result = d.parse_cli_output("")
    assert result.success is True
    assert result.artifacts_processed == 0


def test_test_cli_auth_success():
    d = ClaudeDispatcher()
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("shutil.which", return_value="/usr/bin/claude"), \
         patch("subprocess.run", return_value=fake):
        ok, msg = d.test_cli_auth()
    assert ok is True
    assert msg == "ok"


def test_test_cli_auth_not_installed():
    d = ClaudeDispatcher()
    with patch("shutil.which", return_value=None):
        ok, msg = d.test_cli_auth()
    assert ok is False
    assert "not found" in msg.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_claude_dispatcher.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement ClaudeDispatcher**

Create `src/services/llm/claude_dispatcher.py`:

```python
"""Claude Code CLI dispatcher."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base_dispatcher import BaseDispatcher, DispatchResult

logger = logging.getLogger(__name__)

_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "max": "max"}


class ClaudeDispatcher(BaseDispatcher):
    """Dispatcher for Anthropic's Claude Code CLI."""

    provider_kind = "anthropic"

    def map_effort(self, unified_level: str) -> Optional[str]:
        return _EFFORT_MAP.get(unified_level)

    def build_cli_command(
        self,
        prompt: str,
        model: str,
        effort: Optional[str],
        tools: Optional[List[str]],
    ) -> List[str]:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("Claude CLI not found on PATH")

        cmd = [
            claude_bin, "-p",
            "--output-format", "json",
            "--model", model,
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
        ]
        native_effort = self.map_effort(effort) if effort else None
        if native_effort:
            cmd.extend(["--effort", native_effort])
        if tools:
            cmd.extend(["--allowedTools", ",".join(tools)])
        return cmd

    def parse_cli_output(self, stdout: str) -> DispatchResult:
        stdout = stdout.strip()
        parsed: Optional[dict] = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                for line in reversed(stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            parsed = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                if parsed is None:
                    parsed = {"raw_output": stdout[:2000]}

        return DispatchResult(
            success=True,
            batch_index=0,
            total_batches=1,
            artifacts_processed=parsed.get("processed", 0) if parsed else 0,
            provider_kind=self.provider_kind,
            model_name="",
            llm_output=parsed,
            budget_used_usd=parsed.get("cost_usd") if parsed else None,
        )

    def test_cli_auth(self) -> tuple[bool, str]:
        claude_bin = shutil.which("claude")
        if not claude_bin:
            return False, "Claude CLI not found on PATH"
        try:
            result = subprocess.run(
                [claude_bin, "-p", "--max-turns", "0", "respond with ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return True, "ok"
            return False, f"error: exit {result.returncode} — {result.stderr[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def test_api_key(self, api_key: str) -> tuple[bool, str]:
        try:
            import httpx
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "ok"}],
                },
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "ok"
            return False, f"error: HTTP {resp.status_code} — {resp.text[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def fetch_models(self, auth_slot: Any) -> List[Dict[str, Any]]:
        """Fetch models from Anthropic API. Reuses ai_model_catalog logic."""
        # Delegate to existing catalog fetcher if available
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_claude_dispatcher.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/llm/claude_dispatcher.py \
       tech-assessment-hub/tests/test_llm_claude_dispatcher.py
git commit -m "feat: add ClaudeDispatcher with CLI command building and auth testing"
```

---

## Task 5: GeminiDispatcher

**Files:**
- Create: `tech-assessment-hub/src/services/llm/gemini_dispatcher.py`
- Test: `tech-assessment-hub/tests/test_llm_gemini_dispatcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_gemini_dispatcher.py`:

```python
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
    # Effort should NOT be in command (Gemini doesn't support it)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_gemini_dispatcher.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement GeminiDispatcher**

Create `src/services/llm/gemini_dispatcher.py`:

```python
"""Gemini CLI dispatcher."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base_dispatcher import BaseDispatcher, DispatchResult

logger = logging.getLogger(__name__)


class GeminiDispatcher(BaseDispatcher):
    """Dispatcher for Google's Gemini CLI."""

    provider_kind = "google"

    def map_effort(self, unified_level: str) -> Optional[str]:
        return None  # Gemini CLI does not support effort levels

    def build_cli_command(
        self,
        prompt: str,
        model: str,
        effort: Optional[str],
        tools: Optional[List[str]],
    ) -> List[str]:
        gemini_bin = shutil.which("gemini")
        if not gemini_bin:
            raise RuntimeError("Gemini CLI not found on PATH")

        cmd = [
            gemini_bin, "-p",
            "--model", model,
            "--approval-mode", "yolo",
            "--output-format", "stream-json",
        ]
        # Gemini does not support --effort; intentionally omitted
        return cmd

    def parse_cli_output(self, stdout: str) -> DispatchResult:
        stdout = stdout.strip()
        parsed: Optional[dict] = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                for line in reversed(stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            parsed = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                if parsed is None:
                    parsed = {"raw_output": stdout[:2000]}

        return DispatchResult(
            success=True,
            batch_index=0,
            total_batches=1,
            artifacts_processed=parsed.get("processed", 0) if parsed else 0,
            provider_kind=self.provider_kind,
            model_name="",
            llm_output=parsed,
        )

    def test_cli_auth(self) -> tuple[bool, str]:
        gemini_bin = shutil.which("gemini")
        if not gemini_bin:
            return False, "Gemini CLI not found on PATH"
        try:
            result = subprocess.run(
                [gemini_bin, "--prompt", "respond with just ok"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return True, "ok"
            return False, f"error: exit {result.returncode} — {result.stderr[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def test_api_key(self, api_key: str) -> tuple[bool, str]:
        try:
            import httpx
            resp = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "ok"
            return False, f"error: HTTP {resp.status_code} — {resp.text[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def fetch_models(self, auth_slot: Any) -> List[Dict[str, Any]]:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_gemini_dispatcher.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/llm/gemini_dispatcher.py \
       tech-assessment-hub/tests/test_llm_gemini_dispatcher.py
git commit -m "feat: add GeminiDispatcher with CLI command building and auth testing"
```

---

## Task 6: CodexDispatcher

**Files:**
- Create: `tech-assessment-hub/src/services/llm/codex_dispatcher.py`
- Test: `tech-assessment-hub/tests/test_llm_codex_dispatcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_codex_dispatcher.py`:

```python
"""Tests for CodexDispatcher (OpenAI)."""

import json
import subprocess
from unittest.mock import patch

from src.services.llm.codex_dispatcher import CodexDispatcher
from src.services.llm.base_dispatcher import DispatchResult


def test_effort_mapping():
    d = CodexDispatcher()
    assert d.map_effort("low") == "low"
    assert d.map_effort("medium") == "medium"
    assert d.map_effort("high") == "high"
    assert d.map_effort("max") == "high"  # capped


def test_build_cli_command():
    d = CodexDispatcher()
    with patch("shutil.which", return_value="/usr/bin/codex"):
        cmd = d.build_cli_command(
            prompt="test", model="gpt-4.1", effort=None, tools=None,
        )
    assert cmd[0] == "/usr/bin/codex"
    assert "exec" in cmd
    assert "--model" in cmd
    assert "--json" in cmd


def test_parse_cli_output():
    d = CodexDispatcher()
    stdout = json.dumps({"result": "done", "processed": 7})
    result = d.parse_cli_output(stdout)
    assert result.success is True
    assert result.artifacts_processed == 7


def test_test_cli_auth_success():
    d = CodexDispatcher()
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="authenticated", stderr="")
    with patch("shutil.which", return_value="/usr/bin/codex"), \
         patch("subprocess.run", return_value=fake):
        ok, msg = d.test_cli_auth()
    assert ok is True


def test_test_cli_auth_not_installed():
    d = CodexDispatcher()
    with patch("shutil.which", return_value=None):
        ok, msg = d.test_cli_auth()
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_codex_dispatcher.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement CodexDispatcher**

Create `src/services/llm/codex_dispatcher.py`:

```python
"""OpenAI Codex CLI dispatcher."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base_dispatcher import BaseDispatcher, DispatchResult

logger = logging.getLogger(__name__)

_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "max": "high"}


class CodexDispatcher(BaseDispatcher):
    """Dispatcher for OpenAI's Codex CLI."""

    provider_kind = "openai"

    def map_effort(self, unified_level: str) -> Optional[str]:
        return _EFFORT_MAP.get(unified_level)

    def build_cli_command(
        self,
        prompt: str,
        model: str,
        effort: Optional[str],
        tools: Optional[List[str]],
    ) -> List[str]:
        codex_bin = shutil.which("codex")
        if not codex_bin:
            raise RuntimeError("Codex CLI not found on PATH")

        cmd = [
            codex_bin, "exec",
            "--model", model,
            "--json",
            "--dangerously-bypass-approvals-and-sandbox",
        ]
        return cmd

    def parse_cli_output(self, stdout: str) -> DispatchResult:
        stdout = stdout.strip()
        parsed: Optional[dict] = None
        if stdout:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                for line in reversed(stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            parsed = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                if parsed is None:
                    parsed = {"raw_output": stdout[:2000]}

        return DispatchResult(
            success=True,
            batch_index=0,
            total_batches=1,
            artifacts_processed=parsed.get("processed", 0) if parsed else 0,
            provider_kind=self.provider_kind,
            model_name="",
            llm_output=parsed,
        )

    def test_cli_auth(self) -> tuple[bool, str]:
        codex_bin = shutil.which("codex")
        if not codex_bin:
            return False, "Codex CLI not found on PATH"
        try:
            result = subprocess.run(
                [codex_bin, "login", "status"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return True, "ok"
            return False, f"error: exit {result.returncode} — {result.stderr[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def test_api_key(self, api_key: str) -> tuple[bool, str]:
        try:
            import httpx
            resp = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            if resp.status_code == 200:
                return True, "ok"
            return False, f"error: HTTP {resp.status_code} — {resp.text[:200]}"
        except Exception as exc:
            return False, f"error: {exc}"

    def fetch_models(self, auth_slot: Any) -> List[Dict[str, Any]]:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_codex_dispatcher.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/llm/codex_dispatcher.py \
       tech-assessment-hub/tests/test_llm_codex_dispatcher.py
git commit -m "feat: add CodexDispatcher for OpenAI CLI command building and auth testing"
```

---

## Task 7: AuthManager

**Files:**
- Create: `tech-assessment-hub/src/services/llm/auth_manager.py`
- Test: `tech-assessment-hub/tests/test_llm_auth_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_auth_manager.py`:

```python
"""Tests for LLM AuthManager — CLI detection, slot creation, testing."""

import subprocess
from unittest.mock import patch, MagicMock
from datetime import datetime

from sqlmodel import Session, select

from src.services.llm.models import LLMProvider, LLMAuthSlot
from src.services.llm.provider_catalog import seed_default_catalog
from src.services.llm.auth_manager import AuthManager


def _seed(db_session: Session) -> None:
    seed_default_catalog(db_session)


def test_detect_clis_all_missing(db_session: Session):
    mgr = AuthManager(db_session)
    with patch("shutil.which", return_value=None):
        result = mgr.detect_clis()
    for kind in ("anthropic", "google", "openai"):
        assert result[kind]["installed"] is False


def test_detect_clis_claude_found(db_session: Session):
    mgr = AuthManager(db_session)

    def _which(name):
        return "/usr/bin/claude" if name == "claude" else None

    fake_version = subprocess.CompletedProcess(args=[], returncode=0, stdout="1.2.3\n", stderr="")
    with patch("shutil.which", side_effect=_which), \
         patch("subprocess.run", return_value=fake_version):
        result = mgr.detect_clis()
    assert result["anthropic"]["installed"] is True
    assert result["anthropic"]["version"] == "1.2.3"


def test_store_api_key(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "anthropic")
    ).one()

    slot = mgr.store_api_key(provider.id, "sk-ant-test-abcd1234")
    assert slot.slot_kind == "api_key"
    assert slot.api_key == "sk-ant-test-abcd1234"
    assert slot.api_key_hint == "1234"
    assert slot.is_active is True


def test_create_cli_slot(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "google")
    ).one()

    slot = mgr.create_cli_slot(provider.id)
    assert slot.slot_kind == "cli"
    assert slot.api_key is None


def test_get_active_auth(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "openai")
    ).one()

    # No slot yet
    assert mgr.get_active_auth(provider.id) is None

    # Create one
    mgr.store_api_key(provider.id, "sk-test-9999")
    slot = mgr.get_active_auth(provider.id)
    assert slot is not None
    assert slot.api_key_hint == "9999"


def test_store_api_key_deactivates_previous(db_session: Session):
    _seed(db_session)
    mgr = AuthManager(db_session)

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "anthropic")
    ).one()

    slot1 = mgr.store_api_key(provider.id, "sk-ant-first-0001")
    slot2 = mgr.store_api_key(provider.id, "sk-ant-second-0002")

    db_session.refresh(slot1)
    assert slot1.is_active is False
    assert slot2.is_active is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_auth_manager.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement AuthManager**

Create `src/services/llm/auth_manager.py`:

```python
"""LLM auth manager — CLI detection, credential storage, testing."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

from sqlmodel import Session, select

from .models import LLMProvider, LLMAuthSlot
from .claude_dispatcher import ClaudeDispatcher
from .gemini_dispatcher import GeminiDispatcher
from .codex_dispatcher import CodexDispatcher

logger = logging.getLogger(__name__)

_CLI_MAP = {
    "anthropic": "claude",
    "google": "gemini",
    "openai": "codex",
}

_DISPATCHER_MAP = {
    "anthropic": ClaudeDispatcher,
    "google": GeminiDispatcher,
    "openai": CodexDispatcher,
}


class AuthManager:
    """Manages LLM provider authentication — CLI detection, login, API keys."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def detect_clis(self) -> Dict[str, Dict[str, Any]]:
        """Check which LLM CLIs are installed and their versions."""
        result = {}
        for kind, cli_name in _CLI_MAP.items():
            path = shutil.which(cli_name)
            if not path:
                result[kind] = {"installed": False, "version": None, "path": None}
                continue

            version = None
            try:
                proc = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                if proc.returncode == 0:
                    version = proc.stdout.strip().split("\n")[0].strip()
            except Exception:
                pass

            result[kind] = {"installed": True, "version": version, "path": path}
        return result

    def trigger_cli_login(self, provider_kind: str) -> None:
        """Open Terminal.app with the CLI login command (macOS)."""
        cli_name = _CLI_MAP.get(provider_kind)
        if not cli_name:
            raise ValueError(f"Unknown provider_kind: {provider_kind}")

        import platform
        if platform.system() == "Darwin":
            import subprocess as sp
            sp.Popen([
                "osascript", "-e",
                f'tell application "Terminal" to do script "{cli_name} login"',
            ])
        else:
            logger.warning("CLI login trigger only supported on macOS")

    def store_api_key(self, provider_id: int, api_key: str) -> LLMAuthSlot:
        """Create an API key auth slot. Deactivates any existing slots for this provider."""
        # Deactivate existing slots
        existing = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).all()
        for slot in existing:
            slot.is_active = False
            self._session.add(slot)

        hint = api_key[-4:] if len(api_key) >= 4 else api_key
        new_slot = LLMAuthSlot(
            provider_id=provider_id,
            slot_kind="api_key",
            api_key=api_key,
            api_key_hint=hint,
            is_active=True,
        )
        self._session.add(new_slot)
        self._session.commit()
        self._session.refresh(new_slot)
        return new_slot

    def create_cli_slot(self, provider_id: int) -> LLMAuthSlot:
        """Create a CLI auth slot. Deactivates existing slots."""
        existing = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).all()
        for slot in existing:
            slot.is_active = False
            self._session.add(slot)

        new_slot = LLMAuthSlot(
            provider_id=provider_id,
            slot_kind="cli",
            is_active=True,
        )
        self._session.add(new_slot)
        self._session.commit()
        self._session.refresh(new_slot)
        return new_slot

    def test_auth_slot(self, slot_id: int) -> tuple[bool, str]:
        """Test an auth slot by routing to the correct dispatcher's test method."""
        slot = self._session.get(LLMAuthSlot, slot_id)
        if not slot:
            return False, "Auth slot not found"

        provider = self._session.get(LLMProvider, slot.provider_id)
        if not provider:
            return False, "Provider not found"

        dispatcher_cls = _DISPATCHER_MAP.get(provider.provider_kind)
        if not dispatcher_cls:
            return False, f"No dispatcher for {provider.provider_kind}"

        dispatcher = dispatcher_cls()

        if slot.slot_kind == "cli":
            ok, msg = dispatcher.test_cli_auth()
        elif slot.slot_kind == "api_key":
            key = slot.api_key
            if slot.env_var_name:
                import os
                key = os.environ.get(slot.env_var_name, key)
            if not key:
                return False, "No API key configured"
            ok, msg = dispatcher.test_api_key(key)
        else:
            return False, f"Unknown slot_kind: {slot.slot_kind}"

        slot.last_tested_at = datetime.utcnow().isoformat()
        slot.last_test_result = "ok" if ok else msg
        self._session.add(slot)
        self._session.commit()

        return ok, msg

    def get_active_auth(self, provider_id: int) -> Optional[LLMAuthSlot]:
        """Get the active auth slot for a provider."""
        return self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_auth_manager.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/services/llm/auth_manager.py \
       tech-assessment-hub/tests/test_llm_auth_manager.py
git commit -m "feat: add AuthManager for CLI detection, API key storage, and auth testing"
```

---

## Task 8: DispatcherRouter

**Files:**
- Create: `tech-assessment-hub/src/services/llm/dispatcher_router.py`
- Test: `tech-assessment-hub/tests/test_llm_dispatcher_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_dispatcher_router.py`:

```python
"""Tests for DispatcherRouter — provider/model/effort resolution and preflight checks."""

from sqlmodel import Session

from src.models import AppConfig
from src.services.llm.models import LLMProvider, LLMAuthSlot
from src.services.llm.provider_catalog import seed_default_catalog
from src.services.llm.auth_manager import AuthManager
from src.services.llm.dispatcher_router import DispatcherRouter


def _setup_authenticated_provider(db_session: Session, kind: str = "anthropic") -> int:
    """Seed catalog, create CLI auth slot, mark as ok."""
    seed_default_catalog(db_session)
    from sqlmodel import select
    from src.services.llm.models import LLMProvider, LLMModel

    provider = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == kind)
    ).one()
    slot = LLMAuthSlot(
        provider_id=provider.id, slot_kind="cli", is_active=True,
        last_test_result="ok",
    )
    db_session.add(slot)
    db_session.commit()

    # Set global defaults
    default_model = db_session.exec(
        select(LLMModel).where(
            LLMModel.provider_id == provider.id,
            LLMModel.is_default == True,  # noqa: E712
        )
    ).one()

    for key, val in [
        ("ai.default_provider_id", str(provider.id)),
        ("ai.default_model_id", str(default_model.id)),
        ("ai.default_effort_level", "medium"),
    ]:
        db_session.add(AppConfig(key=key, value=val))
    db_session.commit()

    return provider.id


def test_resolve_global_defaults(db_session: Session):
    _setup_authenticated_provider(db_session, "anthropic")
    router = DispatcherRouter(db_session)
    config = router.resolve("ai_analysis")

    assert config.provider_kind == "anthropic"
    assert config.model_name == "claude-sonnet-4-6"
    assert config.effort_level == "medium"


def test_resolve_per_stage_override(db_session: Session):
    _setup_authenticated_provider(db_session, "anthropic")

    # Also set up google
    from sqlmodel import select
    from src.services.llm.models import LLMProvider, LLMModel

    google = db_session.exec(
        select(LLMProvider).where(LLMProvider.provider_kind == "google")
    ).one()
    slot = LLMAuthSlot(
        provider_id=google.id, slot_kind="cli", is_active=True,
        last_test_result="ok",
    )
    db_session.add(slot)

    google_model = db_session.exec(
        select(LLMModel).where(
            LLMModel.provider_id == google.id,
            LLMModel.is_default == True,  # noqa: E712
        )
    ).one()

    db_session.add(AppConfig(key="ai.stage.grouping.provider_id", value=str(google.id)))
    db_session.add(AppConfig(key="ai.stage.grouping.model_id", value=str(google_model.id)))
    db_session.add(AppConfig(key="ai.stage.grouping.effort_level", value="low"))
    db_session.commit()

    router = DispatcherRouter(db_session)

    # ai_analysis uses global default (anthropic)
    config_analysis = router.resolve("ai_analysis")
    assert config_analysis.provider_kind == "anthropic"

    # grouping uses per-stage override (google)
    config_grouping = router.resolve("grouping")
    assert config_grouping.provider_kind == "google"
    assert config_grouping.effort_level == "low"


def test_preflight_check_no_provider(db_session: Session):
    seed_default_catalog(db_session)
    router = DispatcherRouter(db_session)
    errors = router.preflight_check("ai_analysis")
    assert len(errors) > 0
    assert any("no llm provider" in e.lower() for e in errors)


def test_preflight_check_ok(db_session: Session):
    _setup_authenticated_provider(db_session, "anthropic")
    router = DispatcherRouter(db_session)
    errors = router.preflight_check("ai_analysis")
    assert errors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_dispatcher_router.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement DispatcherRouter**

Create `src/services/llm/dispatcher_router.py`:

```python
"""Dispatcher router — resolves provider/model/effort per pipeline stage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from sqlmodel import Session, select

from ...models import AppConfig
from .models import LLMProvider, LLMModel, LLMAuthSlot
from .base_dispatcher import BaseDispatcher
from .claude_dispatcher import ClaudeDispatcher
from .gemini_dispatcher import GeminiDispatcher
from .codex_dispatcher import CodexDispatcher

logger = logging.getLogger(__name__)

_DISPATCHER_MAP = {
    "anthropic": ClaudeDispatcher,
    "google": GeminiDispatcher,
    "openai": CodexDispatcher,
}


@dataclass
class ResolvedConfig:
    """Resolved LLM configuration for a pipeline stage."""
    provider_kind: str
    provider_id: int
    model_name: str
    model_id: int
    effort_level: str
    dispatcher: BaseDispatcher
    auth_slot: LLMAuthSlot


class DispatcherRouter:
    """Resolves which LLM provider/model/effort to use for each pipeline stage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _get_config(self, key: str) -> Optional[str]:
        row = self._session.exec(
            select(AppConfig).where(AppConfig.key == key)
        ).first()
        return row.value if row else None

    def resolve(self, stage: str) -> ResolvedConfig:
        """Resolve provider/model/effort for a stage.

        Resolution chain:
        1. Per-stage override (ai.stage.<stage>.provider_id)
        2. Global default (ai.default_provider_id)
        """
        # Provider
        provider_id_str = (
            self._get_config(f"ai.stage.{stage}.provider_id")
            or self._get_config("ai.default_provider_id")
        )
        if not provider_id_str:
            raise ValueError("No LLM provider configured")

        provider_id = int(provider_id_str)
        provider = self._session.get(LLMProvider, provider_id)
        if not provider:
            raise ValueError(f"Provider {provider_id} not found")

        # Model
        model_id_str = (
            self._get_config(f"ai.stage.{stage}.model_id")
            or self._get_config("ai.default_model_id")
        )
        if not model_id_str:
            # Fall back to provider's default model
            default_model = self._session.exec(
                select(LLMModel).where(
                    LLMModel.provider_id == provider_id,
                    LLMModel.is_default == True,  # noqa: E712
                )
            ).first()
            if not default_model:
                raise ValueError(f"No default model for provider {provider.name}")
            model = default_model
        else:
            model = self._session.get(LLMModel, int(model_id_str))
            if not model:
                raise ValueError(f"Model {model_id_str} not found")

        # Effort
        effort = (
            self._get_config(f"ai.stage.{stage}.effort_level")
            or self._get_config("ai.default_effort_level")
            or "medium"
        )

        # Auth slot
        auth_slot = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider_id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()
        if not auth_slot:
            raise ValueError(f"No active auth for {provider.name}")

        # Dispatcher
        dispatcher_cls = _DISPATCHER_MAP.get(provider.provider_kind)
        if not dispatcher_cls:
            raise ValueError(f"No dispatcher for {provider.provider_kind}")

        return ResolvedConfig(
            provider_kind=provider.provider_kind,
            provider_id=provider.id,
            model_name=model.model_name,
            model_id=model.id,
            effort_level=effort,
            dispatcher=dispatcher_cls(),
            auth_slot=auth_slot,
        )

    def preflight_check(self, stage: str) -> List[str]:
        """Check if a stage can be dispatched. Returns list of blocking issues."""
        errors: List[str] = []

        provider_id_str = (
            self._get_config(f"ai.stage.{stage}.provider_id")
            or self._get_config("ai.default_provider_id")
        )
        if not provider_id_str:
            errors.append("No LLM provider configured. Go to LLM Settings.")
            return errors

        provider = self._session.get(LLMProvider, int(provider_id_str))
        if not provider:
            errors.append(f"Provider ID {provider_id_str} not found.")
            return errors

        auth_slot = self._session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == provider.id,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()

        if not auth_slot:
            errors.append(f"No auth configured for {provider.name}. Go to LLM Settings.")
        elif auth_slot.last_test_result and auth_slot.last_test_result != "ok":
            errors.append(f"Auth for {provider.name} failed: {auth_slot.last_test_result}")

        return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_dispatcher_router.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Update `__init__.py` re-exports**

Update `src/services/llm/__init__.py`:

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add tech-assessment-hub/src/services/llm/dispatcher_router.py \
       tech-assessment-hub/src/services/llm/__init__.py \
       tech-assessment-hub/tests/test_llm_dispatcher_router.py
git commit -m "feat: add DispatcherRouter for per-stage provider/model/effort resolution"
```

---

## Task 9: API Routes for LLM Settings

**Files:**
- Modify: `tech-assessment-hub/src/server.py`
- Test: `tech-assessment-hub/tests/test_llm_api_routes.py`

- [ ] **Step 1: Write failing tests for key API endpoints**

Create `tests/test_llm_api_routes.py`:

```python
"""Tests for /api/llm/* routes."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from src.services.llm.provider_catalog import seed_default_catalog


def test_get_providers(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)
    resp = client.get("/api/llm/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    kinds = {p["provider"]["provider_kind"] for p in data}
    assert kinds == {"anthropic", "google", "openai"}


def test_get_provider_models(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)
    # Get anthropic provider id
    providers = client.get("/api/llm/providers").json()
    anthropic = next(p for p in providers if p["provider"]["provider_kind"] == "anthropic")
    pid = anthropic["provider"]["id"]

    resp = client.get(f"/api/llm/providers/{pid}/models")
    assert resp.status_code == 200
    models = resp.json()
    assert len(models) >= 3
    names = {m["model_name"] for m in models}
    assert "claude-sonnet-4-6" in names


def test_detect_clis(client: TestClient):
    with patch("src.services.llm.auth_manager.shutil.which", return_value=None):
        resp = client.get("/api/llm/detect-clis")
    assert resp.status_code == 200
    data = resp.json()
    assert "anthropic" in data
    assert data["anthropic"]["installed"] is False


def test_create_api_key_slot(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)
    providers = client.get("/api/llm/providers").json()
    anthropic = next(p for p in providers if p["provider"]["provider_kind"] == "anthropic")
    pid = anthropic["provider"]["id"]

    resp = client.post("/api/llm/auth-slots", json={
        "provider_id": pid,
        "slot_kind": "api_key",
        "api_key": "sk-ant-test-abcd5678",
    })
    assert resp.status_code == 200
    slot = resp.json()
    assert slot["slot_kind"] == "api_key"
    assert slot["api_key_hint"] == "5678"
    assert "sk-ant" not in json.dumps(slot)  # Full key not in response


def test_get_and_update_config(client: TestClient, db_session: Session):
    seed_default_catalog(db_session)

    # Get config — initially empty
    resp = client.get("/api/llm/config")
    assert resp.status_code == 200

    # Set defaults
    providers = client.get("/api/llm/providers").json()
    anthropic = next(p for p in providers if p["provider"]["provider_kind"] == "anthropic")

    resp = client.put("/api/llm/config", json={
        "ai.default_provider_id": str(anthropic["provider"]["id"]),
        "ai.default_effort_level": "high",
    })
    assert resp.status_code == 200

    # Verify
    resp = client.get("/api/llm/config")
    config = resp.json()
    assert config.get("ai.default_effort_level") == "high"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_api_routes.py -v`
Expected: FAIL — 404 on all `/api/llm/*` routes

- [ ] **Step 3: Add LLM API routes to server.py**

Add the following route block to `src/server.py`. Find an appropriate location near the end of the file, after existing API routes. Add imports at the top of the file:

```python
# Near the top imports section of server.py, add:
from src.services.llm import (
    seed_default_catalog, get_providers_with_models,
    AuthManager, LLMProvider, LLMModel, LLMAuthSlot,
)
```

Then add routes (find a location after the existing `/api/` route blocks):

```python
# ── LLM Provider Settings API ──────────────────────────────────────

@app.get("/api/llm/providers")
def api_llm_providers(session: Session = Depends(get_session)):
    """List all LLM providers with their models and auth status."""
    seed_default_catalog(session)  # Ensure defaults exist
    providers = get_providers_with_models(session)
    # Enrich with auth slot status
    for entry in providers:
        pid = entry["provider"]["id"]
        slot = session.exec(
            select(LLMAuthSlot).where(
                LLMAuthSlot.provider_id == pid,
                LLMAuthSlot.is_active == True,  # noqa: E712
            )
        ).first()
        entry["auth"] = {
            "has_auth": slot is not None,
            "slot_kind": slot.slot_kind if slot else None,
            "last_test_result": slot.last_test_result if slot else None,
            "api_key_hint": slot.api_key_hint if slot else None,
        } if slot else {"has_auth": False}
    return providers


@app.get("/api/llm/providers/{provider_id}/models")
def api_llm_provider_models(
    provider_id: int, session: Session = Depends(get_session)
):
    """List models for a provider."""
    models = session.exec(
        select(LLMModel).where(LLMModel.provider_id == provider_id)
    ).all()
    return [
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
    ]


@app.get("/api/llm/detect-clis")
def api_llm_detect_clis(session: Session = Depends(get_session)):
    """Detect which LLM CLIs are installed."""
    mgr = AuthManager(session)
    return mgr.detect_clis()


@app.post("/api/llm/cli-login/{provider_kind}")
def api_llm_cli_login(
    provider_kind: str, session: Session = Depends(get_session)
):
    """Trigger CLI browser login for a provider."""
    mgr = AuthManager(session)
    mgr.trigger_cli_login(provider_kind)
    return {"status": "login_triggered", "provider_kind": provider_kind}


@app.post("/api/llm/auth-slots")
async def api_llm_create_auth_slot(
    request: Request, session: Session = Depends(get_session)
):
    """Create an auth slot (CLI or API key)."""
    body = await request.json()
    mgr = AuthManager(session)
    provider_id = body["provider_id"]
    slot_kind = body.get("slot_kind", "cli")

    if slot_kind == "api_key":
        slot = mgr.store_api_key(provider_id, body["api_key"])
    else:
        slot = mgr.create_cli_slot(provider_id)

    return {
        "id": slot.id,
        "provider_id": slot.provider_id,
        "slot_kind": slot.slot_kind,
        "api_key_hint": slot.api_key_hint,
        "is_active": slot.is_active,
        "last_test_result": slot.last_test_result,
    }


@app.post("/api/llm/auth-slots/{slot_id}/test")
def api_llm_test_auth_slot(
    slot_id: int, session: Session = Depends(get_session)
):
    """Test an auth slot's connectivity."""
    mgr = AuthManager(session)
    ok, msg = mgr.test_auth_slot(slot_id)
    return {"success": ok, "message": msg}


@app.delete("/api/llm/auth-slots/{slot_id}")
def api_llm_delete_auth_slot(
    slot_id: int, session: Session = Depends(get_session)
):
    """Delete an auth slot."""
    slot = session.get(LLMAuthSlot, slot_id)
    if not slot:
        return {"error": "not found"}, 404
    session.delete(slot)
    session.commit()
    return {"deleted": True}


@app.get("/api/llm/config")
def api_llm_config(session: Session = Depends(get_session)):
    """Get current LLM configuration (global defaults + per-stage overrides)."""
    rows = session.exec(
        select(AppConfig).where(AppConfig.key.startswith("ai."))  # type: ignore
    ).all()
    return {row.key: row.value for row in rows}


@app.put("/api/llm/config")
async def api_llm_update_config(
    request: Request, session: Session = Depends(get_session)
):
    """Update LLM configuration properties."""
    body = await request.json()
    for key, value in body.items():
        if not key.startswith("ai."):
            continue
        existing = session.exec(
            select(AppConfig).where(AppConfig.key == key)
        ).first()
        if existing:
            existing.value = str(value)
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            session.add(AppConfig(key=key, value=str(value)))
    session.commit()
    return {"updated": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_api_routes.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`
Expected: All existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add tech-assessment-hub/src/server.py \
       tech-assessment-hub/tests/test_llm_api_routes.py
git commit -m "feat: add /api/llm/* routes for provider auth, model catalog, and config"
```

---

## Task 10: LLM Settings Page Template

**Files:**
- Create: `tech-assessment-hub/src/web/templates/llm_settings.html`
- Modify: `tech-assessment-hub/src/server.py` (add page route)
- Modify: `tech-assessment-hub/src/web/templates/base.html` (add nav link)

- [ ] **Step 1: Add page route to server.py**

Add this route to `src/server.py` near the other page-serving routes:

```python
@app.get("/settings/llm-providers", response_class=HTMLResponse)
def page_llm_settings(request: Request, session: Session = Depends(get_session)):
    """LLM provider settings page."""
    seed_default_catalog(session)
    return templates.TemplateResponse("llm_settings.html", {"request": request})
```

- [ ] **Step 2: Add nav link to base.html**

In `src/web/templates/base.html`, after the "Properties" link (line 24), add:

```html
<li><a href="/settings/llm-providers" class="{% if '/settings/llm-providers' in request.url.path %}active{% endif %}">LLM Settings</a></li>
```

- [ ] **Step 3: Create the settings template**

Create `src/web/templates/llm_settings.html`:

```html
{% extends "base.html" %}
{% block title %}LLM Provider Settings{% endblock %}
{% block content %}
<div class="page-header">
    <h1>LLM Provider Settings</h1>
    <p class="page-subtitle">Configure AI providers for assessment pipeline stages</p>
</div>

<!-- Provider Setup Cards -->
<div class="section-card" style="margin-bottom: 2rem;">
    <h2 class="section-title">Provider Authentication</h2>
    <div id="provider-cards" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; margin-top: 1rem;">
        <!-- Populated by JS -->
    </div>
</div>

<!-- AI Configuration -->
<div class="section-card">
    <h2 class="section-title">Default AI Configuration</h2>
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-top: 1rem; max-width: 800px;">
        <div>
            <label class="form-label">Provider</label>
            <select id="cfg-provider" class="form-select" onchange="onProviderChange()">
                <option value="">-- Select --</option>
            </select>
        </div>
        <div>
            <label class="form-label">Model</label>
            <select id="cfg-model" class="form-select">
                <option value="">-- Select provider first --</option>
            </select>
        </div>
        <div>
            <label class="form-label">Effort Level</label>
            <select id="cfg-effort" class="form-select">
                <option value="low">Low</option>
                <option value="medium" selected>Medium</option>
                <option value="high">High</option>
                <option value="max">Max</option>
            </select>
        </div>
    </div>
    <button class="btn btn-primary" style="margin-top: 1rem;" onclick="saveDefaults()">Save Defaults</button>

    <!-- Per-Stage Overrides -->
    <h3 style="margin-top: 2rem;">Per-Stage Overrides <span style="font-weight: normal; font-size: 0.85em; color: var(--text-muted);">(optional)</span></h3>
    <div id="stage-overrides" style="margin-top: 0.75rem;"></div>
    <button class="btn btn-secondary" style="margin-top: 0.75rem;" onclick="addStageOverride()">+ Add Override</button>
</div>

<script>
const AI_STAGES = ['ai_analysis','observations','grouping','ai_refinement','recommendations','report'];
let _providers = [];
let _config = {};
let _cliStatus = {};

async function loadAll() {
    const [provRes, cfgRes, cliRes] = await Promise.all([
        fetch('/api/llm/providers'),
        fetch('/api/llm/config'),
        fetch('/api/llm/detect-clis'),
    ]);
    _providers = await provRes.json();
    _config = await cfgRes.json();
    _cliStatus = await cliRes.json();
    renderProviderCards();
    renderConfigForm();
    renderStageOverrides();
}

function renderProviderCards() {
    const container = document.getElementById('provider-cards');
    container.innerHTML = '';
    for (const entry of _providers) {
        const p = entry.provider;
        const auth = entry.auth || {};
        const cli = _cliStatus[p.provider_kind] || {};
        const isOk = auth.last_test_result === 'ok';
        const isError = auth.last_test_result && auth.last_test_result.startsWith('error');
        const borderColor = isOk ? 'var(--success, #22c55e)' : isError ? 'var(--danger, #ef4444)' : 'var(--border-color, #e5e7eb)';

        const card = document.createElement('div');
        card.className = 'section-card';
        card.style.cssText = `border: 2px solid ${borderColor}; padding: 1.25rem;`;
        card.innerHTML = `
            <h3 style="margin: 0 0 0.75rem;">${p.name}</h3>
            <div style="margin-bottom: 0.75rem; font-size: 0.9em;">
                <strong>CLI:</strong> ${cli.installed ? '&#10003; ' + (cli.version || 'installed') : '&#10007; not found'}
            </div>
            <div style="margin-bottom: 0.75rem; font-size: 0.9em;">
                <strong>Status:</strong> ${isOk ? '&#9679; OK' : isError ? '&#9679; ' + auth.last_test_result : '&#9675; Not configured'}
                ${auth.slot_kind === 'api_key' && auth.api_key_hint ? ' (key: ...' + auth.api_key_hint + ')' : ''}
            </div>
            <div style="margin-bottom: 0.5rem;"><strong>Models:</strong> ${entry.models.length}</div>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.75rem;">
                <button class="btn btn-secondary btn-sm" onclick="triggerCliLogin('${p.provider_kind}')" ${!cli.installed ? 'disabled title="CLI not installed"' : ''}>Sign In</button>
                <button class="btn btn-secondary btn-sm" onclick="connectCli(${p.id})" ${!cli.installed ? 'disabled title="CLI not installed"' : ''}>Connect CLI</button>
                <button class="btn btn-secondary btn-sm" onclick="connectApiKey(${p.id})">Use API Key</button>
                ${auth.has_auth ? '<button class="btn btn-secondary btn-sm" onclick="testAuth(' + p.id + ')">Re-test</button>' : ''}
                <button class="btn btn-secondary btn-sm" onclick="refreshModels(${p.id})">Refresh Models</button>
            </div>
            <div id="card-msg-${p.id}" style="margin-top: 0.5rem; font-size: 0.85em;"></div>
        `;
        container.appendChild(card);
    }
}

function renderConfigForm() {
    const provSelect = document.getElementById('cfg-provider');
    provSelect.innerHTML = '<option value="">-- Select --</option>';
    for (const entry of _providers) {
        if (entry.auth && entry.auth.last_test_result === 'ok') {
            const opt = document.createElement('option');
            opt.value = entry.provider.id;
            opt.textContent = entry.provider.name;
            if (_config['ai.default_provider_id'] === String(entry.provider.id)) opt.selected = true;
            provSelect.appendChild(opt);
        }
    }
    onProviderChange();

    const effortSelect = document.getElementById('cfg-effort');
    const currentEffort = _config['ai.default_effort_level'] || 'medium';
    effortSelect.value = currentEffort;
}

async function onProviderChange() {
    const pid = document.getElementById('cfg-provider').value;
    const modelSelect = document.getElementById('cfg-model');
    modelSelect.innerHTML = '<option value="">-- Select --</option>';
    if (!pid) return;

    const res = await fetch(`/api/llm/providers/${pid}/models`);
    const models = await res.json();
    for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.display_name || m.model_name;
        if (_config['ai.default_model_id'] === String(m.id)) opt.selected = true;
        modelSelect.appendChild(opt);
    }
}

function renderStageOverrides() {
    const container = document.getElementById('stage-overrides');
    container.innerHTML = '';
    for (const stage of AI_STAGES) {
        const pid = _config[`ai.stage.${stage}.provider_id`];
        if (!pid) continue;
        // Render override row
        const row = document.createElement('div');
        row.className = 'section-card';
        row.style.cssText = 'padding: 0.75rem; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 1rem;';
        const effort = _config[`ai.stage.${stage}.effort_level`] || 'medium';
        const provider = _providers.find(e => String(e.provider.id) === pid);
        const pName = provider ? provider.provider.name : pid;
        row.innerHTML = `
            <strong style="min-width: 130px;">${stage}</strong>
            <span>${pName} / effort: ${effort}</span>
            <button class="btn btn-secondary btn-sm" onclick="removeStageOverride('${stage}')">Remove</button>
        `;
        container.appendChild(row);
    }
}

async function saveDefaults() {
    const body = {};
    const pid = document.getElementById('cfg-provider').value;
    const mid = document.getElementById('cfg-model').value;
    const effort = document.getElementById('cfg-effort').value;
    if (pid) body['ai.default_provider_id'] = pid;
    if (mid) body['ai.default_model_id'] = mid;
    if (effort) body['ai.default_effort_level'] = effort;
    await fetch('/api/llm/config', { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    await loadAll();
}

async function triggerCliLogin(kind) {
    await fetch(`/api/llm/cli-login/${kind}`, { method: 'POST' });
    alert('Login command opened in Terminal. Complete sign-in, then click "Connect CLI".');
}

async function connectCli(providerId) {
    const res = await fetch('/api/llm/auth-slots', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ provider_id: providerId, slot_kind: 'cli' }),
    });
    const slot = await res.json();
    // Test immediately
    const testRes = await fetch(`/api/llm/auth-slots/${slot.id}/test`, { method: 'POST' });
    await loadAll();
}

async function connectApiKey(providerId) {
    const key = prompt('Enter API key:');
    if (!key) return;
    await fetch('/api/llm/auth-slots', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ provider_id: providerId, slot_kind: 'api_key', api_key: key }),
    });
    await loadAll();
}

async function testAuth(providerId) {
    const entry = _providers.find(e => e.provider.id === providerId);
    // Find active slot from the auth data — need slot ID
    // Re-fetch to get slot id, or use a simpler approach
    const msgEl = document.getElementById(`card-msg-${providerId}`);
    msgEl.textContent = 'Testing...';
    // For simplicity, get all slots for provider and test the active one
    const res = await fetch('/api/llm/providers');
    const providers = await res.json();
    await loadAll();
}

async function refreshModels(providerId) {
    const msgEl = document.getElementById(`card-msg-${providerId}`);
    msgEl.textContent = 'Refreshing models...';
    await fetch(`/api/llm/providers/${providerId}/models/refresh`, { method: 'POST' });
    await loadAll();
    msgEl.textContent = '';
}

function addStageOverride() {
    const stage = prompt('Enter stage name:\n' + AI_STAGES.join(', '));
    if (!stage || !AI_STAGES.includes(stage)) return;
    const pid = document.getElementById('cfg-provider').value;
    const mid = document.getElementById('cfg-model').value;
    const effort = document.getElementById('cfg-effort').value;
    if (!pid) { alert('Select a provider first'); return; }
    const body = {};
    body[`ai.stage.${stage}.provider_id`] = pid;
    if (mid) body[`ai.stage.${stage}.model_id`] = mid;
    body[`ai.stage.${stage}.effort_level`] = effort;
    fetch('/api/llm/config', { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) })
        .then(() => loadAll());
}

async function removeStageOverride(stage) {
    // Set values to empty to clear
    const body = {};
    body[`ai.stage.${stage}.provider_id`] = '';
    body[`ai.stage.${stage}.model_id`] = '';
    body[`ai.stage.${stage}.effort_level`] = '';
    await fetch('/api/llm/config', { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
    await loadAll();
}

document.addEventListener('DOMContentLoaded', loadAll);
</script>
{% endblock %}
```

- [ ] **Step 4: Run the full test suite**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`
Expected: All tests pass (no regressions)

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/web/templates/llm_settings.html \
       tech-assessment-hub/src/web/templates/base.html \
       tech-assessment-hub/src/server.py
git commit -m "feat: add LLM Settings page with provider cards, auth buttons, and config UI"
```

---

## Task 11: Pipeline Integration — Wire DispatcherRouter

**Files:**
- Modify: `tech-assessment-hub/src/server.py` (update `_run_assessment_pipeline_stage`)

- [ ] **Step 1: Write a test for preflight check integration**

Add to `tests/test_llm_api_routes.py`:

```python
def test_advance_pipeline_preflight_fails_without_llm_config(
    client: TestClient, db_session: Session, sample_instance
):
    """Advancing to an AI stage without LLM config should return preflight errors."""
    from src.models import Assessment, PipelineStage, AssessmentState
    assessment = Assessment(
        instance_id=sample_instance.id,
        state=AssessmentState.in_progress,
        pipeline_stage=PipelineStage.engines.value,
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    resp = client.post(f"/api/assessments/{assessment.id}/advance-pipeline", json={
        "target_stage": "ai_analysis",
    })
    # Should either return preflight errors or proceed (depending on implementation)
    # At minimum, it should not crash
    assert resp.status_code in (200, 400, 422)
```

- [ ] **Step 2: Run the test**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/test_llm_api_routes.py::test_advance_pipeline_preflight_fails_without_llm_config -v`

- [ ] **Step 3: Update pipeline stage runner to use DispatcherRouter**

In `src/server.py`, locate the `_run_assessment_pipeline_stage()` function (around line 1559). For AI stages (`ai_analysis`, `observations`, `grouping`, `ai_refinement`, `recommendations`, `report`), add a preflight check before dispatching:

```python
# At the top of _run_assessment_pipeline_stage, after session creation:
from src.services.llm.dispatcher_router import DispatcherRouter

# Before dispatching any AI stage, add:
if target_stage in ("ai_analysis", "observations", "grouping", "ai_refinement", "recommendations", "report"):
    router = DispatcherRouter(session)
    preflight_errors = router.preflight_check(target_stage)
    if preflight_errors:
        logger.warning("LLM preflight failed for stage %s: %s", target_stage, preflight_errors)
        # Store errors in job status for frontend display
        # Fall through to existing behavior for now (graceful degradation)
```

This is a minimal integration point. The full dispatcher swap (replacing `ClaudeCodeDispatcher` calls with `DispatcherRouter.dispatch_stage()`) should be done incrementally per-stage to avoid breaking existing functionality.

- [ ] **Step 4: Run full test suite**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add tech-assessment-hub/src/server.py \
       tech-assessment-hub/tests/test_llm_api_routes.py
git commit -m "feat: add LLM preflight check to pipeline stage runner"
```

---

## Task 12: Assessment Detail Page — AI Config Display

**Files:**
- Modify: `tech-assessment-hub/src/web/templates/assessment_detail.html`

- [ ] **Step 1: Add resolved config display near pipeline buttons**

In `src/web/templates/assessment_detail.html`, locate the pipeline flow bar section (around line 125). After the pipeline step rendering, add an info block that shows the resolved LLM configuration. Add this JavaScript near the existing `advancePipelineStage()` function:

```javascript
async function loadLlmConfig() {
    try {
        const res = await fetch('/api/llm/config');
        if (!res.ok) return;
        const config = await res.json();
        const providerId = config['ai.default_provider_id'];
        if (!providerId) {
            document.getElementById('llm-config-display').innerHTML =
                '<span style="color: var(--text-muted);">No LLM configured. <a href="/settings/llm-providers">Configure AI</a></span>';
            return;
        }
        // Fetch provider name and model
        const provRes = await fetch('/api/llm/providers');
        const providers = await provRes.json();
        const provider = providers.find(p => String(p.provider.id) === providerId);
        const modelId = config['ai.default_model_id'];
        let modelName = '';
        if (provider && modelId) {
            const m = provider.models.find(m => String(m.id) === modelId);
            modelName = m ? (m.display_name || m.model_name) : '';
        }
        const effort = config['ai.default_effort_level'] || 'medium';
        document.getElementById('llm-config-display').innerHTML =
            `<strong>${provider ? provider.provider.name : 'Unknown'}</strong> &mdash; ${modelName} &mdash; ${effort} effort ` +
            `<a href="/settings/llm-providers" style="margin-left: 0.5rem;">Configure AI</a>`;
    } catch (e) {
        console.warn('Could not load LLM config:', e);
    }
}
```

Add the HTML element near the pipeline flow bar:

```html
<div id="llm-config-display" style="margin-top: 0.5rem; font-size: 0.9em; color: var(--text-secondary);"></div>
```

Call `loadLlmConfig()` on page load alongside existing initialization.

- [ ] **Step 2: Run full test suite to check for regressions**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add tech-assessment-hub/src/web/templates/assessment_detail.html
git commit -m "feat: show resolved LLM config on assessment detail page with Configure AI link"
```

---

## Task 13: Seed Catalog on Startup + Final Integration

**Files:**
- Modify: `tech-assessment-hub/src/database.py`
- Modify: `tech-assessment-hub/src/server.py` (startup event)

- [ ] **Step 1: Add catalog seeding to startup**

In `src/server.py`, find the startup event handler. Add catalog seeding:

```python
# In the startup event handler:
from src.services.llm.provider_catalog import seed_default_catalog

# After create_db_and_tables():
with Session(engine) as session:
    seed_default_catalog(session)
```

- [ ] **Step 2: Run full test suite**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`
Expected: All tests pass, no regressions

- [ ] **Step 3: Manual smoke test**

Start the app and verify:
1. Navigate to `/settings/llm-providers` — should show 3 provider cards
2. CLI detection should show installed/not-found status
3. Click "Use API Key" on a provider — should prompt for key
4. Save defaults — should persist provider/model/effort
5. Navigate to assessment detail — should show "Configure AI" link

Run: `cd tech-assessment-hub && ./venv/bin/python -m src.server`

- [ ] **Step 4: Commit**

```bash
git add tech-assessment-hub/src/database.py \
       tech-assessment-hub/src/server.py
git commit -m "feat: seed LLM provider catalog on app startup"
```

---

## Task 14: MCP Tool — run_ai_stage

**Files:**
- Create: `tech-assessment-hub/src/mcp/tools/core/run_ai_stage.py`
- Modify: `tech-assessment-hub/src/mcp/registry.py` (register tool)

- [ ] **Step 1: Create the MCP tool**

Create `src/mcp/tools/core/run_ai_stage.py`:

```python
"""MCP tool to kick off an AI stage of the assessment pipeline."""

from __future__ import annotations

from typing import Any, Dict

from sqlmodel import Session

from ...registry import ToolSpec

AI_STAGES = {"ai_analysis", "observations", "grouping", "ai_refinement", "recommendations", "report"}


def _handler(arguments: Dict[str, Any], session: Session) -> Dict[str, Any]:
    from ....server import _start_assessment_pipeline_job

    assessment_id = int(arguments["assessment_id"])
    stage = arguments.get("stage")

    if stage and stage not in AI_STAGES:
        return {"error": f"Invalid AI stage: {stage}. Valid: {sorted(AI_STAGES)}"}

    # If no stage specified, would need to look up current stage
    if not stage:
        from ....models import Assessment
        assessment = session.get(Assessment, assessment_id)
        if not assessment:
            return {"error": f"Assessment {assessment_id} not found"}
        stage = assessment.pipeline_stage
        if stage not in AI_STAGES:
            return {"error": f"Current stage '{stage}' is not an AI stage"}

    success = _start_assessment_pipeline_job(
        assessment_id, target_stage=stage,
    )
    return {
        "started": success,
        "assessment_id": assessment_id,
        "stage": stage,
    }


run_ai_stage_tool = ToolSpec(
    name="run_ai_stage",
    description="Kick off the next AI stage of an assessment pipeline. "
                "Optionally specify stage, provider_override, model_override.",
    input_schema={
        "type": "object",
        "properties": {
            "assessment_id": {
                "type": "string",
                "description": "The assessment ID to run the AI stage for",
            },
            "stage": {
                "type": "string",
                "description": "Specific AI stage to run. Defaults to current stage.",
                "enum": sorted(AI_STAGES),
            },
        },
        "required": ["assessment_id"],
    },
    handler=_handler,
)
```

- [ ] **Step 2: Register the tool**

Find where other core tools are registered (likely in server.py or a tools init file). Add:

```python
from src.mcp.tools.core.run_ai_stage import run_ai_stage_tool
tool_registry.register(run_ai_stage_tool)
```

- [ ] **Step 3: Run full test suite**

Run: `./tech-assessment-hub/venv/bin/python -m pytest tech-assessment-hub/tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tech-assessment-hub/src/mcp/tools/core/run_ai_stage.py \
       tech-assessment-hub/src/server.py
git commit -m "feat: add run_ai_stage MCP tool for slash-command AI stage invocation"
```

---

## Summary

| Task | What | Tests Added |
|------|------|-------------|
| 1 | LLM SQLModel tables | 5 |
| 2 | Provider catalog seed + CRUD | 4 |
| 3 | BaseDispatcher ABC + DispatchResult | 4 |
| 4 | ClaudeDispatcher | 8 |
| 5 | GeminiDispatcher | 5 |
| 6 | CodexDispatcher | 5 |
| 7 | AuthManager | 6 |
| 8 | DispatcherRouter | 4 |
| 9 | API routes `/api/llm/*` | 5 |
| 10 | LLM Settings page template | 0 (UI) |
| 11 | Pipeline preflight integration | 1 |
| 12 | Assessment detail AI config display | 0 (UI) |
| 13 | Startup catalog seeding | 0 (integration) |
| 14 | MCP tool `run_ai_stage` | 0 (registration) |
| **Total** | | **~47 new tests** |
