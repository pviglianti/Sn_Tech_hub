"""MCP tool modules.

Backward-compatibility shim: tool implementations have moved to tools/core/.
This module re-exports key symbols so existing imports continue to work.

Note: Imports are lazy (inside the __init__.py shim files in tools/*.py)
to avoid circular import chains with registry.py.
"""
