# 00_admin/context.md (Template)

## Job identity
- Chat name: [CHATNAME]
- Date created: [YYYY-MM-DD]

## Trusted memory rule
- If information is not written in 00_admin/*.md or present in 01_source_data/, treat it as unknown.

## Goal
[One paragraph: what success looks like.]

## Deliverables
- [Deliverable 1]
- [Deliverable 2]
- [etc.]

## Deliverable traceability
- deliverables_spec.md: [link or path]
- 03_outputs/00_delivery_index.md: [link or path]

## Scope
IN SCOPE:
- ...
OUT OF SCOPE:
- ...

## Constraints / Non-negotiables
- Files are memory. Chat is disposable.
- Keep chat context small by working in small batches and checkpointing often.
- After each batch, update (in this order): insights.md, todos.md, context.md (only if needed), run_log.md.
- After each checkpoint, stop and instruct (verbatim): Checkpoint complete. Run /clear now.
- After /clear (or auto-compaction), re-ground by reading: context.md, todos.md, insights.md, run_log.md (in that order).
- Treat todos.md as the progress source of truth; only check items when the referenced artifact exists.
- Record decisions + rationale and open questions in insights.md.
- Prefer authoritative references in 01_source_data/01_reference_docs.

## Definitions / Glossary
- Term: meaning
- Term: meaning

## Working assumptions (must be validated)
- ...

## Inputs expected (where to place them)
- Brief/problem statement: 01_source_data/00_brief/
- Reference docs/standards: 01_source_data/01_reference_docs/
- Raw exports/logs/screenshots: 01_source_data/02_exports_raw/
- Code snippets/search results: 01_source_data/03_codebase_snippets/ and 02_working/04_code_search/
- Unsorted items to triage: 01_source_data/99_inbox_drop/

## Current status (human-readable)
- Last checkpoint:
- Completed:
- In progress:
- Next:
- Next checkpoint trigger (what ends the current batch):