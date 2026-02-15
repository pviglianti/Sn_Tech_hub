# 00_admin/todos.md (Template)

## How to use this checklist (non-negotiable)
- This file is the source of truth for progress.
- Every task must point to an output artifact path in 02_working/ or 03_outputs/.
- Check items only when the referenced artifact exists on disk.
- Work in small batches. After each batch, update (in this order): insights.md, todos.md, context.md (only if needed), run_log.md.
- After each checkpoint, stop and instruct (verbatim): Checkpoint complete. Run /clear now.

## Phase 0 — Setup (no analysis)
- [ ] Create/verify folder structure (per standard architecture)
- [ ] Create admin files in 00_admin/ (context.md, todos.md, insights.md, deliverables_spec.md, reference_index.md, run_log.md, prompt_factory_improvements.md)
- [ ] Create 03_outputs/00_delivery_index.md
- [ ] Initialize run_log.md with first entry
- [ ] Populate context.md (goal, scope, constraints, definitions, current status)
- [ ] Populate deliverables_spec.md (explicit acceptance criteria per deliverable)

## Phase 1 — Inventory + Triage (no synthesis)
- [ ] Inventory 01_source_data/ recursively and complete reference_index.md (path, type, 1-line summary, priority, intended use)
- [ ] Identify missing inputs (explicit list in insights.md)
- [ ] Confirm inventory + missing inputs with the user before analysis begins
- [ ] Create an extraction plan (what to pull from each source type; where drafts will live)

## Phase 2 — Extraction (iterative batches)
- [ ] Batch 1 extraction complete → artifacts saved to 02_working/ (list paths in insights.md)
- [ ] Batch 2 extraction complete → artifacts saved to 02_working/ (list paths in insights.md)
- [ ] Batch 3 extraction complete → artifacts saved to 02_working/ (list paths in insights.md)
- [ ] Batch 4 extraction complete → artifacts saved to 02_working/ (list paths in insights.md)
- [ ] Batch 5 extraction complete → artifacts saved to 02_working/ (list paths in insights.md)

## Phase 3 — Synthesis (grouping/clustering)
- [ ] Define grouping approach (what constitutes a “feature/solution”)
- [ ] Build candidate clusters/groupings → 02_working/03_candidate_lists/
- [ ] Validate clusters with cross-references (update sets, sys_metadata, sys_update_xml/sys_version, code refs)
- [ ] Promote stable clusters to outputs (traceable lists) → 03_outputs/

## Phase 4 — Deliverables (final output)
- [ ] Draft deliverables in 02_working/02_intermediate_outputs/
- [ ] Finalize deliverables to 03_outputs/ (update 00_delivery_index.md)
- [ ] Run consistency check: context.md ↔ insights.md ↔ deliverables_spec.md ↔ outputs
- [ ] Ensure every deliverable section is traceable to source paths or working artifacts

## Phase 5 — Quality + Recommendations
- [ ] Identify gaps vs OOTB (what can be replaced; what must remain)
- [ ] Recommend improvements for items that must remain (better architecture, scoped app, patterns)
- [ ] Capture global recommendations (code quality, naming, update set hygiene, data integrity)

## Phase 6 — Prompt Factory Improvements (required)
- [ ] Maintain prompt_factory_improvements.md during the job (as issues/ideas occur)
- [ ] Finalize prompt_factory_improvements.md with actionable edits to:
  - Templates/*
  - bootstrap prompt wording
  - workflow/architecture rules