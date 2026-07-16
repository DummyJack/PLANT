"""User-facing output helpers that are safe before dependencies are installed."""

from __future__ import annotations

import sys
from typing import NoReturn


def abort_startup(message: object) -> NoReturn:
    """Print a concise startup failure and exit without a traceback."""
    print("[ERROR] 後端啟動失敗", file=sys.stderr, flush=True)
    for line in str(message).splitlines():
        print(f"[ERROR] {line}", file=sys.stderr, flush=True)
    raise SystemExit(1)
