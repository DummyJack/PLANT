import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Dict, Any, Optional, List

from agents.base import BaseAgent


MODELER_REVIEW_ACTIONS = [
    "assess_impact",
    "update_diagram",
    "validate_diagram",
    "fix_diagram",
    "review_neutrals",
    "done",
]


class ModelerAgent(BaseAgent):
    """系統建模 Agent — 產生 UML 系統模型（PlantUML 格式）+ 設計衝突辨識"""

    name = "modeler"

    system_prompt = """你是一個專業的 UML 系統建模專家，負責將需求規格轉換為 UML 系統模型。

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

    def generate_system_model(
        self, requirements: List[Dict], stakeholders: List[Dict]
    ) -> Dict[str, Any]:
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
- models 陣列中的 name（圖表顯示名稱）請使用繁體中文。plantuml 程式碼內關鍵字維持英文。

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

    def refine_model(
        self, requirements: List[Dict], prev_models: List[Dict] = None
    ) -> Dict[str, Any]:
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
- models 陣列中的 name（圖表顯示名稱）請使用繁體中文。plantuml 程式碼內關鍵字維持英文。

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
        if not models:
            return model_data

        # 並行執行所有驗證
        validation_results = {}

        def validate_one(idx: int, m: Dict) -> tuple:
            code = m.get("plantuml", "")
            if not code:
                return (idx, m, None)
            result = self.execute_tool("plantuml_validate", {"plantuml_code": code})
            return (idx, m, result)

        max_workers = min(len(models), 6)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(validate_one, i, m): i for i, m in enumerate(models)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    i, m, result = future.result()
                    validation_results[i] = (m, result)
                except Exception as e:
                    self.logger.warning(f"  模型驗證失敗: {e}")
                    validation_results[idx] = (models[idx], None)

        # 依序處理需修正的模型（fix_plantuml 呼叫 LLM，維持順序並控制並發）
        for i in range(len(models)):
            m, result = validation_results.get(i, (models[i], None))
            if result is None:
                continue
            if "通過" in result:
                continue
            self.logger.warning(
                f"  模型 {m.get('name', '')} 語法有誤，嘗試修正: {result}"
            )
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

    def cross_review_neutrals(self, artifact: Dict) -> list:
        """從系統架構角度複審 Neutral 項目，找出設計層衝突。"""
        neutrals = [
            c for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
        ]
        if not neutrals:
            return []

        models = artifact.get("system_models", {}).get("models", [])
        context = {
            "neutrals": neutrals,
            "requirements": artifact.get("requirements", []),
            "system_models": [
                {"name": m.get("name"), "type": m.get("type"),
                 "plantuml": m.get("plantuml", "")}
                for m in models
            ],
        }
        task = """你是系統建模專家。以下是 Analyst 判定為「無衝突（Neutral）」的項目。
請對照系統模型（UML 圖），從架構設計角度複審，判斷是否有被遺漏的設計層衝突。

常見盲點：
- 兩個 Use Case 看似獨立，但共用同一個 Component 導致資源競爭
- 兩條需求從文字看無衝突，但對映到 Class Diagram 後發現職責邊界衝突
- 某需求的 Sequence 流程會阻塞另一需求的關鍵路徑

輸出 JSON：
{
    "upgraded_conflicts": [
        {
            "original_neutral_id": "NF-XX",
            "description": "為什麼這其實是衝突",
            "conflict_type": "Logical/Technical/Resource/Temporal/Data/State/Priority/Scope",
            "requirement_ids": ["R-XX", "R-YY"],
            "architecture_evidence": "架構依據（涉及的模型元素或設計衝突）"
        }
    ],
    "review_summary": "複審摘要"
}
若所有 Neutral 確實無衝突，upgraded_conflicts 為空陣列。
文字請使用繁體中文。只輸出 JSON。"""

        messages = self.build_direct_messages(task, context=context)
        try:
            result = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Modeler Neutral 複審失敗: {e}")
            return []

        upgraded = result.get("upgraded_conflicts", [])
        if not isinstance(upgraded, list):
            return []

        if upgraded:
            self.logger.info(
                f"Modeler 複審發現 {len(upgraded)} 個 Neutral 可能有衝突"
            )
        return upgraded

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 若發言中涉及 PlantUML 片段，可先使用 plantuml_validate 驗證語法，再撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""{topic_text}
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
- 依你的立場投票（vote）：agreed 表示可達成共識；unresolved 表示仍有衝突需升級
- statement、open_questions 的 question 請使用繁體中文

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "vote": "agreed 或 unresolved",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "vote": response.get("vote", "unresolved"),
            "open_questions": response.get("open_questions", []),
        }

    # ===== 子 OODA 循環 =====

    def run_review_loop(self, artifact, recent_discussions=None, max_iterations=5):
        """Modeler 子 OODA：評估影響 → 更新圖表 → 驗證修正。"""
        observation = None
        actions_taken = []
        pending_issues = []

        for i in range(max_iterations):
            state = self._build_review_state(
                artifact, recent_discussions, actions_taken, i, max_iterations,
            )
            decision = self.decide_next_review_action(state, observation)
            action = decision.get("action", "done")
            self.logger.info(
                f"  Modeler review [{i + 1}/{max_iterations}]: {action}"
                f" — {decision.get('reasoning', '')}"
            )
            if action == "done" or action not in MODELER_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self._execute_review_action(
                action, params, artifact, pending_issues, observation,
            )
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Modeler review error: {observation['error']}")

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
你是系統建模專家，正在對當前專案的 UML 模型進行自主更新與驗證。根據「當前狀態」與「上一步結果」，決定下一步行動。

# 可用動作
- assess_impact：分析需求變更對現有模型的影響，判斷哪些圖表需要更新。無參數。
- update_diagram：更新或新建特定類型的圖表。params: {{ "diagram_type": "use_case_diagram/class_diagram/sequence_diagram" }}
- validate_diagram：驗證特定圖表的 PlantUML 語法。params: {{ "diagram_type": "..." }}
- fix_diagram：修正驗證失敗的圖表（依上一步驗證錯誤修正）。params: {{ "diagram_type": "..." }}
- review_neutrals：從架構角度複審被標為 Neutral（無衝突）的項目，找出 Analyst 可能遺漏的設計層衝突。無參數。
- done：更新完成，交還控制權。無參數。

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 決策指引
- 先 assess_impact 判斷哪些模型需更新
- 對每個需更新的圖表：update_diagram → validate_diagram → (若失敗) fix_diagram → validate_diagram
- Use Case Diagram 和 Class Diagram 為必要，Sequence Diagram 視需求而定
- 若有 Neutral 項目且已有系統模型，呼叫 review_neutrals 從架構角度複審
- 所有需更新的圖表處理完後呼叫 done
- reasoning 請使用繁體中文

輸出 JSON:
{{
    "action": "動作名稱",
    "params": {{}},
    "reasoning": "一句說明"
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Modeler review 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}

        action = (response.get("action") or "").strip()
        if action not in MODELER_REVIEW_ACTIONS:
            action = "done"
        return {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }

    def _build_review_state(
        self, artifact, recent_discussions, actions_taken,
        iteration, max_iterations,
    ):
        models = artifact.get("system_models", {}).get("models", [])
        model_summary = [
            {"name": m.get("name"), "type": m.get("type"),
             "has_plantuml": bool(m.get("plantuml"))}
            for m in models
        ]
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"),
             "text": (r.get("text") or "")[:80]}
            for r in reqs
        ]
        disc_summaries = []
        for disc in (recent_discussions or []):
            topic = disc.get("topic", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "topic_id": topic.get("id"),
                "title": topic.get("title"),
                "summary": (resolution.get("summary") or "")[:150],
            })
        neutrals = [
            {"id": c.get("id"),
             "confidence": c.get("confidence"),
             "description": (c.get("description") or "")[:120]}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
        ]
        return {
            "current_models": model_summary,
            "requirements": summary_reqs,
            "neutrals": neutrals,
            "recent_discussions": disc_summaries,
            "actions_taken": actions_taken,
            "has_validator": "plantuml_validate" in self.tools,
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def _execute_review_action(
        self, action, params, artifact, pending_issues, last_observation=None,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "assess_impact":
            reqs = artifact.get("requirements", [])
            models = artifact.get("system_models", {}).get("models", [])
            context = {
                "requirements": [
                    {"id": r.get("id"), "type": r.get("type"),
                     "text": r.get("text", "")}
                    for r in reqs
                ],
                "current_models": [
                    {"name": m.get("name"), "type": m.get("type")}
                    for m in models
                ],
            }
            ctx_text = json.dumps(context, ensure_ascii=False, indent=2)
            task = f"""分析需求與現有模型，判斷哪些圖表需要更新或新建。

# Context
{ctx_text}

輸出 JSON:
{{
    "models_to_update": ["需更新的 diagram type"],
    "models_to_create": ["需新建的 diagram type"],
    "impact_summary": "影響摘要"
}}
impact_summary 請使用繁體中文。只輸出 JSON。"""
            messages = self.build_direct_messages(task)
            try:
                result = self.model.chat_json(messages)
                obs["result"] = result
                to_update = result.get("models_to_update", [])
                to_create = result.get("models_to_create", [])
                obs["summary"] = (
                    f"影響評估: 更新 {len(to_update)}, 新建 {len(to_create)}"
                )
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"影響評估失敗: {e}"
            return obs

        if action == "update_diagram":
            diagram_type = params.get("diagram_type", "")
            if not diagram_type:
                obs["error"] = "diagram_type 參數為空"
                return obs
            models = artifact.get("system_models", {}).get("models", [])
            existing = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            reqs = artifact.get("requirements", [])
            stakeholders = artifact.get("stakeholders", [])
            try:
                result = self._update_single_diagram(
                    diagram_type, reqs, stakeholders,
                    existing_model=existing,
                )
                new_plantuml = result.get("plantuml", "")
                new_name = result.get(
                    "name",
                    existing.get("name", diagram_type) if existing else diagram_type,
                )
                if existing:
                    existing["plantuml"] = new_plantuml
                    existing["name"] = new_name
                else:
                    artifact.setdefault("system_models", {}).setdefault(
                        "models", []
                    ).append({
                        "name": new_name,
                        "type": diagram_type,
                        "plantuml": new_plantuml,
                    })
                label = "更新" if existing else "新建"
                obs["summary"] = f"{diagram_type} 已{label}"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"{diagram_type} 更新失敗: {e}"
            return obs

        if action == "validate_diagram":
            diagram_type = params.get("diagram_type", "")
            models = artifact.get("system_models", {}).get("models", [])
            target = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            if not target:
                obs["error"] = f"找不到 {diagram_type}"
                return obs
            validator = self.tools.get("plantuml_validate")
            if not validator:
                obs["result"] = {"valid": True}
                obs["summary"] = f"{diagram_type}: 無驗證工具，跳過"
                return obs
            code = target.get("plantuml", "")
            if not code:
                obs["error"] = f"{diagram_type} 無 PlantUML 內容"
                return obs
            result = self.execute_tool(
                "plantuml_validate", {"plantuml_code": code}
            )
            if "通過" in result:
                obs["result"] = {"valid": True}
                obs["summary"] = f"{diagram_type} 驗證通過"
            else:
                obs["result"] = {"valid": False, "error": result}
                obs["summary"] = f"{diagram_type} 驗證失敗"
            return obs

        if action == "fix_diagram":
            diagram_type = params.get("diagram_type", "")
            models = artifact.get("system_models", {}).get("models", [])
            target = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            if not target:
                obs["error"] = f"找不到 {diagram_type}"
                return obs
            error_msg = ""
            if (
                last_observation
                and isinstance(last_observation.get("result"), dict)
            ):
                error_msg = last_observation["result"].get("error", "")
            if not error_msg:
                error_msg = "語法錯誤"
            fixed = self.fix_plantuml(target, error_msg)
            if fixed:
                target["plantuml"] = fixed
                obs["summary"] = f"{diagram_type} 已修正"
            else:
                obs["error"] = "修正失敗"
                obs["summary"] = f"{diagram_type} 修正失敗"
            return obs

        if action == "review_neutrals":
            try:
                upgraded = self.cross_review_neutrals(artifact)
                if upgraded:
                    for up in upgraded:
                        pending_issues.append({
                            "type": "upgraded_neutral",
                            "description": up.get("description", ""),
                            "source": "modeler",
                            "original_neutral_id": up.get("original_neutral_id"),
                            "conflict_type": up.get("conflict_type", ""),
                            "requirement_ids": up.get("requirement_ids", []),
                            "architecture_evidence": up.get(
                                "architecture_evidence", ""
                            ),
                        })
                    obs["result"] = {"upgraded_count": len(upgraded)}
                    obs["summary"] = (
                        f"複審發現 {len(upgraded)} 個 Neutral 可能有衝突"
                    )
                else:
                    obs["summary"] = "所有 Neutral 項目確認無設計衝突"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"Neutral 複審失敗: {e}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    def _update_single_diagram(
        self, diagram_type, requirements, stakeholders=None,
        existing_model=None,
    ):
        type_names = {
            "use_case_diagram": "Use Case Diagram",
            "class_diagram": "Class Diagram",
            "sequence_diagram": "Sequence Diagram",
        }
        type_name = type_names.get(diagram_type, diagram_type)
        req_text = json.dumps(requirements, ensure_ascii=False, indent=2)

        if existing_model and existing_model.get("plantuml"):
            task = f"""根據更新後的需求，精煉以下 {type_name}。只修改受影響的部分，保留未變動的元素。

當前 PlantUML:
{existing_model['plantuml']}

需求:
{req_text}

- name 使用繁體中文，plantuml 關鍵字維持英文
輸出 JSON:
{{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml"}}"""
        else:
            sh_text = json.dumps(stakeholders or [], ensure_ascii=False, indent=2)
            task = f"""根據以下需求產生 {type_name}。

需求:
{req_text}

利害關係人:
{sh_text}

- name 使用繁體中文，plantuml 關鍵字維持英文
輸出 JSON:
{{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml"}}"""

        messages = self.build_direct_messages(task)
        return self.model.chat_json(messages)
