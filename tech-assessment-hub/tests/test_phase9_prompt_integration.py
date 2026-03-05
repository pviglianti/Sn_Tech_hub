"""Phase 9 prompt integration tests for pipeline stage handlers."""

from unittest.mock import patch
import json

from sqlmodel import select

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Feature,
    FeatureScanResult,
    GeneralRecommendation,
    Instance,
    OriginType,
    PipelineStage,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
)
from src.services.integration_properties import PipelinePromptProperties


def _seed_base_assessment(
    db_session,
    *,
    stage: str,
    number: str = "ASMTP90001",
):
    inst = Instance(
        name="prompt-inst",
        url="https://prompt-test.service-now.com",
        username="admin",
        password_encrypted="encrypted",
    )
    db_session.add(inst)
    db_session.flush()

    asmt = Assessment(
        instance_id=inst.id,
        name="Prompt Integration Test",
        number=number,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        pipeline_stage=stage,
    )
    db_session.add(asmt)
    db_session.flush()

    scan = Scan(
        assessment_id=asmt.id,
        scan_type=ScanType.metadata,
        name="prompt-scan",
        status=ScanStatus.completed,
    )
    db_session.add(scan)
    db_session.flush()
    return inst, asmt, scan


def _seed_refinement_feature_with_members(db_session, *, asmt: Assessment, scan: Scan):
    feature = Feature(
        assessment_id=asmt.id,
        name="Prompt Feature",
        description="feature for prompt integration test",
    )
    db_session.add(feature)
    db_session.flush()

    members = []
    for idx in range(5):
        sr = ScanResult(
            scan_id=scan.id,
            sys_id=f"prompt_refine_sr_{idx}",
            table_name="sys_script_include",
            name=f"Refine Artifact {idx}",
            origin_type=OriginType.modified_ootb,
            ai_observations=json.dumps({"seeded": True}),
        )
        db_session.add(sr)
        db_session.flush()
        members.append(sr)
        db_session.add(
            FeatureScanResult(
                feature_id=feature.id,
                scan_result_id=sr.id,
                is_primary=(idx == 0),
                assignment_source="engine",
            )
        )
    db_session.commit()
    return feature, members


def test_ai_analysis_uses_registered_prompt_when_enabled(db_session, db_engine):
    _, asmt, scan = _seed_base_assessment(
        db_session,
        stage=PipelineStage.ai_analysis.value,
        number="ASMTP90011",
    )
    sr = ScanResult(
        scan_id=scan.id,
        sys_id="prompt_sr_1",
        table_name="sys_script_include",
        name="Prompt Artifact",
        origin_type=OriginType.modified_ootb,
    )
    db_session.add(sr)
    db_session.commit()
    db_session.refresh(sr)

    mock_ctx = {
        "artifact": {"name": sr.name, "table_name": sr.table_name},
        "references": [{"resolved": True}, {"resolved": False}],
        "human_context": {"observations": None, "disposition": None, "features": []},
        "has_local_table_data": True,
        "update_sets": [{"name": "US1"}],
    }
    mock_prompt = {
        "messages": [{"role": "user", "content": {"type": "text", "text": "artifact prompt context"}}]
    }

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine), \
        patch("src.server._set_assessment_pipeline_job_state"), \
        patch("src.server._set_assessment_pipeline_stage"), \
        patch("src.server.gather_artifact_context", return_value=mock_ctx), \
        patch(
            "src.server.load_pipeline_prompt_properties",
            return_value=PipelinePromptProperties(use_registered_prompts=True),
        ), \
        patch("src.server.PROMPT_REGISTRY.get_prompt", return_value=mock_prompt) as mock_get_prompt:
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_analysis")

    db_session.refresh(sr)
    parsed = json.loads(sr.ai_observations or "{}")
    assert parsed.get("artifact_name") == sr.name
    assert parsed.get("registered_prompt") == "artifact_analyzer"
    assert parsed.get("prompt_context") == "artifact prompt context"
    assert mock_get_prompt.call_count >= 1


def test_ai_refinement_uses_registered_prompts_when_enabled(db_session, db_engine):
    _, asmt, scan = _seed_base_assessment(
        db_session,
        stage=PipelineStage.ai_refinement.value,
        number="ASMTP90012",
    )
    feature, members = _seed_refinement_feature_with_members(
        db_session,
        asmt=asmt,
        scan=scan,
    )

    def _prompt_side_effect(name, arguments, session=None):
        if name == "relationship_tracer":
            text = "relationship tracer context"
        elif name == "technical_architect" and arguments.get("result_id"):
            text = "technical architect mode A context"
        elif name == "technical_architect":
            text = "technical architect mode B context"
        else:
            text = "unknown prompt"
        return {"messages": [{"role": "user", "content": {"type": "text", "text": text}}]}

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine), \
        patch("src.server._set_assessment_pipeline_job_state"), \
        patch("src.server._set_assessment_pipeline_stage"), \
        patch(
            "src.server.load_pipeline_prompt_properties",
            return_value=PipelinePromptProperties(use_registered_prompts=True),
        ), \
        patch("src.server.PROMPT_REGISTRY.get_prompt", side_effect=_prompt_side_effect):
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    db_session.refresh(feature)
    feature_summary = json.loads(feature.ai_summary or "{}")
    assert feature_summary.get("registered_prompt") == "relationship_tracer"
    assert "relationship tracer context" in feature_summary.get("prompt_context", "")

    first_member = db_session.get(ScanResult, members[0].id)
    first_obs = json.loads(first_member.ai_observations or "{}")
    technical_review = first_obs.get("technical_review") or {}
    assert technical_review.get("registered_prompt") == "technical_architect"
    assert "mode A" in technical_review.get("prompt_context", "")

    rollup = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "technical_findings")
    ).first()
    assert rollup is not None
    rollup_data = json.loads(rollup.description or "{}")
    assert rollup_data.get("registered_prompt") == "technical_architect"
    assert "mode B" in rollup_data.get("prompt_context", "")


def test_ai_refinement_skips_registered_prompts_when_disabled(db_session, db_engine):
    _, asmt, scan = _seed_base_assessment(
        db_session,
        stage=PipelineStage.ai_refinement.value,
        number="ASMTP90014",
    )
    feature, members = _seed_refinement_feature_with_members(
        db_session,
        asmt=asmt,
        scan=scan,
    )

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine), \
        patch("src.server._set_assessment_pipeline_job_state"), \
        patch("src.server._set_assessment_pipeline_stage"), \
        patch(
            "src.server.load_pipeline_prompt_properties",
            return_value=PipelinePromptProperties(use_registered_prompts=False),
        ), \
        patch("src.server.PROMPT_REGISTRY.get_prompt") as mock_get_prompt:
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    mock_get_prompt.assert_not_called()

    db_session.refresh(feature)
    feature_summary = json.loads(feature.ai_summary or "{}")
    assert "registered_prompt" not in feature_summary
    assert "registered_prompt_error" not in feature_summary

    first_member = db_session.get(ScanResult, members[0].id)
    first_obs = json.loads(first_member.ai_observations or "{}")
    technical_review = first_obs.get("technical_review") or {}
    assert "registered_prompt" not in technical_review
    assert "registered_prompt_error" not in technical_review

    rollup = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "technical_findings")
    ).first()
    assert rollup is not None
    rollup_data = json.loads(rollup.description or "{}")
    assert "registered_prompt" not in rollup_data
    assert "registered_prompt_error" not in rollup_data


def test_ai_refinement_records_prompt_errors_when_not_registered(db_session, db_engine):
    _, asmt, scan = _seed_base_assessment(
        db_session,
        stage=PipelineStage.ai_refinement.value,
        number="ASMTP90015",
    )
    feature, members = _seed_refinement_feature_with_members(
        db_session,
        asmt=asmt,
        scan=scan,
    )

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine), \
        patch("src.server._set_assessment_pipeline_job_state"), \
        patch("src.server._set_assessment_pipeline_stage"), \
        patch(
            "src.server.load_pipeline_prompt_properties",
            return_value=PipelinePromptProperties(use_registered_prompts=True),
        ), \
        patch("src.server.PROMPT_REGISTRY.has_prompt", return_value=False), \
        patch("src.server.PROMPT_REGISTRY.get_prompt") as mock_get_prompt:
        _run_assessment_pipeline_stage(asmt.id, target_stage="ai_refinement")

    mock_get_prompt.assert_not_called()

    db_session.refresh(feature)
    feature_summary = json.loads(feature.ai_summary or "{}")
    assert feature_summary.get("registered_prompt_error") == "Prompt not registered: relationship_tracer"

    first_member = db_session.get(ScanResult, members[0].id)
    first_obs = json.loads(first_member.ai_observations or "{}")
    technical_review = first_obs.get("technical_review") or {}
    assert technical_review.get("registered_prompt_error") == "Prompt not registered: technical_architect"

    rollup = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "technical_findings")
    ).first()
    assert rollup is not None
    rollup_data = json.loads(rollup.description or "{}")
    assert rollup_data.get("registered_prompt_error") == "Prompt not registered: technical_architect"


def test_report_stage_uses_registered_prompt_when_enabled(db_session, db_engine):
    _, asmt, scan = _seed_base_assessment(
        db_session,
        stage=PipelineStage.report.value,
        number="ASMTP90013",
    )
    db_session.add(
        ScanResult(
            scan_id=scan.id,
            sys_id="prompt_report_sr_1",
            table_name="sys_script_include",
            name="Report Artifact",
            origin_type=OriginType.modified_ootb,
        )
    )
    db_session.commit()

    mock_prompt = {
        "messages": [{"role": "user", "content": {"type": "text", "text": "report writer context"}}]
    }

    from src.server import _run_assessment_pipeline_stage

    with patch("src.server.engine", db_engine), \
        patch("src.server._set_assessment_pipeline_job_state"), \
        patch("src.server._set_assessment_pipeline_stage"), \
        patch(
            "src.server.load_pipeline_prompt_properties",
            return_value=PipelinePromptProperties(use_registered_prompts=True),
        ), \
        patch("src.server.PROMPT_REGISTRY.get_prompt", return_value=mock_prompt):
        _run_assessment_pipeline_stage(asmt.id, target_stage="report")

    report_row = db_session.exec(
        select(GeneralRecommendation)
        .where(GeneralRecommendation.assessment_id == asmt.id)
        .where(GeneralRecommendation.category == "assessment_report")
    ).first()
    assert report_row is not None
    report_payload = json.loads(report_row.description or "{}")
    assert report_payload.get("registered_prompt") == "report_writer"
    assert report_payload.get("prompt_context") == "report writer context"
