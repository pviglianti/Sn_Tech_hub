# 05 — Auth & Transport Layer

> **Scope**: Auth schemas, providers, OAuth flows, PKCE, portal sync, enterprise auth, HTTP/SSE transport, session management
> **Source**: Agent a1cd197 analysis of `packages/core/src/auth/` and `packages/snowcode/src/server/auth-routes.ts`
> **Status**: DONE

---

## 1. Auth Schema (`packages/core/src/auth/index.ts`)

### Credential Storage
- **File**: `~/.local/share/snow-code/auth.json`
- **Permissions**: `0o600` (owner read/write only)
- **Format**: Discriminated union by `type` field

### Auth Types (Zod Schema)

```typescript
export const Info = z.discriminatedUnion("type", [
  Oauth,        // OAuth 2.0 tokens (refresh + access + expires)
  Api,          // API key
  WellKnown,    // Well-known endpoint auth
  // + custom types per provider
])
```

### ServiceNow OAuth Schema (`servicenow-oauth.ts`)

```typescript
{
  type: "servicenow-oauth",
  instanceUrl: string,         // e.g., "dev12345.service-now.com"
  clientId: string,
  clientSecret: string,
  accessToken: string,
  refreshToken: string,
  tokenExpiry: number,         // Unix timestamp
  scope: string,               // "useraccount" etc.
}
```

### PKCE Utilities (`pkce.ts`)
- `generateCodeVerifier()` — 128 char random string
- `generateCodeChallenge(verifier)` — SHA-256 hash, base64url encoded
- Standard OAuth 2.0 PKCE flow for public clients

---

## 2. Auth Providers (`packages/core/src/auth/providers/`)

### Provider Interface

```typescript
interface BuiltInAuthProvider {
  provider: string
  loader?: (getAuth, provider, client) => Promise<Record<string, any>>
  methods: AuthMethod[]
}

type AuthMethod =
  | { type: "oauth"; label: string; authorize(): Promise<...> }
  | { type: "api"; label: string; provider?: string }
```

### Anthropic Provider (`providers/anthropic.ts`)
- **Flow**: OAuth 2.0 with PKCE
- **Modes**: `"max"` (Claude Pro/Max) or `"console"` (API console)
- **Client ID**: `9d1c250a-e61b-44d9-88ed-5944d1962f5e`
- **Endpoints**:
  - Auth: `https://claude.ai/oauth/authorize` or `https://console.anthropic.com/oauth/authorize`
  - Token: `https://console.anthropic.com/v1/oauth/token`
- **Special**: API key creation endpoint for programmatic key generation
- **Auto-refresh**: Token refresh in loader (fetch wrapper)

### GitHub Copilot Provider (`providers/github-copilot.ts`)
- **Flow**: Device authorization (user visits URL, enters code)
- **Endpoints**:
  - Device code: `https://github.com/login/device/code`
  - Access token: `https://github.com/login/oauth/access_token`
  - Copilot token: `https://api.github.com/copilot_internal/v2/token`
- **Polling**: Auto-poll every 5 seconds for user approval
- **Storage**: Both GitHub OAuth token and Copilot API token

### ServiceNow OAuth (`servicenow-oauth.ts`)
- **Flow**: OAuth 2.0 Authorization Code + PKCE
- **Redirect URI**: `http://localhost:{port}/callback` (local server)
- **Token refresh**: Automatic with expiry tracking
- **Multiple instances**: Stored per-instance in auth.json

---

## 3. Auth Priority & Fallback Chain

```
Priority 1: Environment variables
  SERVICENOW_INSTANCE_URL, SERVICENOW_CLIENT_ID, SERVICENOW_CLIENT_SECRET
  (also SNOW_* prefix variants)

Priority 2: auth.json file
  ~/.local/share/snow-code/auth.json

Priority 3: Unauthenticated mode (last resort — no API access)
```

### Auto-Healing
- Detects auth.json at **incorrect** path (`~/.local/share/snowcode/` without dash)
- Auto-moves to correct path (`~/.local/share/snow-code/`)
- Creates symlink at old location for backwards compatibility

---

## 4. SnowCode Auth Routes (`packages/snowcode/src/server/auth-routes.ts`)

**3,009 lines** — comprehensive auth endpoint handling.

### Route Map

```typescript
AuthRoute = new Hono()
  .get("/",                              /* list auth methods */)
  .post("/oauth/:provider/authorize",    /* start OAuth flow */)
  .post("/oauth/callback",               /* handle OAuth callback */)
  .post("/oauth/token/poll",             /* poll for device auth approval */)
  .get("/providers",                     /* list available providers */)
  .post("/servicenow/authorize",         /* start SN OAuth */)
  .post("/servicenow/callback",          /* handle SN OAuth callback */)
  .post("/portal/sync",                 /* sync credentials to portal */)
  .post("/portal/pull",                 /* pull credentials from portal */)
  .post("/enterprise/login",            /* enterprise JWT auth */)
```

### Provider Registry

```typescript
const AUTH_PROVIDERS: Record<string, BuiltInAuthProvider> = {
  "anthropic": AnthropicAuthProvider,
  "github-copilot": GitHubCopilotAuthProvider,
}
```

### OAuth Session Management

```typescript
const oauthSessions: Map<string, {
  verifier: string;
  callback: (code: string) => Promise<any>
}>

const headlessServiceNowSessions: Map<string, {
  instance: string,
  clientId: string,
  clientSecret: string,
  state: string,
  codeVerifier: string,
  redirectUri: string,
  createdAt: number      // Auto-cleanup after 10 min
}>
```

- Auto-cleanup of expired sessions every 60 seconds
- 10-minute timeout for headless OAuth sessions

---

## 5. Portal Sync (`portal-sync.ts`)

```typescript
PortalSync.syncToPortal(licenseKey, portalUrl?)   // Push local creds to portal
PortalSync.fetchFromPortal(licenseKey, portalUrl?) // Fetch decrypted creds
PortalSync.pullFromPortal(licenseKey, portalUrl?)  // Fetch and store locally
PortalSync.autoSync(portalUrl?)                    // Auto-sync if enterprise
```

- **Portal URL**: `https://portal.snow-flow.dev` (configurable)
- **Supported Services**: Jira, Azure DevOps, Confluence, GitHub, GitLab
- **API Endpoints**:
  - `POST /api/credentials/sync-from-cli` — Push credentials
  - `POST /api/credentials/fetch-for-cli` — Pull credentials

---

## 6. Enterprise Auth & MCP Config Update

### Enterprise Login Flow

```typescript
POST /enterprise/login
  → Validates JWT token with enterprise portal
  → Updates MCP config files:
     1. .mcp.json (project-level)
     2. ~/.config/snow-code/opencode.json (global)
     3. .claude/mcp-config.json (Claude Desktop)
```

### MCP Config Update (critical pattern)

```typescript
updateEnterpriseMcpConfig(token: string, mcpServerUrl: string)
  // Supports TWO transport modes:

  // Mode 1: Local proxy (default)
  {
    type: "local",
    command: ["node", "/path/to/enterprise-proxy/server.js"],
    environment: {
      SNOW_ENTERPRISE_URL: "https://portal.snow-flow.dev",
      SNOW_LICENSE_KEY: "jwt-token-here"
    }
  }

  // Mode 2: Remote SSE (alternative)
  {
    type: "sse",
    url: "https://enterprise-server/sse",
    headers: { "Authorization": "Bearer jwt-token" }
  }
```

### Enterprise Proxy Discovery

```typescript
getEnterpriseProxyPath(): string
  // Searches in order:
  // 1. npm global (-g installation)
  // 2. Local node_modules
  // 3. Development path (../core)
```

### Third-Party Credential Fetching

```typescript
fetchThirdPartyCredentials(token): Promise<{
  enabledServices: string[],
  credentials?: {
    jira?: { baseUrl, email, apiToken, enabled },
    azureDevOps?: { baseUrl, username, apiToken, enabled },
    confluence?: { baseUrl, email, apiToken, enabled },
  }
}>
```

---

## 7. Security Architecture

| Aspect | Implementation |
|--------|---------------|
| Credential storage | File permissions `0o600` |
| OAuth security | PKCE (Proof Key for Code Exchange) |
| CSRF prevention | State parameter in OAuth flows |
| Token management | Auto-refresh with expiry tracking |
| Enterprise | JWT tokens, server-side credential fetch |
| Multiple transport | Local subprocess OR remote SSE |

---

## 8. Transport Summary

### MCP Transport Options

| Transport | Type | Use Case |
|-----------|------|----------|
| **stdio** | Local subprocess | Default — MCP server as child process |
| **SSE** | Remote streaming | Enterprise — connect to remote MCP |
| **HTTP** | Request/response | API calls to ServiceNow |

### SSE Event Flow (Server → Client)

```
Client connects: GET /event
Server sends: { type: "server.connected", properties: {} }
Server streams: All Bus events as SSE messages
Client disconnects: Cleanup subscriptions
```

### ServiceNow API Transport
- All SN API calls go through the `shared/` ServiceNow client
- OAuth token auto-refresh on 401
- Rate limiting and pagination built-in
- Standard REST endpoints: `/api/now/table/{table}`, `/api/now/cmdb/`, etc.

---

## Integration Points for Our Project

### What to Extract

1. **ServiceNow OAuth flow** (`servicenow-oauth.ts` + `pkce.ts`)
   - Port to Python for our FastAPI auth endpoints
   - Keep PKCE — it's required for modern OAuth
   - Adapt for our wizard's "Step 4: Initial ServiceNow Instance"

2. **Auth priority chain** (env → file → unauthenticated)
   - Match this pattern in our settings.json loading

3. **SSE transport pattern** (`GET /event` + Bus)
   - This IS the Management Service Bridge we need
   - Our FastAPI app subscribes to MCP SSE for real-time updates
   - Enables: progress tracking, status updates, error reporting

4. **Multi-instance support** (per-instance credentials in auth.json)
   - Our DB already supports multiple instances
   - Need to align credential storage format

### What to Simplify

1. **Portal sync** — Not needed for MVP (enterprise feature)
2. **Enterprise proxy** — Not needed (we're not SaaS yet)
3. **GitHub Copilot auth** — Not relevant to our use case
4. **Anthropic OAuth** — We use API keys, not OAuth subscriptions
5. **3-file config update** — We only need `settings.json` for MVP

### What to Reference

1. **Headless OAuth session management** — Pattern for future when we add OAuth wizard
2. **Auto-healing auth paths** — Good UX pattern to adopt
3. **Token caching** — `~/.snow-flow/token-cache.json` pattern for performance
