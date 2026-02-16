# Codex MCP Instructions: Phase 1 (Protocol) + Phase 5 (Tools)

> Date: 2026-02-15
> Context: Part of the MCP Tools + Classification Quality plan (`03_outputs/plan_mcp_tools_classification_quality_2026-02-15.md`)

## Overview

You have **2 phases** that can run in parallel. Both are mechanical, pattern-following work. No domain knowledge required — just follow existing code patterns precisely.

**Codebase root:** `/Users/pviglianti/Documents/Claude Unlimited Context/tech-assessment-hub/`

**Test command:** `./venv/bin/python -m pytest tests/ -q` (expect 98 passing)

**IMPORTANT:** Run tests after EACH task within a phase. Do not batch changes.

---

## Execution Update (2026-02-15 by Codex)

Completed:
- Phase 1 Task 1.1: Added `PromptSpec` / `ResourceSpec` and `PromptRegistry` / `ResourceRegistry` in `src/mcp/registry.py`, plus `PROMPT_REGISTRY` and `RESOURCE_REGISTRY` singletons.
- Phase 1 Task 1.2: Added JSON-RPC support for:
  - `prompts/list`
  - `prompts/get`
  - `resources/list`
  - `resources/read`
  and updated initialize capabilities to include `prompts` + `resources`.
- Phase 1 Task 1.3: Added protocol test suite `tests/test_mcp_prompts_resources_protocol.py` (15 tests).
- Phase 5 Task 5.1: Added `src/mcp/tools/core/update_result.py` (`update_scan_result`).
- Phase 5 Task 5.2: Added `src/mcp/tools/core/update_feature.py` (`update_feature`).
- Phase 5 Task 5.3: Added `src/mcp/tools/core/feature_detail.py` (`get_feature_detail`).
- Phase 5 Task 5.4: Added `src/mcp/tools/core/update_set_contents.py` (`get_update_set_contents`).
- Phase 5 Task 5.5: Added `GeneralRecommendation` model in `src/models.py` + `src/mcp/tools/core/general_recommendation.py` (`save_general_recommendation`).
- Phase 5 Task 5.6: Registered all 5 new tools in `build_registry()` in `src/mcp/registry.py`.

Validation:
- `./venv/bin/python -m pytest tests/test_mcp_prompts_resources_protocol.py -q` -> `15 passed`
- `./venv/bin/python -m pytest tests/ -q` -> `117 passed, 8 warnings`
- Registry sanity check confirms all 5 new Phase 5 tool names are present in `REGISTRY.list_tools()`.

No app/server restart was performed by Codex.

---

## Phase 1: MCP Protocol — Add Prompts + Resources Support

**Goal**: Extend the JSON-RPC handler to support `prompts/list`, `prompts/get`, `resources/list`, `resources/read`. This lets AI clients discover and load prompts and reference documents from the MCP server.

**Dependency**: None — start immediately.

### Task 1.1: Add PromptSpec + ResourceSpec to registry.py

**File to modify:** `src/mcp/registry.py`

**What to add:** Two new dataclasses and two new registry classes, following the exact same pattern as `ToolSpec`/`ToolRegistry`. Add them AFTER the existing `ToolRegistry` class (after line 48) and BEFORE `build_registry()`.

```python
# ── Prompt Registry ──────────────────────────────────────────────────

@dataclass
class PromptSpec:
    """MCP Prompt specification."""
    name: str
    description: str
    arguments: List[Dict[str, Any]]  # e.g., [{"name": "assessment_id", "required": False}]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]  # Returns {"description": str, "messages": [...]}


class PromptRegistry:
    def __init__(self) -> None:
        self._prompts: Dict[str, PromptSpec] = {}

    def register(self, spec: PromptSpec) -> None:
        self._prompts[spec.name] = spec

    def list_prompts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "arguments": spec.arguments,
            }
            for spec in self._prompts.values()
        ]

    def has_prompt(self, name: str) -> bool:
        return name in self._prompts

    def get_prompt(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if name not in self._prompts:
            raise KeyError(f"Prompt not found: {name}")
        return self._prompts[name].handler(arguments or {})


# ── Resource Registry ────────────────────────────────────────────────

@dataclass
class ResourceSpec:
    """MCP Resource specification."""
    uri: str
    name: str
    description: str
    mime_type: str  # e.g., "text/markdown"
    handler: Callable[[], str]  # Returns content string


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: Dict[str, ResourceSpec] = {}

    def register(self, spec: ResourceSpec) -> None:
        self._resources[spec.uri] = spec

    def list_resources(self) -> List[Dict[str, Any]]:
        return [
            {
                "uri": spec.uri,
                "name": spec.name,
                "description": spec.description,
                "mimeType": spec.mime_type,
            }
            for spec in self._resources.values()
        ]

    def has_resource(self, uri: str) -> bool:
        return uri in self._resources

    def read_resource(self, uri: str) -> Dict[str, Any]:
        if uri not in self._resources:
            raise KeyError(f"Resource not found: {uri}")
        spec = self._resources[uri]
        content = spec.handler()
        return {
            "contents": [
                {
                    "uri": spec.uri,
                    "mimeType": spec.mime_type,
                    "text": content,
                }
            ]
        }
```

**Also add** two module-level singletons after `REGISTRY = _LazyRegistry()` (at end of file):

```python
PROMPT_REGISTRY = PromptRegistry()
RESOURCE_REGISTRY = ResourceRegistry()
```

**Update imports** at the top of the file — no new imports needed since we already have `dataclass`, `Callable`, `Dict`, `List`, `Optional`, `Any`.

**NOTE**: Unlike `ToolRegistry`, `PromptRegistry` and `ResourceRegistry` do NOT need a `_LazyRegistry` proxy or a `build_*` function yet. They start empty and will be populated by Phase 2/3 (Claude's work). The registries just need to exist so the protocol handlers can reference them.

**Verification:**
1. `./venv/bin/python -m pytest tests/ -q` — 98 tests pass
2. `python -c "from src.mcp.registry import PromptSpec, PromptRegistry, ResourceSpec, ResourceRegistry, PROMPT_REGISTRY, RESOURCE_REGISTRY; print('OK')"` — prints OK

---

### Task 1.2: Add protocol handlers to jsonrpc.py

**File to modify:** `src/mcp/protocol/jsonrpc.py`

**Step 1:** Add imports at top (after existing imports):

```python
from ..registry import PROMPT_REGISTRY, RESOURCE_REGISTRY
```

**Step 2:** Update `_handle_initialize()` to advertise prompts + resources capabilities. Change the `capabilities` dict:

Replace:
```python
        "capabilities": {
            "tools": {}
        }
```

With:
```python
        "capabilities": {
            "tools": {},
            "prompts": {},
            "resources": {},
        }
```

**Step 3:** Add four new handler functions AFTER `_handle_tools_call()` and BEFORE `handle_request()`:

```python
def _handle_prompts_list(request_id: Optional[Union[str, int]]) -> Dict[str, Any]:
    return make_result(request_id, {
        "prompts": PROMPT_REGISTRY.list_prompts()
    })


def _handle_prompts_get(
    request_id: Optional[Union[str, int]],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    name = params.get("name")
    if not name:
        return make_error(request_id, -32602, "Missing prompt name")

    try:
        arguments = params.get("arguments") or {}
        result = PROMPT_REGISTRY.get_prompt(name, arguments)
    except KeyError:
        return make_error(request_id, -32601, f"Prompt not found: {name}")
    except Exception as exc:
        return make_error(request_id, -32000, f"Prompt retrieval failed: {exc}")

    return make_result(request_id, result)


def _handle_resources_list(request_id: Optional[Union[str, int]]) -> Dict[str, Any]:
    return make_result(request_id, {
        "resources": RESOURCE_REGISTRY.list_resources()
    })


def _handle_resources_read(
    request_id: Optional[Union[str, int]],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    uri = params.get("uri")
    if not uri:
        return make_error(request_id, -32602, "Missing resource URI")

    try:
        result = RESOURCE_REGISTRY.read_resource(uri)
    except KeyError:
        return make_error(request_id, -32601, f"Resource not found: {uri}")
    except Exception as exc:
        return make_error(request_id, -32000, f"Resource read failed: {exc}")

    return make_result(request_id, result)
```

**Step 4:** Update `handle_request()` to dispatch the new methods. Add these branches BEFORE the final `return make_error(...)` line:

```python
    if method == "prompts/list":
        return _handle_prompts_list(request_id)

    if method == "prompts/get":
        params = payload.get("params") or {}
        return _handle_prompts_get(request_id, params)

    if method == "resources/list":
        return _handle_resources_list(request_id)

    if method == "resources/read":
        params = payload.get("params") or {}
        return _handle_resources_read(request_id, params)
```

**Verification:**
1. `./venv/bin/python -m pytest tests/ -q` — 98 tests pass
2. Start the app: `./venv/bin/python -m src.server`
3. Test with curl:
```bash
# Initialize — should show prompts + resources in capabilities
curl -s -X POST http://localhost:8081/mcp -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}' | python -m json.tool

# List prompts — should return empty list (no prompts registered yet)
curl -s -X POST http://localhost:8081/mcp -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":2,"method":"prompts/list"}' | python -m json.tool

# List resources — should return empty list
curl -s -X POST http://localhost:8081/mcp -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":3,"method":"resources/list"}' | python -m json.tool
```

**Expected `initialize` response should now include:**
```json
{
  "capabilities": {
    "tools": {},
    "prompts": {},
    "resources": {}
  }
}
```

---

### Task 1.3: Add protocol tests

**File to create:** `tests/test_mcp_prompts_resources_protocol.py`

```python
"""Tests for MCP prompts + resources protocol support."""
import pytest
from src.mcp.registry import (
    PromptSpec, PromptRegistry, ResourceSpec, ResourceRegistry,
    PROMPT_REGISTRY, RESOURCE_REGISTRY,
)
from src.mcp.protocol.jsonrpc import handle_request


# ── Registry unit tests ──────────────────────────────────────────────

def test_prompt_registry_empty():
    reg = PromptRegistry()
    assert reg.list_prompts() == []
    assert reg.has_prompt("nonexistent") is False


def test_prompt_registry_register_and_list():
    reg = PromptRegistry()
    spec = PromptSpec(
        name="test_prompt",
        description="A test prompt",
        arguments=[],
        handler=lambda args: {
            "description": "Test",
            "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
        },
    )
    reg.register(spec)
    assert reg.has_prompt("test_prompt") is True
    prompts = reg.list_prompts()
    assert len(prompts) == 1
    assert prompts[0]["name"] == "test_prompt"


def test_prompt_registry_get():
    reg = PromptRegistry()
    spec = PromptSpec(
        name="greet",
        description="Greeting prompt",
        arguments=[{"name": "name", "required": False}],
        handler=lambda args: {
            "description": "Greeting",
            "messages": [{"role": "user", "content": {"type": "text", "text": f"Hello {args.get('name', 'world')}"}}],
        },
    )
    reg.register(spec)
    result = reg.get_prompt("greet", {"name": "Alice"})
    assert result["messages"][0]["content"]["text"] == "Hello Alice"


def test_prompt_registry_get_not_found():
    reg = PromptRegistry()
    with pytest.raises(KeyError, match="Prompt not found"):
        reg.get_prompt("missing")


def test_resource_registry_empty():
    reg = ResourceRegistry()
    assert reg.list_resources() == []
    assert reg.has_resource("test://foo") is False


def test_resource_registry_register_and_list():
    reg = ResourceRegistry()
    spec = ResourceSpec(
        uri="test://doc",
        name="Test Doc",
        description="A test document",
        mime_type="text/markdown",
        handler=lambda: "# Hello",
    )
    reg.register(spec)
    assert reg.has_resource("test://doc") is True
    resources = reg.list_resources()
    assert len(resources) == 1
    assert resources[0]["uri"] == "test://doc"
    assert resources[0]["mimeType"] == "text/markdown"


def test_resource_registry_read():
    reg = ResourceRegistry()
    spec = ResourceSpec(
        uri="test://doc",
        name="Test Doc",
        description="A test document",
        mime_type="text/markdown",
        handler=lambda: "# Hello World",
    )
    reg.register(spec)
    result = reg.read_resource("test://doc")
    assert result["contents"][0]["text"] == "# Hello World"
    assert result["contents"][0]["uri"] == "test://doc"


def test_resource_registry_read_not_found():
    reg = ResourceRegistry()
    with pytest.raises(KeyError, match="Resource not found"):
        reg.read_resource("test://missing")


# ── JSON-RPC protocol tests ─────────────────────────────────────────

def _make_request(method, params=None):
    """Helper to build a JSON-RPC request dict."""
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        req["params"] = params
    return req


def test_initialize_includes_prompts_and_resources():
    """Initialize response should advertise prompts + resources capabilities."""
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("initialize"), session)
    caps = result["result"]["capabilities"]
    assert "prompts" in caps
    assert "resources" in caps
    assert "tools" in caps


def test_prompts_list_returns_result():
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("prompts/list"), session)
    assert "result" in result
    assert "prompts" in result["result"]
    assert isinstance(result["result"]["prompts"], list)


def test_prompts_get_missing_name():
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("prompts/get", {}), session)
    assert "error" in result
    assert result["error"]["code"] == -32602


def test_prompts_get_not_found():
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("prompts/get", {"name": "nonexistent"}), session)
    assert "error" in result
    assert result["error"]["code"] == -32601


def test_resources_list_returns_result():
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("resources/list"), session)
    assert "result" in result
    assert "resources" in result["result"]
    assert isinstance(result["result"]["resources"], list)


def test_resources_read_missing_uri():
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("resources/read", {}), session)
    assert "error" in result
    assert result["error"]["code"] == -32602


def test_resources_read_not_found():
    from unittest.mock import MagicMock
    session = MagicMock()
    result = handle_request(_make_request("resources/read", {"uri": "test://missing"}), session)
    assert "error" in result
    assert result["error"]["code"] == -32601
```

**Verification:**
1. `./venv/bin/python -m pytest tests/test_mcp_prompts_resources_protocol.py -v` — all tests pass
2. `./venv/bin/python -m pytest tests/ -q` — full suite passes (98 + new tests)

**Commit after Phase 1:**
```bash
git add src/mcp/registry.py src/mcp/protocol/jsonrpc.py tests/test_mcp_prompts_resources_protocol.py
git commit -m "feat: add MCP prompts + resources protocol support (prompts/list, prompts/get, resources/list, resources/read)"
```

---

## Phase 5: Assessment Tools — Fill Gaps

**Goal**: Add 5 missing tools the AI needs for the full assessment write-back workflow.

**Dependency**: None — these use the existing `ToolSpec` registration pattern. Start immediately, in parallel with Phase 1.

**Pattern to follow**: Every tool file has this structure:
1. Module docstring
2. Imports: `from ...registry import ToolSpec` and model imports from `....models`
3. `INPUT_SCHEMA` dict (JSON Schema)
4. `handle(params, session)` function → returns `Dict[str, Any]`
5. `TOOL_SPEC = ToolSpec(...)` at module bottom
6. Register in `src/mcp/registry.py` > `build_registry()`

### Task 5.1: `update_scan_result` (write tool)

**File to create:** `src/mcp/tools/core/update_result.py`

```python
"""MCP tool: update_scan_result — AI writes analysis back to a scan result.

Allows the AI to record its disposition, observations, recommendation,
severity, category, and finding details on a ScanResult.
"""

from typing import Any, Dict
from datetime import datetime

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import (
    ScanResult, ReviewStatus, Disposition, Severity, FindingCategory,
)


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "result_id": {
            "type": "integer",
            "description": "ID of the scan result to update.",
        },
        "review_status": {
            "type": "string",
            "enum": ["pending_review", "review_in_progress", "reviewed"],
            "description": "Review status.",
        },
        "disposition": {
            "type": "string",
            "enum": ["remove", "keep_as_is", "keep_and_refactor", "needs_analysis"],
            "description": "Disposition recommendation.",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Finding severity.",
        },
        "category": {
            "type": "string",
            "enum": ["customization", "code_quality", "security", "performance", "upgrade_risk", "best_practice"],
            "description": "Finding category.",
        },
        "observations": {
            "type": "string",
            "description": "AI observations about the artifact.",
        },
        "recommendation": {
            "type": "string",
            "description": "AI recommendation text.",
        },
        "finding_title": {
            "type": "string",
            "description": "Short title for the finding.",
        },
        "finding_description": {
            "type": "string",
            "description": "Detailed finding description.",
        },
    },
    "required": ["result_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    result_id = int(params["result_id"])
    result = session.get(ScanResult, result_id)
    if not result:
        raise ValueError(f"ScanResult not found: {result_id}")

    updated_fields = []

    if "review_status" in params:
        result.review_status = ReviewStatus(params["review_status"])
        updated_fields.append("review_status")

    if "disposition" in params:
        result.disposition = Disposition(params["disposition"])
        updated_fields.append("disposition")

    if "severity" in params:
        result.severity = Severity(params["severity"])
        updated_fields.append("severity")

    if "category" in params:
        result.category = FindingCategory(params["category"])
        updated_fields.append("category")

    for text_field in ("observations", "recommendation", "finding_title", "finding_description"):
        if text_field in params:
            setattr(result, text_field, params[text_field])
            updated_fields.append(text_field)

    if not updated_fields:
        return {"success": True, "message": "No fields to update.", "result_id": result_id}

    session.add(result)
    session.commit()
    session.refresh(result)

    return {
        "success": True,
        "result_id": result_id,
        "updated_fields": updated_fields,
        "message": f"Updated {len(updated_fields)} field(s) on ScanResult {result_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="update_scan_result",
    description=(
        "Update a scan result with AI analysis: disposition, severity, category, "
        "observations, recommendation, and finding details. Only specified fields "
        "are updated — omitted fields are left unchanged."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

---

### Task 5.2: `update_feature` (write tool)

**File to create:** `src/mcp/tools/core/update_feature.py`

```python
"""MCP tool: update_feature — AI writes feature-level analysis.

Allows the AI to record description, disposition, recommendation,
and ai_summary on a Feature group.
"""

from typing import Any, Dict
from datetime import datetime

from sqlmodel import Session

from ...registry import ToolSpec
from ....models import Feature, Disposition


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "ID of the feature to update.",
        },
        "name": {
            "type": "string",
            "description": "Feature name.",
        },
        "description": {
            "type": "string",
            "description": "Feature description.",
        },
        "disposition": {
            "type": "string",
            "enum": ["remove", "keep_as_is", "keep_and_refactor", "needs_analysis"],
            "description": "Overall disposition for the feature.",
        },
        "recommendation": {
            "type": "string",
            "description": "Recommendation text.",
        },
        "ai_summary": {
            "type": "string",
            "description": "AI-generated summary of the feature analysis.",
        },
    },
    "required": ["feature_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    updated_fields = []

    if "disposition" in params:
        feature.disposition = Disposition(params["disposition"])
        updated_fields.append("disposition")

    for text_field in ("name", "description", "recommendation", "ai_summary"):
        if text_field in params:
            setattr(feature, text_field, params[text_field])
            updated_fields.append(text_field)

    if not updated_fields:
        return {"success": True, "message": "No fields to update.", "feature_id": feature_id}

    feature.updated_at = datetime.utcnow()
    session.add(feature)
    session.commit()
    session.refresh(feature)

    return {
        "success": True,
        "feature_id": feature_id,
        "updated_fields": updated_fields,
        "message": f"Updated {len(updated_fields)} field(s) on Feature {feature_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="update_feature",
    description=(
        "Update a feature group with AI analysis: name, description, disposition, "
        "recommendation, and ai_summary. Only specified fields are updated."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

---

### Task 5.3: `get_feature_detail` (read tool)

**File to create:** `src/mcp/tools/core/feature_detail.py`

```python
"""MCP tool: get_feature_detail — read a feature group with linked scan results.

Returns the feature record plus its linked ScanResults (via FeatureScanResult).
"""

from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Feature, FeatureScanResult, ScanResult


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "ID of the feature to retrieve.",
        },
    },
    "required": ["feature_id"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    # Get linked scan results
    links = session.exec(
        select(FeatureScanResult).where(FeatureScanResult.feature_id == feature_id)
    ).all()

    scan_results = []
    for link in links:
        sr = session.get(ScanResult, link.scan_result_id)
        if sr:
            scan_results.append({
                "id": sr.id,
                "sys_id": sr.sys_id,
                "table_name": sr.table_name,
                "name": sr.name,
                "origin_type": sr.origin_type.value if sr.origin_type else None,
                "disposition": sr.disposition.value if sr.disposition else None,
                "review_status": sr.review_status.value if sr.review_status else None,
                "severity": sr.severity.value if sr.severity else None,
                "is_primary": link.is_primary,
                "link_notes": link.notes,
            })

    return {
        "success": True,
        "feature": {
            "id": feature.id,
            "assessment_id": feature.assessment_id,
            "name": feature.name,
            "description": feature.description,
            "parent_id": feature.parent_id,
            "disposition": feature.disposition.value if feature.disposition else None,
            "recommendation": feature.recommendation,
            "ai_summary": feature.ai_summary,
            "created_at": feature.created_at.isoformat() if feature.created_at else None,
            "updated_at": feature.updated_at.isoformat() if feature.updated_at else None,
        },
        "scan_results": scan_results,
        "scan_result_count": len(scan_results),
    }


TOOL_SPEC = ToolSpec(
    name="get_feature_detail",
    description=(
        "Get full details for a feature group including all linked scan results. "
        "Use this after group_by_feature to inspect a specific feature's contents."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
```

---

### Task 5.4: `get_update_set_contents` (read tool)

**File to create:** `src/mcp/tools/core/update_set_contents.py`

```python
"""MCP tool: get_update_set_contents — see what's in an update set.

Returns all customer_update_xml records for an update set.
Critical for feature grouping analysis — the AI needs to see what
artifacts are bundled together in an update set.
"""

from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import UpdateSet, CustomerUpdateXML


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "update_set_id": {
            "type": "integer",
            "description": "Database ID of the update set.",
        },
        "update_set_name": {
            "type": "string",
            "description": "Name of the update set (alternative to ID).",
        },
        "instance_id": {
            "type": "integer",
            "description": "Instance ID (required when using update_set_name).",
        },
        "limit": {
            "type": "integer",
            "description": "Max records to return (default 200).",
            "default": 200,
        },
    },
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    update_set_id = params.get("update_set_id")
    update_set_name = params.get("update_set_name")
    instance_id = params.get("instance_id")
    limit = min(int(params.get("limit", 200)), 1000)

    update_set = None

    if update_set_id:
        update_set = session.get(UpdateSet, int(update_set_id))
    elif update_set_name and instance_id:
        update_set = session.exec(
            select(UpdateSet).where(
                UpdateSet.name == update_set_name,
                UpdateSet.instance_id == int(instance_id),
            )
        ).first()
    else:
        raise ValueError("Provide either update_set_id or both update_set_name and instance_id.")

    if not update_set:
        raise ValueError("Update set not found.")

    # Get all customer_update_xml records for this update set
    xml_records = session.exec(
        select(CustomerUpdateXML)
        .where(CustomerUpdateXML.update_set_id == update_set.id)
        .limit(limit)
    ).all()

    contents = []
    for xml in xml_records:
        contents.append({
            "id": xml.id,
            "name": xml.name,
            "type": xml.type,
            "target_name": xml.target_name,
            "table": xml.table,
            "action": xml.action,
            "sys_created_on": xml.sys_created_on.isoformat() if xml.sys_created_on else None,
            "sys_created_by": xml.sys_created_by,
        })

    return {
        "success": True,
        "update_set": {
            "id": update_set.id,
            "name": update_set.name,
            "state": update_set.state,
            "application": update_set.application,
            "sys_created_on": update_set.sys_created_on.isoformat() if update_set.sys_created_on else None,
        },
        "contents": contents,
        "count": len(contents),
    }


TOOL_SPEC = ToolSpec(
    name="get_update_set_contents",
    description=(
        "Get all customer_update_xml records in an update set. "
        "Look up by ID or by name+instance_id. Critical for understanding "
        "what artifacts are grouped together for feature analysis."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
```

---

### Task 5.5: `save_general_recommendation` (write tool + new model)

**This task has two parts:** add a new model, then add the tool.

#### Part A: Add `GeneralRecommendation` model

**File to modify:** `src/models.py`

Add this model AFTER the `Feature` class (around line 592, before `FeatureScanResult`):

```python
class GeneralRecommendation(SQLModel, table=True):
    """Assessment-scoped general technical recommendation.

    These are high-level recommendations not tied to a specific scan result
    or feature (e.g., "Adopt OOTB alternatives for email processing",
    "Establish update set discipline").
    """
    __tablename__ = "general_recommendation"

    id: Optional[int] = Field(default=None, primary_key=True)
    assessment_id: int = Field(foreign_key="assessment.id", index=True)

    title: str
    description: Optional[str] = None
    category: Optional[str] = None  # e.g., "platform_maturity", "governance", "upgrade_risk"
    severity: Optional[Severity] = None
    created_by: str = "ai_agent"  # Who created this: ai_agent, user, etc.

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    assessment: Assessment = Relationship(back_populates="general_recommendations")
```

**Also add** the back-reference on the `Assessment` model. Find the `Assessment` class (line ~217) and add after the `features` relationship:

```python
    general_recommendations: List["GeneralRecommendation"] = Relationship(back_populates="assessment")
```

**IMPORTANT**: The SQLite DB will need the new table. Since this project doesn't use Alembic migrations, add the table creation to the startup. Find the `create_db_and_tables()` call in `src/database.py` — `SQLModel.metadata.create_all()` handles new models automatically as long as the model is imported. Verify that `GeneralRecommendation` is importable from `src.models`.

#### Part B: Add the tool

**File to create:** `src/mcp/tools/core/general_recommendation.py`

```python
"""MCP tool: save_general_recommendation — AI writes assessment-level recommendations.

General technical recommendations not tied to specific artifacts —
e.g., governance gaps, platform maturity observations, upgrade risk themes.
"""

from typing import Any, Dict
from datetime import datetime

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import GeneralRecommendation, Assessment, Severity


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "assessment_id": {
            "type": "integer",
            "description": "Assessment this recommendation belongs to.",
        },
        "title": {
            "type": "string",
            "description": "Short recommendation title.",
        },
        "description": {
            "type": "string",
            "description": "Detailed recommendation text.",
        },
        "category": {
            "type": "string",
            "description": "Category: platform_maturity, governance, upgrade_risk, performance, security, best_practice.",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low", "info"],
            "description": "Severity level.",
        },
        "created_by": {
            "type": "string",
            "description": "Who created this (default: ai_agent).",
            "default": "ai_agent",
        },
    },
    "required": ["assessment_id", "title"],
}


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    assessment_id = int(params["assessment_id"])
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        raise ValueError(f"Assessment not found: {assessment_id}")

    severity = Severity(params["severity"]) if params.get("severity") else None

    rec = GeneralRecommendation(
        assessment_id=assessment_id,
        title=params["title"],
        description=params.get("description"),
        category=params.get("category"),
        severity=severity,
        created_by=params.get("created_by", "ai_agent"),
    )

    session.add(rec)
    session.commit()
    session.refresh(rec)

    return {
        "success": True,
        "recommendation_id": rec.id,
        "title": rec.title,
        "message": f"General recommendation saved for assessment {assessment_id}.",
    }


TOOL_SPEC = ToolSpec(
    name="save_general_recommendation",
    description=(
        "Save a general technical recommendation for an assessment. "
        "These are high-level observations not tied to a specific artifact — "
        "governance gaps, platform maturity themes, upgrade risk patterns, etc."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="write",
)
```

---

### Task 5.6: Register all 5 new tools in the registry

**File to modify:** `src/mcp/registry.py`

Add imports and registrations inside `build_registry()`, AFTER the existing Level 2 pipeline section (after `registry.register(feature_grouping_tool)`):

```python
    # --- Level 1 write-back tools ---
    from .tools.core.update_result import TOOL_SPEC as update_result_tool
    from .tools.core.update_feature import TOOL_SPEC as update_feature_tool
    from .tools.core.feature_detail import TOOL_SPEC as feature_detail_tool
    from .tools.core.update_set_contents import TOOL_SPEC as update_set_contents_tool
    from .tools.core.general_recommendation import TOOL_SPEC as general_recommendation_tool

    registry.register(update_result_tool)
    registry.register(update_feature_tool)
    registry.register(feature_detail_tool)
    registry.register(update_set_contents_tool)
    registry.register(general_recommendation_tool)
```

**Verification after ALL Phase 5 tasks:**
1. `./venv/bin/python -m pytest tests/ -q` — all tests pass
2. `python -c "from src.mcp.registry import REGISTRY; tools = REGISTRY.list_tools(); print(f'{len(tools)} tools'); names = [t['name'] for t in tools]; assert 'update_scan_result' in names; assert 'update_feature' in names; assert 'get_feature_detail' in names; assert 'get_update_set_contents' in names; assert 'save_general_recommendation' in names; print('All 5 new tools registered')"` — prints count and confirmation
3. Start the app and verify via MCP console: `tools/list` should show all new tools

**Commit after Phase 5:**
```bash
git add src/mcp/tools/core/update_result.py src/mcp/tools/core/update_feature.py src/mcp/tools/core/feature_detail.py src/mcp/tools/core/update_set_contents.py src/mcp/tools/core/general_recommendation.py src/mcp/registry.py src/models.py
git commit -m "feat: add 5 assessment write-back tools (update_scan_result, update_feature, get_feature_detail, get_update_set_contents, save_general_recommendation)"
```

---

## Execution Order Summary

Both phases can run in **parallel** — they touch different files:

| Phase | Tasks | Files Created/Modified |
|-------|-------|----------------------|
| Phase 1 | 1.1, 1.2, 1.3 | `registry.py`, `jsonrpc.py`, new test file |
| Phase 5 | 5.1-5.6 | 5 new tool files, `registry.py` (different section), `models.py` |

**Only shared file:** `registry.py` — Phase 1 adds dataclasses + singletons at top/bottom, Phase 5 adds imports inside `build_registry()`. These are non-overlapping sections, but do Phase 1's `registry.py` changes first if editing sequentially.

**After both phases:**
1. `./venv/bin/python -m pytest tests/ -q` — full suite passes
2. Update the plan file: `03_outputs/plan_mcp_tools_classification_quality_2026-02-15.md` with execution status
