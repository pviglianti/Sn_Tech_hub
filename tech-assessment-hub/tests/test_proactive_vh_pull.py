"""Tests for proactive VH pull + event signaling (Item 2)."""

import threading
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from src.server import (
    _get_or_create_vh_event,
    _clear_vh_event,
    _is_vh_pull_active,
    _start_proactive_vh_pull,
    _VH_EVENTS,
    _VH_EVENTS_LOCK,
)


@pytest.fixture(autouse=True)
def _clean_vh_events():
    """Ensure the VH events registry is clean before/after each test."""
    with _VH_EVENTS_LOCK:
        _VH_EVENTS.clear()
    yield
    with _VH_EVENTS_LOCK:
        _VH_EVENTS.clear()


# ── Event registry tests ──


def test_get_or_create_vh_event_creates_new():
    """Creates a new Event for an instance that doesn't have one."""
    event = _get_or_create_vh_event(42)
    assert isinstance(event, threading.Event)
    assert not event.is_set()


def test_get_or_create_vh_event_returns_existing():
    """Returns the same Event for repeated calls with the same instance_id."""
    event1 = _get_or_create_vh_event(42)
    event2 = _get_or_create_vh_event(42)
    assert event1 is event2


def test_clear_vh_event_removes_event():
    """Clearing removes the event from the registry."""
    _get_or_create_vh_event(42)
    _clear_vh_event(42)
    with _VH_EVENTS_LOCK:
        assert 42 not in _VH_EVENTS


def test_clear_vh_event_noop_for_missing():
    """Clearing a nonexistent event doesn't raise."""
    _clear_vh_event(999)  # Should not raise


# ── VH pull active check ──


@patch("src.server.Session")
def test_is_vh_pull_active_true_when_running(mock_session_cls):
    """Returns True when a running VH pull record exists."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
    # Simulate a running pull record
    mock_session.exec.return_value.first.return_value = MagicMock()

    assert _is_vh_pull_active(1) is True


@patch("src.server.Session")
def test_is_vh_pull_active_false_when_no_pull(mock_session_cls):
    """Returns False when no running VH pull record exists."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
    mock_session.exec.return_value.first.return_value = None

    assert _is_vh_pull_active(1) is False


# ── Proactive VH pull start ──


@patch("src.server.execute_data_pull")
@patch("src.server.decrypt_password", return_value="password")
@patch("src.server.ServiceNowClient")
@patch("src.server.Session")
def test_start_proactive_vh_pull_spawns_thread(
    mock_session_cls, mock_client_cls, mock_decrypt, mock_execute_pull
):
    """Starting a proactive VH pull spawns a thread and sets the event on completion."""
    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

    # First call: _is_vh_pull_active check (no running pull)
    mock_instance = MagicMock()
    mock_instance.id = 1
    mock_instance.url = "https://test.service-now.com"
    mock_instance.username = "admin"
    mock_instance.password_encrypted = "encrypted"
    mock_session.exec.return_value.first.return_value = None  # No running pull
    mock_session.get.return_value = mock_instance

    result = _start_proactive_vh_pull(1)
    assert result is True

    # Wait for the thread to finish
    event = _get_or_create_vh_event(1)
    event.wait(timeout=5)
    assert event.is_set()


@patch("src.server._is_vh_pull_active", return_value=True)
def test_start_proactive_vh_pull_skips_when_already_running(mock_active):
    """Returns False without spawning a thread if VH pull is already running."""
    result = _start_proactive_vh_pull(1)
    assert result is False
    # Event should still be created for waiters
    event = _get_or_create_vh_event(1)
    assert isinstance(event, threading.Event)


# ── Event signaling integration ──


def test_event_wait_returns_immediately_when_set():
    """Stage 5 wait returns instantly if VH already completed."""
    event = _get_or_create_vh_event(1)
    event.set()  # Simulate VH completion

    start = time.monotonic()
    result = event.wait(timeout=5)
    elapsed = time.monotonic() - start

    assert result is True
    assert elapsed < 0.1  # Should be near-instant


def test_event_wait_blocks_until_set():
    """Stage 5 wait blocks until VH signals completion."""
    event = _get_or_create_vh_event(1)

    # Set the event after a short delay in another thread
    def _set_later():
        time.sleep(0.2)
        event.set()

    t = threading.Thread(target=_set_later)
    t.start()

    start = time.monotonic()
    result = event.wait(timeout=5)
    elapsed = time.monotonic() - start

    assert result is True
    assert 0.1 < elapsed < 1.0  # Waited for the delayed set
    t.join()


def test_event_wait_timeout():
    """Stage 5 wait returns False on timeout."""
    event = _get_or_create_vh_event(1)

    start = time.monotonic()
    result = event.wait(timeout=0.2)
    elapsed = time.monotonic() - start

    assert result is False
    assert elapsed >= 0.15  # Waited approximately the timeout
