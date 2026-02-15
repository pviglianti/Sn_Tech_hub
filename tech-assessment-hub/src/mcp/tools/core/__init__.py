"""Core MCP tools -- platform-level connectivity, DB read, workspace file ops.

Tool specs are registered via registry.build_registry() which imports
directly from each tool module. This __init__.py provides convenient
re-exports for external code but uses a lazy pattern to avoid circular
imports with the registry.

Usage:
    from src.mcp.tools.core.connection import TOOL_SPEC
    from src.mcp.tools.core.inventory import TOOL_SPEC
    from src.mcp.tools.core.db_reader import TOOL_SPEC
    from src.mcp.tools.core.workspace import SCAFFOLD_TOOL_SPEC
"""


def __getattr__(name: str):
    """Lazy re-export to avoid circular imports with registry.py."""
    _exports = {
        "CONNECTION_TOOL_SPEC": (".connection", "TOOL_SPEC"),
        "INVENTORY_TOOL_SPEC": (".inventory", "TOOL_SPEC"),
        "DB_READER_TOOL_SPEC": (".db_reader", "TOOL_SPEC"),
        "SCAFFOLD_TOOL_SPEC": (".workspace", "SCAFFOLD_TOOL_SPEC"),
        "READ_FILE_TOOL_SPEC": (".workspace", "READ_FILE_TOOL_SPEC"),
        "UPDATE_FILE_TOOL_SPEC": (".workspace", "UPDATE_FILE_TOOL_SPEC"),
        "LIST_FILES_TOOL_SPEC": (".workspace", "LIST_FILES_TOOL_SPEC"),
    }
    if name in _exports:
        import importlib
        mod_name, attr = _exports[name]
        mod = importlib.import_module(mod_name, __name__)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
