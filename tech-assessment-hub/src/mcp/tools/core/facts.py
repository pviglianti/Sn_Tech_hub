"""MCP tools: save_fact and get_facts — agent memory persistence.

Lets AI agents persist instance-specific discoveries (facts) that survive
context resets. Facts are always instance-scoped.
"""

from typing import Any, Dict
from datetime import datetime

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Fact


# ============================================
# save_fact
# ============================================

SAVE_FACT_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {"type": "integer", "description": "Instance this fact is about."},
        "module": {"type": "string", "description": "Domain: tech_assessment, csdm, etc."},
        "topic_type": {"type": "string", "description": "What it's about: global_app, table, pattern, etc."},
        "topic_value": {"type": "string", "description": "Specific topic: incident, sys_script, etc."},
        "fact_key": {"type": "string", "description": "Fact identifier: custom_br_count, routing_mechanism, etc."},
        "fact_value": {"type": "string", "description": "The fact content (string or JSON-encoded)."},
        "created_by": {"type": "string", "description": "Who created this: ta_agent, user, computed."},
        "confidence": {"type": "number", "description": "1.0=verified, <1.0=inferred. Default 1.0."},
    },
    "required": ["instance_id", "module", "topic_type", "fact_key", "fact_value", "created_by"],
}


def handle_save_fact(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = int(params["instance_id"])
    module = params["module"]
    topic_type = params["topic_type"]
    topic_value = params.get("topic_value")
    fact_key = params["fact_key"]
    fact_value = params["fact_value"]
    created_by = params["created_by"]
    confidence = params.get("confidence", 1.0)

    # Upsert: find existing by unique key
    query = select(Fact).where(
        Fact.instance_id == instance_id,
        Fact.module == module,
        Fact.topic_type == topic_type,
        Fact.fact_key == fact_key,
    )
    if topic_value:
        query = query.where(Fact.topic_value == topic_value)

    existing = session.exec(query).first()

    if existing:
        existing.fact_value = fact_value
        existing.confidence = confidence
        existing.created_by = created_by
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return {"success": True, "action": "updated", "fact_id": existing.id}
    else:
        fact = Fact(
            instance_id=instance_id,
            module=module,
            topic_type=topic_type,
            topic_value=topic_value,
            fact_key=fact_key,
            fact_value=fact_value,
            created_by=created_by,
            confidence=confidence,
        )
        session.add(fact)
        session.commit()
        session.refresh(fact)
        return {"success": True, "action": "created", "fact_id": fact.id}


SAVE_FACT_TOOL_SPEC = ToolSpec(
    name="save_fact",
    description=(
        "Persist an instance-specific fact (discovery) that survives context resets. "
        "Facts are upserted by instance+module+topic_type+topic_value+fact_key."
    ),
    input_schema=SAVE_FACT_INPUT_SCHEMA,
    handler=handle_save_fact,
    permission="write",
)


# ============================================
# get_facts
# ============================================

GET_FACTS_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {"type": "integer", "description": "Filter by instance."},
        "module": {"type": "string", "description": "Filter by module/domain."},
        "topic_type": {"type": "string", "description": "Filter by topic type."},
        "topic_value": {"type": "string", "description": "Filter by specific topic."},
        "fact_key": {"type": "string", "description": "Filter by fact key."},
        "limit": {"type": "integer", "description": "Max facts to return (default 100)."},
    },
}


def handle_get_facts(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    query = select(Fact)

    instance_id = params.get("instance_id")
    if instance_id is not None:
        query = query.where(Fact.instance_id == int(instance_id))

    module = params.get("module")
    if module:
        query = query.where(Fact.module == module)

    topic_type = params.get("topic_type")
    if topic_type:
        query = query.where(Fact.topic_type == topic_type)

    topic_value = params.get("topic_value")
    if topic_value:
        query = query.where(Fact.topic_value == topic_value)

    fact_key = params.get("fact_key")
    if fact_key:
        query = query.where(Fact.fact_key == fact_key)

    limit = min(params.get("limit", 100), 500)
    query = query.limit(limit)

    facts = session.exec(query).all()

    return {
        "success": True,
        "count": len(facts),
        "facts": [
            {
                "id": f.id,
                "instance_id": f.instance_id,
                "module": f.module,
                "topic_type": f.topic_type,
                "topic_value": f.topic_value,
                "fact_key": f.fact_key,
                "fact_value": f.fact_value,
                "created_by": f.created_by,
                "confidence": f.confidence,
                "updated_at": f.updated_at.isoformat() if f.updated_at else None,
            }
            for f in facts
        ],
    }


GET_FACTS_TOOL_SPEC = ToolSpec(
    name="get_facts",
    description=(
        "Retrieve persisted facts for an instance. Filter by module, topic, or key. "
        "Facts are instance-specific discoveries that persist across AI sessions."
    ),
    input_schema=GET_FACTS_INPUT_SCHEMA,
    handler=handle_get_facts,
    permission="read",
)


# ============================================
# delete_facts
# ============================================

DELETE_FACTS_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "instance_id": {"type": "integer", "description": "Instance ID to delete facts for."},
        "module": {"type": "string", "description": "Optional module filter."},
        "topic_type": {"type": "string", "description": "Optional topic type filter."},
        "fact_key": {"type": "string", "description": "Optional specific fact key to delete."},
    },
    "required": ["instance_id"],
}


def handle_delete_facts(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    instance_id = int(params["instance_id"])

    query = select(Fact).where(Fact.instance_id == instance_id)

    module = params.get("module")
    if module:
        query = query.where(Fact.module == module)

    topic_type = params.get("topic_type")
    if topic_type:
        query = query.where(Fact.topic_type == topic_type)

    fact_key = params.get("fact_key")
    if fact_key:
        query = query.where(Fact.fact_key == fact_key)

    facts = session.exec(query).all()
    count = len(facts)

    for fact in facts:
        session.delete(fact)

    if count > 0:
        session.commit()

    return {
        "success": True,
        "deleted_count": count,
        "instance_id": instance_id,
    }


DELETE_FACTS_TOOL_SPEC = ToolSpec(
    name="delete_facts",
    description=(
        "Delete persisted facts for an instance. Filter by module, topic_type, "
        "or fact_key. Deletes all matching rows and returns the count deleted."
    ),
    input_schema=DELETE_FACTS_INPUT_SCHEMA,
    handler=handle_delete_facts,
    permission="write",
)
