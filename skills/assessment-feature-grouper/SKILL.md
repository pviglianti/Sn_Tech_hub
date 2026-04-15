---
name: assessment-feature-grouper
description: >
  Logic for evaluating algorithmic clusters, merging, splitting, and resolving
  orphan artifacts into business features during the grouping phase.
metadata:
  domain: servicenow-assessment
  phase: grouping
---

# Feature Grouper — Cluster Evaluation

You are grouping customized ServiceNow artifacts into logical business features
during the grouping phase of a technical assessment.

## What is a Feature?

A feature is a cohesive set of customizations that together deliver a single
business capability. Examples:
- "Incident Auto-Assignment" — a business rule, a script include, and a
  UI action that together handle automatic incident routing
- "Custom Approval Workflow" — workflow, business rules, notifications

## Grouping Rules

1. **Engine signals first:** The preprocessing engines have already created
   structural relationships, code references, update set links, temporal
   clusters, naming clusters, and table colocation data. Use `get_customizations`
   to see these signals.

2. **Evaluate clusters:** For each engine-generated cluster:
   - Do the artifacts share a business purpose? -> Group as one feature
   - Is the cluster too broad (unrelated artifacts lumped together)? -> Split
   - Are there multiple small clusters that serve the same purpose? -> Merge

3. **Resolve orphans:** Artifacts not in any cluster still need a home:
   - Check if they relate to an existing feature by code/table/naming patterns
   - If genuinely standalone, create a single-artifact feature or assign to
     a bucket feature (e.g., "Miscellaneous Incident Customizations")

4. **Name features clearly:** Feature names should describe the business
   capability, not the implementation. "Incident Auto-Assignment" not
   "BR + SI + UA on incident".

## Using MCP Tools

- `get_customizations` — see all artifacts with engine signals and current grouping
- `get_features` — see existing feature definitions
- `create_feature` — create a new feature
- `update_feature` — rename or update a feature
- `assign_result_to_feature` — assign an artifact to a feature

## Rules
- Every in-scope artifact must end up in a feature. No orphans at the end.
- Provisional features (auto-generated names) should be renamed to meaningful
  business capability names.
- Do not create features for out-of-scope artifacts.
