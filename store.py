import json

from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime


class Store:
    """I/O 層：JSON / Markdown 檔案讀寫"""

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

    def list_projects(self) -> List[Dict[str, Any]]:
        projects = []
        if not self.projects_dir.exists():
            return projects

        for project_path in sorted(self.projects_dir.iterdir()):
            if project_path.is_dir():
                artifact_file = project_path / "artifact" / "artifact.json"
                rough_idea = "未知"
                if artifact_file.exists():
                    try:
                        with open(artifact_file, 'r', encoding='utf-8') as f:
                            artifact = json.load(f)
                            rough_idea = artifact.get("rough_idea", "未知")
                            if len(rough_idea) > 50:
                                rough_idea = rough_idea[:50] + "..."
                    except:
                        pass
                projects.append({
                    "project_id": project_path.name,
                    "created_at": datetime.fromtimestamp(project_path.stat().st_ctime).isoformat(),
                    "rough_idea": rough_idea
                })
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

    def save_round_mom(self, round_data: Dict):
        """Round 1: 全部 stage 合併成一份 md；Round 2+: 每個議題各一個 md"""
        round_num = round_data.get("round", 1)

        # Round 1: 合併成一份
        stages = round_data.get("stages", [])
        if stages:
            md = f"# Round {round_num} 會議記錄\n\n"
            md += f"**時間**：{round_data.get('timestamp', '')}\n\n"
            for idx, stage in enumerate(stages, 1):
                stage_id = f"R{round_num}-S{idx:02d}"
                md += self.generate_stage_markdown(stage, stage_id)
                md += "\n---\n\n"
            self.save_markdown(md, f"R{round_num}-Spec.md")

        # Round 2+: 每個議題各一個 md
        meetings = round_data.get("meetings", [])
        for meeting in meetings:
            meeting_id = meeting.get("meeting_id", "unknown")
            topic_title = meeting.get("topic", {}).get("title", "未命名")
            md = self.generate_meeting_markdown(meeting)
            filename = self.safe_mom_filename(f"{meeting_id} {topic_title}")
            self.save_markdown(md, f"{filename}.md")

    def generate_stage_markdown(self, stage: Dict, stage_id: str) -> str:
        """產生單一 Round 1 stage 的 markdown"""
        title = stage.get("stage", "")
        agent = stage.get("agent", "")
        md = f"#### {stage_id}: {title}\n\n"
        md += f"- **執行代理**：{agent}\n"
        md += f"- **描述**：{stage.get('description', '')}\n"
        md += f"- **時間**：{stage.get('timestamp', '')}\n\n"

        outputs = stage.get("outputs", {})
        if outputs:
            md += "**輸出**：\n\n"
            md += f"```json\n{json.dumps(outputs, ensure_ascii=False, indent=2)}\n```\n"

        return md

    def generate_meeting_markdown(self, meeting: Dict) -> str:
        """產生單一 Round 2+ meeting 的 markdown"""
        topic = meeting.get("topic", {})
        resolution = meeting.get("resolution", {})

        md = f"#### {meeting.get('meeting_id', '?')}: {topic.get('title', '')}\n\n"
        md += f"- **議題類型**：{topic.get('type', '')}\n"
        md += f"- **討論模式**：{meeting.get('discussion_mode', '?')}\n"
        md += f"- **參與者**：{', '.join(meeting.get('participants', []))}\n"
        md += f"- **時間**：{meeting.get('timestamp', '')}\n\n"

        for c in meeting.get("contributions", []):
            resp = c.get("response", {})
            md += f"**{c.get('agent', '?')}**：\n"
            position = resp.get("position", resp.get("content", ""))
            if position:
                md += f"- 立場：{position}\n"
            for arg in resp.get("arguments", []):
                md += f"  - {arg}\n"
            for sug in resp.get("suggestions", []):
                md += f"  - 建議：{sug}\n"
            md += "\n"

        md += f"**決議**：{resolution.get('status', '?')}\n\n"
        if resolution.get("summary"):
            md += f"- 摘要：{resolution['summary']}\n"
        if resolution.get("decision"):
            md += f"- 決策：{resolution['decision']}\n"
        for issue in resolution.get("remaining_issues", []):
            md += f"  - {issue}\n"
        if resolution.get("escalated_to_human"):
            md += f"- **已升級至人類裁決**\n"

        return md

    @staticmethod
    def safe_mom_filename(name: str) -> str:
        """清理檔名，保留中文字元"""
        for ch in [':', '/', '\\', '<', '>', '"', '|', '?', '*']:
            name = name.replace(ch, '_')
        return name.strip()

    def load_draft(self) -> Dict[str, Any]:
        draft_path = self.artifact_dir / "draft.json"
        if not draft_path.exists():
            return {}
        return self.load_json(draft_path)

    def load_uml(self) -> Dict[str, Any]:
        uml_path = self.artifact_dir / "uml.json"
        if not uml_path.exists():
            return {}
        return self.load_json(uml_path)

    def save_uml(self, data: Dict[str, Any], round_num: int):
        self.save_json(data, self.artifact_dir / f"uml_{round_num}.json")

    def save_draft(self, data: Dict[str, Any], round_num: int):
        self.save_json(data, self.artifact_dir / f"draft_{round_num}.json")

    def save_srs(self, data: Dict[str, Any]):
        self.save_json(data, self.artifact_dir / "srs.json")

    # Config

    def load_config(self) -> Dict[str, Any]:
        return self.load_json(self.config_dir / "config.json")

    def load_spec_template(self) -> Dict[str, Any]:
        template_path = self.config_dir / "spec.json"
        if not template_path.exists():
            raise FileNotFoundError(f"spec.json 不存在: {template_path}")
        return self.load_json(template_path)

    def save_config(self, config: Dict[str, Any]):
        with open(self.config_dir / "config.json", 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    # Markdown

    def save_markdown(self, content: str, filename: str):
        with open(self.output_dir / filename, 'w', encoding='utf-8') as f:
            f.write(content)

    def generate_report_markdown(self, reports: List[Dict]) -> str:
        md = "# 需求衝突報告\n\n"
        if reports:
            for report in reports:
                md += f"### {report['id']}: {report['title']}\n\n"
                md += f"衝突描述: {report['description']}\n\n"
                md += f"涉及利害關係人: {', '.join(report['stakeholder_names'])}\n\n"
        else:
            md += "## 衝突分析\n\n未識別出明顯衝突。"
        return md


    def generate_srs_markdown(self, srs_data: Dict[str, Any]) -> str:
        md = "# Software Requirements Specification (SRS)\n\n"

        def process_subsection(subsection, level=3):
            nonlocal md
            md += f"{'#' * level} {subsection.get('id', '')}\n\n"
            content = subsection.get("content", "")
            if isinstance(content, list):
                for item in content:
                    md += f"- {item}\n"
                md += "\n"
            elif content:
                md += f"{content}\n\n"
            for nested in subsection.get("subsection", []):
                process_subsection(nested, level + 1)

        for section_data in srs_data.get("ieee_29148", []):
            md += f"## {section_data.get('section', '')}\n\n"

            section_content = section_data.get("content", None)
            if section_content is not None:
                if isinstance(section_content, list):
                    if section_content and isinstance(section_content[0], dict):
                        for item in section_content:
                            md += f"### {item.get('id', '')}\n\n"
                            if item.get("plantuml"):
                                md += f"```plantuml\n{item['plantuml']}\n```\n\n"
                            for key, value in item.items():
                                if key in ("id", "plantuml"):
                                    continue
                                if isinstance(value, str) and value:
                                    md += f"{value}\n\n"
                                elif isinstance(value, list):
                                    for v in value:
                                        md += f"- {v}\n"
                                    md += "\n"
                    else:
                        for item in section_content:
                            md += f"- {item}\n"
                        md += "\n"
                elif isinstance(section_content, str):
                    md += f"{section_content}\n\n"

            for subsection in section_data.get("subsection", []):
                process_subsection(subsection)

        return md

    def generate_draft_markdown(self, draft: Dict[str, Any]) -> str:
        md = ""
        for section_data in draft.get("draft", []):
            md += f"\n## {section_data.get('section', '')}\n\n"

            if "content" in section_data:
                content = section_data["content"]
                if isinstance(content, str):
                    md += f"{content}\n\n"
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, str):
                            md += f"- {item}\n"
                        elif isinstance(item, dict):
                            if "stakeholder_name" in item and "concern" in item:
                                md += f"### {item.get('stakeholder_name', '')}\n"
                                md += f"**關注點**: {item.get('concern', '')}\n**需求**:\n"
                                for req in item.get('requirement', []):
                                    md += f"  - {req}\n"
                                md += "\n"
                            elif "id" in item and "description" in item:
                                md += f"### {item.get('id', '')}\n\n"
                                md += f"**涉及利害關係人**: {', '.join(item.get('stakeholder_name', []))}\n\n"
                                md += f"**描述**: {item.get('description', '')}\n\n**解決方案**:\n"
                                solutions = item.get('solutions', [])
                                if isinstance(solutions, list):
                                    for sol in solutions:
                                        md += f"  - {sol}\n"
                                else:
                                    md += f"  {solutions}\n"
                                md += "\n"
                            else:
                                md += f"- {json.dumps(item, ensure_ascii=False)}\n"
                    md += "\n"

            for subsection in section_data.get("subsection", []):
                md += f"### {subsection.get('id', '')}\n\n"
                sub_content = subsection.get("content", [])
                if isinstance(sub_content, str):
                    md += f"{sub_content}\n\n"
                elif isinstance(sub_content, list):
                    for item in sub_content:
                        if isinstance(item, str):
                            md += f"- {item}\n"
                        elif isinstance(item, dict):
                            md += f"**{item.get('id', '')}**\n{item.get('content', '')}\n\n"
                    md += "\n"

        return md

    # PlantUML

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        for model in model_data.get("models", []):
            plantuml_code = model.get("plantuml", "")
            if plantuml_code:
                safe_name = "".join(c for c in model.get("name", "unnamed") if c.isalnum() or c in (' ', '-', '_')).strip()
                filepath = self.output_dir / f"{safe_name}.plantuml"
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(plantuml_code)
                print(f"✓ 儲存 PlantUML: {safe_name}.plantuml")
