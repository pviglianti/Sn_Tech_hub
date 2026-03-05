"""Relationship Tracer MCP prompt.

Traces cross-artifact dependency graphs by querying the database for
relationships, building context, and returning structured prompt text
for the MCP client's AI model to reason over.

This is an MCP Prompt -- it does NOT call an LLM.  It builds context and
returns prompt text for the connected AI model to reason over.
"""

import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from ..registry import PromptSpec

# ── Static prompt text (system instructions) ───────────────────────

RELATIONSHIP_TRACER_TEXT = """\
# Relationship Tracer — Cross-Artifact Dependency Graph

You are tracing the dependency graph of a ServiceNow artifact from a
technical assessment.  Your goal is to map how this artifact relates to
others — through structural parent/child links, shared update sets,
table co-location, naming conventions, and feature groupings — and
produce a relationship map.

## Analysis Strategy

1. **Map the dependency graph** — follow each relationship type outward
   from the starting artifact through every hop provided in the context.
2. **Identify feature boundaries** — update set boundaries, table
   boundaries, and naming pattern breaks signal where one logical
   feature ends and another begins.
3. **Surface hidden dependencies** — Business Rules calling Script
   Includes, Client Scripts referencing UI Policies, Notifications
   triggered by Business Rules, etc.
4. **Output a relationship map** with the following sections:

```
Core Cluster:
  - [artifacts tightly coupled to the starting artifact]

Adjacent Artifacts:
  - [artifacts with weaker but meaningful connections]

Distant Connections:
  - [artifacts connected at 2+ hops or through indirect signals]

Recommended Grouping Narrative:
  [1-3 sentences describing why these artifacts form a logical unit
   and where the boundaries of the feature/solution lie]
```

## Rules

- Ground every statement in the injected context below — do NOT fabricate.
- If an artifact appears in multiple relationship types (e.g., same
  update set AND structural child), note the overlap.
- Flag potential hidden dependencies even when the injected data does
  not explicitly confirm them (e.g., a Script Include whose name
  matches a Business Rule's script body reference).
- Keep the analysis concise and actionable.
"""


# ── Context-building helpers ────────────────────────────────────────

def _extract_code_snippet(scan_result: Any, max_lines: int = 100) -> Optional[str]:
    """Extract code from raw_data_json if available."""
    if not scan_result.raw_data_json:
        return None
    try:
        raw = json.loads(scan_result.raw_data_json)
    except (json.JSONDecodeError, TypeError):
        return None
    for key in ("script", "code_body", "meta_code_body", "condition"):
        code = raw.get(key)
        if code and isinstance(code, str) and code.strip():
            lines = code.splitlines()
            if len(lines) > max_lines:
                return (
                    "\n".join(lines[:max_lines])
                    + f"\n... (truncated, {len(lines)} total lines)"
                )
            return code
    return None


def _build_structural_context(
    session: Session,
    scan_result_id: int,
    assessment_id: int,
    direction: str,
) -> str:
    """Query StructuralRelationship rows for this artifact.

    ``direction`` controls which edges to include:
      - ``"outward"`` — children (this artifact is the parent)
      - ``"inward"`` — parents (this artifact is the child)
      - ``"both"`` — both directions
    """
    from ...models import StructuralRelationship, ScanResult

    lines: List[str] = []

    # Inward: this artifact is a child → find parents
    if direction in ("inward", "both"):
        parent_rels = session.exec(
            select(StructuralRelationship).where(
                StructuralRelationship.child_scan_result_id == scan_result_id,
                StructuralRelationship.assessment_id == assessment_id,
            )
        ).all()
        for rel in parent_rels:
            parent = session.get(ScanResult, rel.parent_scan_result_id)
            p_name = parent.name if parent else f"(id={rel.parent_scan_result_id})"
            p_table = parent.table_name if parent else "unknown"
            p_origin = (
                parent.origin_type.value if parent and parent.origin_type else "unknown"
            )
            lines.append(
                f"  - Parent: {p_name} ({p_table}, origin={p_origin}) "
                f"[{rel.relationship_type} via {rel.parent_field}]"
            )

    # Outward: this artifact is a parent → find children
    if direction in ("outward", "both"):
        child_rels = session.exec(
            select(StructuralRelationship).where(
                StructuralRelationship.parent_scan_result_id == scan_result_id,
                StructuralRelationship.assessment_id == assessment_id,
            )
        ).all()
        for rel in child_rels:
            child = session.get(ScanResult, rel.child_scan_result_id)
            c_name = child.name if child else f"(id={rel.child_scan_result_id})"
            c_table = child.table_name if child else "unknown"
            c_origin = (
                child.origin_type.value if child and child.origin_type else "unknown"
            )
            lines.append(
                f"  - Child: {c_name} ({c_table}, origin={c_origin}) "
                f"[{rel.relationship_type} via {rel.parent_field}]"
            )

    return "\n".join(lines) if lines else "  (none found)"


def _build_update_set_siblings(
    session: Session,
    scan_result_id: int,
    assessment_id: int,
) -> str:
    """Find other ScanResults sharing the same update set(s), grouped by US name."""
    from ...models import UpdateSetArtifactLink, UpdateSet, ScanResult

    # Step 1: find update sets linked to this artifact
    links = session.exec(
        select(UpdateSetArtifactLink).where(
            UpdateSetArtifactLink.scan_result_id == scan_result_id,
            UpdateSetArtifactLink.assessment_id == assessment_id,
        )
    ).all()

    if not links:
        return "  (no update set links)"

    sections: List[str] = []
    for link in links:
        us = session.get(UpdateSet, link.update_set_id)
        us_name = us.name if us else f"(id={link.update_set_id})"

        # Step 2: find sibling artifacts in the same update set
        sibling_links = session.exec(
            select(UpdateSetArtifactLink).where(
                UpdateSetArtifactLink.update_set_id == link.update_set_id,
                UpdateSetArtifactLink.assessment_id == assessment_id,
                UpdateSetArtifactLink.scan_result_id != scan_result_id,
            )
        ).all()

        sibling_lines: List[str] = []
        seen_ids: set = set()
        for sib_link in sibling_links:
            if sib_link.scan_result_id in seen_ids:
                continue
            seen_ids.add(sib_link.scan_result_id)
            sib = session.get(ScanResult, sib_link.scan_result_id)
            if sib:
                sibling_lines.append(
                    f"    - {sib.name} ({sib.table_name})"
                )

        sections.append(f"  **{us_name}**:")
        if sibling_lines:
            sections.extend(sibling_lines)
        else:
            sections.append("    (no siblings)")

    return "\n".join(sections)


def _build_table_neighbors(
    session: Session,
    scan_result: Any,
    scan_id: int,
) -> str:
    """Find other ScanResults on the same table_name or meta_target_table."""
    from ...models import ScanResult, Scan

    # Get assessment_id via the scan
    scan = session.get(Scan, scan_id)
    if not scan:
        return "  (scan not found)"

    # Find other results from the same assessment sharing the target table
    target = scan_result.meta_target_table or scan_result.table_name

    # Get all scan IDs in this assessment
    assessment_scans = session.exec(
        select(Scan.id).where(Scan.assessment_id == scan.assessment_id)
    ).all()

    if not assessment_scans:
        return "  (none)"

    neighbors = session.exec(
        select(ScanResult).where(
            ScanResult.scan_id.in_(assessment_scans),  # type: ignore[attr-defined]
            ScanResult.id != scan_result.id,
            (
                (ScanResult.meta_target_table == target)
                | (ScanResult.table_name == target)
            ),
        )
    ).all()

    if not neighbors:
        return "  (none)"

    lines: List[str] = []
    for n in neighbors[:20]:  # Cap at 20 to keep prompt manageable
        lines.append(
            f"  - {n.name} ({n.table_name}"
            + (f", target={n.meta_target_table}" if n.meta_target_table else "")
            + ")"
        )
    if len(neighbors) > 20:
        lines.append(f"  ... and {len(neighbors) - 20} more")
    return "\n".join(lines)


def _build_naming_cluster_context(
    session: Session,
    scan_result_id: int,
    assessment_id: int,
) -> str:
    """Check if this artifact appears in any NamingCluster."""
    from ...models import NamingCluster

    clusters = session.exec(
        select(NamingCluster).where(
            NamingCluster.assessment_id == assessment_id,
        )
    ).all()

    matching: List[str] = []
    for cluster in clusters:
        try:
            member_ids = json.loads(cluster.member_ids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if scan_result_id in member_ids:
            tables = "unknown"
            try:
                tables = ", ".join(json.loads(cluster.tables_involved_json))
            except (json.JSONDecodeError, TypeError):
                pass
            matching.append(
                f"  - Cluster \"{cluster.cluster_label}\" "
                f"(pattern: {cluster.pattern_type}, "
                f"members: {cluster.member_count}, "
                f"tables: {tables})"
            )

    return "\n".join(matching) if matching else "  (not part of any naming cluster)"


def _build_feature_context(
    session: Session,
    scan_result_id: int,
) -> str:
    """Check if this artifact is linked to any Feature via FeatureScanResult."""
    from ...models import FeatureScanResult, Feature, ScanResult

    fsr_links = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.scan_result_id == scan_result_id,
        )
    ).all()

    if not fsr_links:
        return "  (not assigned to any feature)"

    sections: List[str] = []
    for link in fsr_links:
        feature = session.get(Feature, link.feature_id)
        if not feature:
            continue
        # Find other members of this feature
        other_links = session.exec(
            select(FeatureScanResult).where(
                FeatureScanResult.feature_id == feature.id,
                FeatureScanResult.scan_result_id != scan_result_id,
            )
        ).all()
        other_names: List[str] = []
        for ol in other_links[:15]:
            sr = session.get(ScanResult, ol.scan_result_id)
            if sr:
                other_names.append(f"    - {sr.name} ({sr.table_name})")

        sections.append(f"  **{feature.name}**")
        if feature.description:
            sections.append(f"    Description: {feature.description}")
        if other_names:
            sections.append("    Other members:")
            sections.extend(other_names)
        else:
            sections.append("    (sole member)")

    return "\n".join(sections) if sections else "  (not assigned to any feature)"


# ── Main handler ────────────────────────────────────────────────────

def _relationship_tracer_handler(
    arguments: Dict[str, Any],
    *,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Build and return the relationship tracer prompt with injected context.

    When ``session`` is None the handler returns a static prompt without
    dynamic context injection (graceful fallback for environments that
    don't pass a DB session).
    """
    result_id_str = arguments.get("result_id", "")
    assessment_id_str = arguments.get("assessment_id", "")
    max_depth_str = arguments.get("max_depth", "3")
    direction = arguments.get("direction", "outward")

    # Validate direction
    if direction not in ("outward", "inward", "both"):
        direction = "outward"

    try:
        max_depth = int(max_depth_str)
    except (ValueError, TypeError):
        max_depth = 3

    # --- Graceful fallback: no session ---
    if session is None:
        text = RELATIONSHIP_TRACER_TEXT + (
            "\n---\n\n"
            "**Note:** No database session available. Provide artifact "
            "relationship details manually or use MCP tools to query "
            "the assessment data.\n"
        )
        if result_id_str:
            text += f"\nRequested result_id: {result_id_str}\n"
        if assessment_id_str:
            text += f"Requested assessment_id: {assessment_id_str}\n"
        return {
            "description": "Trace cross-artifact dependency graphs.",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }

    # --- Normal path: query DB and build context ---
    from ...models import ScanResult

    try:
        result_id = int(result_id_str)
    except (ValueError, TypeError):
        raise ValueError(f"ScanResult not found: {result_id_str}")

    scan_result = session.get(ScanResult, result_id)
    if scan_result is None:
        raise ValueError(f"ScanResult not found: {result_id}")

    assessment_id = int(assessment_id_str) if assessment_id_str else None

    # Build context sections
    sections: List[str] = []

    # 0. Tracing parameters
    sections.append("## Tracing Parameters\n")
    sections.append(f"- **Direction:** {direction}")
    sections.append(f"- **Max Depth:** {max_depth}")
    sections.append("")

    # 1. Starting artifact
    sections.append("## Starting Artifact\n")
    sections.append(f"- **Name:** {scan_result.name}")
    sections.append(f"- **Table:** {scan_result.table_name}")
    sections.append(
        f"- **Origin:** "
        f"{scan_result.origin_type.value if scan_result.origin_type else 'unknown'}"
    )
    if scan_result.meta_target_table:
        sections.append(f"- **Target Table:** {scan_result.meta_target_table}")
    if scan_result.observations:
        sections.append(f"- **Observations:** {scan_result.observations}")
    sections.append("")

    # 2. Code snippet
    code = _extract_code_snippet(scan_result)
    if code:
        sections.append("## Code Snippet (first 100 lines)\n")
        sections.append("```javascript")
        sections.append(code)
        sections.append("```\n")

    # 3. Direct structural relationships
    if assessment_id:
        structural_ctx = _build_structural_context(
            session, result_id, assessment_id, direction,
        )
        sections.append("## Direct Structural Relationships\n")
        sections.append(structural_ctx)
        sections.append("")

        # 4. Update set siblings
        us_ctx = _build_update_set_siblings(session, result_id, assessment_id)
        sections.append("## Update Set Siblings\n")
        sections.append(us_ctx)
        sections.append("")

    # 5. Table-level neighbors
    table_ctx = _build_table_neighbors(session, scan_result, scan_result.scan_id)
    sections.append("## Table-Level Neighbors\n")
    sections.append(table_ctx)
    sections.append("")

    # 6. Naming cluster context
    if assessment_id:
        naming_ctx = _build_naming_cluster_context(
            session, result_id, assessment_id,
        )
        sections.append("## Naming Cluster Context\n")
        sections.append(naming_ctx)
        sections.append("")

    # 7. Feature context
    feature_ctx = _build_feature_context(session, result_id)
    sections.append("## Existing Feature Context\n")
    sections.append(feature_ctx)
    sections.append("")

    # Assemble final prompt
    context_block = "\n".join(sections)
    full_text = (
        RELATIONSHIP_TRACER_TEXT
        + "\n---\n\n"
        + "# Injected Context\n\n"
        + context_block
    )

    return {
        "description": "Trace cross-artifact dependency graphs.",
        "messages": [
            {
                "role": "user",
                "content": {"type": "text", "text": full_text},
            }
        ],
    }


# ── Prompt Specs for Registration ──────────────────────────────────

PROMPT_SPECS: List[PromptSpec] = [
    PromptSpec(
        name="relationship_tracer",
        description="Trace cross-artifact dependency graphs — queries "
                    "structural relationships, update set siblings, table "
                    "neighbors, naming clusters, and feature context to "
                    "build a comprehensive relationship map prompt.",
        arguments=[
            {
                "name": "result_id",
                "description": "ScanResult ID of the starting artifact to trace from",
                "required": True,
            },
            {
                "name": "assessment_id",
                "description": "Assessment ID for scoping related data queries",
                "required": True,
            },
            {
                "name": "max_depth",
                "description": "How many hops to trace (default: 3)",
                "required": False,
            },
            {
                "name": "direction",
                "description": (
                    'Trace direction: "outward" (default), "inward", or "both"'
                ),
                "required": False,
            },
        ],
        handler=_relationship_tracer_handler,
    ),
]
