# Tech Assessment Hub

ServiceNow technical assessment platform with a hybrid MCP runtime:
- Python FastAPI control plane (UI, DB owner, orchestration)
- TypeScript sidecar MCP (reused Snow-Flow tools)
- Unified tool contracts surfaced through one `/mcp` interface

## Run

```bash
cd tech-assessment-hub
source venv/bin/activate
python -m src.main
```

### Run detached (prevents terminal/session kill)
If you start the app from a terminal session that later closes (or from an agent-run session), the OS may send SIGHUP and the server will exit. Use the detached scripts to keep it running:

```bash
cd tech-assessment-hub
./scripts/run_detached.sh
./scripts/status_detached.sh
./scripts/open_app.sh
./scripts/restart_detached.sh
./scripts/stop_detached.sh
```

### Run from IDE (no terminal needed)
- Open Command Palette and run `Tasks: Run Task`
- Pick one of:
  - `Tech Assessment: Start App`
  - `Tech Assessment: Restart App`
  - `Tech Assessment: Stop App`
  - `Tech Assessment: App Status`
  - `Tech Assessment: Open App`
- These are defined in `.vscode/tasks.json`.

### Port behavior
- Start script does **not** kill whatever is already on port `8080`.
- If `8080` is busy, it selects the next free port (`8081`, `8082`, etc.) and writes the actual URL to `data/server.url`.
- `open_app.sh` reads `data/server.url`, so it opens the correct port automatically.

### Port selection
- Default: `127.0.0.1:8080`
- Override:
  - `TECH_ASSESSMENT_HUB_PORT=8081 python -m src.main`
- If the default port is already in use, the app auto-selects the next available port and prints which one it chose.

### Assessment preflight cache sync
- Before assessment scans run, the app preflights all Data Browser tab datasets for that instance:
  - Full pull when local cache is empty
  - Delta pull when cache is stale
- Staleness window default is 10 minutes and can be overridden:
  - `TECH_ASSESSMENT_PREFLIGHT_STALE_MINUTES=15 python -m src.main`
- Scan-start gating waits on required relationship datasets first:
  - `metadata_customization`, `version_history` (current state), `customer_update_xml`, `update_sets`
- Running-pull wait timeout default is 900 seconds:
  - `TECH_ASSESSMENT_PREFLIGHT_WAIT_SECONDS=1200 python -m src.main`
- After scans complete, the app runs a post-scan version-history catch-up (smart full/delta) to backfill non-current rows.
- Metadata scan classification uses local cached relationships:
  - `metadata_customization` + current `version_history` + related `customer_update_xml` + `update_set`
  - `customer_update_xml.remote_update_set` is used as a fallback when `update_set` is blank.
  - `version_history.sys_customer_update` (mapped as `customer_update_sys_id`) is used as a fallback link to metadata `sys_id` when `sys_update_name` does not line up cleanly.

## Hybrid MCP Operations Runbook

### Runtime model
- End users interact with one tool catalog and one workflow.
- Tool routing (Python vs TypeScript sidecar) is internal.
- Admin diagnostics expose runtime internals for troubleshooting.

### Admin access
- Bridge management endpoints are admin-protected:
  - `/api/mcp/bridge/*`
  - `/api/mcp/admin/diagnostics`
- Preferred auth:
  - Set env var `TECH_ASSESSMENT_MCP_ADMIN_TOKEN`
  - Send header `X-MCP-Admin-Token: <token>`
- If no token is configured, localhost requests are trusted for development only.

### Key MCP endpoints
- `POST /mcp`
  - JSON-RPC methods: `initialize`, `tools/list`, `tools/call`
- `GET /api/mcp/capabilities`
  - Unified user-facing tool catalog (no engine metadata)
- `GET /api/mcp/health`
  - Aggregate runtime health and degraded capability summary
- `GET /api/mcp/admin/diagnostics`
  - Admin runtime diagnostics (engine routing + audit tail)

### Sidecar lifecycle
- Use MCP Console admin bridge controls for:
  - start / stop / restart
  - reload
  - reconnect all / reconnect single server
- Runtime degrades gracefully:
  - Python tools continue if TS sidecar is down
  - TS-routed calls return `tool_temporarily_unavailable` with correlation ID
  - Sidecar recovery includes retry + backoff + auto-restart cooldown

### Audit and troubleshooting
- Runtime tool execution events are written to:
  - `tech-assessment-hub/data/mcp_runtime_audit.jsonl`
- Bridge process logs are available from:
  - `GET /api/mcp/bridge/logs`
- Correlate failures using `correlation_id` in tool responses and audit rows.
