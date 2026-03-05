"""MCP tool: get_usage_count.

Efficiently query ServiceNow usage volume via ``X-Total-Count`` and cache the
result in the Fact table for reuse during observation runs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Fact, Instance
from ....services.encryption import decrypt_password
from ....services.integration_properties import load_observation_properties
from ....services.sn_client import ServiceNowClient, ServiceNowClientError


INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {
            "type": "integer",
            "description": "Instance ID to query.",
        },
        "table": {
            "type": "string",
            "description": "ServiceNow table name to count records from.",
        },
        "query": {
            "type": "string",
            "description": "Base encoded query before lookback filter is appended.",
            "default": "",
        },
        "date_field": {
            "type": "string",
            "description": "Date field used for lookback filtering.",
            "default": "sys_updated_on",
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of the usage check.",
            "default": "",
        },
        "use_cache": {
            "type": "boolean",
            "description": "Whether to return cached Fact rows when still valid.",
            "default": True,
        },
    },
    "required": ["instance_id", "table"],
}


_FACT_MODULE = "tech_assessment"
_FACT_TOPIC_TYPE = "usage_count"
_CACHE_TTL_HOURS = 12


def _compose_query(base_query: str, date_field: str, lookback_months: int) -> str:
    base = (base_query or "").strip()
    field = (date_field or "sys_updated_on").strip() or "sys_updated_on"
    lookback_filter = f"{field}>=javascript:gs.monthsAgo({int(lookback_months)})"
    if not base:
        return lookback_filter
    if base.endswith("^"):
        return f"{base}{lookback_filter}"
    return f"{base}^{lookback_filter}"


def _fact_key(table: str, query: str) -> str:
    digest = hashlib.sha1(f"{table}|{query}".encode("utf-8")).hexdigest()[:16]
    return f"usage_count:{table}:{digest}"


def _read_cached_fact(
    session: Session,
    *,
    instance_id: int,
    table: str,
    fact_key: str,
) -> Fact | None:
    return session.exec(
        select(Fact)
        .where(Fact.instance_id == instance_id)
        .where(Fact.module == _FACT_MODULE)
        .where(Fact.topic_type == _FACT_TOPIC_TYPE)
        .where(Fact.topic_value == table)
        .where(Fact.fact_key == fact_key)
        .limit(1)
    ).first()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def handle(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = int(params["instance_id"])
    table = str(params["table"]).strip()
    if not table:
        raise ValueError("table is required")

    instance = session.get(Instance, instance_id)
    if not instance:
        return {"success": False, "error": f"Instance not found: {instance_id}"}

    obs_props = load_observation_properties(session, instance_id=instance_id)
    base_query = str(params.get("query", "") or "")
    date_field = str(params.get("date_field", "sys_updated_on") or "sys_updated_on")
    description = str(params.get("description", "") or "")
    use_cache = bool(params.get("use_cache", True))

    resolved_query = _compose_query(base_query, date_field, obs_props.usage_lookback_months)
    key = _fact_key(table, resolved_query)
    now = datetime.utcnow()

    cached_row = _read_cached_fact(session, instance_id=instance_id, table=table, fact_key=key)
    if use_cache and cached_row and cached_row.valid_until and cached_row.valid_until >= now:
        cached_payload: Dict[str, Any] = {}
        try:
            cached_payload = json.loads(cached_row.fact_value or "{}")
        except Exception:
            cached_payload = {}
        return {
            "success": True,
            "instance_id": instance_id,
            "table": table,
            "query": resolved_query,
            "lookback_months": obs_props.usage_lookback_months,
            "count": _to_int(cached_payload.get("count"), 0),
            "cached": True,
            "description": description or cached_payload.get("description"),
            "fact_id": cached_row.id,
            "valid_until": cached_row.valid_until.isoformat() if cached_row.valid_until else None,
        }

    try:
        password = decrypt_password(instance.password_encrypted)
        client = ServiceNowClient(
            instance.url,
            instance.username,
            password,
            instance_id=instance.id,
        )
        count = int(client.get_record_count(table=table, query=resolved_query))
    except ServiceNowClientError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive branch
        return {"success": False, "error": f"Unexpected error: {exc}"}

    payload = {
        "count": count,
        "table": table,
        "query": resolved_query,
        "lookback_months": obs_props.usage_lookback_months,
        "description": description,
        "queried_at": now.isoformat(),
    }
    valid_until = now + timedelta(hours=_CACHE_TTL_HOURS)

    fact_row = cached_row
    if fact_row:
        fact_row.fact_value = json.dumps(payload, sort_keys=True)
        fact_row.confidence = 1.0
        fact_row.created_by = "computed"
        fact_row.output_type = "count"
        fact_row.deliverable_target = "observation_pipeline"
        fact_row.valid_until = valid_until
        fact_row.updated_at = now
    else:
        fact_row = Fact(
            instance_id=instance_id,
            module=_FACT_MODULE,
            topic_type=_FACT_TOPIC_TYPE,
            topic_value=table,
            fact_key=key,
            fact_value=json.dumps(payload, sort_keys=True),
            created_by="computed",
            output_type="count",
            deliverable_target="observation_pipeline",
            confidence=1.0,
            valid_until=valid_until,
            source_table=table,
            source_sys_id=None,
            computed_at=now,
            created_at=now,
            updated_at=now,
        )
    session.add(fact_row)
    session.commit()
    session.refresh(fact_row)

    return {
        "success": True,
        "instance_id": instance_id,
        "table": table,
        "query": resolved_query,
        "lookback_months": obs_props.usage_lookback_months,
        "count": count,
        "cached": False,
        "description": description,
        "fact_id": fact_row.id,
        "valid_until": fact_row.valid_until.isoformat() if fact_row.valid_until else None,
    }


TOOL_SPEC = ToolSpec(
    name="get_usage_count",
    description=(
        "Return a lightweight ServiceNow record count (via X-Total-Count header) "
        "for a table/query and cache the result as a Fact for reuse."
    ),
    input_schema=INPUT_SCHEMA,
    handler=handle,
    permission="read",
)
