# Codex Full App UI Modularization Audit

> Date: 2026-02-15  
> Scope: Whole app UI (all major templates/components), not assessment-only

## 1. Scope and Intent
This audit reviewed UI architecture consistency across the app, with focus on:
- reusable/modular components
- duplicated page logic
- maintainability and technical debt reduction
- places to add system-property-driven UI behavior for tenant-level adjustability

Reviewed surfaces include dashboard, instances, preflight/data browser, dynamic browser, job log, CSDM ingestion, assessments, results, scan detail, result detail, artifact detail, analytics, MCP console, and integration properties pages.

## 2. High-Level Conclusion
The app has a solid reusable core (`DataTable`, `ConditionBuilder`, `ColumnPicker`), but many high-traffic pages still use page-local script/controller patterns. The largest debt is duplicated results filtering/rendering flows, duplicated polling/status engines, inconsistent API client handling, and oversized inline scripts in templates.

## 3. Opportunity Matrix (H/M/L)

### 3.1 [H] Unify Results Grids into one reusable module
Current issue:
- Similar results list logic is implemented separately in global results, assessment detail, and scan detail.

Value:
- High reduction in drift and regression risk.

Recommendation:
- Build one reusable `ResultsGridController` (or DataTable adapter) configurable by scope (`global`, `assessment`, `scan`) and endpoints.

Primary references:
- `tech-assessment-hub/src/web/templates/results.html`
- `tech-assessment-hub/src/web/templates/assessment_detail.html`
- `tech-assessment-hub/src/web/templates/scan_detail.html`

### 3.2 [H] Extract large inline scripts into page modules
Current issue:
- Multiple templates contain large inline JS blocks, coupling markup + controller logic and making QA/refactor harder.

Value:
- High maintainability improvement and cleaner ownership boundaries.

Recommendation:
- Move inline scripts to `src/web/static/js/pages/*` and keep templates to markup + bootstrap payload only.

Primary references:
- `tech-assessment-hub/src/web/templates/assessment_detail.html`
- `tech-assessment-hub/src/web/templates/instance_assessment_app_file_options.html`
- `tech-assessment-hub/src/web/templates/csdm_ingestion.html`

### 3.3 [H] Create one polling/status engine
Current issue:
- Polling exists in several pages with custom intervals, lifecycle handling, and stop logic.

Value:
- High reliability gain; reduces stale status bugs and background load.

Recommendation:
- Implement shared polling manager with:
  - start/stop controls
  - in-flight guard
  - optional backoff
  - page visibility pause/resume
  - standardized run-state mapping

Primary references:
- `tech-assessment-hub/src/web/templates/assessment_detail.html`
- `tech-assessment-hub/src/web/templates/instance_data.html`
- `tech-assessment-hub/src/web/templates/csdm_ingestion.html`
- `tech-assessment-hub/src/web/static/js/data_browser.js`
- `tech-assessment-hub/src/web/static/js/app.js`

### 3.4 [H] Standardize API + notification layer
Current issue:
- Multiple fetch wrappers (`apiCall`, `fetchJson`, `apiPost`) and extensive `alert/confirm` usage.

Value:
- High consistency and lower bug surface for auth headers/error normalization.

Recommendation:
- Add shared `api_client.js` and `ui_notifications.js`:
  - consistent request options
  - unified error shape
  - centralized admin-token/header handling
  - standardized non-blocking notifications and confirm modals

Primary references:
- `tech-assessment-hub/src/web/static/js/app.js`
- `tech-assessment-hub/src/web/static/js/mcp_console.js`
- `tech-assessment-hub/src/web/static/js/integration_properties.js`
- `tech-assessment-hub/src/web/templates/csdm_ingestion.html`

### 3.5 [H] Expand reusable table adoption beyond current pages
Current issue:
- Reusable table stack is strong but used in a limited set of pages.

Value:
- High long-term debt reduction and feature consistency.

Recommendation:
- Extend `DataTable` with optional row actions/cell render hooks and migrate remaining table-heavy screens.

Primary references:
- `tech-assessment-hub/src/web/templates/dynamic_browser.html`
- `tech-assessment-hub/src/web/templates/job_log.html`
- `tech-assessment-hub/src/web/static/js/data_browser.js`
- `tech-assessment-hub/src/web/templates/results.html`

### 3.6 [H] Break up App File Options mega-controller
Current issue:
- One page has a large custom in-template controller for grouping/sorting/bulk actions.

Value:
- High maintainability gain for an admin-critical surface.

Recommendation:
- Move to dedicated module/component with isolated state + reusable table behaviors.

Primary references:
- `tech-assessment-hub/src/web/templates/instance_assessment_app_file_options.html`

### 3.7 [M] Introduce shared tab controller
Current issue:
- Several pages implement near-identical tab logic.

Value:
- Medium (small but repeated duplication).

Recommendation:
- Add one tab utility driven by data attributes and optional lazy-load callback hook.

Primary references:
- `tech-assessment-hub/src/web/templates/assessment_detail.html`
- `tech-assessment-hub/src/web/templates/scan_detail.html`
- `tech-assessment-hub/src/web/templates/result_detail.html`

### 3.8 [M] Standardize modal framework
Current issue:
- Different modal patterns are used across pages (inventory, dict pull, preview, raw).

Value:
- Medium UX and accessibility consistency.

Recommendation:
- Create one modal host/component supporting size presets, scroll behavior, title/actions, ESC/outside-close policy.

Primary references:
- `tech-assessment-hub/src/web/templates/base.html`
- `tech-assessment-hub/src/web/templates/instances.html`
- `tech-assessment-hub/src/web/templates/data_browser.html`
- `tech-assessment-hub/src/web/templates/result_detail.html`

### 3.9 [H] Add UI-focused system properties
Current issue:
- Integration properties currently emphasize fetch/timezone, with little UI runtime configurability.

Value:
- High for multi-tenant deployments needing tenant-specific preferences without code edits.

Recommendation:
- Add `ui.*` properties for:
  - poll intervals/timeouts
  - default page sizes
  - default theme
  - modal/preview sizing
  - module visibility toggles

Primary references:
- `tech-assessment-hub/src/services/integration_properties.py`
- `tech-assessment-hub/src/web/templates/base.html`
- `tech-assessment-hub/src/web/static/js/app.js`

### 3.10 [M] Split monolithic CSS into component/page layers
Current issue:
- `style.css` is large and cross-cutting, making regressions easier.

Value:
- Medium maintainability and safer styling changes.

Recommendation:
- Split into component-level styles (`table`, `tabs`, `modal`, `forms`) plus page-specific overrides.

Primary references:
- `tech-assessment-hub/src/web/static/css/style.css`
- `tech-assessment-hub/src/web/static/css/themes.css`

### 3.11 [M] Harden client-side HTML rendering patterns
Current issue:
- Some table rows and details are assembled via `innerHTML` with API data.

Value:
- Medium security hardening and safer future changes.

Recommendation:
- Prefer DOM-node construction or centralized escaping utility for all dynamic HTML paths.

Primary references:
- `tech-assessment-hub/src/web/templates/results.html`
- `tech-assessment-hub/src/web/templates/scan_detail.html`
- `tech-assessment-hub/src/web/templates/assessment_detail.html`

## 4. Suggested Implementation Order
1. [H] #3.1 + #3.3 + #3.4 first (highest leverage).
2. [H] #3.5 + #3.6 next (table/component modularization).
3. [H] #3.9 next (tenant adjustability via properties).
4. [M] #3.7 + #3.8 + #3.10 + #3.11 final hardening pass.

## 5. Assessment-Specific Overlap With Claude’s Findings
Overlap found:
- tab logic duplication
- results rendering/filter duplication
- artifact list/detail duplication
- date formatting duplication and inconsistency

Additional assessment-relevant items from this full-app audit:
- shared polling engine (assessment + scan pages + other modules)
- standardized API client/notifications across all pages
- migration path toward common table stack instead of custom page tables
- broader UI system-property strategy for tenant-level behavior tuning
