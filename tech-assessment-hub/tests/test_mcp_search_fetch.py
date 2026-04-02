import json

from src.mcp.protocol.jsonrpc import handle_request
from src.models import (
    Assessment,
    AssessmentType,
    Feature,
    FeatureScanResult,
    GeneralRecommendation,
    Instance,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)


def _request(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def _seed_assessment_graph(db_session):
    instance = Instance(
        name="DEV",
        url="https://acme.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)

    assessment = Assessment(
        number="ASMT0001001",
        name="Service Portal Modernization",
        instance_id=instance.id,
        assessment_type=AssessmentType.platform_global,
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.script_includes,
        name="Script Includes",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    result = ScanResult(
        scan_id=scan.id,
        sys_id="abc123",
        table_name="sys_script_include",
        name="LegacyHeartbeat",
        display_value="LegacyHeartbeat",
        sys_scope="global",
        recommendation="Refactor this heartbeat integration before upgrade.",
        observations="Used by the service portal and upgrade-sensitive.",
        ai_summary="This script include coordinates the legacy heartbeat flow.",
    )
    db_session.add(result)
    db_session.commit()
    db_session.refresh(result)

    feature = Feature(
        assessment_id=assessment.id,
        name="Heartbeat Integration",
        description="Handles the legacy heartbeat path used by the portal.",
        recommendation="Replace with an event-driven integration.",
    )
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(feature)

    db_session.add(
        FeatureScanResult(
            feature_id=feature.id,
            scan_result_id=result.id,
            is_primary=True,
        )
    )

    db_session.add(
        GeneralRecommendation(
            assessment_id=assessment.id,
            title="Portal heartbeat modernization",
            category="assessment_report",
            description="The portal heartbeat flow should be modernized before the next upgrade cycle.",
        )
    )
    db_session.commit()
    return instance, assessment, result, feature


def test_tools_list_includes_search_fetch_with_annotations(db_session):
    result = handle_request(_request("tools/list"), db_session)
    tools = {tool["name"]: tool for tool in result["result"]["tools"]}

    assert "search" in tools
    assert "fetch" in tools
    assert tools["search"]["inputSchema"]["required"] == ["query"]
    assert tools["fetch"]["inputSchema"]["required"] == ["id"]
    assert tools["search"]["annotations"]["readOnlyHint"] is True


def test_search_and_fetch_use_text_content_shape(db_session):
    _, assessment, scan_result, feature = _seed_assessment_graph(db_session)

    search_response = handle_request(
        _request("tools/call", {"name": "search", "arguments": {"query": "heartbeat modernization"}}),
        db_session,
    )

    content = search_response["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"

    payload = json.loads(content[0]["text"])
    ids = [item["id"] for item in payload["results"]]
    assert f"scan_result:{scan_result.id}" in ids
    assert f"feature:{feature.id}" in ids
    assert any(item["title"].startswith(assessment.number) for item in payload["results"])

    fetch_response = handle_request(
        _request("tools/call", {"name": "fetch", "arguments": {"id": f"scan_result:{scan_result.id}"}}),
        db_session,
    )
    fetch_content = fetch_response["result"]["content"]
    assert len(fetch_content) == 1
    assert fetch_content[0]["type"] == "text"

    fetch_payload = json.loads(fetch_content[0]["text"])
    assert fetch_payload["id"] == f"scan_result:{scan_result.id}"
    assert "LegacyHeartbeat" in fetch_payload["text"]
    assert fetch_payload["metadata"]["document_type"] == "scan_result"
    assert fetch_payload["url"].startswith("https://acme.service-now.com/")


def test_existing_tools_still_return_json_content(db_session):
    instance = Instance(
        name="QA",
        url="https://qa.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)

    response = handle_request(
        _request("tools/call", {"name": "get_instance_summary", "arguments": {"instance_id": instance.id}}),
        db_session,
    )

    content = response["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "json"
    assert content[0]["json"]["success"] is True
    assert content[0]["json"]["instance"]["id"] == instance.id
