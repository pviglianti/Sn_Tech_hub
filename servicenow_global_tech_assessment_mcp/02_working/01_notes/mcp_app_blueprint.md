# mcp_app_blueprint.md

## Purpose
North-star blueprint for architecture decisions. Updated 2026-02-15 with corrected plane definitions.

## The Three Planes

### Control Plane: Web App (FastAPI + UI)
- **Full management surface**: instance CRUD, data pulls, browsing, configuration, analytics, visibility.
- **MCP setup wizard / installer**: Makes it easy for app owners to configure MCP without terminal expertise. After downloading the local package, setup happens via the web UI.
- **Data ownership**: Local SQLite DB is the single source of truth for all pulled SN data, analysis results, and AI findings.
- **NOT the reasoning surface**: The web app does not kick off assessments or scans that require AI judgment. It orchestrates data collection and presents results.

### Reasoning Plane: MCP + LLM Agents
The MCP layer is **where AI does the hard, judgment-based work** that justifies the product. This is the core value.

**Technical Assessment module — AI responsibilities:**
- **Feature discovery**: Group related configurations (business rules + UI policies + client scripts + workflows) into logical "features" that represent a customer's customization intent. An app file can support more than one feature (e.g., a shared script include).
- **Technical debt analysis**: Review scripts, business rules, and other app files. Identify debt patterns, deprecated APIs, over-customized OOTB processes, redundant logic.
- **Disposition recommendations**: For each feature/customization cluster, recommend:
  - **Keep** — valuable and well-built
  - **Refactor** — good intent, poor implementation
  - **Replace with OOTB** — ServiceNow has this built-in now, custom version is unnecessary
  - With supporting observations and evidence that help the customer decide.
- **Data/trend analysis**: Deterministic engines handle what they can (counts, patterns). AI handles reasoning, interpretation, and judgment on top of engine outputs.

**CSDM module — AI responsibilities:**
- Analyze CSDM data, evaluate completeness and relationships.
- Identify findings (gaps, misclassifications, orphaned records).
- Produce end-to-end service structure: Business Service → Technical Service → Application Service → Service Offerings → Service Instances (where applicable).
- Other domain-specific outputs guided by CSDM best practices.

**How AI works:**
- **Reads from local DB** for all analysis (saves tokens — data is already pulled and stored locally).
- **Uses Snow-flow tools** to reach back into ServiceNow for supplemental data when the AI needs more context (e.g., "this script references a table I haven't seen — let me check what's configured there").
- **Writes findings back** to the app's tables/records. AI analysis results are stored as structured data in the local DB, not just ephemeral chat output.
- **Web search** for supplemental context where needed (OOTB capability lookups, best practice references).

### Execution Plane: Snow-flow TS Sidecar
- Provides MCP tools that let AI interact with ServiceNow instances.
- **Dual purpose**:
  1. Supports the AI reasoning plane — tools for grabbing supplemental SN data during analysis.
  2. **Customer-facing tools** — some tools are useful to customers directly, independent of the assessment/CSDM purpose. They're there, so expose them.
- Tools and agent patterns from Snow-flow are reused ("stolen") for the assessment platform. Not reinvented.

## Data Flow

```
ServiceNow Instance(s)
    │
    ├─── [Data Pull] ──→ Local SQLite DB (mirror tables, metadata, app files)
    │                         │
    │                         ├──→ Web App (browse, manage, visualize)
    │                         │
    │                         └──→ MCP/AI Reasoning Plane
    │                                │
    │                                ├── Reads local DB (primary data source, token-efficient)
    │                                ├── Calls Snow-flow tools for supplemental SN data
    │                                ├── Calls web for supplemental context
    │                                ├── Runs reasoning (group, analyze, observe, recommend)
    │                                └── Writes findings BACK to local DB tables
    │                                         │
    │                                         └──→ Web App displays AI findings
    │
    └─── [Snow-flow tools] ──→ Direct customer use (bonus features)
```

## Token Efficiency Strategy
- **Engines for deterministic work**: Counting, pattern matching, trend detection, data aggregation — no AI needed.
- **AI for judgment only**: Logic, reasoning, understanding, data analysis, observations, recommendations, feature grouping.
- **Local DB prevents redundant SN queries**: All pulled data is local. AI reads local first, goes to SN only for supplemental data.
- **Guardrails and guidance**: AI operates within defined assessment frameworks (Assessment Guide logic, CSDM best practices) — not freeform.

## Core Principles
- Local DB is the performance and cost optimization layer — AI reads local, not SN.
- LLMs handle reasoning and judgment, not raw counting/discovery.
- Shared data foundation (SnTableRegistry + SnFieldMapping) across TA and CSDM use cases.
- Snow-flow tools are reused, not rebuilt.
- MCP setup should be as easy as possible — wizard-driven, not terminal commands.

## Priority Sequence (Current)
1. ~~Stabilize runtime and UI critical workflows.~~ DONE
2. ~~Harden tests and safety net.~~ DONE (baseline: 87 tests)
3. ~~Decompose monolithic server routes.~~ DONE (Codex #6 complete)
4. Complete MCP tools and classification quality fixes.
5. Build AI reasoning pipeline (feature grouping, tech debt analysis, disposition engine).
6. MCP installer wizard + packaging.
7. Expand pipeline foundations (DB evolution, multi-instance workflows).

## Integration Direction
- Keep API and delta behavior standardized (keyset + watermark discipline).
- Keep rehydration lightweight with section-gated admin files.
- Keep archived history external and active files concise.

## Archive Note
Full blueprint narrative archived on 2026-02-14:
`/Users/pviglianti/Library/Mobile Documents/com~apple~CloudDocs/Cloud Archive/2026-02-14_core_md_compression_round4/servicenow_global_tech_assessment_mcp/02_working/01_notes/mcp_app_blueprint.md`
