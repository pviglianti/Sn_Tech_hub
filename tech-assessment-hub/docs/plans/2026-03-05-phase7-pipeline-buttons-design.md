# Phase 7 — Human-in-the-Loop Pipeline Buttons + Re-run

**Date:** 2026-03-05
**Status:** Approved
**Approach:** Extend existing PipelineStage enum with 3 new AI stages + re-run capability

---

## Overview

Phase 6 built 4 MCP prompts (artifact_analyzer, relationship_tracer, technical_architect, report_writer) but nothing orchestrates them within the assessment pipeline. Phase 7 adds human-triggered buttons on the assessment detail page for each AI stage, with pause points between stages so humans can review and edit before the next stage runs. A re-run capability allows the full post-scan pipeline to be relaunched after completion, preserving all human edits as context.

---

## Pipeline Stages (10 stages, was 7)

```
 1. scans            → Pull customized artifacts from ServiceNow
 2. ai_analysis      → NEW: artifact_analyzer on each customized result
    [HUMAN PAUSE]    → Review AI summaries, correct if needed
 3. engines          → 6 deterministic preprocessing engines
 4. observations     → Generate baseline observations (enriched by AI context)
 5. review           → GATE: human reviews observations, edits as needed
 6. grouping         → Seed feature groups from engine signals
 7. ai_refinement    → NEW: relationship_tracer + technical_architect
    [HUMAN PAUSE]    → Review technical findings, adjust features/groupings
 8. recommendations  → Iterative feature reasoning (up to 3 passes)
 9. report           → NEW: report_writer generates assessment deliverable
10. complete         → Done
```

### New Stages Detail

#### Stage 2: `ai_analysis`

- Runs `artifact_analyzer` prompt on each customized ScanResult (origin_type in [modified_ootb, net_new_customer])
- Stores results in `ScanResult.ai_observations`
- Batch size controlled by property `ai_analysis.batch_size` (default: 0 = all, set to 50+ for batching)
- Checks for existing human-written `observations` and treats them as context
- If human has already set `disposition` or assigned to a Feature, includes that as context too

#### Stage 7: `ai_refinement`

Runs three sub-steps:
1. `relationship_tracer` on complex clusters (features with 5+ members or cross-table relationships)
2. `technical_architect` Mode A on flagged artifacts (those with critical/high severity observations)
3. `technical_architect` Mode B for assessment-wide technical debt roll-up

Results stored in:
- `GeneralRecommendation` with `category="technical_findings"` (assessment-wide)
- Per-artifact findings enriched into `ScanResult.ai_observations`
- Feature-level recommendations refined on `Feature.recommendation`

#### Stage 9: `report`

- Runs `report_writer` prompt with full assessment data
- Stores output as `GeneralRecommendation` with `category="assessment_report"`
- Generates sections: executive summary, landscape, feature analysis, technical findings, recommendations

---

## Human-Edit-as-Context Principle

**Core rule:** At every pipeline stage, the AI checks for existing human edits and treats them as authoritative context. It never overwrites human work — it builds on it.

| Stage | What AI checks for human context |
|-------|----------------------------------|
| `ai_analysis` | Existing `observations` (human-written), existing `disposition`, existing feature membership |
| `engines` | N/A (deterministic) |
| `observations` | Existing `ai_observations`, human edits to `observations` |
| `review` | N/A (purely human) |
| `grouping` | Existing Feature records (human-created), FeatureScanResult links (human-assigned) |
| `ai_refinement` | Feature.recommendation, Feature.disposition, ScanResult.disposition, GeneralRecommendation edits |
| `recommendations` | All of the above + prior pass results |
| `report` | Everything — full current state including all human changes |

### Merge Strategy

When AI generates output for a field that already has human content:
- **Observation fields:** AI appends its analysis below human text, clearly marked as `[AI Analysis]`
- **Recommendation fields:** If human has written a recommendation, AI refines it rather than replacing
- **Disposition fields:** If human has set a disposition, AI accepts it and provides supporting rationale
- **Feature membership:** If human has moved artifacts between features, AI accepts the new grouping

---

## Re-run Capability

After pipeline reaches `complete`:
- "Re-run Analysis" button appears on assessment detail page
- Clicking resets `pipeline_stage` to `ai_analysis`
- All human edits are preserved (Features, dispositions, observations, recommendations)
- AI treats the full current state as context for the next pass
- Changed feature memberships, dispositions, and recommendations from humans are accepted as ground truth
- The pipeline runs through all stages again with enriched context

---

## UI Changes

### Flow Bar
- Extends from 7 to 10 steps, same visual style
- New step labels: "AI Analysis" (2), "AI Refinement" (7), "Report" (9)

### Buttons on Assessment Detail

| Stage | Button Label | Action |
|-------|-------------|--------|
| `ai_analysis` | "Run AI Analysis" | Triggers artifact_analyzer on customized results |
| `engines` | "Run Engines" | (existing) |
| `observations` | "Generate Observations" | (existing) |
| `review` | "Enter Review" / "Skip Review" | (existing) |
| `grouping` | "Run Grouping" | (existing) |
| `ai_refinement` | "Run AI Refinement" | Triggers relationship_tracer + technical_architect |
| `recommendations` | "Run Recommendations" | (existing) |
| `report` | "Generate Report" | Triggers report_writer |
| `complete` | "Re-run Analysis" | Resets to ai_analysis stage |

### Progress Tracking
- Each AI stage uses the existing job tracking system (`_ASSESSMENT_PIPELINE_JOBS`)
- Polling at `/api/assessments/{id}/scan-status` returns progress for AI stages
- Progress bar shows "Processing artifact X of Y" during ai_analysis batch processing

---

## Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `ai_analysis.batch_size` | integer | `0` | Number of artifacts to process per batch. 0 = all at once. Set to 50+ for large assessments. |

---

## Output & Deliverables

### Data Storage (no new tables)

All AI outputs use existing models:
- `ScanResult.ai_observations` — per-artifact AI analysis
- `GeneralRecommendation` — technical findings, report sections, landscape summaries (has `assessment_id` FK)
- `Feature.recommendation` / `Feature.disposition` — feature-level outputs
- `ScanResult.disposition` — per-artifact disposition

### Export Sheets (future — not in this phase)

| Sheet | Source | Key Columns |
|-------|--------|-------------|
| **Customizations** | ScanResult (customized) | Name, Table, Origin, Observation, Recommendation, Disposition, Feature Ref |
| **Features** | Feature + members | Name, Description/Purpose, Observation, Recommendation, Disposition |
| **Technical Recommendations** | GeneralRecommendation (technical_findings) | Finding, Severity, Affected Count, BestPractice Code, Recommendation |
| **Process Recommendations** | GeneralRecommendation (process) | Title, Description, Recommendation *(human-authored)* |

### Word/PDF Document (future — not in this phase)
Generated by `report_writer`, stored as `GeneralRecommendation` with `category="assessment_report"`.

---

## Implementation Scope

### In Scope (Phase 7)
1. Extend `PipelineStage` enum with `ai_analysis`, `ai_refinement`, `report`
2. Update `_PIPELINE_STAGE_ORDER` and stage handler dispatch
3. Implement stage handlers that call MCP prompts with DB context
4. Add `ai_analysis.batch_size` property
5. Update flow bar UI (10 steps)
6. Update `advance-pipeline` endpoint to handle new stages
7. Add "Re-run Analysis" button after complete
8. Update polling endpoint to report AI stage progress
9. Migrate existing assessments (set pipeline_stage correctly for in-progress ones)

### Out of Scope (Later)
- Excel/Word export generation
- Process recommendations UI
- Learning/self-improvement from human edits (Phase 8)
- New tabs for technical/process recommendations on assessment page

---

## Dependencies

- Phase 6 MCP prompts (artifact_analyzer, relationship_tracer, technical_architect, report_writer) — DONE
- BestPractice catalog (41 checks) — DONE
- Session-aware prompt infrastructure — DONE
- Existing pipeline job tracking system — DONE
