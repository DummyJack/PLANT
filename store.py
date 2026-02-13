import re
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
        """Round 1: 全部 stage 合併成一份 md（Round 2+ 議題 md 已在討論迴圈中即時儲存）"""
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
        md += f"- **時間**：{meeting.get('timestamp', '')}\n\n"

        # 發言紀錄
        contributions = meeting.get("contributions", [])
        if contributions:
            md += "---\n\n"
            md += "##### 討論紀錄\n\n"
            for c in contributions:
                agent = c.get("agent", "?")
                resp = c.get("response", {})

                md += f"**{agent}**：\n"
                position = resp.get("position", resp.get("content", ""))
                if position:
                    md += f"- 立場：{position}\n"
                for arg in resp.get("arguments", []):
                    md += f"  - {arg}\n"
                for sug in resp.get("suggestions", []):
                    md += f"  - 建議：{sug}\n"
                for q in resp.get("questions_to_others", []):
                    md += f"  - 提問 → {q.get('to', '?')}：{q.get('question', '')}\n"
                md += "\n"

            md += "---\n\n"

        # 決議
        md += f"### 決議：{resolution.get('status', '?')}\n\n"
        if resolution.get("summary"):
            md += f"- **摘要**：{resolution['summary']}\n"
        if resolution.get("decision"):
            md += f"- **決策**：{resolution['decision']}\n"
        for issue in resolution.get("remaining_issues", []):
            md += f"  - 剩餘：{issue}\n"

        # Action items
        for ai in resolution.get("action_items", []):
            assignee = ai.get("assignee", "?") if isinstance(ai, dict) else "?"
            task = ai.get("task", str(ai)) if isinstance(ai, dict) else str(ai)
            md += f"- **待辦** ({assignee})：{task}\n"

        if resolution.get("escalated_to_human"):
            md += f"- **已升級至人類裁決**\n"

        return md

    @staticmethod
    def safe_mom_filename(name: str) -> str:
        """清理檔名，保留中文字元"""
        for ch in [':', '/', '\\', '<', '>', '"', '|', '?', '*']:
            name = name.replace(ch, '_')
        return name.strip()

    def save_spec_md(self, md: str, round_num: int):
        filepath = self.output_dir / f"spec_{round_num}.md"
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md)

    def load_spec_md(self, round_num: int) -> str:
        filepath = self.output_dir / f"spec_{round_num}.md"
        if not filepath.exists():
            return ""
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    def append_uml_to_spec(self, spec_md: str, uml_data: Dict[str, Any]) -> str:
        uml_section = "## 附錄 — UML 系統模型\n\n"

        models = uml_data.get("models", [])
        for model in models:
            name = model.get("name", "Unnamed")
            model_type = model.get("type", "")
            plantuml = model.get("plantuml", "")
            uml_section += f"### {name} ({model_type})\n\n"
            if plantuml:
                uml_section += f"```plantuml\n{plantuml}\n```\n\n"

        ast = uml_data.get("ast", {})
        components = ast.get("components", [])
        relationships = ast.get("relationships", [])

        if components:
            uml_section += "### 系統元件\n\n"
            for c in components:
                uml_section += f"- **{c.get('name', '')}** ({c.get('type', '')})\n"
                attrs = c.get("attributes", [])
                methods = c.get("methods", [])
                if attrs:
                    uml_section += f"  - 屬性: {', '.join(str(a) for a in attrs)}\n"
                if methods:
                    uml_section += f"  - 方法: {', '.join(str(m) for m in methods)}\n"
            uml_section += "\n"

        if relationships:
            uml_section += "### 元件關係\n\n"
            for r in relationships:
                uml_section += f"- {r.get('from', '')} → {r.get('to', '')} ({r.get('type', '')}): {r.get('description', '')}\n"
            uml_section += "\n"

        # 若 spec_md 已有附錄章節，替換之（支援中英文標題）
        appendix_pattern = r'##\s+(?:附錄|7\.\s*Appendices).*$'
        if re.search(appendix_pattern, spec_md, flags=re.DOTALL):
            spec_md = re.sub(appendix_pattern, '', spec_md, flags=re.DOTALL).rstrip()

        return spec_md + "\n\n" + uml_section.strip() + "\n"

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

        for section_data in srs_data.get("srs", []):
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
