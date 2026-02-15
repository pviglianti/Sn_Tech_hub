# Rehydration Validation - 2026-02-14

## Budget Checks
- Tier 0 (`ACTIVE_PROJECT.md`): 69 words (target <=150) - PASS
- Tier 1:
  - `context.md` -> `## Rehydrate Snapshot`: 92 words
  - `todos.md` -> `## Now`: 110 words
  - Total: 202 words (target <=900) - PASS
- Tier 2:
  - `insights.md` -> `## Active Decisions`: 121 words
  - `run_log.md` tail 80 lines: 279 words
  - Total: 400 words (target <=1,800) - PASS

## Structure Checks
- `context.md` contains `## Rehydrate Snapshot` - PASS
- `todos.md` uses only `## Now`, `## Next`, `## Backlog` blocks - PASS
- `insights.md` contains `## Active Decisions` - PASS
- `run_log.md` uses standardized row format - PASS

## Rollover Threshold Checks
- `context.md`: 40 lines (limit 300) - PASS
- `todos.md`: 23 lines (limit 220) - PASS
- `insights.md`: 25 lines (limit 600) - PASS
- `run_log.md`: 15 lines (limit 1,000) - PASS

## Cross-Agent Routing Checks
- `ACTIVE_PROJECT.md` present - PASS
- `.cursorrules` present - PASS
- `.windsurfrules` present - PASS
- `.github/copilot-instructions.md` present - PASS
- `AGENTS.md` + `CLAUDE.md` aligned to same rehydration standard - PASS

## Notes
- Pre-guardrail and stale markdown were archived externally on 2026-02-14.
- Archive references are maintained in `00_admin/archive_index.md`.
