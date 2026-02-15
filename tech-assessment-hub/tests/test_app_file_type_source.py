import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from starlette.requests import Request

from src.models import AppFileClass, Instance, InstanceAppFileType
from src.server import (
    _assessment_file_class_options,
    _default_selected_file_classes,
    _preserve_unavailable_selected_file_classes,
    _set_instance_app_file_type_assessment_flags,
    instance_assessment_app_file_options_page,
)
from src.services.data_pull_executor import _default_assessment_availability, _fetch_app_file_class_names


def test_fetch_metadata_class_names_prefers_instance_cached_types(db_session, sample_instance):
    db_session.add(
        AppFileClass(
            sys_class_name="sys_script",
            label="Business Rule",
            is_active=True,
            is_important=True,
            display_order=10,
        )
    )
    db_session.add(
        AppFileClass(
            sys_class_name="sys_ui_action",
            label="UI Action",
            is_active=True,
            is_important=True,
            display_order=20,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="sys_script",
            label="Business Rule",
            priority=10,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-2",
            sys_class_name="x_custom_file_type",
            label="Custom File Type",
            priority=20,
        )
    )
    db_session.commit()

    classes = _fetch_app_file_class_names(db_session, instance_id=sample_instance.id)

    assert "sys_script" in classes
    assert "x_custom_file_type" in classes
    assert "sys_ui_action" not in classes


def test_assessment_class_options_use_cached_table_with_seeded_defaults(db_session, sample_instance):
    db_session.add(
        AppFileClass(
            sys_class_name="sys_script",
            label="Business Rule",
            is_active=True,
            is_important=True,
            display_order=10,
        )
    )
    db_session.add(
        AppFileClass(
            sys_class_name="sys_ui_action",
            label="UI Action",
            is_active=True,
            is_important=False,
            display_order=20,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="sys_script",
            label="Business Rule",
            priority=1,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-2",
            sys_class_name="x_custom_file_type",
            label="Custom File Type",
            priority=2,
        )
    )
    db_session.commit()

    options = _assessment_file_class_options(db_session, sample_instance.id)
    option_map = {row["sys_class_name"]: row for row in options}

    assert "sys_script" in option_map
    assert "x_custom_file_type" in option_map
    assert option_map["sys_script"]["is_important"] is True
    assert option_map["x_custom_file_type"]["is_important"] is False


def test_default_selected_classes_use_instance_table_availability(db_session, sample_instance):
    db_session.add(
        AppFileClass(
            sys_class_name="sys_script",
            label="Business Rule",
            is_active=True,
            is_important=True,
            display_order=10,
        )
    )
    db_session.add(
        AppFileClass(
            sys_class_name="sys_ui_action",
            label="UI Action",
            is_active=True,
            is_important=False,
            display_order=20,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="sys_script",
            label="Business Rule",
            priority=1,
            is_default_for_assessment=True,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-2",
            sys_class_name="sys_ui_action",
            label="UI Action",
            priority=2,
            is_default_for_assessment=False,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-3",
            sys_class_name="x_custom_file_type",
            label="Custom File Type",
            priority=3,
            is_default_for_assessment=True,
        )
    )
    db_session.commit()

    defaults = _default_selected_file_classes(db_session, sample_instance.id)

    assert defaults == ["sys_script", "x_custom_file_type"]


def test_assessment_options_and_class_names_ignore_disabled_instance_rows(db_session, sample_instance):
    db_session.add(
        AppFileClass(
            sys_class_name="sys_script",
            label="Business Rule",
            is_active=True,
            is_important=True,
            display_order=10,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="sys_script",
            label="Business Rule",
            priority=1,
            is_available_for_assessment=True,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-2",
            sys_class_name="x_kmf_signature",
            label="KMF Signature Records",
            priority=2,
            is_available_for_assessment=False,
        )
    )
    db_session.commit()

    options = _assessment_file_class_options(db_session, sample_instance.id)
    option_names = {row["sys_class_name"] for row in options}
    pulled_class_names = _fetch_app_file_class_names(db_session, instance_id=sample_instance.id)

    assert "sys_script" in option_names
    assert "x_kmf_signature" not in option_names
    assert "sys_script" in pulled_class_names
    assert "x_kmf_signature" not in pulled_class_names


def test_assessment_class_options_humanize_label_when_source_label_missing(db_session, sample_instance):
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="cmn_map_page",
            label=None,
            name=None,
            priority=1,
            is_available_for_assessment=True,
        )
    )
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-2",
            sys_class_name="ci_identifier",
            label=None,
            name="ci_identifier",
            priority=2,
            is_available_for_assessment=True,
        )
    )
    db_session.commit()

    options = _assessment_file_class_options(db_session, sample_instance.id)
    option_map = {row["sys_class_name"]: row for row in options}

    assert "cmn_map_page" in option_map
    assert option_map["cmn_map_page"]["label"] == "CMN Map Page"
    assert "ci_identifier" in option_map
    assert option_map["ci_identifier"]["label"] == "CI Identifier"


def test_default_assessment_availability_uses_baseline_catalog():
    assert _default_assessment_availability("sys_script", "KMF Signature Records", None) is False
    assert _default_assessment_availability("sys_script", None, "kmf helper file") is False
    assert _default_assessment_availability("sys_script", "Business Rule", "sys_script") is True
    assert _default_assessment_availability("sys_ui_macro", "UI Macro", "sys_ui_macro") is False
    assert _default_assessment_availability("x_custom_file_type", "Custom Type", "x_custom_file_type") is False


def test_set_instance_app_file_type_assessment_flags_updates_single_row(db_session, sample_instance):
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="sys_script",
            label="Business Rule",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
        )
    )
    db_session.commit()

    row = db_session.exec(
        select(InstanceAppFileType).where(InstanceAppFileType.instance_id == sample_instance.id)
    ).first()
    assert row is not None

    updated = _set_instance_app_file_type_assessment_flags(
        db_session,
        instance_id=sample_instance.id,
        app_file_type_id=row.id,
        is_available_for_assessment=False,
    )

    assert updated is not None
    assert updated.is_available_for_assessment is False
    assert updated.is_default_for_assessment is False


def test_set_instance_app_file_type_assessment_flags_can_enable_default_and_availability(db_session, sample_instance):
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-1",
            sys_class_name="sys_script",
            label="Business Rule",
            is_available_for_assessment=False,
            is_default_for_assessment=False,
        )
    )
    db_session.commit()

    row = db_session.exec(
        select(InstanceAppFileType).where(InstanceAppFileType.instance_id == sample_instance.id)
    ).first()
    assert row is not None

    updated = _set_instance_app_file_type_assessment_flags(
        db_session,
        instance_id=sample_instance.id,
        app_file_type_id=row.id,
        is_default_for_assessment=True,
    )

    assert updated is not None
    assert updated.is_available_for_assessment is True
    assert updated.is_default_for_assessment is True


def test_set_instance_app_file_type_assessment_flags_ignores_other_instances(db_session, sample_instance):
    other_instance = Instance(
        name="inst-b",
        url="https://inst-b.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(other_instance)
    db_session.commit()
    db_session.refresh(other_instance)

    db_session.add(
        InstanceAppFileType(
            instance_id=other_instance.id,
            sn_sys_id="aft-2",
            sys_class_name="sys_ui_action",
            label="UI Action",
            is_available_for_assessment=True,
        )
    )
    db_session.commit()

    other_row = db_session.exec(
        select(InstanceAppFileType).where(InstanceAppFileType.instance_id == other_instance.id)
    ).first()
    assert other_row is not None

    updated = _set_instance_app_file_type_assessment_flags(
        db_session,
        instance_id=sample_instance.id,
        app_file_type_id=other_row.id,
        is_available_for_assessment=False,
    )

    assert updated is None


def test_preserve_unavailable_selected_file_classes_keeps_hidden_existing_values():
    merged = _preserve_unavailable_selected_file_classes(
        submitted_class_names=["sys_script"],
        existing_class_names=["sys_script", "x_kmf_signature"],
        available_options=[{"sys_class_name": "sys_script"}],
    )
    assert merged == ["sys_script", "x_kmf_signature"]


def test_instance_app_file_type_requires_unique_sn_sys_id_per_instance(db_session, sample_instance):
    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-unique",
            sys_class_name="sys_script",
            label="Business Rule",
        )
    )
    db_session.commit()

    db_session.add(
        InstanceAppFileType(
            instance_id=sample_instance.id,
            sn_sys_id="aft-unique",
            sys_class_name="sys_ui_action",
            label="UI Action",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_assessment_app_file_options_page_auto_syncs_rows_when_empty(db_session, sample_instance):
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    def _fake_sync(session, instance, mode="smart"):
        assert instance.id == sample_instance.id
        session.add(
            InstanceAppFileType(
                instance_id=instance.id,
                sn_sys_id="aft-auto-1",
                sys_class_name="sys_script",
                label="Business Rule",
                is_available_for_assessment=True,
            )
        )
        session.commit()
        return "full"

    with patch("src.server._sync_app_file_types_for_instance", side_effect=_fake_sync) as sync_mock:
        response = asyncio.run(
            instance_assessment_app_file_options_page(
                request=request,
                instance_id=sample_instance.id,
                session=db_session,
            )
        )

    context = response.context
    assert context["auto_sync_status"] == "completed"
    assert context["auto_sync_message"] is None
    assert len(context["app_file_types"]) == 1
    assert context["available_count"] == 1
    sync_mock.assert_called_once()


def test_assessment_app_file_options_page_reports_auto_sync_failure(db_session, sample_instance):
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    with patch("src.server._sync_app_file_types_for_instance", side_effect=RuntimeError("sync failed")) as sync_mock:
        response = asyncio.run(
            instance_assessment_app_file_options_page(
                request=request,
                instance_id=sample_instance.id,
                session=db_session,
            )
        )

    context = response.context
    assert context["auto_sync_status"] == "failed"
    assert "sync failed" in context["auto_sync_message"]
    assert context["app_file_types"] == []
    assert context["available_count"] == 0
    sync_mock.assert_called_once()
