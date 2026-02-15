"""Permission checks for MCP tool execution.

Wave 2 scaffold — all calls pass (permissive default).
Hook into the router execution path so the permission gate is in place
for Wave 3+ when role-based access is needed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Permission levels
PERMISSION_READ = "read"
PERMISSION_WRITE = "write"
PERMISSION_ADMIN = "admin"

PERMISSION_LEVELS = {PERMISSION_READ, PERMISSION_WRITE, PERMISSION_ADMIN}

# Permission hierarchy: admin > write > read
PERMISSION_HIERARCHY = {
    PERMISSION_READ: 0,
    PERMISSION_WRITE: 1,
    PERMISSION_ADMIN: 2,
}


def check_permission(
    tool_name: str,
    required_permission: str = PERMISSION_READ,
    user_context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Check whether the current user context has sufficient permission.

    Args:
        tool_name: Name of the tool being invoked.
        required_permission: Minimum permission level required (read/write/admin).
        user_context: Dict with at least ``role`` key (e.g. {"role": "admin"}).

    Returns:
        True if the call is allowed.

    Note:
        Wave 2 scaffold — always returns True (permissive default).
        Replace with real logic in Wave 3+.
    """
    # Permissive default: all calls pass
    return True


class PermissionDeniedError(Exception):
    """Raised when a tool call fails the permission check."""

    def __init__(self, tool_name: str, required: str, actual: str = "unknown") -> None:
        self.tool_name = tool_name
        self.required = required
        self.actual = actual
        super().__init__(
            f"Permission denied for tool '{tool_name}': requires '{required}', user has '{actual}'"
        )
