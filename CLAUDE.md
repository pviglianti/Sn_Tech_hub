# Claude Code Instructions

## Scope
This file extends `AGENTS.md` for Claude-specific behavior only.
The rehydration contract and rollover rules must stay identical to `AGENTS.md`.

## Startup Sequence (Required)
1. Read `ACTIVE_PROJECT.md`.
2. Run Tier 1 rehydration only.
3. Use Tier 2 only when task complexity requires it.

## Rehydration Limits
- Tier 0 target: <=150 words
- Tier 1 target: <=900 words
- Tier 2 target: <=1,800 words
- If target is exceeded, summarize and archive before continuing.

## Compaction Behavior
- At ~70% context: checkpoint files, then request `/compact`.
- At ~85% context: emergency checkpoint, then request `/clear`.
- After any reset: rerun Tier 0 then Tier 1.

## File Update Discipline
- Keep `context.md` focused on direction/status.
- Keep `todos.md` in `Now/Next/Backlog` only.
- Keep `insights.md` durable and concise.
- Keep `run_log.md` append-only with standardized rows.

## Tooling
- Do not auto-load whole folders.
- Do not print full rehydration files into chat.
- Prefer explicit file paths in references.
- Exclude `archive/` from default context scans and rehydration unless explicitly requested.
- Treat files under `archive/` as old/historical and ignore them for active planning and implementation unless user asks.
- Also exclude these from default scans unless explicitly requested by user or active task:
  - `docs/`
  - `Templates/`
  - `snow-flow_pv/`
  - `tech-assessment-hub/docs/plans/`
- For `00_admin/*coordination*.md` and `00_admin/*chat*.md`, load only files tied to the active phase; treat others as historical unless asked.
- If launched through `.claude/orchestration/roles/*.md`, follow the orchestration role prompt as the controlling workflow for that run. In orchestrated mode, do not apply the interactive chat polling loop from `agent_coordination_protocol.md` unless the role prompt explicitly says to.

## Engineering Principles
Follow `AGENTS.md` > "Engineering Principles" section in full. Key reminders:
- Always check for existing reusable components before creating new ones.
- User-configurable values go in the properties system, not hardcoded.
- Acknowledge refactor debt explicitly when discovered — log it, don't ignore it.

For generic rules and rollover thresholds, follow `AGENTS.md`.
