"""MCP bridge submodule — sidecar lifecycle, RPC, and config.

Re-exports key symbols for backward compatibility with code that imports
from ``src.mcp.bridge``.
"""

from .config_store import (  # noqa: F401
    CONFIG_KEY,
    default_bridge_config,
    load_bridge_config,
    save_bridge_config,
)
from .manager import (  # noqa: F401
    BRIDGE_MANAGER,
    MCPBridgeManager,
)
