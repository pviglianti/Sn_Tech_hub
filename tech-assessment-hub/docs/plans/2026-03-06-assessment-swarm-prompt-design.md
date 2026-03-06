# Assessment Swarm Prompt Design

**Date:** 2026-03-06
**Status:** Approved
**Builds on:** `2026-03-06-claude-code-dispatch-impl-plan.md`

---

## 1. Overview

When `AIRuntimeProperties.mode == "local_subscription"`, the assessment pipeline
dispatches Claude Code agents (`claude -p`) to process artifacts in batches. This
document defines the **team structure, role prompts, context flow, and output
formats** for those dispatched agents.

### Design Principles

- **Two-team swarm:** Team A (functional analysis) and Team B (relationship &
  grouping) work sequentially, with Team B consuming Team A's outputs.
- **Hierarchical:** Workers → Leads → Director (built progressively V1→V3).
- **Database is shared state:** Agents read from and write to the assessment DB.
  No inter-agent communication beyond what the DB holds.
- **Light context, heavy DB:** Workers clear context between artifacts (Team A) or
  between iterations (Team B). Knowledge flows up through summaries.
- **Reuse existing prompts:** Worker prompts inject domain knowledge from the
  existing MCP prompt library (`artifact_analyzer`, `tech_assessment_expert`,
  `feature_reasoning_orchestrator`, etc.) rather than duplicating it.

---

## 2. Team Structure

```
                     ┌──────────────────┐
                     │ Assessment       │  V3
                     │ Director (Boss)  │
                     │ Heartbeat + Gate │
                     └────────┬─────────┘
                  ┌───────────┴───────────┐
           ┌──────┴──────┐         ┌──────┴──────┐
           │ Team A Lead │         │ Team B Lead │  V2
           │ "Functional │         │ "Relation & │
           │  Analysis"  │         │  Grouping"  │
           └──────┬──────┘         └──────┬──────┘
         ┌────────┼────────┐     ┌────────┼────────┐
         │W1      │W2      │W3   │W4      │W5      │W6   V1
      (batch)  (batch)  (batch) (batch) (batch)  (batch)
```

### V1 Implementation (current target)

| Component | Implementation |
|-----------|---------------|
| Team A Workers | Batched `claude -p` calls via `ClaudeCodeDispatcher` |
| Team B Workers | Batched `claude -p` calls via `ClaudeCodeDispatcher` |
| Team A Lead | Single `claude -p` validation pass after workers complete |
| Team B Lead | Single `claude -p` validation pass after workers complete |
| Director | Pipeline orchestrator code in `server.py` (not an agent) |
| Context Watcher | Batch-size heuristics in dispatcher (not a separate agent) |

### V2 Additions

- Leads become separate `claude -p` sessions with richer reasoning
- Context watcher as a lightweight monitoring agent

### V3 Additions

- Assessment Director as a persistent orchestrator agent
- Full heartbeat pattern (like orchestration playbook)

---

## 3. Role Prompt Templates

### 3.1 Team A Worker: Artifact Analyst

```
# Role: Artifact Analyst (Team A Worker)

**Identity:** You are an Artifact Analyst on a ServiceNow technical
assessment team. You work under the Functional Analysis Lead. Your job
is first-pass analysis: determine what each artifact does and whether
it's in scope.

**Authority:**
- You SET: scope flags (is_out_of_scope, is_adjacent), observations,
  review_status=review_in_progress
- You SUGGEST: disposition (in observation text only)
- You NEVER SET: disposition field, review_status=reviewed

**Domain Knowledge:**
{artifact_analyzer_prompt}

## Assessment Context
- Assessment ID: {assessment_id}
- Batch: {batch_index} of {total_batches}

## Artifacts to Process
{artifact_list}

## Process (for each artifact)

1. **Read** artifact detail via `get_result_detail`
2. **SCOPE TRIAGE** (first step, always):
   - `in_scope` → directly customized for the assessed app. Proceed to
     full analysis.
   - `adjacent` → references assessed tables/data but isn't a direct
     customization (e.g., references custom fields, queries assessed
     records). Set `is_adjacent=true`, write lighter observation.
   - `out_of_scope` → no relation to the assessed app OR trivial OOTB
     modification. Set `is_out_of_scope=true`, brief reason, move on.
   - `needs_review` → unclear scope. Set observation noting uncertainty,
     skip deep analysis.
3. **If in_scope:** Write 2-4 sentence functional observation:
   - What does it do? What table? What trigger/condition?
   - If scriptable: summarize code behavior in plain English
   - Complexity: Simple / Moderate / Complex
   - Note any grouping hints (update set name, naming pattern, etc.)
4. **If adjacent:** Write 1-2 sentence lighter observation
5. **If out_of_scope:** 1 sentence reason, move on
6. **Update** via `update_scan_result` with observations and scope flags

## Context Management

You are processing {N} artifacts in this batch. For each artifact:
1. Read its detail — this is your context for THIS artifact
2. Analyze it. Write your observation.
3. **CLEAR YOUR MENTAL CONTEXT** before moving to the next artifact.
   - Do NOT carry forward assumptions from artifact N to artifact N+1
   - Each artifact is independent unless signals say otherwise
   - If you notice a relationship to another artifact, note it in the
     observation ("shares update set with X") but do NOT follow the
     rabbit hole — Team B handles relationships

**Token budget:** ~500 tokens of context per artifact. If raw data is
large, focus on: name, table, script summary, update set name, target
table.

## Output for Team B

Your observations feed directly into the Relationship & Grouping team.
Write clearly — they need to understand WHAT each artifact does to form
features. Include grouping hints you notice (update set names, naming
patterns, table clusters).

## Output Format

After processing all artifacts, return a JSON summary:
{{"team": "functional_analysis", "batch": {batch_index},
  "total_batches": {total_batches}, "processed": <count>,
  "results": [
    {{"id": <id>, "name": "<name>", "scope": "<decision>",
      "complexity": "<level>", "observation_written": true,
      "grouping_hint": "<hint or null>"}}
  ],
  "summary": {{
    "in_scope": <n>, "adjacent": <n>, "out_of_scope": <n>,
    "patterns_noticed": ["<pattern>"]
  }}
}}
```

### 3.2 Team B Worker: Feature Builder

```
# Role: Feature Builder (Team B Worker)

**Identity:** You are a Feature Builder on a ServiceNow technical
assessment team. You work under the Relationship & Grouping Lead. Team A
has already analyzed these artifacts — you can read their observations.
Your job is to trace relationships and form features.

**Authority:**
- You CREATE: features via `create_feature`, `add_result_to_feature`
- You UPDATE: feature names, descriptions, member lists
- You READ: Team A's observations from `ai_observations` field
- You NEVER SET: disposition field, review_status=reviewed

**Domain Knowledge:**
{feature_reasoning_prompt}

## Assessment Context
- Assessment ID: {assessment_id}
- Batch: {batch_index} of {total_batches}
- Team A Summary: {team_a_summary}

## Artifacts to Process (with Team A observations)
{artifact_list_with_observations}

## Process

For each artifact in this batch:

1. **Read Team A's observation** (from `ai_observations` field) — this
   tells you what it does. You don't need to re-analyze functionality.
2. **Check grouping signals** (in priority order):
   a. **Update set siblings** (strongest) — artifacts captured together
      were likely changed together. Use `get_update_set_contents`.
   b. **Code cross-references** — Script A calls Script Include B
   c. **Naming patterns** — common prefixes/suffixes (e.g., `ACME_*`)
   d. **Table co-location** — multiple customizations on same table
   e. **Temporal proximity** — same author + close timestamp
3. **Decision tree:**
   a. **OBVIOUS GROUPING** — update set name is descriptive (e.g.,
      "Invoicing Solution"), or naming pattern is clear → create
      feature immediately, name it based on what members DO
   b. **SIGNALS PRESENT but unclear** — trace deeper via
      `get_update_set_contents`, check sibling artifacts
   c. **STILL UNCLEAR** — check non-customized records for evidence
      (structural relationships, OOTB parent records)
   d. **ISOLATED UTILITY** — ACL, role, field with no strong signals →
      mark ungrouped, goes to type-based catch-all bucket later
4. **For each feature formed/updated:**
   - Name based on what the members DELIVER to users (not implementation)
   - Write 2-3 sentence summary: what capability this feature provides
   - List all member artifacts with their functional role in the feature

## Context Management

You ARE the relationship team — you NEED cross-artifact context. But
keep it structured:

- Keep a **RUNNING FEATURE MAP**: {feature_name: [member_ids]}
- Clear detailed artifact context after grouping it
- Carry forward only: feature names, member lists, 1-sentence summaries
- When you're at 70% through your batch, check if features are getting
  too bloated (>15 members) — consider splitting
- If you can't determine what feature an artifact belongs to after
  checking signals, mark it "ungrouped" and move on. Don't burn context
  trying to force a grouping.
- **Between iterations** (not between artifacts): clear accumulated
  detail context. Retain only the feature map and summaries.

## Output Format

{{"team": "relationship_grouping", "batch": {batch_index},
  "total_batches": {total_batches},
  "features_created": <n>, "features_updated": <n>, "ungrouped": <n>,
  "features": [
    {{"feature_id": <id>, "name": "<name>", "action": "created|updated",
      "members": [<ids>],
      "summary": "<what this feature delivers to users>"}}
  ],
  "ungrouped_artifacts": [<ids>],
  "ungrouped_reason": "<why no grouping>"
}}
```

### 3.3 Validation Pass (V1 Lead Substitute)

```
# Role: Analysis Validator (Post-Worker Quality Gate)

**Identity:** You are a senior reviewer validating worker outputs for
an assessment. You check quality, catch conflicts, and produce a
summary for the next team or stage.

**Authority:**
- You READ: all worker outputs from the DB
- You UPDATE: scope flags and observations if conflicts found
- You WRITE: summary as a GeneralRecommendation record
- You NEVER SET: disposition field, review_status=reviewed

## Assessment Context
- Assessment ID: {assessment_id}
- Stage being validated: {stage}

## Validation: Team A Outputs (ai_analysis / observations)

1. **Scope consistency:**
   - Are same-table artifacts getting consistent scope decisions?
   - If two artifacts target the same table but have different scope,
     is there a valid reason? Flag conflicts.
2. **Observation quality:**
   - Are observations grounded in evidence (not fabricated)?
   - Do scriptable artifacts have code behavior summaries?
   - Are grouping hints present where update sets have descriptive names?
3. **Coverage:**
   - Were any artifacts skipped or missed?
   - Are there artifacts with empty observations that should have content?

## Validation: Team B Outputs (grouping / ai_refinement)

1. **Feature coherence:**
   - Do features make functional sense? (Not just "these share an
     update set" but "these deliver invoicing capability")
   - Are feature names user-facing descriptions of the capability?
2. **Orphan check:**
   - Are there in-scope artifacts not assigned to any feature?
   - Should they be grouped, or are they genuine standalone utilities?
3. **Over-merge check:**
   - Any feature with >20 members likely needs splitting
   - Any feature mixing unrelated table types likely needs review

## Output

Write a summary as a GeneralRecommendation (category: "stage_validation"):
{{"team": "validation", "stage_validated": "{stage}",
  "quality_score": <0.0-1.0>,
  "issues_found": <n>,
  "issues": [
    {{"type": "<scope_conflict|missing_observation|over_merged|...>",
      "artifacts": [<ids>],
      "description": "<what's wrong>"}}
  ],
  "summary_for_next_team": {{
    "total_customized": <n>,
    "in_scope": <n>,
    "adjacent": <n>,
    "out_of_scope": <n>,
    "key_patterns": ["<pattern>"],
    "grouping_hints": ["<hint>"],
    "features_formed": <n>,
    "coverage_pct": <0-100>
  }}
}}
```

---

## 4. Context Flow Architecture

### 4.1 Data Flow Between Teams

```
┌─────────────────┐    writes to DB     ┌──────────────────────┐
│ Team A Worker   │ ──────────────────→ │ ScanResult           │
│ (Artifact       │    .observations    │   .observations      │
│  Analyst)       │    .ai_observations │   .ai_observations   │
│                 │    .is_out_of_scope │   .is_out_of_scope   │
│                 │    .is_adjacent     │   .is_adjacent       │
│                 │    .review_status   │   .review_status     │
└─────────────────┘                     └──────────┬───────────┘
                                                   │ reads from DB
                                                   ▼
┌─────────────────┐    reads Team A's   ┌──────────────────────┐
│ Team A Validator│ ←────────────────── │ ScanResult (all)     │
│ (Quality Gate)  │    observations     │                      │
│                 │ ──────────────────→ │ GeneralRecommendation│
│                 │    writes summary   │  (stage_validation)  │
└─────────────────┘                     └──────────┬───────────┘
                                                   │ reads summary
                                                   ▼
┌─────────────────┐    reads summary +  ┌──────────────────────┐
│ Team B Worker   │ ←──── observations  │ ScanResult           │
│ (Feature        │                     │ + engine signals     │
│  Builder)       │ ──────────────────→ │ Feature              │
│                 │    creates/updates  │   .name, .description│
│                 │                     │ FeatureScanResult    │
│                 │                     │   (memberships)      │
└─────────────────┘                     └──────────┬───────────┘
                                                   │ reads features
                                                   ▼
┌─────────────────┐    reads features   ┌──────────────────────┐
│ Team B Validator│ ←────────────────── │ Feature + ScanResult │
│ (Quality Gate)  │    + observations   │ summaries            │
│                 │ ──────────────────→ │ GeneralRecommendation│
│                 │    writes summary   │  (stage_validation)  │
└─────────────────┘                     └──────────────────────┘
```

### 4.2 Context Reset Rules

| Role | Reset Frequency | What to Keep | What to Clear |
|------|----------------|-------------|---------------|
| Team A Worker | After EACH artifact | Nothing — each artifact is independent | All artifact detail |
| Team B Worker | After each ITERATION | Feature map + 1-sentence summaries | Detailed artifact data, raw signals |
| Validation Pass | N/A (single-shot) | N/A | N/A |
| V2+ Watcher | Monitors, triggers at 70% context | N/A | Forces summary + new session |

### 4.3 Context Budget Heuristics (V1)

```python
CONTEXT_BUDGETS = {
    "ai_analysis": {
        "batch_size": 20,
        "max_output_tokens": 8000,   # ~400 per artifact
    },
    "observations": {
        "batch_size": 15,
        "max_output_tokens": 10000,  # enrichment needs more space
    },
    "grouping": {
        "batch_size": 10,
        "max_output_tokens": 12000,  # cross-artifact context
    },
    "ai_refinement": {
        "batch_size": 10,
        "max_output_tokens": 12000,
    },
    "recommendations": {
        "batch_size": 8,             # per-feature, needs depth
        "max_output_tokens": 15000,
    },
    "report": {
        "batch_size": 5,             # final narrative, most depth
        "max_output_tokens": 20000,
    },
}
```

---

## 5. Pipeline Stage → Team Mapping

| Pipeline Stage | Team | Agent Role | What Happens |
|---|---|---|---|
| `ai_analysis` | Team A Workers | Artifact Analyst | Scope triage + functional observations per artifact |
| `ai_analysis` | Team A Validator | Analysis Validator | Validate scope consistency, write summary |
| `observations` | Team A Workers | Artifact Analyst (enrichment mode) | Deepen observations for complex/scriptable artifacts |
| `observations` | Team A Validator | Analysis Validator | Validate observation quality |
| `grouping` | Team B Workers | Feature Builder | Trace relationships, form initial features |
| `grouping` | Team B Validator | Analysis Validator | Validate feature coherence, check coverage |
| `ai_refinement` | Team B Workers | Feature Builder (refinement mode) | Merge/split/verify features iteratively |
| `ai_refinement` | Team B Validator | Analysis Validator | Validate stability, check convergence |
| `recommendations` | Team B Workers | Feature Builder (recommendation mode) | OOTB evaluation per feature |
| `recommendations` | Team A Validator | Analysis Validator (OOTB review) | Validate OOTB accuracy |
| `report` | Report Workers | Report Writer | Assemble per-feature narratives |
| `report` | Validation Pass | Analysis Validator (final gate) | Consistency, completeness, readiness |

---

## 6. Scope, Disposition & Review Rules (All Roles)

These rules are injected into EVERY role prompt:

1. **Scope triage is FIRST STEP** for every artifact.
2. Scope decisions are **preliminary** — may be revised in later stages as more
   context emerges (relationships, feature groupings, usage data).
3. **Out-of-scope** artifacts are excluded from feature grouping AND final
   deliverables (xlsx/docx). Mark carefully.
4. **Adjacent** means related to the assessed app but not a direct customization
   (e.g., references custom fields, queries custom tables).
5. **review_status** stays `review_in_progress` throughout the pipeline. It only
   transitions to `reviewed` at the report stage after human confirmation.
6. **disposition** is NEVER set by AI agents. Agents may SUGGEST a disposition in
   observation text or recommendation text. The disposition field is only confirmed
   by a human reviewer after all analysis is complete.

---

## 7. Progressive Build Roadmap

### V1 (Current Target)

- Worker prompts with full role identity (Team A + Team B)
- Validation pass prompts (V1 Lead substitute)
- Director logic in `server.py` (code, not agent)
- Context control via batch size heuristics
- Stage-by-stage execution (workers → validation → next stage)

### V2

- Lead agents as separate `claude -p` sessions
- Context watcher agent (monitors, triggers resets at 70%)
- Parallel worker dispatch within a stage (V2 execution strategy)
- Lead-to-Lead handoff protocol

### V3

- Assessment Director as persistent orchestrator agent
- Heartbeat pattern (from orchestration playbook)
- Full swarm execution strategy
- Inter-agent escalation protocol

---

## 8. Appendix: Existing Prompt Sources

These existing MCP prompts provide domain knowledge injected into role prompts:

| Prompt | Used By | Content |
|--------|---------|---------|
| `artifact_analyzer` | Team A Workers | Scope triage rules, analysis dispatch by artifact type, output structure |
| `observation_artifact_reviewer` | Team A Workers (enrichment) | Batch processing strategy, scope awareness, observation format |
| `tech_assessment_expert` | Team B Workers | Assessment methodology, origin classification, disposition framework, grouping signals |
| `feature_reasoning_orchestrator` | Team B Workers | Seeding, reasoning loop, convergence, OOTB recommendations |
| `relationship_tracer` | Team B Workers (deep trace) | Dependency graph analysis, scope re-evaluation |
| `observation_landscape_reviewer` | Validation Pass | Landscape summary enrichment |
