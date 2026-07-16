"""Startup checks that remain importable before third-party packages exist."""

from .dependencies import ensure_python_dependencies
from .settings import preflight_enabled

__all__ = ["ensure_python_dependencies", "preflight_enabled"]
