# Handles project logic for project artifact storage and file export behavior.
import json

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ========
# Defines load one project function for this module workflow.
# ========
def load_one_project(project_path: Path) -> Optional[Dict[str, Any]]:
    if not project_path.is_dir():
        return None
    project_file = project_path / "artifact" / "project.json"
    if not project_file.exists():
        return None
    rough_idea = ""
    scenario = ""
    try:
        with open(project_file, "r", encoding="utf-8") as f:
            project = json.load(f)
            rough_idea = str(project.get("rough_idea") or "").strip()
            scenario = str(project.get("scenario") or "").strip()
    except Exception:
        return None
    return {
        "project_id": project_path.name,
        "created_at": datetime.fromtimestamp(
            project_path.stat().st_ctime
        ).isoformat(),
        "rough_idea": rough_idea,
        "scenario": scenario,
    }


# ========
# Defines list projects function for this module workflow.
# ========
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


# ========
# Defines create project function for this module workflow.
# ========
def create_project(projects_dir: Path) -> str:
    projects_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        project_id = datetime.now().strftime("%H%M%S%f")
        try:
            (projects_dir / project_id).mkdir(parents=True, exist_ok=False)
            return project_id
        except FileExistsError:
            continue
    raise RuntimeError("Unable to create unique project id")
