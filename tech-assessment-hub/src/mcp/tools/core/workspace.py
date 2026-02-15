"""MCP tools for AI workspace scaffolding and file management.

These tools enable AI to create and manage its own unlimited context workspace
using the /Templates/TPL_*.md files, enabling persistent memory across sessions.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from ...registry import ToolSpec


# Default templates directory (relative to project root)
DEFAULT_TEMPLATES_DIR = "/Users/pviglianti/Documents/Claude Unlimited Context/Templates"

# Template file mapping: template filename -> output filename
TEMPLATE_MAP = {
    "TPL_CONTEXT_TEMPLATE.md": "context.md",
    "TPL_TODOS_TEMPLATE.md": "todos.md",
    "TPL_INSIGHTS_TEMPLATE.md": "insights.md",
    "TPL_DELIVERABLES_SPEC_TEMPLATE.md": "deliverables_spec.md",
    "TPL_REFERENCE_INDEX_TEMPLATE.md": "reference_index.md",
    "TPL_RUN_LOG_TEMPLATE.md": "run_log.md",
    "TPL_PROMPT_FACTORY_IMPROVEMENTS_TEMPLATE.md": "prompt_factory_improvements.md",
}

# Standard folder structure for unlimited context workspace
WORKSPACE_FOLDERS = [
    "00_admin",
    "01_source_data/00_brief",
    "01_source_data/01_reference_docs",
    "01_source_data/02_exports_raw",
    "01_source_data/03_codebase_snippets",
    "01_source_data/99_inbox_drop",
    "02_working/01_notes",
    "02_working/02_intermediate_outputs",
    "02_working/03_candidate_lists",
    "02_working/04_code_search",
    "03_outputs",
]

# Allowed base paths for security (restrict where workspaces can be created)
ALLOWED_BASE_PATHS = [
    "/Users/pviglianti/Documents/Claude Unlimited Context",
    "/tmp",
]


def _is_path_allowed(path: str) -> bool:
    """Check if path is within allowed directories."""
    abs_path = os.path.abspath(path)
    for allowed in ALLOWED_BASE_PATHS:
        if abs_path.startswith(allowed):
            return True
    return False


def _customize_template(content: str, workspace_name: str) -> str:
    """Replace template placeholders with actual values."""
    today = datetime.now().strftime("%Y-%m-%d")
    replacements = {
        "[CHATNAME]": workspace_name,
        "[YYYY-MM-DD]": today,
        "(Template)": "",
    }
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return content


# ============================================
# TOOL: scaffold_workspace
# ============================================

SCAFFOLD_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "workspace_name": {
            "type": "string",
            "description": "Name for the workspace folder (e.g., 'Incident_Assessment_2026-02-01')"
        },
        "base_path": {
            "type": "string",
            "description": "Base directory where workspace will be created. Defaults to Claude Unlimited Context folder."
        },
        "templates_dir": {
            "type": "string",
            "description": "Path to templates directory. Defaults to /Templates."
        }
    },
    "required": ["workspace_name"]
}


def handle_scaffold_workspace(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    """Create a new unlimited context workspace with folder structure and templates."""
    workspace_name = params.get("workspace_name")
    if not workspace_name:
        raise ValueError("workspace_name is required")
    
    # Sanitize workspace name (remove dangerous characters)
    workspace_name = "".join(c for c in workspace_name if c.isalnum() or c in "-_ ")
    
    base_path = params.get("base_path", "/Users/pviglianti/Documents/Claude Unlimited Context")
    templates_dir = params.get("templates_dir", DEFAULT_TEMPLATES_DIR)
    
    # Security check
    if not _is_path_allowed(base_path):
        return {
            "success": False,
            "error": f"Base path not allowed: {base_path}. Allowed paths: {ALLOWED_BASE_PATHS}"
        }
    
    workspace_path = os.path.join(base_path, workspace_name)
    
    # Check if workspace already exists
    if os.path.exists(workspace_path):
        return {
            "success": False,
            "error": f"Workspace already exists: {workspace_path}"
        }
    
    try:
        files_created: List[str] = []
        folders_created: List[str] = []
        
        # Create folder structure
        for folder in WORKSPACE_FOLDERS:
            folder_path = os.path.join(workspace_path, folder)
            os.makedirs(folder_path, exist_ok=True)
            folders_created.append(folder)
        
        # Copy and customize templates
        for template_file, output_file in TEMPLATE_MAP.items():
            template_path = os.path.join(templates_dir, template_file)
            output_path = os.path.join(workspace_path, "00_admin", output_file)
            
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Customize template
                content = _customize_template(content, workspace_name)
                
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(content)
                
                files_created.append(f"00_admin/{output_file}")
        
        # Create delivery index in 03_outputs
        delivery_index_path = os.path.join(workspace_path, "03_outputs", "00_delivery_index.md")
        delivery_index_content = f"""# 03_outputs/00_delivery_index.md

## Workspace: {workspace_name}
Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## Deliverables

| # | Deliverable | Status | Path |
|---|-------------|--------|------|
| 01 | [Deliverable 1] | Not started | |
| 02 | [Deliverable 2] | Not started | |

## Notes
- Update this index as deliverables are created
- Link to actual file paths in 03_outputs/
"""
        with open(delivery_index_path, "w", encoding="utf-8") as f:
            f.write(delivery_index_content)
        files_created.append("03_outputs/00_delivery_index.md")
        
        return {
            "success": True,
            "workspace_path": workspace_path,
            "folders_created": folders_created,
            "files_created": files_created,
            "message": f"Workspace '{workspace_name}' created successfully"
        }
        
    except Exception as e:
        # Cleanup on failure
        if os.path.exists(workspace_path):
            shutil.rmtree(workspace_path, ignore_errors=True)
        return {
            "success": False,
            "error": str(e)
        }


SCAFFOLD_TOOL_SPEC = ToolSpec(
    name="scaffold_workspace",
    description="Create a new unlimited context workspace with folder structure (00_admin, 01_source_data, 02_working, 03_outputs) and populate from templates.",
    input_schema=SCAFFOLD_INPUT_SCHEMA,
    handler=handle_scaffold_workspace,
    permission="write",
)


# ============================================
# TOOL: read_workspace_file
# ============================================

READ_FILE_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to the file to read"
        }
    },
    "required": ["file_path"]
}


def handle_read_workspace_file(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    """Read contents of a workspace file."""
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path is required")
    
    # Security check
    if not _is_path_allowed(file_path):
        return {
            "success": False,
            "error": f"Path not allowed: {file_path}. Allowed paths: {ALLOWED_BASE_PATHS}"
        }
    
    if not os.path.exists(file_path):
        return {
            "success": False,
            "error": f"File not found: {file_path}"
        }
    
    if not os.path.isfile(file_path):
        return {
            "success": False,
            "error": f"Path is not a file: {file_path}"
        }
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        return {
            "success": True,
            "file_path": file_path,
            "content": content,
            "size_bytes": len(content.encode("utf-8"))
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


READ_FILE_TOOL_SPEC = ToolSpec(
    name="read_workspace_file",
    description="Read the contents of a file in an unlimited context workspace.",
    input_schema=READ_FILE_INPUT_SCHEMA,
    handler=handle_read_workspace_file,
    permission="read",
)


# ============================================
# TOOL: update_workspace_file
# ============================================

UPDATE_FILE_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to the file to update"
        },
        "content": {
            "type": "string",
            "description": "New content to write to the file"
        },
        "create_if_missing": {
            "type": "boolean",
            "description": "Create the file if it doesn't exist (default: true)",
            "default": True
        }
    },
    "required": ["file_path", "content"]
}


def handle_update_workspace_file(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    """Update (or create) a file in a workspace."""
    file_path = params.get("file_path")
    content = params.get("content")
    create_if_missing = params.get("create_if_missing", True)
    
    if not file_path:
        raise ValueError("file_path is required")
    if content is None:
        raise ValueError("content is required")
    
    # Security check
    if not _is_path_allowed(file_path):
        return {
            "success": False,
            "error": f"Path not allowed: {file_path}. Allowed paths: {ALLOWED_BASE_PATHS}"
        }
    
    file_exists = os.path.exists(file_path)
    
    if not file_exists and not create_if_missing:
        return {
            "success": False,
            "error": f"File not found and create_if_missing is False: {file_path}"
        }
    
    try:
        # Create parent directories if needed
        parent_dir = os.path.dirname(file_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        bytes_written = len(content.encode("utf-8"))
        
        return {
            "success": True,
            "file_path": file_path,
            "bytes_written": bytes_written,
            "created": not file_exists,
            "message": f"File {'created' if not file_exists else 'updated'} successfully"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


UPDATE_FILE_TOOL_SPEC = ToolSpec(
    name="update_workspace_file",
    description="Update or create a file in an unlimited context workspace. Use this to maintain context.md, todos.md, insights.md, etc.",
    input_schema=UPDATE_FILE_INPUT_SCHEMA,
    handler=handle_update_workspace_file,
    permission="write",
)


# ============================================
# TOOL: list_workspace_files
# ============================================

LIST_FILES_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "workspace_path": {
            "type": "string",
            "description": "Path to the workspace root folder"
        },
        "folder": {
            "type": "string",
            "description": "Specific subfolder to list (e.g., '00_admin', '03_outputs'). If not provided, lists all."
        }
    },
    "required": ["workspace_path"]
}


def handle_list_workspace_files(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    """List files in a workspace or specific folder."""
    workspace_path = params.get("workspace_path")
    folder = params.get("folder")
    
    if not workspace_path:
        raise ValueError("workspace_path is required")
    
    # Security check
    if not _is_path_allowed(workspace_path):
        return {
            "success": False,
            "error": f"Path not allowed: {workspace_path}. Allowed paths: {ALLOWED_BASE_PATHS}"
        }
    
    target_path = workspace_path
    if folder:
        target_path = os.path.join(workspace_path, folder)
    
    if not os.path.exists(target_path):
        return {
            "success": False,
            "error": f"Path not found: {target_path}"
        }
    
    try:
        files: List[Dict[str, Any]] = []
        
        for root, dirs, filenames in os.walk(target_path):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, workspace_path)
                stat = os.stat(file_path)
                files.append({
                    "path": rel_path,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return {
            "success": True,
            "workspace_path": workspace_path,
            "folder": folder,
            "files": files,
            "total_files": len(files)
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


LIST_FILES_TOOL_SPEC = ToolSpec(
    name="list_workspace_files",
    description="List files in an unlimited context workspace or specific subfolder.",
    input_schema=LIST_FILES_INPUT_SCHEMA,
    handler=handle_list_workspace_files,
    permission="read",
)
