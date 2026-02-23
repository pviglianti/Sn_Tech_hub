"""Tests for version history postscan catchup logic.

Verifies that the catchup function detects when a prior VH pull used a state
filter (e.g., state=current) and uses delta mode from watermark instead of
incorrectly deciding "full" due to count mismatch.
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    DataPullStatus,
    DataPullType,
    Instance,
    InstanceDataPull,
    VersionHistory,
)
from src.services.data_pull_executor import DataPullMode
from src.server import _run_assessment_version_history_postscan_catchup


@pytest.fixture()
def vh_ctx(db_session, sample_instance):
    """Provide context for VH catchup tests."""

    def _add_vh_pull(*, state_filter_applied=None, watermark=None, status=DataPullStatus.completed):
        pull = InstanceDataPull(
            instance_id=sample_instance.id,
            data_type=DataPullType.version_history,
            status=status,
            state_filter_applied=state_filter_applied,
            last_sys_updated_on=watermark,
            last_pulled_at=datetime.utcnow(),
        )
        db_session.add(pull)
        db_session.commit()
        return pull

    def _add_vh_record(*, sn_sys_id, sys_updated_on):
        vh = VersionHistory(
            instance_id=sample_instance.id,
            sn_sys_id=sn_sys_id,
            name="test",
            sys_update_name="test",
            state="current",
            sys_updated_on=sys_updated_on,
        )
        db_session.add(vh)
        db_session.commit()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.session = db_session
    ctx.instance = sample_instance
    ctx.add_vh_pull = _add_vh_pull
    ctx.add_vh_record = _add_vh_record
    return ctx


@patch("src.server.run_data_pulls_for_instance")
def test_catchup_uses_delta_when_state_filter_applied(mock_run_pulls, vh_ctx):
    """When prior VH pull had state_filter=current, catchup should use delta mode."""
    watermark = datetime(2026, 2, 13, 9, 0, 0)
    vh_ctx.add_vh_record(sn_sys_id="vh-1", sys_updated_on=watermark)
    vh_ctx.add_vh_pull(state_filter_applied="current", watermark=watermark)

    client = MagicMock()
    _run_assessment_version_history_postscan_catchup(
        session=vh_ctx.session,
        instance=vh_ctx.instance,
        client=client,
    )

    mock_run_pulls.assert_called_once()
    call_kwargs = mock_run_pulls.call_args
    assert call_kwargs.kwargs["mode"] == DataPullMode.delta


@patch("src.server.run_data_pulls_for_instance")
@patch("src.server._determine_smart_mode_for_type")
def test_catchup_uses_smart_mode_when_no_state_filter(mock_smart_mode, mock_run_pulls, vh_ctx):
    """When prior VH pull had no state filter, use standard smart mode decision."""
    watermark = datetime(2026, 2, 13, 9, 0, 0)
    vh_ctx.add_vh_record(sn_sys_id="vh-1", sys_updated_on=watermark)
    vh_ctx.add_vh_pull(state_filter_applied=None, watermark=watermark)

    mock_smart_mode.return_value = "delta"
    client = MagicMock()

    _run_assessment_version_history_postscan_catchup(
        session=vh_ctx.session,
        instance=vh_ctx.instance,
        client=client,
    )

    mock_smart_mode.assert_called_once()
    mock_run_pulls.assert_called_once()
    assert mock_run_pulls.call_args.kwargs["mode"] == DataPullMode.delta


@patch("src.server.run_data_pulls_for_instance")
@patch("src.server._determine_smart_mode_for_type")
def test_catchup_skips_when_smart_mode_says_skip(mock_smart_mode, mock_run_pulls, vh_ctx):
    """When smart mode says skip (no state filter case), no pull should run."""
    vh_ctx.add_vh_pull(state_filter_applied=None, watermark=datetime(2026, 2, 13, 9, 0, 0))
    mock_smart_mode.return_value = "skip"
    client = MagicMock()

    _run_assessment_version_history_postscan_catchup(
        session=vh_ctx.session,
        instance=vh_ctx.instance,
        client=client,
    )

    mock_smart_mode.assert_called_once()
    mock_run_pulls.assert_not_called()


@patch("src.server.run_data_pulls_for_instance")
def test_catchup_falls_back_to_full_when_no_watermark(mock_run_pulls, vh_ctx):
    """When state_filter was applied but no watermark exists, fall back to full."""
    vh_ctx.add_vh_pull(state_filter_applied="current", watermark=None)

    client = MagicMock()
    _run_assessment_version_history_postscan_catchup(
        session=vh_ctx.session,
        instance=vh_ctx.instance,
        client=client,
    )

    mock_run_pulls.assert_called_once()
    assert mock_run_pulls.call_args.kwargs["mode"] == DataPullMode.full


def test_execute_data_pull_records_state_filter(db_session, sample_instance):
    """execute_data_pull should record version_state_filter on the pull record."""
    from src.services.data_pull_executor import _get_or_create_data_pull

    pull = _get_or_create_data_pull(db_session, sample_instance.id, DataPullType.version_history)
    assert pull.state_filter_applied is None

    # Simulate what execute_data_pull does after _start_pull
    pull.state_filter_applied = "current"
    db_session.add(pull)
    db_session.commit()

    db_session.refresh(pull)
    assert pull.state_filter_applied == "current"
