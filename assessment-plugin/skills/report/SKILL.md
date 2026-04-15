---
name: report
description: >
  Generate the final technical assessment report as Excel (.xlsx) and Word (.docx)
  deliverables. Produces executive summary, feature inventory, full artifact
  detail, and recommendations. Use after all other pipeline stages are complete.
allowed-tools: mcp__tech-assessment-hub__get_customizations mcp__tech-assessment-hub__get_result_detail mcp__tech-assessment-hub__get_features mcp__tech-assessment-hub__query_instance_live Bash Write Read
---

# Assessment Report Generation

Generate deliverable files: an Excel workbook and a Word document.

## CRITICAL: How to generate the files

Do NOT use sandbox or base64 transfers. Write a single Python script to
`/tmp/generate_report.py` and execute it with:

```bash
/Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/venv/bin/python /tmp/generate_report.py
```

The script should connect to the SQLite database DIRECTLY at:
`/Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/tech_assessment.db`

Output files go to:
`/Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/reports/`

## Setup
1. Get assessment ID from user or $ARGUMENTS
2. Write the Python script that queries the DB and generates both files
3. Run it via the venv Python

## Excel Workbook (`assessment_{id}_report.xlsx`)

Use `openpyxl`. The script should query the DB directly (sqlite3 + sqlalchemy).

**Tab 1: Executive Summary**
- Assessment name, target app, target tables
- Total scanned, customized, in-scope, out-of-scope, adjacent
- Feature count, top features by artifact count
- Overall risk level

**Tab 2: Feature Inventory**
Columns: Feature Name | Description | Artifact Count | Types | Disposition | Risk Level | Key Risks | OOTB Alternative | AI Summary
One row per feature, sorted by artifact count descending.

**Tab 3: In-Scope Customizations**
ALL in-scope and adjacent artifacts (is_out_of_scope != true).
Columns: ID | Name | Table | sys_class_name | Origin Type | Scope (in_scope/adjacent) | Feature Name | Observations | Recommendation | AI Scope Rationale
One row per artifact. This is the main working tab.

**Tab 4: Out of Scope**
Columns: ID | Name | Table | sys_class_name | Origin Type | Observations
One row per out-of-scope artifact.

**Tab 5: Risk Matrix**
Columns: Risk Category | Count | Severity | Affected Features | Examples

**Formatting:**
- Header row: bold, frozen, auto-filter
- Column widths: auto-fit or sensible defaults
- Feature name column: color-coded by feature (use color_index from feature table)

## Word Document (`assessment_{id}_report.docx`)

Use `python-docx`.

1. Title page — assessment name, date
2. Executive Summary — key metrics, top 5 findings
3. Feature-by-Feature Analysis — each feature:
   - Name, description, artifact count
   - Disposition recommendation with rationale
   - Risk level and key concerns
   - OOTB replacement opportunities
4. Systemic Findings — cross-feature patterns
5. Recommendations — priority-ordered action items
6. Appendix — artifact count by table/type

## The Python Script Pattern

```python
import sqlite3, json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from docx import Document

DB = "/Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/tech_assessment.db"
OUT = Path("/Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/reports")
OUT.mkdir(exist_ok=True)
ASSESSMENT_ID = 24  # or from sys.argv

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Query assessment, features, artifacts, then build both files...
```

## Rules
- Ground every finding in data — cite specific artifacts
- Do not fabricate findings
- Write for a technical decision-maker
- The In-Scope Customizations tab is the most important — it must have every
  in-scope artifact with its feature assignment and observations

## Iterative Refinement Rules

- Observations on both artifacts and features should be REFINED each pass, not
  replaced. Read what exists first. Add to it, tighten it, correct errors — but
  never blank out or lose prior context.
- Reference artifacts and records by their NAME, not sys_id. Use sys_ids only
  in structured fields (ai_observations JSON, directly_related_result_ids).
  Human-readable text (observations, recommendations, descriptions) should say
  "Business Rule: Reset Assignment Group On Reopen" not "sys_id: abc123...".
- When referencing other artifacts in observations, use the pattern:
  "Related to <Name> (<table>)" — e.g. "Related to Set Assigned (sys_script)".


## Advance Pipeline (Required — do this LAST)

When you have finished ALL work for this stage, advance the pipeline by running:

```bash
curl -s -X POST http://127.0.0.1:$(cat /Volumes/SN_TA_MCP/SN_TechAssessment_Hub_App/tech-assessment-hub/data/server.url | sed 's|.*:||' | sed 's|/.*||')/api/assessments/${ASSESSMENT_ID}/advance-pipeline \
  -H "Content-Type: application/json" \
  -d '{"target_stage": "complete", "force": true}'
```

This updates the pipeline stage in the app UI so the next stage button appears.
Do NOT skip this step.
