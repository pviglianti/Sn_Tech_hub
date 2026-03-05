"""Tests for session-aware prompt handler support."""

from sqlmodel import Session

from src.mcp.registry import PromptSpec, PromptRegistry


def _static_handler(arguments):
    """Handler that does NOT need session (existing pattern)."""
    return {
        "description": "Static prompt",
        "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
    }


def _session_handler(arguments, session=None):
    """Handler that CAN accept session (new pattern)."""
    label = "with_session" if session is not None else "no_session"
    return {
        "description": f"Dynamic prompt ({label})",
        "messages": [{"role": "user", "content": {"type": "text", "text": f"Context: {label}"}}],
    }


def test_prompt_registry_backward_compatible():
    """Existing handlers without session parameter still work."""
    registry = PromptRegistry()
    registry.register(PromptSpec(
        name="static_test",
        description="test",
        arguments=[],
        handler=_static_handler,
    ))
    result = registry.get_prompt("static_test", {})
    assert result["description"] == "Static prompt"


def test_prompt_registry_session_passed(db_session: Session):
    """New handlers with session parameter receive it."""
    registry = PromptRegistry()
    registry.register(PromptSpec(
        name="dynamic_test",
        description="test",
        arguments=[],
        handler=_session_handler,
    ))
    result = registry.get_prompt("dynamic_test", {}, session=db_session)
    assert "with_session" in result["messages"][0]["content"]["text"]


def test_prompt_registry_session_not_required():
    """Handlers with optional session work when session is None."""
    registry = PromptRegistry()
    registry.register(PromptSpec(
        name="optional_test",
        description="test",
        arguments=[],
        handler=_session_handler,
    ))
    result = registry.get_prompt("optional_test", {})
    assert "no_session" in result["messages"][0]["content"]["text"]
