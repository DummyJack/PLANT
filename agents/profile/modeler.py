import json

from typing import Dict, Any, Optional, List

from agents.base import BaseAgent


class ModelerAgent(BaseAgent):
    """系統建模 Agent — 產生 UML 系統模型（PlantUML 格式）"""

    name = "modeler"

    system_prompt = """你是系統建模專家，負責將需求規格轉換為 UML 系統模型。

核心原則：
1. UML 2.x 規範 — 嚴格遵守 UML 2.x 標準語法和語意
2. PlantUML 語法 — 生成的程式碼須符合 PlantUML 語法
3. 完整性 — 模型必須涵蓋需求規格中所有主要 Actor 和 Use Case
4. 一致性 — 不同圖表之間的元素命名必須一致
5. 最小變動 — 精煉時只修改受影響的部分，保留未變動的元素

命名慣例：
- Actor: PascalCase（如 SystemAdmin, EndUser）
- Use Case: 動詞開頭（如 ManageUsers, ViewReport）
- Class: PascalCase（如 UserAccount, OrderService）
- 關係標籤: 使用描述性文字"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools or [], registry=registry)

    # 覆寫：議題討論回應

    def respond_to_topic(self, topic, previous_responses=None):
        """以系統建模專家身份回應議題"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = []
            for r in previous_responses:
                agent = r.get("agent", "?")
                resp = r.get("response", {})
                content = resp.get("content", resp.get("position", ""))
                parts.append(f"【{agent}】{content}")
            prev_text = "\n# 前面的發言\n" + "\n".join(parts)

        user_prompt = f"""你正在以系統建模專家的身份參與需求討論。

{topic_text}
{prev_text}

# 回應要求
1. position: 從系統架構和建模角度，這個議題的影響和你的立場
2. arguments: 基於 UML 建模、系統設計、元件關係等面向的論點
3. suggestions: 從系統架構角度提出的建議（如何影響 Use Case、Class、元件關係等）
4. questions_to_others: 想請其他角色回答的問題（可為空陣列）

# 約束
- 聚焦於系統架構、建模、元件設計的觀點
- 評估需求變更對 UML 模型的影響
- 指出可能的架構風險或設計矛盾

輸出 JSON:
{{{{
    "position": "從系統架構角度，我認為...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"],
    "questions_to_others": [{{{{"to": "agent名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "position": response.get("position", ""),
            "arguments": response.get("arguments", []),
            "suggestions": response.get("suggestions", []),
            "questions_to_others": response.get("questions_to_others", []),
        }

    def generate_system_model(self, spec_md: str) -> Dict[str, Any]:
        task = f"""# 任務
根據以下需求規格產生 UML 系統模型。

# 需求規格
{spec_md}

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
1. 分析需求規格，提取 Actor、Use Case、Entity
2. 生成 PlantUML 程式碼（每段以 @startuml 開頭、@enduml 結尾）
3. Actor 使用 actor 關鍵字，避免使用中文作為元素 ID（label 可用中文）

# 輸出格式（直接輸出以下 JSON）
{{
    "models": [
        {{"name": "名稱", "type": "use_case_diagram/class_diagram/sequence_diagram", "plantuml": "@startuml\\n...\\n@enduml"}}
    ],
    "ast": {{
        "components": [{{"id": "C-01", "name": "...", "type": "entity/service/interface", "attributes": [...], "methods": [...]}}],
        "relationships": [{{"from": "C-01", "to": "C-02", "type": "association/inheritance/dependency", "description": "..."}}]
    }}
}}"""

        messages = self.build_direct_messages(task)
        result = self.model.chat_json(messages)
        return self.ensure_model_format(result)

    def refine_model(self, spec_md: str, prev_uml: Dict[str, Any] = None) -> Dict[str, Any]:
        current_model = prev_uml or {}
        current_model_json = json.dumps(current_model, ensure_ascii=False, indent=2)

        task = f"""# 任務
根據新的需求規格，評估並更新現有系統模型。

# 當前系統模型
```json
{current_model_json}
```

# 新的需求規格
{spec_md}

# 分析步驟
1. 比較新規格與當前模型，識別差異
2. 判斷哪些元素需要新增、修改或移除
3. 只修改受影響的部分，保留未變動的元素
4. 確保修改後各圖表間的元素命名一致

# 輸出格式（直接輸出以下 JSON）
{{
    "models": [{{"name": "...", "type": "...", "plantuml": "@startuml\\n...\\n@enduml"}}],
    "ast": {{"components": [...], "relationships": [...]}}
}}"""

        try:
            messages = self.build_direct_messages(task)
            result = self.model.chat_json(messages)
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
