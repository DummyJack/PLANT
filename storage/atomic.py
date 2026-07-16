# Handles atomic file writes for project storage.
import os
import tempfile
import time

from pathlib import Path


def _replace_with_retry(source: Path, target: Path) -> None:
    """Replace a file atomically, tolerating short-lived Windows read locks."""
    delay = 0.01
    for attempt in range(8):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if os.name != "nt" or attempt == 7:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: Path, content: bytes) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

