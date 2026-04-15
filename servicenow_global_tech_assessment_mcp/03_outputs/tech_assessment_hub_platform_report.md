# Tech Assessment Hub — Platform Report

**Project:** ServiceNow Global Technical Assessment MCP Platform
**Date:** 2026-04-04
**Status:** Production Development — Active

---

## 1. Solution Vision & Scope

### What We Built

A production-ready ServiceNow technical assessment platform with three architectural planes:

**Control Plane (Web App)** — FastAPI + Jinja UI running on local SQLite. Full management surface: instance connections, data collection, artifact browsing, configuration, analytics, MCP setup wizard. The web app owns all data and orchestrates the pipeline but does not perform AI reasoning.

**Reasoning Plane (MCP + LLM)** — Where AI does the judgment work. Connected via MCP protocol to Claude (Anthropic) or Codex (OpenAI) CLI sessions. AI reads from local DB (token-efficient), uses Snow-flow tools for supplemental ServiceNow data, and writes findings back to app tables. Handles: feature discovery, technical debt analysis, disposition recommendations, CSDM service structure analysis.

**Execution Plane (Snow-flow Sidecar)** — TypeScript MCP server providing 382+ ServiceNow tools across 83 domains. Dual purpose: supports AI reasoning with live SN data access, and exposes customer-facing bonus tools. Runs as a managed sidecar process controlled from the web app.

### Core Principles
- Local DB is the cost optimization layer — AI reads local, not SN
- Deterministic engines handle counts/patterns; LLMs handle judgment only
- Shared data foundation (dynamic SnTableRegistry) across TA and CSDM modules
- Snow-flow tools are reused, not rebuilt
- MCP setup is wizard-driven, not terminal commands

### What's In Scope
- Global-scope technical assessment workflows
- Hybrid MCP runtime with tool reliability
- Data quality, classification accuracy, workflow UX
- CSDM data foundations integration
- Multi-pass AI refinement with observation evolution

### What's Out of Scope (Current Cycle)
- Multi-tenant SaaS production rollout
- Full scoped-app assessment coverage
- Security penetration testing

---

## 2. MCP Architecture & Data Contracts

### Architecture

```
ServiceNow Instance(s)
    |
    +--- [Data Pull] ---> Local SQLite DB
    |                         |
    |                         +---> Web App (browse, manage, visualize)
    |                         |
    |                         +---> MCP/AI Reasoning Plane
    |                                |
    |                                +-- Reads local DB (primary, token-efficient)
    |                                +-- Calls Snow-flow tools (supplemental SN data)
    |                                +-- Runs reasoning (group, analyze, recommend)
    |                                +-- Writes findings BACK to local DB
    |
    +--- [Snow-flow tools] ---> Direct customer use (bonus features)
```

### MCP Protocol
- **Transport:** Streamable HTTP (POST /mcp endpoint)
- **Protocol:** JSON-RPC 2.0, MCP spec 2024-11-05
- **Notifications:** Handled with 202 Accepted (no body)
- **Tool Registry:** 50+ tools across 3 levels (connection/inventory, assessment/results, pipeline/write-back)
- **Prompt Registry:** 7 registered prompts (artifact_analyzer, relationship_tracer, technical_architect, observation reviewers, feature_reasoning_orchestrator, report_writer, tech_assessment_expert)
- **Resource Registry:** Assessment data resources for ChatGPT/deep research compatibility

### Tool Inventory by Level
| Level | Purpose | Tool Count |
|-------|---------|-----------|
| Level 0 | Connection, inventory, DB reader, search/fetch | ~15 |
| Level 1 | Instance summary, assessment results, data pull, customizations | ~15 |
| Level 2 | Pipeline tools (grouping, observations, engines, features) | ~15 |
| Write-back | Update result, features, recommendations | ~8 |

### Snow-flow Integration Status
- **83 tool domains** analyzed and mapped
- **30 domains (196 tools):** EXTRACT_NOW — core assessment capabilities
- **32 domains (132 tools):** ADAPT_PHASE_2 — useful but not critical for MVP
- **21 domains (54 tools):** DEFER_OR_DROP — low value or replaceable
- **Wave 1 focus:** operations, CMDB, update-sets, development, business-rules, integration, security, automation

### Integration Waves
| Wave | Focus | Status |
|------|-------|--------|
| Wave 0 | Stabilize analysis assets | Complete |
| Wave 1 | Runtime bridge + management control | Complete (sidecar management, config push, SSE events) |
| Wave 2 | Assessment-first tool cut | In Progress |
| Wave 3 | Context + token optimization | Planned |
| Wave 4 | Deep feature expansion (CSDM, adapt domains) | Planned |
| Wave 5 | Portability + hardening (Python ports, enterprise proxy) | Planned |

---

## 3. ServiceNow Data Model Relationships

### Classification Logic
Two methods for detecting customizations (from Assessment Guide v3):

**Update Version History Method:** Examines `sys_update_version` for ownership. If a version exists with `source != "system"`, the record has been customized.

**Baseline Comparison Method:** Compares against ServiceNow baseline via `SncAppFiles.hasCustomerUpdate()`. If a customer update exists, the OOTB record has been modified.

### Origin Types
| Origin | Meaning |
|--------|---------|
| `modified_ootb` | OOTB record that's been customized |
| `ootb_untouched` | Pristine OOTB record |
| `net_new_customer` | Customer-created from scratch |
| `unknown_no_history` | No tracking data available |

### Key Data Relationships
- `sys_metadata` → parent/child structural links between artifacts
- `sys_update_xml` → artifacts grouped by update set delivery
- `sys_update_version` → version history chain showing lifecycle
- `sys_dictionary` → field definitions, reference fields, table structure
- `sys_dictionary_override` → inherited field customizations
- `sys_scope` → application scope boundaries

### Dynamic Table Mirroring
All ServiceNow tables mirrored locally via `SnTableRegistry` + `SnFieldMapping` — fully dynamic DDL, no hardcoded SQLModel classes. Tables prefixed `sn_`, partitioned by `_instance_id`. Schema drift between instances handled automatically.

---

## 4. Instance Data Extraction Plan

### Assessment Workflow
1. **Instance Add/Test** — triggers proactive version history pull in background
2. **Start Assessment** — single button kicks off full pipeline
3. **Preflight Data Sync** — concurrent pulls (VH, customer update XML) + sequential pulls (metadata, app file types, update sets)
4. **Scan Execution** — metadata index scans by artifact class and scope keyword
5. **Classification** — origin type classification using VH + baseline comparison

### Extraction Strategy
- **Full pull:** First-time instance connection — all records
- **Delta pull:** Subsequent runs — keyset + watermark discipline from last pull timestamp
- **Deduplication:** `UniqueConstraint("instance_id", "sn_sys_id")` on all pull tables
- **Error handling:** Concurrent pull failures retry once immediately, then once more after sequential pulls complete
- **VH does NOT block preflight** — continues in background, classification waits

### Artifact Detail Records
28 artifact detail tables (`asmt_business_rule`, `asmt_script_include`, `asmt_client_script`, etc.) store the actual ServiceNow configuration records with full field settings, code, conditions. Joined to scan results by `sys_id` for AI analysis.

---

## 5. Feature Grouping Heuristics & Clustering Rules

### The Grouping Problem
Given thousands of customized records across dozens of tables, identify which records belong together as a "feature" or "solution" that delivers a specific business capability. Example: a custom approval workflow might span 2 business rules + 1 script include + 3 client scripts + 1 workflow + 5 notifications + 2 UI policies — these should be grouped as one feature.

### Signal Taxonomy (8 Types)

| Signal | Weight | Strength | Description |
|--------|--------|----------|-------------|
| Dependency Cluster | 3.5 | Strongest | Transitive dependency chains between customized artifacts |
| AI Relationship | 3.5 | Strongest | AI-discovered functional relationships |
| Code Reference | 3.0 | Strong | Script calls/references other artifacts |
| Update Set Overlap | 3.0 | Strong | Shared records across update sets |
| Structural Relationship | 2.5 | Strong | Parent/child metadata links |
| Update Set Artifact Link | 2.5 | Strong | Co-delivered in same update set |
| Naming Cluster | 2.0 | Medium | Shared naming patterns/prefixes |
| Temporal Cluster | 1.8 | Medium | Changed together in time by same developer |
| Table Colocation | 1.2 | Weak | Multiple customizations on same table |

### Clustering Algorithm (4 Phases)
1. **Initial Clusters** — High-confidence: update set, scoped app, package grouping
2. **Merge by Strong Signals** — Code references, naming patterns, update set name similarity
3. **Split by Weak Signals** — Table boundaries, time gaps, author diversity
4. **Orphan Assignment** — Assign remaining to nearest cluster or "Unclustered" bucket

### Confidence Scoring
- **High (8+):** Strong cluster, likely a real feature
- **Medium (4-7):** Probable, needs validation
- **Low (1-3):** Weak, may be coincidental

### Feature Types
- **Functional features** — Solution-based groupings (feature_kind="functional")
- **Bucket features** — Categorical catch-alls for leftovers (feature_kind="bucket": Form & Fields, ACL, Notifications, Scheduled Jobs, Integration Artifacts, Data Policies)
- **Adjacent features** — Can be direct, adjacent, or mixed membership
- **Feature naming** — Provisional during grouping, finalized after refinement (name_status="provisional" → "final")

---

## 6. Assessment Rubric: OOTB Gap & Recommendations

### Disposition Framework
| Disposition | Meaning | Action |
|-------------|---------|--------|
| **Keep** | Valuable, well-built, serves real need | Migrate to scoped app |
| **Refactor** | Good intent, bad implementation | Fix identified issues |
| **Replace with OOTB** | Platform has this built-in now | Remove custom, enable OOTB |
| **Evaluate for Retirement** | May be obsolete, unused, or broken | Usage analysis needed |

### Common Finding Patterns
- **OOTB Alternative Exists** — Custom fields replicating OOTB functionality, client scripts doing what UI policies handle declaratively, custom notifications when OOTB engine covers it
- **Platform Maturity Gap** — Feature built when platform was immature, SN has since released OOTB capability
- **Bad Implementation, Good Intent** — Real business need but poor implementation (deprecated APIs, fragile logic, over-engineered)
- **Dead or Broken Config** — Scripts with errors, references to nonexistent tables/fields, abandoned features
- **Competing/Conflicting Config** — Multiple solutions for same purpose, custom + OOTB both active

### Best Practice Checks
40+ active best practice checks in the `BestPractice` table, evaluated per-artifact during the technical architect stage. Each check has:
- Severity (critical/high/medium/low)
- Detection hint (what to look for in code/config)
- Recommendation (what to do about it)
- Applies-to filter (which artifact types)

Examples: hardcoded sys_ids, synchronous HTTP in business rules, GlideRecord in client scripts, business rules without conditions, bypassing ACLs.

---

## 7. Revert/Deactivate Automation Safety Plan

### Risk Tiers
| Tier | Risk | Examples | Guardrail |
|------|------|----------|-----------|
| Read-only | None | Browsing, analysis, reports | No restrictions |
| Deactivate | Low | Set active=false on BR/CS/UI Policy | Reversible, logged |
| Modify | Medium | Update script, change conditions | Requires backup/snapshot |
| Delete | High | Remove artifacts from instance | Requires approval + rollback plan |

### Safety Controls
- All write operations require explicit human confirmation
- Disposition field is human-only — AI suggests, never sets
- Update set packaging for any changes pushed back to SN
- Dry-run mode for cleanup operations (preview before execute)
- Audit trail for all modifications

### Rollback Strategy
- Assessment data is local (SQLite) — SN instance is never modified by default
- Any SN-side changes go through update sets with rollback capability
- Pipeline supports re-run from any AI stage without losing human edits
- Pass history preserved across AI loop reruns

---

## 8. Roadmap: Phases & Backlog

### Completed Phases

| Phase | Deliverable | Tests | Status |
|-------|-------------|-------|--------|
| P1-P2 | Reasoning data model + 6 preprocessing engines | ~150 | Complete |
| P3-P4 | Feature grouping, hierarchy UI, recommendations | ~305 | Complete |
| P5 | 7-stage pipeline orchestration, observations, review gate | ~330 | Complete |
| P6 | MCP prompts library + best practice knowledge base | ~478 | Complete |
| P7 | 10-stage pipeline, AI handlers, re-run, contextual enrichment | ~496 | Complete |
| Post-P7 | Runtime telemetry, checkpoints, AI budget properties | ~532 | Complete |
| P9/10 | Prompt integration, exports (xlsx/docx), process recommendations, summary dashboard | ~532 | Complete |
| P11A | SN API centralization sprint (3 tasks, 3 devs, 3 reviewers) | ~713 | Complete |
| P11B | AI-owned feature lifecycle, bucket features, coverage gates | ~713+ | Complete |

### Current Pipeline (11 Stages)
```
scans -> enrichment -> engines -> ai_analysis -> observations -> review -> grouping -> ai_refinement -> recommendations -> report -> complete
```

### Active Development (2026-04-04)
- Dependency mapper engine (7th engine) — complete, producing chains + clusters
- Reference trace enrichment stage — designed, implementation planned
- AI analysis prompt refinements — multi-pass awareness, artifact detail integration
- MCP streamable HTTP transport fix — complete
- AI loop rerun support — complete
- Swarm execution (opt-in) — complete
- LLM settings catalog refresh (OpenAI Codex models) — complete

### Upcoming
| Priority | Item | Owner |
|----------|------|-------|
| 1 | Reference trace enrichment (discover out-of-scope dependencies) | Planned |
| 2 | Artifact-type-aware code parsing (type-specific field maps) | Planned |
| 3 | Table-centric discovery enrichment (full artifact set per table) | Planned |
| 4 | Reference field tracing (sys_dictionary reference dependencies) | Planned |
| 5 | OOTB replacement detection (pattern matching) | Planned |
| 6 | Inherited dictionary-override ancestry bridging | Backlog |
| 7 | API-access fallback table import utility | Backlog |

### Technical Debt
- `server.py` decomposition (monolithic, priority maintainability investment)
- Bail-out boilerplate refactor (~25 lines x 11 handlers)
- `csdm_ingestion.py` consolidation to centralized SN client
- Frontend standardization (bespoke tables vs shared DataTable components)
- Property contract hygiene sweep

---

## 9. Open Questions & Validation Plan

### Open Questions
1. How to handle circular references in dependency chains? (Currently detected and flagged, not resolved)
2. What's the right cluster size? (Too small = fragmented, too large = meaningless — currently min_cluster_size=2)
3. How to name clusters/features automatically? (Currently: most common table + count, refined by AI in later passes)
4. How to validate grouping quality? (Currently: AI multi-pass refinement + human review gate)
5. Should deleted records be included in analysis? (Currently: no, only current records)
6. Inherited dictionary-override bridging — Incident overrides for Task fields not yet connected
7. Optimal batch size for connected AI analysis (currently configurable, testing with real data)
8. Swarm execution convergence validation (provider-native subagents, parent coordinator pattern)

### Validation Plan
| Item | Owner | Status |
|------|-------|--------|
| Full pipeline live QA (10 stages, real SN instance) | Human | Pending |
| AI analysis scope triage (connected CLI + MCP tools) | Human | In Progress (Assessment 24) |
| AI loop rerun (re-run from any AI stage, pass_history preserved) | Human | Pending |
| Swarm execution (Codex/Claude subagents) | Human | Pending |
| Relationship graph + dependency map visualization | Human | Pending |
| Assessment out-of-scope related list | Human | Pending |
| Export files (xlsx/docx) quality check | Human | Pending |
| Resume/recovery (interrupt mid-stage, checkpoint rehydrate) | Human | Pending |
| Runtime telemetry + cost tracking | Human | Pending |

---

## 10. Platform Metrics (Current State)

### Test Coverage
| Suite | Tests |
|-------|-------|
| Full regression | 845+ |
| Dependency engine | 29 |
| Feature grouping | 12 |
| MCP protocol | 22 |
| Pipeline stages | ~76 |

### Engine Outputs (Assessment 24 — Incident Management)
| Engine | Output Count |
|--------|-------------|
| Code References | 5,531 (960 resolved) |
| Update Set Artifact Links | 5,748 |
| Update Set Overlaps | 21,594 |
| Temporal Clusters | 559 |
| Naming Clusters | 455 |
| Structural Relationships | 372 |
| Dependency Chains | 314 |
| Dependency Clusters | 73 |
| Table Colocation Summaries | 84 |

### AI Prompt Library
| Prompt | Stage | Purpose |
|--------|-------|---------|
| artifact_analyzer | ai_analysis | Scope triage (in/out/adjacent) |
| observation_artifact_reviewer | observations | Functional summaries with artifact detail |
| observation_landscape_reviewer | observations | Assessment-wide landscape summary |
| technical_architect (Mode A) | ai_refinement | Per-artifact best practice review |
| technical_architect (Mode B) | ai_refinement | Assessment-wide technical debt roll-up |
| relationship_tracer | ai_refinement | Cross-artifact dependency graph tracing |
| feature_reasoning_orchestrator | recommendations | AI-owned feature lifecycle (group/refine/name) |
| report_writer | report | Final deliverable generation |
| tech_assessment_expert | ai_analysis | Full methodology teaching |
| tech_assessment_reviewer | review | Review checklist for validation |

---

*Report compiled 2026-04-04 from project working notes, admin files, and codebase analysis.*
*Source files: 02_working/01_notes/*, 00_admin/context.md, 00_admin/insights.md, 00_admin/todos.md, 03_outputs/00_delivery_index.md*
