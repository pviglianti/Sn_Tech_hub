# seed_data.py - Seed data for lookup tables
# Run this after database initialization to populate reference data

import json
from sqlmodel import Session
from .database import engine
from sqlmodel import select

from .models import (
    GlobalApp, AppFileClass, NumberSequence, BestPractice, BestPracticeCategory,
    AppFileClassQuery, AssessmentTypeConfig, AssessmentTypeFileClass,
)
from .app_file_class_catalog import app_file_class_seed_rows


def _dedupe_list(items):
    """Return deduplicated list preserving order."""
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# YAML global_app_overrides merged into seed data so GlobalApp is the single
# source of truth.  Keys must match the ``name`` field in the apps list below.
_GLOBAL_APP_OVERRIDES = {
    "incident": {
        "tables": ["incident_task", "incident"],
        "keywords": ["incident", "inc", "major incident"],
    },
    "change": {
        "tables": ["change_request", "change_task"],
        "keywords": ["change", "change_request", "change_task", "chg"],
    },
    "problem": {
        "tables": ["problem", "problem_task"],
        "keywords": ["problem", "prb"],
    },
    "request": {
        "tables": ["sc_request", "sc_req_item", "sc_task", "sc_cat_item"],
        "keywords": ["request", "catalog", "ritm", "req"],
    },
    "knowledge": {
        "tables": ["kb_knowledge", "kb_category"],
        "keywords": ["knowledge", "kb"],
    },
    "cmdb": {
        "tables": ["cmdb_ci", "cmdb_rel_ci"],
        "table_prefixes": ["cmdb_"],
        "keywords": ["cmdb", "ci", "configuration"],
    },
    "asset": {
        "tables": ["alm_asset", "alm_hardware", "alm_consumable"],
        "table_prefixes": ["alm_"],
        "keywords": ["asset", "alm"],
    },
    "sla": {
        "tables": ["contract_sla", "task_sla"],
        "keywords": ["sla", "service level"],
    },
    "service_portal": {
        "tables": ["sp_portal", "sp_page", "sp_widget"],
        "table_prefixes": ["sp_"],
        "keywords": ["portal", "widget", "sp_"],
    },
    "hr_case": {
        "tables": ["sn_hr_core_case", "sn_hr_core_task"],
        "table_prefixes": ["sn_hr_"],
        "keywords": ["hr", "hr_case"],
    },
    "csm_case": {
        "tables": ["sn_customerservice_case"],
        "table_prefixes": ["sn_customerservice_"],
        "keywords": ["csm", "customer"],
    },
}


def seed_global_apps(session: Session):
    """Seed the GlobalApp table with known ITSM applications.

    Merges YAML ``global_app_overrides`` into the seed data so that
    ``core_tables_json``, ``keywords_json``, and ``table_prefixes_json``
    are the single source of truth.
    """

    apps = [
        {
            "name": "incident",
            "label": "Incident Management",
            "description": "IT Incident Management application",
            "core_tables_json": ["incident"],
            "parent_table": "task",
            "plugins_json": ["com.snc.incident.mgt"],
            "keywords_json": ["incident", "inc"],
            "display_order": 10,
        },
        {
            "name": "change",
            "label": "Change Management",
            "description": "IT Change Management application",
            "core_tables_json": ["change_request", "change_task"],
            "parent_table": "task",
            "plugins_json": ["com.snc.change.mgt"],
            "keywords_json": ["change", "chg"],
            "display_order": 20,
        },
        {
            "name": "problem",
            "label": "Problem Management",
            "description": "IT Problem Management application",
            "core_tables_json": ["problem", "problem_task"],
            "parent_table": "task",
            "plugins_json": ["com.snc.problem.mgt"],
            "keywords_json": ["problem", "prb"],
            "display_order": 30,
        },
        {
            "name": "request",
            "label": "Service Catalog",
            "description": "Service Catalog and Service Request fulfillment",
            "core_tables_json": ["sc_request", "sc_req_item", "sc_task", "sc_cat_item"],
            "parent_table": "task",
            "plugins_json": ["com.snc.service_catalog"],
            "keywords_json": ["request", "catalog", "ritm", "req"],
            "display_order": 40,
        },
        {
            "name": "spm",
            "label": "Strategic Portfolio Management (SPM)",
            "description": "Project and Portfolio Management, Demand, Agile, Scrum/SAFe",
            "core_tables_json": [
                "pm_project", "pm_project_task", "pm_portfolio", "pm_program",
                "dmn_demand",
                "rm_story", "rm_defect", "rm_enhancement", "rm_feature", "rm_task", "rm_epic",
            ],
            "parent_table": "planned_task",
            "plugins_json": ["com.snc.pm", "com.snc.sdlc.agile.2.0", "com.snc.demand"],
            "keywords_json": ["spm", "project", "portfolio", "demand", "story", "epic", "agile", "scrum"],
            "display_order": 45,
        },
        {
            "name": "knowledge",
            "label": "Knowledge Management",
            "description": "Knowledge Base application",
            "core_tables_json": ["kb_knowledge", "kb_category"],
            "parent_table": None,
            "plugins_json": ["com.snc.knowledge"],
            "keywords_json": ["knowledge", "kb"],
            "display_order": 50,
        },
        {
            "name": "cmdb",
            "label": "CMDB / Configuration Management",
            "description": "Configuration Management Database",
            "core_tables_json": ["cmdb_ci", "cmdb_rel_ci"],
            "parent_table": None,
            "plugins_json": ["com.snc.cmdb"],
            "keywords_json": ["cmdb", "ci", "configuration"],
            "display_order": 60,
        },
        {
            "name": "asset",
            "label": "Asset Management",
            "description": "IT Asset Management application",
            "core_tables_json": ["alm_asset", "alm_hardware", "alm_consumable"],
            "parent_table": None,
            "plugins_json": ["com.snc.asset_management"],
            "keywords_json": ["asset", "alm"],
            "display_order": 70,
        },
        {
            "name": "sla",
            "label": "SLA Management",
            "description": "Service Level Agreement management",
            "core_tables_json": ["contract_sla", "task_sla"],
            "parent_table": None,
            "plugins_json": ["com.snc.sla"],
            "keywords_json": ["sla", "service level"],
            "display_order": 80,
        },
        {
            "name": "service_portal",
            "label": "Service Portal",
            "description": "Service Portal customizations",
            "core_tables_json": ["sp_portal", "sp_page", "sp_widget"],
            "parent_table": None,
            "plugins_json": ["com.glide.service-portal.core"],
            "keywords_json": ["portal", "widget", "sp_"],
            "display_order": 90,
        },
        {
            "name": "hr_case",
            "label": "HR Case Management",
            "description": "HR Service Delivery - Case Management",
            "core_tables_json": ["sn_hr_core_case", "sn_hr_core_task"],
            "parent_table": "task",
            "plugins_json": ["com.sn_hr_core"],
            "keywords_json": ["hr", "hr_case"],
            "display_order": 100,
        },
        {
            "name": "csm_case",
            "label": "Customer Service Management",
            "description": "Customer Service Management cases",
            "core_tables_json": ["sn_customerservice_case"],
            "parent_table": "task",
            "plugins_json": ["com.sn_csm"],
            "keywords_json": ["csm", "customer"],
            "display_order": 110,
        },
    ]

    for app_data in apps:
        name = app_data["name"]
        overrides = _GLOBAL_APP_OVERRIDES.get(name, {})

        # Merge override tables/keywords into seed data (deduplicated)
        merged_tables = _dedupe_list(app_data["core_tables_json"] + overrides.get("tables", []))
        merged_keywords = _dedupe_list(app_data["keywords_json"] + overrides.get("keywords", []))
        table_prefixes = overrides.get("table_prefixes", [])

        app_data["core_tables_json"] = json.dumps(merged_tables)
        app_data["keywords_json"] = json.dumps(merged_keywords)
        app_data["plugins_json"] = json.dumps(app_data["plugins_json"])
        app_data["table_prefixes_json"] = json.dumps(table_prefixes) if table_prefixes else None

        existing = session.query(GlobalApp).filter(GlobalApp.name == name).first()
        if existing:
            # Update existing records to backfill merged data
            existing.core_tables_json = app_data["core_tables_json"]
            existing.keywords_json = app_data["keywords_json"]
            existing.table_prefixes_json = app_data["table_prefixes_json"]
        else:
            app = GlobalApp(**app_data)
            session.add(app)

    session.commit()
    print(f"Seeded {len(apps)} global apps")


def seed_app_file_classes(session: Session):
    """Seed the AppFileClass table with known application file types"""
    classes = app_file_class_seed_rows()

    for class_data in classes:
        existing = session.query(AppFileClass).filter(
            AppFileClass.sys_class_name == class_data["sys_class_name"]
        ).first()
        if not existing:
            file_class = AppFileClass(**class_data)
            session.add(file_class)

    session.commit()
    print(f"Seeded {len(classes)} app file classes")


def seed_number_sequences(session: Session):
    """Initialize number sequences"""

    sequences = [
        {"prefix": "ASMT", "current_value": 0, "padding": 7},  # ASMT0000001
    ]

    for seq_data in sequences:
        existing = session.query(NumberSequence).filter(
            NumberSequence.prefix == seq_data["prefix"]
        ).first()
        if not existing:
            seq = NumberSequence(**seq_data)
            session.add(seq)

    session.commit()
    print(f"Seeded {len(sequences)} number sequences")


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

    print(f"Seeded {len(new_records)} best practices ({len(checks)} total defined)")


def seed_app_file_class_queries(session: Session):
    """Seed the AppFileClassQuery table from scan_rules.yaml app_file_class_queries.

    Each YAML entry may produce 1 or 2 rows (table_pattern and/or keyword_pattern).
    Idempotent — skips rows where (app_file_class_id, query_type, pattern) already exists.
    """

    # Map from YAML app_file_class_queries section
    query_defs = [
        # (sys_class_name, query_type, pattern, target_table_field, display_order)
        ("sys_script", "table_pattern", "ref_sys_script.collectionLIKE{table}", "ref_sys_script.collection", 10),
        ("sys_script_client", "table_pattern", "ref_sys_script_client.tableLIKE{table}", "ref_sys_script_client.table", 10),
        ("sys_ui_policy", "table_pattern", "ref_sys_ui_policy.tableLIKE{table}", "ref_sys_ui_policy.table", 10),
        ("sys_ui_action", "table_pattern", "ref_sys_ui_action.tableLIKE{table}", "ref_sys_ui_action.table", 10),
        ("sys_ui_policy_action", "table_pattern", "ref_sys_ui_policy_action.ui_policy.tableLIKE{table}", "ref_sys_ui_policy_action.ui_policy.table", 10),
        ("sys_data_policy2", "table_pattern", "ref_sys_data_policy2.tableLIKE{table}", "ref_sys_data_policy2.table", 10),
        ("wf_workflow", "table_pattern", "ref_wf_workflow.tableLIKE{table}", "ref_wf_workflow.table", 10),
        ("sys_report", "table_pattern", "ref_sys_report.tableLIKE{table}", "ref_sys_report.table", 10),
        ("sys_dictionary", "keyword_pattern", "123TEXTQUERY321={keyword}", None, 10),
        ("sys_choice", "table_pattern", "ref_sys_choice.nameSTARTSWITH{table}.", "ref_sys_choice.name", 10),
        ("sys_script_include", "keyword_pattern", "{base}^nameLIKE{keyword}^OR{base}^scriptLIKE{keyword}", None, 10),
        ("sp_widget", "keyword_pattern", "123TEXTQUERY321={keyword}", None, 10),
        ("sp_page", "keyword_pattern", "123TEXTQUERY321={keyword}", None, 10),
    ]

    # Build lookup of sys_class_name → AppFileClass.id
    all_classes = session.exec(select(AppFileClass)).all()
    class_id_map = {c.sys_class_name: c.id for c in all_classes}

    # Build set of existing queries for idempotency
    existing_queries = session.exec(select(AppFileClassQuery)).all()
    existing_keys = {
        (q.app_file_class_id, q.query_type, q.pattern)
        for q in existing_queries
    }

    created = 0
    for sys_class_name, query_type, pattern, target_table_field, display_order in query_defs:
        class_id = class_id_map.get(sys_class_name)
        if class_id is None:
            print(f"  WARN: AppFileClass '{sys_class_name}' not found, skipping query seed")
            continue

        key = (class_id, query_type, pattern)
        if key in existing_keys:
            continue

        query = AppFileClassQuery(
            app_file_class_id=class_id,
            query_type=query_type,
            pattern=pattern,
            target_table_field=target_table_field,
            description=f"{query_type} for {sys_class_name}",
            display_order=display_order,
        )
        session.add(query)
        created += 1

    session.commit()
    print(f"Seeded {created} app file class queries ({len(query_defs)} total defined)")


def seed_assessment_type_configs(session: Session):
    """Seed the AssessmentTypeConfig table from scan_rules.yaml assessment_types.

    Idempotent — skips rows where name already exists.
    """

    configs = [
        {
            "name": "global_app",
            "label": "Global Application",
            "description": "Scan customizations for a global ITSM application",
            "required_fields_json": json.dumps(["target_app_id", "app_file_classes_json"]),
            "default_scans_json": json.dumps(["metadata_index"]),
            "scope_options_json": json.dumps(["all", "global"]),
            "drivers_json": json.dumps(["core_tables", "keywords"]),
            "display_order": 10,
        },
        {
            "name": "table",
            "label": "Table Assessment",
            "description": "Scan customizations for specific tables",
            "required_fields_json": json.dumps(["target_tables_json", "app_file_classes_json"]),
            "default_scans_json": json.dumps(["metadata_index"]),
            "scope_options_json": json.dumps(["all", "global"]),
            "drivers_json": json.dumps(["target_tables", "keywords"]),
            "display_order": 20,
        },
        {
            "name": "plugin",
            "label": "Plugin Assessment",
            "description": "Scan customizations for specific plugins",
            "required_fields_json": json.dumps(["target_plugins_json", "app_file_classes_json"]),
            "default_scans_json": json.dumps(["metadata_index"]),
            "scope_options_json": json.dumps(["all", "global"]),
            "drivers_json": json.dumps(["plugins"]),
            "display_order": 30,
        },
        {
            "name": "platform_global",
            "label": "Platform Global",
            "description": "Scan across entire platform",
            "required_fields_json": json.dumps(["app_file_classes_json"]),
            "default_scans_json": json.dumps(["metadata_index"]),
            "scope_options_json": json.dumps(["all", "global"]),
            "drivers_json": json.dumps([]),
            "display_order": 40,
        },
    ]

    for cfg_data in configs:
        existing = session.query(AssessmentTypeConfig).filter(
            AssessmentTypeConfig.name == cfg_data["name"]
        ).first()
        if not existing:
            session.add(AssessmentTypeConfig(**cfg_data))

    session.commit()
    print(f"Seeded {len(configs)} assessment type configs")


def seed_assessment_type_file_classes(session: Session):
    """Seed the AssessmentTypeFileClass junction table.

    Links each assessment type to the file classes that are relevant/default
    for that type.  Currently all active file classes are linked to
    ``global_app`` (existing behaviour).  Other types get the same initial
    set but can be customised later via the admin UI.

    Idempotent — skips rows where (assessment_type_config_id, app_file_class_id)
    already exists.
    """
    all_types = session.exec(select(AssessmentTypeConfig)).all()
    type_map = {t.name: t.id for t in all_types}
    all_classes = session.exec(
        select(AppFileClass).where(AppFileClass.is_active == True)
    ).all()

    existing = session.exec(select(AssessmentTypeFileClass)).all()
    existing_keys = {(r.assessment_type_config_id, r.app_file_class_id) for r in existing}

    created = 0
    for type_name, type_id in type_map.items():
        for idx, fc in enumerate(all_classes):
            key = (type_id, fc.id)
            if key in existing_keys:
                continue
            session.add(AssessmentTypeFileClass(
                assessment_type_config_id=type_id,
                app_file_class_id=fc.id,
                is_default=True,
                display_order=idx * 10,
            ))
            created += 1

    session.commit()
    print(f"Seeded {created} assessment-type ↔ file-class links ({len(type_map)} types × {len(all_classes)} classes)")


def run_seed():
    """Run all seed operations"""
    with Session(engine) as session:
        print("Seeding database...")
        seed_global_apps(session)
        seed_app_file_classes(session)
        seed_number_sequences(session)
        seed_best_practices(session)
        seed_app_file_class_queries(session)
        seed_assessment_type_configs(session)
        seed_assessment_type_file_classes(session)
        print("Seed complete!")


if __name__ == "__main__":
    run_seed()
