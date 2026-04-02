"""Engine 1: Code Reference Parser.

Parses script/code fields in artifact detail tables to find cross-references
to other artifacts (script includes, tables, events, etc.).

Input: Artifact detail tables with code_fields
Output: Rows in code_reference table
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlmodel import Session, select
from sqlalchemy import text

from ..artifact_detail_defs import ARTIFACT_DETAIL_DEFS
from ..models import Assessment, CodeReference, Scan, ScanResult


_CUSTOMIZED_ORIGIN_VALUES = frozenset({"modified_ootb", "net_new_customer"})
_REFERENCE_TYPE_EXACT_TABLES: Dict[str, Tuple[str, ...]] = {
    "script_include": ("sys_script_include",),
    "table_query": ("sys_db_object",),
    "workflow": ("wf_workflow",),
    "sp_widget": ("sp_widget",),
}


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
        for optional_field in _optional_code_fields_for_sn_table(sn_table):
            if optional_field not in code_fields:
                code_fields.append(optional_field)
        if code_fields:
            table_code_fields[sn_table] = code_fields
            table_local_name[sn_table] = str(defn["local_table"])

    sr_by_id: Dict[int, ScanResult] = {int(sr.id): sr for sr in scan_results if sr.id is not None}
    sr_by_sys_id: Dict[str, ScanResult] = {}
    sr_by_table: Dict[str, List[ScanResult]] = {}
    sr_by_name: Dict[str, List[ScanResult]] = {}
    table_results_by_name: Dict[str, List[ScanResult]] = {}
    field_targets_by_key: Dict[Tuple[str, str], List[ScanResult]] = {}
    source_table_hints_by_result_id: Dict[int, List[str]] = {}
    script_include_targets_by_api_name: Dict[Tuple[str, str], List[ScanResult]] = {}
    for sr in scan_results:
        sr_by_table.setdefault(sr.table_name, []).append(sr)
        sr_by_name.setdefault(sr.name, []).append(sr)
        if sr.sys_id:
            sr_by_sys_id[str(sr.sys_id).lower()] = sr
        raw_payload = _safe_json(sr.raw_data_json)
        if sr.table_name == "sys_db_object":
            for table_name in _table_names_for_result(sr, raw_payload):
                table_results_by_name.setdefault(table_name, []).append(sr)
        if sr.table_name in {"sys_dictionary", "sys_dictionary_override"}:
            dict_key = _dictionary_key_from_result(sr, raw_payload)
            if dict_key is not None:
                _append_result_mapping(field_targets_by_key, dict_key, sr)

        if sr.id is not None:
            for table_hint in _source_table_candidates(source_sr=sr):
                _append_source_table_hint(source_table_hints_by_result_id, int(sr.id), table_hint)

    _augment_dictionary_indexes_from_detail_rows(
        session=session,
        assessment_id=assessment_id,
        sr_by_id=sr_by_id,
        field_targets_by_key=field_targets_by_key,
        source_table_hints_by_result_id=source_table_hints_by_result_id,
    )
    _augment_script_include_indexes_from_detail_rows(
        session=session,
        assessment_id=assessment_id,
        sr_by_id=sr_by_id,
        script_include_targets_by_api_name=script_include_targets_by_api_name,
    )

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

        available_fields = _load_table_columns(session, local_table)
        code_fields = [field for field in code_fields if field in available_fields]
        if not code_fields:
            continue

        tables_processed += 1

        code_cols = ", ".join(f'art."{f}"' for f in code_fields)
        sql = (
            f"SELECT sr.id, {code_cols} "
            f"FROM scan_result sr "
            f"JOIN scan s ON s.id = sr.scan_id "
            f"JOIN assessment a ON a.id = s.assessment_id "
            f"JOIN {local_table} art ON art.sys_id = sr.sys_id AND art._instance_id = a.instance_id "
            f"WHERE s.assessment_id = :aid"
        )

        try:
            rows = session.exec(text(sql).bindparams(aid=assessment_id)).all()
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
        source_sr = sr_by_id.get(int(code_ref.source_scan_result_id or 0))
        target_srs = _resolve_targets(
            code_ref,
            source_sr=source_sr,
            sr_by_sys_id=sr_by_sys_id,
            sr_by_name=sr_by_name,
            sr_by_table=sr_by_table,
            table_results_by_name=table_results_by_name,
            field_targets_by_key=field_targets_by_key,
            source_table_hints_by_result_id=source_table_hints_by_result_id,
            script_include_targets_by_api_name=script_include_targets_by_api_name,
        )
        if not target_srs:
            continue

        for idx, target_sr in enumerate(target_srs):
            if target_sr.id is None:
                continue
            if idx == 0:
                target_ref = code_ref
            else:
                target_ref = CodeReference(
                    instance_id=code_ref.instance_id,
                    assessment_id=code_ref.assessment_id,
                    source_scan_result_id=code_ref.source_scan_result_id,
                    source_table=code_ref.source_table,
                    source_field=code_ref.source_field,
                    source_name=code_ref.source_name,
                    reference_type=code_ref.reference_type,
                    target_identifier=code_ref.target_identifier,
                    line_number=code_ref.line_number,
                    code_snippet=code_ref.code_snippet,
                    confidence=code_ref.confidence,
                )
            target_ref.target_scan_result_id = target_sr.id
            session.add(target_ref)
            resolved_count += 1

    session.commit()

    return {
        "success": True,
        "references_created": references_created,
        "resolved_count": resolved_count,
        "tables_processed": tables_processed,
        "errors": errors,
    }


def _resolve_targets(
    code_ref: CodeReference,
    *,
    source_sr: Optional[ScanResult],
    sr_by_sys_id: Dict[str, ScanResult],
    sr_by_name: Dict[str, List[ScanResult]],
    sr_by_table: Dict[str, List[ScanResult]],
    table_results_by_name: Dict[str, List[ScanResult]],
    field_targets_by_key: Dict[Tuple[str, str], List[ScanResult]],
    source_table_hints_by_result_id: Dict[int, List[str]],
    script_include_targets_by_api_name: Dict[Tuple[str, str], List[ScanResult]],
) -> List[ScanResult]:
    """Resolve a CodeReference target_identifier to one or more ScanResults."""
    target = (code_ref.target_identifier or "").strip()
    if not target:
        return []

    if code_ref.reference_type == "script_include":
        script_include_candidates = _select_unique_candidates(
            sr_by_name.get(target, []),
            allowed_tables=("sys_script_include",),
        )

        source_scope = _normalized_scope(source_sr.sys_scope if source_sr else None)
        if "." in target:
            scoped_api_matches = _select_unique_candidates(
                script_include_targets_by_api_name.get((source_scope, target.lower()), [])
            )
            if scoped_api_matches:
                return scoped_api_matches
            unscoped_api_matches = _select_unique_candidates(
                script_include_targets_by_api_name.get(("", target.lower()), [])
            )
            return unscoped_api_matches

        if source_scope:
            scoped_matches = [
                candidate
                for candidate in script_include_candidates
                if _normalized_scope(candidate.sys_scope) == source_scope
            ]
            if scoped_matches:
                return _select_unique_candidates(scoped_matches, allowed_tables=("sys_script_include",))
            return []

        if len(script_include_candidates) == 1:
            return script_include_candidates
        return []

    allowed_tables = _REFERENCE_TYPE_EXACT_TABLES.get(code_ref.reference_type)
    if allowed_tables:
        if code_ref.reference_type == "table_query":
            return _select_unique_candidates(
                table_results_by_name.get(target.lower(), []),
                allowed_tables=allowed_tables,
            )
        return _select_unique_candidates(
            sr_by_name.get(target, []),
            allowed_tables=allowed_tables,
        )

    if code_ref.reference_type == "sys_id_reference":
        candidate = sr_by_sys_id.get(target.lower())
        return [candidate] if candidate is not None else []

    if code_ref.reference_type == "field_reference":
        source_result_id = int(source_sr.id) if source_sr and source_sr.id is not None else None
        source_table_hints = []
        if source_result_id is not None:
            source_table_hints = source_table_hints_by_result_id.get(source_result_id, [])
        for table_name in _source_table_candidates(source_sr, source_table_hints=source_table_hints):
            candidates = field_targets_by_key.get((table_name, target.lower()), [])
            if not candidates:
                continue
            return _select_field_candidates(candidates)
        return []

    candidates = sr_by_name.get(target, [])
    if candidates:
        return _select_unique_candidates(candidates)

    return []


def _optional_code_fields_for_sn_table(sn_table: str) -> Sequence[str]:
    if sn_table in {"sys_dictionary", "sys_dictionary_override"}:
        return ("reference_qual",)
    return ()


def _load_table_columns(session: Session, table_name: str) -> Set[str]:
    rows = session.exec(text(f'PRAGMA table_info("{table_name}")')).all()
    return {str(tuple(row)[1]) for row in rows if len(tuple(row)) > 1 and tuple(row)[1]}


def _safe_json(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dictionary_key_from_result(
    result: ScanResult,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[str, str]]:
    raw = raw_payload or {}
    table_name = str(raw.get("name") or result.meta_target_table or "").strip()
    element = str(raw.get("element") or "").strip()

    if (not table_name or not element) and result.name and "." in str(result.name):
        left, right = str(result.name).split(".", 1)
        if not table_name:
            table_name = left.strip()
        if not element:
            element = right.strip()

    if not table_name or not element:
        return None
    return (table_name.lower(), element.lower())


def _table_names_for_result(
    result: ScanResult,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> List[str]:
    raw = raw_payload or {}
    names: List[str] = []
    for candidate in (result.name, raw.get("name"), result.meta_target_table):
        normalized = str(candidate or "").strip().lower()
        if normalized and normalized not in names:
            names.append(normalized)
    return names


def _source_table_candidates(
    source_sr: Optional[ScanResult],
    source_table_hints: Optional[Sequence[str]] = None,
) -> List[str]:
    if not source_sr:
        return []

    raw = _safe_json(source_sr.raw_data_json)
    candidates: List[str] = []

    def _add(candidate: Any) -> None:
        normalized = str(candidate or "").strip().lower()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    _add(source_sr.meta_target_table)
    for hint in source_table_hints or ():
        _add(hint)

    if source_sr.table_name in {"sys_dictionary", "sys_dictionary_override", "sys_choice"}:
        _add(raw.get("name"))
    elif source_sr.table_name == "sys_db_object":
        _add(source_sr.name)
        _add(raw.get("name"))
    else:
        for key in ("table", "collection", "table_name", "target_table"):
            _add(raw.get(key))

    return candidates


def _augment_dictionary_indexes_from_detail_rows(
    *,
    session: Session,
    assessment_id: int,
    sr_by_id: Dict[int, ScanResult],
    field_targets_by_key: Dict[Tuple[str, str], List[ScanResult]],
    source_table_hints_by_result_id: Dict[int, List[str]],
) -> None:
    for sn_table in ("sys_dictionary", "sys_dictionary_override"):
        local_table = str(ARTIFACT_DETAIL_DEFS[sn_table]["local_table"])
        available_fields = _load_table_columns(session, local_table)
        if not {"name", "element"}.issubset(available_fields):
            continue

        rows = session.exec(
            text(
                f"SELECT sr.id, art.\"name\", art.\"element\" "
                f"FROM scan_result sr "
                f"JOIN scan s ON s.id = sr.scan_id "
                f"JOIN assessment a ON a.id = s.assessment_id "
                f"JOIN {local_table} art ON art.sys_id = sr.sys_id AND art._instance_id = a.instance_id "
                f"WHERE s.assessment_id = :aid AND sr.table_name = :sn_table"
            ).bindparams(aid=assessment_id, sn_table=sn_table)
        ).all()

        for row in rows:
            values = tuple(row)
            if len(values) < 3 or values[0] is None:
                continue
            result = sr_by_id.get(int(values[0]))
            if result is None:
                continue

            table_name = str(values[1] or "").strip().lower()
            element = str(values[2] or "").strip().lower()
            if table_name and element:
                _append_result_mapping(field_targets_by_key, (table_name, element), result)
                _append_source_table_hint(source_table_hints_by_result_id, int(result.id), table_name)


def _augment_script_include_indexes_from_detail_rows(
    *,
    session: Session,
    assessment_id: int,
    sr_by_id: Dict[int, ScanResult],
    script_include_targets_by_api_name: Dict[Tuple[str, str], List[ScanResult]],
) -> None:
    local_table = str(ARTIFACT_DETAIL_DEFS["sys_script_include"]["local_table"])
    available_fields = _load_table_columns(session, local_table)
    if "api_name" not in available_fields:
        return

    rows = session.exec(
        text(
            f"SELECT sr.id, art.\"api_name\" "
            f"FROM scan_result sr "
            f"JOIN scan s ON s.id = sr.scan_id "
            f"JOIN assessment a ON a.id = s.assessment_id "
            f"JOIN {local_table} art ON art.sys_id = sr.sys_id AND art._instance_id = a.instance_id "
            f"WHERE s.assessment_id = :aid AND sr.table_name = 'sys_script_include' "
            f"AND art.\"api_name\" IS NOT NULL"
        ).bindparams(aid=assessment_id)
    ).all()

    for row in rows:
        values = tuple(row)
        if len(values) < 2 or values[0] is None:
            continue
        result = sr_by_id.get(int(values[0]))
        if result is None:
            continue
        api_name = str(values[1] or "").strip().lower()
        if not api_name:
            continue
        scope_key = _normalized_scope(result.sys_scope)
        _append_result_mapping(script_include_targets_by_api_name, (scope_key, api_name), result)
        _append_result_mapping(script_include_targets_by_api_name, ("", api_name), result)


def _append_result_mapping(
    mapping: Dict[Tuple[str, str], List[ScanResult]],
    key: Tuple[str, str],
    result: ScanResult,
) -> None:
    result_id = int(result.id or 0)
    if result_id <= 0:
        return
    bucket = mapping.setdefault(key, [])
    if any(int(existing.id or 0) == result_id for existing in bucket):
        return
    bucket.append(result)


def _append_source_table_hint(
    mapping: Dict[int, List[str]],
    result_id: int,
    table_name: str,
) -> None:
    normalized = str(table_name or "").strip().lower()
    if not normalized:
        return
    bucket = mapping.setdefault(int(result_id), [])
    if normalized not in bucket:
        bucket.append(normalized)


def _normalized_scope(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _candidate_identity(candidate: ScanResult) -> Tuple[str, str]:
    return (
        str(candidate.table_name or "").strip().lower(),
        str(candidate.sys_id or candidate.id or "").strip().lower(),
    )


def _select_unique_candidates(
    candidates: Sequence[ScanResult],
    *,
    allowed_tables: Optional[Sequence[str]] = None,
) -> List[ScanResult]:
    selected: List[ScanResult] = []
    seen_keys: Set[Tuple[str, str]] = set()
    allowed = {str(value or "").strip().lower() for value in (allowed_tables or ()) if str(value or "").strip()}

    for candidate in candidates:
        table_name = str(candidate.table_name or "").strip().lower()
        if allowed and table_name not in allowed:
            continue
        logical_key = _candidate_identity(candidate)
        if logical_key in seen_keys:
            continue
        selected.append(candidate)
        seen_keys.add(logical_key)

    return selected


def _field_candidate_rank(candidate: ScanResult) -> Tuple[int, int, int]:
    customized_rank = 0 if str(candidate.origin_type or "").strip() in _CUSTOMIZED_ORIGIN_VALUES else 1
    if candidate.table_name == "sys_dictionary_override":
        table_rank = 0
    elif candidate.table_name == "sys_dictionary":
        table_rank = 1
    else:
        table_rank = 2
    return (customized_rank, table_rank, int(candidate.id or 0))


def _select_field_candidates(candidates: Sequence[ScanResult]) -> List[ScanResult]:
    selected: List[ScanResult] = []
    seen_keys: Set[Tuple[str, str]] = set()

    for candidate in sorted(candidates, key=_field_candidate_rank):
        logical_key = _candidate_identity(candidate)
        if logical_key in seen_keys:
            continue
        selected.append(candidate)
        seen_keys.add(logical_key)

    return selected
