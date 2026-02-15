# Claude Code Bootstrap Prompt (Template)

Replace:
- {CHATNAME}
- {GOAL}
- {DELIVERABLES}
- {NOTES_ON_DATA}

PASTE INTO CLAUDE CODE (Act mode):

You are operating in an “unlimited context” workflow. Your job is to externalize memory into files so we can keep chat context small and reset it frequently without losing progress.

JOB NAME
- {CHATNAME}

GOAL
- {GOAL}

DELIVERABLES (must land in 03_outputs/)
- {DELIVERABLES}

NON-NEGOTIABLES
- Files are memory. Chat is disposable.
- Do NOT wait for auto-compaction. Use proactive checkpoints.
- After every checkpoint, instruct me to run /clear.
- After /clear, you must re-ground yourself by reading the admin files before doing anything else.
- Only check items in todos.md when the referenced artifact exists on disk.
- If information is not written in 00_admin/*.md or present in 01_source_data/, treat it as unknown (do not rely on chat history).

BEFORE YOU START — CONFIRM WORKSPACE + CREATE/VERIFY STRUCTURE
1) Confirm you are operating in the correct local folder (the job workspace for {CHATNAME}).
   - If you are not in a job folder yet, create one now named: {CHATNAME}_YYYY-MM-DD and enter it.
   - This job folder should live alongside a Templates/ folder (preferred).
   - If you created the job folder elsewhere, you must still locate and use the Templates/ folder as the source of admin file templates.

2) Create this folder structure exactly (if missing):
   - 00_admin/
   - 01_source_data/00_brief
   - 01_source_data/01_reference_docs
   - 01_source_data/02_exports_raw
   - 01_source_data/03_codebase_snippets
   - 01_source_data/99_inbox_drop
   - 02_working/01_notes
   - 02_working/02_intermediate_outputs
   - 02_working/03_candidate_lists
   - 02_working/04_code_search
   - 02_working/99_tmp
   - 03_outputs/

3) Initialize 00_admin/ admin files using templates (copy, then fill placeholders):
   - If the target files already exist, do NOT overwrite them; only update placeholders.
   - Use the Template → Target mapping in the TEMPLATE SOURCE RULE section.

4) Create 03_outputs/00_delivery_index.md if missing (markdown).
   - This must list every deliverable and its final filepath when completed.
   - If a template exists for this file in Templates/, you may copy it; otherwise create a simple index stub.

TEMPLATE SOURCE RULE (IMPORTANT)
- You MUST initialize admin files by COPYING the Templates, not inventing new ones.
- Preferred: find a `Templates/` folder adjacent to the job folder, or one directory above it (common when jobs are created under a parent project folder).
- If you cannot find `Templates/`, search the local workspace for files prefixed with `TPL_` and use those.

Template → Target mapping (copy these):
- Templates/TPL_CONTEXT_TEMPLATE.md → 00_admin/context.md
- Templates/TPL_TODOS_TEMPLATE.md → 00_admin/todos.md
- Templates/TPL_INSIGHTS_TEMPLATE.md → 00_admin/insights.md
- Templates/TPL_DELIVERABLES_SPEC_TEMPLATE.md → 00_admin/deliverables_spec.md
- Templates/TPL_REFERENCE_INDEX_TEMPLATE.md → 00_admin/reference_index.md
- Templates/TPL_RUN_LOG_TEMPLATE.md → 00_admin/run_log.md
- Templates/TPL_PROMPT_FACTORY_IMPROVEMENTS_TEMPLATE.md → 00_admin/prompt_factory_improvements.md

If any template file is missing:
- Create the target file anyway, but keep it minimal and add a note in insights.md under “Missing inputs/templates”.

Regardless of template filenames, the job’s working admin filenames MUST be exactly:
- 00_admin/context.md
- 00_admin/todos.md
- 00_admin/insights.md
- 00_admin/deliverables_spec.md
- 00_admin/reference_index.md
- 00_admin/run_log.md
- 00_admin/prompt_factory_improvements.md

INITIALIZE ADMIN FILES (DO THIS BEFORE ANY ANALYSIS)
5) Fill in placeholders in 00_admin/context.md (do not rewrite the template) with:
   - Goal
   - Deliverables
   - Scope (IN / OUT)
   - Constraints / non-negotiables
   - Definitions / glossary
   - Working assumptions (must be validated)
   - Current status (last checkpoint, completed, in progress, next)

6) Fill in placeholders in 00_admin/deliverables_spec.md (do not rewrite the template) with explicit acceptance criteria for each deliverable:
   - Purpose and intended audience
   - Required sections
   - Formatting rules (headings, tables where useful)
   - Traceability rule: major claims must link to source paths or working artifacts

7) Fill in placeholders in 00_admin/todos.md (do not rewrite the template) with a full checklist for this job:
   - phases + tasks + subtasks
   - each task references an artifact path in 02_working/ or 03_outputs/
   - only check tasks when the artifact exists

8) Fill in placeholders in 00_admin/insights.md (do not rewrite the template). Ensure it contains:
   - Key decisions (with rationale + tradeoffs)
   - Extracted facts (with source paths)
   - Open questions (and how to resolve)
   - Patterns / clusters forming (if applicable)
   - “Next checkpoint instructions” (exact steps to resume after /clear)

9) Add the first entry to 00_admin/run_log.md (keep the template, just append the first entry):
   - date/time
   - what you created/initialized
   - what’s next (inventory)

INVENTORY SOURCE DATA (NO DEEP WORK YET)
10) Scan 01_source_data/ recursively and list everything found.
11) Fill 00_admin/reference_index.md with a line-item inventory for every file:
   - path
   - type (reference_doc | export_raw | code_snippet | brief | unknown)
   - 1-line summary
   - priority (high/med/low)
   - how it will be used (authoritative guidance | data input | background)
12) If anything required for the goal is missing, add a “Missing inputs” section to insights.md.

WORK LOOP (SMALL BATCHES ONLY)
13) Process work in small batches. A batch must be small enough to checkpoint cleanly.
    For each batch:
   - read only the relevant files for that batch
   - write any extraction tables/drafts into 02_working/
   - write any final-ready content into 03_outputs/
   - append detailed findings, decisions, and open questions to insights.md
   - update todos.md (check items only when artifacts exist)
   - update context.md ONLY if it materially improves future output
   - update run_log.md with: what processed / what changed / what next

PROACTIVE CHECKPOINT RULE (MOST IMPORTANT)
14) Do NOT wait for auto-compaction.
    After EVERY batch, do a checkpoint in this exact order:
   1) Update insights.md (detailed)
   2) Update todos.md (truthful checkboxes)
   3) Update context.md only if needed
   4) Ensure artifacts are saved in 02_working/ or 03_outputs/
   5) Update run_log.md

15) After the checkpoint, STOP immediately and tell me exactly this single line (verbatim):
   Checkpoint complete. Run /clear now.

15a) After you say that line, do NOT do any additional work until the chat has been cleared and you have re-read the admin files.

RESET / RESUME RULE (AFTER /clear OR AUTO-COMPACTION)
16) After /clear (or auto-compaction), you MUST do this before any new work (in this exact order):
   - Read 00_admin/context.md
   - Read 00_admin/todos.md
   - Read 00_admin/insights.md
   - Read 00_admin/run_log.md
   - Then continue at the next unchecked todo item.

QUALITY BAR
- Before complex synthesis, clustering, or recommendations, write the word “think” and reason carefully.
- If uncertain, write it to insights.md as an open question with what would resolve it.
- Do not let chat history become memory. Files are memory.

END-OF-JOB IMPROVEMENT OUTPUT (REQUIRED)
17) Maintain 00_admin/prompt_factory_improvements.md as you go and finalize it at the end:
   - What worked
   - What failed / was inefficient
   - Changes to templates (actionable edits)
   - Changes to prompts (actionable edits)
   - Workflow changes (actionable edits)
   - Reusable prompt fragments/snippets discovered

NOTES ON DATA
- {NOTES_ON_DATA}

START NOW:
Complete steps 1–12 only (setup + inventory). Then STOP and ask me to confirm the inventory, missing inputs/templates, and the deliverables list before you begin analysis.