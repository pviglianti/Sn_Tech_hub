# Snow-Flow Deep Analysis — Master Index

> **Purpose**: Comprehensive audit of the snow-flow_pv codebase for integration into our ServiceNow Assessment Platform.
> **Created**: 2026-02-06
> **Status**: COMPLETE (takeover reconciled batch)
> **Takeover Note**: Completed by Codex in continuation pass after prior-agent context exhaustion; docs include explicit reconciliation notes.

## Analysis Documents

| # | Document | Scope | Status |
|---|----------|-------|--------|
| 01 | [01_repo_overview.md](01_repo_overview.md) | Repo structure, monorepo config, build system, dependencies | DONE |
| 02 | [02_core_mcp_tools.md](02_core_mcp_tools.md) | packages/core/src/mcp/ — 410+ tools, registry, shared utils | DONE |
| 03 | [03_core_infrastructure.md](03_core_infrastructure.md) | packages/core/src/ — auth, agent, server, config, memory, storage | DONE |
| 04 | [04_snowcode_cli_skills.md](04_snowcode_cli_skills.md) | packages/snowcode/ — CLI, 53 bundled skills, agent framework | DONE |
| 05 | [05_auth_and_transport.md](05_auth_and_transport.md) | Auth providers, OAuth flow, HTTP/SSE transport, session management | DONE |
| 06 | [06_scripts_and_setup.md](06_scripts_and_setup.md) | scripts/, templates/, OS deps, wizard prep | DONE |
| 07 | [07_ui_packages.md](07_ui_packages.md) | console, desktop, web, tui — UI architecture overview | DONE |
| 08 | [08_extensibility_audit.md](08_extensibility_audit.md) | 5 specific audit points (folder paths, SSE bridge, SQLite, wizard, tokens) | DONE |
| 09 | [09_tool_mapping_matrix.md](09_tool_mapping_matrix.md) | Keep/adapt/discard matrix for all tool categories | DONE |
| 10 | [10_integration_plan.md](10_integration_plan.md) | Final synthesis — what to take, how to restructure, implementation order | DONE |

## Key Paths
- **Snow-Flow Repo**: `/Users/pviglianti/Library/CloudStorage/OneDrive-BridgeViewPartners/Snow_flow WS/snow-flow_pv/`
- **Our Project**: `/Users/pviglianti/Documents/Claude Unlimited Context/servicenow_global_tech_assessment_mcp/`
- **Our App**: `/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub/`

## Quick Stats
- Total files: 3,120 | Directories: 413 | Repo size: 440MB
- MCP tool categories: 84 | Tools: 410+ | Bundled skills: 53
- Language: TypeScript (core), Go (TUI) | Runtime: Bun/Node
- Monorepo: Bun workspaces + Turbo build

## Audit Objectives (from user)
1. **Folder Selection Logic** — Where to inject user-selected paths for context memory
2. **Management Service Bridge** — How MCP receives commands; SSE/HTTP transport for Web App push
3. **SQLite Tooling** — Pattern for sqlite_query tool to read Web App's DB
4. **Wizard Preparation** — OS deps, env vars, setup.sh/exe requirements
5. **Token Efficiency Audit** — Existing prompts, context-awareness, refactor recommendations
