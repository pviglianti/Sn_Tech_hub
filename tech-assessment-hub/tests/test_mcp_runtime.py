from unittest.mock import patch

from src.mcp.runtime.capabilities import get_capability_snapshot
from src.mcp.runtime.registry import ToolRoute, load_runtime_config, save_runtime_config
from src.mcp.runtime.router import RuntimeRouter


def test_runtime_config_roundtrip(db_session):
    defaults = load_runtime_config(db_session)
    assert defaults["default_engine"] == "python"
    assert "engine_priority" in defaults

    saved = save_runtime_config(
        db_session,
        {
            "engine_priority": {"python": 80, "ts_sidecar": 120},
            "tool_routes": {"sqlite_query": "python"},
        },
    )
    assert saved["engine_priority"]["ts_sidecar"] == 120
    assert saved["tool_routes"]["sqlite_query"] == "python"

    loaded = load_runtime_config(db_session)
    assert loaded["engine_priority"]["ts_sidecar"] == 120


def test_capability_snapshot_hides_engine_metadata(db_session):
    with patch("src.mcp.runtime.capabilities._fetch_remote_tools", return_value=([], {"success": False})):
        snapshot = get_capability_snapshot(db_session, include_admin=False)

    assert snapshot["tools"]
    first = snapshot["tools"][0]
    assert "name" in first
    assert "inputSchema" in first
    assert "selected_route" not in first
    assert "engine" not in first


def test_router_executes_python_tool(db_session):
    router = RuntimeRouter()
    with patch.object(
        RuntimeRouter,
        "_selected_route_for_tool",
        return_value=ToolRoute(
            engine="python",
            target="sqlite_query",
            timeout_ms=12000,
            retry_policy={"max_retries": 0},
            priority=100,
        ),
    ):
        result = router.call_tool(
            "sqlite_query",
            {"sql": "SELECT name FROM sqlite_master WHERE type='table'", "max_rows": 10},
            db_session,
            actor="unit_test",
        )
    assert result.success is True
    assert result.engine_used == "python"


def test_router_returns_unavailable_for_ts_sidecar_recovery(db_session):
    router = RuntimeRouter()
    with patch.object(
        RuntimeRouter,
        "_selected_route_for_tool",
        return_value=ToolRoute(
            engine="ts_sidecar",
            target="remote_tool",
            timeout_ms=12000,
            retry_policy={"max_retries": 0},
            priority=100,
        ),
    ), patch("src.mcp.runtime.router.BRIDGE_MANAGER.can_attempt_tool_call", return_value=False), patch(
        "src.mcp.runtime.router.BRIDGE_MANAGER.maybe_auto_restart", return_value={"success": True}
    ):
        result = router.call_tool("remote_tool", {}, db_session, actor="unit_test")

    assert result.success is False
    assert result.error_code == "tool_temporarily_unavailable"
    assert result.degraded is True
