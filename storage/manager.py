# Store facade: project directories, artifact files, markdown, config, and PlantUML.
import json

from pathlib import Path
from typing import Any, Dict, List, Optional

from .artifact import (
    get_draft_version as artifact_get_draft_version,
    load_artifact as artifact_load_artifact,
    load_draft as artifact_load_draft,
    save_artifact as artifact_save_artifact,
    save_draft as artifact_save_draft,
)
from .json import load_json_file, save_json_file
from .markdown import (
    load_markdown as markdown_load_markdown,
    markdown_target_dir,
    save_markdown as markdown_save_markdown,
)
from .plantuml import (
    save_plantuml_files as plantuml_save_plantuml_files,
    write_plantuml_file as plantuml_write_plantuml_file,
)
from .project import (
    create_project as project_create_project,
    list_projects as project_list_projects,
    load_one_project as project_load_one_project,
)


class Store:
    """I/O 層：JSON 檔案讀寫"""

    def __init__(self, base_dir: str = ".", project_id: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.project_id = project_id

        self.projects_dir = self.base_dir / "projects"
        self.log_dir = self.base_dir / "log"

        if not project_id:
            self.projects_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            return

        self.project_dir = self.projects_dir / project_id
        self.artifact_dir = self.project_dir / "artifact"
        self.output_dir = self.project_dir / "output"

        for dir_path in [
            self.artifact_dir,
            self.output_dir,
            self.log_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

    # 專案管理

    def load_one_project(self, project_path: Path) -> Optional[Dict[str, Any]]:
        return project_load_one_project(project_path)

    def list_projects(self) -> List[Dict[str, Any]]:
        return project_list_projects(self.projects_dir)

    def create_project(self) -> str:
        return project_create_project(self.projects_dir)

    def load_artifact(self) -> Optional[Dict[str, Any]]:
        return artifact_load_artifact(self.artifact_dir)

    # JSON 讀寫

    def load_json(self, filepath: str) -> Dict[str, Any]:
        return load_json_file(self.base_dir, filepath)

    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        save_json_file(self.base_dir, data, filepath, indent=indent)

    # Artifact

    def save_artifact(self, data: Dict[str, Any]):
        artifact_save_artifact(self.base_dir, self.artifact_dir, data)

    def save_draft(self, content: str, version: int):
        artifact_save_draft(self.artifact_dir, content, version)

    def get_draft_version(self) -> int:
        return artifact_get_draft_version(self.artifact_dir)

    def load_draft(self, version: int) -> Optional[str]:
        return artifact_load_draft(self.artifact_dir, version)

    # Config

    def load_config(self) -> Dict[str, Any]:
        return self.load_json(self.base_dir / "config.json")

    def save_config(self, config: Dict[str, Any]):
        with open(self.base_dir / "config.json", "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    # Markdown

    def markdown_target_dir(self, filename: str) -> Path:
        return markdown_target_dir(self.artifact_dir, self.output_dir, filename)

    def save_markdown(self, content: str, filename: str):
        markdown_save_markdown(self.artifact_dir, self.output_dir, content, filename)

    def load_markdown(self, filename: str) -> str:
        return markdown_load_markdown(self.artifact_dir, self.output_dir, filename)

    # PlantUML

    def write_plantuml_file(self, model: Dict) -> Optional[str]:
        return plantuml_write_plantuml_file(self.artifact_dir, model)

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        plantuml_save_plantuml_files(self.artifact_dir, model_data)
