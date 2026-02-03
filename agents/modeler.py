import json

from typing import Dict, Any

# 系統建模者，需求草稿產生系統模型（PlantUML 程式碼、AST 結構化資料）
class ModelerAgent:
    def __init__(self, model):
        self.model = model
        self.system_prompt = "你是系統建模專家，任務是將需求轉換為系統模型。"

    # 根據需求草稿產生系統模型
    def generate_system_model(self, draft: Dict[str, Any]) -> Dict[str, Any]:

        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)

        user_prompt = f"""需求草稿：
{draft_text}

請根據需求產生 UML 系統模型，包含：
1. PlantUML 圖（Class Diagram, Use Case Diagram, ...）
2. AST 結構化

請以 JSON 格式回應：
{{{{
"models": [
    {{{{
    "name": "title 加上什麼圖",
    "type": "class_diagram",
    "plantuml": "@startuml\\n...\\n@enduml"
    }}}}
],
"ast": {{{{
    "components": [],
    "relationships": []
}}}}
}}}}"""

        print(user_prompt)
        
        response = self.model.generate_json(user_prompt)
        return response

    # 第二輪以上，原有基礎上繼續調整模型
    def refine_model(
        self, current_model: Dict[str, Any], draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        current_text = json.dumps(current_model, ensure_ascii=False, indent=2)
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)

        user_prompt = f"""目前的系統模型：
                {current_text}

                新的需求草稿：
                {draft_text}

                請評估新的需求草稿，判斷是否需要調整系統模型：
                
                評估步驟：
                1. 分析新需求與現有模型的關係
                2. 判斷是否需要調整（新增、修改、刪除）
                3. 如果不需要調整，保持原有模型不變
                4. 如果需要調整，則進行必要的修改：
                   - 新增：新的組件、類別或關係
                   - 修改：調整現有結構的屬性或行為
                   - 刪除：移除不再需要的部分
                
                重要：只在真正需要時才修改模型，避免不必要的變動。

                請以 JSON 格式回應，保持相同結構。"""

        try:
            response = self.model.generate_json(user_prompt, self.system_prompt)
            return response
        except Exception as e:
            return current_model
