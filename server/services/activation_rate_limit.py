from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Iterable

from storage.atomic import atomic_write_text
from storage.coordinator import FileRunCoordinator


MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 5 * 60
LOCKOUT_SECONDS = 15 * 60


def _client_key(client_id: str) -> str:
    normalized = str(client_id or "unknown").strip().lower() or "unknown"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_state(path: Path) -> dict[str, dict[str, float | int]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def verify_activation_attempt(
    base_dir: Path,
    client_id: str,
    candidate: str,
    valid_codes: Iterable[str],
) -> tuple[bool, int]:
    """Validate and update a cross-process rate limit. Returns (valid, retry_after)."""
    coordinator = FileRunCoordinator(base_dir)
    state_path = coordinator.root / "activation-attempts.json"
    key = _client_key(client_id)
    now = time.time()

    with coordinator.exclusive_lock("activation-rate-limit", timeout=10.0):
        state = _load_state(state_path)
        state = {
            row_key: row
            for row_key, row in state.items()
            if float(row.get("locked_until", 0) or 0) > now
            or now - float(row.get("first_failure", 0) or 0) <= FAILURE_WINDOW_SECONDS
        }
        row = state.get(key, {})
        locked_until = float(row.get("locked_until", 0) or 0)
        if locked_until > now:
            return False, max(1, int(locked_until - now + 0.999))

        if any(hmac.compare_digest(candidate, code) for code in valid_codes):
            if key in state:
                state.pop(key, None)
                atomic_write_text(
                    state_path,
                    json.dumps(state, ensure_ascii=False),
                    encoding="utf-8",
                )
            return True, 0

        first_failure = float(row.get("first_failure", 0) or 0)
        failures = int(row.get("failures", 0) or 0)
        if not first_failure or now - first_failure > FAILURE_WINDOW_SECONDS:
            first_failure = now
            failures = 0
        failures += 1
        locked_until = now + LOCKOUT_SECONDS if failures >= MAX_FAILURES else 0
        state[key] = {
            "first_failure": first_failure,
            "failures": failures,
            "locked_until": locked_until,
        }
        atomic_write_text(
            state_path,
            json.dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )
        retry_after = max(1, int(locked_until - now)) if locked_until else 0
        return False, retry_after
