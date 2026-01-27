import sys
from typing import Dict, Any
import json
from pathlib import Path

class ModelerAgent:
    """
    Modeler Agent: 系統模型建立
        - 依 Spec 建立系統模型
        - 產出 uml.md 和 uml.json
    """
    
    system_prompt = "你是系統 UML 模型建構師，擅長將系統規格轉換為 UML 模型和 plantuml 程式碼。"

    def __init__(self, model):
        self.model = model
    
    def generate_system_model(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        # 根據 draft.json 產生系統模型（plantuml 和 ast）
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)

        user_prompt = f"""需求草稿：
                {draft_text}

                請根據需求草稿產生系統模型，包括：
                1. PlantUML 類別圖或組件圖
                2. AST（Abstract Syntax Tree）結構

                請以 JSON 格式回應：
                {{{{
                "models": [
                    {{{{
                    "id": "MODEL-01",
                    "name": "模型名稱",
                    "type": "class/component/sequence",
                    "plantuml": "@startuml\\n...\\n@enduml",
                    "ast": {{{{
                        "type": "root",
                        "children": [
                        {{{{
                            "type": "class/interface/component",
                            "value": "名稱",
                            "visibility": "public/private",
                            "children": []
                        }}}}
                        ]
                    }}}}
                    }}}}
                ]
                }}}}"""
        
        try:
            model_data = self.model.generate_json(user_prompt, self.system_prompt)
            return model_data
        except Exception as e:
            raise RuntimeError(f"ModelerAgent 產生系統模型失敗，原因: {str(e)}")
    
    def refine_model(self, current_model: Dict, draft: Dict) -> Dict[str, Any]:
        # 多輪時根據新的 draft 調整/刪除/新增模型
        current_text = json.dumps(current_model, ensure_ascii=False, indent=2)
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        
        user_prompt = f"""目前的系統模型：
                {current_text}

                新的需求草稿：
                {draft_text}

                請根據新需求調整系統模型：
                - 新增：新的組件或類別
                - 修改：調整現有結構
                - 刪除：移除不需要的部分

                請以 JSON 格式回應，保持相同結構。"""

        
        try:
            response = self.model.generate_json(user_prompt, self.system_prompt)
            return response
        except Exception as e:
            return current_model
    
    def save_plantuml_files(self, model_data: Dict[str, Any], output_dir: Path) -> None:
        """
        將模型中的 PlantUML 程式碼儲存為 .plantuml 檔案
        
        Args:
            model_data: 模型資料
            output_dir: 輸出目錄
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for model in model_data.get("models", []):
            model_name = model.get('name', 'model')
            plantuml_content = model.get('plantuml', '')
            
            if plantuml_content:
                # 清理檔案名稱（移除特殊字元）
                safe_name = "".join(c for c in model_name if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"{safe_name}.plantuml"
                filepath = output_dir / filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(plantuml_content)
                
                print(f"✓ 產生 PlantUML 檔案: {filename}")
