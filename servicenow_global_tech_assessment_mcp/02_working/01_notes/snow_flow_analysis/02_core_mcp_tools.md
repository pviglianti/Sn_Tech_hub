# 02 — Core MCP Tools (Unified Server, Registry, Shared Infrastructure)

> **Scope**: `packages/core/src/mcp/servicenow-mcp-unified/` + `packages/core/src/mcp/enterprise-proxy/`
> **Source**: takeover continuation audit (Codex), building on prior batch outputs
> **Status**: DONE (takeover batch)

---

## 1. MCP Server Architecture

### Primary entrypoints
- `packages/core/src/mcp/servicenow-mcp-unified/index.ts` (3,610 bytes)
- `packages/core/src/mcp/servicenow-mcp-unified/server.ts` (33,627 bytes)

### Initialization flow
1. Preserve critical MCP env vars before dotenv load (`SNOW_LAZY_TOOLS`, `SNOW_TOOL_DOMAINS`, SN credentials)
2. Build `ServiceNowUnifiedServer`
3. Load credentials with priority:
   - Enterprise portal runtime fetch (JWT-based)
   - Env vars (`SERVICENOW_*` / `SNOW_*`)
   - auth.json fallbacks
4. Initialize tool registry (`toolRegistry.initialize()`)
5. Start stdio transport (`StdioServerTransport`)

### MCP handlers implemented in unified server
- `ListToolsRequestSchema`
- `CallToolRequestSchema`
- `ListPromptsRequestSchema`
- `GetPromptRequestSchema`

### Transport
- Unified server process uses **stdio transport** to clients.
- Separate HTTP wrapper exists at `packages/core/src/mcp/http-transport-wrapper.ts`, but `callTool` path is explicitly unfinished (`"Tool execution not yet implemented..."`).

---

## 2. Tool Registry Pattern

### Registry implementation
- `packages/core/src/mcp/servicenow-mcp-unified/shared/tool-registry.ts` (19,732 bytes)
- Supports two loading modes:
  - **Dynamic (file-based)**: discovers domain dirs and imports tool modules
  - **Static (bundled fallback)**: uses `STATIC_TOOL_MODULES` map

### Tool export conventions
- Static mode expects `*_def` + paired `*_exec` exports.
- Dynamic loader expects `toolDefinition` + `execute` exports.

### Domain and tool inventory (current repo snapshot)
- Unified top-level tool domains: **83**
- Unified `.ts` tool files (excluding `index.ts`): **382**
- Static registry map domains: **59**
- Dynamic-only domains (not in static map): **24**

### Critical portability finding
- Some domains are available only in dynamic filesystem mode (example: `development`, `service-portal`, `performance-analytics`, `ui-actions`, `plugins`, `meta`, `parsers`, `processors`).
- If packaged/runtime environment forces static-only behavior, these domains may be absent unless static map is expanded.

### Token optimization hooks
- `SNOW_LAZY_TOOLS=true`: list only meta-tools (`tool_search`, `tool_execute`) and execute full catalog indirectly
- `SNOW_TOOL_DOMAINS=...`: domain-scope tool listing to reduce tool schema token load

---

## 3. Shared Infrastructure

### Core shared files
- `shared/auth.ts` (24,143 bytes)
- `shared/error-handler.ts` (12,778 bytes)
- `shared/types.ts` (6,450 bytes)
- `shared/permission-validator.ts` (7,165 bytes)

### Auth pattern
- Unified `ServiceNowAuthManager` with:
  - OAuth refresh path
  - basic auth fallback
  - cached token handling
  - Axios client instrumentation (auto retry after 401/token refresh)
- Token cache path pattern includes `~/.snow-flow/token-cache.json` logic.

### Error handling pattern
- `SnowFlowError` classification + retryability flags
- `retryWithBackoff()` with configurable retry strategy
- standardized tool result wrappers (`createSuccessResult`, `createErrorResult`)

### Permission model
- `ToolPermission`: `read | write | admin`
- `UserRole`: `developer | stakeholder | admin`
- Defaults when missing metadata:
  - permission defaults to `write` (restrictive)
  - allowed roles defaults to `developer, admin`
- Runtime enforcement via `validatePermission()` before tool execution

---

## 4. Tool Implementation Patterns (Representative Samples)

### Common pattern across domains
- Each tool defines metadata-rich `*_def`
- Executor `*_exec` receives `(args, context)`
- Calls ServiceNow REST via authenticated client
- Returns standardized `ToolResult`

### Representative files reviewed
1. `tools/operations/snow_query_table.ts` (7,186 bytes)
   - Generic table query tool (`/api/now/table/{table}`)
   - Read permission, broad role support
2. `tools/cmdb/snow_search_cmdb.ts` (2,401 bytes)
   - CMDB query composition over `cmdb_ci`
3. `tools/business-rules/snow_create_business_rule.ts` (7,384 bytes)
   - Write operation to `sys_script`
   - ES5 guidance in metadata/description
4. `tools/automation/snow_get_logs.ts` (6,223 bytes)
   - Read logs from `syslog`
5. `tools/security/snow_scan_vulnerabilities.ts` (1,584 bytes)
   - Security scan operation (`sn_vul_scan`)
6. `tools/update-sets/snow_update_set_query.ts` (5,045 bytes)
   - Reads `sys_update_set` + `sys_update_xml`

### Observed API usage style
- Direct REST table endpoints dominate:
  - `/api/now/table/*`
- Encoded query composition pattern (`sysparm_query`) is consistent and reusable.

---

## 5. Tool Classification System

### Metadata fields present in definitions
- Discovery/UX: `category`, `subcategory`, `use_cases`
- Cognitive load hints: `complexity`, `frequency`
- Authorization: `permission`, `allowedRoles`

### Classification quality
- Many tools already include explicit metadata, but not universally complete.
- Defaults in permission validator provide safe behavior when metadata is absent.
- Existing script `scripts/classify-all-tools.ts` is useful for metadata normalization at scale.

---

## 6. Enterprise Proxy

### File
- `packages/core/src/mcp/enterprise-proxy/server.ts` (13,571 bytes)

### Pattern
- Presents local MCP server interface while proxying calls upstream via HTTPS.
- Uses JWT/license env (`SNOW_LICENSE_KEY`, `SNOW_ENTERPRISE_URL`).
- Keeps ServiceNow credentials on enterprise side (portal fetch model), not local storage.

### Relevance
- Strong pattern for future managed mode, but not required for MVP local-first app.

---

## 7. Key File Reference Table

| File | Size | Role |
|------|------|------|
| `packages/core/src/mcp/servicenow-mcp-unified/index.ts` | 3,610 B | Bootstrap + env preservation |
| `packages/core/src/mcp/servicenow-mcp-unified/server.ts` | 33,627 B | MCP request handlers, auth loading, lazy/domain modes |
| `packages/core/src/mcp/servicenow-mcp-unified/shared/tool-registry.ts` | 19,732 B | Tool discovery + static fallback |
| `packages/core/src/mcp/servicenow-mcp-unified/shared/auth.ts` | 24,143 B | OAuth/basic auth manager + client creation |
| `packages/core/src/mcp/servicenow-mcp-unified/shared/error-handler.ts` | 12,778 B | Error classification + retry/backoff |
| `packages/core/src/mcp/servicenow-mcp-unified/shared/permission-validator.ts` | 7,165 B | Role/permission enforcement |
| `packages/core/src/mcp/servicenow-mcp-unified/shared/types.ts` | 6,450 B | Shared tool/auth typing contracts |
| `packages/core/src/mcp/enterprise-proxy/server.ts` | 13,571 B | Enterprise proxy transport |
| `packages/core/src/mcp/http-transport-wrapper.ts` | 14,182 B | HTTP wrapper (tool execution incomplete) |

---

## 8. Integration Points for Our Project

### Extract now
1. Unified tool definition + executor pattern (`*_def`/`*_exec`)
2. Permission metadata contract (`permission`, `allowedRoles`)
3. Error/retry wrappers from `shared/error-handler.ts`
4. Encoded-query-centric REST patterns from representative read tools
5. Lazy/domain filtering concepts for token control (`SNOW_LAZY_TOOLS`, `SNOW_TOOL_DOMAINS`)

### Adapt before use
1. Registry to avoid static/dynamic domain mismatch risk
2. Credential chain to align with Web App-owned settings and DB-backed secrets
3. Tool output contracts to our MCP JSON schema style
4. Write tools gated behind explicit confirmation and role checks

### Defer for later phases
1. Enterprise proxy deployment path
2. Full write-heavy domain coverage beyond assessment scope

---

## 9. Takeover Notes (for reconciliation)

- This document was completed in a takeover pass after prior-agent context exhaustion.
- It reconciles missing deep-dive scope for core MCP tools and is intended to pair with:
  - `03_core_infrastructure.md`
  - `05_auth_and_transport.md`
  - `08_extensibility_audit.md`
  - `09_tool_mapping_matrix.md`

