# AI Team Orchestration System

A portable, reusable framework for coordinating multiple AI agents (architect, PM, devs, reviewer) on a shared codebase via an outer orchestrator (Codex).

## Quick Start

1. Copy this entire folder structure into your project root
2. Orchestrator reads `AGENTS.md` > BOOTSTRAP section
3. Bootstrap resolves `servicenow_global_tech_assessment_mcp/00_admin` and `SN_TechAssessment_Hub_App` placeholders
4. Bootstrap section self-deletes after resolution
5. Follow `playbook.md` for each orchestration run

## How It Works

```
Orchestrator (Codex)
  ├── Launches Architect → produces plan
  ├── Launches PM → refines plan, assigns tasks
  ├── Creates worktrees (1 per dev)
  ├── Launches Devs in parallel → implement in worktrees
  ├── Launches Reviewer after first [DONE] → constrained reviewer
  ├── Re-launches Devs as cross-testers
  ├── Sends findings to Arch + PM for feedback
  ├── Merges worktrees → runs full tests → commits
  └── Sends memory-write prompts → session complete
```

Shared orchestration docs live only in the ROOT `orchestration_run/` directory. Devs in worktrees must edit those files via absolute paths, never via worktree-local copies.

Architect and PM do not require open tabs between prompts. They are re-launched as fresh `claude -p` runs, with continuity carried by shared docs and memory files.

All launches should be streamable to `.jsonl` logs so Codex can steer in real time.

Model / reasoning guidance:
- Architect stays on `opus` with highest reasoning (`--effort high` / ultrathink-equivalent).
- Devs, PM, reviewer, cross-testers, UI tester, and live watcher are chosen case-by-case.
- Use the cheapest tier likely to succeed, but if the stream shows drift or weak reasoning, Codex either tightens the prompt or escalates model/effort.
- Simple, tightly prescribed tasks can use `haiku` or `opus`/medium depending on risk; complex or ambiguous dev work can absolutely stay on `opus`/high.

## Folder Structure

```
.claude/orchestration/
├── README.md           ← you are here
├── config.md           ← team size, models, paths, tool restrictions
├── playbook.md         ← step-by-step for the orchestrator
├── roles/              ← self-contained prompts for each agent
├── protocols/          ← communication, checkpoints, lifecycle
└── templates/          ← blank docs copied into each run
```

## Placeholders

Before first use, the BOOTSTRAP in `AGENTS.md` resolves these:

| Placeholder | Replaced With | Example |
|-------------|---------------|---------|
| `servicenow_global_tech_assessment_mcp/00_admin` | Path to project admin files | `00_admin` |
| `SN_TechAssessment_Hub_App` | Project directory name | `my-app` |

## If Project Already Has AGENTS.md

Merge the orchestration sections from the template `AGENTS.md` into your existing one.
Keep your existing project-specific instructions and add the `## Orchestration System` section.

For orchestrated runs, `.claude/orchestration/*` overrides the interactive chat-polling workflow from `agent_coordination_protocol.md`.
