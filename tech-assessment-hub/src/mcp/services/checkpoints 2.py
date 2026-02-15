"""Checkpoint hooks before compaction/clear events.

Provides hooks that fire before context compaction or clear operations
to ensure all in-flight state is persisted to the file-backed memory
system (00_admin/ files, 02_working/ notes, etc.).

Wave 4 target -- stub only.
"""

from typing import Any, Dict, Optional


def pre_compaction_checkpoint(
    workspace_path: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Checkpoint all in-flight state before a context compaction.

    Args:
        workspace_path: Absolute path to the workspace root.
        run_id: Optional active run to checkpoint.

    Returns:
        Dictionary with checkpoint result (files_updated, warnings).
    """
    raise NotImplementedError("checkpoints.pre_compaction_checkpoint is a Wave 4 stub")


def pre_clear_checkpoint(
    workspace_path: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Emergency checkpoint before a context clear.

    Args:
        workspace_path: Absolute path to the workspace root.
        run_id: Optional active run to checkpoint.

    Returns:
        Dictionary with checkpoint result (files_updated, warnings).
    """
    raise NotImplementedError("checkpoints.pre_clear_checkpoint is a Wave 4 stub")
