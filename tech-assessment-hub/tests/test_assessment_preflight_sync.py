from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    DataPullStatus,
    DataPullType,
    Instance,
    InstanceDataPull,
    UpdateSet,
)
from src.server import _build_assessment_preflight_plan


@pytest.fixture()
def preflight_ctx(db_session, sample_instance):
    """Provide common context for preflight tests."""
    now = datetime.utcnow()

    def _add_update_set(*, sys_updated_on=None):
        row = UpdateSet(
            instance_id=sample_instance.id,
            sn_sys_id="us-1",
            name="Default",
            sys_updated_on=sys_updated_on or (now - timedelta(minutes=30)),
        )
        db_session.add(row)
        db_session.commit()

    def _set_pull(*, status: DataPullStatus, last_pulled_at: Optional[datetime]):
        pull = InstanceDataPull(
            instance_id=sample_instance.id,
            data_type=DataPullType.update_sets,
            status=status,
            last_pulled_at=last_pulled_at,
        )
        db_session.add(pull)
        db_session.commit()

    class Ctx:
        pass

    ctx = Ctx()
    ctx.session = db_session
    ctx.instance_id = sample_instance.id
    ctx.now = now
    ctx.add_update_set = _add_update_set
    ctx.set_pull = _set_pull
    return ctx


def test_empty_cache_plans_full_pull(preflight_ctx):
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
    )
    assert plan["full"] == [DataPullType.update_sets]
    assert plan["delta"] == []
    assert plan["fresh"] == []
    assert plan["skip"] == []


def test_cached_without_last_pull_plans_delta(preflight_ctx):
    """Data in cache but no pull record → delta (has watermark from data, trust it)."""
    preflight_ctx.add_update_set()
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
    )
    assert plan["full"] == []
    assert plan["delta"] == [DataPullType.update_sets]
    assert plan["fresh"] == []
    assert plan["skip"] == []


def test_cached_with_stale_pull_plans_delta(preflight_ctx):
    """Data in cache with stale pull record → delta (has watermark + sync history)."""
    preflight_ctx.add_update_set()
    preflight_ctx.set_pull(
        status=DataPullStatus.completed,
        last_pulled_at=preflight_ctx.now - timedelta(hours=3),
    )
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
    )
    assert plan["full"] == []
    assert plan["delta"] == [DataPullType.update_sets]
    assert plan["fresh"] == []
    assert plan["skip"] == []


def test_cached_with_recent_pull_uses_probes_not_freshness(preflight_ctx):
    """No time-based freshness gate — always delegates to resolve_delta_decision.

    Without a client (no probes), the function falls through to delta
    because a watermark exists and probe data is unavailable.
    """
    preflight_ctx.add_update_set()
    preflight_ctx.set_pull(
        status=DataPullStatus.completed,
        last_pulled_at=preflight_ctx.now - timedelta(minutes=3),
    )
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
    )
    assert plan["full"] == []
    assert plan["delta"] == [DataPullType.update_sets]
    assert plan["fresh"] == []
    assert plan["skip"] == []


def test_running_pull_is_skipped_to_avoid_overlap(preflight_ctx):
    preflight_ctx.add_update_set()
    preflight_ctx.set_pull(
        status=DataPullStatus.running,
        last_pulled_at=preflight_ctx.now - timedelta(minutes=60),
    )
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
    )
    assert plan["full"] == []
    assert plan["delta"] == []
    assert plan["fresh"] == []
    assert plan["skip"] == [DataPullType.update_sets]


@patch("src.server._estimate_expected_total")
def test_incomplete_cache_probe_positive_gap_too_large_uses_full(mock_estimate, preflight_ctx):
    """When local=1, remote=500, delta_probe=10 → 1+10 < 500 → full (delta won't close gap)."""
    preflight_ctx.add_update_set()  # 1 local record
    preflight_ctx.set_pull(
        status=DataPullStatus.completed,
        last_pulled_at=preflight_ctx.now - timedelta(hours=3),
    )
    # First call: remote total = 500, second call: delta probe = 10
    mock_estimate.side_effect = [500, 10]
    client = MagicMock()
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
        client=client,
    )
    assert plan["full"] == [DataPullType.update_sets]
    assert plan["delta"] == []
    assert "full" in plan["decisions"]["update_sets"]


@patch("src.server._estimate_expected_total")
def test_incomplete_cache_probe_zero_triggers_full(mock_estimate, preflight_ctx):
    """When local=1, remote=500, delta_probe=0 → no updates + count mismatch → full."""
    preflight_ctx.add_update_set()  # 1 local record
    preflight_ctx.set_pull(
        status=DataPullStatus.completed,
        last_pulled_at=preflight_ctx.now - timedelta(hours=3),
    )
    # First call: remote total = 500, second call: delta probe = 0
    mock_estimate.side_effect = [500, 0]
    client = MagicMock()
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
        client=client,
    )
    assert plan["full"] == [DataPullType.update_sets]
    assert plan["delta"] == []
    assert "full" in plan["decisions"]["update_sets"]


@patch("src.server._estimate_expected_total")
def test_delta_probe_can_close_gap_stays_delta(mock_estimate, preflight_ctx):
    """When probe count >= gap, delta will close the gap → delta."""
    preflight_ctx.add_update_set()  # 1 local record
    preflight_ctx.set_pull(
        status=DataPullStatus.completed,
        last_pulled_at=preflight_ctx.now - timedelta(hours=3),
    )
    # First call: remote total = 10, second call: delta probe = 15 (>= gap of 9)
    mock_estimate.side_effect = [10, 15]
    client = MagicMock()
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
        client=client,
    )
    assert plan["full"] == []
    assert plan["delta"] == [DataPullType.update_sets]
    assert "delta" in plan["decisions"]["update_sets"]


@patch("src.server._estimate_expected_total")
def test_complete_cache_with_no_updates_skips(mock_estimate, preflight_ctx):
    """When local matches remote and delta probe = 0 → skip."""
    preflight_ctx.add_update_set()  # 1 local record
    preflight_ctx.set_pull(
        status=DataPullStatus.completed,
        last_pulled_at=preflight_ctx.now - timedelta(hours=3),
    )
    # First call: remote total = 1 (matches local), second call: delta probe = 0
    mock_estimate.side_effect = [1, 0]
    client = MagicMock()
    plan = _build_assessment_preflight_plan(
        session=preflight_ctx.session,
        instance_id=preflight_ctx.instance_id,
        stale_minutes=10,
        data_types=[DataPullType.update_sets],
        client=client,
    )
    assert plan["full"] == []
    assert plan["delta"] == []
    assert plan["fresh"] == [DataPullType.update_sets]
    assert "fresh" in plan["decisions"]["update_sets"]
