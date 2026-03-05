"""Tests for assessment runtime usage telemetry service + routes."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    FeatureRecommendation,
    FeatureScanResult,
    GeneralRecommendation,
    OriginType,
    Scan,
    ScanResult,
    ScanType,
)
from src.services.assessment_runtime_usage import refresh_assessment_runtime_usage


def _seed_assessment_with_results(db_session: Session, instance_id: int) -> Assessment:
    assessment = Assessment(
        number="ASMT-RUNTIME-0001",
        name="Runtime Usage Seed",
        instance_id=instance_id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        started_at=datetime.utcnow() - timedelta(minutes=15),
        completed_at=datetime.utcnow(),
    )
    db_session.add(assessment)
    db_session.commit()
    db_session.refresh(assessment)

    scan = Scan(
        assessment_id=assessment.id,
        scan_type=ScanType.metadata,
        name="Metadata Scan",
    )
    db_session.add(scan)
    db_session.commit()
    db_session.refresh(scan)

    customized = ScanResult(
        scan_id=scan.id,
        sys_id="customized_sys_id",
        table_name="sys_script",
        name="Customized BR",
        origin_type=OriginType.modified_ootb,
    )
    untouched = ScanResult(
        scan_id=scan.id,
        sys_id="untouched_sys_id",
        table_name="sys_script_include",
        name="Untouched SI",
        origin_type=OriginType.ootb_untouched,
    )
    db_session.add(customized)
    db_session.add(untouched)
    db_session.commit()
    db_session.refresh(customized)

    feature = Feature(
        assessment_id=assessment.id,
        name="Legacy Approval Feature",
    )
    db_session.add(feature)
    db_session.commit()
    db_session.refresh(feature)

    db_session.add(
        FeatureScanResult(
            feature_id=feature.id,
            scan_result_id=customized.id,
            assignment_source="engine",
        )
    )
    db_session.add(
        FeatureRecommendation(
            instance_id=instance_id,
            assessment_id=assessment.id,
            feature_id=feature.id,
            recommendation_type="replace_with_ootb",
            rationale="Consolidate to OOTB capability.",
        )
    )
    db_session.add(
        GeneralRecommendation(
            assessment_id=assessment.id,
            title="General Technical Debt",
            category="technical_findings",
            description="Refactor duplicated BR logic.",
            created_by="test",
        )
    )
    db_session.commit()
    return assessment


def test_refresh_assessment_runtime_usage_builds_snapshot(db_session: Session, sample_instance):
    assessment = _seed_assessment_with_results(db_session, sample_instance.id)

    row = refresh_assessment_runtime_usage(
        db_session,
        assessment.id,
        mcp_calls_local_delta=3,
        mcp_calls_servicenow_delta=4,
        mcp_calls_local_db_delta=2,
        llm_input_tokens_delta=1000,
        llm_output_tokens_delta=250,
        estimated_cost_usd_delta=1.23,
        last_event="test:runtime:update",
        details={"source": "unit_test"},
        commit=True,
    )

    assert row is not None
    assert row.assessment_id == assessment.id
    assert row.total_results == 2
    assert row.customized_results == 1
    assert row.total_features == 1
    assert row.total_groupings == 1
    assert row.total_feature_memberships == 1
    assert row.total_general_recommendations == 1
    assert row.total_feature_recommendations == 1
    assert row.total_technical_recommendations == 2
    assert row.mcp_calls_local == 3
    assert row.mcp_calls_servicenow == 4
    assert row.mcp_calls_local_db == 2
    assert row.llm_input_tokens == 1000
    assert row.llm_output_tokens == 250
    assert row.llm_total_tokens == 1250
    assert abs(float(row.estimated_cost_usd) - 1.23) < 1e-6
    assert row.run_duration_seconds is not None
    assert row.last_event == "test:runtime:update"
    assert row.llm_runtime_mode in {"api", "local", "local_subscription"}


def test_runtime_usage_link_is_on_integration_properties_page(client: TestClient):
    response = client.get("/integration-properties")
    assert response.status_code == 200
    assert "/integration-properties/assessment-runtime-usage" in response.text
    assert "/integration-properties/ai-setup" in response.text


def test_ai_setup_wizard_page_renders(client: TestClient):
    response = client.get("/integration-properties/ai-setup")
    assert response.status_code == 200
    assert "AI Setup Wizard" in response.text
    assert "Step 3: Local Bridge Launcher" in response.text
    assert "Step 4: Start AI Pipeline Stage" in response.text


def test_runtime_usage_page_and_api_require_admin_token_when_configured(
    client: TestClient,
    db_session: Session,
    sample_instance,
    monkeypatch,
):
    _seed_assessment_with_results(db_session, sample_instance.id)
    monkeypatch.setenv("TECH_ASSESSMENT_MCP_ADMIN_TOKEN", "runtime-secret")

    page_response = client.get("/integration-properties/assessment-runtime-usage")
    assert page_response.status_code == 200
    assert "Assessment Runtime Usage" in page_response.text

    denied = client.get("/api/integration-properties/assessment-runtime-usage/records")
    assert denied.status_code == 403

    allowed = client.get(
        "/api/integration-properties/assessment-runtime-usage/records?admin_token=runtime-secret"
    )
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["total"] >= 1
    assert isinstance(payload.get("rows"), list)
