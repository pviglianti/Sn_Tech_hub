"""Phase 9/10 tests for process recommendations UI APIs and report exports."""

import json
from urllib.parse import quote

from src.models import (
    Assessment,
    AssessmentRuntimeUsage,
    AssessmentState,
    AssessmentType,
    GeneralRecommendation,
    Instance,
    PipelineStage,
    Severity,
)


def _seed_assessment(db_session, *, number: str = "ASMTP90101"):
    inst = Instance(
        name="exports-inst",
        url="https://exports-test.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Exports / Process Recs",
        number=number,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=PipelineStage.report.value,
    )
    db_session.add(asmt)
    db_session.commit()
    db_session.refresh(asmt)
    return inst, asmt


def test_process_recommendations_schema_and_records(client, db_session):
    _, asmt = _seed_assessment(db_session, number="ASMTP90111")
    db_session.add_all(
        [
            GeneralRecommendation(
                assessment_id=asmt.id,
                title="Tech Rollup",
                category="technical_findings",
                severity=Severity.high,
                created_by="ai_pipeline",
                description="excluded technical",
            ),
            GeneralRecommendation(
                assessment_id=asmt.id,
                title="Landscape",
                category="landscape_summary",
                created_by="ai_pipeline",
                description="excluded landscape",
            ),
            GeneralRecommendation(
                assessment_id=asmt.id,
                title="Process Improvement",
                category="process",
                severity=Severity.medium,
                created_by="ai_pipeline",
                description="included process",
            ),
            GeneralRecommendation(
                assessment_id=asmt.id,
                title="Governance Gap",
                category="governance",
                severity=Severity.low,
                created_by="ai_pipeline",
                description="included governance",
            ),
        ]
    )
    db_session.commit()

    schema_resp = client.get(f"/api/assessments/{asmt.id}/process-recommendations/field-schema")
    assert schema_resp.status_code == 200, schema_resp.text
    schema = schema_resp.json()
    assert schema["table"] == "assessment_process_recommendations"
    assert any(field["local_column"] == "title" for field in schema["fields"])

    rows_resp = client.get(
        f"/api/assessments/{asmt.id}/process-recommendations/records?offset=0&limit=50&sort_field=title&sort_dir=asc"
    )
    assert rows_resp.status_code == 200, rows_resp.text
    payload = rows_resp.json()
    assert payload["total"] == 2
    titles = [row["title"] for row in payload["rows"]]
    assert titles == sorted(titles)

    cond = quote(json.dumps({"logic": "AND", "conditions": [{"field": "category", "operator": "is", "value": "process"}]}))
    filtered_resp = client.get(
        f"/api/assessments/{asmt.id}/process-recommendations/records?offset=0&limit=50&conditions={cond}"
    )
    assert filtered_resp.status_code == 200, filtered_resp.text
    filtered = filtered_resp.json()
    assert filtered["total"] == 1
    assert filtered["rows"][0]["category"] == "process"


def test_assessment_summary_page_renders(client, db_session):
    inst, asmt = _seed_assessment(db_session, number="ASMTP90114")
    db_session.add(
        AssessmentRuntimeUsage(
            assessment_id=asmt.id,
            instance_id=inst.id,
            assessment_number=asmt.number,
            assessment_name=asmt.name,
            instance_name=inst.name,
            assessment_state=asmt.state.value,
            llm_runtime_mode="local_subscription",
            llm_provider="openai",
            llm_model="gpt-5-mini",
            llm_total_tokens=12345,
            estimated_cost_usd=1.23,
            total_results=25,
            customized_results=8,
            total_features=3,
        )
    )
    db_session.commit()

    resp = client.get("/assessments/summary")
    assert resp.status_code == 200, resp.text
    assert "Assessment Summary" in resp.text
    assert asmt.number in resp.text
