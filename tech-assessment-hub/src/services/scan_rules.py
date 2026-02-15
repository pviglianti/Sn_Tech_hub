from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "scan_rules.yaml"


def load_scan_rules(path: Path | None = None) -> Dict[str, Any]:
    """Load scan rules from YAML on disk."""
    config_path = path or _CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"scan rules file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("scan rules file must be a YAML mapping at the top level")
    return data


@lru_cache(maxsize=1)
def get_scan_rules() -> Dict[str, Any]:
    """Return cached scan rules."""
    return load_scan_rules()


def reload_scan_rules() -> Dict[str, Any]:
    """Clear cache and reload scan rules from disk."""
    get_scan_rules.cache_clear()
    return get_scan_rules()
