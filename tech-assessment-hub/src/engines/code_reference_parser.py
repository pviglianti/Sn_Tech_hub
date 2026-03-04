"""Engine 1: Code Reference Parser.

Parses script/code fields in artifact detail tables to find cross-references
to other artifacts (script includes, tables, events, etc.).

Input: Artifact detail tables with code_fields
Output: Rows in code_reference table
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select
from sqlalchemy import text

from ..artifact_detail_defs import ARTIFACT_DETAIL_DEFS
from ..models import Assessment, CodeReference, Scan, ScanResult


# ---------------------------------------------------------------------------
# Regex patterns — each tuple is (compiled_regex, reference_type, group_index)
# ---------------------------------------------------------------------------
_PATTERNS: List[Tuple[re.Pattern, str, int]] = [
    # Script include-like class instantiation. Excludes common SN builtins.
    (
        re.compile(
            r"\bnew\s+"
            r"(?!Glide(?:Record|Ajax|DateTime|Aggregate|Duration|Schedule|Element|"
            r"Filter|Session|System|Transaction|URI|Sys|Evaluation|App(?:Navigation)?|"
            r"PluginManager|UpdateManager2?|Workflow|DBFunctionBuilder)\b)"
            r"(?!sn_\w+\.)"
            r"([A-Z]\w{2,})\s*\("
        ),
        "script_include",
        1,
    ),
    (
        re.compile(r"\bnew\s+Glide(?:Record|Aggregate)\s*\(\s*['\"]([a-z_][a-z0-9_]*)['\"]"),
        "table_query",
        1,
    ),
    (re.compile(r"\bgs\.include\s*\(\s*['\"]([^\"']+)['\"]"), "script_include", 1),
    (re.compile(r"\bgs\.eventQueue\s*\(\s*['\"]([^\"']+)['\"]"), "event", 1),
    (re.compile(r"\bnew\s+GlideAjax\s*\(\s*['\"]([^\"']+)['\"]"), "script_include", 1),
    (re.compile(r"\bnew\s+(?:sn_ws\.)?RESTMessageV2\s*\(\s*['\"]([^\"']+)['\"]"), "rest_message", 1),
    (re.compile(r"\bworkflow\.start(?:Flow)?\s*\(\s*['\"]([^\"']+)['\"]"), "workflow", 1),
    (re.compile(r"\$sp\.getWidget\s*\(\s*['\"]([^\"']+)['\"]"), "sp_widget", 1),
    (re.compile(r"(?:['\"])([0-9a-f]{32})(?:['\"])", re.IGNORECASE), "sys_id_reference", 1),
    (re.compile(r"\bg_(?:form|list)\.\w+\s*\(\s*['\"]([a-z_]\w*)['\"]", re.IGNORECASE), "field_reference", 1),
    (re.compile(r"\bcurrent\.([a-z_]\w*)\b(?!\s*\()", re.IGNORECASE), "field_reference", 1),
]


_IGNORE_FIELDS = frozenset(
    {
        "sys_id",
        "sys_created_on",
        "sys_updated_on",
        "sys_created_by",
        "sys_updated_by",
        "sys_mod_count",
        "sys_class_name",
        "sys_domain",
        "update",
        "insert",
        "deleterecord",
        "next",
        "get",
        "initialize",
        "isnewrecord",
        "isvalid",
        "isvalidrecord",
        "setworkflow",
        "autosysfields",
        "setlimit",
        "getrowcount",
        "getuniquevalue",
        "getdisplayvalue",
        "gettablename",
        "nil",
        "changes",
        "changesfrom",
        "changesto",
        "operation",
        "isactionaborted",
        "setabortaction",
        "addquery",
        "query",
        "orderby",
        "orderbydesc",
        "hasnext",
        "getvalue",
        "setvalue",
        "getelement",
        "geted",
        "getlabel",
        "getrecordclassname",
        "canread",
        "canwrite",
        "cancreate",
        "candelete",
    }
)


def extract_references(script: str, source_table: str, source_field: str) -> List[Dict[str, Any]]:
    """Extract cross-references from a script string."""
    del source_table, source_field

    if not script or not script.strip():
        return []

    results: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
    lines = script.split("\n")

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue

        for pattern, ref_type, group_idx in _PATTERNS:
            for match in pattern.finditer(line):
                target = (match.group(group_idx) or "").strip()
                if not target:
                    continue

                normalized_target = target.lower() if ref_type == "field_reference" else target

                if ref_type == "field_reference" and normalized_target in _IGNORE_FIELDS:
                    continue
                if ref_type == "table_query" and normalized_target in {"true", "false", "null"}:
                    continue

                dedup_key = (ref_type, normalized_target)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                snippet = stripped if len(stripped) <= 200 else stripped[:200]
                results.append(
                    {
                        "reference_type": ref_type,
                        "target_identifier": target,
                        "line_number": line_idx,
                        "code_snippet": snippet,
                        "confidence": 1.0,
                    }
                )

    return results


def run(assessment_id: int, session: Session) -> Dict[str, Any]:
    """Run the code reference parser engine for an assessment."""
    assessment = session.get(Assessment, assessment_id)
    if not assessment:
        return {
            "success": False,
            "references_created": 0,
            "resolved_count": 0,
            "tables_processed": 0,
            "errors": [f"Assessment not found: {assessment_id}"],
        }

    instance_id = assessment.instance_id

    scan_results = list(
        session.exec(
            select(ScanResult)
            .join(Scan, Scan.id == ScanResult.scan_id)
            .where(Scan.assessment_id == assessment_id)
        ).all()
    )

    if not scan_results:
        return {
            "success": True,
            "references_created": 0,
            "resolved_count": 0,
            "tables_processed": 0,
            "errors": [],
            "message": "No scan results found",
        }

    # Make reruns idempotent per assessment.
    existing = list(session.exec(select(CodeReference).where(CodeReference.assessment_id == assessment_id)).all())
    for row in existing:
        session.delete(row)
    session.flush()

    table_code_fields: Dict[str, List[str]] = {}
    table_local_name: Dict[str, str] = {}
    for sn_table, defn in ARTIFACT_DETAIL_DEFS.items():
        code_fields = list(defn.get("code_fields", []))
        if code_fields:
            table_code_fields[sn_table] = code_fields
            table_local_name[sn_table] = str(defn["local_table"])

    sr_by_id: Dict[int, ScanResult] = {int(sr.id): sr for sr in scan_results if sr.id is not None}
    sr_by_table: Dict[str, List[ScanResult]] = {}
    sr_by_name: Dict[str, List[ScanResult]] = {}
    for sr in scan_results:
        sr_by_table.setdefault(sr.table_name, []).append(sr)
        sr_by_name.setdefault(sr.name, []).append(sr)

    references_created = 0
    tables_processed = 0
    errors: List[str] = []

    for sn_table, code_fields in table_code_fields.items():
        if sn_table not in sr_by_table:
            continue

        local_table = table_local_name[sn_table]
        exists = session.exec(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:tbl").bindparams(
                tbl=local_table
            )
        ).first()
        if not exists:
            continue

        tables_processed += 1

        select_columns = ["scan_result_id"] + [f'"{field_name}"' for field_name in code_fields]
        sql = f"SELECT {', '.join(select_columns)} FROM {local_table} WHERE scan_result_id IS NOT NULL"

        try:
            rows = session.exec(text(sql)).all()
        except Exception as exc:  # pragma: no cover - defensive branch
            errors.append(f"Error reading {local_table}: {exc}")
            continue

        for row in rows:
            row_values = tuple(row)
            if not row_values:
                continue
            sr_id = row_values[0]
            if sr_id is None:
                continue
            source_sr = sr_by_id.get(int(sr_id))
            if not source_sr:
                continue

            for idx, field_name in enumerate(code_fields, start=1):
                script_content = row_values[idx] if idx < len(row_values) else None
                if not isinstance(script_content, str) or not script_content.strip():
                    continue

                refs = extract_references(script_content, sn_table, field_name)
                for ref_data in refs:
                    session.add(
                        CodeReference(
                            instance_id=instance_id,
                            assessment_id=assessment_id,
                            source_scan_result_id=source_sr.id,
                            source_table=sn_table,
                            source_field=field_name,
                            source_name=source_sr.name,
                            reference_type=str(ref_data["reference_type"]),
                            target_identifier=str(ref_data["target_identifier"]),
                            line_number=ref_data.get("line_number"),
                            code_snippet=ref_data.get("code_snippet"),
                            confidence=float(ref_data.get("confidence", 1.0)),
                        )
                    )
                    references_created += 1

    session.flush()

    resolved_count = 0
    unresolved_refs = list(
        session.exec(
            select(CodeReference).where(
                CodeReference.assessment_id == assessment_id,
                CodeReference.target_scan_result_id.is_(None),
            )
        ).all()
    )

    for code_ref in unresolved_refs:
        target_sr = _resolve_target(code_ref, sr_by_name, sr_by_table)
        if target_sr and target_sr.id is not None:
            code_ref.target_scan_result_id = target_sr.id
            session.add(code_ref)
            resolved_count += 1

    session.commit()

    return {
        "success": True,
        "references_created": references_created,
        "resolved_count": resolved_count,
        "tables_processed": tables_processed,
        "errors": errors,
    }


def _resolve_target(
    code_ref: CodeReference,
    sr_by_name: Dict[str, List[ScanResult]],
    sr_by_table: Dict[str, List[ScanResult]],
) -> Optional[ScanResult]:
    """Resolve a CodeReference target_identifier to a ScanResult when possible."""
    target = code_ref.target_identifier

    if code_ref.reference_type == "script_include":
        candidates = sr_by_name.get(target, [])
        for candidate in candidates:
            if candidate.table_name == "sys_script_include":
                return candidate
        if candidates:
            return candidates[0]

    if code_ref.reference_type == "table_query":
        # Table names generally represent data tables, not metadata artifacts.
        # A best-effort match is to scan results directly for matching table_name.
        table_candidates = sr_by_table.get(target, [])
        if table_candidates:
            return table_candidates[0]
        return None

    candidates = sr_by_name.get(target, [])
    if candidates:
        return candidates[0]

    return None
