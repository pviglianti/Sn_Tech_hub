# AI Inference Client — Design Document

**Date:** 2026-03-06
**Phase:** 8 — Direct AI Inference from Pipeline
**Status:** Approved

## Problem

The pipeline stages (ai_analysis, observations, ai_refinement, grouping, recommendations, report) prepare prompts via the PROMPT_REGISTRY and store them as `prompt_context` in `ai_observations` JSON, but never call a model. An external MCP client (Claude Desktop) is required to drive reasoning. This makes the pipeline dependent on an external tool and prevents end-to-end execution from the web app.

## Goal

Add a direct inference client so the pipeline calls the configured AI model in-process, using the provider/model/budget already configured in the AI Setup Wizard. The pipeline becomes fully self-contained — trigger from the web UI, AI runs, results land in the DB.

## Approach: Dual SDK Client (Approach C)

Two first-class SDKs:
- **Anthropic SDK** for `provider == "anthropic"` (native tool_use format)
- **OpenAI SDK** for everything else (OpenAI, DeepSeek, Gemini, Ollama, custom endpoints)

Phase 1 builds the Anthropic path. OpenAI path is Phase 2.

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `services/ai_client.py` | `AIClient` class — provider routing, `complete()`, `run_agent_loop()` |
| `services/ai_tool_sets.py` | Per-stage tool set definitions — which tools each stage exposes to the model |
| `services/ai_cost_table.py` | Token-to-USD cost lookup per model (dict constant, not DB) |

### Modified Files

| File | Change |
|------|--------|
| `server.py` | Pipeline stages call `ai_client.complete()` / `run_agent_loop()` instead of storing `prompt_context` |
| `services/assessment_runtime_usage.py` | Record actual token usage + cost after each inference call |
| `requirements.txt` | Add `anthropic` SDK |

### Core Client: `services/ai_client.py`

```python
@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class AIResponse:
    content: str | None           # text response
    tool_calls: list[ToolCall]    # tool_use blocks (if any)
    usage: TokenUsage             # for budget tracking
    stop_reason: str              # "end_turn", "tool_use", "max_tokens"

class AIClient:
    def __init__(self, ai_props: AIRuntimeProperties, env: dict[str, str]):
        """Initialize with properties from wizard + environment variables."""

    def complete(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> AIResponse:
        """Single inference call. Routes to Anthropic or OpenAI SDK."""

    def run_agent_loop(
        self,
        messages: list[dict],
        *,
        system: str,
        tools: list[dict],
        tool_executor: Callable[[str, dict], Any],
        max_turns: int = 10,
        budget_check: Callable[[TokenUsage], bool] | None = None,
    ) -> AgentLoopResult:
        """Multi-turn agent loop with tool calling.

        Calls complete() → if tool_use, calls tool_executor() → feeds result
        back → repeats until end_turn, max_turns, or budget exceeded.
        """
```

### Provider Routing

| Provider | SDK | base_url | API key env var |
|----------|-----|----------|-----------------|
| `anthropic` | `anthropic` | native SDK | `ANTHROPIC_API_KEY` |
| `openai` | `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `deepseek` | `openai` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` |
| `google_gemini` | `openai` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `GEMINI_API_KEY` |
| `openai_compatible_custom` | `openai` | `OPENAI_COMPATIBLE_BASE_URL` | `OPENAI_COMPATIBLE_API_KEY` |

Token limits respected from `AIRuntimeProperties.max_input_tokens_per_call` and `max_output_tokens_per_call`.

### Two Call Modes

#### Mode 1: Structured JSON (ai_analysis, observations, ai_refinement)

Pipeline stages iterate over artifacts. For each one:
1. Build prompt via `_try_registered_prompt_text()` (already works)
2. Call `ai_client.complete(messages=[system + user prompt])`
3. Parse text response as structured analysis
4. Store in `sr.ai_observations` — the model's actual analysis, not just the prompt
5. Record tokens to `assessment_runtime_usage`

Batching controlled by existing `AIAnalysisProperties.batch_size`.

#### Mode 2: Agentic Tool-Calling (grouping, recommendations, report)

1. Build system prompt via registered prompt
2. Assemble tool set via `ai_tool_sets.get_tools(stage, bridge_available=...)`
3. Call `ai_client.run_agent_loop(messages, tools, tool_executor)`
4. Tool executor routes: `REGISTRY.call()` for local tools, `BRIDGE_MANAGER.call_remote_tool()` for bridge tools
5. Loop until model returns `end_turn`, hits `max_turns`, or budget exceeded
6. Record cumulative tokens

### Per-Stage Tool Sets (`services/ai_tool_sets.py`)

| Stage | Local Tools (REGISTRY) | Bridge Tools (if available) |
|-------|----------------------|----------------------------|
| grouping | `get_suggested_groupings`, `create_feature`, `update_feature`, `add_result_to_feature`, `remove_result_from_feature`, `feature_detail`, `save_fact` | — |
| ai_refinement | `feature_detail`, `update_feature`, `update_result`, `save_fact`, `get_facts` | — |
| recommendations | `feature_recommendation`, `general_recommendation`, `update_result`, `update_feature`, `save_fact` | — |
| report | `assessment_results`, `feature_detail`, `get_facts`, `general_recommendation` | Word connector (`create_document`, `insert_text`, `save_document`), Excel connector |

### Document Generation (Report Stage)

**Primary path:** If Word/Excel MCP connectors are detected via `BRIDGE_MANAGER`, include their tools in the report stage tool set. The model calls `create_document` / `insert_text` / `save_document` through the bridge to produce formatted output.

**Fallback path:** If connectors are not installed, use `python-docx` and `openpyxl` directly. Provide local wrapper tools (`create_word_report`, `create_excel_summary`) that produce files in `data/reports/`.

Detection at pipeline startup:
```python
bridge_tools = BRIDGE_MANAGER.list_remote_tools() if BRIDGE_MANAGER.is_running() else []
has_word = any(t["name"].startswith("create_document") or "Word" in t.get("description", "") for t in bridge_tools)
has_excel = any("xlsx" in t["name"].lower() or "Excel" in t.get("description", "") for t in bridge_tools)
```

### Error Handling

| Failure | Response |
|---------|----------|
| API key missing/invalid | Fail stage immediately with clear message |
| Model returns error (rate limit, overloaded) | Retry with exponential backoff, max 3 attempts, then fail stage |
| Budget exceeded | Graceful stop, mark stage `completed_partial`, log what finished |
| Tool call fails | Feed error back to model as tool result, let it retry (max 2 per tool) |
| Model hallucinates tool name | Return "tool not found" as result, model self-corrects |

### Observability

Every model call logs to `mcp_runtime_audit.jsonl`:
```json
{
  "ts": "2026-03-06T14:30:00Z",
  "type": "ai_inference",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "stage": "ai_analysis",
  "assessment_id": 42,
  "input_tokens": 3200,
  "output_tokens": 850,
  "tool_calls": 0,
  "duration_ms": 2100,
  "cost_usd": 0.018
}
```

### Cost Estimation (`services/ai_cost_table.py`)

Small dict constant with per-model pricing. Not stored in DB (changes too often).

```python
COST_PER_MILLION_TOKENS = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.0},
    # OpenAI models added in Phase 2
}
```

Falls back to zero cost if model not in table (logs warning).

## What Does NOT Change

- MCP REGISTRY, tool definitions, prompt specs — untouched
- Bridge architecture — untouched, we consume it
- AI Setup Wizard UI — already has all needed fields
- Pipeline stage order and background job pattern — same
- `_PIPELINE_STAGE_ORDER`, `_PIPELINE_STAGE_AUTONEXT` — same

## User Configuration (via existing wizard)

- **Provider:** `anthropic`
- **Model:** `claude-sonnet-4-20250514` (or pick from catalog refresh)
- **API Key:** `ANTHROPIC_API_KEY` env var
- **Budget limits:** Already in wizard (soft/hard per assessment, monthly)
- **Batch size:** Already in wizard (`ai_analysis.batch_size`)
- **Bridge connectors:** Already in wizard (enable Word/Excel if wanted)

## Phasing

| Phase | Scope |
|-------|-------|
| Phase 1 (this build) | Anthropic SDK client, structured + agentic modes, budget tracking, bridge tool routing |
| Phase 2 (next) | OpenAI SDK path for all other providers |
