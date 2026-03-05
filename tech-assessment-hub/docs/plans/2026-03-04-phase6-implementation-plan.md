# Phase 6 — MCP Skills/Prompts Library Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 new MCP prompts with dynamic context injection, an admin-editable BestPractice model with ~41 seed checks, and the prompt infrastructure to support session-aware handlers.

**Architecture:** New `BestPractice` SQLModel table seeded at startup. Extended `PromptSpec` handler signature to optionally accept a DB session. Four new prompt files with handlers that query the database and inject artifact data, signals, relationships, and best-practice checklists into prompt text before returning to the MCP client.

**Tech Stack:** Python 3, SQLModel, FastAPI, Jinja2 templates, pytest

**Design Doc:** `docs/plans/2026-03-04-phase6-mcp-skills-library-design.md`

**Test Runner:** `./venv/bin/python -m pytest` (from project root)

---

## Task 1: Add BestPracticeCategory Enum + BestPractice Model

**Files:**
- Modify: `src/models.py` (after line 1708, end of file)

**Step 1: Write the failing test**

Create: `tests/test_best_practice_model.py`

```python
"""Tests for the BestPractice model."""

import pytest
from sqlmodel import Session, select

from src.models import BestPractice, BestPracticeCategory


def test_best_practice_category_enum_values():
    assert BestPracticeCategory.technical_server == "technical_server"
    assert BestPracticeCategory.technical_client == "technical_client"
    assert BestPracticeCategory.architecture == "architecture"
    assert BestPracticeCategory.process == "process"
    assert BestPracticeCategory.security == "security"
    assert BestPracticeCategory.performance == "performance"
    assert BestPracticeCategory.upgradeability == "upgradeability"
    assert BestPracticeCategory.catalog == "catalog"
    assert BestPracticeCategory.integration == "integration"


def test_best_practice_create(db_session: Session):
    bp = BestPractice(
        code="TEST_001",
        title="Test Best Practice",
        category=BestPracticeCategory.technical_server,
        severity="high",
        description="A test best practice.",
        detection_hint="Look for test pattern",
        recommendation="Do something else",
        is_active=True,
    )
    db_session.add(bp)
    db_session.commit()
    db_session.refresh(bp)

    assert bp.id is not None
    assert bp.code == "TEST_001"
    assert bp.category == BestPracticeCategory.technical_server
    assert bp.is_active is True


def test_best_practice_unique_code(db_session: Session):
    bp1 = BestPractice(
        code="UNIQUE_001",
        title="First",
        category=BestPracticeCategory.process,
        severity="medium",
    )
    db_session.add(bp1)
    db_session.commit()

    bp2 = BestPractice(
        code="UNIQUE_001",
        title="Duplicate",
        category=BestPracticeCategory.process,
        severity="medium",
    )
    db_session.add(bp2)
    with pytest.raises(Exception):
        db_session.commit()


def test_best_practice_defaults(db_session: Session):
    bp = BestPractice(
        code="DEFAULTS_001",
        title="Defaults Test",
        category=BestPracticeCategory.security,
        severity="low",
    )
    db_session.add(bp)
    db_session.commit()
    db_session.refresh(bp)

    assert bp.is_active is True
    assert bp.description is None
    assert bp.applies_to is None
    assert bp.source_url is None
    assert bp.created_at is not None
    assert bp.updated_at is not None


def test_best_practice_filter_by_category(db_session: Session):
    for i, cat in enumerate(["technical_server", "technical_client", "architecture"]):
        db_session.add(BestPractice(
            code=f"FILTER_{i}",
            title=f"Filter test {i}",
            category=BestPracticeCategory(cat),
            severity="medium",
        ))
    db_session.commit()

    server_bps = db_session.exec(
        select(BestPractice).where(
            BestPractice.category == BestPracticeCategory.technical_server
        )
    ).all()
    assert len(server_bps) == 1
    assert server_bps[0].code == "FILTER_0"
```

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_best_practice_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'BestPractice'`

**Step 3: Add BestPracticeCategory enum and BestPractice model**

Add to `src/models.py` after the `NumberSequence` class (after line 1708):

```python
class BestPracticeCategory(str, Enum):
    """Categories for ServiceNow best practice checks."""
    technical_server = "technical_server"
    technical_client = "technical_client"
    architecture = "architecture"
    process = "process"
    security = "security"
    performance = "performance"
    upgradeability = "upgradeability"
    catalog = "catalog"
    integration = "integration"


class BestPractice(SQLModel, table=True):
    """Admin-editable ServiceNow best practice check.

    Used by the technical_architect prompt to evaluate artifacts
    and produce assessment-wide technical findings.
    """
    __tablename__ = "best_practice"

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    title: str
    category: BestPracticeCategory
    severity: str = "medium"  # Uses Severity values but stored as str for flexibility
    description: Optional[str] = None
    detection_hint: Optional[str] = None
    recommendation: Optional[str] = None
    applies_to: Optional[str] = None  # Comma-separated sys_class_name values, or null = all
    is_active: bool = Field(default=True)
    source_url: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

**Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_best_practice_model.py -v`
Expected: All 5 tests PASS

**Step 5: Run full test suite**

Run: `./venv/bin/python -m pytest -v`
Expected: All existing tests still PASS

**Step 6: Commit**

```bash
git add src/models.py tests/test_best_practice_model.py
git commit -m "feat: add BestPractice model and BestPracticeCategory enum"
```

---

## Task 2: Add BestPractice Seed Data

**Files:**
- Modify: `src/seed_data.py` (add `seed_best_practices` function)
- Modify: `src/database.py` (call seed at startup)

**Step 1: Write the failing test**

Create: `tests/test_best_practice_seed.py`

```python
"""Tests for BestPractice seed data."""

from sqlmodel import Session, select

from src.models import BestPractice, BestPracticeCategory
from src.seed_data import seed_best_practices


def test_seed_best_practices_creates_records(db_session: Session):
    seed_best_practices(db_session)
    all_bps = db_session.exec(select(BestPractice)).all()
    assert len(all_bps) >= 40  # Design calls for ~41 seed checks


def test_seed_best_practices_idempotent(db_session: Session):
    seed_best_practices(db_session)
    count_1 = len(db_session.exec(select(BestPractice)).all())
    seed_best_practices(db_session)
    count_2 = len(db_session.exec(select(BestPractice)).all())
    assert count_1 == count_2  # Running twice doesn't duplicate


def test_seed_best_practices_all_categories_covered(db_session: Session):
    seed_best_practices(db_session)
    all_bps = db_session.exec(select(BestPractice)).all()
    categories_present = {bp.category for bp in all_bps}
    # At minimum: technical_server, technical_client, architecture, process, security, performance, upgradeability
    expected = {
        BestPracticeCategory.technical_server,
        BestPracticeCategory.technical_client,
        BestPracticeCategory.architecture,
        BestPracticeCategory.process,
        BestPracticeCategory.security,
        BestPracticeCategory.performance,
        BestPracticeCategory.upgradeability,
    }
    assert expected.issubset(categories_present)


def test_seed_best_practices_codes_unique(db_session: Session):
    seed_best_practices(db_session)
    all_bps = db_session.exec(select(BestPractice)).all()
    codes = [bp.code for bp in all_bps]
    assert len(codes) == len(set(codes))  # No duplicate codes


def test_seed_best_practices_critical_checks_present(db_session: Session):
    seed_best_practices(db_session)
    critical_codes = {"SRV_CURRENT_UPDATE_BEFORE", "SRV_CURRENT_UPDATE_AFTER",
                      "ARCH_EXTEND_CORE_TABLE", "SEC_CREDENTIALS_IN_CODE"}
    all_codes = {bp.code for bp in db_session.exec(select(BestPractice)).all()}
    assert critical_codes.issubset(all_codes)
```

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_best_practice_seed.py -v`
Expected: FAIL — `ImportError: cannot import name 'seed_best_practices'`

**Step 3: Implement seed_best_practices in seed_data.py**

Add to `src/seed_data.py` (before the `run_seed` function):

```python
from .models import BestPractice, BestPracticeCategory


def seed_best_practices(session: Session):
    """Seed the BestPractice table with ServiceNow best practice checks.

    Idempotent — skips records whose code already exists.
    """
    existing_codes = {
        row.code
        for row in session.exec(select(BestPractice)).all()
    }

    checks = [
        # ── Technical — Server Side ──
        {
            "code": "SRV_CURRENT_UPDATE_BEFORE",
            "title": "current.update() in Before Business Rules",
            "category": BestPracticeCategory.technical_server,
            "severity": "critical",
            "description": "current.update() should never be used in Before Business Rules. ServiceNow automatically saves all values on current after Before BR execution completes.",
            "detection_hint": "current.update() in sys_script where when=before",
            "recommendation": "Remove current.update() — values set on current object are auto-saved after Before BR completes.",
            "applies_to": "sys_script",
            "source_url": "https://www.servicenow.com/community/developer-blog/never-use-current-update-in-a-business-rule/ba-p/2274329",
        },
        {
            "code": "SRV_CURRENT_UPDATE_AFTER",
            "title": "current.update() in After Business Rules",
            "category": BestPracticeCategory.technical_server,
            "severity": "critical",
            "description": "current.update() in After Business Rules causes a double-update and can trigger recursive BR execution.",
            "detection_hint": "current.update() in sys_script where when=after",
            "recommendation": "Use workflow/flow or async BR to update related records. If updating current is truly needed, use a Before BR instead.",
            "applies_to": "sys_script",
            "source_url": "https://www.servicenow.com/community/developer-blog/never-use-current-update-in-a-business-rule/ba-p/2274329",
        },
        {
            "code": "SRV_CURRENT_UPDATE_NO_WORKFLOW",
            "title": "current.update() without setWorkflow(false)",
            "category": BestPracticeCategory.technical_server,
            "severity": "critical",
            "description": "current.update() without setWorkflow(false) triggers all business rules again, potentially causing infinite recursion.",
            "detection_hint": "current.update() without nearby setWorkflow(false)",
            "recommendation": "If current.update() is absolutely needed, call current.setWorkflow(false) first. But prefer Before BR pattern instead.",
            "applies_to": "sys_script",
        },
        {
            "code": "SRV_GLIDERECORD_IN_LOOP",
            "title": "GlideRecord queries inside loops",
            "category": BestPracticeCategory.technical_server,
            "severity": "high",
            "description": "Querying the database inside a loop causes N+1 performance problems. Each iteration creates a new database query.",
            "detection_hint": "GlideRecord constructor or .query() inside while/for loop body",
            "recommendation": "Build a list of values first, then query once using the IN operator. Or use GlideAggregate for counts/sums.",
            "source_url": "https://www.servicenow.com/community/developer-articles/performance-best-practices-for-server-side-coding-in-servicenow/ta-p/2324426",
        },
        {
            "code": "SRV_NO_TRY_CATCH",
            "title": "No error handling in server scripts",
            "category": BestPracticeCategory.technical_server,
            "severity": "medium",
            "description": "Server-side scripts without try/catch blocks may fail silently or produce unhelpful errors.",
            "detection_hint": "Server script code body with no try/catch block",
            "recommendation": "Wrap significant logic in try/catch and log errors with gs.error() or gs.logError().",
        },
        {
            "code": "SRV_AFTER_NOT_ASYNC",
            "title": "After BR where Async BR would suffice",
            "category": BestPracticeCategory.technical_server,
            "severity": "medium",
            "description": "After Business Rules block the user transaction. If the BR doesn't need to run synchronously, Async is faster for the user.",
            "detection_hint": "After BR with no user-facing side effects (e.g., updating related records, sending events)",
            "recommendation": "Change timing from After to Async. The platform runs Async BRs on a background worker thread.",
            "applies_to": "sys_script",
        },
        {
            "code": "SRV_GLOBAL_BR_NO_TABLE",
            "title": "Global Business Rule without table filter",
            "category": BestPracticeCategory.technical_server,
            "severity": "medium",
            "description": "A Business Rule with no table filter runs on every table operation in the system, which is rarely intended and impacts performance.",
            "detection_hint": "sys_script with empty or null table/collection field",
            "recommendation": "Set a specific table. If truly global behavior is needed, document why clearly.",
            "applies_to": "sys_script",
        },
        {
            "code": "SRV_SCRIPT_INCLUDE_NO_INIT",
            "title": "Script Include missing initialize()",
            "category": BestPracticeCategory.technical_server,
            "severity": "low",
            "description": "Class-based Script Includes should have an initialize() method for proper constructor behavior.",
            "detection_hint": "sys_script_include with Class.create() pattern but no initialize function",
            "recommendation": "Add initialize: function() {} to the prototype definition.",
            "applies_to": "sys_script_include",
        },
        {
            "code": "SRV_CLIENT_CALLABLE_MISUSE",
            "title": "Script Include client-callable flag misuse",
            "category": BestPracticeCategory.technical_server,
            "severity": "medium",
            "description": "A Script Include marked client_callable=true should extend AbstractAjaxProcessor. If it doesn't, the flag may be set incorrectly, exposing server logic to client-side calls.",
            "detection_hint": "client_callable=true but no AbstractAjaxProcessor extension in code",
            "recommendation": "If client-callable, extend AbstractAjaxProcessor. If not needed client-side, set client_callable=false.",
            "applies_to": "sys_script_include",
        },
        {
            "code": "SRV_DEPRECATED_API",
            "title": "Deprecated API usage",
            "category": BestPracticeCategory.technical_server,
            "severity": "medium",
            "description": "Using deprecated ServiceNow APIs risks breakage on upgrades.",
            "detection_hint": "current.variables used outside of catalog context, Packages.* Java calls, obsolete GlideRecord methods",
            "recommendation": "Replace with current supported API equivalents.",
        },
        # ── Technical — Client Side ──
        {
            "code": "CLI_DOM_MANIPULATION",
            "title": "DOM manipulation (unsupported)",
            "category": BestPracticeCategory.technical_client,
            "severity": "high",
            "description": "Direct DOM manipulation using jQuery selectors or document.getElementById is not supported by ServiceNow and may break on UI updates or upgrades. Sometimes unavoidable but should always be flagged.",
            "detection_hint": "$(' or document.get or document.querySelector or jQuery( in client script code",
            "recommendation": "Use supported g_form API methods (setValue, setDisplay, setMandatory, etc.). If DOM manipulation is truly needed, document the reason.",
            "applies_to": "sys_script_client,sys_ui_script",
            "source_url": "https://www.servicenow.com/community/queensland-snug/client-script-best-practices/ba-p/2273951",
        },
        {
            "code": "CLI_SYNC_GLIDEAJAX",
            "title": "Synchronous GlideAjax calls",
            "category": BestPracticeCategory.technical_client,
            "severity": "high",
            "description": "getXMLWait() blocks the browser thread until the server responds, causing the UI to freeze.",
            "detection_hint": "getXMLWait() in client script code",
            "recommendation": "Use asynchronous getXMLAnswer() with a callback function instead.",
            "applies_to": "sys_script_client,sys_ui_script",
        },
        {
            "code": "CLI_GLIDERECORD_CLIENT",
            "title": "GlideRecord used client-side",
            "category": BestPracticeCategory.technical_client,
            "severity": "medium",
            "description": "Client-side GlideRecord makes direct database calls from the browser. ServiceNow recommends GlideAjax for client-server communication.",
            "detection_hint": "GlideRecord constructor in sys_script_client or sys_ui_script code",
            "recommendation": "Create a Script Include extending AbstractAjaxProcessor and call it via GlideAjax.",
            "applies_to": "sys_script_client,sys_ui_script",
        },
        {
            "code": "CLI_DOING_UI_POLICY_WORK",
            "title": "Client script setting mandatory/visible/readonly",
            "category": BestPracticeCategory.technical_client,
            "severity": "high",
            "description": "Client scripts that only set fields mandatory, visible, or read-only should use UI Policies instead. UI Policies are declarative, faster to load, and easier for admins to maintain.",
            "detection_hint": "g_form.setMandatory, g_form.setVisible, g_form.setDisplay, g_form.setReadOnly as primary purpose of client script",
            "recommendation": "Replace with UI Policy + UI Policy Actions. Reserve client scripts for complex logic that UI Policies cannot handle.",
            "applies_to": "sys_script_client",
            "source_url": "https://www.servicenow.com/community/developer-forum/ui-policy-and-client-script-best-practice/m-p/3247425",
        },
        {
            "code": "CLI_GSCRATCHPAD_MISUSE",
            "title": "g_scratchpad misuse",
            "category": BestPracticeCategory.technical_client,
            "severity": "medium",
            "description": "g_scratchpad should only be populated from Display Business Rules and read in client scripts. Misuse includes setting values from client scripts or over-reliance for data passing.",
            "detection_hint": "g_scratchpad used outside Display BR → Client Script pattern",
            "recommendation": "Use Display BR to set g_scratchpad values. For complex data needs, use GlideAjax.",
            "applies_to": "sys_script_client,sys_ui_script",
        },
        # ── Architecture ──
        {
            "code": "ARCH_EXTEND_CORE_TABLE",
            "title": "Extending core task-child tables",
            "category": BestPracticeCategory.architecture,
            "severity": "critical",
            "description": "Extending Incident, Change Request, Problem, or other core task-child tables fractures AI training data, complicates routing, SLAs, and reporting. Extending the Task table itself is acceptable.",
            "detection_hint": "Custom table extending incident, change_request, problem, or other OOTB task children",
            "recommendation": "Extend Task directly if task-based workflow is needed. Do not extend Incident or other core task children.",
            "source_url": "https://www.servicenow.com/community/itsm-articles/best-practice-incident-management-to-extend-or-not-to-extend-and/ta-p/3486025",
        },
        {
            "code": "ARCH_CUSTOM_FIELD_OOTB_EXISTS",
            "title": "Custom field where OOTB field exists",
            "category": BestPracticeCategory.architecture,
            "severity": "high",
            "description": "Creating custom u_ fields when an equivalent OOTB field exists wastes resources and misses built-in functionality.",
            "detection_hint": "u_ prefixed field on a table where a similar standard field exists and is not used",
            "recommendation": "Use the OOTB field instead. If the OOTB field doesn't quite fit, consider Dictionary Overrides before creating custom.",
        },
        {
            "code": "ARCH_LOOKUP_NOT_DL",
            "title": "Lookup table not using Data Lookup framework",
            "category": BestPracticeCategory.architecture,
            "severity": "high",
            "description": "Custom tables used purely for data lookups should extend dl_matcher to leverage ServiceNow's built-in Data Lookup Definitions, Matchers, and unlimited table storage.",
            "detection_hint": "Custom table used as a lookup/reference table that does not extend dl_matcher",
            "recommendation": "Extend dl_matcher for lookup tables. Use Data Lookup Definitions for auto-population rules.",
            "source_url": "https://www.servicenow.com/community/developer-blog/the-power-of-servicenow-data-matching-using-data-lookup-rules/ba-p/3008708",
        },
        {
            "code": "ARCH_NOT_MODULAR",
            "title": "Business logic not modular/reusable",
            "category": BestPracticeCategory.architecture,
            "severity": "medium",
            "description": "Complex business logic embedded directly in Business Rules cannot be reused by other scripts, flows, or APIs.",
            "detection_hint": "Business Rule with >30 lines of logic that could be extracted to a Script Include",
            "recommendation": "Extract reusable logic into Script Includes. Call from BRs, Flows, and other scripts.",
        },
        {
            "code": "ARCH_GLOBAL_NOT_SCOPED",
            "title": "Custom code in global scope",
            "category": BestPracticeCategory.architecture,
            "severity": "medium",
            "description": "Custom artifacts in global scope lack namespace isolation, are harder to manage, and create more upgrade conflicts.",
            "detection_hint": "Custom artifacts (not OOTB modifications) that are not in a scoped application",
            "recommendation": "Package custom development into scoped custom applications. Each feature should ideally be its own scope for easy disposal.",
            "source_url": "https://www.servicenow.com/community/servicenow-ai-platform-blog/application-development-best-practice-1-work-in-a-scope/ba-p/2288784",
        },
        {
            "code": "ARCH_LEGACY_WORKFLOW",
            "title": "Legacy Workflow instead of Flow Designer",
            "category": BestPracticeCategory.architecture,
            "severity": "medium",
            "description": "ServiceNow is deprecating legacy workflows. Flow Designer provides better testing, error handling, and async processing.",
            "detection_hint": "Active records in wf_workflow table",
            "recommendation": "Plan migration to Flow Designer. Use the Workflow Automation CoE migration guide.",
            "source_url": "https://www.servicenow.com/community/workflow-automation-articles/migrate-legacy-workflows-to-flows-and-playbooks-workflow/ta-p/3132026",
        },
        {
            "code": "ARCH_CATALOG_CLIENT_NOT_UI_POLICY",
            "title": "Catalog Client Script instead of Catalog UI Policy",
            "category": BestPracticeCategory.architecture,
            "severity": "medium",
            "description": "Catalog Client Scripts doing field visibility/mandatory work should use Catalog UI Policies instead.",
            "detection_hint": "Catalog client script whose primary purpose is setMandatory/setDisplay/setReadOnly on catalog variables",
            "recommendation": "Use Catalog UI Policy + UI Policy Actions for declarative variable control.",
            "applies_to": "catalog_script_client",
        },
        {
            "code": "ARCH_NO_VARIABLE_SETS",
            "title": "Catalog variables not using Variable Sets",
            "category": BestPracticeCategory.architecture,
            "severity": "low",
            "description": "Repeated individual variables across catalog items should be consolidated into reusable Variable Sets.",
            "detection_hint": "Same variable definitions repeated across multiple catalog items",
            "recommendation": "Create Variable Sets for shared variable groups. Attach to multiple catalog items.",
        },
        {
            "code": "ARCH_LIST_COLLECTOR_OVERUSE",
            "title": "List Collector variable overuse",
            "category": BestPracticeCategory.architecture,
            "severity": "medium",
            "description": "List Collector (slush bucket) variables are not supported by the g_form API and are hard to customize programmatically.",
            "detection_hint": "List Collector variable type in catalog items",
            "recommendation": "Use Multi-Row Variable Sets or other supported variable types instead.",
        },
        # ── Process ──
        {
            "code": "PROC_DEFAULT_UPDATE_SET",
            "title": "Artifacts in Default update set",
            "category": BestPracticeCategory.process,
            "severity": "high",
            "description": "Changes captured in the Default update set indicate development done directly in the environment without proper change tracking.",
            "detection_hint": "Artifacts linked to update set named 'Default' or 'default'",
            "recommendation": "Always create a named update set before making changes. Use naming convention: [Project]-[Story]-[Description].",
            "source_url": "https://www.servicenow.com/community/developer-blog/servicenow-update-set-leading-practices-part-1/ba-p/3246473",
        },
        {
            "code": "PROC_NO_US_NAMING",
            "title": "No update set naming convention",
            "category": BestPracticeCategory.process,
            "severity": "medium",
            "description": "Update set names without a consistent prefix, project code, or story number make change tracking and deployment difficult.",
            "detection_hint": "Update set names that lack a common prefix pattern or project identifier",
            "recommendation": "Adopt a naming convention: [ProjectCode]-[StoryNumber]-[ShortDescription]. Prefix with a number for ordering.",
        },
        {
            "code": "PROC_OVERSIZED_US",
            "title": "Update set too large (>100 entries)",
            "category": BestPracticeCategory.process,
            "severity": "medium",
            "description": "Update sets with more than ~100 XML entries are hard to review, deploy, and troubleshoot. Recommended max is 500-1000 XML entries.",
            "detection_hint": "Update set with >100 artifact links or XML entries",
            "recommendation": "Break large changes into smaller, focused update sets. Use parent/child batch grouping for related sets.",
        },
        {
            "code": "PROC_NO_US_BATCHING",
            "title": "Related update sets not batched",
            "category": BestPracticeCategory.process,
            "severity": "medium",
            "description": "Related update sets without parent/child batch grouping complicate deployment ordering and rollback.",
            "detection_hint": "Multiple related update sets (by naming or time) without a parent batch update set",
            "recommendation": "Group related update sets under a parent batch. Limit to 5-10 children per batch.",
        },
        {
            "code": "PROC_NO_CODE_COMMENTS",
            "title": "No comments in code",
            "category": BestPracticeCategory.process,
            "severity": "medium",
            "description": "Code without comments (header block and inline) is harder to maintain and review.",
            "detection_hint": "Scriptable artifact code body with zero comment lines (// or /* patterns)",
            "recommendation": "Add a header comment block (author, purpose, date) and inline comments for complex logic.",
        },
        {
            "code": "PROC_HARDCODED_SYSID",
            "title": "Hard-coded sys_ids in scripts",
            "category": BestPracticeCategory.process,
            "severity": "high",
            "description": "Hard-coded 32-character sys_ids are not portable between instances (dev/test/prod may have different IDs).",
            "detection_hint": "32-character hexadecimal strings in code body",
            "recommendation": "Store sys_ids in System Properties using gs.getProperty(), or use Script Include constants.",
            "source_url": "https://www.servicenow.com/community/developer-articles/scripting-best-practices-avoid-using-hardcoded-values-in-scripts/ta-p/2466714",
        },
        {
            "code": "PROC_NO_SYSTEM_PROPERTIES",
            "title": "Config values not in System Properties",
            "category": BestPracticeCategory.process,
            "severity": "high",
            "description": "Configuration values (URLs, thresholds, feature flags) embedded directly in scripts require code changes to update.",
            "detection_hint": "Hard-coded URLs, email addresses, threshold numbers, or feature flags in script code",
            "recommendation": "Create System Properties and retrieve with gs.getProperty(). Allows admin changes without code deployment.",
        },
        # ── Security ──
        {
            "code": "SEC_ACL_SCRIPT_NO_ROLE",
            "title": "Scripted ACL without role shielding",
            "category": BestPracticeCategory.security,
            "severity": "high",
            "description": "ACLs with scripted conditions but no role requirement force the script to execute on every access check, impacting performance.",
            "detection_hint": "ACL record with script condition populated but no role requirement set",
            "recommendation": "Add a role requirement to the ACL. The role check (cached in memory) prevents unnecessary script execution.",
            "applies_to": "sys_security_acl",
            "source_url": "https://www.servicenow.com/community/platform-privacy-security-blog/configuring-acls-the-right-way/ba-p/3446017",
        },
        {
            "code": "SEC_NO_ACL_CUSTOM_TABLE",
            "title": "Custom table missing ACLs",
            "category": BestPracticeCategory.security,
            "severity": "high",
            "description": "Custom tables without ACL records may rely on default permissions, potentially exposing data to unauthorized users.",
            "detection_hint": "Custom table (sys_db_object) with no corresponding ACL records",
            "recommendation": "Create table-level and field-level ACLs for custom tables. At minimum: read, write, create, delete ACLs.",
        },
        {
            "code": "SEC_OVERLY_PERMISSIVE_ACL",
            "title": "Overly permissive ACL",
            "category": BestPracticeCategory.security,
            "severity": "medium",
            "description": "ACLs granting broad access (e.g., to 'itil' or 'snc_internal' roles) without additional conditions may expose sensitive data.",
            "detection_hint": "ACL with only broad role requirement and no conditions or scripts",
            "recommendation": "Add conditions or scripted checks to narrow access. Use least-privilege principle.",
            "applies_to": "sys_security_acl",
        },
        {
            "code": "SEC_CREDENTIALS_IN_CODE",
            "title": "Credentials or secrets in scripts",
            "category": BestPracticeCategory.security,
            "severity": "critical",
            "description": "Passwords, API keys, tokens, or other secrets hard-coded in scripts are a critical security risk.",
            "detection_hint": "Strings resembling passwords, API keys, bearer tokens, or base64-encoded credentials in code body",
            "recommendation": "Use ServiceNow Credential Store, Connection & Credential Aliases, or System Properties (with encryption) for secrets.",
        },
        # ── Performance ──
        {
            "code": "PERF_UNINDEXED_QUERY",
            "title": "Queries on unindexed fields",
            "category": BestPracticeCategory.performance,
            "severity": "high",
            "description": "GlideRecord queries on large tables without indexed where-clause fields cause full table scans.",
            "detection_hint": "GlideRecord addQuery on fields not known to be indexed, especially on large tables (task, sys_audit, syslog)",
            "recommendation": "Add database indexes for frequently queried fields. Use setLimit() to cap result sets.",
        },
        {
            "code": "PERF_HEAVY_BEFORE_QUERY_BR",
            "title": "Heavy Before Query Business Rule",
            "category": BestPracticeCategory.performance,
            "severity": "high",
            "description": "Before Query Business Rules run on every query to the table, including list views. Complex scripts here severely impact page load.",
            "detection_hint": "Before Query BR with significant scripting (>10 lines) or GlideRecord queries inside it",
            "recommendation": "Minimize Before Query BR logic. Move complex logic to ACLs or other mechanisms.",
            "applies_to": "sys_script",
        },
        {
            "code": "PERF_SYNC_WHERE_ASYNC",
            "title": "Synchronous processing where async works",
            "category": BestPracticeCategory.performance,
            "severity": "medium",
            "description": "Blocking the user transaction for operations that could run in the background (event queue, async BR, scheduled job).",
            "detection_hint": "After BR or script doing heavy processing (emails, integrations, bulk updates) synchronously",
            "recommendation": "Use gs.eventQueue(), Async Business Rules, or Flow Designer for background processing.",
        },
        {
            "code": "PERF_NOTIFICATION_OVERUSE",
            "title": "Excessive record-based notifications",
            "category": BestPracticeCategory.performance,
            "severity": "low",
            "description": "Many condition-based notifications are harder to troubleshoot than event-driven ones.",
            "detection_hint": "Large number of 'Record inserted or updated' notifications on the same table",
            "recommendation": "Consider event-driven notifications for easier troubleshooting. Events provide a clear audit trail.",
        },
        # ── Upgradeability ──
        {
            "code": "UPG_MODIFIED_OOTB_SCRIPT",
            "title": "Direct modification of OOTB scripts",
            "category": BestPracticeCategory.upgradeability,
            "severity": "high",
            "description": "Directly modifying OOTB Business Rules, Script Includes, or UI Scripts creates skipped records on every upgrade that must be manually reconciled.",
            "detection_hint": "modified_ootb origin on scriptable artifacts (sys_script, sys_script_include, sys_ui_script)",
            "recommendation": "Instead of modifying OOTB scripts, create new artifacts that extend or override behavior. Use scoped applications for isolation.",
            "source_url": "https://www.servicenow.com/community/developer-blog/best-practices-to-manage-skipped-updates-effectively-during/ba-p/3421456",
        },
        {
            "code": "UPG_HIGH_SKIPPED_RISK",
            "title": "High skipped record risk on upgrade",
            "category": BestPracticeCategory.upgradeability,
            "severity": "medium",
            "description": "Assessments with many modified OOTB artifacts will produce many skipped records on upgrade, requiring significant review effort.",
            "detection_hint": "High count (>20) of modified_ootb artifacts across the assessment",
            "recommendation": "Prioritize refactoring modified OOTB artifacts into custom scoped applications that extend rather than modify.",
        },
    ]

    new_records = [
        BestPractice(**data)
        for data in checks
        if data["code"] not in existing_codes
    ]

    if new_records:
        for rec in new_records:
            session.add(rec)
        session.commit()
```

Also update `run_seed()` in `src/seed_data.py` to call `seed_best_practices(session)`.

**Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_best_practice_seed.py -v`
Expected: All 5 tests PASS

**Step 5: Run full test suite**

Run: `./venv/bin/python -m pytest -v`
Expected: All existing tests + 5 new tests PASS

**Step 6: Commit**

```bash
git add src/seed_data.py tests/test_best_practice_seed.py
git commit -m "feat: add BestPractice seed data with 41 ServiceNow best practice checks"
```

---

## Task 3: Add BestPractice Admin API Routes + Page

**Files:**
- Modify: `src/server.py` (add API routes + HTML page route)
- Create: `src/web/templates/admin_best_practices.html`
- Modify: `src/web/templates/base.html` (add nav link)

**Step 1: Write the failing test**

Create: `tests/test_best_practice_admin.py`

```python
"""Tests for BestPractice admin API routes."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from src.models import BestPractice, BestPracticeCategory


@pytest.fixture
def seeded_bps(db_session: Session):
    """Create a few best practices for testing."""
    bps = []
    for i, (code, cat) in enumerate([
        ("TEST_SRV_001", BestPracticeCategory.technical_server),
        ("TEST_CLI_001", BestPracticeCategory.technical_client),
        ("TEST_ARCH_001", BestPracticeCategory.architecture),
    ]):
        bp = BestPractice(
            code=code,
            title=f"Test BP {i}",
            category=cat,
            severity="medium",
            description=f"Description {i}",
            detection_hint=f"Hint {i}",
            recommendation=f"Rec {i}",
            is_active=True,
        )
        db_session.add(bp)
        bps.append(bp)
    db_session.commit()
    for bp in bps:
        db_session.refresh(bp)
    return bps


def test_api_list_best_practices(client: TestClient, seeded_bps):
    resp = client.get("/api/best-practices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["best_practices"]) == 3


def test_api_list_best_practices_filter_category(client: TestClient, seeded_bps):
    resp = client.get("/api/best-practices?category=technical_server")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["best_practices"]) == 1
    assert data["best_practices"][0]["code"] == "TEST_SRV_001"


def test_api_update_best_practice(client: TestClient, seeded_bps):
    bp_id = seeded_bps[0].id
    resp = client.put(f"/api/best-practices/{bp_id}", json={
        "title": "Updated Title",
        "severity": "critical",
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"
    assert resp.json()["severity"] == "critical"


def test_api_toggle_best_practice_active(client: TestClient, seeded_bps):
    bp_id = seeded_bps[0].id
    resp = client.put(f"/api/best-practices/{bp_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_api_create_best_practice(client: TestClient, db_session):
    resp = client.post("/api/best-practices", json={
        "code": "NEW_001",
        "title": "Brand New Check",
        "category": "process",
        "severity": "high",
        "description": "A new check",
    })
    assert resp.status_code == 201
    assert resp.json()["code"] == "NEW_001"
```

Note: This test requires a `client` fixture. Check if one exists in conftest.py. If not, add one that creates a FastAPI TestClient. The test structure depends on how the app handles the session — may need adjustment to match the existing test app fixture pattern.

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_best_practice_admin.py -v`
Expected: FAIL — routes don't exist yet

**Step 3: Add API routes to server.py**

Add these routes to `src/server.py`:

```python
# ── Best Practice Admin API ──────────────────────────────────────────

@app.get("/api/best-practices")
async def api_list_best_practices(
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    session: Session = Depends(get_session),
):
    """List all best practice checks with optional filtering."""
    stmt = select(BestPractice).order_by(BestPractice.category, BestPractice.severity, BestPractice.code)
    if category:
        stmt = stmt.where(BestPractice.category == category)
    if is_active is not None:
        stmt = stmt.where(BestPractice.is_active == is_active)
    rows = session.exec(stmt).all()
    return {
        "best_practices": [
            {
                "id": bp.id,
                "code": bp.code,
                "title": bp.title,
                "category": bp.category.value if hasattr(bp.category, "value") else bp.category,
                "severity": bp.severity,
                "description": bp.description,
                "detection_hint": bp.detection_hint,
                "recommendation": bp.recommendation,
                "applies_to": bp.applies_to,
                "is_active": bp.is_active,
                "source_url": bp.source_url,
            }
            for bp in rows
        ]
    }


@app.post("/api/best-practices", status_code=201)
async def api_create_best_practice(
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    """Create a new best practice check."""
    bp = BestPractice(
        code=payload["code"],
        title=payload["title"],
        category=BestPracticeCategory(payload["category"]),
        severity=payload.get("severity", "medium"),
        description=payload.get("description"),
        detection_hint=payload.get("detection_hint"),
        recommendation=payload.get("recommendation"),
        applies_to=payload.get("applies_to"),
        is_active=payload.get("is_active", True),
        source_url=payload.get("source_url"),
    )
    session.add(bp)
    session.commit()
    session.refresh(bp)
    return {
        "id": bp.id, "code": bp.code, "title": bp.title,
        "category": bp.category.value, "severity": bp.severity,
        "description": bp.description, "detection_hint": bp.detection_hint,
        "recommendation": bp.recommendation, "applies_to": bp.applies_to,
        "is_active": bp.is_active, "source_url": bp.source_url,
    }


@app.put("/api/best-practices/{bp_id}")
async def api_update_best_practice(
    bp_id: int,
    payload: Dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
):
    """Update an existing best practice check."""
    bp = session.get(BestPractice, bp_id)
    if not bp:
        raise HTTPException(status_code=404, detail="Best practice not found")
    for key in ("title", "severity", "description", "detection_hint",
                "recommendation", "applies_to", "is_active", "source_url"):
        if key in payload:
            setattr(bp, key, payload[key])
    if "category" in payload:
        bp.category = BestPracticeCategory(payload["category"])
    bp.updated_at = datetime.utcnow()
    session.add(bp)
    session.commit()
    session.refresh(bp)
    return {
        "id": bp.id, "code": bp.code, "title": bp.title,
        "category": bp.category.value, "severity": bp.severity,
        "description": bp.description, "detection_hint": bp.detection_hint,
        "recommendation": bp.recommendation, "applies_to": bp.applies_to,
        "is_active": bp.is_active, "source_url": bp.source_url,
    }
```

Also add the HTML page route and create the template (follow existing instances.html pattern with a data-table showing code, title, category, severity, is_active columns with inline edit/toggle).

**Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_best_practice_admin.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/server.py src/web/templates/admin_best_practices.html src/web/templates/base.html tests/test_best_practice_admin.py
git commit -m "feat: add BestPractice admin API routes and list page"
```

---

## Task 4: Extend Prompt Infrastructure for Session-Aware Handlers

**Files:**
- Modify: `src/mcp/registry.py` (lines 53-85 — PromptSpec + PromptRegistry)
- Modify: `src/mcp/protocol/jsonrpc.py` (line 150 — pass session to prompts/get)

**Step 1: Write the failing test**

Create: `tests/test_prompt_session_support.py`

```python
"""Tests for session-aware prompt handler support."""

from sqlmodel import Session

from src.mcp.registry import PromptSpec, PromptRegistry


def _static_handler(arguments):
    """Handler that does NOT need session (existing pattern)."""
    return {
        "description": "Static prompt",
        "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
    }


def _session_handler(arguments, session=None):
    """Handler that CAN accept session (new pattern)."""
    label = "with_session" if session is not None else "no_session"
    return {
        "description": f"Dynamic prompt ({label})",
        "messages": [{"role": "user", "content": {"type": "text", "text": f"Context: {label}"}}],
    }


def test_prompt_registry_backward_compatible():
    """Existing handlers without session parameter still work."""
    registry = PromptRegistry()
    registry.register(PromptSpec(
        name="static_test",
        description="test",
        arguments=[],
        handler=_static_handler,
    ))
    result = registry.get_prompt("static_test", {})
    assert result["description"] == "Static prompt"


def test_prompt_registry_session_passed(db_session: Session):
    """New handlers with session parameter receive it."""
    registry = PromptRegistry()
    registry.register(PromptSpec(
        name="dynamic_test",
        description="test",
        arguments=[],
        handler=_session_handler,
    ))
    result = registry.get_prompt("dynamic_test", {}, session=db_session)
    assert "with_session" in result["messages"][0]["content"]["text"]


def test_prompt_registry_session_not_required():
    """Handlers with optional session work when session is None."""
    registry = PromptRegistry()
    registry.register(PromptSpec(
        name="optional_test",
        description="test",
        arguments=[],
        handler=_session_handler,
    ))
    result = registry.get_prompt("optional_test", {})
    assert "no_session" in result["messages"][0]["content"]["text"]
```

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_prompt_session_support.py -v`
Expected: FAIL — `get_prompt() got an unexpected keyword argument 'session'`

**Step 3: Update PromptSpec and PromptRegistry**

In `src/mcp/registry.py`, update `PromptSpec` (line 53-59):

```python
@dataclass
class PromptSpec:
    """MCP Prompt specification."""
    name: str
    description: str
    arguments: List[Dict[str, Any]]
    handler: Callable[..., Dict[str, Any]]  # Changed from Callable[[Dict], Dict]
```

Update `PromptRegistry.get_prompt` (line 82-85):

```python
def get_prompt(
    self,
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    session: Optional[Any] = None,
) -> Dict[str, Any]:
    if name not in self._prompts:
        raise KeyError(f"Prompt not found: {name}")
    handler = self._prompts[name].handler
    # Check if handler accepts session parameter
    import inspect
    sig = inspect.signature(handler)
    if "session" in sig.parameters:
        return handler(arguments or {}, session=session)
    return handler(arguments or {})
```

Update `src/mcp/protocol/jsonrpc.py` line 81-91 to pass session:

```python
def _handle_prompts_get(
    request_id: Optional[Union[str, int]],
    params: Dict[str, Any],
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    name = params.get("name")
    if not name:
        return make_error(request_id, -32602, "Missing prompt name")
    try:
        arguments = params.get("arguments") or {}
        result = PROMPT_REGISTRY.get_prompt(name, arguments, session=session)
    except KeyError:
        return make_error(request_id, -32601, f"Prompt not found: {name}")
    except Exception as exc:
        return make_error(request_id, -32000, f"Prompt retrieval failed: {exc}")
    return make_result(request_id, result)
```

Update `handle_request` line 148-150 to pass session:

```python
    if method == "prompts/get":
        params = payload.get("params") or {}
        return _handle_prompts_get(request_id, params, session=session)
```

**Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_prompt_session_support.py -v`
Expected: All 3 tests PASS

**Step 5: Run full test suite**

Run: `./venv/bin/python -m pytest -v`
Expected: All tests PASS (existing prompts unaffected)

**Step 6: Commit**

```bash
git add src/mcp/registry.py src/mcp/protocol/jsonrpc.py tests/test_prompt_session_support.py
git commit -m "feat: extend prompt infrastructure for session-aware handlers"
```

---

## Task 5: Create `artifact_analyzer` Prompt

**Files:**
- Create: `src/mcp/prompts/artifact_analyzer.py`
- Modify: `src/mcp/registry.py` (register new prompt)

**Step 1: Write the failing test**

Create: `tests/test_artifact_analyzer_prompt.py`

```python
"""Tests for the artifact_analyzer MCP prompt."""

from sqlmodel import Session

from src.models import (
    Assessment, AssessmentState, AssessmentType, Instance,
    OriginType, Scan, ScanResult, ScanStatus,
)


def _seed_result(session: Session):
    inst = Instance(name="test", url="https://test.service-now.com",
                    username="admin", password_encrypted="x")
    session.add(inst)
    session.flush()
    asmt = Assessment(instance_id=inst.id, name="Test", number="ASMT0001",
                      assessment_type=AssessmentType.global_app,
                      state=AssessmentState.in_progress)
    session.add(asmt)
    session.flush()
    scan = Scan(assessment_id=asmt.id, scan_type="customization", status=ScanStatus.completed)
    session.add(scan)
    session.flush()
    sr = ScanResult(
        scan_id=scan.id, name="Test BR", table_name="sys_script",
        origin_type=OriginType.net_new_customer,
        code_body="(function executeRule(current, previous) {\n  current.update();\n})(current, previous);",
        observations="Baseline observation text.",
    )
    session.add(sr)
    session.commit()
    session.refresh(sr)
    return asmt, sr


def test_artifact_analyzer_prompt_returns_messages(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    asmt, sr = _seed_result(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    assert "messages" in result
    assert len(result["messages"]) >= 1
    text = result["messages"][0]["content"]["text"]
    assert "Test BR" in text  # Artifact name injected
    assert "sys_script" in text  # Table name injected


def test_artifact_analyzer_includes_code_body(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    asmt, sr = _seed_result(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "current.update()" in text  # Code body injected


def test_artifact_analyzer_includes_observations(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    asmt, sr = _seed_result(db_session)
    handler = PROMPT_SPECS[0].handler
    result = handler(
        {"result_id": str(sr.id), "assessment_id": str(asmt.id)},
        session=db_session,
    )
    text = result["messages"][0]["content"]["text"]
    assert "Baseline observation" in text


def test_artifact_analyzer_missing_result_raises(db_session: Session):
    from src.mcp.prompts.artifact_analyzer import PROMPT_SPECS
    import pytest
    handler = PROMPT_SPECS[0].handler
    with pytest.raises(ValueError, match="ScanResult not found"):
        handler({"result_id": "99999", "assessment_id": "1"}, session=db_session)
```

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_artifact_analyzer_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.mcp.prompts.artifact_analyzer'`

**Step 3: Create artifact_analyzer.py**

Create `src/mcp/prompts/artifact_analyzer.py` with:
- `ARTIFACT_ANALYZER_TEXT` constant — system instructions for per-artifact deep dive with per-type dispatch strategies (see design doc Section 2)
- `_build_artifact_context(session, result_id, assessment_id)` — queries DB for result metadata, code body (first 150 lines), engine signals, structural relationships, update set context, usage data, existing observations
- `_artifact_analyzer_handler(arguments, session=None)` — calls context builder, appends dynamic context to prompt text
- `PROMPT_SPECS` list with one PromptSpec entry

Register in `src/mcp/registry.py` `_populate_prompt_registry()`.

**Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_artifact_analyzer_prompt.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/mcp/prompts/artifact_analyzer.py src/mcp/registry.py tests/test_artifact_analyzer_prompt.py
git commit -m "feat: add artifact_analyzer MCP prompt with dynamic context injection"
```

---

## Task 6: Create `relationship_tracer` Prompt

**Files:**
- Create: `src/mcp/prompts/relationship_tracer.py`
- Modify: `src/mcp/registry.py` (register)

**Step 1: Write the failing test**

Create: `tests/test_relationship_tracer_prompt.py`

Test that the handler:
- Returns messages with starting artifact context
- Includes structural relationships when they exist
- Includes update set siblings
- Works without session (graceful fallback with static text)
- Raises ValueError for missing result_id

Follow same pattern as Task 5 tests. Seed 2-3 ScanResults with a StructuralRelationship between them and shared UpdateSetArtifactLinks.

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_relationship_tracer_prompt.py -v`

**Step 3: Create relationship_tracer.py**

Create `src/mcp/prompts/relationship_tracer.py` with:
- `RELATIONSHIP_TRACER_TEXT` constant — instructions for dependency graph tracing (see design doc Section 3)
- `_build_relationship_context(session, result_id, assessment_id, max_depth, direction)` — queries StructuralRelationship, UpdateSetArtifactLink, same-table neighbors, GroupingSignal, FeatureGroupMember
- `_relationship_tracer_handler(arguments, session=None)` — builds context and returns prompt
- `PROMPT_SPECS` list

Register in `src/mcp/registry.py`.

**Step 4: Run test, verify pass, commit**

```bash
git add src/mcp/prompts/relationship_tracer.py src/mcp/registry.py tests/test_relationship_tracer_prompt.py
git commit -m "feat: add relationship_tracer MCP prompt for dependency graph tracing"
```

---

## Task 7: Create `technical_architect` Prompt

**Files:**
- Create: `src/mcp/prompts/technical_architect.py`
- Modify: `src/mcp/registry.py` (register)

**Step 1: Write the failing test**

Create: `tests/test_technical_architect_prompt.py`

Test two modes:
- **Mode A (per-artifact):** `result_id` + `assessment_id` → injects artifact context + filtered BestPractice catalog
- **Mode B (assessment-wide):** `assessment_id` only (no `result_id`) → injects aggregated stats + full BestPractice catalog
- Verify BestPractice records are injected into prompt text
- Verify inactive BestPractice records are excluded
- Verify `applies_to` filtering works (only matching sys_class_name checks included)

Seed BestPractice records + ScanResults in tests.

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_technical_architect_prompt.py -v`

**Step 3: Create technical_architect.py**

Create `src/mcp/prompts/technical_architect.py` with:
- `TECHNICAL_ARCHITECT_ARTIFACT_TEXT` — Mode A instructions (per-artifact evaluation, disposition tree, scoped app guidance)
- `TECHNICAL_ARCHITECT_ASSESSMENT_TEXT` — Mode B instructions (assessment-wide roll-up)
- `_build_best_practice_checklist(session, applies_to=None)` — queries active BestPractice records, filters by applies_to, formats as structured checklist
- `_build_artifact_tech_context(session, result_id, assessment_id)` — full code body + metadata
- `_build_assessment_tech_context(session, assessment_id)` — aggregate stats + sample snippets + landscape summary
- `_technical_architect_handler(arguments, session=None)` — dispatches Mode A vs Mode B based on presence of `result_id`
- `PROMPT_SPECS` list with one entry (mode determined by arguments)

Register in `src/mcp/registry.py`.

**Step 4: Run test, verify pass, commit**

```bash
git add src/mcp/prompts/technical_architect.py src/mcp/registry.py tests/test_technical_architect_prompt.py
git commit -m "feat: add technical_architect MCP prompt with BestPractice catalog integration"
```

---

## Task 8: Create `report_writer` Prompt

**Files:**
- Create: `src/mcp/prompts/report_writer.py`
- Modify: `src/mcp/registry.py` (register)

**Step 1: Write the failing test**

Create: `tests/test_report_writer_prompt.py`

Test that the handler:
- Returns messages with assessment metadata
- Includes landscape summary when GeneralRecommendation exists
- Includes feature groups when Features exist
- Includes technical findings when present
- Includes statistics (artifact counts, customized counts)
- Respects `sections` parameter (only includes requested sections)
- Respects `format` parameter

Seed Assessment, ScanResults, GeneralRecommendation (landscape_summary + technical_findings), Features.

**Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_report_writer_prompt.py -v`

**Step 3: Create report_writer.py**

Create `src/mcp/prompts/report_writer.py` with:
- `REPORT_WRITER_TEXT` — instructions for generating assessment report sections
- `_build_report_context(session, assessment_id, sections, format)` — queries all relevant data: assessment, landscape summary, technical findings, features, general recommendations, stats, ungrouped artifacts
- `_report_writer_handler(arguments, session=None)` — builds full context and returns prompt
- `PROMPT_SPECS` list

Register in `src/mcp/registry.py`.

**Step 4: Run test, verify pass, commit**

```bash
git add src/mcp/prompts/report_writer.py src/mcp/registry.py tests/test_report_writer_prompt.py
git commit -m "feat: add report_writer MCP prompt for assessment deliverable generation"
```

---

## Task 9: Final Integration Test + Full Suite Verification

**Files:**
- Create: `tests/test_phase6_integration.py`

**Step 1: Write integration test**

```python
"""Integration test: all Phase 6 prompts registered and callable."""

from src.mcp.registry import PROMPT_REGISTRY, build_prompt_registry


def test_all_phase6_prompts_registered():
    """All four new prompts appear in the registry."""
    prompts = PROMPT_REGISTRY.list_prompts()
    names = {p["name"] for p in prompts}
    assert "artifact_analyzer" in names
    assert "relationship_tracer" in names
    assert "technical_architect" in names
    assert "report_writer" in names


def test_phase6_prompt_count():
    """Phase 6 adds 4 new prompts to existing set."""
    prompts = PROMPT_REGISTRY.list_prompts()
    # Phase 5 had: tech_assessment_guide, observation_landscape_reviewer,
    #              observation_artifact_reviewer (3 existing + maybe more)
    # Phase 6 adds: 4 new
    assert len(prompts) >= 7
```

**Step 2: Run full test suite**

Run: `./venv/bin/python -m pytest -v`
Expected: All tests PASS (existing + ~25-30 new Phase 6 tests)

**Step 3: Commit**

```bash
git add tests/test_phase6_integration.py
git commit -m "feat: add Phase 6 integration tests, all prompts registered"
```

---

## Summary

| Task | Component | Est. New Tests |
|------|-----------|---------------|
| 1 | BestPractice model + enum | 5 |
| 2 | Seed data (41 checks) | 5 |
| 3 | Admin API + page | 5 |
| 4 | Session-aware prompt infrastructure | 3 |
| 5 | artifact_analyzer prompt | 4 |
| 6 | relationship_tracer prompt | 4 |
| 7 | technical_architect prompt | 5 |
| 8 | report_writer prompt | 4 |
| 9 | Integration tests | 2 |
| **Total** | | **~37 new tests** |

Dependencies: Task 1 → Task 2 → Task 3 (model → seed → admin). Task 4 → Tasks 5-8 (infra → prompts). Task 7 depends on Task 2 (needs BestPractice records). Task 9 depends on all.
