import json

from pathlib import Path
from typing import Any, Dict, Optional

from .json_io import save_json_file


def load_artifact(artifact_dir: Path) -> Optional[Dict[str, Any]]:
    artifact_file = artifact_dir / "artifact.json"
    if not artifact_file.exists():
        return None
    with open(artifact_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_artifact(base_dir: Path, artifact_dir: Path, data: Dict[str, Any]) -> None:
    save_json_file(base_dir, data, artifact_dir / "artifact.json")


def save_draft(artifact_dir: Path, content: str, version: int) -> None:
    """儲存需求草稿為 draft_v{version}.md（Markdown）到 artifact 目錄"""
    path = artifact_dir / f"draft_v{version}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def get_draft_version(artifact_dir: Path) -> int:
    """回傳目前已有的 draft 最大版本號；若無則回傳 -1"""
    max_v = -1
    if not artifact_dir.exists():
        return max_v
    for f in artifact_dir.iterdir():
        if f.name.startswith("draft_v") and f.name.endswith(".md"):
            try:
                v = int(f.name[len("draft_v") : -len(".md")])
                max_v = max(max_v, v)
            except ValueError:
                pass
    return max_v


def load_draft(artifact_dir: Path, version: int) -> Optional[str]:
    """載入指定版本的 draft markdown"""
    path = artifact_dir / f"draft_v{version}.md"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
