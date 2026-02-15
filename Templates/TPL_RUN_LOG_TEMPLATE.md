

# 00_admin/run_log.md (Template)

## Purpose
This is the checkpoint ledger. It should be short, factual, and append-only.
Use it to resume work after /clear by knowing exactly what was processed, what changed, and what’s next.

## Operating rules (non-negotiable)
- One entry per batch/checkpoint.
- Keep it concise (links and paths > prose).
- Do not rewrite history; append new entries.
- After each batch: update insights.md, todos.md, context.md (only if needed), then this file.
- After checkpoint: stop and instruct (verbatim): Checkpoint complete. Run /clear now.

## Log entries (append-only)

### YYYY-MM-DD HH:MM — Batch <#> — <short label>
- Inputs processed (paths):
  - 
- Outputs updated (paths):
  - 02_working/
  - 03_outputs/
- Admin updates:
  - context.md: updated | no change
  - todos.md: updated | no change
  - insights.md: updated
- Decisions made (link to insights decision bullets):
  - 
- Open questions / blockers:
  - 
- Next todo to execute:
  - 
- Next checkpoint trigger (what ends next batch):
  - 

## Resume protocol (after /clear)
1) Read (in order):
   - 00_admin/context.md
   - 00_admin/todos.md
   - 00_admin/insights.md
   - 00_admin/run_log.md
2) Jump to the most recent log entry.
3) Continue at the `Next todo to execute` line.