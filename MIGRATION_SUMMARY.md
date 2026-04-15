# Universal Agent Architecture Migration Summary

## Overview
We have successfully transitioned the Snow-Flow and Tech Assessment Hub AI architecture from a "Fat Prompt" model (injecting massive monolithic text files on every execution) to a "Fat Context, Thin Prompt" modular architecture.

By adopting the **Agent Skills Open Standard**, we extracted all domain rules and behavioral instructions from legacy text files (`codex.txt`, `anthropic.txt`, `beast.txt`, `swarm_role_prompts.py`) into isolated, reusable Markdown files. These can now be natively installed as plugins into local LLM CLIs (Claude Code, Gemini CLI, Codex).

---

## 1. Skills Extracted (Domain Knowledge)
We separated "what to do" and "how to do it" into localized `SKILL.md` files. The AI only loads these into context when specifically requested, saving massive amounts of tokens.

**General Engineering Skills:**
- `servicenow-core`: ES5 rules, strict URL fetching logic, update set protocols.
- `github-operations`: Tool discovery patterns for interacting with GitHub Enterprise.

**Assessment Pipeline Skills:**
- `assessment-artifact-analyzer`: Rules for deep-diving into individual SN artifacts (OOTB checks, deprecated APIs, security).
- `assessment-feature-grouper`: Logic for evaluating algorithmic clusters, merging, splitting, and resolving orphans.
- `assessment-technical-architect`: Directives for assigning dispositions (keep/refactor/replace) and suggesting OOTB replacements.
- `assessment-refiner`: Holistic cross-reference checking to ensure zero dependency conflicts across features.

---

## 2. Agent Roles Created (Personas & Behaviors)
We translated the overarching personas into lightweight Agent Role definitions. The pipeline dispatcher now simply calls these roles by name.

**General Agents:**
- `snow-coder`: The standard daily-driver for software engineering and ServiceNow tasks.
- `snow-planner`: Read-only architectural planning agent.
- `snow-beast`: High-effort, autonomous recursive troubleshooting agent.
- `snow-reviewer`: Dedicated quality, security, and ES5 compliance checker.

**Assessment Pipeline Agents:**
- `snow-assessor`: Executes the `ai_analysis` phase using the artifact analyzer skill.
- `snow-architect`: Executes the `grouping` and `refinement` phases using the architect and grouper skills.

---

## 3. Automation & Deployment
To ensure this works seamlessly across all platforms without touching the legacy production code, we created a universal build script:
- **`scripts/package-install.py`**: A Python script that reads the canonical `agent-roles/` and `skills/` directories and automatically compiles them into the native formats required by `.claude/`, `.gemini/`, and `.codex/`.

## 4. Maintained Global Context
The existing `AGENTS.md` and `CLAUDE.md` files were kept strictly as **Workspace Context**. They continue to govern global repository rules (e.g., Tier 0/1/2 memory rehydration, "Reuse Before Create" engineering principles, and directory exclusions) regardless of which agent role is active.

---

## Impact
1. **Token Efficiency:** The CLI dispatcher no longer sends 5,000-word system prompts. 
2. **Simplicity:** Pipeline logic is reduced to invoking `claude --agent snow-assessor "Analyze batch 1"`.
3. **Scalability:** New ServiceNow skills can be added as single `.md` files without risking prompt regression or confusing the main coding agent.