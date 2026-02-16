# Snow-flow Bridge Integration Research

Date: 2026-02-15
Owner: Claude
Status: Research complete, implementation pending

## Problem

Tech-assessment-hub's `MCPBridgeManager` communicates with the TS sidecar via **HTTP JSON-RPC** (`POST` to `rpc_url`). Snow-flow's MCP server uses **stdio transport** (`StdioServerTransport`). These are incompatible. The JSON-RPC payloads are identical — only the transport differs.

## Current State

| Component | Location | Status |
|---|---|---|
| Bridge manager (Python) | `src/mcp/bridge/manager.py` | Built, working. Spawns subprocess, talks HTTP JSON-RPC |
| Bridge config store | `src/mcp/bridge/config_store.py` | Built. All defaults empty/disabled |
| Runtime router | `src/mcp/runtime/router.py` | Built. Routes to Python local or ts_sidecar |
| Unified registry | `src/mcp/runtime/registry.py` | Built. Merges local + remote tool catalogs |
| MCP Console UI | `templates/mcp_console.html` | Basic admin controls + raw JSON editor |
| Existing stdio bridge | `scripts/mcp_stdio_bridge.py` | **Wrong direction**: stdio→HTTP (for Claude Desktop→our app) |
| Snow-flow compiled output | N/A | **Does not exist** — no `dist/` folder, never built |
| Snow-flow HTTP wrapper | `snow-flow_pv/.../http-transport-wrapper.ts` | 90% done, but `handleToolCall()` throws "not implemented" |

## Snow-flow MCP Tools Available (when auth'd)

- `snow_auth_status`, `snow_test_connection`, `snow_get_instance_info`
- `snow_create_widget`, `snow_update_widget`, `snow_get_widget`, `snow_list_widgets`
- `snow_create_workflow`, `snow_schedule_script_job`
- On-demand proxy maps ~40+ more tools (e.g., `snow_query_table`) to backend servers

## Three Integration Options

### Option A: HTTP-to-Stdio adapter script (Simplest, no Snow-flow changes)
Write a small (~60 line) Python or Node script that:
1. Spawns Snow-flow MCP server on stdio (`node dist/mcp/start-servicenow-mcp.js`)
2. Listens on HTTP port (e.g., 3100)
3. For each `POST /mcp`, writes JSON-RPC to stdin, reads response from stdout, returns via HTTP

Our bridge manager already handles subprocess lifecycle. This script is the middleware.

**Pros**: Zero Snow-flow modifications, fast to build
**Cons**: Extra process layer, may have buffering edge cases

### Option B: Fix Snow-flow's `HttpTransportWrapper.handleToolCall()` (Medium effort)
The wrapper is 90% done. `handleToolCall()` at line 312 throws because it can't access the MCP server's internal request handlers. Fix by:
- Using in-memory stdio pair (pipe the wrapper to the MCP server in-process)
- Or calling tool handler methods directly (bypass MCP SDK server layer)

**Pros**: Cleanest, reusable for Snow-flow ecosystem
**Cons**: Requires Snow-flow code changes, needs understanding of MCP SDK internals

### Option C: Use MCP SDK StreamableHTTP transport (SDK-native)
Replace `StdioServerTransport` with `StreamableHTTPServerTransport` in Snow-flow's server. SDK 1.25.2 supports this. But our bridge sends plain JSON-RPC POST, not StreamableHTTP protocol — compatibility may not align.

**Pros**: SDK-native, future-proof
**Cons**: Transport protocol mismatch with our bridge, most changes needed

## Recommendation

**Option A first** (adapter script). It's the fastest path to getting Snow-flow tools callable from our MCP. If performance or reliability issues emerge, upgrade to Option B.

## Pre-requisites Before Any Option

1. **Build Snow-flow**: `cd snow-flow_pv && bun install && turbo build` (or `cd packages/core && bun run build`)
2. **Auth Snow-flow**: `snow-flow auth login` or set env vars (`SNOW_INSTANCE`, `SNOW_CLIENT_ID`, `SNOW_CLIENT_SECRET`)
3. **Test Snow-flow standalone**: Verify stdio MCP works: `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | node dist/mcp/start-servicenow-mcp.js`

## Protocol Compatibility

| Feature | Our Bridge Sends | Snow-flow Expects | Compatible? |
|---|---|---|---|
| `tools/list` | `{"jsonrpc":"2.0","method":"tools/list","params":{}}` | `ListToolsRequestSchema` | Yes |
| `tools/call` | `{"jsonrpc":"2.0","method":"tools/call","params":{"name":"...","arguments":{...}}}` | `CallToolRequestSchema` | Yes |
| Transport | HTTP POST | stdio | **Needs adapter** |
| Response format | JSON-RPC 2.0 | JSON-RPC 2.0 | Yes |
