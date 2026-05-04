# Modeler modeling helpers: generate, refine, validate, and repair UML models.
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from agents.base import (
    modeler_models_array_name_line,
    modeler_name_field_language,
)
from agents.skills.base import get_skill

MODEL_SELECTION_RULES = """- 所有 diagram type 都不是必產生；只在模型能幫助需求理解、驗證或追溯時才建立、保留或更新。
- 不從模型反推新增需求，也不可把 open_questions / pending candidates 畫成正式模型內容。
- 資訊不足時不要畫死，改在 to_confirm 或 assumptions 說明。
- Context / Use Case / Activity / Data Flow 可用於呈現系統邊界、角色互動、流程或資料流。
- Sequence Diagram 只在互動順序會影響需求理解時建立。
- State Machine Diagram 只在需求已有明確生命週期或狀態轉換時建立。
- Class Diagram 若建立，只能作為 tentative domain model，不可當成設計模型。"""


class ModelerModeling:
    AVAILABLE_MODEL_TYPES = [
        "context_diagram",
        "use_case_diagram",
        "activity_diagram",
        "data_flow_diagram",
        "sequence_diagram",
        "state_machine_diagram",
        "class_diagram",
    ]

    def build_requirement_model_artifact(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """保留建模需要的 artifact 欄位，避免把 pending 內容畫成正式模型。"""
        feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        return {
            "requirements": artifact.get("requirements", []) or [],
            "stakeholders": artifact.get("stakeholders", []) or [],
            "scope": artifact.get("scope", {}) or {},
            "conflicts": artifact.get("conflicts", []) or [],
            "open_questions": artifact.get("open_questions", []) or [],
            "feedback": {"domain_research": feedback.get("domain_research", {}) or {}},
            "elicitation_meeting": artifact.get("elicitation_meeting", []) or [],
            "workflow_sketch": artifact.get("workflow_sketch", {}) or {},
            "system_models": artifact.get("system_models", {"models": []}) or {"models": []},
            "meta": {
                **(artifact.get("meta", {}) if isinstance(artifact.get("meta"), dict) else {}),
                "model_stage": "generate_system_model",
            },
        }

    def generate_requirement_models(
        self,
        artifact: Dict[str, Any],
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """根據目前 artifact 產生 System Model。"""
        model_artifact = self.build_requirement_model_artifact(artifact)
        n = 15 if max_iterations is None else max_iterations
        self.run_model_loop(model_artifact, max_iterations=n)
        model_data = self.ensure_model_format(model_artifact.get("system_models", {}))
        model_data.setdefault("model_stage", "generate_system_model")
        model_data.setdefault("maturity", "requirement_level")
        model_data.setdefault("source", "requirements_for_system_model")
        model_data.setdefault("model_summary", "")
        model_data.setdefault("to_confirm", [])
        model_data.setdefault("assumptions", [])
        for model in model_data.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            model.setdefault("model_stage", "generate_system_model")
            model.setdefault("source", "requirements_for_system_model")
            if str(model.get("type") or "").strip() == "class_diagram":
                model["maturity"] = "tentative"
            else:
                model.setdefault("maturity", "requirement_level")
        return self.validate_models(model_data)

    def generate_system_model(
        self,
        requirements: List[Dict],
        stakeholders: List[Dict],
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """向後相容入口；新流程請改用 generate_requirement_models(artifact)。"""
        artifact = {
            "requirements": requirements,
            "stakeholders": stakeholders or [],
            "system_models": {"models": []},
            "conflicts": [],
        }
        return self.generate_requirement_models(artifact, max_iterations=max_iterations)

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

    # 規則
    - 比較新需求與當前模型，識別差異。
    - 只修改受影響的部分，保留未變動元素。
    {MODEL_SELECTION_RULES}
    - {modeler_models_array_name_line()}
    - {modeler_name_field_language()}
    - 資訊不足時請在 to_confirm 列出待確認事項。

    # 輸出格式
    {{
    "model_summary": "模型整體摘要",
    "to_confirm": ["跨模型待確認事項"],
    "assumptions": ["建模假設"],
    "models": [{{"name": "...", "type": "context_diagram|use_case_diagram|activity_diagram|data_flow_diagram|sequence_diagram|state_machine_diagram|class_diagram", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"], "maturity": "requirement_level|tentative"}}]
    }}"""

        try:
            skill = get_skill("UML")
            messages = self.build_skill_messages(skill, "UML", task)
            result = self.chat_json(messages)
            model_data = self.ensure_model_format(result)
            return self.validate_models(model_data)
        except Exception as e:
            self.logger.warning(f"模型精煉失敗: {e}")
            return {"models": prev_models or []}

    def update_single_diagram(
        self, diagram_type, requirements, stakeholders=None,
        existing_model=None,
        artifact_context: Optional[Dict[str, Any]] = None,
    ):
        type_names = {
            "context_diagram": "Context Diagram",
            "use_case_diagram": "Use Case Diagram",
            "activity_diagram": "Activity Diagram",
            "data_flow_diagram": "Data Flow Diagram",
            "class_diagram": "Class Diagram",
            "sequence_diagram": "Sequence Diagram",
            "state_machine_diagram": "State Machine Diagram",
        }
        type_name = type_names.get(diagram_type, diagram_type)
        req_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        artifact_context = artifact_context or {}
        context_payload = {
            "scope": artifact_context.get("scope", {}) or {},
            "conflicts_summary": [
                {
                    "id": c.get("id"),
                    "label": c.get("label"),
                    "description": c.get("description"),
                    "requirement_ids": c.get("requirement_ids", []),
                }
                for c in artifact_context.get("conflicts", []) or []
                if isinstance(c, dict)
            ],
            "open_questions": artifact_context.get("open_questions", []) or [],
            "domain_research": (artifact_context.get("feedback") or {}).get("domain_research", {}),
            "workflow_sketch": artifact_context.get("workflow_sketch", {}) or {},
        }
        context_text = json.dumps(context_payload, ensure_ascii=False, indent=2)
        diagram_layout_hint = ""
        if diagram_type == "context_diagram":
            diagram_layout_hint = """
    Context Diagram 要求：呈現系統邊界、外部 actor、外部系統與主要資訊/互動流。不可把未確認的 provider/API 畫成已定案外部系統；若來源未定，請用抽象資料來源並放入 to_confirm。"""
        elif diagram_type == "use_case_diagram":
            diagram_layout_hint = """
    用例圖版面要求：產出時以「actor 與 use case 的關聯一目了然」為準。請善用 PlantUML 的版面控制（例如 left to right direction、或將 actor 分置系統邊界左右兩側），使連線少交叉、誰對應哪些用例清楚可辨；若單圖用例過多導致連線雜亂，可精簡為核心用例或依角色拆成多張圖。"""
        elif diagram_type == "activity_diagram":
            diagram_layout_hint = """
    Activity Diagram 要求：聚焦需求層級 user workflow，呈現主流程、關鍵分支、例外路徑與結束點。不要放入技術實作步驟。"""
        elif diagram_type == "data_flow_diagram":
            diagram_layout_hint = """
    Data Flow Diagram 要求：呈現資料輸入、處理、資料儲存/外部資料來源與輸出。使用抽象資料類型，不要未經確認指定 provider、API 或 database design。"""
        elif diagram_type == "class_diagram":
            diagram_layout_hint = """
    Class Diagram 要求：只作為 tentative domain model，呈現需求中的核心概念與關係，不可當成設計模型；避免加入未確認的 service、database、API 或實作類別。maturity 必須為 tentative。"""
        elif diagram_type == "sequence_diagram":
            diagram_layout_hint = """
    Sequence Diagram 要求：只在核心互動順序需要釐清時產生，一張圖聚焦一個主要情境流程；lifeline 使用需求層級角色/系統，不要放入低階 service/database 實作。"""
        elif diagram_type == "state_machine_diagram":
            diagram_layout_hint = """
    State Machine Diagram 要求：只有在需求中存在明確生命週期或狀態轉換時產生；若狀態不明確，請在 to_confirm 說明，不要硬畫。"""
        maturity_value = "tentative" if diagram_type == "class_diagram" else "requirement_level"

        if existing_model and existing_model.get("plantuml"):
            task = f"""根據更新後的需求，精煉以下 {type_name}。只修改受影響的部分，保留未變動的元素。

    當前 PlantUML:
    {existing_model['plantuml']}

    需求:
    {req_text}

    補充背景（不得擴張 requirements；只可用於邊界、to_confirm、assumptions）:
    {context_text}
    {diagram_layout_hint}

    - {modeler_name_field_language()}
    - PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
    - 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
    - 此為 requirement-level model，不是 design/architecture model；不可擴張需求。
    輸出 JSON:
    {{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"], "maturity": "{maturity_value}"}}"""
        else:
            sh_text = json.dumps(stakeholders or [], ensure_ascii=False, indent=2)
            task = f"""根據以下需求產生 {type_name}。

    需求:
    {req_text}

    利害關係人:
    {sh_text}

    補充背景（不得擴張 requirements；只可用於邊界、to_confirm、assumptions）:
    {context_text}
    {diagram_layout_hint}

    - {modeler_name_field_language()}
    - PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
    - 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
    - 此為 requirement-level model，不是 design/architecture model；不可擴張需求。
    輸出 JSON:
    {{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"], "maturity": "{maturity_value}"}}"""

        skill = get_skill("UML")
        messages = self.build_skill_messages(skill, "UML", task)
        return self.chat_json(messages)

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
                active_skill="UML",
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
            self.logger.warning(f"  {m.get('name', '')} 語法修正中")
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
            skill = get_skill("UML")
            messages = self.build_skill_messages(skill, "UML", user_prompt)
            response = self.chat_json(messages)
            fixed = response.get("plantuml", "")
            if "@startuml" in fixed and "@enduml" in fixed:
                return fixed
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
