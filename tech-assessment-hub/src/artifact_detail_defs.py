"""Per-class artifact detail field definitions.

Curated from sys_dictionary pull (Instance 5 / BVP 3, 2026-02-15).
Each entry tells the artifact detail pull:
  - which SN fields to request (sysparm_fields)
  - the local DB table name
  - which field holds the primary script/code content
  - field metadata for building typed SQLModel columns

Field tuples: (sn_element, display_label, py_type)
  py_type: "str"  = short string (VARCHAR/TEXT)
           "text" = long text / script / code (TEXT, potentially large)
           "bool" = boolean (stored as 0/1)
           "int"  = integer
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Fields inherited from sys_metadata — present on EVERY SN table.
# The detail pull appends these automatically; no need to repeat per class.
COMMON_INHERITED_FIELDS: List[Tuple[str, str, str]] = [
    ("sys_created_by", "Created by", "str"),
    ("sys_created_on", "Created", "str"),
    ("sys_updated_by", "Updated by", "str"),
    ("sys_updated_on", "Updated", "str"),
    ("sys_mod_count", "Updates", "int"),
    ("sys_scope", "Scope", "str"),
    ("sys_package", "Package", "str"),
    ("sys_class_name", "Class", "str"),
    ("sys_policy", "Protection policy", "str"),
]


# ---------------------------------------------------------------------------
# Per-class field definitions keyed by sys_class_name
# ---------------------------------------------------------------------------

ARTIFACT_DETAIL_DEFS: Dict[str, Dict[str, Any]] = {

    # ------------------------------------------------------------------
    # Business Rule
    # ------------------------------------------------------------------
    "sys_script": {
        "local_table": "asmt_business_rule",
        "code_fields": ["script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("collection", "Table", "str"),
            ("when", "When", "str"),
            ("order", "Order", "int"),
            ("priority", "Priority", "int"),
            ("advanced", "Advanced", "bool"),
            ("action_insert", "Insert", "bool"),
            ("action_update", "Update", "bool"),
            ("action_delete", "Delete", "bool"),
            ("action_query", "Query", "bool"),
            ("condition", "Condition", "str"),
            ("filter_condition", "Filter Conditions", "text"),
            ("script", "Script", "text"),
            ("abort_action", "Abort action", "bool"),
            ("add_message", "Add message", "bool"),
            ("message", "Message", "text"),
            ("execute_function", "Execute function", "bool"),
            ("client_callable", "Client callable", "bool"),
            ("change_fields", "Update reference fields", "bool"),
            ("is_rest", "Web Services", "bool"),
            ("access", "Accessible from", "str"),
            ("role_conditions", "Role conditions", "str"),
            ("description", "Description", "text"),
            ("template", "Set field values", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # Script Include
    # ------------------------------------------------------------------
    "sys_script_include": {
        "local_table": "asmt_script_include",
        "code_fields": ["script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("api_name", "API Name", "str"),
            ("access", "Accessible from", "str"),
            ("caller_access", "Caller Access", "str"),
            ("client_callable", "Client callable", "bool"),
            ("mobile_callable", "Mobile callable", "bool"),
            ("sandbox_callable", "Sandbox enabled", "bool"),
            ("description", "Description", "text"),
            ("script", "Script", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # Client Script
    # ------------------------------------------------------------------
    "sys_script_client": {
        "local_table": "asmt_client_script",
        "code_fields": ["script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("table", "Table", "str"),
            ("type", "Type", "str"),
            ("ui_type", "UI Type", "int"),
            ("field", "Field name", "str"),
            ("order", "Order", "int"),
            ("applies_extended", "Inherited", "bool"),
            ("global", "Global", "bool"),
            ("isolate_script", "Isolate script", "bool"),
            ("condition", "Condition / onClick", "str"),
            ("description", "Description", "text"),
            ("messages", "Messages", "str"),
            ("view", "View", "str"),
            ("script", "Script", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # UI Policy
    # ------------------------------------------------------------------
    "sys_ui_policy": {
        "local_table": "asmt_ui_policy",
        "code_fields": ["script_true", "script_false"],
        "fields": [
            ("short_description", "Short description", "str"),
            ("active", "Active", "bool"),
            ("table", "Table", "str"),
            ("order", "Order", "int"),
            ("conditions", "Conditions", "text"),
            ("on_load", "On load", "bool"),
            ("global", "Global", "bool"),
            ("inherit", "Inherit", "bool"),
            ("reverse_if_false", "Reverse if false", "bool"),
            ("run_scripts", "Run scripts", "bool"),
            ("isolate_script", "Isolate script", "bool"),
            ("ui_type", "Run scripts in UI type", "int"),
            ("script_true", "Execute if true", "text"),
            ("script_false", "Execute if false", "text"),
            ("description", "Description", "text"),
            ("set_values", "Set values", "text"),
            ("view", "View", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # UI Policy Action
    # ------------------------------------------------------------------
    "sys_ui_policy_action": {
        "local_table": "asmt_ui_policy_action",
        "code_fields": [],
        "fields": [
            ("table", "Table", "str"),
            ("ui_policy", "UI policy", "str"),
            ("field", "Field name", "str"),
            ("disabled", "Read only", "str"),
            ("mandatory", "Mandatory", "str"),
            ("visible", "Visible", "str"),
            ("value", "Value", "str"),
            ("value_action", "Value action", "str"),
            ("cleared", "Clear the field value", "bool"),
            ("field_message", "Field message", "str"),
            ("field_message_type", "Field message type", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # UI Action
    # ------------------------------------------------------------------
    "sys_ui_action": {
        "local_table": "asmt_ui_action",
        "code_fields": ["script", "client_script_v2"],
        "fields": [
            ("name", "Name", "str"),
            ("action_name", "Action name", "str"),
            ("active", "Active", "bool"),
            ("table", "Table", "str"),
            ("order", "Order", "int"),
            ("comments", "Comments", "str"),
            ("condition", "Condition", "text"),
            ("client", "Client", "bool"),
            ("isolate_script", "Isolate script", "bool"),
            ("script", "Script", "text"),
            ("client_script_v2", "Workspace Client Script", "text"),
            ("onclick", "Onclick", "str"),
            ("hint", "Hint", "str"),
            ("messages", "Messages", "str"),
            # Form placement
            ("form_action", "Form action", "bool"),
            ("form_button", "Form button", "bool"),
            ("form_button_v2", "Workspace Form Button", "bool"),
            ("form_context_menu", "Form context menu", "bool"),
            ("form_link", "Form link", "bool"),
            ("form_menu_button_v2", "Workspace Form Menu", "bool"),
            ("form_style", "Form style", "str"),
            # List placement
            ("list_action", "List action", "bool"),
            ("list_banner_button", "List banner button", "bool"),
            ("list_button", "List bottom button", "bool"),
            ("list_choice", "List choice", "bool"),
            ("list_context_menu", "List context menu", "bool"),
            ("list_link", "List link", "bool"),
            ("list_save_with_form_button", "Save with form button", "bool"),
            ("list_style", "List style", "str"),
            # Visibility
            ("show_insert", "Show insert", "bool"),
            ("show_update", "Show update", "bool"),
            ("show_multiple_update", "Show multiple update", "bool"),
            ("show_query", "Show query", "bool"),
            ("format_for_configurable_workspace", "Format for Configurable Workspace", "bool"),
            ("ui11_compatible", "List v2 Compatible", "bool"),
            ("ui16_compatible", "List v3 Compatible", "bool"),
        ],
    },

    # ------------------------------------------------------------------
    # UI Page
    # ------------------------------------------------------------------
    "sys_ui_page": {
        "local_table": "asmt_ui_page",
        "code_fields": ["html", "client_script", "processing_script"],
        "fields": [
            ("name", "Name", "str"),
            ("description", "Description", "text"),
            ("category", "Category", "str"),
            ("direct", "Direct", "bool"),
            ("endpoint", "Endpoint", "str"),
            ("html", "HTML", "text"),
            ("client_script", "Client script", "text"),
            ("processing_script", "Processing script", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # UI Macro
    # ------------------------------------------------------------------
    "sys_ui_macro": {
        "local_table": "asmt_ui_macro",
        "code_fields": ["xml"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("description", "Description", "text"),
            ("category", "Category", "str"),
            ("media_type", "Media type", "str"),
            ("scoped_name", "API Name", "str"),
            ("xml", "XML", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # Dictionary Entry
    # ------------------------------------------------------------------
    "sys_dictionary": {
        "local_table": "asmt_dictionary_entry",
        "code_fields": ["calculation"],
        "fields": [
            ("name", "Table", "str"),
            ("element", "Column name", "str"),
            ("column_label", "Column label", "str"),
            ("internal_type", "Type", "str"),
            ("max_length", "Max length", "int"),
            ("mandatory", "Mandatory", "bool"),
            ("read_only", "Read only", "bool"),
            ("active", "Active", "bool"),
            ("unique", "Unique", "bool"),
            ("display", "Display", "bool"),
            ("primary", "Primary", "bool"),
            ("default_value", "Default value", "str"),
            ("choice", "Choice", "int"),
            ("reference", "Reference", "str"),
            ("reference_qual", "Reference qual", "str"),
            ("dependent", "Dependent", "str"),
            ("dependent_on_field", "Dependent on field", "str"),
            ("use_dependent_field", "Use dependent field", "bool"),
            ("attributes", "Attributes", "text"),
            ("calculation", "Calculation", "text"),
            ("virtual", "Calculated", "bool"),
            ("audit", "Audit", "bool"),
            ("create_roles", "Create roles", "str"),
            ("read_roles", "Read roles", "str"),
            ("write_roles", "Write roles", "str"),
            ("delete_roles", "Delete roles", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Dictionary Override
    # ------------------------------------------------------------------
    "sys_dictionary_override": {
        "local_table": "asmt_dictionary_override",
        "code_fields": [],
        "fields": [
            ("name", "Table", "str"),
            ("element", "Column name", "str"),
            ("attributes", "Attributes", "str"),
            ("default_value", "Default value", "str"),
            ("mandatory", "Mandatory", "bool"),
            ("read_only", "Read only", "bool"),
            ("display_override", "Display override", "bool"),
            ("reference_qual", "Reference qual", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Choice List
    # ------------------------------------------------------------------
    "sys_choice": {
        "local_table": "asmt_choice_list",
        "code_fields": [],
        "fields": [
            ("name", "Table", "str"),
            ("element", "Element", "str"),
            ("label", "Label", "str"),
            ("value", "Value", "str"),
            ("sequence", "Sequence", "int"),
            ("language", "Language", "str"),
            ("dependent_value", "Dependent value", "str"),
            ("hint", "Hint", "str"),
            ("inactive", "Inactive", "bool"),
            ("synonyms", "Synonyms", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Table (sys_db_object)
    # ------------------------------------------------------------------
    "sys_db_object": {
        "local_table": "asmt_table",
        "code_fields": [],
        "fields": [
            ("name", "Name", "str"),
            ("label", "Label", "str"),
            ("super_class", "Extends table", "str"),
            ("is_extendable", "Extensible", "bool"),
            ("extension_model", "Extension model", "str"),
            ("access", "Accessible from", "str"),
            ("caller_access", "Caller Access", "str"),
            ("number_ref", "Auto number", "str"),
            ("user_role", "User role", "str"),
            ("create_access", "Can create", "bool"),
            ("read_access", "Can read", "bool"),
            ("update_access", "Can update", "bool"),
            ("delete_access", "Can delete", "bool"),
            ("actions_access", "Allow UI actions", "bool"),
            ("alter_access", "Allow new fields", "bool"),
            ("configuration_access", "Allow configuration", "bool"),
            ("client_scripts_access", "Allow client scripts", "bool"),
            ("create_access_controls", "Create access controls", "bool"),
            ("live_feed_enabled", "Live feed", "bool"),
            ("ws_access", "Allow web services", "bool"),
            ("scriptable_table", "Remote Table", "bool"),
            ("is_df_table", "DataFabric Table", "bool"),
        ],
    },

    # ------------------------------------------------------------------
    # Data Policy
    # ------------------------------------------------------------------
    "sys_data_policy2": {
        "local_table": "asmt_data_policy",
        "code_fields": [],
        "fields": [
            ("short_description", "Short description", "str"),
            ("active", "Active", "bool"),
            ("description", "Description", "text"),
            ("model_table", "Table", "str"),
            ("conditions", "Conditions", "text"),
            ("apply_import_set", "Apply to import sets", "bool"),
            ("apply_soap", "Apply to SOAP", "bool"),
            ("enforce_ui", "Use as UI Policy on client", "bool"),
            ("inherit", "Inherit", "bool"),
            ("reverse_if_false", "Reverse if false", "bool"),
        ],
    },

    # ------------------------------------------------------------------
    # Access Control (ACL)
    # ------------------------------------------------------------------
    "sys_security_acl": {
        "local_table": "asmt_acl",
        "code_fields": ["script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("description", "Description", "text"),
            ("operation", "Operation", "str"),
            ("type", "Type", "str"),
            ("decision_type", "Decision Type", "str"),
            ("condition", "Condition", "text"),
            ("applies_to", "Applies To", "text"),
            ("advanced", "Advanced", "bool"),
            ("script", "Script", "text"),
            ("admin_overrides", "Admin overrides", "bool"),
            ("local_or_existing", "Local or Existing", "str"),
            ("security_attribute", "Security Attribute", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Scheduled Job
    # ------------------------------------------------------------------
    "sysauto_script": {
        "local_table": "asmt_scheduled_job",
        "code_fields": ["script"],
        "fields": [
            # Own fields from sys_dictionary pull
            ("script", "Script", "text"),
            # Inherited from sysauto (parent table) — available via API
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("run_type", "Run", "str"),
            ("run_dayofweek", "Day of week", "str"),
            ("run_dayofmonth", "Day of month", "int"),
            ("run_time", "Time", "str"),
            ("run_start", "Starting", "str"),
            ("run_period", "Repeat interval", "str"),
            ("conditional", "Conditional", "bool"),
            ("condition", "Condition", "text"),
            ("upgrade_safe", "Upgrade safe", "bool"),
        ],
    },

    # ------------------------------------------------------------------
    # Email Notification
    # ------------------------------------------------------------------
    "sysevent_email_action": {
        "local_table": "asmt_email_notification",
        "code_fields": ["advanced_condition", "message_html"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("collection", "Table", "str"),
            ("event_name", "Event name", "str"),
            ("action_insert", "Inserted", "bool"),
            ("action_update", "Updated", "bool"),
            ("generation_type", "Send when", "str"),
            ("type", "Type", "str"),
            ("condition", "Conditions", "text"),
            ("advanced_condition", "Advanced condition", "text"),
            ("subject", "Subject", "str"),
            ("message", "Message", "text"),
            ("message_html", "Message HTML", "text"),
            ("message_text", "Message text", "text"),
            ("content_type", "Content type", "str"),
            ("from", "From", "str"),
            ("reply_to", "Reply to", "str"),
            ("importance", "Importance", "str"),
            ("weight", "Weight", "int"),
            ("recipient_users", "Users", "str"),
            ("recipient_groups", "Groups", "str"),
            ("recipient_fields", "Users/Groups in fields", "str"),
            ("event_parm_1", "Event parm 1 contains recipient", "bool"),
            ("event_parm_2", "Event parm 2 contains recipient", "bool"),
            ("force_delivery", "Force delivery", "bool"),
            ("mandatory", "Mandatory", "bool"),
            ("send_self", "Send to event creator", "bool"),
            ("exclude_delegates", "Exclude delegates", "bool"),
            ("include_attachments", "Include attachments", "bool"),
            ("subscribable", "Subscribable", "bool"),
            ("digestable", "Allow Digest", "bool"),
            ("omit_watermark", "Omit watermark", "bool"),
            ("category", "Category", "str"),
            ("template", "Email template", "str"),
            ("style", "Stationery", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Event Script
    # ------------------------------------------------------------------
    "sysevent_script_action": {
        "local_table": "asmt_event_script",
        "code_fields": ["script", "condition_script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("event_name", "Event name", "str"),
            ("synchronous", "Synchronous", "bool"),
            ("condition_script", "Condition script", "text"),
            ("script", "Script", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # Flow (Flow Designer)
    # ------------------------------------------------------------------
    "sys_hub_flow": {
        "local_table": "asmt_flow",
        "code_fields": [],
        "fields": [
            # Inherited from sys_hub_action_base / sys_metadata
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("description", "Description", "text"),
            ("status", "Status", "str"),
            ("trigger_type", "Trigger type", "str"),
            # Own fields
            ("display_name_after_preview", "Display name after preview", "str"),
            ("compiler_build", "Compiler build", "str"),
            ("generation_source", "Generation source", "str"),
            ("pre_compiled", "Pre-Compiled", "bool"),
            ("show_draft_actions", "Show draft actions", "bool"),
            ("show_triggered_flows", "Show triggered flows", "bool"),
            ("substatus", "Substatus", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Workflow (Legacy)
    # ------------------------------------------------------------------
    "wf_workflow": {
        "local_table": "asmt_workflow",
        "code_fields": [],
        "fields": [
            ("name", "Name", "str"),
            ("description", "Description", "text"),
            ("table", "Table", "str"),
            ("access", "Accessible from", "str"),
            ("template", "Template", "bool"),
        ],
    },

    # ------------------------------------------------------------------
    # Service Portal Widget
    # ------------------------------------------------------------------
    "sp_widget": {
        "local_table": "asmt_widget",
        "code_fields": ["script", "client_script", "css", "template", "link"],
        "fields": [
            ("name", "Name", "str"),
            ("id", "ID", "str"),
            ("description", "Description", "text"),
            ("category", "Category", "str"),
            ("data_table", "Data table", "str"),
            ("field_list", "Fields", "str"),
            ("controller_as", "controllerAs", "str"),
            ("has_preview", "Has preview", "bool"),
            ("internal", "Internal", "bool"),
            ("public", "Public", "bool"),
            ("servicenow", "Servicenow", "bool"),
            ("roles", "Roles", "str"),
            # Code fields
            ("client_script", "Client controller", "text"),
            ("script", "Server script", "text"),
            ("css", "CSS", "text"),
            ("template", "Body HTML template", "text"),
            ("link", "Link", "text"),
            ("option_schema", "Option schema", "text"),
            ("demo_data", "Demo data", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # Service Portal Page
    # ------------------------------------------------------------------
    "sp_page": {
        "local_table": "asmt_portal_page",
        "code_fields": ["css"],
        "fields": [
            ("id", "ID", "str"),
            ("title", "Title", "str"),
            ("short_description", "Short description", "str"),
            ("category", "Category", "str"),
            ("css", "Page Specific CSS", "text"),
            ("draft", "Draft", "bool"),
            ("internal", "Internal", "bool"),
            ("public", "Public", "bool"),
            ("omit_watcher", "Omit watcher", "bool"),
            ("roles", "Roles", "str"),
            ("seo_script", "SEO script", "str"),
            ("use_seo_script", "Use SEO script", "bool"),
            ("human_readable_url_structure", "Human readable URL", "str"),
            ("dynamic_title_structure", "Dynamic page title", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Transform Map
    # ------------------------------------------------------------------
    "sys_transform_map": {
        "local_table": "asmt_transform_map",
        "code_fields": ["script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("order", "Order", "int"),
            ("source_table", "Source table", "str"),
            ("target_table", "Target table", "str"),
            ("copy_empty_fields", "Copy empty fields", "bool"),
            ("create_new_record_on_empty_coalesce_fields", "Create on empty coalesce", "bool"),
            ("enforce_mandatory_fields", "Enforce mandatory fields", "str"),
            ("run_business_rules", "Run business rules", "bool"),
            ("run_script", "Run script", "bool"),
            ("script", "Script", "text"),
        ],
    },

    # ------------------------------------------------------------------
    # Scripted REST API
    # ------------------------------------------------------------------
    "sys_web_service": {
        "local_table": "asmt_scripted_rest_api",
        "code_fields": ["script"],
        "fields": [
            ("name", "Name", "str"),
            ("active", "Active", "bool"),
            ("function_name", "Function name", "str"),
            ("scoped_name", "Scoped name", "str"),
            ("short_description", "Short description", "str"),
            ("script", "Script", "text"),
            ("wsdl", "WSDL", "str"),
            ("wsdl_compliance", "WSDL Compliance", "bool"),
        ],
    },

    # ------------------------------------------------------------------
    # Form Layout
    # ------------------------------------------------------------------
    "sys_ui_form": {
        "local_table": "asmt_form_layout",
        "code_fields": [],
        "fields": [
            ("name", "Name", "str"),
            ("table", "Table", "str"),
            ("view", "View", "str"),
            ("position", "Position", "int"),
            ("section", "Section", "str"),
            ("element", "Element", "str"),
            ("type", "Type", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # List Layout
    # ------------------------------------------------------------------
    "sys_ui_list": {
        "local_table": "asmt_list_layout",
        "code_fields": [],
        "fields": [
            ("name", "Name", "str"),
            ("table", "Table", "str"),
            ("view", "View", "str"),
            ("element", "Element", "str"),
            ("position", "Position", "int"),
        ],
    },

    # ------------------------------------------------------------------
    # Related List
    # ------------------------------------------------------------------
    "sys_ui_related_list": {
        "local_table": "asmt_related_list",
        "code_fields": [],
        "fields": [
            ("name", "Name", "str"),
            ("table", "Table", "str"),
            ("view", "View", "str"),
            ("related_list", "Related list", "str"),
            ("position", "Position", "int"),
        ],
    },

    # ------------------------------------------------------------------
    # Report (subset — full table has 146 fields)
    # ------------------------------------------------------------------
    "sys_report": {
        "local_table": "asmt_report",
        "code_fields": [],
        "fields": [
            ("title", "Title", "str"),
            ("active", "Active", "bool"),
            ("description", "Description", "text"),
            ("table", "Table", "str"),
            ("field", "Field Name", "str"),
            ("type", "Type", "str"),
            ("aggregate", "Aggregate", "str"),
            ("filter", "Filter", "text"),
            ("group", "Group", "str"),
            ("column", "Column", "str"),
            ("row", "Row", "str"),
            ("content", "Content", "text"),
            ("roles", "Roles", "str"),
            ("is_published", "Is published", "bool"),
            ("is_scheduled", "Is scheduled", "bool"),
            ("is_real_time", "Is real time", "bool"),
            ("chart_size", "Chart size", "str"),
            ("chart_title", "Chart title", "str"),
            ("direction", "Direction", "str"),
            ("interval", "Interval", "str"),
            ("source_type", "Source type", "str"),
            ("user", "User", "str"),
        ],
    },

    # ------------------------------------------------------------------
    # Update Set
    # ------------------------------------------------------------------
    "sys_update_set": {
        "local_table": "asmt_update_set",
        "code_fields": [],
        "fields": [
            ("name", "Name", "str"),
            ("description", "Description", "text"),
            ("state", "State", "str"),
            ("application", "Application", "str"),
            ("release_date", "Release date", "str"),
            ("base_update_set", "Base update set", "str"),
            ("is_default", "Default set", "bool"),
            ("installed_from", "Installed from", "str"),
            ("origin_sys_id", "Origin sys id", "str"),
            ("remote_sys_id", "Remote sys id", "str"),
            ("parent", "Parent", "str"),
        ],
    },
}


def get_detail_def(sys_class_name: str) -> Dict[str, Any] | None:
    """Return the detail definition for a given sys_class_name, or None."""
    return ARTIFACT_DETAIL_DEFS.get(sys_class_name)


def get_sn_fields_for_class(sys_class_name: str, include_common: bool = True) -> list[str]:
    """Return the list of SN field element names to request for a class.

    Always includes sys_id. Optionally appends COMMON_INHERITED_FIELDS.
    """
    defn = ARTIFACT_DETAIL_DEFS.get(sys_class_name)
    if not defn:
        return ["sys_id"]
    fields = ["sys_id"] + [f[0] for f in defn["fields"]]
    if include_common:
        fields.extend(f[0] for f in COMMON_INHERITED_FIELDS)
    return fields
