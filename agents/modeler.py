from typing import Dict, Any
import json

class ModelerAgent:
    """
    Modeler Agent: 系統建模者
        - 根據需求草稿產生系統模型（PlantUML、AST）
        - 支援多輪調整（新增、刪除、修改）
    """
    
    def __init__(self, model):
        self.model = model
        self.system_prompt = "你是系統建模專家，擅長將需求轉換為系統模型（UML 和 AST）。"
    
    def generate_system_model(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """
        根據需求草稿產生系統模型
        
        Args:
            draft: 需求草稿
        
        Returns:
            Dict: 包含 plantuml 和 ast 的模型資料
        """
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        
        user_prompt = f"""需求草稿：
                {draft_text}

                請根據需求產生系統模型，包含：
                1. PlantUML 圖表（類別圖、循序圖等）
                2. 抽象語法樹 (AST)
                
                請以 JSON 格式回應：
                {{{{
                "models": [
                    {{{{
                    "name": "類別圖",
                    "type": "class_diagram",
                    "plantuml": "@startuml\\n...\\n@enduml"
                    }}}}
                ],
                "ast": {{{{
                    "components": [],
                    "relationships": []
                }}}}
                }}}}"""
        
        response = self.model.generate_json(user_prompt, self.system_prompt)
        return response
    
    def refine_model(
        self,
        current_model: Dict[str, Any],
        draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        根據新需求調整現有模型
        
        Args:
            current_model: 目前的系統模型
            draft: 新的需求草稿
        
        Returns:
            Dict: 更新後的系統模型
        """
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
