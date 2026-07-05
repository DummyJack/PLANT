# Handles manager logic for project artifact storage and file export behavior.
import json

from pathlib import Path
from typing import Any, Dict, List, Optional

from .atomic import atomic_write_text
from .artifact import (
    get_draft_version as artifact_get_draft_version,
    load_artifact as artifact_load_artifact,
    load_draft as artifact_load_draft,
    save_artifact as artifact_save_artifact,
    save_draft as artifact_save_draft,
)
from .json import load_json_file, save_json_file
from .markdown import (
    save_markdown_as_html,
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


# ========
# Defines Store class for this module workflow.
# ========
class Store:

    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, base_dir: str = ".", project_id: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.project_id = project_id

        self.projects_dir = self.base_dir / "projects"
        self.doc_dir = self.base_dir / "doc"
        self.log_dir = self.base_dir / "log"

        if not project_id:
            self.projects_dir.mkdir(parents=True, exist_ok=True)
            self.doc_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            return

        self.project_dir = self.projects_dir / project_id
        self.artifact_dir = self.project_dir / "artifact"
        self.output_dir = self.project_dir / "output"

        for dir_path in [
            self.artifact_dir,
            self.output_dir,
            self.doc_dir,
            self.log_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)


    # ========
    # Defines load one project function for this module workflow.
    # ========
    def load_one_project(self, project_path: Path) -> Optional[Dict[str, Any]]:
        return project_load_one_project(project_path)

    # ========
    # Defines list projects function for this module workflow.
    # ========
    def list_projects(self) -> List[Dict[str, Any]]:
        return project_list_projects(self.projects_dir)

    # ========
    # Defines create project function for this module workflow.
    # ========
    def create_project(self) -> str:
        return project_create_project(self.projects_dir)

    # ========
    # Defines load artifact function for this module workflow.
    # ========
    def load_artifact(self) -> Optional[Dict[str, Any]]:
        return artifact_load_artifact(self.artifact_dir)


    # ========
    # Defines load json function for this module workflow.
    # ========
    def load_json(self, filepath: str) -> Dict[str, Any]:
        return load_json_file(self.base_dir, filepath)

    # ========
    # Defines save json function for this module workflow.
    # ========
    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        save_json_file(self.base_dir, data, filepath, indent=indent)


    # ========
    # Defines save artifact function for this module workflow.
    # ========
    def save_artifact(self, data: Dict[str, Any]):
        artifact_save_artifact(self.base_dir, self.artifact_dir, data)

    # ========
    # Defines save draft function for this module workflow.
    # ========
    def save_draft(self, content: str, version: int):
        artifact_save_draft(self.artifact_dir, content, version)

    # ========
    # Defines get draft version function for this module workflow.
    # ========
    def get_draft_version(self) -> int:
        return artifact_get_draft_version(self.artifact_dir)

    # ========
    # Defines load draft function for this module workflow.
    # ========
    def load_draft(self, version: int) -> Optional[str]:
        return artifact_load_draft(self.artifact_dir, version)


    # ========
    # Defines load config function for this module workflow.
    # ========
    def load_config(self) -> Dict[str, Any]:
        return self.load_json(self.base_dir / "config.json")

    # ========
    # Defines save config function for this module workflow.
    # ========
    def save_config(self, config: Dict[str, Any]):
        atomic_write_text(
            self.base_dir / "config.json",
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


    # ========
    # Defines markdown target dir function for this module workflow.
    # ========
    def markdown_target_dir(self, filename: str) -> Path:
        return markdown_target_dir(self.artifact_dir, self.output_dir, filename)

    # ========
    # Defines save markdown function for this module workflow.
    # ========
    def save_markdown(self, content: str, filename: str):
        markdown_save_markdown(self.artifact_dir, self.output_dir, content, filename)

    # ========
    # Defines save markdown as html function for this module workflow.
    # ========
    def save_markdown_as_html(
        self,
        md_path: Path,
        html_path: Path,
        html_root: Optional[Path] = None,
    ) -> None:
        save_markdown_as_html(
            md_path,
            html_path,
            html_root=html_root,
            project_id=self.project_id,
        )


    # ========
    # Defines write plantuml file function for this module workflow.
    # ========
    def write_plantuml_file(self, model: Dict) -> Optional[str]:
        return plantuml_write_plantuml_file(self.artifact_dir, model)

    # ========
    # Defines save plantuml files function for this module workflow.
    # ========
    def save_plantuml_files(self, model_data: Dict[str, Any]):
        plantuml_save_plantuml_files(self.artifact_dir, model_data)
