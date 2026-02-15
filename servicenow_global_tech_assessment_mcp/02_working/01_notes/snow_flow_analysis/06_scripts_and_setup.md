# 06 — Scripts, Documentation & Setup

> **Scope**: `scripts/` (21 utility scripts), `docs/`, `templates/`, `tests/`, `README.md`, `AGENTS.md`, `AUTH-FLOW.md`
> **Source**: Agent a6486b3 analysis of snow-flow_pv scripts, docs, and templates
> **Status**: DONE

---

## 1. Scripts Overview (21 Utility Scripts)

### 1.1 Configuration & Setup

| Script | Purpose | Key Details |
|--------|---------|-------------|
| `setup-mcp.js` | Generate `.mcp.json` from template | Replaces `{{PROJECT_ROOT}}`, `{{SNOW_INSTANCE}}`, etc.; makes 11 MCP server files executable; validates env vars |
| `generate-mcp-config.js` | Generate `.mcp.json` from `.env` | Reads actual `.env` file; processes template as JSON; reports server count |
| `postinstall.js` | Post-npm-install setup | Fixes binary permissions for 5 platforms (macOS arm64/x64, Linux arm64/x64, Windows x64); creates `~/.snow-flow`; Docker/container-safe |

### 1.2 MCP Server Lifecycle

| Script | Purpose | Key Details |
|--------|---------|-------------|
| `start-mcp-proper.js` | Start MCP servers | Uses MCPServerManager with singleton protection; emoji status indicators; graceful SIGINT shutdown |
| `reset-mcp-servers.js` | Kill + restart servers | 4-step: kill processes → clear cache → verify clean → optional restart; platform-specific (Windows/Unix) |
| `cleanup-mcp-servers.js` | Prevent duplicate servers | Creates singleton lock at `~/.claude/mcp-singleton.lock`; checks stale locks; reports memory usage |
| `safe-mcp-cleanup.js` | Interactive cleanup | Menu: kill all / kill duplicates / kill high-memory (>100MB) / cancel; groups by type |

### 1.3 Diagnostics & Testing

| Script | Purpose | Key Details |
|--------|---------|-------------|
| `diagnose-mcp.js` | Comprehensive diagnostic | 6-step: installation → global config → local config → startup test → version → processes |
| `test-auth-flow.js` | Auth verification | 4-stage: auth.json → env vars → .mcp.json → token cache |
| `test-auth-location-fix.js` | Fix auth file location | Detects incorrect path (snowcode vs snow-code); auto-moves + symlink |
| `test-mcp-manual.js` | Manual server startup test | Spawns servicenow-unified; monitors stdout/stderr; 5-second timeout |

### 1.4 Dependency Management

| Script | Purpose | Key Details |
|--------|---------|-------------|
| `update-dependencies.js` | Update all deps | Reads package.json; npm cache clean; reinstall; rebuild native modules; patch-package |
| `update-snow-code.js` | Install/update snow-code | Exports `updateSnowCode(verbose)` and `forceUpdateToLatest()`; version comparison |
| `check-binary-updates.js` | Check binary updates | Checks 5 platform packages against npm registry; `--auto-update` flag |
| `check-npm-version.js` | Prevent version collisions | Queries npm registry; auto-bumps patch; updates `src/version.ts` |
| `sync-snow-code-version.js` | Sync peer dependency | Sets peerDependencies to `*` before publish |

### 1.5 Code Generation

| Script | Purpose | Key Details |
|--------|---------|-------------|
| `classify-all-tools.ts` | Auto-classify 410+ tools | Pattern matching: 17 READ patterns, 37 WRITE patterns; confidence levels; role assignment |
| `classify-edge-cases.ts` | Handle ambiguous tools | Secondary classification for unmatched tools |
| `generate-mcp-docs.ts` | Generate tool documentation | Scans tools; extracts metadata; outputs JSON + per-category Markdown; bilingual (EN/NL) |

---

## 2. Key Documentation Files

### 2.1 AGENTS.md (31KB — AI Agent Instructions)

**Critical file** — defines how AI agents interact with Snow-Flow tools.

**Key sections**:
1. **Identity & Mission**: AI agent within Snow-Flow, 410+ MCP tools
2. **Lazy Tool Loading**: Tools NOT all available at startup — must discover first
3. **Silent Discovery**: NEVER tell user "I'm discovering tools" — just do it
4. **Tool Categories**: Core, Development, UI, ITSM, Enterprise
5. **Always-Available Tools**: Activity tracking (requires real Update Set sys_id)
6. **Mandatory Instruction Hierarchy**: User instructions > AGENTS.md > .claude/ files > defaults
7. **ES5 Compliance**: `var` not `const/let`, no arrow functions, no template literals, no async/await
8. **Update Set Workflow**: Create first, track all changes, capture real sys_ids
9. **Widget Coherence**: HTML/client/server contract enforcement
10. **Application Scope Management**: All artifacts belong to scope

**Token optimization insight**: This 31KB file is loaded into EVERY conversation. Snow-flow uses lazy loading to reduce tool descriptions from ~71K to ~2K tokens at startup.

### 2.2 AUTH-FLOW.md (Authentication Reference)

**3-Tier Auth Priority**:
1. Environment variables (`SERVICENOW_*` preferred, `SNOW_*` fallback)
2. `auth.json` file (`~/.local/share/snow-code/auth.json`)
3. Unauthenticated mode (last resort)

**Configuration Methods**:
- Option 1: `/auth` command in TUI (recommended)
- Option 2: Environment variables
- Option 3: Project-level `.mcp.json` credentials

**Troubleshooting**: 5 common issues documented with fixes

### 2.3 Tool API Documentation (`docs/api/tools/`)

**379 tools documented** — 170 read, 209 write — across 15 categories:

| Category | Read | Write | Total |
|----------|------|-------|-------|
| Platform Development | - | - | 78 |
| Automation | - | - | 57 |
| Advanced AI/ML | - | - | 52 |
| ITSM | 17 | 28 | 45 |
| Integration | - | - | 33 |
| Core Operations | 14 | 16 | 30 |
| UI Frameworks | - | - | 19 |
| Security | - | - | 18 |
| CMDB | 10 | 4 | 14 |
| Reporting | - | - | 10 |
| UI Builder | - | - | 9 |
| Asset Management | - | - | 8 |
| Performance Analytics | - | - | 3 |
| ML Analytics | - | - | 2 |
| Workspace | - | - | 1 |

**Per-tool documentation format**:
- Tool name and description
- Permission level (read/write)
- Complexity (beginner/intermediate/advanced)
- Frequency (high/medium/low)
- Allowed roles
- JavaScript example usage

---

## 3. Tests

### 3.1 Memory Leak Test (`memory-leak-test.ts`)
- **BoundedCollections**: BoundedMap (max 100), BoundedSet (max 50), BoundedArray (max 25)
- **TimerRegistry**: Register/clear intervals and timeouts; verify no leaks
- **Memory Growth**: 1-minute test; sample every 5s; pass if growth < 100MB

### 3.2 Subagent Communication Test (`subagent-communication-test.js`)
- Tests multi-agent orchestration (orchestrator + 4 specialists)
- Validates: agent definitions, delegation patterns, specialist capabilities, SN domain expertise, communication protocols
- **Agents**: orchestrator, deployment-specialist, risk-assessor, solution-architect, validator

---

## 4. Templates (`templates/`)

- `base-agents.txt` — Base agent instructions template
- `email-notifications/` — Example skill template for email notification patterns

---

## 5. Wizard Preparation Findings

### OS Dependencies Required
- **Node.js** (for MCP server — `node` command)
- **Bun** 1.3.0+ (for package management, optional if using npm)
- **npm** (fallback package manager)
- **Git** (for version control integration)
- **Platform-specific binaries**: 5 platform packages (darwin-arm64, darwin-x64, linux-arm64, linux-x64, windows-x64)

### Environment Variables for Setup
**Minimum required**:
- `SNOW_INSTANCE` — ServiceNow instance URL
- `SNOW_CLIENT_ID` — OAuth client ID
- `SNOW_CLIENT_SECRET` — OAuth client secret
- At least ONE LLM provider API key or local model URL

**Optional but recommended**:
- `DEFAULT_LLM_PROVIDER` — Prevents model confusion
- `DEFAULT_MODEL` — Prevents context window issues
- `LOG_LEVEL` — For debugging
- `ENABLE_MEMORY_SYSTEM` — For persistent context

### Setup Flow (from `postinstall.js` pattern)
1. Fix binary permissions (chmod 755)
2. Create global config directory (`~/.snow-flow` or `~/.config/snow-code`)
3. Generate `.mcp.json` from template
4. Validate environment variables
5. Test auth configuration
6. Start MCP servers

### Config Files Created During Setup
- `.mcp.json` — MCP server configuration (from template)
- `~/.local/share/snow-code/auth.json` — OAuth credentials
- `~/.snow-flow/token-cache.json` — Token cache
- `~/.claude/mcp-singleton.lock` — Singleton protection

---

## 6. Token Efficiency Findings

### Current Token Usage
- **AGENTS.md**: ~31KB loaded into every conversation (≈8K tokens)
- **All tool descriptions**: ~71K tokens if fully expanded
- **After lazy loading**: ~2K tokens at startup (97% reduction)

### Lazy Loading Pattern
```
Startup: Only load tool category names + descriptions
On use: Load specific tool's full schema and examples
Result: 71K → 2K tokens for initial context
```

### Silent Discovery Pattern (from AGENTS.md)
- Agent NEVER says "I'm discovering tools" or "Let me find the right tool"
- Just activates the tool and uses it
- Reduces output tokens and improves UX

### Env Var Controls
- `SNOW_LAZY_TOOLS=true` — Enable lazy tool loading
- `SNOW_TOOL_DOMAINS=itsm,cmdb,development` — Limit loaded categories
- `ENABLE_MEMORY_SYSTEM=true` — Persistent context across sessions

### Recommendations for Our Project
1. **Adopt lazy loading** — Only load tool schemas when needed
2. **Domain filtering** — Let user select relevant domains (ITSM, CMDB, etc.)
3. **Progressive skill loading** — 3-tier: metadata → instructions → resources
4. **Context-aware prompts** — Use `_Context/Projects/{Client}/` to customize prompts per assessment
5. **Token budget tracking** — Monitor actual usage vs budget per stage of pipeline

---

## 7. Integration Points

### Scripts to Extract/Adapt

| Script | Action | Reason |
|--------|--------|--------|
| `setup-mcp.js` | **Adapt** | Template-based config generation — rewrite for our wizard |
| `generate-mcp-config.js` | **Adapt** | .env-based config — integrate into wizard Step 2 |
| `diagnose-mcp.js` | **Extract** | Diagnostic pattern — valuable for troubleshooting |
| `test-auth-flow.js` | **Extract** | Auth verification — reuse for our "Test Connection" button |
| `classify-all-tools.ts` | **Reference** | Tool classification patterns — useful for our tool registry |
| `generate-mcp-docs.ts` | **Reference** | Doc generation — could generate our tool inventory |
| Singleton/cleanup scripts | **Adapt** | Server lifecycle — need similar for our MCP process management |

### Documentation to Leverage
- **AGENTS.md** — Adapt for our agent's system prompt (remove snow-flow specifics, add assessment pipeline instructions)
- **AUTH-FLOW.md** — Reference for our auth documentation
- **Tool API docs** — Reference for our tool inventory and mapping matrix
