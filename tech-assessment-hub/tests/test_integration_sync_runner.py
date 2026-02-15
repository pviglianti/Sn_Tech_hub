from datetime import datetime

from src.services.integration_sync_runner import resolve_delta_decision


def test_resolve_delta_decision_without_watermark_forces_full():
    result = resolve_delta_decision(
        local_count=10,
        remote_count=10,
        watermark=None,
        delta_probe_count=None,
    )
    assert result.mode == "full"
    assert result.since is None


def test_resolve_delta_decision_counts_match_probe_zero_skips():
    result = resolve_delta_decision(
        local_count=50,
        remote_count=50,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=0,
    )
    assert result.mode == "skip"


def test_resolve_delta_decision_probe_positive_gap_too_large_goes_full():
    """When probe > 0 but local + probe < remote, delta won't close gap → full."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=500,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=10,  # 50 + 10 = 60 < 500 → full
    )
    assert result.mode == "full"
    assert result.since is None
    assert "gap" in result.reason.lower()


def test_resolve_delta_decision_probe_positive_closes_gap_uses_delta():
    """When probe > 0 and local + probe >= remote, delta covers it → delta."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=55,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=5,  # 50 + 5 = 55 >= 55 → delta
    )
    assert result.mode == "delta"
    assert result.since == datetime(2026, 2, 13, 9, 0, 0)


def test_resolve_delta_decision_probe_positive_overshoots_uses_delta():
    """When local + probe > remote (updates include existing records), delta."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=55,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=20,  # 50 + 20 = 70 >= 55 → delta (some are updates to existing)
    )
    assert result.mode == "delta"
    assert result.since == datetime(2026, 2, 13, 9, 0, 0)


def test_resolve_delta_decision_count_mismatch_probe_zero_goes_full():
    """When counts differ and probe=0, no recent updates to pull → full reconcile."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=100,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=0,
    )
    assert result.mode == "full"
    assert result.since is None
    assert "Count mismatch" in result.reason


def test_resolve_delta_decision_counts_match_probe_positive_deltas():
    """When counts match but probe > 0, there are updated rows → delta."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=50,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=3,  # 50 + 3 = 53 >= 50 → delta
    )
    assert result.mode == "delta"
    assert result.since == datetime(2026, 2, 13, 9, 0, 0)


def test_resolve_delta_decision_probe_unavailable_defaults_to_delta():
    """When probe is None (API call failed), default to delta using watermark."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=55,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=None,
    )
    assert result.mode == "delta"
    assert result.since == datetime(2026, 2, 13, 9, 0, 0)
    assert "unavailable" in result.reason


def test_resolve_delta_decision_remote_count_none_treated_as_match():
    """When remote_count is None (can't get it), treat as matching local."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=None,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=0,
    )
    assert result.mode == "skip"  # counts "match" (None treated as local_count)


def test_resolve_delta_decision_remote_count_none_probe_positive_deltas():
    """When remote_count unknown and probe > 0, trust probe → delta."""
    result = resolve_delta_decision(
        local_count=50,
        remote_count=None,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=5,
    )
    assert result.mode == "delta"  # can't check gap without remote_count


def test_resolve_delta_decision_empty_table_with_watermark_forces_full():
    """When local_count=0 but watermark exists (data was cleared), force full.

    Regression: without this guard, probe>0 would trigger a delta that only
    pulls recently-updated records, missing all older data.
    """
    result = resolve_delta_decision(
        local_count=0,
        remote_count=481,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=33,
    )
    assert result.mode == "full"
    assert result.since is None
    assert "empty" in result.reason.lower()


def test_resolve_delta_decision_empty_table_probe_zero_still_forces_full():
    """Even with probe=0, an empty table with watermark should do full."""
    result = resolve_delta_decision(
        local_count=0,
        remote_count=481,
        watermark=datetime(2026, 2, 13, 9, 0, 0),
        delta_probe_count=0,
    )
    assert result.mode == "full"
    assert result.since is None
