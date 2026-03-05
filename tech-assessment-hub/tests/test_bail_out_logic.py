"""Tests for bail-out logic in data_pull_executor.py (Task 3).

Verifies:
- All 11 _pull_* handlers accept bail-out parameters
- All 11 _dispatch_* functions pass through bail-out parameters
- Dual-signal bail-out fires when both count AND content gates are met
- Bail-out does NOT fire when only count gate is met (content gate unsatisfied)
- Bail-out does NOT fire when only content gate is met (count gate unsatisfied)
- Safety cap fires independently of bail-out
- Bail-out is skipped on first-time load (local_count_pre == 0)
- Orphan cleanup is skipped when bail-out fires
- execute_data_pull loads properties and populates telemetry columns
- order_desc parameter flows through to client calls
"""
import inspect
import json
import uuid
from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.models import (
    Instance, InstanceDataPull, DataPullType, DataPullStatus,
    UpdateSet, InstancePlugin,
)
from src.services.data_pull_executor import (
    _pull_update_sets,
    _pull_plugins,
    _dispatch_update_sets,
    _dispatch_plugins,
    execute_data_pull,
    _get_local_cached_count,
    DATA_PULL_SPECS,
)
from src.services.sn_client import ServiceNowClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PULL_HANDLER_NAMES = [
    "_pull_update_sets",
    "_pull_customer_update_xml",
    "_pull_version_history",
    "_pull_metadata_customizations",
    "_pull_app_file_types",
    "_pull_plugins",
    "_pull_plugin_view",
    "_pull_scopes",
    "_pull_packages",
    "_pull_applications",
    "_pull_sys_db_object",
]

DISPATCH_NAMES = [
    "_dispatch_update_sets",
    "_dispatch_customer_update_xml",
    "_dispatch_version_history",
    "_dispatch_metadata_customization",
    "_dispatch_app_file_types",
    "_dispatch_plugins",
    "_dispatch_plugin_view",
    "_dispatch_scopes",
    "_dispatch_packages",
    "_dispatch_applications",
    "_dispatch_sys_db_object",
]

BAIL_PARAMS = ["order_desc", "bail_threshold", "max_records", "remote_count", "local_count_pre"]


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session = Session(db_engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def sample_instance(db_session):
    instance = Instance(
        name="test",
        url="https://example.service-now.com",
        username="admin",
        password_encrypted="not-a-real-secret",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance


def _make_pull(db_session, instance_id, data_type=DataPullType.update_sets):
    """Create and return a minimal InstanceDataPull record."""
    pull = InstanceDataPull(
        instance_id=instance_id,
        data_type=data_type,
        status=DataPullStatus.running,
    )
    db_session.add(pull)
    db_session.commit()
    db_session.refresh(pull)
    return pull


def _make_sn_record(sys_id, name="test", state="complete", sys_updated_on="2026-01-01 00:00:00"):
    """Create a fake SN API record dict."""
    return {
        "sys_id": sys_id,
        "name": name,
        "state": state,
        "sys_updated_on": sys_updated_on,
        "sys_mod_count": "1",
    }


def _make_plugin_record(sys_id, plugin_id="com.test", name="Test Plugin", active="true"):
    """Create a fake SN plugin record dict."""
    return {
        "sys_id": sys_id,
        "plugin_id": plugin_id,
        "name": name,
        "active": active,
        "state": "active",
        "version": "1.0",
        "sys_updated_on": "2026-01-01 00:00:00",
    }


def _mock_client():
    """Create a mock ServiceNowClient."""
    return MagicMock(spec=ServiceNowClient)


# ---------------------------------------------------------------------------
# Signature tests: All handlers/dispatchers accept bail-out params
# ---------------------------------------------------------------------------


class TestBailOutSignatures:
    """Verify that all handlers and dispatchers declare bail-out parameters."""

    def test_all_pull_handlers_accept_bail_params(self):
        """All 11 _pull_* handlers must accept order_desc, bail_threshold,
        max_records, remote_count, local_count_pre."""
        import src.services.data_pull_executor as executor

        missing = {}
        for name in PULL_HANDLER_NAMES:
            func = getattr(executor, name)
            sig = inspect.signature(func)
            not_found = [p for p in BAIL_PARAMS if p not in sig.parameters]
            if not_found:
                missing[name] = not_found

        assert not missing, f"Missing bail-out params: {missing}"

    def test_all_dispatch_functions_accept_bail_params(self):
        """All 11 _dispatch_* functions must accept bail-out keyword args."""
        import src.services.data_pull_executor as executor

        missing = {}
        for name in DISPATCH_NAMES:
            func = getattr(executor, name)
            sig = inspect.signature(func)
            not_found = [p for p in BAIL_PARAMS if p not in sig.parameters]
            if not_found:
                missing[name] = not_found

        assert not missing, f"Missing bail-out params in dispatch: {missing}"

    def test_all_pull_handlers_default_bail_threshold_zero(self):
        """bail_threshold must default to 0 in all handlers."""
        import src.services.data_pull_executor as executor

        wrong = []
        for name in PULL_HANDLER_NAMES:
            func = getattr(executor, name)
            sig = inspect.signature(func)
            param = sig.parameters.get("bail_threshold")
            if param is None or param.default != 0:
                wrong.append(name)

        assert not wrong, f"bail_threshold not defaulting to 0: {wrong}"

    def test_all_pull_handlers_default_order_desc_false(self):
        """order_desc must default to False in all handlers."""
        import src.services.data_pull_executor as executor

        wrong = []
        for name in PULL_HANDLER_NAMES:
            func = getattr(executor, name)
            sig = inspect.signature(func)
            param = sig.parameters.get("order_desc")
            if param is None or param.default is not False:
                wrong.append(name)

        assert not wrong, f"order_desc not defaulting to False: {wrong}"


# ---------------------------------------------------------------------------
# Dispatch pass-through tests
# ---------------------------------------------------------------------------


class TestDispatchPassThrough:
    """Verify dispatch functions pass bail-out params to underlying handlers."""

    def test_dispatch_update_sets_passes_bail_params(self):
        """_dispatch_update_sets must relay bail-out kwargs to _pull_update_sets."""
        calls = []

        def fake_pull(*args, **kwargs):
            calls.append(kwargs)
            return (0, None)

        with patch("src.services.data_pull_executor._pull_update_sets", side_effect=fake_pull):
            _dispatch_update_sets(
                MagicMock(), 1, MagicMock(), None, "full", None, None,
                order_desc=True,
                bail_threshold=50,
                max_records=5000,
                remote_count=100,
                local_count_pre=80,
            )

        assert calls, "Expected _pull_update_sets to be called"
        assert calls[0]["order_desc"] is True
        assert calls[0]["bail_threshold"] == 50
        assert calls[0]["max_records"] == 5000
        assert calls[0]["remote_count"] == 100
        assert calls[0]["local_count_pre"] == 80

    def test_dispatch_plugins_passes_bail_params(self):
        """_dispatch_plugins must relay bail-out kwargs to _pull_plugins."""
        calls = []

        def fake_pull(*args, **kwargs):
            calls.append(kwargs)
            return (0, None)

        with patch("src.services.data_pull_executor._pull_plugins", side_effect=fake_pull):
            _dispatch_plugins(
                MagicMock(), 1, MagicMock(), None, "delta", None, None,
                order_desc=True,
                bail_threshold=25,
                max_records=3000,
                remote_count=200,
                local_count_pre=190,
            )

        assert calls
        assert calls[0]["order_desc"] is True
        assert calls[0]["bail_threshold"] == 25


# ---------------------------------------------------------------------------
# Dual-signal bail-out tests
# ---------------------------------------------------------------------------


class TestDualSignalBailOut:
    """Core bail-out logic in _pull_update_sets (representative handler)."""

    def test_bail_fires_when_both_gates_met(self, db_session, sample_instance):
        """Bail fires when local >= remote AND consecutive_unchanged >= threshold."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed 5 existing records with identical field values
        for i in range(5):
            us = UpdateSet(
                instance_id=sample_instance.id,
                sn_sys_id=f"us-{i}",
                name=f"US {i}",
                state="complete",
                sys_updated_on=datetime(2026, 1, 1),
                sys_mod_count="1",
            )
            db_session.add(us)
        db_session.commit()

        # Client returns the SAME 5 records unchanged in a single batch
        batch = [
            _make_sn_record(f"us-{i}", name=f"US {i}", state="complete")
            for i in range(5)
        ]
        client.pull_update_sets.return_value = iter([batch])

        # Mock _get_local_cached_count to return 5 (>= remote_count=5)
        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=5,
        ):
            records, _ = _pull_update_sets(
                db_session, sample_instance.id, client, None, "full", pull,
                order_desc=True,
                bail_threshold=3,  # need 3 consecutive unchanged
                max_records=0,
                remote_count=5,  # local (5) >= remote (5) satisfies count gate
                local_count_pre=5,
            )

        db_session.refresh(pull)
        assert pull.bail_out_reason == "count_and_content_gate"
        assert pull.bail_unchanged_at_exit >= 3

    def test_bail_does_not_fire_when_only_count_gate_met(self, db_session, sample_instance):
        """Bail must NOT fire if count gate is met but content gate is not."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed 3 records, but they will be DIFFERENT from remote
        for i in range(3):
            us = UpdateSet(
                instance_id=sample_instance.id,
                sn_sys_id=f"us-{i}",
                name=f"OLD NAME {i}",  # different from what remote sends
                state="new",
                sys_updated_on=datetime(2025, 1, 1),
                sys_mod_count="0",
            )
            db_session.add(us)
        db_session.commit()

        # Remote returns 3 records with CHANGED field values
        batch = [
            _make_sn_record(f"us-{i}", name=f"NEW NAME {i}", state="complete")
            for i in range(3)
        ]
        client.pull_update_sets.return_value = iter([batch])

        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=3,
        ):
            records, _ = _pull_update_sets(
                db_session, sample_instance.id, client, None, "full", pull,
                order_desc=True,
                bail_threshold=3,
                max_records=0,
                remote_count=3,  # count gate satisfied
                local_count_pre=3,
            )

        db_session.refresh(pull)
        # Bail should NOT fire because content gate is not met (records changed)
        assert pull.bail_out_reason is None
        assert pull.bail_unchanged_at_exit == 0

    def test_bail_does_not_fire_when_only_content_gate_met(self, db_session, sample_instance):
        """Bail must NOT fire if content gate is met but count gate is not."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed 3 records with identical content
        for i in range(3):
            us = UpdateSet(
                instance_id=sample_instance.id,
                sn_sys_id=f"us-{i}",
                name=f"US {i}",
                state="complete",
                sys_updated_on=datetime(2026, 1, 1),
                sys_mod_count="1",
            )
            db_session.add(us)
        db_session.commit()

        batch = [
            _make_sn_record(f"us-{i}", name=f"US {i}", state="complete")
            for i in range(3)
        ]
        client.pull_update_sets.return_value = iter([batch])

        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=3,
        ):
            records, _ = _pull_update_sets(
                db_session, sample_instance.id, client, None, "full", pull,
                order_desc=True,
                bail_threshold=3,
                max_records=0,
                remote_count=10,  # count gate NOT satisfied (3 < 10)
                local_count_pre=3,
            )

        db_session.refresh(pull)
        # Bail should NOT fire because count gate fails
        assert pull.bail_out_reason is None

    def test_safety_cap_fires_independently(self, db_session, sample_instance):
        """Safety cap fires regardless of bail-out gates."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # 10 new records across 2 batches of 5
        batch1 = [_make_sn_record(f"new-{i}") for i in range(5)]
        batch2 = [_make_sn_record(f"new-{i+5}") for i in range(5)]
        client.pull_update_sets.return_value = iter([batch1, batch2])

        records, _ = _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
            order_desc=True,
            bail_threshold=0,  # bail disabled
            max_records=5,  # safety cap at 5
            remote_count=100,
            local_count_pre=0,
        )

        db_session.refresh(pull)
        assert pull.bail_out_reason == "safety_cap"
        assert records == 5

    def test_bail_skipped_on_first_load(self, db_session, sample_instance):
        """Bail-out is skipped when local_count_pre == 0 (first-time load)."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        batch = [_make_sn_record(f"us-{i}") for i in range(3)]
        client.pull_update_sets.return_value = iter([batch])

        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=3,
        ):
            records, _ = _pull_update_sets(
                db_session, sample_instance.id, client, None, "full", pull,
                order_desc=True,
                bail_threshold=1,  # would fire if enabled
                max_records=0,
                remote_count=3,
                local_count_pre=0,  # first-time load -> bail disabled
            )

        db_session.refresh(pull)
        # Bail should NOT fire because local_count_pre == 0
        assert pull.bail_out_reason is None
        assert records == 3

    def test_orphan_cleanup_skipped_on_bail(self, db_session, sample_instance):
        """Orphan cleanup must be skipped when bail-out fires in full mode."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed an "orphan" record that would normally be cleaned
        orphan = UpdateSet(
            instance_id=sample_instance.id,
            sn_sys_id="orphan-1",
            name="Orphan",
            sync_batch_id="old-batch-id",
        )
        db_session.add(orphan)
        # Pre-seed records that will match
        for i in range(3):
            us = UpdateSet(
                instance_id=sample_instance.id,
                sn_sys_id=f"us-{i}",
                name=f"US {i}",
                state="complete",
                sys_updated_on=datetime(2026, 1, 1),
                sys_mod_count="1",
            )
            db_session.add(us)
        db_session.commit()

        batch = [
            _make_sn_record(f"us-{i}", name=f"US {i}", state="complete")
            for i in range(3)
        ]
        client.pull_update_sets.return_value = iter([batch])

        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=4,  # includes orphan
        ):
            _pull_update_sets(
                db_session, sample_instance.id, client, None, "full", pull,
                order_desc=True,
                bail_threshold=3,
                max_records=0,
                remote_count=4,
                local_count_pre=4,
            )

        db_session.refresh(pull)
        assert pull.bail_out_reason == "count_and_content_gate"

        # Orphan should still exist because cleanup was skipped
        orphan_check = db_session.exec(
            select(UpdateSet)
            .where(UpdateSet.instance_id == sample_instance.id)
            .where(UpdateSet.sn_sys_id == "orphan-1")
        ).first()
        assert orphan_check is not None, "Orphan should NOT be cleaned when bail fires"

    def test_orphan_cleanup_runs_on_normal_completion(self, db_session, sample_instance):
        """Orphan cleanup must run when pull completes normally (no bail)."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed an orphan
        orphan = UpdateSet(
            instance_id=sample_instance.id,
            sn_sys_id="orphan-1",
            name="Orphan",
            sync_batch_id="old-batch-id",
        )
        db_session.add(orphan)
        db_session.commit()

        # Pull returns 1 new record
        batch = [_make_sn_record("us-new")]
        client.pull_update_sets.return_value = iter([batch])

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
            bail_threshold=0,  # bail disabled
        )

        db_session.refresh(pull)
        assert pull.bail_out_reason is None

        # Orphan should be cleaned up
        orphan_check = db_session.exec(
            select(UpdateSet)
            .where(UpdateSet.instance_id == sample_instance.id)
            .where(UpdateSet.sn_sys_id == "orphan-1")
        ).first()
        assert orphan_check is None, "Orphan should be cleaned on normal completion"


# ---------------------------------------------------------------------------
# order_desc flow-through test
# ---------------------------------------------------------------------------


class TestOrderDescFlowThrough:
    """Verify order_desc passes from handler to client calls."""

    def test_order_desc_true_passed_to_client(self, db_session, sample_instance):
        """order_desc=True must be forwarded to client.pull_update_sets."""
        client = _mock_client()
        client.pull_update_sets.return_value = iter([])
        pull = _make_pull(db_session, sample_instance.id)

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
            order_desc=True,
        )

        client.pull_update_sets.assert_called_once()
        _, kwargs = client.pull_update_sets.call_args
        assert kwargs.get("order_desc") is True

    def test_order_desc_false_passed_to_client(self, db_session, sample_instance):
        """order_desc=False must be forwarded to client.pull_update_sets."""
        client = _mock_client()
        client.pull_update_sets.return_value = iter([])
        pull = _make_pull(db_session, sample_instance.id)

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
            order_desc=False,
        )

        client.pull_update_sets.assert_called_once()
        _, kwargs = client.pull_update_sets.call_args
        assert kwargs.get("order_desc") is False


# ---------------------------------------------------------------------------
# Change detection tests
# ---------------------------------------------------------------------------


class TestChangeDetection:
    """Verify upsert change detection logic."""

    def test_new_records_reset_consecutive_unchanged(self, db_session, sample_instance):
        """New inserts must reset consecutive_unchanged to 0."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # All new records
        batch = [_make_sn_record(f"new-{i}") for i in range(5)]
        client.pull_update_sets.return_value = iter([batch])

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
            bail_threshold=2, local_count_pre=1, remote_count=5,
        )

        db_session.refresh(pull)
        # bail_unchanged_at_exit should be 0 since all are new inserts
        assert pull.bail_unchanged_at_exit == 0

    def test_changed_records_reset_consecutive_unchanged(self, db_session, sample_instance):
        """Records with changed fields must reset the counter."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed with old values
        us = UpdateSet(
            instance_id=sample_instance.id,
            sn_sys_id="us-1",
            name="OLD",
            state="new",
            sys_updated_on=datetime(2025, 1, 1),
            sys_mod_count="0",
        )
        db_session.add(us)
        db_session.commit()

        # Remote sends different values
        batch = [_make_sn_record("us-1", name="NEW", state="complete")]
        client.pull_update_sets.return_value = iter([batch])

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "delta", pull,
            bail_threshold=1, local_count_pre=1, remote_count=1,
        )

        db_session.refresh(pull)
        assert pull.bail_unchanged_at_exit == 0

    def test_unchanged_records_increment_counter(self, db_session, sample_instance):
        """Records with identical fields must increment consecutive_unchanged."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed records with values matching what remote will send
        for i in range(3):
            us = UpdateSet(
                instance_id=sample_instance.id,
                sn_sys_id=f"us-{i}",
                name=f"US {i}",
                state="complete",
                sys_updated_on=datetime(2026, 1, 1),
                sys_mod_count="1",
            )
            db_session.add(us)
        db_session.commit()

        batch = [
            _make_sn_record(f"us-{i}", name=f"US {i}", state="complete")
            for i in range(3)
        ]
        client.pull_update_sets.return_value = iter([batch])

        # Don't satisfy count gate so bail won't fire; just check counter
        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=3,
        ):
            _pull_update_sets(
                db_session, sample_instance.id, client, None, "delta", pull,
                bail_threshold=100,  # high so bail doesn't fire
                local_count_pre=3,
                remote_count=100,  # count gate won't be met
            )

        db_session.refresh(pull)
        assert pull.bail_unchanged_at_exit == 3


# ---------------------------------------------------------------------------
# execute_data_pull telemetry & property-loading tests
# ---------------------------------------------------------------------------


def _make_fake_spec(handler_fn):
    """Create a non-frozen mock DataPullSpec with the given handler."""
    spec = MagicMock()
    spec.pull_handler = handler_fn
    return spec


class TestExecuteDataPullTelemetry:
    """Verify execute_data_pull loads properties and sets telemetry columns."""

    def test_telemetry_columns_populated(self, db_session, sample_instance):
        """execute_data_pull must populate local_count_pre_pull, remote_count_at_probe,
        and local_count_post_pull on the pull record."""
        client = _mock_client()

        with patch(
            "src.services.data_pull_executor.load_pull_order_desc",
            return_value=True,
        ), patch(
            "src.services.data_pull_executor.load_pull_max_records",
            return_value=5000,
        ), patch(
            "src.services.data_pull_executor.load_pull_bail_unchanged_run",
            return_value=50,
        ), patch(
            "src.services.data_pull_executor._estimate_expected_total",
            return_value=100,
        ), patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=90,
        ), patch(
            "src.services.data_pull_executor.get_data_pull_spec",
            return_value=_make_fake_spec(lambda *a, **kw: (0, None)),
        ):
            pull = execute_data_pull(
                db_session, sample_instance, client,
                DataPullType.update_sets, mode="full",
            )

        assert pull.local_count_pre_pull == 90
        assert pull.remote_count_at_probe == 100
        assert pull.local_count_post_pull == 90  # mock always returns 90

    def test_properties_loaded_and_passed(self, db_session, sample_instance):
        """execute_data_pull must load order_desc, max_records, bail_threshold
        from properties and pass to handler."""
        client = _mock_client()
        handler_calls = []

        def capturing_handler(*args, **kwargs):
            handler_calls.append(kwargs)
            return (0, None)

        with patch(
            "src.services.data_pull_executor.load_pull_order_desc",
            return_value=True,
        ), patch(
            "src.services.data_pull_executor.load_pull_max_records",
            return_value=7500,
        ), patch(
            "src.services.data_pull_executor.load_pull_bail_unchanged_run",
            return_value=42,
        ), patch(
            "src.services.data_pull_executor._estimate_expected_total",
            return_value=200,
        ), patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=150,
        ), patch(
            "src.services.data_pull_executor.get_data_pull_spec",
            return_value=_make_fake_spec(capturing_handler),
        ):
            execute_data_pull(
                db_session, sample_instance, client,
                DataPullType.update_sets, mode="full",
            )

        assert handler_calls, "Expected handler to be called"
        kw = handler_calls[0]
        assert kw["order_desc"] is True
        assert kw["bail_threshold"] == 42
        assert kw["max_records"] == 7500
        assert kw["remote_count"] == 200
        assert kw["local_count_pre"] == 150

    def test_delta_probe_count_populated(self, db_session, sample_instance):
        """In delta mode, delta_probe_count should be set from _resolve_delta_pull_mode."""
        client = _mock_client()

        with patch(
            "src.services.data_pull_executor.load_pull_order_desc",
            return_value=False,
        ), patch(
            "src.services.data_pull_executor.load_pull_max_records",
            return_value=5000,
        ), patch(
            "src.services.data_pull_executor.load_pull_bail_unchanged_run",
            return_value=50,
        ), patch(
            "src.services.data_pull_executor._get_db_derived_watermark",
            return_value=datetime(2026, 1, 1),
        ), patch(
            "src.services.data_pull_executor._resolve_delta_pull_mode",
            return_value=("delta", datetime(2026, 1, 1), "probe decision", 100, 200, 55),
        ), patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=100,
        ), patch(
            "src.services.data_pull_executor._estimate_expected_total",
            return_value=30,
        ), patch(
            "src.services.data_pull_executor.get_data_pull_spec",
            return_value=_make_fake_spec(lambda *a, **kw: (0, None)),
        ):
            pull = execute_data_pull(
                db_session, sample_instance, client,
                DataPullType.update_sets, mode="delta",
            )

        assert pull.delta_probe_count == 55
        assert pull.remote_count_at_probe == 200


# ---------------------------------------------------------------------------
# Bail-out telemetry on pull record
# ---------------------------------------------------------------------------


class TestBailOutTelemetryOnPull:
    """Verify that bail_out_reason and bail_unchanged_at_exit are set correctly."""

    def test_no_bail_reason_on_normal_completion(self, db_session, sample_instance):
        """bail_out_reason stays None when pull completes normally."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        batch = [_make_sn_record("us-1")]
        client.pull_update_sets.return_value = iter([batch])

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
        )

        db_session.refresh(pull)
        assert pull.bail_out_reason is None

    def test_bail_reason_set_on_count_content_gate(self, db_session, sample_instance):
        """bail_out_reason must be 'count_and_content_gate' when both gates fire."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        # Pre-seed identical records
        for i in range(2):
            us = UpdateSet(
                instance_id=sample_instance.id,
                sn_sys_id=f"us-{i}",
                name=f"US {i}",
                state="complete",
                sys_updated_on=datetime(2026, 1, 1),
                sys_mod_count="1",
            )
            db_session.add(us)
        db_session.commit()

        batch = [
            _make_sn_record(f"us-{i}", name=f"US {i}", state="complete")
            for i in range(2)
        ]
        client.pull_update_sets.return_value = iter([batch])

        with patch(
            "src.services.data_pull_executor._get_local_cached_count",
            return_value=2,
        ):
            _pull_update_sets(
                db_session, sample_instance.id, client, None, "full", pull,
                bail_threshold=2, remote_count=2, local_count_pre=2,
            )

        db_session.refresh(pull)
        assert pull.bail_out_reason == "count_and_content_gate"
        assert pull.bail_unchanged_at_exit >= 2

    def test_bail_reason_set_on_safety_cap(self, db_session, sample_instance):
        """bail_out_reason must be 'safety_cap' when max_records exceeded."""
        client = _mock_client()
        pull = _make_pull(db_session, sample_instance.id)

        batch = [_make_sn_record(f"us-{i}") for i in range(10)]
        client.pull_update_sets.return_value = iter([batch])

        _pull_update_sets(
            db_session, sample_instance.id, client, None, "full", pull,
            max_records=3,
        )

        db_session.refresh(pull)
        assert pull.bail_out_reason == "safety_cap"
