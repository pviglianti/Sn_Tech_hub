"""Helpers for preserving iterative AI observation history across reruns."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


PASS_HISTORY_KEY = "pass_history"
_SNAPSHOT_SKIP_KEYS = {
    PASS_HISTORY_KEY,
    "prompt_context",
}


def load_ai_observation_payload(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {"raw_ai_observations": raw}


def archive_ai_observations_for_rerun(
    raw: Optional[str],
    *,
    reason: str = "ai_loop_rerun",
    archived_at: Optional[str] = None,
) -> Dict[str, Any]:
    payload = load_ai_observation_payload(raw)
    history = _history_entries(payload)
    current = _current_payload(payload)
    snapshot = _sanitize_snapshot(current)

    if snapshot:
        history.append(
            {
                "iteration": _safe_int(current.get("ai_loop_iteration")),
                "stage": str(current.get("analysis_stage") or "ai_loop").strip() or "ai_loop",
                "reason": str(reason or "ai_loop_rerun"),
                "archived_at": archived_at or datetime.utcnow().isoformat(),
                "summary_keys": sorted(snapshot.keys()),
                "snapshot": snapshot,
            }
        )

    return {PASS_HISTORY_KEY: history} if history else {}


def merge_ai_observation_payload(
    existing_raw: Optional[str],
    patch: Dict[str, Any],
    *,
    stage: Optional[str] = None,
    replace_current: bool = False,
) -> Dict[str, Any]:
    loaded = load_ai_observation_payload(existing_raw)
    history = _history_entries(loaded)
    current = {} if replace_current else _current_payload(loaded)
    merged = copy.deepcopy(current)
    merged.update(copy.deepcopy(patch or {}))

    resolved_stage = str(stage or merged.get("analysis_stage") or current.get("analysis_stage") or "").strip()
    if resolved_stage:
        merged.setdefault("analysis_stage", resolved_stage)

    if merged and "ai_loop_iteration" not in merged:
        merged["ai_loop_iteration"] = _current_iteration(current, history)

    if history:
        merged[PASS_HISTORY_KEY] = history

    return merged


def _history_entries(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_history = payload.get(PASS_HISTORY_KEY)
    if not isinstance(raw_history, list):
        return []
    return [entry for entry in raw_history if isinstance(entry, dict)]


def _current_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = {k: copy.deepcopy(v) for k, v in payload.items() if k != PASS_HISTORY_KEY}
    return current


def _sanitize_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if key in _SNAPSHOT_SKIP_KEYS:
                continue
            result[key] = _sanitize_snapshot(child)
        return result
    if isinstance(value, list):
        return [_sanitize_snapshot(item) for item in value]
    return copy.deepcopy(value)


def _current_iteration(current: Dict[str, Any], history: List[Dict[str, Any]]) -> int:
    existing = _safe_int(current.get("ai_loop_iteration"))
    if existing and existing > 0:
        return existing

    prior_iterations = [
        value
        for value in (_safe_int(entry.get("iteration")) for entry in history)
        if value and value > 0
    ]
    if prior_iterations:
        return max(prior_iterations) + 1
    return 1


def _safe_int(raw: Any) -> Optional[int]:
    try:
        value = int(raw)
    except Exception:
        return None
    return value
