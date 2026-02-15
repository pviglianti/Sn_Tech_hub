"""MCP tool: sqlite_query -- backward-compat shim.

Implementation has moved to tools/core/db_reader.py.
"""

from .core.db_reader import (  # noqa: F401
    TOOL_SPEC,
    INPUT_SCHEMA,
    FORBIDDEN_KEYWORDS,
    handle,
)
