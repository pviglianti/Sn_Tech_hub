# Claude Code Pipeline Dispatch — Design

**Date**: 2026-03-06
**Status**: Draft
**Depends on**: AI Inference Client Design (same date)

## Problem

The 10-stage pipeline prepares AI prompts at 6 stages (`ai_analysis`, `observations`,
`ai_refinement`, `grouping`, `recommendations`, `report`) but never calls a model.
Prompts are built via `_try_registered_prompt_text()` and stored as `prompt_context`
in `ScanResult.ai_observations` — then nothing happens.

Users want the pipeline to automatically invoke their AI subscription when
`mode == "local_subscription"` in `AIRuntimeProperties`.

## Decision

**Approach A: Single-Session CLI Dispatch** — one `claude -p` call per batch, one at a time.

Each batch is a single CLI invocation (`claude -p`). Batches run one at a time —
batch 1 finishes, then batch 2 starts. No parallelism in V1.

> **Terminology note**: The codebase already uses "sequential" to mean per-artifact
> analysis (vs depth-first traversal) in `server.py`. To avoid confusion, our
> execution strategies use: `single`, `concurrent`, `swarm`.

Rejected alternatives:
- **B: Persistent streaming session** — complex state management, hard error recovery
- **C: DB task queue + watcher** — over-engineered for the use case

## Execution Strategy Property

Users choose their execution strategy from the properties page:

- **`ai.runtime.execution_strategy`** — `single` (default) | `concurrent` | `swarm`
- **`ai.runtime.max_concurrent_sessions`** — integer 1-10 (default: 1)

These are already defined in `integration_properties.py` as `AIRuntimeProperties`
fields and exposed on the properties page under the "AI Runtime" section.

## Future: Concurrency & Swarm Modes (V2+)

The dispatcher is designed to support three execution strategies:

| Strategy | Sessions | Coordination | Use Case |
|----------|----------|-------------|----------|
| `single` (V1) | 1 | None | Default, simple, predictable |
| `concurrent` (V2) | 2-3 | Independent batches | Speed — N batches at once |
| `swarm` (V3) | 3-5 | Roles + shared context | Complex — analyzer, reviewer, architect |

**How the architecture supports this:**
- `dispatch_stage()` accepts a `strategy` parameter (default: `single`)
- `concurrent` wraps batch dispatch in `concurrent.futures.ThreadPoolExecutor`
- `swarm` uses Claude Code's `--input-format stream-json` for a coordinator
  session that spawns sub-agents with different system prompts and tool sets
- All strategies share the same `DispatchResult` and budget tracking
- `ai_runtime.max_concurrent_sessions` (default: 1) controls parallelism
- Swarm role definitions stored in `services/ai_swarm_roles.py` (future file)

**Not built now**, but the dispatcher interface is shaped so these strategies
slot in without changing the pipeline integration point in `server.py`.

## Scope Gate (ai_analysis stage)

The `ai_analysis` stage is the first AI-driven stage after scans and engines.
Before doing deep analysis, the AI's **first action** for each artifact must be
a quick scope determination: "Is this artifact in scope for detailed analysis?"

### Why a scope gate?

Many customized artifacts are trivial modifications (e.g., a field label change,
an OOTB script with a minor tweak) that don't need full analysis. Skipping them
early saves time and budget.

### How it works

The dispatcher sends artifacts through a two-phase flow within the same CLI call:

```
Phase 1 — Scope Triage (fast, per-artifact):
  For each artifact:
    1. Read basic metadata via get_result_detail()
    2. Decide: in_scope / adjacent / out_of_scope / needs_review
    3. If out_of_scope → set is_out_of_scope=true with brief observation, skip
    4. If adjacent → set is_adjacent=true with reason, lighter analysis
    5. If needs_review → flag for human review, skip deep analysis
    6. If in_scope → proceed to Phase 2
    7. Set review_status to review_in_progress (all artifacts)

Phase 2 — Deep Analysis (only for in-scope artifacts):
  For each in-scope artifact:
    1. Full contextual analysis
    2. Suggest disposition in observations text (do NOT set disposition field)
    3. Set severity, category, findings via update_scan_result()
    4. Disposition is confirmed by a human after all analysis is complete
```

### Scope categories

| Scope | Meaning | Example |
|-------|---------|---------|
| `in_scope` | Directly customized for the app being assessed | Custom business rule on Incident |
| `adjacent` | Related to the app but not a direct customization — references assessed tables/data, creates/updates assessed records, etc. | Business rule on Change that queries Incident fields |
| `out_of_scope` | No relation to the assessed app or trivial OOTB modification | Label change on an unrelated table |
| `needs_review` | Unclear — flag for human triage | Complex cross-table logic |

### Scope decisions evolve across iterations

Scope is a **preliminary** decision, not final. As later pipeline stages uncover
more context (relationships, feature groupings, usage data), scope may change:

- An artifact initially marked `out_of_scope` may be reclassified to `adjacent`
  when relationship tracing reveals it references assessed tables
- An `adjacent` artifact may become `in_scope` when feature grouping shows it's
  part of a cohesive custom feature
- These re-classifications happen in the `ai_refinement` and `grouping` stages

All artifacts should be marked `review_in_progress` until the final iteration
(report stage) when grouping is complete and findings are finalized.

### Scope decision in the data model

The scope decision is recorded in `ai_observations` JSON:
```json
{
  "scope_decision": "in_scope" | "adjacent" | "out_of_scope" | "needs_review",
  "scope_reason": "Brief explanation",
  "scope_triage_only": true  // set when out_of_scope, no deep analysis done
}
```

Additionally, `ScanResult.review_status` uses `review_in_progress` throughout
the pipeline until the final report stage, when it transitions to `reviewed`.

The `out_of_scope` and `adjacent` flags should also be exposed as checkboxes
in the UI so humans can manually override AI scope decisions.

This is embedded in the prompt template, not a separate stage — it's the first
instruction block in the `artifact_analyzer` prompt.

### Disposition rules

Disposition (`remove`, `keep_as_is`, `keep_and_refactor`) is **only set after
human confirmation**. The AI pipeline:

- **Suggests** a disposition in observations/recommendation text
- May use `needs_analysis` as a placeholder disposition if needed
- Does **NOT** write a final disposition value — that's the human reviewer's job
- The reviewer confirms or overrides the AI suggestion through the UI

### Out-of-scope filtering in deliverables

Artifacts marked `is_out_of_scope` are **excluded** from:

- Feature grouping (not added to any Feature group)
- Final deliverable exports (xlsx and docx)
- Customization counts in the report landscape section
- Recommendation lists

Adjacent artifacts (`is_adjacent`) are **included** but flagged — they provide
context for the assessed app without being direct customizations.

## Architecture

In V1 (`single` strategy), batches run one at a time. Each `claude -p` call
is a one-shot CLI invocation: starts, does its work, exits, then the next begins.

```
Pipeline stage fires (background thread)
  │
  ├─ mode == "disabled" → skip AI, run data-only logic (current behavior)
  ├─ mode == "api_key"  → call AIClient (separate design doc)
  └─ mode == "local_subscription" → ClaudeCodeDispatcher
        │
        ├─ Build prompt via _try_registered_prompt_text()
        ├─ Split artifacts into batches (from batch_size property)
        │
        ├─ Batch 1:
        │     claude -p <prompt> --mcp-config ... --output-format json
        │     → Claude calls MCP tools, writes results to DB
        │     → Pipeline verifies, updates progress
        │     → CLI exits
        │
        ├─ Batch 2:  (starts only after batch 1 finishes)
        │     claude -p <prompt> --mcp-config ... --output-format json
        │     → same flow
        │
        ├─ ... Batch N
        │
        └─ All batches done → autonext to next stage
```

## New File: `services/claude_code_dispatcher.py`

### ClaudeCodeDispatcher class

```python
@dataclass
class DispatchResult:
    success: bool
    batch_index: int
    total_batches: int
    artifacts_processed: int
    claude_output: dict | None   # parsed JSON from --output-format json
    error: str | None
    duration_seconds: float
    budget_used_usd: float | None

class ClaudeCodeDispatcher:
    """Dispatches AI work to Claude Code CLI for local_subscription mode."""

    def __init__(
        self,
        mcp_config_path: str,        # path to .mcp.json
        model: str = "opus",          # from AIRuntimeProperties.model
        per_batch_budget_usd: float = 5.0,
        stage_timeout_seconds: int = 300,
    ): ...

    def dispatch_batch(
        self,
        prompt: str,
        *,
        stage: str,
        assessment_id: int,
        batch_index: int,
        total_batches: int,
        allowed_tools: list[str] | None = None,
    ) -> DispatchResult:
        """Run one batch through Claude Code CLI."""

    def dispatch_stage(
        self,
        prompt_builder: Callable[[list[int]], str],
        artifact_ids: list[int],
        *,
        stage: str,
        assessment_id: int,
        batch_size: int,
        strategy: str = "single",       # V1: "single" only; V2+: "concurrent", "swarm"
        max_concurrent: int = 1,       # V2+: used when strategy != "single"
        on_batch_complete: Callable[[DispatchResult], None] | None = None,
    ) -> list[DispatchResult]:
        """Run a full stage in batches. Calls prompt_builder per batch.

        V1: strategy="single" — one batch at a time.
        V2+: strategy="concurrent" — up to max_concurrent batches via ThreadPoolExecutor.
        V3+: strategy="swarm" — coordinated multi-role sessions.
        """
```

### CLI Invocation Detail

```python
def _build_command(self, prompt: str, allowed_tools: list[str] | None) -> list[str]:
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", self.model,
        "--max-budget-usd", str(self.per_batch_budget_usd),
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
        "--mcp-config", self.mcp_config_path,
    ]
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    return cmd
```

Prompt is piped via stdin: `subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=...)`

## Stage-to-Prompt Mapping

Each AI stage already has a registered prompt. The dispatcher just needs to know which
prompt to use and what artifact IDs to include:

| Stage | Registered Prompt | Tool Access | Batch Default |
|-------|-------------------|-------------|---------------|
| `ai_analysis` | `artifact_analyzer` | `get_customizations`, `get_result_detail`, `update_scan_result` | 50 |
| `observations` | `observation_artifact_reviewer` | `generate_observations`, `get_result_detail` | 10 |
| `ai_refinement` | `relationship_tracer` | `feature_detail`, `get_result_detail`, `feature_grouping_status` | 20 |
| `grouping` | `feature_reasoning_orchestrator` | `create_feature`, `add_result_to_feature`, `feature_grouping_status` | all |
| `recommendations` | `technical_architect` | `feature_recommendation`, `feature_detail` | 20 |
| `report` | `report_writer` | `assessment_results`, `feature_detail`, `get_customizations` | all |

## Per-Stage Allowed Tools

Instead of giving Claude access to all 34 tools, each stage restricts to relevant tools.
This is safer and cheaper (less tool schema in context).

```python
STAGE_TOOL_SETS: dict[str, list[str]] = {
    "ai_analysis": [
        "mcp__tech-assessment-hub__get_customizations",
        "mcp__tech-assessment-hub__get_result_detail",
        "mcp__tech-assessment-hub__update_scan_result",
    ],
    "observations": [
        "mcp__tech-assessment-hub__generate_observations",
        "mcp__tech-assessment-hub__get_result_detail",
        "mcp__tech-assessment-hub__get_customizations",
    ],
    # ... etc per stage
}
```

## Budget Control

Budget is enforced at three levels:

1. **Per-batch**: `--max-budget-usd` on the CLI (hard stop per subprocess)
2. **Per-stage**: Dispatcher tracks cumulative spend across batches, stops if over
3. **Per-assessment**: `_enforce_assessment_stage_budget()` already exists in pipeline

Formula for per-batch budget:
```
per_batch = min(
    runtime_props.assessment_soft_limit_usd / expected_batches,
    runtime_props.assessment_hard_limit_usd - assessment_spend_so_far
)
```

## Pipeline Integration Point

The change is surgical. In `_run_assessment_pipeline_stage()`, after the existing
`_try_registered_prompt_text()` call, add a dispatch step:

```python
# EXISTING: build prompt
if pipeline_prompt_props.use_registered_prompts:
    prompt_text, prompt_error = _try_registered_prompt_text(...)

# NEW: dispatch to Claude Code if local_subscription mode
runtime_props = load_ai_runtime_properties(session, instance_id=assessment.instance_id)
if runtime_props.mode == "local_subscription" and prompt_text:
    from .services.claude_code_dispatcher import ClaudeCodeDispatcher
    dispatcher = ClaudeCodeDispatcher(
        mcp_config_path=_resolve_mcp_config_path(),
        model=runtime_props.model,
        per_batch_budget_usd=_calc_per_batch_budget(runtime_props, ...),
    )
    result = dispatcher.dispatch_batch(
        prompt_text,
        stage=stage,
        assessment_id=assessment_id,
        batch_index=batch_idx,
        total_batches=total_batches,
        allowed_tools=STAGE_TOOL_SETS.get(stage),
    )
    analysis_result["dispatch_result"] = asdict(result)

# EXISTING: store in DB
sr.ai_observations = json.dumps(analysis_result, sort_keys=True)
```

## Prompt Construction

Each batch prompt follows this template:

```
You are a ServiceNow technical assessment AI. You have access to the
tech-assessment-hub MCP tools to read and write assessment data.

## Task
{stage_specific_instructions}

## Assessment
- Assessment ID: {assessment_id}
- Stage: {stage}
- Batch: {batch_index + 1} of {total_batches}

## Artifacts to Process
{artifact_ids_or_names}

## Instructions
1. SCOPE TRIAGE FIRST: For each artifact, read its basic details and decide:
   - "in_scope" → proceed to full analysis
   - "adjacent" → mark is_adjacent=true, lighter analysis
   - "out_of_scope" → mark is_out_of_scope=true with brief observation, skip
   - "needs_review" → flag for human review, skip deep analysis
2. Set review_status to "review_in_progress" for all artifacts (never "reviewed")
3. For in-scope artifacts, analyze according to the stage requirements
4. SUGGEST dispositions in observation text only — do NOT set the disposition field.
   Disposition is confirmed by a human after all analysis is complete.
5. Write your findings back using the update tools
6. Be thorough but efficient — stay within your tool set

## Output
After processing all artifacts, summarize what you did as a JSON object:
{{"processed": <count>, "findings": [<brief summary per artifact>]}}
```

The registered prompt text from `_try_registered_prompt_text()` replaces
`{stage_specific_instructions}` — it already contains rich context from the
prompt handler (artifact details, relationships, etc.).

## Error Handling

| Failure | Recovery |
|---------|----------|
| Subprocess timeout | Mark batch as failed, continue to next batch, log warning |
| Claude returns error JSON | Parse error, store in `dispatch_result`, continue |
| Budget exceeded mid-stage | Stop remaining batches, mark stage as partial, log spend |
| CLI not found | Raise `RuntimeError` with install instructions |
| MCP server not running | subprocess error includes "Server unreachable", surface to user |
| Partial batch (some artifacts fail) | Claude writes what it can; pipeline verifies DB state |

Failed batches are retried once. If retry fails, stage completes with partial results
and the user can re-run the stage.

## Observability

Each dispatch writes to the existing telemetry system:

```python
telemetry_details["ai_dispatch"] = {
    "mode": "local_subscription",
    "model": runtime_props.model,
    "stage": stage,
    "batches_total": total_batches,
    "batches_succeeded": succeeded_count,
    "batches_failed": failed_count,
    "total_duration_s": total_duration,
    "budget_used_usd": total_spend,
}
```

Progress updates flow through existing `_set_assessment_pipeline_job_state()` so
the UI progress bar tracks batch completion.

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `services/claude_code_dispatcher.py` | **NEW** | `ClaudeCodeDispatcher` class |
| `services/ai_stage_tool_sets.py` | **NEW** | `STAGE_TOOL_SETS` dict + prompt templates |
| `src/server.py` | **MODIFY** | Add dispatch calls in AI stages |
| `.mcp.json` | **EXISTS** | Already created for Claude Code connectivity |

## Testing Strategy

1. **Unit tests** for `ClaudeCodeDispatcher` — mock `subprocess.run`, verify command construction
2. **Integration test** — mock Claude CLI output, verify DB state after dispatch
3. **Manual test** — run a real assessment with Claude Code against localhost:8080

## Sequence: What Happens When User Clicks "Run Stage"

```
1. User clicks "Run ai_analysis" in UI
2. POST /api/assessments/{id}/pipeline/run-stage {stage: "ai_analysis"}
3. Server spawns background thread
4. Thread loads properties:
   - AIRuntimeProperties.mode = "local_subscription"
   - AIRuntimeProperties.execution_strategy = "single"
   - AIAnalysisProperties.batch_size = 50
5. Thread queries customized artifacts (e.g., 200 total)
6. Thread creates ClaudeCodeDispatcher
7. For batch 1 (artifacts 1-50):
   a. Build prompt via _try_registered_prompt_text("artifact_analyzer", ...)
   b. Prepend batch header (assessment_id, batch info, scope triage instructions)
   c. subprocess.run(["claude", "-p", ...], input=prompt, timeout=300)
   d. Claude Code starts, connects to MCP server via stdio bridge
   e. For each artifact: scope triage first → if out_of_scope, quick disposition + skip
   f. For in-scope artifacts: deep analysis → update_scan_result(...)
   g. Claude returns JSON summary with scope decisions + analysis findings
   h. Pipeline parses result, updates progress (25%)
8. Repeat for batches 2-4
9. All batches done → complete_phase_progress()
10. Autonext → observations stage
```
