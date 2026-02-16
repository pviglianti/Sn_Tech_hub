"""Tests for the assessment app file options JSON API endpoint.

Covers: schema, data retrieval with pagination/sorting/conditions,
and DataTable.js contract compliance.
"""
import json

import pytest

from src.models import Instance, InstanceAppFileType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def instance_with_file_types(db_session):
    """Create an instance with several InstanceAppFileType rows."""
    inst = Instance(
        name="test-inst",
        url="https://test.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)

    rows = [
        InstanceAppFileType(
            instance_id=inst.id,
            sn_sys_id="aaa111",
            sys_class_name="sys_script",
            name="Business Rule",
            label="Business Rule",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
            type="code",
            source_table_name="sys_script",
            priority=10,
        ),
        InstanceAppFileType(
            instance_id=inst.id,
            sn_sys_id="bbb222",
            sys_class_name="sys_script_include",
            name="Script Include",
            label="Script Include",
            is_available_for_assessment=True,
            is_default_for_assessment=False,
            type="code",
            source_table_name="sys_script_include",
            priority=20,
        ),
        InstanceAppFileType(
            instance_id=inst.id,
            sn_sys_id="ccc333",
            sys_class_name="sys_ui_action",
            name="UI Action",
            label="UI Action",
            is_available_for_assessment=False,
            is_default_for_assessment=False,
            type="ui",
            source_table_name="sys_ui_action",
            priority=30,
        ),
        InstanceAppFileType(
            instance_id=inst.id,
            sn_sys_id="ddd444",
            sys_class_name="sys_dictionary",
            name="Dictionary Entry",
            label="Dictionary Entry",
            is_available_for_assessment=False,
            is_default_for_assessment=False,
            type="metadata",
            source_table_name="sys_dictionary",
            priority=40,
        ),
        InstanceAppFileType(
            instance_id=inst.id,
            sn_sys_id="eee555",
            sys_class_name="sys_ui_policy",
            name="UI Policy",
            label="UI Policy",
            is_available_for_assessment=True,
            is_default_for_assessment=True,
            type="ui",
            source_table_name="sys_ui_policy",
            priority=50,
        ),
    ]
    for row in rows:
        db_session.add(row)
    db_session.commit()
    for row in rows:
        db_session.refresh(row)

    return inst, rows


# ---------------------------------------------------------------------------
# Schema endpoint
# ---------------------------------------------------------------------------

def test_schema_returns_expected_fields(db_session, instance_with_file_types):
    """Schema endpoint returns field definitions matching InstanceAppFileType columns."""
    from src.web.routes.instances import _app_file_options_field_schema

    inst, _ = instance_with_file_types
    schema = _app_file_options_field_schema()

    assert "fields" in schema
    fields = schema["fields"]
    assert len(fields) > 0

    # All fields have required keys
    for f in fields:
        assert "local_column" in f
        assert "column_label" in f
        assert "kind" in f

    # Key columns exist
    col_names = [f["local_column"] for f in fields]
    assert "is_available_for_assessment" in col_names
    assert "is_default_for_assessment" in col_names
    assert "sys_class_name" in col_names
    assert "display_label" in col_names
    assert "name" in col_names
    assert "type" in col_names
    assert "priority" in col_names

    # Boolean fields have kind=boolean
    avail_field = next(f for f in fields if f["local_column"] == "is_available_for_assessment")
    assert avail_field["kind"] == "boolean"
    default_field = next(f for f in fields if f["local_column"] == "is_default_for_assessment")
    assert default_field["kind"] == "boolean"

    # Priority is number
    priority_field = next(f for f in fields if f["local_column"] == "priority")
    assert priority_field["kind"] == "number"


# ---------------------------------------------------------------------------
# Data endpoint
# ---------------------------------------------------------------------------

def test_data_returns_all_rows(db_session, instance_with_file_types):
    """Data endpoint returns all rows for instance with correct total."""
    from src.web.routes.instances import _query_app_file_options_data

    inst, rows = instance_with_file_types
    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=50,
        sort_field=None, sort_dir="asc", conditions=None,
    )

    assert result["total"] == 5
    assert len(result["rows"]) == 5

    # Each row has required fields
    for row_data in result["rows"]:
        assert "id" in row_data
        assert "sys_class_name" in row_data
        assert "display_label" in row_data
        assert "is_available_for_assessment" in row_data
        assert "is_default_for_assessment" in row_data


def test_data_pagination(db_session, instance_with_file_types):
    """Data endpoint supports offset/limit pagination."""
    from src.web.routes.instances import _query_app_file_options_data

    inst, rows = instance_with_file_types
    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=2,
        sort_field="priority", sort_dir="asc", conditions=None,
    )

    assert result["total"] == 5
    assert len(result["rows"]) == 2
    # First two by priority
    assert result["rows"][0]["sys_class_name"] == "sys_script"
    assert result["rows"][1]["sys_class_name"] == "sys_script_include"

    # Page 2
    result2 = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=2, limit=2,
        sort_field="priority", sort_dir="asc", conditions=None,
    )
    assert result2["total"] == 5
    assert len(result2["rows"]) == 2
    assert result2["rows"][0]["sys_class_name"] == "sys_ui_action"


def test_data_sorting_desc(db_session, instance_with_file_types):
    """Data endpoint supports descending sort."""
    from src.web.routes.instances import _query_app_file_options_data

    inst, _ = instance_with_file_types
    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=50,
        sort_field="priority", sort_dir="desc", conditions=None,
    )

    priorities = [r["priority"] for r in result["rows"]]
    assert priorities == sorted(priorities, reverse=True)


def test_data_with_boolean_condition(db_session, instance_with_file_types):
    """Data endpoint filters by ConditionBuilder-style conditions."""
    from src.web.routes.instances import _query_app_file_options_data

    inst, _ = instance_with_file_types
    conditions = {
        "logic": "AND",
        "conditions": [
            {"field": "is_available_for_assessment", "operator": "is true"},
        ],
    }
    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=50,
        sort_field=None, sort_dir="asc", conditions=conditions,
    )

    assert result["total"] == 3
    for row in result["rows"]:
        assert row["is_available_for_assessment"] is True


def test_data_with_string_condition(db_session, instance_with_file_types):
    """Data endpoint filters by string contains condition."""
    from src.web.routes.instances import _query_app_file_options_data

    inst, _ = instance_with_file_types
    conditions = {
        "logic": "AND",
        "conditions": [
            {"field": "type", "operator": "is", "value": "ui"},
        ],
    }
    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=50,
        sort_field=None, sort_dir="asc", conditions=conditions,
    )

    assert result["total"] == 2
    for row in result["rows"]:
        assert row["type"] == "ui"


def test_data_display_label_resolved(db_session, instance_with_file_types):
    """Each row includes a resolved display_label."""
    from src.web.routes.instances import _query_app_file_options_data

    inst, _ = instance_with_file_types
    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=50,
        sort_field=None, sort_dir="asc", conditions=None,
    )

    for row in result["rows"]:
        assert row["display_label"]  # non-empty string
        assert isinstance(row["display_label"], str)


def test_data_empty_instance(db_session):
    """Data endpoint returns empty result for instance with no rows."""
    from src.web.routes.instances import _query_app_file_options_data

    inst = Instance(
        name="empty-inst",
        url="https://empty.service-now.com",
        username="admin",
        password_encrypted="secret",
    )
    db_session.add(inst)
    db_session.commit()
    db_session.refresh(inst)

    result = _query_app_file_options_data(
        db_session, instance_id=inst.id, offset=0, limit=50,
        sort_field=None, sort_dir="asc", conditions=None,
    )

    assert result["total"] == 0
    assert result["rows"] == []
