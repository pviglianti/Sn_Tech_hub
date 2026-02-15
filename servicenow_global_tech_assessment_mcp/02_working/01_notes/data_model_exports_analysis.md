# data_model_exports_analysis.md

## Purpose
Concise working summary for data-model/export analysis.

## Key Findings
- Core extraction relationships center on metadata, version history, update XML, update set, and classification joins.
- Reliable delta behavior requires consistent `sys_updated_on` + `sys_id` ordering.
- Evidence quality depends on preserving lineage between raw export fields and normalized local tables.

## Current Relevance
- Use this note for planned deliverables:
  - `03_outputs/03_servicenow_data_model_relationships.md`
  - `03_outputs/04_instance_data_extraction_plan.md`

## Follow-Up Needed
- Validate current assumptions against latest runtime pulls before finalizing deliverables.
- Keep table/field mapping examples in implementation docs, not in admin rehydration paths.

## Archive Note
Full analysis content archived on 2026-02-14:
`/Users/pviglianti/Library/Mobile Documents/com~apple~CloudDocs/Cloud Archive/2026-02-14_core_md_compression_round4/servicenow_global_tech_assessment_mcp/02_working/01_notes/data_model_exports_analysis.md`
