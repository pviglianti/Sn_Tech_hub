# 00_admin/insights.md (Template)

## Operating rules (non-negotiable)
- This file is allowed to be long. It is the working brain.
- Chat should stay short. Files should hold the depth.
- If information is not written in 00_admin/*.md or present in 01_source_data/, treat it as unknown.
- Work in small batches.
- After each batch, update (in this order): insights.md, todos.md, context.md (only if needed), run_log.md.
- After each checkpoint, stop and instruct (verbatim): Checkpoint complete. Run /clear now.

## Batch log (append-only)
(One entry per batch. Keep these compact but specific.)

### Batch YYYY-MM-DD HH:MM — <short name>
- Inputs processed:
  - <path>
  - <path>
- What I extracted/learned (bullet facts):
  - 
- Artifacts created/updated:
  - 02_working/.../<file>
  - 03_outputs/.../<file>
- Decisions made this batch (link to decisions section):
  - 
- Open questions created/updated:
  - 
- Next checkpoint trigger (what ends the next batch):
  - 

## Key decisions (with rationale + traceability)
(When you make a decision, include why, tradeoffs, and where it came from.)

- Decision: <what we decided>
  - Rationale: <why>
  - Tradeoffs: <pros/cons>
  - Evidence/refs:
    - Source(s): <01_source_data/...>
    - Working artifact(s): <02_working/...>
  - Impacted deliverable(s): <03_outputs/... or deliverables_spec section>
  - Date/time:

## Extracted facts (grounded + traceable)
(Use this for durable facts you’ll want to reuse later. Avoid duplicating raw source text.)

- Fact: <statement>
  - Source path(s): <01_source_data/...>
  - Confidence: high | medium | low
  - Notes / caveats:

## Hypotheses / open questions (must include a resolution plan)

- Question: <open item>
  - Why it matters:
  - How to resolve (specific evidence to gather):
  - Candidate source paths to check:
    - <01_source_data/...>
    - <02_working/...>
  - Owner: Claude
  - Status: open | investigating | resolved

## Patterns / clusters forming (feature/solution grouping)
(Use this to record candidate groupings and the evidence that links them.)

- Candidate cluster: <name>
  - Shared purpose (1–2 lines):
  - Member artifacts (paths):
    - <sys_update_xml/sys_metadata/sys_version export path>
    - <code snippet path>
  - Relationship evidence:
    - Same update set(s): <sys_update_set/sys_update_xml export path>
    - References (code/field/table): <02_working/04_code_search/...>
    - Same table/module: <evidence>
  - Conflicts/unknowns:
  - Stability: tentative | likely | confirmed

## “Next checkpoint” instructions (required)
(Write exactly what Claude must do after a /clear reset. Keep it explicit and step-by-step.)

1) Read (in order):
   - 00_admin/context.md
   - 00_admin/todos.md
   - 00_admin/insights.md
   - 00_admin/run_log.md
2) Identify the next unchecked todo in todos.md.
3) Execute ONLY the next batch defined by the next unchecked todo.
4) When the batch ends, perform a checkpoint:
   - Update insights.md (this file)
   - Update todos.md
   - Update context.md only if needed
   - Update run_log.md
5) Then STOP and output exactly:
   Checkpoint complete. Run /clear now.