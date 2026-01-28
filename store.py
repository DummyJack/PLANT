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
    
    # 將 JSON 資料轉換為 Markdown 格式
    def generate_markdown(self, json_data: Dict[str, Any]) -> str:
        md = ""
        md += json.dumps(json_data, ensure_ascii=False, indent=2)
        
        return md
    
    # ===== PlantUML 相關 =====
    
    # 將模型中的 PlantUML 程式碼儲存為 .plantuml 檔案
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