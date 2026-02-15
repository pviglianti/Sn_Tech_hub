# 03 — Core Infrastructure (Server, Config, Session, Memory, Storage)

> **Scope**: `packages/core/src/` — server framework, configuration management, session system, memory/storage layers, project management, event bus
> **Source**: Agent a1cd197 analysis of snow-flow_pv core infrastructure
> **Status**: DONE

---

## 1. Server Layer (`packages/core/src/server/server.ts`)

### Framework: Hono (lightweight HTTP)
- **Runtime**: Bun.serve with `idleTimeout: 0` (persistent connections)
- **Port**: Configurable via `listen({ port, hostname })`

### Middleware Stack (order matters)
1. **Error Handler** — converts NamedError/NotFoundError to JSON with proper status codes
2. **Request/Response Logging** — logs method, path, duration (skips `/log` endpoint)
3. **Directory Context** — sets `Instance.directory` from query parameter
4. **CORS** — enabled for all origins
5. **OpenAPI Documentation** — `/doc` endpoint with schema generation

### Key Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/doc` | OpenAPI documentation |
| GET/PATCH | `/config` | Get/update configuration |
| GET | `/path` | System paths (state, config, worktree) |
| GET/POST | `/session` | List/create sessions |
| GET | `/session/:id` | Session details |
| POST | `/session/:id/message` | Send message |
| **GET** | **`/event`** | **SSE stream (all events)** |
| PUT | `/auth/:id` | Set auth credentials |
| GET/POST | `/tui/*` | TUI control endpoints |
| GET/POST/DELETE | `/tasks/*` | Background task management |
| GET/POST | `/debug/tokens/*` | Token debugging |

### SSE Transport (`GET /event`)

```typescript
streamSSE(c, async (stream) => {
  stream.writeSSE({ data: JSON.stringify({ type: "server.connected", properties: {} }) })
  const unsub = Bus.subscribeAll(async (event) => {
    await stream.writeSSE({ data: JSON.stringify(event) })
  })
  stream.onAbort(() => unsub())
})
```

**Key properties**:
- Persistent connection (no timeout)
- Subscribes to ALL bus events
- Auto-cleanup on disconnect
- Format: `{ type: string, properties: {...} }`

### Extended Server (SnowCode — `packages/snowcode/src/server/server.ts`)
- 2,134 lines — extends core server significantly
- **Feature toggles**: `GET/POST /features` → `{ context7, webSearch, webFetch, isEnterprise }`
- **Enterprise detection**: checks `config.mcp["snow-flow-enterprise"]` enabled
- **Auth routes**: 3,009-line auth-routes.ts (see doc 05)
- **Documentation generation**: Auto-generates enterprise AGENTS.md sections

---

## 2. Configuration Management (`packages/core/src/config/`)

### Config Loading Chain (priority order, merged)
1. **Global Config**: `Global.Path.config` (platform XDG)
2. **Project Config Files** (in order):
   - `opencode.jsonc`, `opencode.json`
   - `.mcp.json` (converted from `mcpServers` → `mcp`)
   - `.snow-code/config.json`, `.snowcode/config.json`, `.opencode/config.json`
3. **Environment-based**:
   - `$SNOWCODE_CONFIG` (file path)
   - `$SNOWCODE_CONFIG_CONTENT` (JSON string)
   - `$SNOWCODE_CONFIG_DIR` (directory with config)
4. **Well-Known Endpoints**: Fetch from `.well-known/opencode`
5. **Directory Traversal**: Walk up project tree loading `.snow-code/`, `.snowcode/`, `.opencode/`

### Config Structure (TypeScript)

```typescript
Config.Info = {
  agent?: Record<string, AgentConfig>,
  mode?: Record<string, ModeConfig>,      // Deprecated → migrated to agent
  command?: Record<string, CommandConfig>,
  plugin?: PluginConfig[],
  skill?: Record<string, SkillConfig>,
  mcp?: Record<string, MCPServerConfig>,
  tools?: Record<string, ToolConfig>,
  permission?: Record<string, PermissionConfig>,
  username?: string,
  share?: "auto" | string,
  keybinds?: Record<string, string>,
  features?: { context7?: boolean, webSearch?: boolean, webFetch?: boolean }
}
```

### Key Functions
- `Config.get()` — Get merged config (all sources)
- `Config.update(partial)` — Update (merges with existing)
- `Config.global()` — Get global-only config

### SnowCode Config Extensions
- Auto-loads **bundled skills** (53 ServiceNow domain skills)
- Loads hook definitions from directories
- Tracks per-project state

---

## 3. Global Paths — XDG Base Directory (`packages/core/src/global/index.ts`)

```typescript
Global.Path = {
  data:    "~/.local/share/snow-code",        // XDG_DATA_HOME
  bin:     "~/.local/share/snow-code/bin",
  log:     "~/.local/share/snow-code/log",
  cache:   "~/.cache/snow-code",              // XDG_CACHE_HOME
  config:  "~/.config/snow-code",             // XDG_CONFIG_HOME
  state:   "~/.local/state/snow-code",        // XDG_STATE_HOME
  memory:  "~/.local/share/snow-code/memory",
}
```

> **Integration point**: This is WHERE to inject user-configurable paths. Currently hardcoded to XDG. Our wizard would need to override `Global.Path.memory` (and potentially `data`, `config`) to point to user-selected `_Context/` folder.

---

## 4. Session Management (`packages/core/src/session/`)

### Session Schema
```typescript
Session.Info = {
  id: string,                    // Ascending identifier
  projectID: string,
  directory: string,
  parentID?: string,             // For child/forked sessions
  title: string,                 // Auto-generated or user-provided
  version: string,
  summary?: { diffs: FileDiff[] },
  share?: { url: string },
  revert?: { messageID, partID?, snapshot?, diff? },
  time: { created, updated, compacting? }
}
```

### Session Storage
- **Path**: `~/.local/share/snow-code/storage/session/{projectID}/`
- **Format**: JSON files per session

### Key Operations

| Function | Purpose |
|----------|---------|
| `Session.create(parentID?, title?)` | Create new session |
| `Session.fork(sessionID, messageID?)` | Fork (copy messages up to point) |
| `Session.messages(sessionID)` | List messages |
| `Session.updateMessage(info)` | Store/update message |
| `Session.updatePart(part)` | Store/update message part |
| `Session.delete(sessionID)` | Delete session + artifacts |

### Session Files

| File | Purpose |
|------|---------|
| `index.ts` | Main API |
| `message.ts` / `message-v2.ts` | Message schemas (v1, v2 current) |
| `compaction.ts` | Message pruning/compression |
| `fork-tree.ts` | Fork genealogy tracking |
| `lock.ts` | File-based session locking |
| `store.ts` | Raw storage operations |
| `todo.ts` | Todo item tracking |
| `summary.ts` | Session summaries |
| `retry.ts` | Message retry logic |
| `revert.ts` | Message revert/undo |
| `session-manager.ts` | Multi-session coordination |

### Bus Events
- `session.started`, `session.updated`, `session.deleted`, `session.error`

---

## 5. Memory System (`packages/core/src/memory/`)

### Storage Structure
```
~/.local/share/snow-code/memory/
├── projects/
│   └── {projectID}/
│       ├── sessions/
│       │   └── {sessionID}/
│       │       ├── memory.json      # Main memory
│       │       └── worklog.jsonl    # Append-only log
│       └── learnings.json           # Project-level learnings
└── global_learnings.json            # Cross-project learnings
```

### Memory Components

**WorkLogEntry** (append-only):
```typescript
{
  timestamp: number,
  type: "user_request" | "ai_response" | "tool_call" | "tool_result"
       | "file_created" | "file_modified" | "file_deleted" | "error"
       | "compaction" | "learning",
  summary: string,
  metadata?: Record<string, any>
}
```

**KeyResult**:
```typescript
{
  type: "file_created" | "file_modified" | "file_deleted"
       | "artifact_created" | "task_completed" | "other",
  description: string,
  path?: string,
  sysId?: string,              // ServiceNow sys_id
  timestamp: number
}
```

**Learning** (persistent knowledge):
```typescript
{
  id: string,
  category: "codebase" | "user_preference" | "pattern" | "api"
           | "configuration" | "other",
  insight: string,
  context?: string,
  timestamp: number,
  sessionID?: string
}
```

**CurrentStatus**:
```typescript
{ completed: string[], discussionPoints: string[], openQuestions: string[] }
```

### Memory Files

| File | Purpose |
|------|---------|
| `memory.ts` | Main implementation |
| `memory-sync.ts` | Sync to external systems |
| `memory-system.ts` | Memory system interface |
| `hierarchical-memory-system.ts` | Multi-level memory |
| `session-memory.ts` | Session-specific memory |
| `servicenow-artifact-indexer.ts` | Index ServiceNow artifacts |
| `snow-flow-memory-patterns.ts` | Memory patterns |

### Bus Events
- `memory.updated`, `memory.learning.added`, `memory.worklog.appended`

> **Integration point**: This memory system parallels our `_Context/` file-backed memory. Their `learnings.json` ≈ our `insights.md`. Their `worklog.jsonl` ≈ our `run_log.md`. Their hierarchical project→session→memory maps to our `_Context/Projects/{Client}/` structure.

---

## 6. Storage Layer (`packages/core/src/storage/storage.ts`)

### Unified File-Based Store
- **Root**: `~/.local/share/snow-code/storage/`
- **Format**: Pretty-printed JSON (2 spaces)
- **Features**: File locking (read/write), migrations, error handling

### Directory Layout
```
storage/
├── project/{projectID}.json
├── session/{projectID}/{sessionID}.json
├── message/{sessionID}/{messageID}.json
├── part/{messageID}/{partID}.json
└── migration                     # Current migration version
```

### Operations
```typescript
Storage.read<T>(key: string[]): Promise<T>
Storage.write<T>(key: string[], content: T): Promise<void>
Storage.update<T>(key: string[], fn: (draft: T) => void): Promise<T>
Storage.remove(key: string[]): Promise<void>
Storage.list(prefix: string[]): Promise<string[]>
```

---

## 7. Project & Instance Management

### Instance (Per-Request Context)
```typescript
Instance.provide<T>({ directory, init, fn }): Promise<T>
  // Sets up Instance context for duration of fn()
  // Used in server middleware for per-request isolation

Instance.directory: string   // Current working directory
Instance.worktree: string    // Git worktree root
Instance.project: Project.Info
```

### Project Storage
```typescript
Project.Info = {
  id: string,
  vcs: "git" | "other",
  worktree: string,
  time: { created, initialized }
}
```

---

## 8. Bus & Event System

```typescript
// Define event
const Event = Bus.event("namespace.event", z.object({ data: z.string() }))

// Publish
Bus.publish(Event, { data: "value" })

// Subscribe (single event)
const unsub = Bus.subscribe(Event, (evt) => { ... })

// Subscribe (all events — used by SSE endpoint)
const unsub = Bus.subscribeAll(async (event) => { ... })
```

All major systems (sessions, memory, tasks, auth) emit events through this bus. The SSE endpoint at `GET /event` forwards ALL bus events to connected clients.

> **Integration point**: This bus + SSE pattern is exactly how our Web App could receive real-time updates from MCP. The Management Service Bridge we need is already built — we just need to connect our FastAPI app as an SSE client.

---

## 9. Provider & Model Management (`packages/core/src/provider/`)

- **ModelsDev**: Registry providing cost information and model metadata
- **Provider Loader**: Returns fetch-compatible client with auto token refresh and authorization headers
- **Special handling**:
  - Anthropic Max/Pro → zero cost (subscription)
  - GitHub Copilot → zero cost, vision support
  - Others → cost tracking from models.dev

---

## Integration Points Summary

| Snow-Flow Component | Our Equivalent | Action |
|---------------------|----------------|--------|
| `Global.Path` (XDG) | `_Context/` paths | Override with wizard-selected paths |
| Hono HTTP server | FastAPI | Keep ours; extract route patterns |
| SSE `/event` endpoint | Management Console websocket | **Use pattern** for real-time MCP→App bridge |
| Config loading chain | `settings.json` | Simplify; single source for MVP |
| Session management | Not needed (MVP) | Reference for future |
| Memory system | `_Context/` files | **Align structures** — their learnings ≈ our insights |
| Storage layer | SQLite | We use DB instead of files |
| Bus events | FastAPI events | **Extract pattern** for MCP→App communication |
| Provider management | LLM config in wizard | Extract model registry pattern |
