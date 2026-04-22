---
name: report
description: >
  Generate the final technical assessment report as Excel (.xlsx) and Word (.docx)
  deliverables. Files are produced server-side, attached to the assessment, and
  visible in the Reports panel of the assessment page.
allowed-tools: mcp__tech-assessment-hub__get_assessment_context mcp__tech-assessment-hub__generate_assessment_report mcp__tech-assessment-hub__advance_pipeline
---

# Assessment Report Generation

**⚠ TOOL LOCK — read first.**
Your only toolbox is `mcp__tech-assessment-hub__*`. Do NOT use `Bash`, `curl`,
`Read`, `Glob`, `Grep`, `Write`, `WebFetch`, or `WebSearch`. The report
generation is server-side — you only need to call
`mcp__tech-assessment-hub__generate_assessment_report`. If it fails, retry the
same MCP tool; do not fall back to shell or curl.

Generate deliverable files via the **server-side** report tool. Files are persisted on the VM, registered in the database, and exposed via the Reports panel on the assessment detail page.

## Setup

1. Get assessment ID from user or `$ARGUMENTS`.
2. **Call `get_assessment_context(assessment_id)`** — confirm the assessment exists, capture target app + pipeline stage. Sanity-check the pipeline stage: report generation should run after recommendations.

## Generate the report

Call:

```
generate_assessment_report(assessment_id=<id>, formats=["xlsx", "docx"])
```

Optional: pass `generated_by` to record what triggered it (e.g., `"report skill via Claude Desktop"`).

The tool builds both files server-side, persists `AssessmentReport` rows, and returns a list with download URLs. **You do NOT write a Python script. You do NOT need filesystem access.** Everything runs on the VM.

## What gets produced

### Excel workbook (`assessment_{number}_{timestamp}.xlsx`)
- **Tab 1: Executive Summary** — assessment metadata, scope, totals
- **Tab 2: Feature Inventory** — name, description, artifact count, risk level, recommendation, AI summary (sorted by artifact count desc)
- **Tab 3: In-Scope Customizations** — every in-scope + adjacent artifact with feature assignment, observations, recommendation
- **Tab 4: Out of Scope** — for completeness

### Word document (`assessment_{number}_{timestamp}.docx`)
- Title page + executive summary
- Feature-by-feature analysis (sorted by artifact count)
- Appendix: artifact counts by table

## After generating

Tell the user:

> ✅ Reports generated. View them on the assessment page:
> https://136-112-232-229.nip.io/assessments/{assessment_id}
>
> Or download directly:
> - Excel: https://136-112-232-229.nip.io/api/reports/{xlsx_report_id}/download
> - Word:  https://136-112-232-229.nip.io/api/reports/{docx_report_id}/download

(Substitute the actual IDs from the tool response.)

## Re-generation

Calling `generate_assessment_report` again creates **new** report files with a fresh timestamp. The old reports are kept (visible in the Reports panel as history) until manually cleaned up. This is intentional — you can always go back to a prior version.

## Iterative Refinement Rules

Reports are derived from the artifact/feature observations and recommendations already in the DB. If those need refinement, do that in the appropriate stage (observations / recommendations) and re-generate the report — don't try to "fix" the report by editing the file directly.

## Advance Pipeline (Required — do this LAST)

When the user is happy with the report, mark the assessment complete:

```
mcp__tech-assessment-hub__advance_pipeline(
    assessment_id=<id>,
    target_stage="complete"
)
```

Do NOT use Bash/curl — it's disabled in this session.
