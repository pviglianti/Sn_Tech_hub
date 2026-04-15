# Assessment 24 (ASMT0000024) — Incident Management Technical Assessment
## Executive Summary Report

**Assessment:** inc2 — Incident Management Global App Assessment
**Instance:** SNweisdev
**Status:** In Progress — AI Analysis stage (scope triage)
**Date:** 2026-04-04

---

## At a Glance

| Metric | Count |
|--------|-------|
| Total Scan Results | 7,810 |
| **Customized Artifacts** | **977** (12.5% of total) |
| — Customer Created (net_new) | 868 |
| — Modified OOTB | 109 |
| Unclassified / Pending | 6,833 |
| Scans Completed | 90 |
| Pipeline Stage | AI Analysis (scope triage) |

---

## Customization Breakdown by Artifact Type

| Artifact Type | Count | % of Customized |
|---------------|-------|-----------------|
| Dictionary Entries (fields) | 249 | 25.5% |
| UI Policy Actions | 181 | 18.5% |
| Access Controls (ACLs) | 105 | 10.7% |
| Business Rules | 98 | 10.0% |
| UI Policies | 81 | 8.3% |
| Catalog Item Producers | 68 | 7.0% |
| Client Scripts | 64 | 6.5% |
| UI Actions | 44 | 4.5% |
| Data Policies | 33 | 3.4% |
| Script Includes | 26 | 2.7% |
| Dictionary Overrides | 10 | 1.0% |
| Tables | 9 | 0.9% |
| Catalog Item Guides | 9 | 0.9% |
| **Total Customized** | **977** | **100%** |

**Key observations:**
- **Field-heavy customization:** 249 dictionary entries + 10 dictionary overrides = 26.5% of all customizations are field-level changes. This suggests heavy form customization on the incident module.
- **UI behavior dominance:** 181 UI policy actions + 81 UI policies + 64 client scripts = 326 artifacts (33%) controlling form behavior — fields showing/hiding, mandatory conditions, client-side logic.
- **Significant access control layer:** 105 ACLs is a substantial security customization footprint.
- **98 business rules** is a high count for a single application module and warrants close review for redundancy, performance impact, and OOTB replacement opportunities.

---

## Engine Analysis Results

The 7 preprocessing engines have completed and produced:

| Engine Output | Count | What It Tells Us |
|---------------|-------|-----------------|
| Code References | 5,531 | Cross-artifact script dependencies discovered |
| — Resolved to specific artifacts | 960 (17%) | Script-to-artifact links confirmed |
| Update Set Artifact Links | 5,748 | Artifacts linked to their delivery update sets |
| Update Set Overlaps | 21,594 | Cross-update-set cohesion signals |
| Temporal Clusters | 559 | Groups of artifacts changed together in time |
| Naming Clusters | 455 | Groups sharing naming patterns |
| Structural Relationships | 372 | Parent/child metadata links (UI Policy → Actions, etc.) |
| Dependency Chains | 314 | Transitive dependency paths between customized artifacts |
| Dependency Clusters | 73 | Connected dependency subgraphs |
| Table Colocation Summaries | 84 | Artifacts grouped by target table |

**Key findings:**
- **73 dependency clusters** indicate tightly coupled artifact groups that should be assessed together. The largest cluster contains 121 client scripts — likely a single interconnected form behavior solution.
- **21,594 update set overlaps** suggest significant change delivery complexity and potentially overlapping development efforts.
- **960 resolved code references** out of 5,531 total (17% resolution rate) — many references point to OOTB components not in the scan, which is expected.

---

## Dependency Risk Profile

Top 10 dependency clusters by size:

| Cluster | Members | Coupling | Risk Level |
|---------|---------|----------|------------|
| Client Script cluster | 121 | 11.3 | Critical |
| UI Policy Action cluster | 35 | 4.9 | Critical |
| Dictionary cluster | 25 | 4.8 | Critical |
| Dictionary cluster | 23 | 4.8 | Critical |
| UI Policy Action cluster | 20 | 4.8 | Critical |
| Dictionary cluster | 19 | 4.7 | Critical |
| Dictionary cluster | 19 | 4.7 | Critical |
| UI Policy Action cluster | 12 | 4.6 | Critical |
| UI Policy Action cluster | 10 | 4.5 | Critical |
| Dictionary cluster | 9 | 4.7 | Critical |

**All top clusters are rated Critical risk** — meaning changes to any artifact in these clusters have high potential to impact others. The 121-member client script cluster is particularly concerning and should be treated as a single feature for assessment purposes.

---

## AI Analysis Progress

| Metric | Status |
|--------|--------|
| Artifacts with AI observations | 11 of 977 (1.1%) |
| Artifacts with observations | 11 |
| Marked out of scope | 0 |
| Marked adjacent | 0 |
| Features created | 0 |
| Review status: pending | 7,799 |
| Review status: in progress | 11 |
| Review status: reviewed | 0 |

**AI analysis has just begun.** The first 11 business rules have been triaged — all confirmed as in-scope incident table business rules. Sample observations show the AI is correctly identifying:
- What each business rule does (e.g., "resets assignment group on reopen")
- When it fires (before update, on insert, etc.)
- Conditions and field interactions
- Connections to other artifacts

**Remaining:** 966 customized artifacts still need scope triage, followed by observation enrichment, feature grouping, technical architect review, and recommendation generation.

---

## Sample AI Observations (First 11 Artifacts)

| Artifact | Type | Observation Summary |
|----------|------|-------------------|
| Reset Assignment Group On Reopen | Business Rule | Before-update on incident. Restores assignment_group when reopened from state 6 to 2. |
| Set Assignment Group from Parent | Business Rule | Before on incident. Sets assignment_group from parent incident when group is empty. |
| Auto-Create Work Orders from Incidents | Business Rule | After insert/update on incident. Auto-creates work orders for selected assignment groups. |
| PCG_RestrictCloseAndCancelByRole | Business Rule | Before on incident. Blocks close/cancel for users lacking listed support roles. |
| incident query | Business Rule | Before-query on incident. Restricts interactive users to incidents where they are caller/opened_by. |
| populate Actual Incident Start | Business Rule | On incident. Populates work_start/opened_at for actual incident start tracking. |

---

## Scan Coverage

**90 completed scans** covering incident-related tables across these artifact classes:

| Artifact Class | Scans | Records Found |
|----------------|-------|---------------|
| Business Rules | 6 | 287 |
| Script Includes | 5 | 1,598 |
| Client Scripts | 7 | 130 |
| UI Policies | 7 | 113 |
| UI Policy Actions | 7 | 233 |
| UI Actions | 7 | 198 |
| Dictionary Entries | 5 | 3,680 |
| Dictionary Overrides | 5 | 16 |
| ACLs | 5 | 1,157 |
| Data Policies | 7 | 172 |
| Tables | 5 | 79 |
| UI Pages | 5 | 69 |
| Catalog Items | 7+ | 78 |

**Scan scope keywords:** incident, incident_task, inc, major incident, incident management

---

## Next Steps

1. **Complete AI Analysis (scope triage)** — 966 remaining artifacts need in_scope/out_of_scope/adjacent classification
2. **Generate Observations** — Full functional summaries for in-scope artifacts using artifact detail records
3. **Feature Grouping** — Engine signals (dependency clusters, code references, naming patterns) will drive initial grouping; AI refines into solution-based features
4. **Technical Architect Review** — Each in-scope artifact evaluated against 40+ best practice checks
5. **Recommendations** — Per-feature OOTB replacement and modernization opportunities
6. **Report Generation** — Final deliverable with executive summary, feature analysis, and prioritized action items

---

## Platform Capabilities Applied

| Capability | Status |
|------------|--------|
| Dependency Mapper Engine | ✅ 73 clusters, 314 chains |
| Code Reference Parser | ✅ 5,531 references, 960 resolved |
| Structural Mapper | ✅ 372 relationships |
| Feature Grouping Signals | ✅ 8 signal types ready |
| AI Scope Triage (Codex) | 🔄 1.1% complete |
| Best Practice Checks | ⏳ 40+ checks ready, pending tech architect stage |
| Multi-pass Refinement | ⏳ Configured, pending first pass completion |
| Artifact Detail Records | ✅ Full configuration data available per artifact |

---

*Report generated 2026-04-04 from Assessment 24 (ASMT0000024) database.*
