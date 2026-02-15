import json
from datetime import datetime, timedelta

import pytest

from src.models import (
    Assessment,
    AssessmentState,
    AssessmentType,
    Instance,
    OriginType,
    Scan,
    ScanResult,
    ScanStatus,
    ScanType,
    InstanceAppFileType,
)
from src.server import _query_scan_results_payload, _results_option_app_file_classes


@pytest.fixture()
def results_ctx(db_session):
    """Set up two instances, two assessments, three scans, and scan results."""
    instance_a = Instance(
        name="inst-a",
        url="https://inst-a.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    instance_b = Instance(
        name="inst-b",
        url="https://inst-b.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(instance_a)
    db_session.add(instance_b)
    db_session.commit()
    db_session.refresh(instance_a)
    db_session.refresh(instance_b)

    assessment_a = Assessment(
        number="ASMT0000101",
        name="Assessment A",
        instance_id=instance_a.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        app_file_classes_json=json.dumps(["sys_script", "sys_script_include", "sys_ui_action"]),
    )
    assessment_b = Assessment(
        number="ASMT0000102",
        name="Assessment B",
        instance_id=instance_b.id,
        assessment_type=AssessmentType.global_app,
        state=AssessmentState.in_progress,
        app_file_classes_json=json.dumps(["sys_script"]),
    )
    db_session.add(assessment_a)
    db_session.add(assessment_b)
    db_session.commit()
    db_session.refresh(assessment_a)
    db_session.refresh(assessment_b)

    scan_a1 = Scan(
        assessment_id=assessment_a.id,
        scan_type=ScanType.metadata_index,
        name="Scan A1",
        status=ScanStatus.completed,
        query_params_json=json.dumps({"app_file_class": "sys_script"}),
    )
    scan_a2 = Scan(
        assessment_id=assessment_a.id,
        scan_type=ScanType.metadata_index,
        name="Scan A2",
        status=ScanStatus.completed,
        query_params_json=json.dumps({"app_file_class": "sys_ui_action"}),
    )
    scan_b1 = Scan(
        assessment_id=assessment_b.id,
        scan_type=ScanType.metadata_index,
        name="Scan B1",
        status=ScanStatus.completed,
        query_params_json=json.dumps({"app_file_class": "sys_script"}),
    )
    db_session.add(scan_a1)
    db_session.add(scan_a2)
    db_session.add(scan_b1)
    db_session.commit()
    db_session.refresh(scan_a1)
    db_session.refresh(scan_a2)
    db_session.refresh(scan_b1)

    now = datetime.utcnow()
    db_session.add(
        ScanResult(
            scan_id=scan_a1.id,
            sys_id="sys_a_mod",
            table_name="sys_script",
            name="A Modified",
            origin_type=OriginType.modified_ootb,
            sys_updated_on=now,
        )
    )
    db_session.add(
        ScanResult(
            scan_id=scan_a1.id,
            sys_id="sys_a_oob",
            table_name="sys_script_include",
            name="A OOTB",
            origin_type=OriginType.ootb_untouched,
            sys_updated_on=now - timedelta(minutes=1),
        )
    )
    db_session.add(
        ScanResult(
            scan_id=scan_a2.id,
            sys_id="sys_a_new",
            table_name="sys_ui_action",
            name="A New",
            origin_type=OriginType.net_new_customer,
            sys_updated_on=now - timedelta(minutes=2),
        )
    )
    db_session.add(
        ScanResult(
            scan_id=scan_b1.id,
            sys_id="sys_b_mod",
            table_name="sys_script",
            name="B Modified",
            origin_type=OriginType.modified_ootb,
            sys_updated_on=now - timedelta(minutes=3),
        )
    )

    db_session.add(
        InstanceAppFileType(
            instance_id=instance_a.id,
            sn_sys_id="aft-a-script",
            sys_class_name="sys_script",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=instance_a.id,
            sn_sys_id="aft-a-script-include",
            sys_class_name="sys_script_include",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=instance_a.id,
            sn_sys_id="aft-a-ui-action",
            sys_class_name="sys_ui_action",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=instance_b.id,
            sn_sys_id="aft-b-script",
            sys_class_name="sys_script",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
        )
    )
    db_session.commit()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.session = db_session
    ctx.instance_a = instance_a
    ctx.instance_b = instance_b
    ctx.assessment_a = assessment_a
    ctx.assessment_b = assessment_b
    ctx.scan_a1 = scan_a1
    ctx.scan_a2 = scan_a2
    ctx.scan_b1 = scan_b1
    return ctx


def test_customized_only_filters_out_non_customized(results_ctx):
    payload = _query_scan_results_payload(
        results_ctx.session,
        instance_id=results_ctx.instance_a.id,
        customized_only=True,
        customization_type="all",
        limit=100,
    )

    assert payload["total"] == 2
    names = {row["name"] for row in payload["results"]}
    assert names == {"A Modified", "A New"}


def test_customization_type_filters_single_classification(results_ctx):
    payload = _query_scan_results_payload(
        results_ctx.session,
        instance_id=results_ctx.instance_a.id,
        customized_only=True,
        customization_type="modified_ootb",
        limit=100,
    )

    assert payload["total"] == 1
    assert payload["results"][0]["name"] == "A Modified"


def test_assessment_scan_and_type_filters_cascade(results_ctx):
    payload = _query_scan_results_payload(
        results_ctx.session,
        assessment_ids=[results_ctx.assessment_a.id],
        scan_ids=[results_ctx.scan_a2.id],
        customized_only=False,
        customization_type="all",
        table_names=["sys_ui_action"],
        limit=100,
    )

    assert payload["total"] == 1
    row = payload["results"][0]
    assert row["name"] == "A New"
    assert row["scan"]["id"] == results_ctx.scan_a2.id
    assert row["assessment"]["id"] == results_ctx.assessment_a.id
    assert row["instance"]["id"] == results_ctx.instance_a.id


def test_results_option_classes_follow_assessment_selected_classes(results_ctx):
    classes = _results_option_app_file_classes(
        results_ctx.session,
        instance_id=results_ctx.instance_a.id,
        assessment_ids=[results_ctx.assessment_a.id],
        scan_ids=[],
        customized_only=False,
        customization_type="all",
    )

    assert classes == ["sys_script", "sys_script_include", "sys_ui_action"]


def test_results_option_classes_are_stable_across_customization_scope(results_ctx):
    customized_only_classes = _results_option_app_file_classes(
        results_ctx.session,
        instance_id=results_ctx.instance_a.id,
        assessment_ids=[results_ctx.assessment_a.id],
        scan_ids=[],
        customized_only=True,
        customization_type="all",
    )
    all_results_classes = _results_option_app_file_classes(
        results_ctx.session,
        instance_id=results_ctx.instance_a.id,
        assessment_ids=[results_ctx.assessment_a.id],
        scan_ids=[],
        customized_only=False,
        customization_type="all",
    )

    assert customized_only_classes == all_results_classes


def test_results_option_classes_remove_values_not_in_instance_table(results_ctx):
    results_ctx.assessment_a.app_file_classes_json = json.dumps(["sys_script", "sys_ui_action", "x_missing"])
    results_ctx.session.add(results_ctx.assessment_a)
    results_ctx.session.commit()

    classes = _results_option_app_file_classes(
        results_ctx.session,
        instance_id=results_ctx.instance_a.id,
        assessment_ids=[results_ctx.assessment_a.id],
        scan_ids=[],
        customized_only=False,
        customization_type="all",
    )

    assert classes == ["sys_script", "sys_ui_action"]
