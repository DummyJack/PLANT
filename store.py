import json

from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

# I/O 層：負責 JSON 和 Markdown 檔案的讀寫
class Store:
    def __init__(self, base_dir: str = ".", project_id: Optional[str] = None):
        self.base_dir = Path(base_dir)
        self.project_id = project_id
        
        # 基礎目錄
        self.config_dir = self.base_dir / "config"
        self.projects_dir = self.base_dir / "projects"
        self.log_dir = self.base_dir / "log"  # log 統一放在外面
        
        # 如果沒有 project_id，只初始化基礎目錄（用於專案管理）
        if not project_id:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            self.projects_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir.mkdir(parents=True, exist_ok=True)
            return
        
        # 設置專案特定目錄
        self.project_dir = self.projects_dir / project_id
        self.artifact_dir = self.project_dir / "artifact"
        self.output_dir = self.project_dir / "output"
        
        # 確保所有目錄存在
        for dir_path in [self.config_dir, self.artifact_dir, self.output_dir, self.log_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    # ===== 專案管理 =====
    
    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有專案"""
        projects = []
        if not self.projects_dir.exists():
            return projects
        
        for project_path in sorted(self.projects_dir.iterdir()):
            if project_path.is_dir():
                # 讀取 artifact.json 獲取專案資訊
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
        """創建新專案，返回 project_id"""
        # 使用時間戳作為 project_id
        timestamp = datetime.now().strftime("%H%M%S")
        project_id = f"{timestamp}"
        
        # 創建專案目錄
        project_dir = self.projects_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        return project_id
    
    def load_artifact(self) -> Optional[Dict[str, Any]]:
        """載入當前專案的 artifact"""
        artifact_file = self.artifact_dir / "artifact.json"
        if not artifact_file.exists():
            return None
        
        with open(artifact_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # ===== JSON 讀寫 =====
    
    def load_json(self, filepath: str) -> Dict[str, Any]:
        """載入 JSON 檔案"""
        path = Path(filepath)
        if not path.is_absolute():
            path = self.base_dir / filepath
        
        if not path.exists():
            raise FileNotFoundError(f"檔案不存在: {path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        """儲存 JSON 檔案"""
        path = Path(filepath)
        if not path.is_absolute():
            path = self.base_dir / filepath
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
    
    # ===== Artifact 相關 =====
    
    def save_artifact(self, data: Dict[str, Any]):
        """儲存 artifact.json"""
        self.save_json(data, self.artifact_dir / "artifact.json")
    
    def load_mom(self) -> Dict[str, Any]:
        """載入 mom.json"""
        mom_path = self.artifact_dir / "mom.json"
        if not mom_path.exists():
            return {"rounds": []}
        return self.load_json(mom_path)
    
    def save_mom(self, data: Dict[str, Any]):
        """儲存 mom.json（只保存最新版本）"""
        self.save_json(data, self.artifact_dir / "mom.json")
    
    def load_draft(self) -> Dict[str, Any]:
        """載入 draft.json（需求草稿）"""
        draft_path = self.artifact_dir / "draft.json"
        if not draft_path.exists():
            return {}
        return self.load_json(draft_path)
    
    def load_uml(self) -> Dict[str, Any]:
        """載入 uml.json"""
        uml_path = self.artifact_dir / "uml.json"
        if not uml_path.exists():
            return {}
        return self.load_json(uml_path)
    
    def save_uml(self, data: Dict[str, Any], round_num: int):
        """儲存 uml.json（從 uml_1.json 開始）"""
        # 只保存帶輪次的版本（uml_1.json, uml_2.json, ...）
        self.save_json(data, self.artifact_dir / f"uml_{round_num}.json")
    
    def save_draft(self, data: Dict[str, Any], round_num: int):
        """儲存 draft.json（從 draft_1.json 開始）"""
        # 只保存帶輪次的版本（draft_1.json, draft_2.json, ...）
        self.save_json(data, self.artifact_dir / f"draft_{round_num}.json")
    
    def save_srs(self, data: Dict[str, Any]):
        """儲存 srs.json"""
        self.save_json(data, self.artifact_dir / "srs.json")
    
    # ===== Config 相關 =====
    
    def load_config(self) -> Dict[str, Any]:
        """載入 config.json"""
        config_path = self.config_dir / "config.json"
        return self.load_json(config_path)
    
    def load_spec_template(self) -> Dict[str, Any]:
        """載入 Spec 模板（包含 draft 和 ieee_29148 兩個結構）"""
        template_path = self.config_dir / "spec.json"
        if not template_path.exists():
            raise FileNotFoundError(f"spec.json 模板不存在: {template_path}")
        return self.load_json(template_path)
    
    def save_config(self, config: Dict[str, Any]) -> None:
        """儲存 config.json"""
        config_path = self.config_dir / "config.json"
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    # ===== Markdown 相關 =====
    
    def save_markdown(self, content: str, filename: str):
        """儲存 Markdown 檔案到 output 目錄"""
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    
    # 產生衝突報告(report.md)
    def generate_report_markdown(self, reports: List[Dict]) -> str:
        md = "# 需求衝突報告\n\n"
        if reports:
            for report in reports:
                md += f"### {report['id']}: {report['title']}\n\n"
                md += f"衝突描述: {report['description']}\n\n"
                md += f"涉及利害關係人: {', '.join(report['stakeholder_names'])}\n\n"
                md += f"衝突類型: {report.get('conflict_type', '未分類')}\n\n"
        else:
            md += "## 衝突分析\n\n未識別出明顯衝突。"
        
        return md

    # 將 MoM 轉換為 Markdown 格式
    def generate_mom_markdown(self, mom_data: Dict[str, Any]) -> str:
        md = "# 會議記錄\n\n"
        
        rounds = mom_data.get("rounds", [])
        
        for round_data in rounds:
            round_num = round_data.get("round", "?")
            timestamp = round_data.get("timestamp", "")
            
            md += f"## Round {round_num}\n\n"
            md += f"**時間**：{timestamp}\n\n"
            
            # 整合人類決策：將 stages 中的 Human 決策統一收集
            stages = round_data.get("stages", [])
            human_decisions = []
            other_stages = []
            
            for stage in stages:
                if stage.get("agent") == "Human":
                    human_decisions.append(stage)
                else:
                    other_stages.append(stage)
            
            # 顯示非人類決策的階段
            if other_stages:
                md += "### 階段流程\n\n"
                
                for idx, stage in enumerate(other_stages, 1):
                    stage_name = stage.get("stage", "")
                    agent = stage.get("agent", "")
                    description = stage.get("description", "")
                    stage_timestamp = stage.get("timestamp", "")
                    
                    md += f"#### {idx}. {stage_name}\n\n"
                    md += f"- **執行代理**：{agent}\n"
                    md += f"- **描述**：{description}\n"
                    md += f"- **時間**：{stage_timestamp}\n"
                    
                    # 處理 outputs - 使用 JSON 格式
                    outputs = stage.get("outputs", {})
                    if outputs:
                        md += f"- **輸出**：\n\n"
                        md += "```json\n"
                        md += json.dumps(outputs, ensure_ascii=False, indent=2)
                        md += "\n```\n"
                    
                    md += "\n"
            
            # 統一顯示人類決策
            if human_decisions:
                md += "### 人類決策\n\n"
                
                for idx, decision in enumerate(human_decisions, 1):
                    stage_name = decision.get("stage", "")
                    description = decision.get("description", "")
                    stage_timestamp = decision.get("timestamp", "")
                    
                    md += f"#### {idx}. {stage_name}\n\n"
                    md += f"- **描述**：{description}\n"
                    md += f"- **時間**：{stage_timestamp}\n"
                    
                    # 輸出使用 JSON 格式
                    outputs = decision.get("outputs", {})
                    if outputs:
                        md += f"- **輸出**：\n\n"
                        md += "```json\n"
                        md += json.dumps(outputs, ensure_ascii=False, indent=2)
                        md += "\n```\n"
                    
                    md += "\n"
        
        return md
    
    # 將 SRS 轉換為 Markdown 格式
    def generate_srs_markdown(self, srs_data: Dict[str, Any]) -> str:
        md = "# Software Requirements Specification (SRS)\n\n"
        
        sections = srs_data.get("ieee_29148", [])
        
        def process_subsection(subsection, level=3):
            nonlocal md
            subsection_id = subsection.get("id", "")
            content = subsection.get("content", "")
            nested_subsections = subsection.get("subsection", [])
            
            # 標題
            md += f"{'#' * level} {subsection_id}\n\n"
            
            # 內容
            if isinstance(content, list):
                for item in content:
                    md += f"- {item}\n"
                md += "\n"
            elif content:
                md += f"{content}\n\n"
            
            # 處理巢狀子章節
            if nested_subsections:
                for nested in nested_subsections:
                    process_subsection(nested, level + 1)
        
        # 處理每個主要章節
        for section_data in sections:
            section_title = section_data.get("section", "")
            section_content = section_data.get("content", None)
            subsections = section_data.get("subsection", [])
            
            md += f"## {section_title}\n\n"
            
            # 處理直接的 content（如果有）
            if section_content is not None:
                if isinstance(section_content, list):
                    # 檢查是否為 Appendices（content 是字典陣列）
                    if section_content and isinstance(section_content[0], dict):
                        # 處理 Appendices
                        for item in section_content:
                            item_id = item.get("id", "")
                            plantuml_code = item.get("plantuml", "")
                            
                            md += f"### {item_id}\n\n"
                            
                            # 插入 PlantUML 圖表
                            if plantuml_code:
                                md += "```plantuml\n"
                                md += plantuml_code
                                md += "\n```\n\n"
                    else:
                        # 一般的字串陣列
                        for item in section_content:
                            md += f"- {item}\n"
                        md += "\n"
                elif isinstance(section_content, str):
                    md += f"{section_content}\n\n"
            
            # 處理子章節
            if subsections:
                for subsection in subsections:
                    process_subsection(subsection)
        
        return md
    
    # 將 draft 轉換為 Markdown 格式
    def generate_draft_markdown(self, draft: Dict[str, Any]) -> str:
        md = ""
        
        sections = draft.get("draft", [])
        
        for section_data in sections:
            section_title = section_data.get("section", "")
            md += f"\n## {section_title}\n\n"
            
            # 處理直接的 content
            if "content" in section_data:
                content = section_data["content"]
                if isinstance(content, str):
                    md += f"{content}\n\n"
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, str):
                            md += f"- {item}\n"
                        elif isinstance(item, dict):
                            # 處理 System Stakeholders 格式
                            if "stakeholder_name" in item:
                                md += f"### {item.get('stakeholder_name', '')}\n"
                                md += f"**關注點**: {item.get('concern', '')}\n"
                                md += f"**需求**:\n"
                                for req in item.get('requirement', []):
                                    md += f"  - {req}\n"
                                md += "\n"
                            # 處理 Conflicting Requirements 格式
                            elif "id" in item and "stakeholder_name" in item:
                                md += f"### {item.get('id', '')}\n\n"
                                md += f"**涉及利害關係人**: {', '.join(item.get('stakeholder_name', []))}\n\n"
                                md += f"**描述**: {item.get('description', '')}\n\n"
                                md += f"**解決方案**:\n"
                                solutions = item.get('solutions', [])
                                if isinstance(solutions, list):
                                    for sol in solutions:
                                        md += f"  - {sol}\n"
                                else:
                                    md += f"  {solutions}\n"
                                md += "\n"
                            # 處理其他字典格式（如果有的話）
                            else:
                                md += f"- {json.dumps(item, ensure_ascii=False)}\n"
                    md += "\n"
            
            # 處理 subsection
            if "subsection" in section_data:
                for subsection in section_data["subsection"]:
                    subsection_id = subsection.get("id", "")
                    md += f"### {subsection_id}\n\n"
                    
                    sub_content = subsection.get("content", [])
                    if isinstance(sub_content, str):
                        # content 是字串
                        md += f"{sub_content}\n\n"
                    elif isinstance(sub_content, list):
                        # content 是陣列
                        for item in sub_content:
                            if isinstance(item, str):
                                md += f"- {item}\n"
                            elif isinstance(item, dict):
                                item_id = item.get("id", "")
                                item_content = item.get("content", "")
                                md += f"**{item_id}**\n{item_content}\n\n"
                        md += "\n"
        
        return md
    
    # ===== PlantUML 相關 =====
    
    # 將模型中的 PlantUML 程式碼儲存為 .plantuml
    def save_plantuml_files(self, model_data: Dict[str, Any]) -> None:
        models = model_data.get("models", [])
        
        for model in models:
            model_name = model.get("name", "unnamed")
            plantuml_code = model.get("plantuml", "")
            
            if plantuml_code:
                # 清理檔案名稱（移除特殊字元）
                safe_name = "".join(c for c in model_name if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"{safe_name}.plantuml"
                filepath = self.output_dir / filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(plantuml_code)
                
                print(f"✓ 儲存 PlantUML: {filename}")