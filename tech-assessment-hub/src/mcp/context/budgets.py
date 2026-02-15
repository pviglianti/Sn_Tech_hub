"""Token budget calculations and telemetry.

Provides utilities for estimating token costs of context packs and
tracking cumulative token usage across pipeline runs. Enables the
70%% context threshold management described in AGENTS.md.

Wave 4 target -- stub only.
"""

from typing import Any, Dict


def estimate_tokens(text: str) -> int:
    """Estimate the token count for a string of text.

    Uses a simple heuristic (chars / 4) as a placeholder until a proper
    tokenizer is integrated.

    Args:
        text: The text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    return max(1, len(text) // 4)


def check_budget(current_tokens: int, max_tokens: int) -> Dict[str, Any]:
    """Check token budget utilization and return zone info.

    Args:
        current_tokens: Current token usage.
        max_tokens: Maximum token capacity.

    Returns:
        Dictionary with utilization percentage, zone (green/yellow/orange/red),
        and recommended action.
    """
    if max_tokens <= 0:
        return {"utilization": 0.0, "zone": "green", "action": "work_freely"}
    pct = current_tokens / max_tokens
    if pct < 0.50:
        return {"utilization": pct, "zone": "green", "action": "work_freely"}
    elif pct < 0.70:
        return {"utilization": pct, "zone": "yellow", "action": "prepare_checkpoint"}
    elif pct < 0.85:
        return {"utilization": pct, "zone": "orange", "action": "checkpoint_now"}
    else:
        return {"utilization": pct, "zone": "red", "action": "emergency_checkpoint"}
