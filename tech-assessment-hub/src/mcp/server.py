"""MCP JSON-RPC request handler — backward-compatible shim.

The actual implementation has moved to src/mcp/protocol/jsonrpc.py.
This module re-exports for backward compatibility.
"""

# Re-export for backward compatibility
from .protocol.jsonrpc import handle_request  # noqa: F401
from .protocol.schemas import PROTOCOL_VERSION, SERVER_INFO  # noqa: F401
from .protocol.errors import make_error, make_result  # noqa: F401
