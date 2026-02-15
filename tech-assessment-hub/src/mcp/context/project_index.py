"""Project index loading helpers.

Provides utilities for loading and querying the 00_Index-first project
structure used by the unlimited context workspace pattern. Enables MCP
tools to discover available context files, their modification timestamps,
and relevance scores for stage-aware loading.

Wave 4 target -- stub only.
"""

from typing import Any, Dict, List


def load_project_index(workspace_path: str) -> Dict[str, Any]:
    """Load and parse the project index from a workspace path.

    Args:
        workspace_path: Absolute path to the workspace root.

    Returns:
        Dictionary with index metadata (files, timestamps, structure).
    """
    raise NotImplementedError("project_index.load_project_index is a Wave 4 stub")


def list_context_files(workspace_path: str, folder: str = "00_admin") -> List[str]:
    """List context-relevant files in a workspace subfolder.

    Args:
        workspace_path: Absolute path to the workspace root.
        folder: Subfolder to scan (default: 00_admin).

    Returns:
        List of file paths relative to the workspace root.
    """
    raise NotImplementedError("project_index.list_context_files is a Wave 4 stub")
