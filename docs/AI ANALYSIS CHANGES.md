# AI Analysis and Feature Generation Architecture

This document outlines the current architecture of the AI-driven analysis and feature generation capabilities. It consolidates a series of changes that have shifted ownership of the feature lifecycle from deterministic engines to AI-driven processes.

## 1. Core Principles & Workflow

The primary goal of the new architecture is for AI to own the creation, refinement, coverage, and naming of features based on evidence from deterministic engines, which now serve as hints rather than the source of truth.

The updated assessment workflow is as follows:

1.  **`ai_analysis` (Artifact-Level Review):**
    *   Each artifact is reviewed individually.
    *   The analysis is anchored to the assessment's defined scope (e.g., target application, tables).
    *   The AI determines if an artifact is `in_scope`, `adjacent`, or `out_of_scope`, writes a concrete observation, and identifies relationships to other customized artifacts.
    *   This stage acts as a gate: if it fails to persist scope triage, downstream stages like `observations` are blocked.

2.  **`grouping` (AI Feature Authoring):**
    *   **Structure Pass:** The AI builds initial functional groups from artifacts that clearly work together. Features are given provisional names (e.g., "Working Feature 01").
    *   **Coverage Pass:** Remaining in-scope artifacts are assigned to an existing functional feature or to a "bucket feature".

3.  **`ai_refinement` (Iterative Cleanup & Naming):**
    *   The AI merges or splits features to improve coherence.
    *   It confirms that all in-scope artifacts are assigned to a feature.
    *   **Final Naming Pass:** Only at the end of this stage does the AI assign final, descriptive names to the features based on the complete set of grouped artifacts.

4.  **`recommendations` & `report`:**
    *   These stages are blocked until the feature grouping and refinement are complete, with full artifact coverage and no provisional names remaining. A strict manual override is required to proceed with incomplete data.

## 2. Key Architectural Concepts

### 2.1. Feature Data Model

The `Feature` data model has been expanded to support the AI-driven workflow. Key attributes include:

*   **`feature_kind`**: `functional` (a solution feature) or `bucket` (a collection of related leftovers).
*   **`composition_type`**: `direct` (only target-app artifacts), `adjacent` (only artifacts outside the target app), or `mixed`.
*   **`name_status`**: `provisional`, `final`, or `human_locked`.
*   **`bucket_key`**: A key for bucket features (e.g., `form_fields`, `acl`).

### 2.2. Bucket Features

-   Bucket features are first-class citizens used to group in-scope artifacts that do not belong to a clear functional solution.
-   Default buckets include `Form & Fields`, `ACL`, `Notifications`, `Scheduled Jobs`, `Integration Artifacts`, and `Data Policies & Validations`.
-   They are displayed in the main feature list alongside functional features.

### 2.3. Adjacent Artifacts

-   Adjacent artifacts are first-class members of features. Features can be composed entirely of adjacent artifacts or a mix of direct and adjacent ones.
-   The definition of `adjacent` has been refined: it applies to table-bound artifacts outside the direct target tables. Tableless artifacts (e.g., script includes) are judged by their behavior as either `in_scope` or `out_of_scope`.
-   Adjacency is tracked at the artifact level and rolled up to the feature level.

### 2.4. Pass Orchestration

-   The feature generation process is managed by a configurable pass plan (e.g., `grouping/structure`, `grouping/coverage`, `ai_refinement/final_name`).
-   This allows for rerunning specific passes, potentially with different LLM providers or models, without resetting the entire process.

### 2.5. Dependency Analysis Engines

The dependency analysis engines (`structural_mapper`, `code_reference_parser`) have been corrected to properly query the database. They now join through the `scan_result` -> `scan` -> `assessment` -> `artifact` tables to correctly map relationships between customized artifacts. Previously, they were querying a non-existent column, resulting in no output.

## 3. Current Status & Known Issues

While the core logic for the AI-owned feature lifecycle is implemented, several blocking issues prevent a clean end-to-end run in the live environment.

*   **HIGH: DB Schema Mismatch:** The `dependency_mapper` engine now reads the new `Feature` model columns (`feature_kind`, `composition_type`, etc.). The live database schema for the `feature` table has not been migrated, causing runs to fail with a `no such column` error. **This is the primary blocker.**
*   **MEDIUM: Incorrect Engine Mappings:** The `structural_mapper` still contains incorrect dictionary mappings, preventing it from identifying all dictionary-based structural relationships.
    *   It points `sys_dictionary` to `asmt_dictionary` instead of `asmt_dictionary_entry`.
    *   It expects a `collection_name` column in `asmt_dictionary_override` that does not exist.
*   **MEDIUM: Optimistic Engine Reporting:** The `run_engines.py` script can report a successful run even if the underlying engines produce zero output or encounter non-fatal errors. This can lead to a false impression of success, as seen in previous runs where `engines` completed but no dependency data was generated.
*   **UNRELIABLE TESTING ENVIRONMENT:** The local Python/venv setup is unstable, preventing consistent and trustworthy `pytest` execution. Full automated verification of changes remains outstanding.

## 4. Verification and Next Steps

The patched dependency engines have been shown to produce results on a disposable copy of the database when the schema issue is manually bypassed.

The recommended path forward is:

1.  **Migrate the Database:** Apply the necessary schema changes to the `feature` table to add the `feature_kind`, `composition_type`, `name_status`, and `bucket_key` columns.
2.  **Fix `structural_mapper`:** Correct the dictionary mappings in `structural_mapper.py`.
3.  **Harden Engine Runner:** Improve `run_engines.py` to fail more explicitly if its child engines do not produce the expected output.
4.  **Full Re-run:** Execute a full `grouping -> ai_refinement -> recommendations -> report` pipeline run on an assessment (e.g., Assessment 22) with connected AI to validate the end-to-end workflow.
