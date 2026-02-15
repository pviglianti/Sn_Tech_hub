"""MCP tool: sn_test_connection -- backward-compat shim.

Implementation has moved to tools/core/connection.py.
"""

from .core.connection import (  # noqa: F401
    TOOL_SPEC,
    INPUT_SCHEMA,
    handle,
)
