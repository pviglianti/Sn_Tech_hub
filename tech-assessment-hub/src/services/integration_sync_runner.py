"""Shared integration sync decision runner.

Unifies count/probe delta decisions for all integration modules
(Preflight/Data Browser, CSDM, future integrations).

Decision logic (single path for all callers):
  1. No watermark → full (no sync history)
  2. Local count = 0 → full (data was cleared, stale watermark)
  3. Probe > 0 AND local + probe < remote → full (delta won't close the gap)
  4. Probe > 0 AND local + probe >= remote → delta (delta covers everything)
  5. Probe = 0 + count mismatch → full (missing data, no recent changes)
  6. Probe = 0 + counts match → skip (nothing changed)
  7. Probe unavailable → delta (trust watermark, pull what changed)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class DeltaDecisionResult:
    mode: str  # "skip" | "delta" | "full"
    since: Optional[datetime]
    reason: str
    local_count: int
    remote_count: Optional[int]
    delta_probe_count: Optional[int]


def resolve_delta_decision(
    *,
    local_count: int,
    remote_count: Optional[int],
    watermark: Optional[datetime],
    delta_probe_count: Optional[int],
) -> DeltaDecisionResult:
    """Resolve delta execution mode using count + probe logic.

    This is THE single decision point for all integration sync paths:
    Data Browser, CSDM, Dictionary, Assessment Preflight, MCP tools.
    """
    if watermark is None:
        return DeltaDecisionResult(
            mode="full",
            since=None,
            reason="Missing local watermark - using full refresh",
            local_count=local_count,
            remote_count=remote_count,
            delta_probe_count=delta_probe_count,
        )

    # Guard: if the local table is empty but we have a watermark, the data was
    # cleared (or never actually ingested).  A delta would only pull recently
    # updated records, missing everything else.  Force a full refresh.
    if local_count == 0:
        return DeltaDecisionResult(
            mode="full",
            since=None,
            reason="Local table is empty despite existing watermark - full refresh required",
            local_count=local_count,
            remote_count=remote_count,
            delta_probe_count=delta_probe_count,
        )

    # Primary contract: count + delta probe.
    #
    # Core logic:
    #   1. If probe > 0, check whether delta alone will close the gap:
    #      - local + probe >= remote → delta is sufficient
    #      - local + probe <  remote → delta won't cover missing records → full
    #   2. If probe = 0 AND counts mismatch → full (no recent changes but data missing)
    #   3. If probe = 0 AND counts match → skip (nothing changed)
    if delta_probe_count is not None:
        if delta_probe_count > 0:
            # Can we know the remote count?  If not, trust the probe and delta.
            if remote_count is not None:
                projected = local_count + delta_probe_count
                gap = remote_count - local_count
                if projected < remote_count:
                    # Delta won't close the gap — records exist in SN that we
                    # never had and they haven't been updated since the watermark.
                    return DeltaDecisionResult(
                        mode="full",
                        since=None,
                        reason=(
                            f"Delta probe found {delta_probe_count} updated rows "
                            f"but local({local_count}) + probe({delta_probe_count}) = {projected} "
                            f"< remote({remote_count}) — full refresh to close gap of {gap}"
                        ),
                        local_count=local_count,
                        remote_count=remote_count,
                        delta_probe_count=delta_probe_count,
                    )

            # Delta is sufficient (or remote_count unknown — trust the probe)
            gap = (remote_count - local_count) if remote_count is not None else 0
            counts_match = gap == 0
            return DeltaDecisionResult(
                mode="delta",
                since=watermark,
                reason=(
                    f"Delta probe found {delta_probe_count} updated rows"
                    + (f" (local={local_count}, remote={remote_count}, gap={gap})"
                       if not counts_match else f" (counts match at {local_count})")
                ),
                local_count=local_count,
                remote_count=remote_count,
                delta_probe_count=delta_probe_count,
            )

        # probe = 0: no records updated since watermark
        counts_match = local_count == (remote_count if remote_count is not None else local_count)
        if not counts_match:
            gap = (remote_count - local_count) if remote_count is not None else 0
            return DeltaDecisionResult(
                mode="full",
                since=None,
                reason=(
                    f"Count mismatch (local={local_count}, remote={remote_count}, gap={gap}) "
                    f"with 0 updates since watermark - full reconcile required"
                ),
                local_count=local_count,
                remote_count=remote_count,
                delta_probe_count=delta_probe_count,
            )

        return DeltaDecisionResult(
            mode="skip",
            since=watermark,
            reason=f"Counts match ({local_count}) and delta probe found 0 updates",
            local_count=local_count,
            remote_count=remote_count,
            delta_probe_count=delta_probe_count,
        )

    # Probe unavailable: trust watermark and pull delta.
    return DeltaDecisionResult(
        mode="delta",
        since=watermark,
        reason="Delta probe unavailable - continuing with delta pull",
        local_count=local_count,
        remote_count=remote_count,
        delta_probe_count=delta_probe_count,
    )
