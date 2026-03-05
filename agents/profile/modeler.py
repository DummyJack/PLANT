import json

from typing import Dict, Any, Optional, List

from agents.base import BaseAgent


class ModelerAgent(BaseAgent):
    """系統建模 Agent — 產生 UML 系統模型（PlantUML 格式）+ 設計衝突辨識"""

    name = "modeler"

    system_prompt = """你是系統建模專家，負責將需求規格轉換為 UML 系統模型。

核心原則：
1. UML 2.x 規範 — 嚴格遵守 UML 2.x 標準語法和語意
2. PlantUML 語法 — 生成的程式碼須符合 PlantUML 語法
3. 完整性 — 模型必須涵蓋需求中所有主要 Actor 和 Use Case
4. 一致性 — 不同圖表之間的元素命名必須一致
5. 最小變動 — 精煉時只修改受影響的部分，保留未變動的元素
6. 衝突敏感 — 識別設計層面或可測試性的衝突

命名慣例：
- Actor: PascalCase（如 SystemAdmin, EndUser）
- Use Case: 動詞開頭（如 ManageUsers, ViewReport）
- Class: PascalCase（如 UserAccount, OrderService）
- 關係標籤: 使用描述性文字"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools or [], registry=registry)

    def generate_system_model(self, requirements: List[Dict], stakeholders: List[Dict]) -> Dict[str, Any]:
        """根據需求產生初始 UML 系統模型"""
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        stakeholders_text = json.dumps(stakeholders, ensure_ascii=False, indent=2)

        task = f"""# 任務
根據以下需求和利害關係人產生 UML 系統模型。

# 需求
{requirements_text}

# 利害關係人
{stakeholders_text}

# 產出要求
1. **Use Case Diagram**（必要）
2. **Class Diagram**（必要）
3. **Sequence Diagram**（選擇性，若有跨 Actor 互動）
（設計/可測試性衝突由 Analyst 在產出模型後統一辨識）

# 輸出格式
{{
    "models": [
        {{"name": "名稱", "type": "use_case_diagram/class_diagram/sequence_diagram", "plantuml": "@startuml\\n...\\n@enduml"}}
    ]
}}"""

        messages = self.build_direct_messages(task)
        result = self.model.chat_json(messages)
        model_data = self.ensure_model_format(result)
        return self.validate_models(model_data)

    def refine_model(self, requirements: List[Dict], prev_models: List[Dict] = None) -> Dict[str, Any]:
        """根據更新的需求精煉系統模型"""
        current_model = {"models": prev_models or []}
        current_model_json = json.dumps(current_model, ensure_ascii=False, indent=2)
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)

        task = f"""# 任務
根據更新後的需求，評估並更新現有系統模型。

# 當前系統模型
```json
{current_model_json}
```

# 更新後的需求
{requirements_text}

# 分析步驟
1. 比較新需求與當前模型，識別差異
2. 只修改受影響的部分，保留未變動的元素
（設計/可測試性衝突由 Analyst 在產出模型後統一辨識）

# 輸出格式
{{
    "models": [{{"name": "...", "type": "...", "plantuml": "@startuml\\n...\\n@enduml"}}]
}}"""

        try:
            messages = self.build_direct_messages(task)
            result = self.model.chat_json(messages)
            model_data = self.ensure_model_format(result)
            return self.validate_models(model_data)
        except Exception as e:
            self.logger.warning(f"模型精煉失敗，保留原有模型。錯誤: {e}")
            return {"models": prev_models or []}

    def ensure_model_format(self, result) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"models": []}
        result.setdefault("models", [])
        return result

    def validate_models(self, model_data: Dict[str, Any]) -> Dict[str, Any]:
        """用 plantuml_validate 工具驗證每個模型的 PlantUML 語法，有錯則自動修正"""
        validator = self.tools.get("plantuml_validate")
        if not validator:
            return model_data

        models = model_data.get("models", [])
        for m in models:
            code = m.get("plantuml", "")
            if not code:
                continue

            result = self.execute_tool("plantuml_validate", {"plantuml_code": code})
            if "通過" in result:
                continue

            self.logger.warning(f"  模型 {m.get('name', '')} 語法有誤，嘗試修正: {result}")
            fixed = self.fix_plantuml(m, result)
            if fixed:
                m["plantuml"] = fixed

        return model_data

    def fix_plantuml(self, model: Dict, error_msg: str) -> Optional[str]:
        """依據錯誤訊息讓 LLM 修正 PlantUML"""
        user_prompt = f"""# 任務
以下 PlantUML 程式碼有語法錯誤，請修正後回傳。

# 模型名稱
{model.get('name', '')}

# 原始程式碼
{model.get('plantuml', '')}

# 驗證錯誤
{error_msg}

# 輸出 JSON
{{{{
    "plantuml": "@startuml\\n...修正後的完整程式碼...\\n@enduml"
}}}}"""

        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages)
            fixed = response.get("plantuml", "")
            if "@startuml" in fixed and "@enduml" in fixed:
                return fixed
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
        
    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        """以系統建模專家身份回應議題"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 若發言中涉及 PlantUML 片段，可先使用 plantuml_validate 驗證語法，再撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""你正在以系統建模專家的身份參與需求討論。

{topic_text}
{prev_text}
{snapshot_text}
{tool_hint}

# 思考與發言流程
1. 先思考：(1) 此議題對系統架構與模型的影響 (2) 不可讓步的架構/建模要點 (3) 可接受調整或折衷的要點
2. 再根據思考結果，撰寫一段完整的發言（statement），聚焦於系統架構、建模、元件設計的觀點
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"expert"）

# 發言風格
- 以系統架構/建模專家在會議中的口吻：說明對模型或架構的影響、取捨與可驗證的建議
- 可說「若需求這樣定，Use Case 圖需要…」「這點會影響到 Class 的職責邊界…」

# 約束
- statement 須聚焦系統架構與建模觀點，評估需求變更對 UML 模型的影響

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }