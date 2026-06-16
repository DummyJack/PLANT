"""Project-local runtime setup helpers."""

import os
import sys
from pathlib import Path


def apply_runtime_setup() -> None:
    sys.dont_write_bytecode = True
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    repo_root = Path(__file__).resolve().parent
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


if __name__ == "__main__":
    apply_runtime_setup()
