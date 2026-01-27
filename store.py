import json
from typing import Dict, Any
from pathlib import Path

# I/O 層：負責 JSON 和 Markdown 檔案的讀寫
class Store:
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.artifact_dir = self.base_dir / "artifact"
        self.config_dir = self.base_dir / "config"
        self.output_dir = self.base_dir / "output"
        self.log_dir = self.base_dir / "log"
        
        # 確保目錄存在
        for dir_path in [self.artifact_dir, self.config_dir, self.output_dir, self.log_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
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
    
    def load_artifact(self) -> Dict[str, Any]:
        """載入 artifact.json"""
        artifact_path = self.artifact_dir / "artifact.json"
        if not artifact_path.exists():
            # 回傳初始結構
            return {
                "rough_idea": "",
                "stakeholders": [],
                "analyse": {
                    "system_description": "",
                    "pairs": [],
                    "report": []
                },
                "feedback": [],
                "decisions": []
            }
        return self.load_json(artifact_path)
    
    def save_artifact(self, data: Dict[str, Any]):
        """儲存 artifact.json"""
        self.save_json(data, self.artifact_dir / "artifact.json")
    
    def load_mom(self) -> Dict[str, Any]:
        """載入 mom.json（會議記錄）"""
        mom_path = self.artifact_dir / "mom.json"
        if not mom_path.exists():
            return {"rounds": []}
        return self.load_json(mom_path)
    
    def save_mom(self, data: Dict[str, Any]):
        """儲存 mom.json"""
        self.save_json(data, self.artifact_dir / "mom.json")
    
    def load_draft(self) -> Dict[str, Any]:
        """載入 draft.json（需求草稿）"""
        draft_path = self.artifact_dir / "draft.json"
        if not draft_path.exists():
            return {}
        return self.load_json(draft_path)
    
    def save_draft(self, data: Dict[str, Any]):
        """儲存 draft.json"""
        self.save_json(data, self.artifact_dir / "draft.json")
    
    def load_srs(self) -> Dict[str, Any]:
        """載入 srs.json"""
        srs_path = self.artifact_dir / "srs.json"
        if not srs_path.exists():
            return {}
        return self.load_json(srs_path)
    
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
    
    # ===== Markdown 輸出 =====
    
    def save_markdown(self, content: str, filename: str):
        """儲存 Markdown 檔案到 output 目錄"""
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def load_markdown(self, filename: str) -> str:
        """載入 Markdown 檔案"""
        filepath = self.output_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"檔案不存在: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    
    # ===== Log 相關 =====
    
    def append_log(self, log_entry: str, log_file: str = "system.log"):
        """追加 log 到檔案"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_path = self.log_dir / log_file
        
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {log_entry}\n")
