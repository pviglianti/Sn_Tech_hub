"""Tests for swarm-mode orchestration helpers in connected AI stages."""

import json
from unittest.mock import patch

from src.models import Assessment, AssessmentType, ScanResult
from src.services.ai_analysis_dispatch import (
    _build_batch_stage_instructions,
    _build_claude_command,
    _build_codex_command,
)
from src.services.ai_feature_dispatch import _build_feature_stage_prompt
from src.services.ai_swarm import effective_ai_analysis_batch_size
from src.services.integration_properties import (
    AI_ANALYSIS_BATCH_SIZE,
    AI_ANALYSIS_CLI_TIMEOUT,
    AIFeatureProperties,
    AIRuntimeProperties,
    load_ai_analysis_properties,
    update_integration_properties,
)


def _make_assessment() -> Assessment:
    return Assessment(
        instance_id=1,
        name="Test Assessment",
        number="ASMT001",
        assessment_type=AssessmentType.global_app,
    )


def _make_result(result_id: int, name: str) -> ScanResult:
    return ScanResult(
        id=result_id,
        scan_id=1,
        sys_id=f"sys_{result_id}",
        table_name="sys_script_include",
        name=name,
    )


def test_effective_ai_analysis_batch_size_uses_swarm_width():
    runtime_props = AIRuntimeProperties(execution_strategy="swarm", max_concurrent_sessions=4)
    assert effective_ai_analysis_batch_size(runtime_props, 1) == 4
    assert effective_ai_analysis_batch_size(runtime_props, 6) == 6


def test_load_ai_analysis_properties_reads_batch_size_and_timeout(db_session):
    update_integration_properties(
        db_session,
        {
            AI_ANALYSIS_BATCH_SIZE: "7",
            AI_ANALYSIS_CLI_TIMEOUT: "1200",
        },
    )
    props = load_ai_analysis_properties(db_session)
    assert props.batch_size == 7
    assert props.cli_timeout_seconds == 1200


def test_build_codex_command_swarm_adds_multi_agent_overrides():
    runtime_props = AIRuntimeProperties(execution_strategy="swarm", max_concurrent_sessions=5)
    with patch("src.services.ai_analysis_dispatch.shutil.which", return_value="/usr/bin/codex"):
        cmd = _build_codex_command(
            model_name="gpt-5.4",
            effort_level="high",
            enabled_tools=["update_scan_result"],
            rpc_url="http://127.0.0.1:8080/mcp",
            force_api_login=False,
            runtime_props=runtime_props,
        )
    assert 'features.multi_agent=true' in cmd
    assert "agents.max_threads=5" in cmd
    assert "agents.max_depth=1" in cmd


def test_build_codex_command_single_mode_does_not_add_swarm_overrides():
    runtime_props = AIRuntimeProperties(execution_strategy="single", max_concurrent_sessions=5)
    with patch("src.services.ai_analysis_dispatch.shutil.which", return_value="/usr/bin/codex"):
        cmd = _build_codex_command(
            model_name="gpt-5.4",
            effort_level="high",
            enabled_tools=["update_scan_result"],
            rpc_url="http://127.0.0.1:8080/mcp",
            force_api_login=False,
            runtime_props=runtime_props,
        )
    assert 'features.multi_agent=true' not in cmd
    assert "agents.max_threads=5" not in cmd


def test_build_claude_command_swarm_adds_agents_and_system_prompt():
    runtime_props = AIRuntimeProperties(execution_strategy="swarm", max_concurrent_sessions=3)
    with patch("src.services.ai_analysis_dispatch.shutil.which", return_value="/usr/bin/claude"):
        cmd = _build_claude_command(
            model_name="claude-sonnet-4-6",
            effort_level="high",
            allowed_tools=["mcp__tech-assessment-hub__feature_grouping_status"],
            rpc_url="http://127.0.0.1:8080/mcp",
            runtime_props=runtime_props,
            stage="grouping",
            pass_key="structure",
        )
    assert "--agents" in cmd
    agents_payload = cmd[cmd.index("--agents") + 1]
    parsed_agents = json.loads(agents_payload)
    assert "feature_cluster_analyst" in parsed_agents
    assert "--append-system-prompt" in cmd
    system_prompt = cmd[cmd.index("--append-system-prompt") + 1]
    assert "Swarm mode is enabled" in system_prompt
    assert "Only the coordinator may write feature graph" in system_prompt


def test_build_batch_stage_instructions_adds_swarm_guidance_for_multi_artifact_runs(db_session):
    assessment = _make_assessment()
    runtime_props = AIRuntimeProperties(execution_strategy="swarm", max_concurrent_sessions=2)
    prompt = _build_batch_stage_instructions(
        db_session,
        assessment=assessment,
        rows=[_make_result(1, "A"), _make_result(2, "B")],
        methodology_prompt_text="Methodology block",
        runtime_props=runtime_props,
        provider_kind="openai",
    )
    assert "Multi-Artifact Batch Rules" in prompt
    assert "Swarm Mode" in prompt
    assert "Codex subagents" in prompt
    assert "Delegate up to 2 artifact-scoped workers" in prompt


def test_build_feature_stage_prompt_adds_swarm_guidance_only_when_enabled(db_session):
    assessment = _make_assessment()
    pass_plan_item = {"stage": "grouping", "pass_key": "structure", "label": "Structure"}
    feature_props = AIFeatureProperties(
        pass_plan=[pass_plan_item],
        bucket_taxonomy=[{"key": "bucket_misc", "label": "Misc", "description": "Fallback"}],
    )
    coverage_summary = {
        "in_scope_customized_total": 3,
        "assigned_count": 1,
        "human_standalone_count": 0,
        "unassigned_count": 2,
        "provisional_feature_count": 1,
        "bucket_feature_count": 0,
    }

    single_prompt = _build_feature_stage_prompt(
        db_session,
        assessment=assessment,
        stage="grouping",
        runtime_props=AIRuntimeProperties(execution_strategy="single"),
        provider_kind="anthropic",
        pass_plan_item=pass_plan_item,
        feature_props=feature_props,
        use_registered_prompts=False,
        coverage_summary=coverage_summary,
    )
    swarm_prompt = _build_feature_stage_prompt(
        db_session,
        assessment=assessment,
        stage="grouping",
        runtime_props=AIRuntimeProperties(execution_strategy="swarm", max_concurrent_sessions=4),
        provider_kind="anthropic",
        pass_plan_item=pass_plan_item,
        feature_props=feature_props,
        use_registered_prompts=False,
        coverage_summary=coverage_summary,
    )

    assert "Swarm Mode" not in single_prompt
    assert "Swarm Mode" in swarm_prompt
    assert "Claude agent team" in swarm_prompt
    assert "coordinator is the only agent allowed to mutate the feature graph" in swarm_prompt
