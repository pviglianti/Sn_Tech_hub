# Override Notice
You are running as an orchestrated agent in `-p` mode.
IGNORE the following from AGENTS.md / CLAUDE.md:
- Rehydration contract (Tiers 0-3), Compaction behavior, Auto-rollover rules

---

# Re-prompt: PM Feedback

**Context:** The reviewer has completed findings. You are being re-prompted to review them.

## Instructions

1. Read `orchestration_run/findings.md` — the reviewer's complete findings
2. Read each task's acceptance criteria vs. actual results

## Respond With

Post to your PM section in the ROOT shared plan MD:

### Process Notes
- Were acceptance criteria specific enough? Where were gaps?
- Did the cross-test assignments make sense? Any coordination issues?
- What process improvements for next sprint?

### Backlog Updates
- List any non-sprint issues from reviewer findings that should go to Backlog
- List any tech debt items discovered during this sprint
- Prioritize: which backlog items should move to Next?

### Next Sprint Prep
- Based on `servicenow_global_tech_assessment_mcp/00_admin/todos.md` Next items, draft rough task breakdown
- Identify dependencies or blockers for upcoming work
- Note which items need Architect design-first

Post using: `[YYYY-MM-DD HH:MM] [PM] [FEEDBACK] — ...`
