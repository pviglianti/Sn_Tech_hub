# Plan: MCP Tools + Classification Quality (Tech Assessment Focus)

> Blueprint priority #4. Authored by Claude 2026-02-15. Approved by PV.
> Implementation can be split between Claude + Codex. Phases 4-5 are independent of 1-3.

## Context

**Why**: The blueprint priority sequence is: ~~1. Stabilize~~ → ~~2. Tests~~ → ~~3. Decompose~~ → **4. MCP tools + classification quality** → 5. AI reasoning pipeline. We're at step 4.

**Problem**: The MCP server has solid tool infrastructure (JSON-RPC, hybrid router, 15+ tools, bridge, audit) but is missing two critical MCP primitives — **Prompts** and **Resources** — that allow the AI to load domain methodology and reference documents. Without these, any AI model connected via MCP has no way to learn the assessment methodology, classification rules, or CSDM standards. The user's core question: "how does the AI know what to abide by?" — the answer is Prompts (behavioral instructions) + Resources (reference docs).

Additionally, the classification logic in `scan_executor.py` needs an audit against the assessment guide's decision tree, and the existing assessment tools need gap-filling for write-back capabilities.

**Scope**: Technical Assessment only (per PV decision). CSDM deferred until reference docs are gathered.

---

## What Exists Today

### MCP Protocol (complete for tools)
- `src/mcp/protocol/jsonrpc.py` — handles `initialize`, `tools/list`, `tools/call`
- `src/mcp/registry.py` — `ToolSpec` + `ToolRegistry` + lazy initialization
- `src/mcp/runtime/router.py` — hybrid Python/TS routing with fallback
- NO support for `prompts/list`, `prompts/get`, `resources/list`, `resources/read`

### Registered Tools (15+)
| Level | Tool | Read/Write | What it does |
|-------|------|------------|--------------|
| 0 | `sn_test_connection` | read | Test SN instance connectivity |
| 0 | `sn_inventory_summary` | read | Scan inventory counts by scope |
| 0 | `sqlite_query` | read | Read-only SQL against local DB |
| 0 | `scaffold_workspace` / `read_file` / `update_file` / `list_files` | write | Workspace file management |
| 1 | `get_instance_summary` | read | Instance overview |
| 1 | `get_assessment_results` | read | Filtered results (token-efficient, no raw_data) |
| 1 | `get_result_detail` | read | Full single result + version history |
| 1 | `trigger_data_pull` | write | Start preflight data pull |
| 1 | `run_assessment` | write | Create assessment + launch scans |
| 1 | `save_fact` / `get_facts` / `delete_facts` | write | Key-value scratchpad |
| 1 | `query_live` | read | Live SN table query |
| 2 | `get_customization_summary` | read | Aggregated stats (~200 tokens vs 50K) |
| 2 | `group_by_feature` | write | Cluster results into Features |

### Classification Logic
- `src/services/scan_executor.py:457` — `_classify_origin()` with 5-step cascade
- Missing: full alignment with assessment guide decision tree (see Phase 4)

### Context System (stubs)
- `src/mcp/context/packs.py` — Wave 4 stub (NotImplementedError)
- `src/mcp/context/budgets.py` — Token budgeting (likely stub)
- `src/mcp/context/project_index.py` — Project file indexing (likely stub)

---

## How MCP Prompts + Resources Work (Conceptual)

MCP defines three primitives that enable an AI to work with domain expertise:

### Tools (already built)
Functions the AI calls — read data, write findings, trigger operations. We have 15+ of these.

### Prompts (to build)
Pre-built instruction templates the AI loads before reasoning. This is how you make the AI **"abide by"** a methodology. Think of them as switchable expert modes:
- `tech_assessment_expert` prompt → loads assessment methodology, classification rules, disposition framework, tool usage guidance
- `csdm_analyst` prompt (future) → loads CSDM 5 rules, service model structure
- The AI client calls `prompts/get` and receives structured instructions that shape its behavior.

### Resources (to build)
URI-addressable reference documents the AI reads on-demand. This is how you make the AI **"aware of"** domain documentation without stuffing everything into the system prompt:
- `assessment://guide/classification-rules` → Origin type decision tree
- `assessment://guide/grouping-signals` → 8 signal categories, clustering algorithm
- The AI calls `resources/read` when it needs deeper reference material.

**Key insight**: The MCP server becomes the **domain knowledge carrier**. The AI model brings general reasoning; the MCP server brings the rules, the data, and the guardrails. The deterministic engines (counts, patterns, grouping signals) run inside tool handlers — the AI calls a tool and gets pre-staged results, then applies judgment using the prompt/resource context.

---

## Implementation Plan

### Phase 1: MCP Protocol — Add Prompts + Resources Support
**Goal**: Extend the JSON-RPC handler to support `prompts/list`, `prompts/get`, `resources/list`, `resources/read`. This is the foundation that enables everything else.

**Owner**: Claude or Codex (mechanical protocol work)

**Files to create/modify**:
- `src/mcp/registry.py` — Add `PromptSpec`, `ResourceSpec` dataclasses and `PromptRegistry`, `ResourceRegistry` classes (same pattern as `ToolSpec`/`ToolRegistry`)
- `src/mcp/protocol/jsonrpc.py` — Add handlers for `prompts/list`, `prompts/get`, `resources/list`, `resources/read`. Update `_handle_initialize` to advertise `prompts` and `resources` capabilities.
- `src/mcp/runtime/router.py` — Extend `MCP_RUNTIME_ROUTER` to include prompt/resource listing (or keep them separate from tool routing since prompts/resources don't need engine selection)

**PromptSpec shape** (mirrors MCP spec):
```python
@dataclass
class PromptSpec:
    name: str              # e.g., "tech_assessment_expert"
    description: str       # What this prompt teaches the AI
    arguments: List[Dict]  # Optional parameterization (e.g., assessment_id)
    handler: Callable      # Returns {"messages": [{"role": "user", "content": {...}}]}
```

**ResourceSpec shape**:
```python
@dataclass
class ResourceSpec:
    uri: str               # e.g., "assessment://guide/classification"
    name: str              # Display name
    description: str
    mime_type: str          # "text/markdown" typically
    handler: Callable      # Returns content string
```

**Protocol responses** (per MCP spec):
- `prompts/list` → `{"prompts": [{"name", "description", "arguments"}]}`
- `prompts/get` → `{"description", "messages": [{"role", "content": {"type": "text", "text": ...}}]}`
- `resources/list` → `{"resources": [{"uri", "name", "description", "mimeType"}]}`
- `resources/read` → `{"contents": [{"uri", "mimeType", "text": ...}]}`

---

### Phase 2: Assessment Methodology Prompts
**Goal**: Create prompts that make the AI "know how to do a technical assessment." When a customer connects their AI to our MCP server, calling `prompts/get` with `tech_assessment_expert` gives them the full methodology.

**Owner**: Claude (domain knowledge authoring — requires understanding the methodology docs)

**Files to create**:
- `src/mcp/prompts/__init__.py`
- `src/mcp/prompts/tech_assessment.py` — Main assessment methodology prompt

**Prompt: `tech_assessment_expert`**
Loads the AI with:
- Assessment methodology (multi-pass iterative approach from `ai_reasoning_pipeline_domain_knowledge.md`)
- Classification rules (origin type decision tree from assessment guide)
- Disposition framework (keep / refactor / replace-OOTB / remove — with criteria)
- Grouping signals overview (8 signal categories, confidence scoring)
- Tool usage guidance (which tools to call in what order: summary → results → detail → write findings)
- Token efficiency rules (use summary first, drill down only when needed, use engines for deterministic work)

**Prompt: `tech_assessment_reviewer`** (lighter)
For reviewing/refining existing findings — loads disposition criteria and review workflow only.

**Key design decision**: Prompts should be self-contained markdown text, not references to external files. The content is derived from our domain knowledge docs but formatted for AI consumption (concise, actionable, structured as instructions).

---

### Phase 3: Assessment Reference Resources
**Goal**: Expose reference documents as on-demand readable content. The AI pulls these when it needs deep reference material beyond what the prompt provides.

**Owner**: Claude or Codex (mechanical + domain knowledge)

**Files to create**:
- `src/mcp/resources/__init__.py`
- `src/mcp/resources/assessment_docs.py` — Resource handlers for assessment documents

**Resources**:
| URI | Source | Purpose |
|-----|--------|---------|
| `assessment://guide/classification-rules` | Assessment guide v3 (condensed) | Origin type decision tree, version history method, baseline comparison |
| `assessment://guide/grouping-signals` | Grouping signals doc (condensed) | 8 signal categories, confidence weights, clustering algorithm |
| `assessment://guide/finding-patterns` | AI reasoning pipeline doc (section) | Common finding patterns (OOTB alternative, platform maturity gap, etc.) |
| `assessment://guide/app-file-types` | AI reasoning pipeline doc (section) | Key app file types and what to look for in each |
| `assessment://schema/scan-result-fields` | Generated from ScanResult model | Field names, types, valid enum values — so AI knows what data is available |
| `assessment://schema/feature-fields` | Generated from Feature model | Feature model fields for write-back |

**Resource content strategy**: Resources return markdown text condensed from our domain knowledge docs. Schema resources are auto-generated from the SQLModel definitions to stay in sync.

---

### Phase 4: Classification Quality Audit & Fixes
**Goal**: Ensure `_classify_origin()` matches the assessment guide decision tree exactly.

**Owner**: Claude (requires understanding the assessment guide deeply)

**File to modify**: `src/services/scan_executor.py`

**Assessment Guide Decision Tree** (target state):
```
IF any OOB version exists (source_table in [sys_upgrade_history, sys_store_app]):
  IF any customer versions exist OR baseline changed now:
    → modified_ootb
  ELSE:
    → ootb_untouched
ELSE:
  IF any customer versions exist OR baseline changed now:
    → net_new_customer
  ELSE IF no version history:
    → unknown_no_history
```

**Known gaps to audit**:

1. **Current-version-first bias**: Current code checks if the "current" version record is Store/Upgrade and immediately returns `ootb_untouched` (step 1). The assessment guide says to check if ANY OOB version exists in full history, AND then check if any customer versions also exist (→ modified_ootb). This means a reverted-to-OOTB record that has customer history would be misclassified as `ootb_untouched` instead of `modified_ootb`.

2. **metadata_customization vs. customer versions**: Step 2 uses `has_metadata_customization` as the signal for modified_ootb. The guide uses "any customer versions exist" as an alternative signal. These overlap but aren't identical — a record could have customer version history without a metadata_customization entry.

3. **`changed_baseline_now` not used in classification**: The `changed_baseline_now` flag (SncAppFiles.hasCustomerUpdate) is stored on ScanResult but not used as an input to `_classify_origin()`. The guide says it should be a signal for modified_ootb / net_new_customer.

4. **V3 user existence check**: Assessment guide v3 adds `created_by_in_user_table` check for unknown records. Not implemented.

**Approach**: Audit each step, write failing tests for the gaps, then fix the logic. Classification changes need careful testing since they affect every scan result.

---

### Phase 5: Assessment Tools — Fill Gaps
**Goal**: Add missing tools the AI needs for the full assessment workflow.

**Owner**: Claude or Codex (follows existing ToolSpec pattern)

**Tools to add**:

1. **`update_scan_result`** (write) — AI writes observations, disposition, recommendation, severity, category, finding_title/description back to a ScanResult. This is how the AI records its analysis.
   - File: `src/mcp/tools/core/update_result.py`
   - Input: `result_id`, `disposition`, `severity`, `category`, `observations`, `recommendation`, `finding_title`, `finding_description`
   - Pattern: Follow `src/mcp/tools/core/assessment.py` (existing write tool)

2. **`update_feature`** (write) — AI writes feature-level analysis: description, disposition, recommendation, ai_summary.
   - File: `src/mcp/tools/core/update_feature.py`
   - Input: `feature_id`, `description`, `disposition`, `recommendation`, `ai_summary`

3. **`get_update_set_contents`** (read) — AI sees what's in an update set (all customer_update_xml records). Critical for grouping analysis.
   - File: `src/mcp/tools/core/update_set_contents.py`
   - Input: `update_set_id` or `update_set_name` + `instance_id`
   - Pattern: Follow `src/mcp/tools/core/result_detail.py` (existing read tool)

4. **`get_feature_detail`** (read) — AI reads a feature group with its linked scan results.
   - File: `src/mcp/tools/core/feature_detail.py`
   - Input: `feature_id`

5. **`save_general_recommendation`** (write) — AI writes instance/assessment-scoped general technical recommendations (the third output type from the domain methodology doc).
   - Requires a new model: `GeneralRecommendation` (assessment_id, title, description, category, severity)
   - File: `src/mcp/tools/core/general_recommendation.py`
   - Model file: Add to `src/models.py`

---

## Execution Sequence

| Step | Phase | Est. Complexity | Dependencies | Candidate Owner |
|------|-------|-----------------|--------------|-----------------|
| 1 | Phase 1: Protocol support | Medium | None | Codex or Claude |
| 2 | Phase 2: Assessment prompts | Medium | Phase 1 | Claude |
| 3 | Phase 3: Assessment resources | Low-Medium | Phase 1 | Codex or Claude |
| 4 | Phase 4: Classification audit | Medium | None (parallel) | Claude |
| 5 | Phase 5: Write-back tools | Medium | None (parallel) | Codex or Claude |

Phases 1-3 are sequential (protocol first, then content). Phases 4 and 5 are independent and can run in parallel with 1-3.

---

## Verification

1. **Protocol**: POST to `/mcp` with `{"method": "prompts/list"}` and `{"method": "resources/list"}` — should return catalogs
2. **Prompts**: `prompts/get` with `name: "tech_assessment_expert"` — should return structured methodology text
3. **Resources**: `resources/read` with `uri: "assessment://guide/classification-rules"` — should return classification guide markdown
4. **Classification**: New tests in `tests/test_classification.py` covering all decision tree paths including edge cases (reverted OOTB, missing history, etc.)
5. **Tools**: POST to `/mcp` with `tools/call` for `update_scan_result` — should persist disposition/observations and return success
6. **MCP Console**: `tools/list` should show new tools, capabilities should include prompts + resources
7. **Full test suite**: `pytest tests/ -q` — must still pass (87+ tests)

---

## Key Files Reference

| File | Role |
|------|------|
| `src/mcp/protocol/jsonrpc.py` | JSON-RPC handler — add prompts/resources methods |
| `src/mcp/registry.py` | Tool registry — extend with PromptRegistry + ResourceRegistry |
| `src/mcp/runtime/router.py` | Hybrid router — may need prompt/resource awareness |
| `src/mcp/runtime/capabilities.py` | Capability snapshot — add prompt/resource counts |
| `src/services/scan_executor.py:457` | `_classify_origin()` — audit + fix |
| `src/mcp/tools/core/` | Existing tools — add new write-back tools here |
| **Domain docs (read-only source):** | |
| `servicenow.../02_working/01_notes/ai_reasoning_pipeline_domain_knowledge.md` | Assessment methodology |
| `servicenow.../02_working/01_notes/grouping_signals.md` | Grouping signals |
| `servicenow.../01_source_data/01_reference_docs/assessment_guide_and_script_v3_pv.md` | Classification rules |

---

## What Comes After This Plan

Once this plan is complete, the platform will have:
- MCP Prompts + Resources protocol support (reusable for CSDM later)
- AI-consumable assessment methodology and reference materials
- Correct classification logic matching the assessment guide
- Write-back tools so AI can persist its analysis

**Next priority (blueprint #5)**: Build the AI reasoning pipeline — deterministic engines for pre-staging (temporal clustering, update set analysis, version history chains, reference graphs), multi-pass AI workflow, and the full feature grouping + tech debt analysis + disposition engine.
