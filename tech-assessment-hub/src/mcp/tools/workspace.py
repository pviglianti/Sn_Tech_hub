"""MCP tools for AI workspace scaffolding and file management -- backward-compat shim.

Implementation has moved to tools/core/workspace.py.
"""

from .core.workspace import (  # noqa: F401
    SCAFFOLD_TOOL_SPEC,
    READ_FILE_TOOL_SPEC,
    UPDATE_FILE_TOOL_SPEC,
    LIST_FILES_TOOL_SPEC,
    TEMPLATE_MAP,
    WORKSPACE_FOLDERS,
    ALLOWED_BASE_PATHS,
    DEFAULT_TEMPLATES_DIR,
    handle_scaffold_workspace,
    handle_read_workspace_file,
    handle_update_workspace_file,
    handle_list_workspace_files,
    SCAFFOLD_INPUT_SCHEMA,
    READ_FILE_INPUT_SCHEMA,
    UPDATE_FILE_INPUT_SCHEMA,
    LIST_FILES_INPUT_SCHEMA,
)
