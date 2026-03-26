# LLM Provider Authentication & Multi-Provider Dispatch

**Date:** 2026-03-26
**Status:** Approved
**Scope:** Add in-app LLM provider authentication, model catalog, adapter-based dispatch, and settings UI to the Tech Assessment Hub

## Problem

The app currently only supports Claude via CLI subprocess (`claude_code_dispatcher.py`) with auth managed entirely outside the app (env vars, manual CLI login). There is no in-app settings UI for LLM configuration, no support for Gemini or OpenAI/Codex, and no way to mix providers across pipeline stages.

## Goals

1. Authenticate LLM providers (Claude, Gemini, GPT/Codex) from within the app
2. Support both CLI subscription auth and API key auth per provider
3. Store provider catalog, models, and auth credentials in SQLite
4. Allow users to pick provider, model, and effort/reasoning level
5. Support per-stage provider overrides (use different LLMs for different AI stages)
6. Enable kicking off AI stages from the app via button and MCP tool
7. Future-ready for multi-instance concurrent dispatch per stage

## Reference Implementation

Based on patterns from the Agent Orchestration App at `/Volumes/SN_TA_MCP/Agent Orchestration App`, adapted to this app's Flask + SQLite + Jinja + MCP architecture.

---

## 1. Database Schema

### 1.1 New Tables

#### `llm_providers`

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `provider_kind` | TEXT UNIQUE | `anthropic` / `google` / `openai` |
| `name` | TEXT | Display name, e.g. "Anthropic (Claude)" |
| `cli_command` | TEXT | CLI binary name: `claude` / `gemini` / `codex` |
| `api_base_url` | TEXT | Provider API base endpoint |
| `is_active` | BOOLEAN | Soft delete flag |
| `created_at` | TEXT | ISO timestamp |

#### `llm_models`

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `provider_id` | TEXT FK | References `llm_providers.id` |
| `model_name` | TEXT | API model identifier, e.g. `claude-opus-4-6` |
| `display_name` | TEXT | Friendly name for UI |
| `context_window` | INTEGER | Context window size |
| `supports_effort` | BOOLEAN | Whether effort/reasoning levels apply |
| `is_default` | BOOLEAN | Default model for this provider |
| `source` | TEXT | `builtin` / `fetched` / `manual` |

#### `llm_auth_slots`

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `provider_id` | TEXT FK | References `llm_providers.id` |
| `slot_kind` | TEXT | `cli` / `api_key` |
| `api_key` | TEXT | Plaintext key (local-only deployment) |
| `api_key_hint` | TEXT | Last 4 chars for display |
| `env_var_name` | TEXT | Alternative: read key from environment variable |
| `is_active` | BOOLEAN | Currently selected auth slot for this provider |
| `last_tested_at` | TEXT | ISO timestamp of last test |
| `last_test_result` | TEXT | `ok` or `error: <message>` |

### 1.2 New AppConfig Properties

Global defaults:
```
ai.default_provider_id      → UUID of default llm_providers row
ai.default_model_id          → UUID of default llm_models row
ai.default_effort_level      → low / medium / high / max
```

Per-stage overrides (optional, inherit global if not set):
```
ai.stage.<stage>.provider_id     → provider override for this stage
ai.stage.<stage>.model_id        → model override for this stage
ai.stage.<stage>.effort_level    → effort override for this stage
ai.stage.<stage>.instance_count  → concurrent instances (default 1, future use)
```

Where `<stage>` is one of: `ai_analysis`, `observations`, `grouping`, `ai_refinement`, `recommendations`, `report`.

### 1.3 Hardcoded Default Catalog

Seeded into `llm_providers` and `llm_models` on first run (when tables are empty):

```python
DEFAULT_CATALOG = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "cli_command": "claude",
        "api_base_url": "https://api.anthropic.com/v1",
        "models": [
            {"name": "claude-opus-4-6", "ctx": 1_000_000, "effort": True, "default": False},
            {"name": "claude-sonnet-4-6", "ctx": 1_000_000, "effort": True, "default": True},
            {"name": "claude-haiku-4-5-20251001", "ctx": 200_000, "effort": True, "default": False},
        ]
    },
    "google": {
        "name": "Google (Gemini)",
        "cli_command": "gemini",
        "api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": [
            {"name": "gemini-2.5-pro", "ctx": 1_000_000, "effort": False, "default": True},
            {"name": "gemini-2.5-flash", "ctx": 1_000_000, "effort": False, "default": False},
        ]
    },
    "openai": {
        "name": "OpenAI (GPT/Codex)",
        "cli_command": "codex",
        "api_base_url": "https://api.openai.com/v1",
        "models": [
            {"name": "gpt-4.1", "ctx": 1_000_000, "effort": False, "default": True},
            {"name": "o3", "ctx": 200_000, "effort": True, "default": False},
            {"name": "codex-mini", "ctx": 1_000_000, "effort": False, "default": False},
        ]
    }
}
```

---

## 2. Adapter Dispatcher Architecture

### 2.1 File Structure

```
src/services/llm/
├── __init__.py
├── base_dispatcher.py       # Abstract base class
├── claude_dispatcher.py     # Claude CLI + API adapter
├── gemini_dispatcher.py     # Gemini CLI + API adapter
├── codex_dispatcher.py      # Codex/OpenAI CLI + API adapter
├── dispatcher_router.py     # Routes to correct adapter by provider
├── provider_catalog.py      # Seed, fetch, CRUD for catalog tables
└── auth_manager.py          # CLI detection, login, key storage, test
```

### 2.2 BaseDispatcher

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class DispatchResult:
    success: bool
    batch_index: int
    total_batches: int
    artifacts_processed: int
    claude_output: dict      # normalized JSON (same shape for all providers)
    error: Optional[str]
    duration_seconds: float
    budget_used_usd: Optional[float]
    provider_kind: str
    model_name: str

class BaseDispatcher(ABC):
    provider_kind: str

    @abstractmethod
    def build_cli_command(self, prompt: str, model: str, effort: str | None,
                          tools: list[str]) -> list[str]:
        """Build CLI argument list for subprocess invocation."""

    @abstractmethod
    def parse_cli_output(self, stdout: str) -> DispatchResult:
        """Normalize provider-specific JSON output to DispatchResult."""

    @abstractmethod
    def test_cli_auth(self) -> tuple[bool, str]:
        """Quick CLI auth check. Returns (success, message)."""

    @abstractmethod
    def test_api_key(self, api_key: str) -> tuple[bool, str]:
        """Validate API key against provider endpoint. Returns (success, message)."""

    @abstractmethod
    def fetch_models(self, auth_slot) -> list[dict]:
        """Live-fetch available models from provider API."""

    def map_effort(self, unified_level: str) -> str | None:
        """Map unified effort level to provider-native value. Override per provider."""
        return None

    def dispatch(self, prompt: str, model: str, effort: str,
                 tools: list[str], mode: str) -> DispatchResult:
        """Main entry point. Builds command, spawns subprocess, parses output.
        Shared logic: timeout, budget check, checkpoint, error handling."""
```

### 2.3 Provider-Specific Command Builders

**ClaudeDispatcher:**
```python
def build_cli_command(self, prompt, model, effort, tools):
    cmd = ["claude", "-p", "--verbose",
           "--model", model or "sonnet",
           "--output-format", "stream-json",
           "--dangerously-skip-permissions"]
    if effort:
        cmd.extend(["--effort", self.map_effort(effort) or "medium"])
    return cmd

def map_effort(self, level):
    return {"low": "low", "medium": "medium", "high": "high", "max": "max"}[level]

def test_cli_auth(self):
    # Run: claude -p --max-turns 0 "respond with ok"
    ...

def test_api_key(self, api_key):
    # POST to https://api.anthropic.com/v1/messages with x-api-key header
    ...
```

**GeminiDispatcher:**
```python
def build_cli_command(self, prompt, model, effort, tools):
    return ["gemini", "-p",
            "--model", model or "gemini-2.5-pro",
            "--approval-mode", "yolo",
            "--output-format", "stream-json"]

def map_effort(self, level):
    return None  # Gemini CLI does not support effort flags

def test_cli_auth(self):
    # Run: gemini --prompt "respond with just ok"
    ...

def test_api_key(self, api_key):
    # GET https://generativelanguage.googleapis.com/v1beta/models?key={key}
    ...
```

**CodexDispatcher:**
```python
def build_cli_command(self, prompt, model, effort, tools):
    return ["codex", "exec",
            "--model", model or "gpt-4.1",
            "--json",
            "--dangerously-bypass-approvals-and-sandbox"]

def map_effort(self, level):
    # Only o-series models support reasoning_effort
    return {"low": "low", "medium": "medium", "high": "high", "max": "high"}.get(level)

def test_cli_auth(self):
    # Run: codex login status
    ...

def test_api_key(self, api_key):
    # GET https://api.openai.com/v1/models with Authorization: Bearer header
    ...
```

### 2.4 DispatcherRouter

```python
class DispatcherRouter:
    _adapters = {
        "anthropic": ClaudeDispatcher,
        "google": GeminiDispatcher,
        "openai": CodexDispatcher,
    }

    def resolve(self, stage: str, assessment_id: str) -> ResolvedConfig:
        """Resolution chain:
        1. Check per-stage override: ai.stage.<stage>.provider_id
        2. Fall back to global default: ai.default_provider_id
        3. Look up active auth slot for that provider
        4. Instantiate correct dispatcher subclass
        5. Resolve model (per-stage → global default)
        6. Resolve effort (per-stage → global default)
        Returns ResolvedConfig(dispatcher, model, effort, auth_slot)
        """

    def preflight_check(self, stage: str, assessment_id: str) -> list[str]:
        """Returns list of blocking issues, empty if ready.
        Checks: provider configured, auth slot exists, last test ok, CLI installed."""

    def dispatch_stage(self, stage: str, assessment_id: str,
                       artifacts: list, tools: list[str]) -> DispatchResult:
        """Main pipeline entry point. Resolves config, runs preflight,
        dispatches via adapter. Supports future fan-out when instance_count > 1."""
```

### 2.5 AuthManager

```python
class AuthManager:
    def detect_clis(self) -> dict[str, dict]:
        """Run '<cli> --version' for each provider.
        Returns {provider_kind: {installed: bool, version: str | None}}"""

    def trigger_cli_login(self, provider_kind: str) -> None:
        """Open Terminal.app with CLI login command via osascript (macOS).
        Claude: 'claude login', Gemini: 'gemini login', Codex: 'codex login'"""

    def test_auth_slot(self, slot_id: str) -> tuple[bool, str]:
        """Route to correct dispatcher's test_cli_auth or test_api_key
        based on slot_kind. Updates last_tested_at and last_test_result."""

    def store_api_key(self, provider_id: str, key: str) -> dict:
        """Create auth slot with slot_kind='api_key', store key + hint (last 4 chars)."""

    def create_cli_slot(self, provider_id: str) -> dict:
        """Create auth slot with slot_kind='cli', then test it."""

    def get_active_auth(self, provider_id: str) -> dict | None:
        """Get the active auth slot for a provider (is_active=True)."""
```

### 2.6 Migration from Existing Dispatcher

- Logic from `src/services/claude_code_dispatcher.py` moves into `ClaudeDispatcher`
- `DispatchResult` dataclass is extended with `provider_kind` and `model_name` fields
- `server.py` pipeline advancement calls `DispatcherRouter.dispatch_stage()` instead of calling `claude_code_dispatcher` directly
- Old `claude_code_dispatcher.py` is deprecated and removed once migration is verified
- Existing `ai_model_catalog.py` fetch logic is reused inside each dispatcher's `fetch_models()` method

---

## 3. Settings UI

### 3.1 Routes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/settings/llm-providers` | Render settings page |
| `GET` | `/api/llm/providers` | List providers with auth status + model counts |
| `POST` | `/api/llm/providers/auto-setup` | One-click setup: seed provider + models + auth + test |
| `GET` | `/api/llm/providers/{id}/models` | List models for a provider |
| `POST` | `/api/llm/providers/{id}/models/refresh` | Live-fetch models from provider API |
| `GET` | `/api/llm/detect-clis` | Check which CLIs are installed |
| `POST` | `/api/llm/cli-login/{provider_kind}` | Trigger CLI browser login (opens Terminal) |
| `POST` | `/api/llm/auth-slots` | Create auth slot (CLI or API key) |
| `POST` | `/api/llm/auth-slots/{id}/test` | Test auth slot connectivity |
| `DELETE` | `/api/llm/auth-slots/{id}` | Remove auth slot |
| `GET` | `/api/llm/config` | Get current default + per-stage config |
| `PUT` | `/api/llm/config` | Update default + per-stage config |

### 3.2 Page Layout

**Template:** `src/web/templates/llm_settings.html`

**Section 1 — Provider Setup Cards** (top of page):
- Three cards side-by-side: Anthropic, Google, OpenAI
- Each card shows:
  - CLI detection status (installed + version, or "not found")
  - Auth status badge (green "OK", red "Error: ...", gray "Not configured")
  - Three action buttons:
    - **"Sign In"** — triggers `cli-login`, opens browser via Terminal
    - **"Connect CLI"** — creates CLI auth slot and tests it
    - **"Use API Key"** — browser prompt for key, stores it
  - Model count + "Refresh Models" button
- Card border color: green if auth OK, red if error, gray if none

**Section 2 — AI Configuration** (below cards):
- **Global defaults:**
  - Provider dropdown (only shows authenticated providers)
  - Model dropdown (filters to selected provider's models)
  - Effort dropdown: Low / Medium / High / Max
  - "Save Defaults" button
- **Per-stage overrides:**
  - "+ Add Override" button → select stage from dropdown
  - Each override shows: stage name, provider, model, effort, instance count
  - "Remove" button to delete override (falls back to global default)

### 3.3 Navigation

- Add "LLM Settings" link to the app sidebar/nav
- Add "Configure AI" link on the assessment detail page near pipeline buttons

---

## 4. Pipeline Integration

### 4.1 Dispatch Flow (Updated)

1. User clicks "Advance" button on assessment detail page (unchanged)
2. `POST /api/assessments/{id}/advance-pipeline` (unchanged)
3. `server.py` calls `DispatcherRouter.dispatch_stage(stage, assessment_id, artifacts, tools)`
4. Router runs `preflight_check()` — if issues, returns errors to frontend with link to LLM Settings
5. Router calls `resolve()` → gets dispatcher instance, model, effort, auth slot
6. Dispatcher builds CLI command, spawns subprocess, parses output
7. Frontend polls for job status (unchanged)

### 4.2 Assessment Detail Page Changes

Add to the stage action area:
- **"Run AI Stage"** button — appears on AI-powered stages, same as Advance but shows resolved provider/model/effort
- **"Configure AI"** link — navigates to LLM Settings
- Resolved config display: "Provider: Anthropic (Claude) — claude-sonnet-4-6 — Medium effort"
- If no provider configured: button disabled with "Configure an LLM provider first" tooltip

### 4.3 Preflight Check

```python
def preflight_check(self, stage, assessment_id) -> list[str]:
    errors = []
    provider_id = get_stage_or_default_config(stage, "provider_id")
    if not provider_id:
        errors.append("No LLM provider configured. Go to LLM Settings.")
        return errors
    auth_slot = get_active_auth(provider_id)
    if not auth_slot:
        errors.append(f"No auth configured for {provider.name}. Go to LLM Settings.")
    elif auth_slot.last_test_result != "ok":
        errors.append(f"Auth for {provider.name} failed: {auth_slot.last_test_result}")
    if auth_slot and auth_slot.slot_kind == "cli":
        cli_status = detect_cli(provider.cli_command)
        if not cli_status["installed"]:
            errors.append(f"{provider.cli_command} CLI not found. Install it or use API key.")
    return errors
```

### 4.4 MCP Tool for Slash Command

```python
ToolSpec(
    name="run_ai_stage",
    description="Kick off the next AI stage of an assessment pipeline",
    parameters={
        "assessment_id": {"type": "string", "required": True},
        "stage": {"type": "string",
                  "description": "Specific stage to run. Defaults to current stage if AI-powered."},
        "provider_override": {"type": "string",
                              "description": "Override provider_kind for this run"},
        "model_override": {"type": "string",
                           "description": "Override model_name for this run"},
    }
)
```

### 4.5 Multi-Instance Fan-Out (Future-Ready)

When `ai.stage.<stage>.instance_count > 1`:
1. Split artifact list into N batches
2. Spawn N concurrent subprocesses (same provider/model/effort)
3. Track each subprocess in `_AssessmentScanJob`
4. Merge results when all complete
5. Report unified progress to frontend

This is architecturally supported but not implemented in v1. The `instance_count` property defaults to 1 and the UI field is present but informational.

---

## 5. Effort Level Mapping

Unified scale mapped to provider-native values:

| Unified Level | Claude (`--effort`) | OpenAI (o-series `reasoning_effort`) | Gemini |
|---------------|---------------------|--------------------------------------|--------|
| Low | `low` | `low` | N/A (ignored) |
| Medium | `medium` | `medium` | N/A (ignored) |
| High | `high` | `high` | N/A (ignored) |
| Max | `max` | `high` (capped) | N/A (ignored) |

- Effort is only passed to providers/models that support it (`supports_effort` flag on model)
- For models where effort doesn't apply, the setting is silently ignored

---

## 6. What Changes vs. What Stays

### Changes
- New `src/services/llm/` module (7 files)
- New DB tables: `llm_providers`, `llm_models`, `llm_auth_slots`
- New AppConfig properties: `ai.default_*`, `ai.stage.<stage>.*`
- New template: `llm_settings.html`
- New API routes: `/api/llm/*`
- New MCP tool: `run_ai_stage`
- `server.py` pipeline dispatch calls routed through `DispatcherRouter`
- Assessment detail template gets "Run AI Stage" button + config display

### Stays the Same
- Assessment detail page pipeline flow bar, polling, job tracking
- MCP prompts, per-stage tool sets, batch prompt template
- `_AssessmentScanJob` background job pattern
- `AppConfig` property system (extended, not replaced)
- All existing non-AI pipeline stages
- Review gate logic
- Existing `AIAnalysisProperties`, `AIRuntimeProperties` (coexist during migration, then deprecated)

---

## 7. Security Notes

- API keys stored plaintext in SQLite — acceptable for local-only single-user deployment
- CLI auth credentials managed by CLI tools themselves (not stored in app DB)
- `--dangerously-skip-permissions` and similar safety bypass flags used for headless operation
- No secrets sent to browser — `api_key_hint` (last 4 chars) shown in UI, never the full key
- `env_var_name` option allows keys to come from environment instead of DB storage
