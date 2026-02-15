# 09 — Tool Mapping Matrix (Keep / Adapt / Defer)

> **Scope**: Unified ServiceNow MCP tool domains under `packages/core/src/mcp/servicenow-mcp-unified/tools/`
> **Source**: takeover continuation audit (Codex)
> **Status**: DONE (takeover batch)

---

## 1. Purpose

This matrix maps Snow-flow tool domains to our assessment-platform objective:
- preserve high-value read/analysis capabilities
- avoid early migration of low-value or write-heavy domains
- keep token and implementation cost focused on Phases 9B/10/11

---

## 2. Decision Legend

- `EXTRACT_NOW`: bring into initial MCP adaptation wave
- `ADAPT_PHASE_2`: useful, but schedule after core assessment pipeline is stable
- `DEFER_OR_DROP`: low current value, placeholder, or can be replaced by simpler local logic

---

## 3. Domain Matrix (83 Domains)

| Domain | Tool Count | Decision | Rationale |
|--------|------------|----------|-----------|
| `access-control` | 4 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `adapters` | 0 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `addons` | 3 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `advanced` | 8 | `ADAPT_PHASE_2` | cross-cutting utilities; evaluate selectively after core domains |
| `aggregators` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `ai-ml-MIGRATED` | 2 | `DEFER_OR_DROP` | migrated/legacy AI domains, not required for MVP extraction |
| `applications` | 5 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `approvals` | 3 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `asset` | 8 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `atf` | 6 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `attachments` | 3 | `DEFER_OR_DROP` | low immediate assessment value or helper-only domain |
| `automation` | 20 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `business-rules` | 2 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `calculators` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `catalog` | 6 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `change` | 2 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `cmdb` | 13 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `connectors` | 5 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `converters` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `csm` | 3 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `dashboards` | 2 | `DEFER_OR_DROP` | low immediate assessment value or helper-only domain |
| `data-management` | 5 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `data-policies` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `decoders` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `deployment` | 8 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `development` | 7 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `devops` | 5 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `email` | 5 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `encoders` | 5 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `events` | 5 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `extensions` | 5 | `ADAPT_PHASE_2` | cross-cutting utilities; evaluate selectively after core domains |
| `filters` | 4 | `ADAPT_PHASE_2` | cross-cutting utilities; evaluate selectively after core domains |
| `formatters` | 3 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `forms` | 3 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `generators` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `handlers` | 4 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `helpers` | 6 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `hr` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `hr-csm` | 3 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `import-export` | 4 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `integration` | 24 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `journals` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `knowledge` | 6 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `lists` | 4 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `local-sync` | 6 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `machine-learning-MIGRATED` | 9 | `DEFER_OR_DROP` | migrated/legacy AI domains, not required for MVP extraction |
| `mappers` | 2 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `menus` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `meta` | 0 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `metrics` | 2 | `ADAPT_PHASE_2` | cross-cutting utilities; evaluate selectively after core domains |
| `mobile` | 7 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `notifications` | 7 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `operations` | 17 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `parsers` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `performance-analytics` | 3 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `platform` | 7 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `plugins` | 3 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `predictive-intelligence-MIGRATED` | 5 | `DEFER_OR_DROP` | migrated/legacy AI domains, not required for MVP extraction |
| `processors` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `procurement` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `project` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `queues` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `reporting` | 5 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `scheduled-jobs` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `schedules` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `script-includes` | 0 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `security` | 18 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `service-portal` | 2 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `sla` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `system-properties` | 4 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `templates` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `transformers` | 1 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `ui-actions` | 0 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `ui-builder` | 12 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `ui-policies` | 1 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `update-sets` | 3 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `user-admin` | 2 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `utilities` | 7 | `ADAPT_PHASE_2` | cross-cutting utilities; evaluate selectively after core domains |
| `validators` | 5 | `DEFER_OR_DROP` | meta/helper layer can be simplified or rebuilt later as needed |
| `variables` | 2 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `virtual-agent` | 7 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |
| `workflow` | 5 | `EXTRACT_NOW` | core read/query or high-value assessment capability |
| `workspace` | 10 | `ADAPT_PHASE_2` | useful domain but not critical for initial TA/CSDM assessment loop |

---

## 4. Summary Totals

- Total domains mapped: **83**
- `EXTRACT_NOW`: **30 domains / 196 tools**
- `ADAPT_PHASE_2`: **32 domains / 132 tools**
- `DEFER_OR_DROP`: **21 domains / 54 tools**

> Note: counts reflect unified tool files present in this repo snapshot; some domains are placeholders (0 files) and some are dynamic-only in registry behavior.

---

## 5. Immediate Integration Cut

### Wave 1 (extract now)
1. `operations`, `cmdb`, `update-sets`, `development`, `business-rules`, `integration`
2. `security`, `automation`, `reporting`, `performance-analytics`
3. `applications`, `system-properties`, `change`, `catalog`, `workflow`

### Wave 2 (after stable MVP)
1. `workspace`, `devops`, `deployment`, `local-sync`, `asset`
2. `hr`, `csm`, `virtual-agent`, `mobile`

### Defer unless requirement appears
1. helper/meta domains (`adapters`, `mappers`, `transformers`, etc.)
2. migrated legacy AI domains (`*-MIGRATED`)

---

## 6. Takeover Notes (for reconciliation)

- This matrix completes the previously pending keep/adapt/discard mapping task from the interrupted deep dive.
- It is designed to feed directly into `10_integration_plan.md` and Phase 9B execution tickets.
