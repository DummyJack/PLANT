import base64
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from .security import ALLOWED_OUTPUT_ROOTS, resolve_project_file, resolve_under
from storage.coordinator import FileRunCoordinator


TEXT_EXTS = {".json", ".md", ".plantuml", ".txt", ".html", ".csv"}
EDITABLE_EXTS = {".json", ".md", ".plantuml"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


class ArtifactService:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.projects_dir = base_dir / "projects"

    def project_dir(self, project_id: str) -> Path:
        path = resolve_under(self.base_dir, self.projects_dir, project_id)
        if not path.exists() or not path.is_dir():
            raise HTTPException(status_code=404, detail="Project not found")
        return path

    def tree(self, project_id: str) -> List[Dict[str, Any]]:
        with FileRunCoordinator(self.base_dir).exclusive_lock(f"artifact-{project_id}", timeout=30.0):
            root = self.project_dir(project_id)
            out: List[Dict[str, Any]] = []
            for allowed_root in sorted(ALLOWED_OUTPUT_ROOTS):
                scan_root = root / allowed_root
                if not scan_root.exists():
                    continue
                for path in sorted(scan_root.rglob("*")):
                    if path.name == ".DS_Store":
                        continue
                    rel = path.relative_to(root).as_posix()
                    out.append({"path": rel, "name": path.name, "kind": "directory" if path.is_dir() else "file", "size": path.stat().st_size if path.is_file() else None, "editable": path.suffix.lower() in EDITABLE_EXTS, "previewable": path.suffix.lower() in TEXT_EXTS | IMAGE_EXTS})
            return out

    def read_file(self, project_id: str, relative_path: str) -> Dict[str, Any]:
        with FileRunCoordinator(self.base_dir).exclusive_lock(f"artifact-{project_id}", timeout=30.0):
            return self._read_file_unlocked(project_id, relative_path)

    def _read_file_unlocked(self, project_id: str, relative_path: str) -> Dict[str, Any]:
        root = self.project_dir(project_id)
        path = resolve_project_file(self.base_dir, root, relative_path)
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTS:
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            return {
                "path": relative_path,
                "type": "image",
                "encoding": "base64",
                "content": data,
                "mime": self._image_mime(suffix),
                "editable": False,
                "readonly": True,
            }
        if suffix not in TEXT_EXTS:
            raise HTTPException(status_code=400, detail="File cannot be previewed")
        return {
            "path": relative_path,
            "type": "json" if suffix == ".json" else suffix.lstrip("."),
            "encoding": "utf-8",
            "content": path.read_text(encoding="utf-8"),
            "editable": suffix in EDITABLE_EXTS,
            "readonly": suffix not in EDITABLE_EXTS,
        }

    @staticmethod
    def _image_mime(suffix: str) -> str:
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
