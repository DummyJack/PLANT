"""Prepare the Python runtime before application modules are imported."""

from __future__ import annotations

import sys
from pathlib import Path

from .dependencies import ensure_python_dependencies
from .output import abort_startup


MINIMUM_PYTHON = (3, 10)


def prepare_python_environment(base_dir: Path, *, enabled: bool) -> None:
    if not enabled:
        return

    if sys.version_info < MINIMUM_PYTHON:
        current = ".".join(str(part) for part in sys.version_info[:3])
        abort_startup(
            f"不支援 Python {current}；PLANT 需要 Python 3.10 以上版本"
        )

    try:
        ensure_python_dependencies(base_dir)
    except RuntimeError as exc:
        abort_startup(exc)
