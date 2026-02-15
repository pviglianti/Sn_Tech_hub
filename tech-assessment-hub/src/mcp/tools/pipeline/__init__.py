"""Pipeline stage tools -- Wave 4 target.

This package will contain the five-stage assessment pipeline:
- stage1_ingestion.py
- stage2_preprocess.py
- stage3_manifest.py
- stage4_deep_dive.py
- stage5_presentation.py

Each stage module will export TOOL_SPEC objects and handle() functions
callable from both MCP JSON-RPC and internal app orchestration.
"""
