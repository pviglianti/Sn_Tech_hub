# 04 — SnowCode CLI & Bundled Skills (53 Skills)

> **Scope**: `packages/snowcode/` (CLI, skills, session, MCP integration, agent framework)
> **Source**: takeover continuation audit (Codex)
> **Status**: DONE (takeover batch)

---

## 1. SnowCode Package Architecture

### Main entrypoint
- `packages/snowcode/src/index.ts` (5,604 bytes)
- CLI framework: `yargs`
- Command set includes: `mcp`, `auth`, `agent`, `memory`, `sessions`, `serve`, `run`, `config`, etc.

### Core package role
- SnowCode is the user-facing orchestration layer over:
  - config loading
  - session lifecycle
  - skill loading/injection
  - MCP client connection management
  - auth flows and runtime server management

---

## 2. Bundled Skills System

### Skills loading pipeline
- `packages/snowcode/src/config/config.ts` (40,344 bytes)
- `loadBundledSkills()` searches bundled locations and loads `SKILL.md` files.
- Confirmed bundled skill count: **53** (`packages/snowcode/src/bundled-skills/*/SKILL.md`).

### Skill schema and metadata
- Parsed into `Config.Skill` with fields including:
  - `name`, `description`, `content`
  - optional `tools` (recommended MCP tools to auto-enable)
  - `path` for resource resolution

### Runtime skill activation
- `packages/snowcode/src/tool/skill.ts`
  - validates requested skill
  - emits skill-matched event
  - auto-enables recommended tools via `ToolSearch.enableTools(...)`
  - injects `<skill ...> ... </skill>` content into model context

### Skill matching helpers
- `packages/snowcode/src/skill/index.ts`
  - semantic trigger extraction from skill descriptions
  - inject and injectAll helpers for context composition

---

## 3. Skill Structure Pattern (Representative)

### Representative skills reviewed
- `incident-management`
- `business-rule-patterns`
- `acl-security`
- `cmdb-patterns`
- `flow-designer`
- `ui-builder-patterns`
- `performance-analytics`
- `update-set-workflow`
- `virtual-agent`
- `rest-integration`

### Common structure observed
1. Frontmatter with activation description/triggers
2. Domain architecture section (tables/components/lifecycle)
3. ES5-safe implementation patterns
4. Tool integration section (recommended MCP tools)
5. Best-practice and anti-pattern guidance

### Approximate size profile
- Smallest observed skill footprint: ~790 tokens (`update-set-workflow`)
- Largest observed skill footprint: ~3,784 tokens (`problem-management`)
- Typical large domain skills cluster around ~2,800–3,300 tokens

---

## 4. Agent Framework

### Agent files
- `packages/snowcode/src/agent/agent.ts` (11,833 bytes)
- `packages/snowcode/src/agent/background.ts` (11,151 bytes)
- `packages/snowcode/src/agent/task-queue.ts` (15,972 bytes)

### Capabilities
- Agent mode model: `subagent | primary | all`
- Permission merging and shell allowlist policy handling
- Background agent execution with token budgets
- Queue-based lifecycle for asynchronous delegated tasks

### Integration implication
- SnowCode already has concrete scaffolding for delegated specialist workflows; we can adapt this for staged assessment agents (ingestion, grouping, deep-dive, presentation).

---

## 5. MCP Integration Layer

### File
- `packages/snowcode/src/mcp/index.ts` (20,962 bytes)

### Key behavior
- Supports both local and remote MCP servers:
  - local: stdio (`StdioClientTransport`)
  - remote: HTTP first, then SSE fallback
- Connection reliability:
  - retry manager
  - reconnect APIs (`reconnect`, `reconnectAll`, `ensureAllConnected`)
  - reload MCP config from disk without full restart (`reload()`)

### Management bridge relevance
- Combined with server routes (`/config`, `/mcp/reload`, `/mcp/:name/restart`, `/event`), this enables dynamic runtime configuration updates from a web control plane.

---

## 6. Session, Compaction, and Memory Integration

### System prompt assembly
- `packages/snowcode/src/session/system.ts` imports provider-specific prompt files and AGENTS/rules context.
- Skill availability is injected into system context as actionable list.

### Compaction path
- `packages/snowcode/src/session/compaction.ts`:
  - estimates overflow
  - summarizes tool outputs
  - compacts conversation state
  - reconnects MCP servers after compaction (`MCP.ensureAllConnected()`)

### Practical consequence
- Session resilience is strong for long-running multi-agent workflows; pattern is reusable for our file-backed context checkpoints.

---

## 7. Complete Skill Inventory (53 Skills)

| Skill | Domain | Size (bytes) | Approx Tokens | Key Topics |
|-------|--------|--------------|---------------|------------|
| `acl-security` | acl security | 6574 | 1643 | ACL Evaluation Order;ACL Types Creating ACLs via MCP;Common ACL Patterns |
| `agent-workspace` | agent workspace | 13489 | 3372 | Workspace Architecture;Key Tables Workspace Configuration (ES5);Contextual Side Panel (ES5) |
| `approval-workflows` | approval workflows | 11367 | 2841 | Approval Architecture;Key Tables Approval Rules (ES5);Managing Approvals (ES5) |
| `asset-management` | asset management | 12001 | 3000 | Asset Architecture;Key Tables Hardware Assets (ES5);Software Licenses (ES5) |
| `atf-testing` | atf testing | 10608 | 2652 | ATF Architecture;Test Step Types Creating Tests;Server-Side Script Steps |
| `business-rule-patterns` | business rule patterns | 5561 | 1390 | When to Use Each Type;Available Objects Before Business Rules;After Business Rules |
| `catalog-items` | catalog items | 9349 | 2337 | Catalog Components;Catalog Item Structure Variable Types;Creating Catalog Variables |
| `change-management` | change management | 12465 | 3116 | Change Types;Change Request Structure Creating Changes;Change Tasks |
| `client-scripts` | client scripts | 9048 | 2262 | Client Script Types;The g_form API Common Patterns;GlideAjax Pattern (Server Communication) |
| `cmdb-patterns` | cmdb patterns | 11583 | 2895 | CMDB Architecture;Creating Configuration Items CI Relationships;Impact Analysis |
| `code-review` | code review | 6200 | 1550 | 1. ES5 Compliance (CRITICAL);2. Security Issues 3. Performance Issues;4. Code Quality Issues |
| `csm-patterns` | csm patterns | 12055 | 3013 | CSM Architecture;Key Tables Customer Accounts (ES5);Customer Cases (ES5) |
| `data-policies` | data policies | 11171 | 2792 | Architecture;Key Tables Dictionary Management (ES5);Dictionary Overrides (ES5) |
| `discovery-patterns` | discovery patterns | 10676 | 2669 | Discovery Architecture;Key Tables Discovery Schedules (ES5);Discovery Credentials (ES5) |
| `document-management` | document management | 12236 | 3059 | Document Architecture;Key Tables Attachments (ES5);Document Templates (ES5) |
| `domain-separation` | domain separation | 10196 | 2549 | Domain Architecture;Key Tables Domain Configuration (ES5);User Domain Membership (ES5) |
| `email-notifications` | email notifications | 10693 | 2673 | Notification Components;Creating Notifications Email Templates;Email Scripts |
| `es5-compliance` | es5 compliance | 3181 | 795 | Forbidden Syntax (WILL CAUSE SyntaxError);Common Patterns Automatic Validation;Exception: Client Scripts |
| `event-management` | event management | 11987 | 2996 | Event Flow;Key Tables Events (ES5);Event Rules (ES5) |
| `field-service` | field service | 11798 | 2949 | FSM Architecture;Key Tables Work Orders (ES5);Technician Management (ES5) |
| `flow-designer` | flow designer | 7603 | 1900 | Flow Designer Components;Flow Triggers Flow Best Practices;Custom Actions (Scripts) |
| `gliderecord-patterns` | gliderecord patterns | 5038 | 1259 | Basic Query Patterns;Encoded Queries (Faster) Performance Tips;CRUD Operations |
| `grc-compliance` | grc compliance | 11983 | 2995 | GRC Architecture;Key Tables Policies (ES5);Controls (ES5) |
| `hr-service-delivery` | hr service delivery | 12938 | 3234 | HRSD Architecture;Key Tables HR Cases (ES5);Lifecycle Events (ES5) |
| `import-export` | import export | 12168 | 3042 | Import/Export Architecture;Key Tables Data Import (ES5);Data Export (ES5) |
| `incident-management` | incident management | 13566 | 3391 | Incident Lifecycle;Key Tables Creating Incidents (ES5);Incident Assignment (ES5) |
| `instance-security` | instance security | 11492 | 2873 | Security Layers;Key Tables Authentication Security (ES5);MFA Implementation (ES5) |
| `integration-hub` | integration hub | 10703 | 2675 | IntegrationHub Architecture;Key Tables Connection & Credential Aliases (ES5);Spoke Development (ES5) |
| `knowledge-management` | knowledge management | 12041 | 3010 | Knowledge Architecture;Key Tables Creating Articles (ES5);Article Workflow |
| `mcp-tool-discovery` | mcp tool discovery | 6845 | 1711 | Quick Start;Tool Categories Always-Available Tools;How tool_search Works |
| `mid-server` | mid server | 12163 | 3040 | MID Server Architecture;Key Tables ECC Queue Communication (ES5);MID Server Scripts (ES5) |
| `mobile-development` | mobile development | 11824 | 2956 | Mobile Architecture;Key Tables Mobile App Configuration (ES5);Card Builder (ES5) |
| `notification-events` | notification events | 10476 | 2619 | Event Architecture;Key Tables Creating Events (ES5);Script Actions (ES5) |
| `performance-analytics` | performance analytics | 10623 | 2655 | PA Architecture;Indicators Breakdowns;Thresholds |
| `predictive-intelligence` | predictive intelligence | 11197 | 2799 | PI Capabilities;Key Tables Classification (ES5);Similarity (ES5) |
| `problem-management` | problem management | 15137 | 3784 | Problem Lifecycle;Key Tables Creating Problems (ES5);Root Cause Analysis (ES5) |
| `reporting-dashboards` | reporting dashboards | 10417 | 2604 | Report Types;Creating Reports Dashboards;Scheduled Reports |
| `request-management` | request management | 11132 | 2783 | Request Hierarchy;Key Tables Request Items (ES5);Fulfillment Tasks (ES5) |
| `rest-integration` | rest integration | 6283 | 1570 | Outbound REST (Calling External APIs);Authentication Methods Error Handling;Response Handling |
| `scheduled-jobs` | scheduled jobs | 11028 | 2757 | Job Types;Scheduled Script Execution (ES5) Schedule Configuration;Job Monitoring |
| `scoped-apps` | scoped apps | 7032 | 1758 | Why Use Scoped Apps?;Creating a Scoped Application Scope Naming Convention;Table Naming |
| `script-include-patterns` | script include patterns | 10310 | 2577 | Script Include Types;Standard Script Include (ES5) Client Callable Script Include (ES5);Client-Side GlideAjax Call (ES5) |
| `security-operations` | security operations | 11496 | 2874 | SecOps Architecture;Key Tables Security Incidents (ES5);Vulnerability Management (ES5) |
| `sla-management` | sla management | 11106 | 2776 | SLA Components;SLA Flow SLA Definition (ES5);Task SLA Operations (ES5) |
| `snow-flow-commands` | snow flow commands | 5142 | 1285 | Core Commands;SPARC Modes Agent Management;Swarm Coordination |
| `transform-maps` | transform maps | 12784 | 3196 | Import Architecture;Key Components Data Sources;Import Set Tables |
| `ui-actions-policies` | ui actions policies | 11013 | 2753 | UI Actions;UI Policies Creating via Scripts (ES5);MCP Tool Integration |
| `ui-builder-patterns` | ui builder patterns | 10166 | 2541 | UI Builder Architecture;Page Structure Data Brokers;Client State Parameters |
| `update-set-workflow` | update set workflow | 3161 | 790 | Before ANY Development;Update Set Naming Conventions Update Set Lifecycle;What Gets Tracked |
| `vendor-management` | vendor management | 11626 | 2906 | Vendor Architecture;Key Tables Vendors (ES5);Contracts (ES5) |
| `virtual-agent` | virtual agent | 11343 | 2835 | Virtual Agent Architecture;Topics Topic Blocks;NLU Training |
| `widget-coherence` | widget coherence | 4291 | 1072 | The Three-Way Contract;Data Flow Patterns Validation Checklist;Common Failures |
| `workspace-builder` | workspace builder | 11165 | 2791 | AES Architecture;Key Tables Application Development (ES5);Workspace Configuration (ES5) |

---

## 8. Knowledge Extraction Value

### Highest-value encoded knowledge
1. ServiceNow implementation patterns by domain (ITSM, CMDB, security, UIB, integration, automation)
2. Guardrails (ES5 compliance, update set discipline, ACL/security practices)
3. Reusable migration heuristics and anti-patterns that can seed our `_Global_Knowledge/` and per-project context packs

### Recommended extraction approach
- Keep skills as modular markdown knowledge packs.
- Tag each with:
  - domain
  - risk level
  - read/write relevance
  - applicable assessment pipeline stages

---

## 9. Integration Points for Our Project

### Extract now
1. Skill loading/discovery pattern from `config.ts`
2. Runtime tool auto-enable behavior from `tool/skill.ts`
3. Agent background queue/token-budget concepts from `agent/background.ts` + `agent/task-queue.ts`
4. MCP reconnect/reload robustness from `mcp/index.ts`

### Adapt before shipping
1. Replace SnowCode-centric prompt guidance with our project-folder memory guidance
2. Re-scope skill triggers to assessment tasks (not generic SN development)
3. Bind skill recommendations to our MCP tool IDs and role model

### Defer
1. Full parity with SnowCode CLI UX
2. Complex multi-provider prompt branching not needed for MVP

---

## 10. Takeover Notes (for reconciliation)

- This document completes the previously pending CLI + skills deep dive.
- It is paired with:
  - `02_core_mcp_tools.md`
  - `07_ui_packages.md`
  - `08_extensibility_audit.md`
  - `09_tool_mapping_matrix.md`
  - `10_integration_plan.md`

