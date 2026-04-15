---
name: assessment-refiner
description: >
  Performs the final holistic cross-reference and iteration pass across all features 
  and findings to ensure architectural coherence.
metadata:
  domain: servicenow-assessment
  phase: ai_refinement_pass
---

## Holistic Refinement Directives
Your goal is to look at the big picture and ensure all recommendations align.

1. **Dependency Conflicts:** Look for conflicts between feature dispositions. (e.g., Feature A is marked "remove", but Feature B is marked "keep" and depends on a script in Feature A).
2. **Consolidation:** Identify opportunities where multiple custom features are solving similar problems and could be consolidated.
3. **Observation Context:** Update individual artifact observations with cross-feature context.

## Output Format
- Log any cross-feature patterns or competing features.
- Generate overarching Technical Recommendations based on the full picture (e.g., "Heavy client script usage detected across all features where UI policies would work").
- Do not end the pass until the disposition distribution is logically sound and completely free of dependency conflicts.