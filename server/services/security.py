import re
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException


SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]")


def sanitize_filename(name: str) -> str:
    cleaned = SAFE_NAME.sub("_", Path(name).name).strip("._")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return cleaned


def resolve_under(base_dir: Path, root: Path, relative_path: str) -> Path:
    if not relative_path or ".." in Path(relative_path).parts:
        raise HTTPException(status_code=400, detail="Invalid path")
    root_resolved = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path is not allowed") from exc
    try:
        target.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path is outside workspace") from exc
    return target


def ensure_extension(path: Path, allowed: Iterable[str]) -> None:
    suffix = path.suffix.lower()
    if suffix not in set(allowed):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")
