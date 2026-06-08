# Handles clean logic for shared utility behavior for the Plant runtime.

import os
import sys
from pathlib import Path


# ========
# Defines disable pycache function for this module workflow.
# ========
def disable_pycache() -> None:
    sys.dont_write_bytecode = True
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


disable_pycache()


# ========
# Defines find repo root function for this module workflow.
# ========
def find_repo_root(start_path: Path) -> Path:
    current = start_path.parent
    for _ in range(8):
        if (current / "main.py").exists() and (current / "utils").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start_path.parent.parent


# ========
# Defines apply entrypoint bootstrap function for this module workflow.
# ========
def apply_entrypoint_bootstrap() -> None:
    repo_root = find_repo_root(Path(__file__).resolve())
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
    disable_pycache()
