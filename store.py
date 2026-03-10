import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime


class Store:
    """I/O 層：JSON 檔案讀寫"""

    def __init__(self, base_dir: str = ".", project_id: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.project_id = project_id

        self.config_dir = self.base_dir / "config"
        self.projects_dir = self.base_dir / "projects"
        self.log_dir = self.base_dir / "log"

        if not project_id:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.projects_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            return

        self.project_dir = self.projects_dir / project_id
        self.artifact_dir = self.project_dir / "artifact"
        self.output_dir = self.project_dir / "output"

        for dir_path in [self.config_dir, self.artifact_dir, self.output_dir, self.log_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    # 專案管理

    def _load_one_project(self, project_path: Path) -> Optional[Dict[str, Any]]:
        if not project_path.is_dir():
            return None
        artifact_file = project_path / "artifact" / "artifact.json"
        rough_idea = "未知"
        if artifact_file.exists():
            try:
                with open(artifact_file, 'r', encoding='utf-8') as f:
                    artifact = json.load(f)
                    rough_idea = artifact.get("rough_idea", "未知")
            except Exception:
                pass
        return {
            "project_id": project_path.name,
            "created_at": datetime.fromtimestamp(project_path.stat().st_ctime).isoformat(),
            "rough_idea": rough_idea,
        }

    def list_projects(self) -> List[Dict[str, Any]]:
        if not self.projects_dir.exists():
            return []

        paths = sorted(self.projects_dir.iterdir())
        if not paths:
            return []

        projects = []
        max_workers = min(len(paths), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {executor.submit(self._load_one_project, p): p for p in paths}
            for future in as_completed(future_to_path):
                try:
                    proj = future.result()
                    if proj is not None:
                        projects.append(proj)
                except Exception:
                    pass
        projects.sort(key=lambda x: (x.get("created_at", ""), x.get("project_id", "")))
        return projects

    def create_project(self) -> str:
        project_id = datetime.now().strftime("%H%M%S")
        (self.projects_dir / project_id).mkdir(parents=True, exist_ok=True)
        return project_id

    def load_artifact(self) -> Optional[Dict[str, Any]]:
        artifact_file = self.artifact_dir / "artifact.json"
        if not artifact_file.exists():
            return None
        with open(artifact_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    # JSON 讀寫

    def load_json(self, filepath: str) -> Dict[str, Any]:
        path = Path(filepath)
        if not path.is_absolute():
            path = self.base_dir / filepath
        if not path.exists():
            raise FileNotFoundError(f"檔案不存在: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        path = Path(filepath)
        if not path.is_absolute():
            path = self.base_dir / filepath
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)

    # Artifact

    def save_artifact(self, data: Dict[str, Any]):
        self.save_json(data, self.artifact_dir / "artifact.json")

    def save_draft(self, content: str, version: int):
        """儲存需求草稿為 draft_v{version}.md（Markdown）到 artifact 目錄"""
        path = self.artifact_dir / f"draft_v{version}.md"
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def get_draft_version(self) -> int:
        """回傳目前已有的 draft 最大版本號；若無則回傳 -1"""
        max_v = -1
        if not self.artifact_dir.exists():
            return max_v
        for f in self.artifact_dir.iterdir():
            if f.name.startswith("draft_v") and f.name.endswith(".md"):
                try:
                    v = int(f.name[len("draft_v"):-len(".md")])
                    max_v = max(max_v, v)
                except ValueError:
                    pass
        return max_v

    def load_draft(self, version: int) -> Optional[str]:
        """載入指定版本的 draft markdown"""
        path = self.artifact_dir / f"draft_v{version}.md"
        if not path.exists():
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    # Config

    def load_config(self) -> Dict[str, Any]:
        return self.load_json(self.config_dir / "config.json")

    def save_config(self, config: Dict[str, Any]):
        with open(self.config_dir / "config.json", 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    # Markdown

    def save_markdown(self, content: str, filename: str):
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    # PlantUML

    def _write_one_plantuml(self, model: Dict) -> Optional[str]:
        plantuml_code = model.get("plantuml", "")
        if not plantuml_code:
            return None
        safe_name = "".join(c for c in model.get("name", "unnamed") if c.isalnum() or c in (' ', '-', '_')).strip()
        filepath = self.output_dir / f"{safe_name}.plantuml"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(plantuml_code)
        return f"{safe_name}.plantuml"

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        models = [m for m in model_data.get("models", []) if m.get("plantuml")]
        if not models:
            return
        max_workers = min(len(models), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._write_one_plantuml, m) for m in models]
            for future in as_completed(futures):
                try:
                    name = future.result()
                    if name:
                        print(f"✓ 儲存 PlantUML: {name}")
                except Exception as e:
                    print(f"儲存 PlantUML 失敗: {e}")
