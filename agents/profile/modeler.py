import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import Dict, Any, Optional, List

from agents.base import BaseAgent
from utils import (
    modeler_models_array_name_line,
    modeler_name_field_language,
    modeler_review_field_language,
    short_reasoning_line,
)


MODELER_ROLE_PROMPT = """你是一個專業的 UML 系統建模專家，負責將需求規格轉換為 UML 系統模型。

核心原則：
1. UML 語意對齊 — 建模語意需盡量對齊 UML 2.x；實作輸出以可被 PlantUML 驗證通過為最終約束。
2. PlantUML 語法正確 — 生成程式碼必須符合 PlantUML 語法並可通過驗證。
3. 完整性 — 模型須涵蓋需求中的主要角色、用例與關鍵結構／流程（依圖型涵蓋對應元素）。
4. 一致性 — 不同圖表之間的元素命名必須一致；同一概念不可多種稱呼。
5. 最小變動 — 精煉時只修改受影響部分，保留未變動元素。
6. 可辨識性 — 模型需完整、可讀，利於後續辨識設計／可測試性問題（問題標記由 Analyst 執行）。
7. 關聯可見 — 圖上應清楚呈現元素間關係（如系統邊界、include/extend、關聯、依賴），避免僅羅列節點。
8. 版面易讀 — 以「誰與哪些元素有關聯」可一眼辨識為優先：減少連線交叉，必要時調整佈局。
9. 可讀性優先於單圖完整性 — 單圖過度擁擠時必須拆圖（依角色、子領域或流程階段拆分）。
10. 建模邊界嚴謹 — Use Case 僅描述系統可提供的行為；不得把願景口號、法規條文或品質目標直接當成用例名稱。
11. 需求可追溯 — 核心元素需可對應需求來源（需求 ID 或需求原文）；若無明確依據，需標註待確認，不可臆造。
12. 元素與圖名語言 — PlantUML elements（actor/use case/class/message/lifeline/relation label）一律使用英文；圖表顯示名稱（`name` 欄位）須遵守每則使用者訊息開頭的「輸出語系」說明（與專案語言一致）。

命名慣例：
- Actor: PascalCase（如 SystemAdmin, EndUser）
- Use Case: 英文動詞開頭（如 ManageUsers, ViewReport）
- Class: PascalCase（如 UserAccount, OrderService）
- Sequence message: 英文動詞片語（如 ValidateToken, CreateOrder）
- 關係標籤: 英文且語意明確

輸出契約：
- 依任務指定格式輸出合法 JSON，不得夾帶 JSON 以外說明文字。
- 若欄位包含 plantuml，內容必須是完整程式碼，且包含 @startuml 與 @enduml。
- 資訊不足時須在輸出中明確標註待確認事項（例如 to_confirm），不可臆測補齊。

產出前自我檢查：
- [ ] PlantUML 語法可通過驗證。
- [ ] Actor 與元素關聯一眼可辨識，交叉線條已盡量降低。
- [ ] 命名一致且語意清楚，PlantUML elements 全為英文。
- [ ] Use Case 名稱為行為，不是願景口號、法規句或品質目標。
- [ ] 主要元素可追溯到需求來源；無法追溯者已標註待確認。"""


MODELER_REVIEW_ACTIONS = [
    "assess_impact",
    "update_diagram",
    "validate_diagram",
    "fix_diagram",
    "done",
]


class ModelerAgent(BaseAgent):
    """系統建模 Agent — 產生 UML 系統模型（PlantUML 格式）+ 設計 Conflict 辨識"""

    name = "modeler"

    system_prompt = MODELER_ROLE_PROMPT

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["plantuml-ascii"],
            project_config=project_config,
        )
        from agents.skills.base import get_skill

        skill = get_skill("plantuml-ascii")
        # 僅附加 SKILL.md 中 <!-- system end --> 前的短文（Plant 對齊說明）。
        # content_user 為長篇 ASCII 教學（逾數千 token），若每則 Modeler 請求都附上會暴增
        # 成本；完整正文請用 invoke_skill("plantuml-ascii", ...) 或讀 SKILL.md。
        cs = (skill.get("content_system") or "").strip()
        self._plantuml_skill_user_block = cs

    def build_direct_messages(
        self, task: str, context: Optional[Dict] = None
    ) -> List[Dict]:
        messages = super().build_direct_messages(task, context)
        block = (getattr(self, "_plantuml_skill_user_block", None) or "").strip()
        if block and messages:
            last = messages[-1]
            if last.get("role") == "user" and isinstance(last.get("content"), str):
                last["content"] = (
                    last["content"]
                    + "\n\n---\n\n# plantuml-ascii（skill 參考，請依任務取用之）\n\n"
                    + block
                )
        return messages

    # ===== 子 OODA 循環（UML 產出／更新） =====

    def run_review_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Modeler 子 OODA：輪數上限 min(caller, self_review_round_cap)；第一輪可縮短。"""
        observation = None
        actions_taken = []
        pending_issues = []
        loop_cap = self.self_review_round_cap()
        effective_max = min(max_iterations, loop_cap)
        i = 0

        while i < effective_max:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= effective_max:
                    effective_max = n
                    self.logger.info(
                        "  Modeler 自訂此次複審輪數: %s（上限 %s）",
                        effective_max,
                        loop_cap,
                    )
            action = decision.get("action", "done")
            self.logger.info(
                f"  Modeler review [{i + 1}/{effective_max}]: {action}"
                f" — {decision.get('reasoning', '')}"
            )
            if action == "done" or action not in MODELER_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self.execute_review_action(
                action, params, artifact, pending_issues, observation,
            )
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Modeler review error: {observation['error']}")
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)
        sr_current = int(state.get("max_iterations") or 1)

        user_prompt = f"""# 任務
你是系統建模專家，正在對當前專案的 UML 模型進行自主更新與驗證。根據「當前狀態」與「上一步結果」，決定下一步行動。

# 可用動作
- assess_impact：分析需求變更對現有模型的影響，判斷哪些圖表需要更新。無參數。
- update_diagram：更新或新建特定類型的圖表。params: {{ "diagram_type": "use_case_diagram/class_diagram/sequence_diagram" }}
- validate_diagram：驗證特定圖表的 PlantUML 語法。params: {{ "diagram_type": "..." }}
- fix_diagram：修正驗證失敗的圖表（依上一步驗證錯誤修正）。params: {{ "diagram_type": "..." }}
- done：更新完成，交還控制權。無參數。

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 決策指引
- 若為第一輪（當前狀態中 iteration 為 1），可選填 max_iterations（1–{sr_current}）表示此次複審你打算跑幾輪；不填則用目前上限 {sr_current}。
- 先 assess_impact 判斷哪些模型需更新
- 對每個需更新的圖表：update_diagram → validate_diagram → (若失敗) fix_diagram → validate_diagram
- 所有需更新的圖表處理完後呼叫 done
- {short_reasoning_line(self.output_language)}

輸出 JSON:
{{
    "action": "動作名稱",
    "params": {{}},
    "reasoning": "一句說明",
    "max_iterations": "選填，僅第一輪有效；填數字 1–{sr_current} 表示此次複審自訂輪數"
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
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        if "max_iterations" in response:
            out["max_iterations"] = response["max_iterations"]
        return out

    def build_review_state(
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
             "text": (r.get("text") or "")}
            for r in reqs
        ]
        disc_summaries = []
        for disc in (recent_discussions or []):
            topic = disc.get("topic", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "topic_id": topic.get("id"),
                "title": topic.get("title"),
                "summary": (resolution.get("summary") or ""),
            })
        neutrals = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")}
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

    def execute_review_action(
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
            task = f"""分析需求與現有模型，完成兩件事：(1) 判斷哪些圖表需要更新或新建；(2) 產出與需求的一致性說明與缺口報告。

# Context
{ctx_text}

# 輸出要求
- models_to_update：需更新的 diagram type 列表（如 use_case_diagram, class_diagram, sequence_diagram）
- models_to_create：需新建的 diagram type 列表
{modeler_review_field_language(self.output_language)}

輸出 JSON:
{{
    "models_to_update": ["需更新的 diagram type"],
    "models_to_create": ["需新建的 diagram type"],
    "impact_summary": "影響摘要",
    "consistency_summary": "與需求一致性的整體說明",
    "gaps": ["缺口或不一致項目1", "缺口或不一致項目2"]
}}
只輸出 JSON。"""
            messages = self.build_direct_messages(task)
            try:
                result = self.model.chat_json(messages)
                obs["result"] = result
                to_update = result.get("models_to_update", [])
                to_create = result.get("models_to_create", [])
                consistency_summary = result.get("consistency_summary", "")
                gaps = result.get("gaps", [])
                if not isinstance(gaps, list):
                    gaps = []
                obs["summary"] = (
                    f"影響評估: 更新 {len(to_update)}, 新建 {len(to_create)}"
                )
                if consistency_summary:
                    obs["summary"] += f"；一致性: {consistency_summary}"
                if gaps:
                    obs["summary"] += f"；缺口 {len(gaps)} 項"
                # 寫入 artifact 供後續查閱
                report = {
                    "consistency_summary": consistency_summary,
                    "gaps": gaps,
                    "models_to_update": to_update,
                    "models_to_create": to_create,
                    "impact_summary": result.get("impact_summary", ""),
                }
                artifact.setdefault("system_models", {})["last_consistency_report"] = report
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
                result = self.update_single_diagram(
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
                "plantuml_validate",
                {"plantuml_code": code},
                active_skill="plantuml-ascii",
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

        obs["error"] = f"未知動作: {action}"
        return obs

    def update_single_diagram(
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
        diagram_layout_hint = ""
        if diagram_type == "use_case_diagram":
            diagram_layout_hint = """
用例圖版面要求：產出時以「actor 與 use case 的關聯一目了然」為準。請善用 PlantUML 的版面控制（例如 left to right direction、或將 actor 分置系統邊界左右兩側），使連線少交叉、誰對應哪些用例清楚可辨；若單圖用例過多導致連線雜亂，可精簡為核心用例或依角色拆成多張圖。"""
        elif diagram_type == "class_diagram":
            diagram_layout_hint = """
類別圖建模要求：優先呈現可讀的核心結構與關係，不要把所有名詞都畫成類別。請先確保主要類別之間的繼承、關聯、聚合/組合、依賴關係清楚可辨，再補必要屬性與方法；每個類別僅保留關鍵欄位/操作，避免圖面過度擁擠。若領域過大，請依子域拆圖或僅呈現本次需求受影響的核心類別。"""
        elif diagram_type == "sequence_diagram":
            diagram_layout_hint = """
時序圖建模要求：一張圖聚焦一個主要情境流程，僅保留關鍵 lifeline 與關鍵訊息，避免放入過多非必要元件。需清楚表達主流程與關鍵分支/例外（可用 alt/opt），並讓訊息方向與前後順序易於追蹤；訊息名稱請使用具體動詞，避免抽象字眼。"""

        if existing_model and existing_model.get("plantuml"):
            task = f"""根據更新後的需求，精煉以下 {type_name}。只修改受影響的部分，保留未變動的元素。

當前 PlantUML:
{existing_model['plantuml']}

需求:
{req_text}
{diagram_layout_hint}

- {modeler_name_field_language(self.output_language)}
- PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
- 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
輸出 JSON:
{{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"]}}"""
        else:
            sh_text = json.dumps(stakeholders or [], ensure_ascii=False, indent=2)
            task = f"""根據以下需求產生 {type_name}。

需求:
{req_text}

利害關係人:
{sh_text}
{diagram_layout_hint}

- {modeler_name_field_language(self.output_language)}
- PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
- 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
輸出 JSON:
{{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"]}}"""

        messages = self.build_direct_messages(task)
        return self.model.chat_json(messages)

    def generate_system_model(
        self,
        requirements: List[Dict],
        stakeholders: List[Dict],
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """依 run_review_loop（observe → reason → act → evaluate）產出初始 UML，回傳 system_models。max_iterations 由 caller 從 config 傳入，未傳則用 15。"""
        artifact = {
            "requirements": requirements,
            "stakeholders": stakeholders or [],
            "system_models": {"models": []},
            "conflicts": [],
        }
        n = 15 if max_iterations is None else max_iterations
        self.run_review_loop(artifact, max_iterations=n)
        model_data = artifact.get("system_models", {})
        return self.validate_models(model_data)

    def refine_model(
        self,
        requirements: List[Dict],
        prev_models: List[Dict] = None,
        stakeholders: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """根據更新的需求精煉系統模型；可選傳入 stakeholders 以對應角色與需求來源。"""
        current_model = {"models": prev_models or []}
        current_model_json = json.dumps(current_model, ensure_ascii=False, indent=2)
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        sh_block = ""
        if stakeholders:
            sh_text = json.dumps(stakeholders, ensure_ascii=False, indent=2)
            sh_block = f"\n# 利害關係人（供對應需求來源與角色）\n{sh_text}\n\n"

        task = f"""# 任務
根據更新後的需求，評估並更新現有系統模型。
{sh_block}# 當前系統模型
```json
{current_model_json}
```

# 更新後的需求
{requirements_text}

# 分析步驟
1. 比較新需求與當前模型，識別差異
2. 只修改受影響的部分，保留未變動的元素
3. **由你自行決定**要保留、新增或移除哪些圖表（type 限 use_case_diagram / class_diagram / sequence_diagram），以符合更新後需求為準
（設計/可測試性 Conflict 由 Analyst 在產出模型後統一辨識）
- {modeler_models_array_name_line(self.output_language)}
- PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
- 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。

# 輸出格式
{{
    "models": [{{"name": "...", "type": "use_case_diagram|class_diagram|sequence_diagram", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"]}}]
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
            result = self.execute_tool(
                "plantuml_validate",
                {"plantuml_code": code},
                active_skill="plantuml-ascii",
            )
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

- PlantUML elements（actor/use case/class/message/lifeline/relation label）必須維持英文，不可改成中文。
- 若錯誤來自需求資訊不足，請不要臆測補齊；在 to_confirm 列出待確認事項（可為空陣列）。

# 輸出 JSON
{{{{
    "plantuml": "@startuml\\n...修正後的完整程式碼...\\n@enduml",
    "to_confirm": ["待確認事項"]
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
1. 先思考：(1) 此議題對系統架構與模型的影響 (2) 你在架構/建模上必須堅守的底線 (3) 在不破壞核心邊界下可接受的調整或折衷 (4) 對既有 UML 與需求追溯的影響
2. 上述 (2)(3) 只用來**內部**整理立場；撰寫 statement 時請勿以「我可讓步的點是…」「不可讓步的點是…」或類似小標／口頭套語作答，應把堅持與彈性**自然融入**架構結論、影響分析與調整建議中。
3. 再根據思考結果，撰寫一段完整的發言（statement），建議採「先架構結論、再影響分析、再調整建議」順序，聚焦於系統架構、建模、元件邊界的觀點
4. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"expert"）

# 表達方式（僅能以文字呈現）
- 發言時可善用**文字形式**的圖、表格、流程、草圖輔助說明，例如：Markdown 表格（| 項目 | 說明 |）、編號步驟流程（1. … 2. …）、箭頭式流程（A → B → C）、簡要結構縮排或文字草圖；無法產出真實圖片，僅能以文字表達。**若有使用表格、流程或圖示，請用 ``` … ``` 程式碼區塊包住，與一般敘述分開，方便閱讀。**

# 發言風格
- 以真實需求工程會議中的系統架構/建模專家口吻：先指出關鍵架構判斷，再說明影響範圍與可驗證的調整方案
- 清楚描述改動對 Use Case / Class / Sequence 的影響，並說明是否會破壞一致性或可測試性
- 可說「若需求這樣定，Use Case 圖需要…」「這點會影響到 Class 的職責邊界…」

# 約束
- statement 須聚焦系統架構與建模觀點，評估需求變更對 UML 模型的影響
- 避免只講抽象原則，需明確指出「哪個模型元素」會變動與原因
- 若資訊不足，需說明需補充的介面、事件流程或資料邊界，不可臆測
- 投票將在討論結束後另行進行，發言時只需專注架構與建模觀點

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
