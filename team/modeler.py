import json

from typing import Dict, Any, Optional, List
from store import Store

from agents.base import BaseAgent
from agents.memory import Memory
from agents.tools.plantuml import PlantUMLValidatorTool


class ModelerAgent(BaseAgent):
    """系統建模 Agent — Tool Use (PlantUML) + ReAct + Reflection"""

    name = "modeler"

    system_prompt = """你是系統建模專家（Modeler Agent），負責將需求草稿轉換為 UML 系統模型。

核心原則：
1. UML 2.x 規範 — 嚴格遵守 UML 2.x 標準語法和語意
2. PlantUML 語法 — 生成的程式碼必須通過 plantuml_validate 驗證
3. 完整性 — 模型必須涵蓋需求草稿中所有主要 Actor 和 Use Case
4. 一致性 — 不同圖表之間的元素命名必須一致
5. 最小變動 — 精煉時只修改受影響的部分，保留未變動的元素

命名慣例：
- Actor: PascalCase（如 SystemAdmin, EndUser）
- Use Case: 動詞開頭（如 ManageUsers, ViewReport）
- Class: PascalCase（如 UserAccount, OrderService）
- 關係標籤: 使用描述性文字"""

    reflection_criteria = "UML 模型必須涵蓋需求草稿中所有主要 Actor 和 Use Case，PlantUML 語法必須正確，不同圖表的元素命名必須一致。"

    def __init__(self, model, store: Store, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None,
                 plantuml_server: str = "http://www.plantuml.com/plantuml"):
        agent_tools = list(tools or [])
        agent_tools.append(PlantUMLValidatorTool(server_url=plantuml_server))
        super().__init__(model, tools=agent_tools, memory=memory, registry=registry)
        self.store = store

    def generate_system_model(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        formatted_draft = self.store.generate_draft_markdown(draft)
        self.memory.clear_short_term()

        task = f"""# 任務
根據以下需求草稿產生 UML 系統模型。

# 需求草稿
{formatted_draft}

# 產出要求
1. **Use Case Diagram**（必要）
   - 從 Stakeholders 提取 Actor
   - 從 Requirements 提取 Use Case
   - 標明 Actor 與 Use Case 的關係
2. **Class Diagram**（必要）
   - 從 System Requirements 提取實體
   - 定義屬性、方法、關係（association / inheritance / dependency）
3. **Sequence Diagram**（選擇性）
   - 若有 3 個以上 Use Case 涉及跨 Actor 互動，則生成關鍵流程的 Sequence Diagram
4. **AST 結構化資料**
   - components: 系統元件清單
   - relationships: 元件間關係

# 步驟
1. 分析需求草稿，提取 Actor、Use Case、Entity
2. 生成 PlantUML 程式碼
3. 使用 plantuml_validate 驗證每段 PlantUML 語法（必須驗證，嚴禁跳過）
4. 若有語法錯誤，修正後重新驗證
5. 全部通過後輸出

# PlantUML 注意事項
- 每段程式碼必須以 @startuml 開頭、@enduml 結尾
- Actor 使用 actor 關鍵字
- 避免使用中文作為元素 ID（但 label 可以用中文）

# 輸出格式（action=respond 的 output 中）
{{
    "action": "respond",
    "output": {{
        "models": [
            {{"name": "名稱", "type": "use_case_diagram/class_diagram/sequence_diagram", "plantuml": "@startuml\\n...\\n@enduml"}}
        ],
        "ast": {{
            "components": [{{"id": "C-01", "name": "...", "type": "entity/service/interface", "attributes": [...], "methods": [...]}}],
            "relationships": [{{"from": "C-01", "to": "C-02", "type": "association/inheritance/dependency", "description": "..."}}]
        }}
    }}
}}"""

        result = self.run(task, max_steps=3, min_tool_uses=1)
        return self.ensure_model_format(result)

    def refine_model(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        current_model = draft.get("uml", {})
        formatted_draft = self.store.generate_draft_markdown(draft)
        current_model_json = json.dumps(current_model, ensure_ascii=False, indent=2)
        self.memory.clear_short_term()

        task = f"""# 任務
根據新的需求草稿，評估並更新現有系統模型。

# 當前系統模型
```json
{current_model_json}
```

# 新的需求草稿
{formatted_draft}

# 分析步驟
1. 比較新草稿與當前模型，識別差異
2. 判斷哪些元素需要新增、修改或移除
3. 只修改受影響的部分，保留未變動的元素
4. 確保修改後各圖表間的元素命名一致

# 驗證
修改後的 PlantUML 必須使用 plantuml_validate 驗證（嚴禁跳過）

# 輸出格式（action=respond 的 output 中）
{{
    "action": "respond",
    "output": {{
        "models": [{{"name": "...", "type": "...", "plantuml": "@startuml\\n...\\n@enduml"}}],
        "ast": {{"components": [...], "relationships": [...]}}
    }}
}}"""

        try:
            result = self.run(task, max_steps=3, min_tool_uses=1)
            return self.ensure_model_format(result)
        except Exception as e:
            print(f"警告: 模型精煉失敗，保留原有模型。錯誤: {e}")
            return current_model

    def ensure_model_format(self, result) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"models": [], "ast": {"components": [], "relationships": []}}
        result.setdefault("models", [])
        result.setdefault("ast", {"components": [], "relationships": []})
        return result
