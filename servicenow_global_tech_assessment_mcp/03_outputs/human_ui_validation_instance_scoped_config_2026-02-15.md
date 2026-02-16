# Human UI Validation: Instance-Scoped Integration Properties

Date: 2026-02-15  
Owner: human  
Related implementation: Codex `#5` instance-scoped AppConfig overrides

## Goal
Verify that Integration Properties can be edited at:
1. Global scope (all instances default), and
2. Per-instance scope (override only one instance),
with correct fallback behavior.

## Environment
- App URL: `http://127.0.0.1:8080` (currently detected listening port)
- Page: `http://127.0.0.1:8080/integration-properties`

## Validation Steps
1. Open `http://127.0.0.1:8080/integration-properties`.
2. In `Override Scope`, confirm dropdown shows:
   - `Global Defaults (all instances)`
   - one or more instance options (name + ID).
3. Leave scope on `Global Defaults`.
4. In Integration/Fetch section, set `Request Timeout (sec)` to a unique test value (example `88`), click `Save Changes`, then `Reload`.
5. Confirm saved value persists at global scope.
6. Change scope dropdown to a specific instance.
7. Confirm `Request Timeout (sec)` initially matches global value if no instance override exists.
8. Change `Request Timeout (sec)` to a different value (example `91`), click `Save Changes`, then `Reload`.
9. Confirm value remains `91` for that selected instance.
10. Switch scope back to `Global Defaults`, click `Reload`.
11. Confirm global value is still `88` (instance override did not overwrite global).
12. Switch to a different instance (if available), click `Reload`.
13. Confirm that other instance still inherits global `88` unless explicitly overridden.
14. Optional cleanup:
    - Return instance override back to empty/default behavior using UI reset + save pattern.
    - Restore global value to prior baseline.

## Expected Results
- Scope selector changes which config set you are editing.
- Instance-scoped saves only affect selected instance.
- Global saves affect default/fallback for all instances without overrides.
- No UI errors; status box returns success payloads.

## API Spot-Check (Optional)
Use browser dev tools or curl:
- `GET /api/integration-properties` -> global (`instance_id: null`)
- `GET /api/integration-properties?instance_id=<id>` -> scoped
- `POST /api/integration-properties?instance_id=<id>` -> scoped write

## Pass/Fail Notes
- Pass criteria: all expected behaviors above observed.
- If fail, capture:
  - selected scope
  - property key
  - expected vs actual value
  - screenshot + timestamp

---
---

# Human Validation: MCP Prompts + Resources (Phase 2+3)

Date: 2026-02-15
Owner: human
Related implementation: Claude MCP Plan Phases 2+3 (prompts + resources content)

## What This Tests

The MCP server now serves **2 prompts** (methodology instructions for the AI) and **6 resources** (reference documents the AI reads on-demand). These were added as Python code inside the server — this test verifies the server actually returns them when asked via the MCP protocol.

**Think of it like this**: When a real AI connects to our MCP server, the first thing it does is ask "what prompts do you have?" and "what resources do you have?" — then it loads them. This test simulates that by making the same API calls manually.

## Environment
- App URL: `http://127.0.0.1:8080`
- MCP endpoint: `POST http://127.0.0.1:8080/mcp`
- All requests are JSON-RPC format (POST with JSON body)

## How to Run These Tests

Open a terminal. The app must be running. Copy/paste each curl command and check the output matches the expected result.

---

### Test 1: Server advertises prompts + resources capabilities

**What this checks**: When an AI client first connects, the server tells it "I support prompts and resources." If this fails, no AI client will even try to load our methodology.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}' | python3 -m json.tool
```

**Expected**: The response has a `capabilities` object containing `"prompts": {}` and `"resources": {}` (alongside `"tools": {}`).

**Pass if**: You see all three — `tools`, `prompts`, `resources` — inside `capabilities`.

---

### Test 2: Prompts list returns 2 prompts

**What this checks**: When an AI asks "what assessment methodologies do you have?", it gets back our 2 prompts. This is the menu of available expert modes.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"prompts/list"}' | python3 -m json.tool
```

**Expected**: A `prompts` array with exactly 2 entries:
- `tech_assessment_expert` — the full methodology
- `tech_assessment_reviewer` — the lighter review checklist

**Pass if**: Both prompt names appear with descriptions.

---

### Test 3: Expert prompt returns the full methodology

**What this checks**: When an AI loads the expert prompt, it gets back the complete assessment methodology — the depth-first workflow, classification rules, disposition framework, grouping signals, tool usage guide, and token efficiency rules. This is the core "how to do an assessment" document.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{"name":"tech_assessment_expert"}}' | python3 -m json.tool
```

**Expected**: A response with `messages` array containing one message with `role: "user"` and a large `text` field that starts with `# ServiceNow Technical Assessment Expert` and includes sections about methodology, classification rules, dispositions, grouping, tool usage, and token efficiency.

**Pass if**: The text content is substantial (not empty), starts with the right heading, and you can see sections like "Depth-First, Temporal Order", "Origin Classification Rules", "Disposition Framework", "Tool Usage Guide".

---

### Test 4: Reviewer prompt returns a shorter checklist

**What this checks**: Same as above but for the lighter review-only prompt.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":4,"method":"prompts/get","params":{"name":"tech_assessment_reviewer"}}' | python3 -m json.tool
```

**Expected**: A response with `messages` containing text starting with `# ServiceNow Assessment Reviewer` — shorter than the expert prompt, focused on review checklist and disposition criteria.

**Pass if**: Content loads, is shorter than the expert prompt, and covers review-specific topics.

---

### Test 5: Resources list returns 6 resources

**What this checks**: When an AI asks "what reference documents are available?", it gets back 6 resources. These are the on-demand docs the AI reads when it needs deeper reference material during an assessment.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":5,"method":"resources/list"}' | python3 -m json.tool
```

**Expected**: A `resources` array with 6 entries, all with `assessment://` URIs:

| # | URI | What it is |
|---|-----|------------|
| 1 | `assessment://guide/classification-rules` | How records get classified (modified_ootb, net_new_customer, etc.) |
| 2 | `assessment://guide/grouping-signals` | How to detect which records belong together as a feature |
| 3 | `assessment://guide/finding-patterns` | Common issues to look for (OOTB alternative, dead code, etc.) |
| 4 | `assessment://guide/app-file-types` | Important ServiceNow config types and what to look for |
| 5 | `assessment://schema/scan-result-fields` | ScanResult model field reference (what data is available) |
| 6 | `assessment://schema/feature-fields` | Feature model field reference (for grouping write-back) |

**Pass if**: All 6 URIs appear with names, descriptions, and `mimeType: "text/markdown"`.

---

### Test 6: Read a resource — classification rules

**What this checks**: When an AI needs to look up the exact classification rules during analysis, it reads this resource. Verify it returns real markdown content about origin types.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":6,"method":"resources/read","params":{"uri":"assessment://guide/classification-rules"}}' | python3 -m json.tool
```

**Expected**: A `contents` array with one entry containing `uri`, `mimeType: "text/markdown"`, and a `text` field with markdown about classification rules (mentions `modified_ootb`, `net_new_customer`, `ootb_untouched`, decision tree, version history method, baseline comparison).

**Pass if**: Real markdown content returned, mentions all origin types.

---

### Test 7: Read a resource — grouping signals

**What this checks**: When an AI needs to look up how to group records into features, it reads this resource.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":7,"method":"resources/read","params":{"uri":"assessment://guide/grouping-signals"}}' | python3 -m json.tool
```

**Expected**: Markdown content about 8 signal categories (update set cohorts, table affinity, naming conventions, code references, etc.) with confidence scoring weights.

**Pass if**: Real content returned, mentions "update set", "confidence", signal categories.

---

### Test 8: Error handling — ask for a prompt that doesn't exist

**What this checks**: If someone asks for a prompt we don't have, the server returns a proper error instead of crashing.

```bash
curl -s http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":8,"method":"prompts/get","params":{"name":"nonexistent_prompt"}}' | python3 -m json.tool
```

**Expected**: An `error` response with code `-32601` and message about prompt not found.

**Pass if**: Error response returned (not a crash or 500).

---

## Pass/Fail Summary

| Test | Description | Pass? |
|------|-------------|-------|
| 1 | Initialize advertises prompts + resources | |
| 2 | prompts/list returns 2 prompts | |
| 3 | Expert prompt loads full methodology | |
| 4 | Reviewer prompt loads review checklist | |
| 5 | resources/list returns 6 resources | |
| 6 | Classification rules resource loads | |
| 7 | Grouping signals resource loads | |
| 8 | Missing prompt returns error (not crash) | |

**Overall pass criteria**: All 8 tests pass. The MCP server correctly serves methodology prompts and reference resources to any AI client that connects.
