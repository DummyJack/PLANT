# Modeler modeling helpers: generate, refine, validate, and repair UML models.
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from agents.skills.base import get_skill
from agents.profile.analyst.conflict_store import all_conflict_rows
from agents.profile.analyst.requirements import requirement_discussion_pool
from .validation import (
    ALLOWED_DIAGRAM_TYPES,
    diagram_payload,
    model_artifact_payload,
    plantuml_fix_payload,
)


class ModelerModeling:
    AVAILABLE_MODEL_TYPES = sorted(ALLOWED_DIAGRAM_TYPES)

    def build_requirement_model_artifact(
        self,
        artifact: Dict[str, Any],
        *,
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保留建模需要的 artifact 欄位，避免把 pending 內容畫成正式模型。"""
        feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        return {
            "requirements": requirement_discussion_pool(artifact),
            "stakeholders": artifact.get("stakeholders", []) or [],
            "scope": artifact.get("scope", {}) or {},
            "conflicts": all_conflict_rows(artifact),
            "open_questions": artifact.get("open_questions", []) or [],
            "feedback": {"domain_research": feedback.get("domain_research", {}) or {}},
            "elicitation": artifact.get("elicitation", {}) or {},
            "workflow_sketch": artifact.get("workflow_sketch", {}) or {},
            "system_models": artifact.get("system_models", {"models": []}) or {"models": []},
            "model_revision_context": revision_context or artifact.get("model_revision_context", {}) or {},
            "meta": {
                **(artifact.get("meta", {}) if isinstance(artifact.get("meta"), dict) else {}),
                "model_stage": "generate_system_model",
            },
        }

    def generate_requirement_models(
        self,
        artifact: Dict[str, Any],
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """根據目前 artifact 產生 System Model。"""
        model_artifact = self.build_requirement_model_artifact(
            artifact,
            revision_context=revision_context,
        )
        self.run_model_loop(model_artifact)
        model_data = self.ensure_model_format(model_artifact.get("system_models", {}))
        model_data.setdefault("model_stage", "generate_system_model")
        model_data.setdefault("maturity", "requirement_level")
        model_data.setdefault("source", "requirements_for_system_model")
        if revision_context:
            model_data["model_revision_mode"] = "revise_existing_models"
            history = list(model_data.get("revision_history") or [])
            history.append(
                {
                    "mode": "revise_existing_models",
                    "round": revision_context.get("round_num"),
                    "changed_requirement_ids": revision_context.get("changed_requirement_ids", []),
                    "change_candidate_ids": revision_context.get("change_candidate_ids", []),
                    "decision_ids": revision_context.get("decision_ids", []),
                }
            )
            model_data["revision_history"] = history
        else:
            model_data.setdefault("model_revision_mode", "initial_or_full_refresh")
        model_data.setdefault("model_summary", "")
        model_data.setdefault("to_confirm", [])
        model_data.setdefault("assumptions", [])
        for model in model_data.get("models", []) or []:
            model.setdefault("model_stage", "generate_system_model")
            model.setdefault("source", "requirements_for_system_model")
        return self.validate_models(model_data)

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
            "model_revision_context": artifact_context.get("model_revision_context", {}) or {},
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

    - 這是 revision-aware 模型迭代：以上一版 PlantUML 為基礎，只修訂受 model_revision_context / requirements / decisions 影響的元素。
    - 未受影響的 actor、use case、流程、資料流、狀態或概念必須保留；不得因重畫而改名或刪除仍有效元素。
    - 上一版 to_confirm 若尚未被最新決策或需求解決，必須保留或改寫為仍待確認事項。
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

    - PlantUML elements（actor/use case/class/message/lifeline/relation label）一律英文，不可混用中文元素名。
    - 若資訊不足，不可臆測；請在 to_confirm 列出待確認事項（可為空陣列）。
    - 此為 requirement-level model，不是 design/architecture model；不可擴張需求。
    輸出 JSON:
    {{"name": "圖表名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "to_confirm": ["待確認事項"], "maturity": "{maturity_value}"}}"""

        skill = get_skill("UML")
        messages = self.build_skill_messages(skill, "UML", task)
        result = self.chat_json(messages)
        return diagram_payload(result, expected_type=diagram_type)

    def ensure_model_format(self, result) -> Dict[str, Any]:
        return model_artifact_payload(result)

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

    - 只修正 PlantUML 語法，不得改變圖的需求語意、範圍、角色、流程或資料關係。
    - PlantUML elements（actor/use case/class/message/lifeline/relation label）必須維持英文，不可改成中文。
    - 不要新增或移除需求內容；如果資訊不足，維持原本抽象元素，不要臆測補齊。

    # 輸出 JSON
    {{{{
    "plantuml": "@startuml\\n...修正後的完整程式碼...\\n@enduml"
    }}}}"""

        try:
            skill = get_skill("UML")
            messages = self.build_skill_messages(skill, "UML", user_prompt)
            response = self.chat_json(messages)
            return plantuml_fix_payload(response)["plantuml"]
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
