import json

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_one_project(project_path: Path) -> Optional[Dict[str, Any]]:
    if not project_path.is_dir():
        return None
    artifact_file = project_path / "artifact" / "artifact.json"
    rough_idea = "未知"
    if artifact_file.exists():
        try:
            with open(artifact_file, "r", encoding="utf-8") as f:
                artifact = json.load(f)
                rough_idea = artifact.get("rough_idea", "未知")
        except Exception:
            pass
    return {
        "project_id": project_path.name,
        "created_at": datetime.fromtimestamp(
            project_path.stat().st_ctime
        ).isoformat(),
        "rough_idea": rough_idea,
    }


def list_projects(projects_dir: Path) -> List[Dict[str, Any]]:
    if not projects_dir.exists():
        return []

    paths = sorted(projects_dir.iterdir())
    if not paths:
        return []

    projects = []
    max_workers = min(len(paths), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {
            executor.submit(load_one_project, p): p for p in paths
        }
        for future in as_completed(future_to_path):
            try:
                proj = future.result()
                if proj is not None:
                    projects.append(proj)
            except Exception:
                pass
    projects.sort(key=lambda x: (x.get("created_at", ""), x.get("project_id", "")))
    return projects


def create_project(projects_dir: Path) -> str:
    project_id = datetime.now().strftime("%H%M%S")
    (projects_dir / project_id).mkdir(parents=True, exist_ok=True)
    return project_id
