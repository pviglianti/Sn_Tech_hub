"""MCP tools: add_result_to_feature / remove_result_from_feature.

AI manages feature membership -- add or remove customized scan results
to/from features.  Only customized results (origin_type in
``modified_ootb``, ``net_new_customer``) may be feature members.
"""

from typing import Any, Dict

from sqlmodel import Session, select

from ...registry import ToolSpec
from ....models import Feature, FeatureScanResult, ScanResult
from ....services.feature_governance import (
    refresh_feature_metadata,
    replace_result_feature_membership,
)

# ── Add tool ────────────────────────────────────────────────────────

ADD_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "ID of the feature to add the scan result to.",
        },
        "scan_result_id": {
            "type": "integer",
            "description": "ID of the scan result to add as a feature member.",
        },
    },
    "required": ["feature_id", "scan_result_id"],
}


def handle_add(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    scan_result_id = int(params["scan_result_id"])

    # Validate feature exists
    feature = session.get(Feature, feature_id)
    if not feature:
        raise ValueError(f"Feature not found: {feature_id}")

    # Validate scan result exists
    scan_result = session.get(ScanResult, scan_result_id)
    if not scan_result:
        raise ValueError(f"ScanResult not found: {scan_result_id}")

    # Idempotent: check if link already exists
    existing = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature_id,
            FeatureScanResult.scan_result_id == scan_result_id,
        )
    ).first()
    if existing:
        return {
            "success": True,
            "feature_id": feature_id,
            "scan_result_id": scan_result_id,
            "message": (
                f"ScanResult {scan_result_id} is already a member of "
                f"Feature {feature_id}."
            ),
        }

    existing_feature_ids = session.exec(
        select(FeatureScanResult.feature_id).where(FeatureScanResult.scan_result_id == scan_result_id)
    ).all()
    link = replace_result_feature_membership(
        session,
        feature_id=feature_id,
        scan_result=scan_result,
        assignment_source="ai",
        assignment_confidence=1.0,
        is_primary=True,
        membership_type="primary",
    )
    refresh_feature_metadata(
        session,
        feature_ids=[feature_id, *existing_feature_ids],
        commit=False,
    )
    session.commit()
    session.refresh(link)

    return {
        "success": True,
        "feature_id": feature_id,
        "scan_result_id": scan_result_id,
        "link_id": link.id,
        "message": (
            f"Added ScanResult {scan_result_id} to Feature {feature_id}."
        ),
    }


# ── Remove tool ─────────────────────────────────────────────────────

REMOVE_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "feature_id": {
            "type": "integer",
            "description": "ID of the feature to remove the scan result from.",
        },
        "scan_result_id": {
            "type": "integer",
            "description": "ID of the scan result to remove from the feature.",
        },
    },
    "required": ["feature_id", "scan_result_id"],
}


def handle_remove(params: Dict[str, Any], session: Session) -> Dict[str, Any]:
    feature_id = int(params["feature_id"])
    scan_result_id = int(params["scan_result_id"])

    existing = session.exec(
        select(FeatureScanResult).where(
            FeatureScanResult.feature_id == feature_id,
            FeatureScanResult.scan_result_id == scan_result_id,
        )
    ).first()

    if not existing:
        return {
            "success": True,
            "feature_id": feature_id,
            "scan_result_id": scan_result_id,
            "message": (
                f"No membership found for ScanResult {scan_result_id} "
                f"in Feature {feature_id}."
            ),
        }

    affected_feature_ids = [feature_id]
    session.delete(existing)
    refresh_feature_metadata(
        session,
        feature_ids=affected_feature_ids,
        commit=False,
    )
    session.commit()

    return {
        "success": True,
        "feature_id": feature_id,
        "scan_result_id": scan_result_id,
        "message": (
            f"Removed ScanResult {scan_result_id} from Feature {feature_id}."
        ),
    }


# ── ToolSpec exports ────────────────────────────────────────────────

ADD_TOOL_SPEC = ToolSpec(
    name="add_result_to_feature",
    description=(
        "Add a customized scan result to a feature group. "
        "Only modified_ootb and net_new_customer results are accepted. "
        "Idempotent: adding an existing member returns success."
    ),
    input_schema=ADD_INPUT_SCHEMA,
    handler=handle_add,
    permission="write",
)

REMOVE_TOOL_SPEC = ToolSpec(
    name="remove_result_from_feature",
    description=(
        "Remove a scan result from a feature group. "
        "Idempotent: removing a non-member returns success."
    ),
    input_schema=REMOVE_INPUT_SCHEMA,
    handler=handle_remove,
    permission="write",
)
