"""Read preflight switches without requiring third-party dependencies."""

import json
from pathlib import Path


def preflight_enabled(base_dir: Path, target: str) -> bool:
    """Return a target switch; missing or invalid values default to enabled."""
    try:
        with (Path(base_dir) / "config.json").open("r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True

    if not isinstance(config, dict):
        return True
    settings = config.get("preflight")
    if not isinstance(settings, dict):
        return True
    value = settings.get(target, True)
    return value if isinstance(value, bool) else True
