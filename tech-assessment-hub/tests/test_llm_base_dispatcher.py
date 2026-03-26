"""Tests for BaseDispatcher ABC and DispatchResult."""

import pytest
from dataclasses import asdict

from src.services.llm.base_dispatcher import BaseDispatcher, DispatchResult


def test_dispatch_result_defaults():
    r = DispatchResult(
        success=True,
        batch_index=0,
        total_batches=1,
        artifacts_processed=5,
        provider_kind="anthropic",
        model_name="claude-sonnet-4-6",
    )
    assert r.success is True
    assert r.error is None
    assert r.budget_used_usd is None
    d = asdict(r)
    assert d["provider_kind"] == "anthropic"


def test_dispatch_result_with_error():
    r = DispatchResult(
        success=False,
        batch_index=1,
        total_batches=3,
        artifacts_processed=0,
        provider_kind="google",
        model_name="gemini-2.5-pro",
        error="Timeout after 300s",
    )
    assert r.success is False
    assert r.error == "Timeout after 300s"


def test_base_dispatcher_cannot_instantiate():
    """BaseDispatcher is abstract — cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseDispatcher()


def test_effort_mapping_default():
    """Concrete subclass can use default map_effort which returns None."""

    class StubDispatcher(BaseDispatcher):
        provider_kind = "stub"

        def build_cli_command(self, prompt, model, effort, tools):
            return ["stub"]

        def parse_cli_output(self, stdout):
            return DispatchResult(
                success=True, batch_index=0, total_batches=1,
                artifacts_processed=0, provider_kind="stub", model_name="stub",
            )

        def test_cli_auth(self):
            return True, "ok"

        def test_api_key(self, api_key):
            return True, "ok"

        def fetch_models(self, auth_slot):
            return []

    d = StubDispatcher()
    assert d.map_effort("high") is None
