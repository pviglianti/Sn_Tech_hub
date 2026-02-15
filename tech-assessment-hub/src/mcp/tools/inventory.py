"""MCP tool: sn_inventory_summary -- backward-compat shim.

Implementation has moved to tools/core/inventory.py.
"""

from .core.inventory import (  # noqa: F401
    TOOL_SPEC,
    INPUT_SCHEMA,
    handle,
)
