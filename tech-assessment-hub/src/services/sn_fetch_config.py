"""Shared configuration for ServiceNow data fetching.

Constants used by both CSDM ingestion (csdm_ingestion.py) and
Preflight/Data Browser pulls (sn_client._iterate_batches).
Centralised here so pagination, rate-limiting, and retry behaviour
are identical across both systems.

Compile-time defaults below serve as fallbacks.  At runtime, call
``get_effective_config()`` to read the live values from the Integration
Properties UI (AppConfig table), with graceful fallback to these defaults.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# -- Batch / pagination -----------------------------------------------
DEFAULT_BATCH_SIZE: int = 200
"""Records per API call.  200 keeps response payloads manageable and
matches the proven CSDM ingestion setting."""

MAX_BATCHES: int = 5000
"""Safety cap per table pull.  5 000 × 200 = 1 000 000 rows max."""

# -- Rate limiting -----------------------------------------------------
INTER_BATCH_DELAY: float = 0.5
"""Seconds to sleep between successive API calls (polite pacing)."""

# -- Retry / backoff ---------------------------------------------------
MAX_RETRIES: int = 3
"""Maximum number of attempts per batch before giving up."""

RETRY_DELAYS: list = [2, 5, 15]
"""Seconds to wait between retries (exponential-ish backoff)."""

# -- Timeouts ----------------------------------------------------------
REQUEST_TIMEOUT: int = 60
"""HTTP request timeout in seconds (large tables can be slow)."""


def _hardcoded_defaults() -> Dict[str, object]:
    """Return compile-time defaults as a dict (used as fallback)."""
    return {
        "batch_size": DEFAULT_BATCH_SIZE,
        "inter_batch_delay": INTER_BATCH_DELAY,
        "max_batches": MAX_BATCHES,
        "request_timeout": REQUEST_TIMEOUT,
    }


def get_effective_config(instance_id: Optional[int] = None) -> Dict[str, object]:
    """Load live fetch config from the Integration Properties UI (AppConfig).

    Opens a short-lived DB session, reads the four tunable values, and falls
    back to the compile-time defaults on any error (DB not ready, import
    failure, etc.).  Safe to call at any point in the app lifecycle.
    """
    try:
        from sqlmodel import Session
        from ..database import engine
        from .integration_properties import load_fetch_properties

        with Session(engine) as session:
            props = load_fetch_properties(session, instance_id=instance_id)
            return {
                "batch_size": props.default_batch_size,
                "inter_batch_delay": props.inter_batch_delay,
                "max_batches": props.max_batches,
                "request_timeout": props.request_timeout,
            }
    except Exception as exc:
        logger.debug("get_effective_config fell back to defaults: %s", exc)
        return _hardcoded_defaults()
