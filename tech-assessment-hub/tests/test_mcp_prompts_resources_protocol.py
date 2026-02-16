"""Tests for MCP prompts + resources protocol support."""

import pytest

from src.mcp.registry import (
    PROMPT_REGISTRY,
    RESOURCE_REGISTRY,
    PromptRegistry,
    PromptSpec,
    ResourceRegistry,
    ResourceSpec,
)
from src.mcp.protocol.jsonrpc import handle_request


@pytest.fixture(autouse=True)
def _clear_global_prompt_resource_registries():
    """Keep global prompt/resource registries isolated across tests."""
    old_prompts = dict(PROMPT_REGISTRY._prompts)
    old_resources = dict(RESOURCE_REGISTRY._resources)
    PROMPT_REGISTRY._prompts.clear()
    RESOURCE_REGISTRY._resources.clear()
    try:
        yield
    finally:
        PROMPT_REGISTRY._prompts.clear()
        PROMPT_REGISTRY._prompts.update(old_prompts)
        RESOURCE_REGISTRY._resources.clear()
        RESOURCE_REGISTRY._resources.update(old_resources)


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


def test_initialize_includes_prompts_and_resources(db_session):
    """Initialize response should advertise prompts + resources capabilities."""
    result = handle_request(_make_request("initialize"), db_session)
    caps = result["result"]["capabilities"]
    assert "prompts" in caps
    assert "resources" in caps
    assert "tools" in caps


def test_prompts_list_returns_result(db_session):
    result = handle_request(_make_request("prompts/list"), db_session)
    assert "result" in result
    assert "prompts" in result["result"]
    assert isinstance(result["result"]["prompts"], list)


def test_prompts_get_missing_name(db_session):
    result = handle_request(_make_request("prompts/get", {}), db_session)
    assert "error" in result
    assert result["error"]["code"] == -32602


def test_prompts_get_not_found(db_session):
    result = handle_request(_make_request("prompts/get", {"name": "nonexistent"}), db_session)
    assert "error" in result
    assert result["error"]["code"] == -32601


def test_resources_list_returns_result(db_session):
    result = handle_request(_make_request("resources/list"), db_session)
    assert "result" in result
    assert "resources" in result["result"]
    assert isinstance(result["result"]["resources"], list)


def test_resources_read_missing_uri(db_session):
    result = handle_request(_make_request("resources/read", {}), db_session)
    assert "error" in result
    assert result["error"]["code"] == -32602


def test_resources_read_not_found(db_session):
    result = handle_request(_make_request("resources/read", {"uri": "test://missing"}), db_session)
    assert "error" in result
    assert result["error"]["code"] == -32601
