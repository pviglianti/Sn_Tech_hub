# 01 — Snow-Flow Repository Overview

> **Scope**: Repo structure, monorepo config, package inventory, build system, key metrics
> **Source**: `/Users/pviglianti/Library/CloudStorage/OneDrive-BridgeViewPartners/Snow_flow WS/snow-flow_pv/`

---

## Identity

| Field | Value |
|-------|-------|
| Name | Snow-Flow (fork: snow-flow_pv) |
| Version | 9.0.0 |
| License | Elastic-2.0 |
| Language | TypeScript (core), Go (TUI) |
| Runtime | Bun 1.3.0 / Node.js |
| Package Manager | Bun (with bun.lock) |
| Build System | Turbo (monorepo pipeline) |
| Repo Size | 440MB |
| Total Files | 3,120 |
| Total Directories | 413 |

---

## Monorepo Structure

```
snow-flow_pv/
├── packages/           ← 13 packages (core, sdk, cli, snowcode, ui, web, console, desktop, tui, plugin, identity, function, script, slack)
├── apps/               ← 3 apps (website, health-api, status-page)
├── scripts/            ← 25 utility scripts (setup, config gen, cleanup, testing)
├── docs/               ← Auth flow, skills plan, tool inventory, API docs
├── templates/          ← Skill templates (base-agents.txt + email-notifications example)
├── tests/              ← Memory leak + SDK subagent tests
├── bin/                ← Executable entry points
├── src/                ← Root source (minimal)
├── examples/           ← Example projects
└── [root configs]      ← package.json, turbo.json, .mcp.json.template, .env.example, etc.
```

---

## Package Inventory

### By Size and Importance

| Package | Size | Files | Language | Purpose | Relevance to Us |
|---------|------|-------|----------|---------|----------------|
| **core** | 8.6MB | 800 | TS | MCP tools (410+), agent framework, auth, server, config, memory | **CRITICAL** — primary extraction target |
| **snowcode** | 5.6MB | 291 | TS | CLI, 53 bundled skills, agent, session, storage | **HIGH** — skills, agent framework, config patterns |
| **tui** | 103MB | 142 | Go | Terminal UI (Bubble Tea) | LOW — not relevant (we use web UI) |
| **console** | 43MB | 262 | TS | Multi-tenant web console (billing, auth, workspace) | MEDIUM — SaaS patterns, but our UI is different |
| **desktop** | 5.6MB | 1,127 | TS/TSX | Desktop app (React/Solid) | LOW — we have our own UI |
| **web** | 18MB | 84 | Astro | Documentation site | LOW — docs only |
| **sdk** | 900KB | 104 | TS/Go | SDKs (Go, JS, Stainless) | MEDIUM — client SDK patterns |
| **ui** | 1.2MB | 54 | TS/TSX | UI component library (Tailwind/Solid) | LOW — we use Jinja2 |
| **plugin** | 40KB | 9 | TS | Plugin framework | MEDIUM — extensibility patterns |
| **identity** | 40KB | 10 | TS | Identity management | LOW — we handle auth differently |
| **slack** | 32KB | 7 | TS | Slack integration | LOW — not in our scope |
| **function** | 24KB | 4 | TS | Cloud functions | LOW — not in our scope |
| **script** | 12KB | 3 | TS | Utility scripts | LOW |

### Extraction Priority

**Must Extract** (core value for our project):
1. `packages/core/src/mcp/` — All 410+ ServiceNow MCP tools
2. `packages/core/src/auth/` — ServiceNow OAuth patterns
3. `packages/snowcode/src/bundled-skills/` — 53 domain knowledge skill definitions
4. `packages/core/src/mcp/servicenow-mcp-unified/shared/` — SN client wrapper, error handling

**Should Extract** (patterns and architecture):
5. `packages/core/src/agent/` — Agent framework patterns
6. `packages/core/src/config/` — Configuration management
7. `packages/core/src/memory/` — State/memory management
8. `packages/core/src/server/` — HTTP server + transport patterns
9. `scripts/` — Setup, config generation, MCP management scripts

**Reference Only** (understand but don't port):
10. `packages/tui/` — Go TUI (different tech stack)
11. `packages/console/` — SaaS console (our UI is different)
12. `packages/desktop/` — Desktop app (we use web)
13. `apps/` — Website and status page

---

## MCP Tool Categories (84 categories, 410+ tools)

### By ServiceNow Domain

**ITSM / Core Platform**:
- business-rules, script-includes, ui-actions, ui-policies, ui-builder
- scheduled-jobs, schedules, events, notifications
- forms, lists, menus, templates, variables
- data-management, data-policies, system-properties
- access-control, security, user-admin

**ITSM Processes**:
- catalog, change, approvals, sla, workflow
- queues, journals, email

**CMDB / Asset**:
- cmdb, asset, procurement

**Development**:
- development, deployment, update-sets, plugins
- local-sync, attachments

**Analytics / Reporting**:
- reporting, dashboards, performance-analytics, metrics
- aggregators, calculators

**Advanced / AI**:
- ai-ml-MIGRATED, machine-learning-MIGRATED, predictive-intelligence-MIGRATED
- virtual-agent, automation

**Service Management Extensions**:
- csm, hr, hr-csm, knowledge, service-portal, workspace
- mobile, project

**Utilities**:
- adapters, addons, advanced, connectors, converters
- decoders, encoders, extensions, filters, formatters
- generators, handlers, helpers, import-export, integration
- mappers, meta, operations, parsers, processors
- transformers, utilities, validators

---

## 53 Bundled Skills (SnowCode)

Skills are domain-knowledge modules that contain ServiceNow best practices, patterns, and analysis capabilities:

| # | Skill | Domain |
|---|-------|--------|
| 1 | acl-security | Security |
| 2 | agent-workspace | UI |
| 3 | approval-workflows | Process |
| 4 | asset-management | CMDB |
| 5 | atf-testing | Quality |
| 6 | business-rule-patterns | Development |
| 7 | catalog-items | Service Catalog |
| 8 | change-management | ITSM |
| 9 | client-scripts | Development |
| 10 | cmdb-patterns | CMDB |
| 11 | code-review | Quality |
| 12 | csm-patterns | CSM |
| 13 | data-policies | Data |
| 14 | discovery-patterns | CMDB |
| 15 | document-management | Content |
| 16 | domain-separation | Platform |
| 17 | email-notifications | Comms |
| 18 | es5-compliance | Development |
| 19 | event-management | Events |
| 20 | field-service | FSM |
| 21 | flow-designer | Automation |
| 22 | gliderecord-patterns | Development |
| 23 | grc-compliance | GRC |
| 24 | hr-service-delivery | HR |
| 25 | import-export | Data |
| 26 | incident-management | ITSM |
| 27 | instance-security | Security |
| 28 | integration-hub | Integration |
| 29 | knowledge-management | KM |
| 30 | mcp-tool-discovery | Platform |
| 31 | mid-server | Infrastructure |
| 32 | mobile-development | Mobile |
| 33 | notification-events | Comms |
| 34 | performance-analytics | Analytics |
| 35 | predictive-intelligence | AI |
| 36 | problem-management | ITSM |
| 37 | reporting-dashboards | Analytics |
| 38 | request-management | ITSM |
| 39 | rest-integration | Integration |
| 40 | scheduled-jobs | Automation |
| 41 | scoped-apps | Development |
| 42 | script-include-patterns | Development |
| 43 | security-operations | Security |
| 44 | sla-management | ITSM |
| 45 | snow-flow-commands | Platform |
| 46 | transform-maps | Data |
| 47 | ui-actions-policies | UI |
| 48 | ui-builder-patterns | UI |
| 49 | update-set-workflow | Development |
| 50 | vendor-management | Procurement |
| 51 | virtual-agent | AI |
| 52 | widget-coherence | UI |
| 53 | workspace-builder | UI |

---

## Key Technology Decisions

| Area | Snow-Flow Choice | Our Equivalent | Gap |
|------|-----------------|----------------|-----|
| Language | TypeScript | Python | Port or hybrid? |
| Runtime | Bun/Node | Python/uvicorn | Different stack |
| Web Framework | Hono/Solid.js | FastAPI/Jinja2 | Different stack |
| DB | Drizzle ORM + SQL | SQLModel/SQLAlchemy + SQLite | Different ORM |
| MCP Transport | stdio + HTTP | HTTP (embedded in FastAPI) | Need to align |
| Auth | OAuth 2.0 + PKCE | Basic Auth (MVP) | We're behind |
| Build | Turbo monorepo | Single Python package | Simpler |
| AI SDK | ai (v6.0.16) + multi-provider | Direct API calls | Need to add |
| TUI | Go + Bubble Tea | N/A | Not needed |

---

## What Snow-Flow Has That We Need

1. **410+ MCP tools** — ServiceNow API interactions already built
2. **53 domain knowledge skills** — Best practices, patterns, anti-patterns
3. **OAuth flow** — ServiceNow OAuth 2.0 with PKCE
4. **Tool registry** — Auto-discovery, lazy loading, domain filtering
5. **Error handling** — Standardized SN error codes and recovery
6. **Pagination** — Batched API calls with rate limiting
7. **Config template** — .mcp.json.template → .mcp.json expansion
8. **Setup scripts** — MCP server management, config generation
9. **Auth flow testing** — End-to-end auth verification
10. **Multi-provider AI** — Support for 75+ LLM providers

## What Snow-Flow Doesn't Have (Our Additions)

1. **SQLite local DB** — Resolved knowledge store
2. **5-stage assessment pipeline** — Ingestion → Pre-processing → Manifest → Deep Dive → Presentation
3. **Feature grouping** — AI-driven customization clustering
4. **Technical debt scoring** — Rubric-based assessment
5. **CSDM 5 alignment** — Service mapping and classification
6. **Context memory architecture** — File-backed unlimited context per project
7. **Installer wizard** — First-run guided setup
8. **Management console** — Web-based instance/LLM/run management
9. **Revert/deactivate automation** — Safe mutation operations
10. **Assessment workflow** — Create, run, review, export assessments
