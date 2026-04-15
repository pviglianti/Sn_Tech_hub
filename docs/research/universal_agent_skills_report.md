# Universal Agent Skills, Agents, and MCP Across LLM CLI Tools

**Research Report -- April 2026**
**Scope**: Claude Code, OpenAI Codex CLI, Google Gemini CLI

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Agent Skills Open Standard](#2-the-agent-skills-open-standard)
3. [Claude Code: Skills, Agents, Hooks, MCP](#3-claude-code)
4. [OpenAI Codex CLI: Skills, Agents, Plugins, MCP](#4-openai-codex-cli)
5. [Google Gemini CLI: Skills, Agents, Hooks, MCP](#5-google-gemini-cli)
6. [Cross-Platform Comparison Matrix](#6-cross-platform-comparison-matrix)
7. [Universal MCP Configuration](#7-universal-mcp-configuration)
8. [Designing a Universal .md-Based Dispatch System](#8-universal-dispatch-system)
9. [Best Practices for Writing Agent .md Files](#9-best-practices)
10. [Concrete Universal Skill Example](#10-concrete-example)
11. [Architecture for TA Hub Multi-CLI Dispatch](#11-ta-hub-architecture)
12. [Sources](#sources)

---

## 1. Executive Summary

All three major LLM CLI tools (Claude Code, Codex CLI, Gemini CLI) have converged on the **Agent Skills open standard** for defining portable, task-specific capabilities. The core format is a `SKILL.md` file with YAML frontmatter (`name`, `description`) and markdown instructions. Each platform extends this base with proprietary fields. MCP (Model Context Protocol) is supported by all three, though config formats differ. Subagents/agents are defined as markdown files with YAML frontmatter in all three tools, using nearly identical patterns.

**Key finding**: You can define one `SKILL.md` per skill that works across all three CLIs. Agent definitions require thin per-platform wrappers but can share the same core system prompt. MCP servers configured once can be referenced from all three tools.

---

## 2. The Agent Skills Open Standard

The Agent Skills standard (published by Anthropic, adopted by OpenAI and Google) defines a universal format for packaging AI agent capabilities.

### Specification (agentskills.io)

**Directory structure:**
```
skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
```

**SKILL.md universal frontmatter:**

| Field           | Required | Description                                              |
|:----------------|:---------|:---------------------------------------------------------|
| `name`          | Yes      | 1-64 chars, lowercase + hyphens, must match dir name    |
| `description`   | Yes      | 1-1024 chars, what + when to use                         |
| `license`       | No       | License name or file reference                           |
| `compatibility` | No       | Environment requirements (max 500 chars)                 |
| `metadata`      | No       | Arbitrary key-value pairs                                |
| `allowed-tools` | No       | Space-delimited tool pre-approvals (experimental)        |

**Minimal valid SKILL.md:**
```yaml
---
name: sn-table-analyzer
description: Analyzes ServiceNow table structures, relationships, and customizations. Use when examining table schemas, dictionary entries, or cross-table references.
---

When analyzing a ServiceNow table:

1. Pull the table's dictionary entries
2. Identify custom fields (u_ prefix) vs OOTB
3. Map relationships via reference fields
4. Flag potential issues (orphan references, missing indexes)
5. Output structured JSON findings
```

**Progressive disclosure model:**
1. **Metadata** (~100 tokens) -- name + description loaded at startup for all skills
2. **Instructions** (<5000 tokens recommended) -- full SKILL.md loaded on activation
3. **Resources** (on demand) -- scripts/, references/, assets/ loaded when needed

---

## 3. Claude Code

### 3.1 Skills

Claude Code fully implements the Agent Skills standard and adds proprietary extensions.

**Discovery locations (priority order):**

| Scope      | Path                                      | Applies to                  |
|:-----------|:------------------------------------------|:----------------------------|
| Enterprise | Managed settings                          | All org users               |
| Personal   | `~/.claude/skills/<name>/SKILL.md`        | All your projects           |
| Project    | `.claude/skills/<name>/SKILL.md`          | This project only           |
| Plugin     | `<plugin>/skills/<name>/SKILL.md`         | Where plugin enabled        |

**Claude-specific frontmatter extensions:**

| Field                      | Description                                                       |
|:---------------------------|:------------------------------------------------------------------|
| `disable-model-invocation` | `true` = only user can invoke via `/name`                         |
| `user-invocable`           | `false` = only Claude can invoke (background knowledge)           |
| `context`                  | `fork` = run in isolated subagent context                         |
| `agent`                    | Which subagent type (`Explore`, `Plan`, custom name)              |
| `model`                    | Model override for this skill                                     |
| `effort`                   | `low`, `medium`, `high`, `max`                                    |
| `paths`                    | Glob patterns limiting when skill activates                       |
| `hooks`                    | Lifecycle hooks scoped to this skill                              |
| `shell`                    | `bash` (default) or `powershell`                                  |
| `argument-hint`            | Autocomplete hint like `[issue-number]`                           |

**String substitutions in skill content:**
- `$ARGUMENTS` -- all args passed to skill
- `$ARGUMENTS[N]` or `$N` -- positional args
- `${CLAUDE_SESSION_ID}` -- current session ID
- `${CLAUDE_SKILL_DIR}` -- directory containing the SKILL.md

**Dynamic context injection:**
```yaml
---
name: pr-summary
context: fork
agent: Explore
---

## Live PR data
- PR diff: !`gh pr diff`
- Changed files: !`gh pr diff --name-only`

Summarize this pull request.
```

The `` !`command` `` syntax runs shell commands **before** content is sent to the model.

### 3.2 Subagents

Subagents are markdown files with YAML frontmatter stored in `.claude/agents/` (project) or `~/.claude/agents/` (personal).

**Built-in subagents:**
- **Explore** -- Haiku, read-only, fast codebase search
- **Plan** -- inherits model, read-only, planning research
- **general-purpose** -- inherits model, all tools, complex multi-step tasks

**Subagent frontmatter:**

| Field             | Required | Description                                                    |
|:------------------|:---------|:---------------------------------------------------------------|
| `name`            | Yes      | Unique lowercase identifier                                    |
| `description`     | Yes      | When to delegate to this subagent                              |
| `tools`           | No       | Allowlist of tools (inherits all if omitted)                   |
| `disallowedTools` | No       | Denylist of tools                                              |
| `model`           | No       | `sonnet`, `opus`, `haiku`, full ID, or `inherit`               |
| `permissionMode`  | No       | `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan` |
| `maxTurns`        | No       | Max agentic turns                                              |
| `skills`          | No       | Skills to preload into context                                 |
| `mcpServers`      | No       | MCP servers (inline definitions or name references)            |
| `hooks`           | No       | Lifecycle hooks scoped to this subagent                        |
| `memory`          | No       | `user`, `project`, or `local` -- persistent memory             |
| `background`      | No       | `true` = always run as background task                         |
| `effort`          | No       | `low`, `medium`, `high`, `max`                                 |
| `isolation`       | No       | `worktree` = isolated git worktree                             |
| `color`           | No       | Display color in UI                                            |
| `initialPrompt`   | No       | Auto-submitted first user turn when run via `--agent`          |

**Example subagent (`~/.claude/agents/sn-reviewer.md`):**
```yaml
---
name: sn-reviewer
description: Reviews ServiceNow customizations for best practices, upgrade safety, and performance. Delegate when analyzing SN artifacts.
tools: Read, Grep, Glob, Bash
model: sonnet
memory: user
skills:
  - sn-best-practices
  - sn-naming-conventions
---

You are a ServiceNow technical reviewer. When analyzing artifacts:

1. Check naming conventions (u_ prefix, scope prefix for scoped apps)
2. Identify upgrade-unsafe patterns (direct OOTB modifications)
3. Flag performance concerns (GlideRecord in client scripts, dot-walking depth)
4. Verify ACL coverage for custom tables
5. Check for hardcoded sys_ids or instance-specific values

Output findings as structured JSON with severity levels.
```

**CLI-defined subagents (session-only):**
```bash
claude --agents '{
  "sn-scanner": {
    "description": "Scans SN instance artifacts for assessment",
    "prompt": "You scan ServiceNow instances...",
    "tools": ["Read", "Grep", "Bash"],
    "model": "sonnet"
  }
}'
```

### 3.3 Hooks

Hooks are deterministic shell commands, HTTP endpoints, LLM prompts, or agents that fire at lifecycle points.

**Lifecycle events:**
```
SessionStart -> UserPromptSubmit -> [PreToolUse -> PermissionRequest -> PostToolUse] -> Stop -> SessionEnd
```

Plus async: `FileChanged`, `CwdChanged`, `ConfigChange`, `InstructionsLoaded`, `Notification`, `SubagentStart/Stop`, `TaskCreated/Completed`, `PreCompact/PostCompact`

**Configuration (in `.claude/settings.json`):**
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/validate-bash.sh",
            "timeout": 600
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/lint-check.sh"
          }
        ]
      }
    ]
  }
}
```

**Hook handler types:**
- `command` -- shell script, exit 0=success, exit 2=blocking error
- `http` -- POST to endpoint with JSON payload
- `prompt` -- LLM call with fast model
- `agent` -- spawn agent to evaluate

**Hook output JSON (from command/http):**
```json
{
  "continue": true,
  "decision": "allow",
  "reason": "Command is safe",
  "additionalContext": "Note: this modifies the database",
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow"
  }
}
```

### 3.4 MCP Configuration

**Project-level (`.mcp.json` at project root):**
```json
{
  "mcpServers": {
    "sn-tools": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "snow_flow.mcp_server"],
      "env": {
        "SN_INSTANCE": "dev12345"
      }
    }
  }
}
```

**User-level (`~/.claude/mcp-config.json`):**
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/docs"]
    }
  }
}
```

**CLI flag:**
```bash
claude --mcp-config ./custom-mcp.json
```

**Scoping MCP to subagents (inline in agent frontmatter):**
```yaml
mcpServers:
  - sn-tools:
      type: stdio
      command: python
      args: ["-m", "snow_flow.mcp_server"]
  - github  # reference existing server by name
```

---

## 4. OpenAI Codex CLI

### 4.1 Skills

Codex CLI fully supports the Agent Skills standard with its own discovery hierarchy.

**Discovery locations (priority order):**

| Scope       | Path                          | Use case                    |
|:------------|:------------------------------|:----------------------------|
| Repo (cwd)  | `.agents/skills/`             | Folder-specific workflows   |
| Repo (root) | `$REPO_ROOT/.agents/skills/`  | Org-wide standards          |
| User        | `$HOME/.agents/skills/`       | Personal cross-project      |
| Admin       | `/etc/codex/skills/`          | System-wide defaults        |
| System      | Bundled                       | OpenAI-provided utilities   |

Note: Codex uses `.agents/skills/` rather than `.claude/skills/`. This is the key path difference.

**Codex-specific metadata (`agents/openai.yaml`):**
```yaml
interface:
  display_name: "SN Table Scanner"
  short_description: "Scan ServiceNow tables"
  icon_small: "./assets/icon.svg"
  brand_color: "#3B82F6"
  default_prompt: "Scan the following table..."

policy:
  allow_implicit_invocation: false

dependencies:
  tools:
    - type: "mcp"
      value: "sn-tools"
      description: "ServiceNow MCP tools"
```

**Activation:**
- Explicit: `/skills` command or `$skill-name` mention syntax
- Implicit: Codex auto-matches tasks to skill descriptions

**Install/manage:**
```bash
# Install curated skill
$skill-installer linear

# Create new skill
$skill-creator

# Disable without deleting (config.toml)
[[skills.config]]
path = "/path/to/skill/SKILL.md"
enabled = false
```

### 4.2 Agents (Subagents)

Codex defines agents as standalone TOML files.

**Discovery:** `~/.codex/agents/` (personal) or `.codex/agents/` (project-scoped).

**Agent TOML schema:**

| Field                    | Required | Description                            |
|:-------------------------|:---------|:---------------------------------------|
| `name`                   | Yes      | Agent identifier                       |
| `description`            | Yes      | When to use this agent                 |
| `developer_instructions` | Yes      | Core behavioral instructions           |
| `nickname_candidates`    | No       | Display name pool                      |
| `model`                  | No       | Model selection                        |
| `model_reasoning_effort` | No       | Reasoning level                        |
| `sandbox_mode`           | No       | Execution constraints                  |
| `mcp_servers`            | No       | Tool integrations                      |
| `skills.config`          | No       | Skill definitions                      |

**Example (`.codex/agents/sn-reviewer.toml`):**
```toml
name = "sn-reviewer"
description = "Reviews ServiceNow customizations for best practices and upgrade safety."
model = "gpt-5-codex"
sandbox_mode = "read-only"

developer_instructions = """
You are a ServiceNow technical reviewer. When analyzing artifacts:

1. Check naming conventions (u_ prefix, scope prefix for scoped apps)
2. Identify upgrade-unsafe patterns (direct OOTB modifications)
3. Flag performance concerns
4. Verify ACL coverage
5. Check for hardcoded sys_ids

Output findings as structured JSON with severity levels.
"""
```

**Built-in agents:**
- `default` -- general-purpose fallback
- `worker` -- execution-focused implementation
- `explorer` -- read-heavy codebase exploration

**Global agent settings (`config.toml`):**
```toml
[agents]
max_threads = 6      # concurrent agent cap
max_depth = 1        # nesting depth
job_max_runtime_seconds = 300
```

### 4.3 AGENTS.md (System Instructions)

Codex uses `AGENTS.md` files (not `CLAUDE.md`) for persistent project instructions. Plain markdown, no frontmatter.

**Discovery order:**
1. `~/.codex/AGENTS.override.md` then `AGENTS.md` (global)
2. Git root to cwd: each directory's `AGENTS.override.md` then `AGENTS.md`
3. Files concatenate root-downward; closer files override

**Size limit:** 32 KiB default (`project_doc_max_bytes` in config.toml).

**Custom fallback filenames:**
```toml
project_doc_fallback_filenames = ["TEAM_GUIDE.md", ".agents.md"]
```

### 4.4 MCP Configuration

**In `~/.codex/config.toml`:**
```toml
[mcp_servers.sn-tools]
command = "python"
args = ["-m", "snow_flow.mcp_server"]
cwd = "/path/to/project"
enabled = true
enabled_tools = ["query_table", "get_record"]
env = { SN_INSTANCE = "dev12345" }
startup_timeout_sec = 10
tool_timeout_sec = 60

# HTTP server example
[mcp_servers.remote-api]
url = "https://api.example.com/mcp"
bearer_token_env_var = "API_TOKEN"
```

**CLI management:**
```bash
codex mcp add sn-tools -- python -m snow_flow.mcp_server
codex mcp list
codex mcp remove sn-tools
```

### 4.5 Features Toggle

```toml
[features]
multi_agent = true       # agent spawning (stable, on by default)
web_search = true        # web search (stable, on by default)
smart_approvals = false  # guardian reviewer subagent (experimental)
```

---

## 5. Google Gemini CLI

### 5.1 Skills

Gemini CLI supports the Agent Skills standard with its own discovery hierarchy.

**Discovery tiers:**

| Scope     | Path                                            | Override precedence |
|:----------|:------------------------------------------------|:--------------------|
| Workspace | `.gemini/skills/` or `.agents/skills/`          | Highest             |
| User      | `~/.gemini/skills/` or `~/.agents/skills/`      | Medium              |
| Extension | Bundled within extensions                        | Lowest              |

Note: Gemini supports **both** `.gemini/skills/` and `.agents/skills/` paths.

**Activation workflow:**
1. At session start, Gemini scans discovery tiers and injects skill name+description into system prompt
2. When Gemini identifies a matching task, it calls `activate_skill` tool
3. User confirms activation
4. Full SKILL.md content injected into context
5. Agent executes with prioritized skill guidance

**Skill management:**
```bash
# CLI commands
gemini skills list
gemini skills install <name>
gemini skills uninstall <name>
gemini skills link <path>
gemini skills enable <name>
gemini skills disable <name>

# Interactive commands
/skills list
/skills link
/skills disable
/skills enable
/skills reload
```

**Skill configuration in settings.json:**
```json
{
  "skills": {
    "enabled": true,
    "disabled": ["skill-name-to-skip"]
  }
}
```

### 5.2 Subagents

Gemini CLI subagents are markdown files with YAML frontmatter.

**Discovery:**
- Project: `.gemini/agents/*.md`
- User: `~/.gemini/agents/*.md`

**Frontmatter fields:**

| Field         | Type   | Required | Description                                   |
|:--------------|:-------|:---------|:----------------------------------------------|
| `name`        | string | Yes      | Unique identifier (lowercase, hyphens allowed)|
| `description` | string | Yes      | What the agent does                           |
| `kind`        | string | No       | `local` (default) or `remote`                 |
| `tools`       | array  | No       | Tool names; supports wildcards (`*`, `mcp_*`) |
| `mcpServers`  | object | No       | Inline MCP server configuration               |
| `model`       | string | No       | Model override                                |
| `temperature` | number | No       | 0.0-2.0, defaults to 1                        |
| `max_turns`   | number | No       | Turn limit, defaults to 30                    |
| `timeout_mins`| number | No       | Max execution time, defaults to 10            |

**Built-in subagents:**
- `codebase_investigator` -- analyzes codebases and dependencies
- `cli_help` -- Gemini CLI knowledge
- `generalist_agent` -- routes to appropriate specialists
- `browser_agent` -- web browser automation (experimental)

**Example (`.gemini/agents/sn-reviewer.md`):**
```yaml
---
name: sn-reviewer
description: Reviews ServiceNow customizations for best practices and upgrade safety
tools:
  - read_file
  - search_files
  - run_command
  - mcp_sn-tools_*
model: gemini-2.5-pro
max_turns: 20
timeout_mins: 5
---

You are a ServiceNow technical reviewer. When analyzing artifacts:

1. Check naming conventions (u_ prefix, scope prefix for scoped apps)
2. Identify upgrade-unsafe patterns (direct OOTB modifications)
3. Flag performance concerns
4. Verify ACL coverage
5. Check for hardcoded sys_ids

Output findings as structured JSON with severity levels.
```

**Invocation:**
- Automatic: main agent delegates based on task
- Explicit: `@sn-reviewer analyze this business rule`
- Subagents cannot call other subagents (recursion protection)

### 5.3 System Prompts (GEMINI.md)

`GEMINI.md` is Gemini's equivalent of `CLAUDE.md`. It provides persistent project context.

**Discovery:** Walks up directory tree from cwd, stopping at `.git` boundaries. All found `GEMINI.md` files are concatenated.

**Modular imports:**
```markdown
# Project Context

@lib/api-conventions.md
@lib/coding-standards.md
```

**Full system prompt override:**
```bash
export GEMINI_SYSTEM_MD=/path/to/custom-system.md
```

When overriding, use template variables to retain built-in capabilities:
```markdown
${AgentSkills}
${SubAgents}
${AvailableTools}

# Custom Instructions
Your custom instructions here...
```

### 5.4 Hooks

Gemini CLI has a hooks system configured in `settings.json`.

**Hook lifecycle points:**
- `BeforeTool` / `AfterTool`
- `BeforeAgent` / `AfterAgent`
- `SessionStart` / `SessionEnd`
- `PreCompress`
- `BeforeModel` / `AfterModel`
- `BeforeToolSelection`
- `Notification`

**Configuration in `~/.gemini/settings.json`:**
```json
{
  "hooks": {
    "BeforeTool": {
      "command": "./scripts/validate-tool.sh",
      "enabled": true
    },
    "AfterTool": {
      "command": "./scripts/post-tool-check.sh",
      "enabled": true
    },
    "SessionStart": {
      "command": "./scripts/setup-env.sh",
      "enabled": true
    }
  }
}
```

### 5.5 MCP Configuration

**In `~/.gemini/settings.json`:**
```json
{
  "mcpServers": {
    "sn-tools": {
      "command": "python",
      "args": ["-m", "snow_flow.mcp_server"],
      "env": {
        "SN_INSTANCE": "$SN_INSTANCE"
      },
      "timeout": 15000
    },
    "remote-api": {
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer $API_TOKEN"
      }
    }
  }
}
```

**CLI management:**
```bash
gemini mcp add sn-tools -- python -m snow_flow.mcp_server
gemini mcp list
gemini mcp remove sn-tools
gemini mcp enable sn-tools
gemini mcp disable sn-tools
```

---

## 6. Cross-Platform Comparison Matrix

### 6.1 Skills

| Feature                    | Claude Code                           | Codex CLI                          | Gemini CLI                         |
|:---------------------------|:--------------------------------------|:-----------------------------------|:-----------------------------------|
| Standard                   | Agent Skills (creator)                | Agent Skills (adopted)             | Agent Skills (adopted)             |
| Skill file                 | `SKILL.md`                            | `SKILL.md`                         | `SKILL.md`                         |
| Project path               | `.claude/skills/`                     | `.agents/skills/`                  | `.gemini/skills/` or `.agents/skills/` |
| User path                  | `~/.claude/skills/`                   | `~/.agents/skills/`               | `~/.gemini/skills/` or `~/.agents/skills/` |
| Auto-invocation            | Yes (description matching)            | Yes (implicit matching)            | Yes (activate_skill tool)          |
| Manual invocation          | `/skill-name`                         | `/skills` or `$skill-name`         | `/skills` menu                     |
| Disable auto-invoke        | `disable-model-invocation: true`      | `allow_implicit_invocation: false` | disabled list in settings          |
| Subagent execution         | `context: fork` + `agent:` field      | N/A (agents are separate)          | N/A (agents are separate)          |
| Dynamic context            | `` !`command` `` syntax               | N/A                                | N/A                                |
| String substitutions       | `$ARGUMENTS`, `$N`, `${CLAUDE_*}`     | N/A                                | N/A                                |
| Scoped hooks               | Yes (in frontmatter)                  | No                                 | No                                 |

### 6.2 Agents/Subagents

| Feature               | Claude Code                    | Codex CLI                     | Gemini CLI                    |
|:-----------------------|:-------------------------------|:------------------------------|:------------------------------|
| Definition format      | Markdown + YAML frontmatter    | TOML file                     | Markdown + YAML frontmatter   |
| Project path           | `.claude/agents/`              | `.codex/agents/`              | `.gemini/agents/`             |
| User path              | `~/.claude/agents/`            | `~/.codex/agents/`            | `~/.gemini/agents/`           |
| System prompt          | Markdown body                  | `developer_instructions`      | Markdown body                 |
| Tool restriction       | `tools:` allowlist             | N/A in TOML (sandbox_mode)    | `tools:` array with wildcards |
| Tool denylist          | `disallowedTools:`             | N/A                           | N/A                           |
| MCP scoping            | `mcpServers:` in frontmatter   | `mcp_servers` in TOML         | `mcpServers:` in frontmatter  |
| Skill preloading       | `skills:` field                | `skills.config` field         | N/A                           |
| Memory persistence     | `memory: user/project/local`   | N/A                           | N/A                           |
| Max turns              | `maxTurns:`                    | N/A (global timeout)          | `max_turns:`                  |
| Model override         | `model:` (alias or full ID)    | `model:` in TOML              | `model:` in frontmatter       |
| Nesting                | No (subagents cannot spawn)    | `max_depth: 1` (configurable) | No (recursion protection)     |
| CLI-defined agents     | `--agents '{json}'`            | N/A                           | N/A                           |
| Explicit invocation    | Claude decides + ask           | Codex decides                 | `@agent-name` prefix          |

### 6.3 System Prompts

| Feature          | Claude Code          | Codex CLI              | Gemini CLI              |
|:-----------------|:---------------------|:-----------------------|:------------------------|
| File name        | `CLAUDE.md`          | `AGENTS.md`            | `GEMINI.md`             |
| Format           | Markdown (no front.) | Markdown (no front.)   | Markdown (supports @imports) |
| Discovery        | Walk up to git root  | Walk up to git root    | Walk up to git root     |
| Override file    | N/A                  | `AGENTS.override.md`   | `GEMINI_SYSTEM_MD` env  |
| Size limit       | N/A (practical)      | 32 KiB                 | N/A                     |
| Concatenation    | Root down            | Root down              | Root down               |

### 6.4 Hooks

| Feature        | Claude Code                              | Codex CLI    | Gemini CLI                        |
|:---------------|:-----------------------------------------|:-------------|:----------------------------------|
| Config file    | `.claude/settings.json`                  | N/A          | `settings.json`                   |
| Handler types  | command, http, prompt, agent             | N/A          | command                           |
| Pre-tool       | `PreToolUse` with matcher                | N/A          | `BeforeTool`                      |
| Post-tool      | `PostToolUse` with matcher               | N/A          | `AfterTool`                       |
| Session hooks  | `SessionStart`, `SessionEnd`             | N/A          | `SessionStart`, `SessionEnd`      |
| Blocking       | Exit code 2 blocks                       | N/A          | Configurable                      |
| Agent hooks    | `SubagentStart/Stop`                     | N/A          | `BeforeAgent/AfterAgent`          |
| Scoped to skill| Yes (in SKILL.md frontmatter)            | N/A          | No                                |

### 6.5 MCP

| Feature        | Claude Code                | Codex CLI                  | Gemini CLI                 |
|:---------------|:---------------------------|:---------------------------|:---------------------------|
| Config file    | `.mcp.json`                | `~/.codex/config.toml`     | `settings.json`            |
| Config format  | JSON (`mcpServers`)        | TOML (`mcp_servers`)       | JSON (`mcpServers`)        |
| Transports     | stdio, http, sse, ws       | stdio, streaming HTTP      | stdio, http, sse           |
| CLI management | `claude mcp add`           | `codex mcp add`            | `gemini mcp add`           |
| Tool filtering | per-server config          | `enabled_tools/disabled_tools` | `includeTools/excludeTools`|
| Agent scoping  | `mcpServers:` in agent .md | `mcp_servers` in agent TOML | `mcpServers:` in agent .md |

---

## 7. Universal MCP Configuration

All three CLIs use the same MCP protocol but different config formats. Here is how to maintain one MCP server and configure it for all three.

### 7.1 The MCP Server (shared)

Your MCP server code is the same regardless of client. Example `snow_flow/mcp_server.py`:
```python
# Standard MCP server -- works with all three CLIs
from mcp.server.stdio import StdioServerTransport
from mcp.server import Server

server = Server("sn-tools")

@server.tool()
async def query_table(table: str, query: str) -> str:
    """Query a ServiceNow table with encoded query."""
    ...

if __name__ == "__main__":
    server.run(StdioServerTransport())
```

### 7.2 Per-CLI Config Files

**Claude Code (`.mcp.json`):**
```json
{
  "mcpServers": {
    "sn-tools": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "snow_flow.mcp_server"],
      "env": { "SN_INSTANCE": "dev12345" }
    }
  }
}
```

**Codex CLI (`~/.codex/config.toml` or `.codex/config.toml`):**
```toml
[mcp_servers.sn-tools]
command = "python"
args = ["-m", "snow_flow.mcp_server"]
env = { SN_INSTANCE = "dev12345" }
```

**Gemini CLI (`.gemini/settings.json`):**
```json
{
  "mcpServers": {
    "sn-tools": {
      "command": "python",
      "args": ["-m", "snow_flow.mcp_server"],
      "env": { "SN_INSTANCE": "$SN_INSTANCE" }
    }
  }
}
```

### 7.3 Generator Script

Automate config generation from a single source of truth:

```python
#!/usr/bin/env python3
"""Generate MCP configs for all CLI tools from a single definition."""
import json, toml

MCP_SERVERS = {
    "sn-tools": {
        "command": "python",
        "args": ["-m", "snow_flow.mcp_server"],
        "env": {"SN_INSTANCE": "dev12345"}
    },
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    }
}

# Claude Code: .mcp.json
with open(".mcp.json", "w") as f:
    json.dump({"mcpServers": {
        k: {"type": "stdio", **v} for k, v in MCP_SERVERS.items()
    }}, f, indent=2)

# Codex CLI: .codex/config.toml (merge into existing)
codex_cfg = {"mcp_servers": MCP_SERVERS}
with open(".codex/config.toml", "w") as f:
    toml.dump(codex_cfg, f)

# Gemini CLI: .gemini/settings.json (merge into existing)
gemini_cfg = {"mcpServers": MCP_SERVERS}
with open(".gemini/settings.json", "w") as f:
    json.dump(gemini_cfg, f, indent=2)
```

---

## 8. Designing a Universal .md-Based Dispatch System

### 8.1 The Convergence Point

All three CLIs share:
- SKILL.md with `name` + `description` frontmatter (Agent Skills standard)
- Markdown-body agent definitions with frontmatter metadata
- MCP server connections for tool access
- Directory-based discovery (project and user scope)

The divergence is in:
- Skills path: `.claude/skills/` vs `.agents/skills/` vs `.gemini/skills/`
- Agent format: Markdown (Claude/Gemini) vs TOML (Codex)
- Agent path: `.claude/agents/` vs `.codex/agents/` vs `.gemini/agents/`
- System prompt file: `CLAUDE.md` vs `AGENTS.md` vs `GEMINI.md`

### 8.2 Universal Directory Layout

```
project-root/
├── .agents/                    # Cross-platform (Codex + Gemini support this)
│   └── skills/                 # SKILL.md files (universal standard)
│       ├── sn-table-analyzer/
│       │   └── SKILL.md
│       └── sn-best-practices/
│           └── SKILL.md
│
├── .claude/                    # Claude Code specific
│   ├── skills/                 # Symlinks to .agents/skills/ OR copies
│   ├── agents/                 # Claude subagent .md files
│   ├── settings.json           # Hooks config
│   └── hooks/                  # Hook scripts
│
├── .codex/                     # Codex CLI specific
│   ├── agents/                 # Codex agent .toml files
│   └── config.toml             # MCP + features config
│
├── .gemini/                    # Gemini CLI specific
│   ├── skills/                 # Symlinks to .agents/skills/ OR copies
│   ├── agents/                 # Gemini subagent .md files
│   └── settings.json           # MCP + hooks config
│
├── .mcp.json                   # Claude Code MCP config
├── CLAUDE.md                   # Claude system prompt
├── AGENTS.md                   # Codex system prompt
├── GEMINI.md                   # Gemini system prompt
│
├── agent-roles/                # CANONICAL role definitions (source of truth)
│   ├── sn-reviewer.md          # Shared system prompt content
│   ├── sn-scanner.md
│   └── sn-architect.md
│
└── scripts/
    ├── sync-skills.sh          # Symlink .agents/skills to all CLI paths
    ├── sync-agents.sh          # Generate per-CLI agent files from agent-roles/
    ├── sync-mcp.py             # Generate MCP configs from single definition
    └── sync-system-prompts.sh  # Generate CLAUDE.md/AGENTS.md/GEMINI.md
```

### 8.3 Skill Sync (one SKILL.md, all CLIs)

Since all three CLIs support `.agents/skills/` (Codex natively, Gemini optionally), you can use that as the canonical path and symlink for Claude:

```bash
#!/bin/bash
# scripts/sync-skills.sh -- Symlink skills across all CLI directories

SKILLS_DIR=".agents/skills"

# Claude Code
mkdir -p .claude/skills
for skill_dir in "$SKILLS_DIR"/*/; do
    skill_name=$(basename "$skill_dir")
    ln -sfn "../../$SKILLS_DIR/$skill_name" ".claude/skills/$skill_name"
done

# Gemini CLI (also supports .agents/skills natively, but symlink .gemini too)
mkdir -p .gemini/skills
for skill_dir in "$SKILLS_DIR"/*/; do
    skill_name=$(basename "$skill_dir")
    ln -sfn "../../$SKILLS_DIR/$skill_name" ".gemini/skills/$skill_name"
done

echo "Skills synced to all CLI directories."
```

### 8.4 Agent Sync (one role definition, per-CLI format)

Define canonical agent roles as plain markdown, then generate per-CLI wrappers:

**Canonical role (`agent-roles/sn-reviewer.md`):**
```markdown
---
# Universal agent metadata (not tied to any CLI)
role: sn-reviewer
description: Reviews ServiceNow customizations for best practices, upgrade safety, and performance
tools:
  - read_files
  - search_files
  - run_commands
  - mcp:sn-tools
model_preference: mid  # low=haiku-class, mid=sonnet-class, high=opus-class
max_turns: 20
skills:
  - sn-best-practices
  - sn-naming-conventions
---

You are a ServiceNow technical reviewer. When analyzing artifacts:

1. Check naming conventions (u_ prefix, scope prefix for scoped apps)
2. Identify upgrade-unsafe patterns (direct OOTB modifications)
3. Flag performance concerns (GlideRecord in client scripts, dot-walking depth)
4. Verify ACL coverage for custom tables
5. Check for hardcoded sys_ids or instance-specific values

Output findings as structured JSON with severity levels:
- CRITICAL: Upgrade blockers, security vulnerabilities
- HIGH: Performance issues, missing ACLs
- MEDIUM: Naming convention violations, code quality
- LOW: Style issues, documentation gaps
```

**Generator script (`scripts/sync-agents.py`):**
```python
#!/usr/bin/env python3
"""Generate per-CLI agent files from universal role definitions."""
import yaml, json, os
from pathlib import Path

MODEL_MAP = {
    "claude": {"low": "haiku", "mid": "sonnet", "high": "opus"},
    "codex":  {"low": "gpt-5-codex", "mid": "gpt-5-codex", "high": "gpt-5.4"},
    "gemini": {"low": "gemini-2.0-flash", "mid": "gemini-2.5-pro", "high": "gemini-2.5-pro"},
}

TOOL_MAP = {
    "claude": {"read_files": "Read", "search_files": "Grep, Glob",
               "run_commands": "Bash"},
    "codex":  {"read_files": "read", "search_files": "search",
               "run_commands": "shell"},
    "gemini": {"read_files": "read_file", "search_files": "search_files",
               "run_commands": "run_command"},
}

def parse_role(path: Path):
    text = path.read_text()
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm)
    return meta, body.strip()

def gen_claude(meta, body, out_dir):
    model = MODEL_MAP["claude"].get(meta.get("model_preference", "mid"), "sonnet")
    tools = []
    for t in meta.get("tools", []):
        if t.startswith("mcp:"):
            continue  # handled via mcpServers
        tools.extend(TOOL_MAP["claude"].get(t, t).split(", "))

    lines = ["---"]
    lines.append(f"name: {meta['role']}")
    lines.append(f"description: {meta['description']}")
    if tools:
        lines.append(f"tools: {', '.join(tools)}")
    lines.append(f"model: {model}")
    if meta.get("max_turns"):
        lines.append(f"maxTurns: {meta['max_turns']}")
    if meta.get("skills"):
        lines.append("skills:")
        for s in meta["skills"]:
            lines.append(f"  - {s}")
    lines.append("---")
    lines.append("")
    lines.append(body)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{meta['role']}.md").write_text("\n".join(lines))

def gen_codex(meta, body, out_dir):
    import toml as toml_lib
    model = MODEL_MAP["codex"].get(meta.get("model_preference", "mid"))
    agent = {
        "name": meta["role"],
        "description": meta["description"],
        "developer_instructions": body,
    }
    if model:
        agent["model"] = model

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{meta['role']}.toml").write_text(toml_lib.dumps(agent))

def gen_gemini(meta, body, out_dir):
    model = MODEL_MAP["gemini"].get(meta.get("model_preference", "mid"))
    tools = []
    for t in meta.get("tools", []):
        if t.startswith("mcp:"):
            server = t.split(":")[1]
            tools.append(f"mcp_{server}_*")
        else:
            tools.extend(TOOL_MAP["gemini"].get(t, t).split(", "))

    lines = ["---"]
    lines.append(f"name: {meta['role']}")
    lines.append(f"description: {meta['description']}")
    if tools:
        lines.append("tools:")
        for t in tools:
            lines.append(f"  - {t}")
    if model:
        lines.append(f"model: {model}")
    if meta.get("max_turns"):
        lines.append(f"max_turns: {meta['max_turns']}")
    lines.append("---")
    lines.append("")
    lines.append(body)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{meta['role']}.md").write_text("\n".join(lines))

if __name__ == "__main__":
    for role_file in Path("agent-roles").glob("*.md"):
        meta, body = parse_role(role_file)
        gen_claude(meta, body, Path(".claude/agents"))
        gen_codex(meta, body, Path(".codex/agents"))
        gen_gemini(meta, body, Path(".gemini/agents"))
    print("Agent files generated for all CLIs.")
```

### 8.5 System Prompt Sync

Maintain a shared core and generate per-CLI files:

**Shared core (`agent-roles/_system-prompt-core.md`):**
```markdown
## Project: ServiceNow Technical Assessment Hub

### Architecture
- Web app (control plane) + MCP tools (reasoning plane)
- Python backend with SQLModel, Flask routes
- Pipeline: 10-stage assessment with AI handlers

### Key Directories
- `tech-assessment-hub/src/` -- main application code
- `tech-assessment-hub/src/services/` -- scan and data pull executors
- `tech-assessment-hub/src/mcp/` -- MCP tools and prompts
- `tech-assessment-hub/tests/` -- pytest test suite (496+ tests)

### Working Agreements
- Always run tests after modifications: `./venv/bin/python -m pytest tests/`
- User-configurable values go in properties system, not hardcoded
- Check for existing reusable components before creating new ones
- Acknowledge refactor debt explicitly
```

```bash
#!/bin/bash
# scripts/sync-system-prompts.sh
CORE="agent-roles/_system-prompt-core.md"

# CLAUDE.md
cat > CLAUDE.md << 'HEADER'
# Claude Code Instructions
HEADER
cat "$CORE" >> CLAUDE.md

# AGENTS.md (Codex)
cat > AGENTS.md << 'HEADER'
# AGENTS.md
HEADER
cat "$CORE" >> AGENTS.md

# GEMINI.md
cat > GEMINI.md << 'HEADER'
# Gemini CLI Instructions
HEADER
cat "$CORE" >> GEMINI.md

echo "System prompts generated."
```

---

## 9. Best Practices for Writing Agent .md Files

### 9.1 Skill Files (SKILL.md)

**Structure template:**
```yaml
---
name: lowercase-hyphenated-name
description: >
  [WHAT] Verb-first description of capability.
  [WHEN] Use when [specific trigger conditions].
  [NOT] Do not use for [exclusions].
---

## Context
Brief background the agent needs (2-3 sentences max).

## Steps
1. First action (imperative voice)
2. Second action
3. Third action

## Output Format
Describe expected output structure.

## Edge Cases
- Handle [case A] by [action]
- If [condition], then [fallback]

## References
- See [detailed API docs](references/api.md) for complete field list
- Run `scripts/validate.sh` to check results
```

**Rules of thumb:**
1. **Front-load the description** -- first 250 chars matter most (truncation threshold)
2. **Include trigger keywords** -- words users naturally say that should activate this skill
3. **Keep SKILL.md under 500 lines** -- move details to `references/`
4. **Use imperative voice** -- "Check the table" not "The table should be checked"
5. **Specify output format** -- JSON, markdown, table -- be explicit
6. **Include negative triggers** -- "Do NOT use for" prevents false activation
7. **Test with all three CLIs** -- description matching differs slightly

### 9.2 Agent/Subagent Files

**Structure template:**
```yaml
---
name: agent-name
description: >
  [ROLE] One-line role summary.
  [DELEGATE] Use when [delegation triggers].
---

You are a [specific role]. Your expertise is [domain].

## Responsibilities
- [Primary responsibility]
- [Secondary responsibility]

## Approach
1. [First step in standard workflow]
2. [Second step]
3. [Third step]

## Constraints
- Never [prohibited action]
- Always [required action]
- Limit scope to [boundaries]

## Output
Return [format] with [required fields].
```

**Rules of thumb:**
1. **Single responsibility** -- one agent, one job
2. **Minimize tool access** -- principle of least privilege
3. **Set model thoughtfully** -- use cheap/fast models for read-only exploration
4. **Include constraints** -- explicitly state what the agent should NOT do
5. **Define output format** -- downstream consumers need predictable structure

### 9.3 System Prompt Files

**Rules of thumb:**
1. **Keep under 2000 lines** -- context budget matters
2. **Structure as reference, not narrative** -- agents scan, they don't read linearly
3. **Use headers for navigation** -- agents use these to find relevant sections
4. **Include concrete examples** -- "like this" beats "should be similar to"
5. **Put most important rules first** -- earlier content gets more attention

### 9.4 Scoping Tool Access

| Agent Role          | Claude Tools                    | Codex Sandbox      | Gemini Tools          |
|:--------------------|:--------------------------------|:--------------------|:----------------------|
| Read-only explorer  | `Read, Grep, Glob`             | `read-only`         | `read_file, search_files` |
| Code modifier       | (all, minus deploy)            | `workspace-write`   | `*` minus deploy      |
| Deploy operator     | `Bash(deploy*)` only           | Explicit permission | `run_command` only    |
| MCP-only agent      | `mcp__sn-tools__*`             | MCP servers only    | `mcp_sn-tools_*`     |

### 9.5 Chaining Agents

**Pattern: Pipeline chain (Claude Code)**
```yaml
---
name: full-assessment
description: Run complete ServiceNow assessment pipeline
context: fork
agent: general-purpose
disable-model-invocation: true
---

Execute the full assessment pipeline:

1. Use the sn-scanner skill to pull artifacts from the instance
2. Use the sn-table-analyzer skill to analyze table structures
3. Use the sn-reviewer skill to evaluate each artifact
4. Compile findings into a structured assessment report

For each step, invoke the appropriate skill and pass results forward.
```

**Pattern: Parallel dispatch (Codex)**
```toml
# .codex/agents/assessment-coordinator.toml
name = "assessment-coordinator"
description = "Coordinates parallel assessment of SN artifacts"
developer_instructions = """
You coordinate ServiceNow assessments by dispatching work to specialists:
1. Spawn sn-scanner agent to pull artifacts
2. Once artifacts are retrieved, spawn multiple sn-reviewer agents in parallel
3. Collect all findings and compile the final report
"""

[agents]
max_threads = 4
```

---

## 10. Concrete Universal Skill Example

Here is a complete example of one skill that works across all three CLIs.

### 10.1 The Canonical Skill

**`.agents/skills/sn-table-analyzer/SKILL.md`:**
```yaml
---
name: sn-table-analyzer
description: >
  Analyzes ServiceNow table structures including dictionary entries,
  field types, relationships via reference fields, and customization levels.
  Use when examining table schemas, reviewing table configurations,
  or identifying customization impact for upgrade assessments.
  Do not use for record-level data analysis or performance tuning.
allowed-tools: Read Grep Bash
metadata:
  author: ta-hub-team
  version: "1.0"
  domain: servicenow
---

## Context
ServiceNow tables have dictionary entries that define field structure.
Custom fields use the `u_` prefix. Reference fields create relationships
between tables. OOTB tables should not be directly modified.

## Steps

1. **Identify the target table** from user input or current context
2. **Pull dictionary entries** using the `sn-tools` MCP server:
   - Call `query_table` with table=`sys_dictionary` and query for the target table
   - Parse field names, types, reference targets, and attributes
3. **Classify fields**:
   - OOTB: no `u_` prefix, part of base platform
   - Custom: `u_` prefix or added by scoped app
   - Modified OOTB: standard name but non-default attributes
4. **Map relationships**:
   - For each reference field, identify the target table
   - Build a dependency graph of table relationships
5. **Assess customization level**:
   - Count custom vs OOTB fields
   - Calculate customization ratio
   - Identify high-risk modifications (OOTB field overrides)

## Output Format

Return JSON:
```json
{
  "table": "table_name",
  "field_count": { "total": 0, "custom": 0, "ootb": 0, "modified_ootb": 0 },
  "customization_ratio": 0.0,
  "relationships": [
    { "field": "field_name", "target_table": "table", "type": "reference" }
  ],
  "risks": [
    { "severity": "HIGH", "field": "field_name", "issue": "description" }
  ]
}
```

## Edge Cases
- If the table does not exist, report clearly and do not guess
- For extended tables, include parent table fields separately
- Handle tables with 500+ fields by summarizing rather than listing all
```

### 10.2 Symlink Setup

```bash
# Claude sees it
ln -sfn ../../.agents/skills/sn-table-analyzer .claude/skills/sn-table-analyzer

# Gemini sees it (also discovers .agents/skills/ natively)
ln -sfn ../../.agents/skills/sn-table-analyzer .gemini/skills/sn-table-analyzer

# Codex discovers .agents/skills/ natively -- no action needed
```

---

## 11. Architecture for TA Hub Multi-CLI Dispatch

### 11.1 Dispatch Flow

```
TA Hub Web App (Control Plane)
        |
        v
  Dispatch Router
  (selects CLI based on task type, availability, cost)
        |
        +---> Claude Code CLI
        |     - claude --agent sn-reviewer --mcp-config .mcp.json "Assess table X"
        |
        +---> Codex CLI
        |     - codex exec --agent sn-reviewer "Assess table X"
        |
        +---> Gemini CLI
              - gemini --agent sn-reviewer "Assess table X"
```

### 11.2 CLI Invocation Examples

**Claude Code:**
```bash
# Use a predefined subagent with MCP tools
claude --agent sn-reviewer \
       --mcp-config .mcp.json \
       --print \
       "Analyze the incident table for customization impact"

# Use inline agent definition for one-off tasks
claude --agents '{"scanner": {"description": "Scan SN artifacts", "prompt": "You scan...", "tools": ["Bash", "Read"]}}' \
       --print \
       "Scan the instance for all business rules on incident"

# Invoke a skill directly
claude --print "/sn-table-analyzer incident"
```

**Codex CLI:**
```bash
# Use a predefined agent
codex exec --agent sn-reviewer \
  "Analyze the incident table for customization impact"

# With specific approval policy
codex exec --approval-policy on-request \
  --agent sn-reviewer \
  "Analyze the incident table"
```

**Gemini CLI:**
```bash
# Use a predefined subagent
gemini --agent sn-reviewer \
  "Analyze the incident table for customization impact"

# Explicit subagent invocation
gemini "@sn-reviewer analyze the incident table for customization impact"
```

### 11.3 Python Dispatch Wrapper

```python
"""Universal CLI dispatcher for TA Hub assessments."""
import subprocess, json, os
from enum import Enum
from dataclasses import dataclass

class CLITool(Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"

@dataclass
class DispatchResult:
    tool: CLITool
    exit_code: int
    stdout: str
    stderr: str

def dispatch(
    tool: CLITool,
    prompt: str,
    agent: str | None = None,
    skill: str | None = None,
    cwd: str = ".",
) -> DispatchResult:
    """Dispatch a prompt to a specific CLI tool."""

    if tool == CLITool.CLAUDE:
        cmd = ["claude", "--print"]
        if agent:
            cmd.extend(["--agent", agent, "--mcp-config", ".mcp.json"])
        if skill:
            prompt = f"/{skill} {prompt}"
        cmd.append(prompt)

    elif tool == CLITool.CODEX:
        cmd = ["codex", "exec"]
        if agent:
            cmd.extend(["--agent", agent])
        cmd.append(prompt)

    elif tool == CLITool.GEMINI:
        cmd = ["gemini"]
        if agent:
            prompt = f"@{agent} {prompt}"
        cmd.append(prompt)

    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=300
    )
    return DispatchResult(
        tool=tool,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
```

### 11.4 Sync All Configs (Master Script)

```bash
#!/bin/bash
# scripts/sync-all.sh -- Generate all per-CLI configs from canonical sources

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Syncing skills ==="
bash scripts/sync-skills.sh

echo "=== Syncing agents ==="
python scripts/sync-agents.py

echo "=== Syncing MCP configs ==="
python scripts/sync-mcp.py

echo "=== Syncing system prompts ==="
bash scripts/sync-system-prompts.sh

echo "=== All configs synced ==="
echo "Verify with:"
echo "  claude agents       # List Claude subagents"
echo "  codex agents list   # List Codex agents"
echo "  gemini agents list  # List Gemini agents"
```

---

## Sources

- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
- [Claude Code Subagents Documentation](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Hooks Documentation](https://code.claude.com/docs/en/hooks)
- [Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp)
- [Agent Skills Open Standard Specification](https://agentskills.io/specification)
- [Agent Skills GitHub Repository](https://github.com/agentskills/agentskills)
- [OpenAI Codex CLI Configuration Reference](https://developers.openai.com/codex/config-reference)
- [OpenAI Codex CLI AGENTS.md Guide](https://developers.openai.com/codex/guides/agents-md)
- [OpenAI Codex CLI Subagents](https://developers.openai.com/codex/subagents)
- [OpenAI Codex CLI Agent Skills](https://developers.openai.com/codex/skills)
- [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/skills/)
- [Gemini CLI Subagents](https://geminicli.com/docs/core/subagents/)
- [Gemini CLI MCP Servers](https://geminicli.com/docs/tools/mcp-server/)
- [Gemini CLI Configuration Reference](https://geminicli.com/docs/reference/configuration/)
- [Gemini CLI System Prompt Override](https://geminicli.com/docs/cli/system-prompt/)
- [Gemini CLI GitHub Configuration](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/configuration.md)
- [Awesome Claude Code (Skills Collection)](https://github.com/hesreallyhim/awesome-claude-code)
- [Claude Code Customization Guide](https://alexop.dev/posts/claude-code-customization-guide-claudemd-skills-subagents/)
- [How to Create Agent Skills for Gemini CLI (Codelab)](https://codelabs.developers.google.com/gemini-cli/how-to-create-agent-skills-for-gemini-cli)
- [Google Developers Blog: Agent Skills](https://developers.googleblog.com/closing-the-knowledge-gap-with-agent-skills/)
- [MCP Config Guide (Multi-tool)](https://mcpplaygroundonline.com/blog/complete-guide-mcp-config-files-claude-desktop-cursor-lovable)
