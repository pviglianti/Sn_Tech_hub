---
name: servicenow-core
description: >
  Core ServiceNow development rules: ES5 scripting standards, strict URL
  fetching, update set protocols, and platform API patterns. Load this skill
  whenever working with ServiceNow artifacts or code.
metadata:
  domain: servicenow
---

# ServiceNow Core Development Rules

## JavaScript Standards
- ServiceNow server-side scripting uses **ES5 only**. No arrow functions,
  no let/const, no template literals, no destructuring, no async/await.
- Use `var` for all variable declarations.
- Use string concatenation, not template literals.
- Use `function(){}` not `() => {}`.

## GlideRecord Patterns
- Always check `gr.next()` before accessing fields.
- Use `gr.addQuery()` / `gr.addEncodedQuery()` — never raw SQL.
- Use `gr.getValue('field')` not `gr.field` for safety.
- Always set `gr.setLimit()` when you only need one record.
- Use `GlideAggregate` for counts — never iterate to count.

## URL and External Calls
- Never hardcode instance URLs. Use `gs.getProperty('glide.servlet.uri')`.
- Use `GlideHTTPRequest` or `RESTMessageV2` for outbound calls — never
  raw XMLHttpRequest on server side.
- All outbound calls should be async where possible (via scheduled jobs
  or flow designer).

## Update Sets and Scoping
- All customizations should target a specific update set, never Default.
- Scoped apps: respect scope boundaries. Don't use `global` scope unless
  the artifact is genuinely global.
- Check `sys_scope` on artifacts to understand their application context.

## Common Anti-Patterns
- `setWorkflow(false)` — bypasses business rules and ACLs. Flag as risk.
- Hardcoded sys_ids — use sys_properties or system properties instead.
- `current.update()` inside a business rule — causes infinite loops.
- Client-side GlideRecord — use GlideAjax or REST instead.
- Global business rules — should almost always be table-specific.

## Platform Knowledge
- `sys_script` = Business Rule
- `sys_script_include` = Script Include
- `sys_ui_policy` = UI Policy
- `sys_ui_action` = UI Action
- `sys_dictionary` = Dictionary Entry (field definition)
- `sys_choice` = Choice list entry
- `sys_db_object` = Table definition
