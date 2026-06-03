"""
Runtime bootstrap helpers for project-wide Python behavior.
"""

import os
import sys
from pathlib import Path


def disable_pycache() -> None:
    """Disable writing Python bytecode cache files (__pycache__) for this process."""
    sys.dont_write_bytecode = True
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


# Apply once at import time for this process.
disable_pycache()


def _find_repo_root(start_path: Path) -> Path:
    current = start_path.parent
    for _ in range(8):
        if (current / "main.py").exists() and (current / "utils").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start_path.parent.parent


def apply_entrypoint_bootstrap() -> None:
    """Call at script start for repo-wide execution behavior."""
    repo_root = _find_repo_root(Path(__file__).resolve())
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    disable_pycache()
