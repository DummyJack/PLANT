# Modeler modeling helpers: generate, refine, validate, and repair UML models.
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from agents.skills.base import get_skill
from utils.language import current_output_language
from .prompts import uml_skill_subset
from .validation import (
    ALLOWED_MODEL_TYPES,
    parse_diagram_model,
    parse_model_list,
    parse_use_case_text,
    parse_plantuml_fix,
)


class ModelerModeling:
    AVAILABLE_MODEL_TYPES = sorted(ALLOWED_MODEL_TYPES)

    @staticmethod
    def model_name(model_type: str) -> str:
        zh_names = {
            "context_diagram": "系統脈絡圖",
            "use_case_diagram": "使用案例圖",
            "activity_diagram": "活動圖",
            "sequence_diagram": "循序圖",
            "state_machine": "狀態機",
            "class_diagram": "領域模型圖",
        }
        en_names = {
            "context_diagram": "Context Diagram",
            "use_case_diagram": "Use Case Diagram",
            "activity_diagram": "Activity Diagram",
            "sequence_diagram": "Sequence Diagram",
            "state_machine": "State Machine",
            "class_diagram": "Domain Model",
        }
        names = en_names if current_output_language() == "en" else zh_names
        return names.get(model_type, model_type)

    @staticmethod
    def model_source(revision_context: Optional[Dict[str, Any]] = None) -> str:
        if isinstance(revision_context, dict):
            meeting_ids = [
                str(value).strip()
                for value in (revision_context.get("meeting_ids") or [])
                if str(value).strip()
            ]
            if meeting_ids:
                return ",".join(dict.fromkeys(meeting_ids))
        return "initial_modeling"

    @staticmethod
    def system_model_rows(artifact: Any) -> list[Dict[str, Any]]:
        if not isinstance(artifact, dict):
            return []
        models = artifact.get("system_models", [])
        if not isinstance(models, list):
            return []
        return [row for row in models if isinstance(row, dict)]

    @staticmethod
    def model_requirements(artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        source_rows = artifact.get("requirements") or artifact.get("URL") or []
        return [
            {"id": r.get("id"), "text": r.get("text", "")}
            for r in source_rows
            if isinstance(r, dict) and str(r.get("text") or "").strip()
        ]

    @staticmethod
    def model_stakeholders(artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        rows: list[Dict[str, Any]] = []
        for stakeholder in artifact.get("stakeholders", []) or []:
            if not isinstance(stakeholder, dict):
                continue
            name = str(stakeholder.get("name") or "").strip()
            if not name:
                continue
            row = {"name": name}
            stakeholder_type = str(stakeholder.get("type") or "").strip()
            if stakeholder_type:
                row["type"] = stakeholder_type
            rows.append(row)
        return rows

    @staticmethod
    def model_feedback(artifact_or_context: Dict[str, Any]) -> Dict[str, Any]:
        feedback = (
            artifact_or_context.get("feedback")
            if isinstance(artifact_or_context.get("feedback"), dict)
            else {}
        )
        return {
            key: feedback.get(key, []) or []
            for key in ("constraints", "risks", "open_items")
        }

    def build_model_context(
        self,
        artifact: Dict[str, Any],
        *,
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保留建模需要的 artifact 欄位，避免把 pending 內容畫成正式模型。"""
        return {
            "scenario": artifact.get("scenario", {}) or artifact.get("rough_idea", ""),
            "stakeholders": self.model_stakeholders(artifact),
            "requirements": self.model_requirements(artifact),
            "scope": artifact.get("scope", {}) or {},
            "feedback": self.model_feedback(artifact),
            "open_questions": artifact.get("open_questions", []) or [],
            "system_models": self.system_model_rows(artifact),
            "model_source": self.model_source(revision_context),
            "model_revision_context": revision_context or artifact.get("model_revision_context", {}) or {},
        }

    def generate_system_models(
        self,
        artifact: Dict[str, Any],
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """根據目前 artifact 產生 System Model。"""
        model_artifact = self.build_model_context(
            artifact,
            revision_context=revision_context,
        )
        self.run_model_loop(model_artifact)
        model_data = self.parse_model_output(
            model_artifact.get("system_models", []),
            source=model_artifact.get("model_source", ""),
        )
        self.ensure_use_case_text(model_data, model_artifact)
        return self.validate_plantuml_models(model_data)

    def ensure_use_case_text(
        self,
        model_data: list[Dict[str, Any]],
        artifact_context: Dict[str, Any],
    ) -> None:
        """use_case_diagram 一定要附文字版 use case；缺少時在輸出前補齊。"""
        use_case_diagram = next(
            (
                model for model in model_data
                if model.get("type") == "use_case_diagram" and model.get("plantuml")
            ),
            None,
        )
        if not use_case_diagram or use_case_diagram.get("text"):
            return

        context = dict(artifact_context)
        context["system_models"] = model_data
        result = self.generate_or_update_model(
            "use_case_text",
            self.model_requirements(context),
            artifact_context=context,
        )
        use_case_text = result.get("text", []) if isinstance(result, dict) else []
        if not use_case_text:
            raise RuntimeError("use_case_diagram 已生成，但 use_case_text 生成失敗")
        use_case_diagram["text"] = use_case_text

    def generate_or_update_model(
        self, diagram_type, requirements,
        existing_model=None,
        artifact_context: Optional[Dict[str, Any]] = None,
    ):
        type_name = self.model_name(diagram_type)
        req_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        artifact_context = artifact_context or {}
        context_payload = {
            "scenario": artifact_context.get("scenario", {}) or artifact_context.get("rough_idea", ""),
            "stakeholders": self.model_stakeholders(artifact_context),
            "scope": artifact_context.get("scope", {}) or {},
            "feedback": self.model_feedback(artifact_context),
            "open_questions": artifact_context.get("open_questions", []) or [],
            "model_revision_context": artifact_context.get("model_revision_context", {}) or {},
        }
        context_text = json.dumps(context_payload, ensure_ascii=False, indent=2)
        diagram_layout_hint = ""
        if diagram_type == "context_diagram":
            diagram_layout_hint = """
    本專案限制：不可把未確認的 provider/API 畫成已定案外部系統；若來源未定，請使用抽象資料來源。
    context_diagram 只呈現本系統與外部 actor / external systems 的互動；不得把本系統內部功能、子系統、管理模組或實作元件畫成外部系統。只有在 requirements 明確指出某項系統是既有外部系統或第三方服務時，才可畫成 external system。"""
        elif diagram_type == "use_case_diagram":
            diagram_layout_hint = """
    版面要求：actor 與 use case 的關聯要一目了然；若單圖連線過多，可精簡為核心用例或依角色拆分。"""
        elif diagram_type == "activity_diagram":
            diagram_layout_hint = """
    本專案限制：不要放入技術實作步驟。"""
        elif diagram_type == "class_diagram":
            diagram_layout_hint = """
    本專案限制：只作為需求層級 domain model；避免加入未確認的 service、database、API 或實作類別。"""
        elif diagram_type == "sequence_diagram":
            diagram_layout_hint = """
    本專案限制：一張圖聚焦一個主要情境流程；lifeline 使用需求層級角色/系統，不要放入低階 service/database 實作。"""
        elif diagram_type == "state_machine":
            diagram_layout_hint = """
    本專案限制：若狀態不明確，不要硬畫。"""


        description_rule = ""
        description_field = ""
        if diagram_type != "use_case_diagram":
            description_rule = """
    - description 請說明這張圖用來釐清哪一個需求面向，以及圖中實際呈現的關鍵元素或關係。依圖型目的撰寫，例如：Context Diagram 說明系統邊界與外部互動，Activity Diagram 說明流程步驟與分支，Sequence Diagram 說明互動順序，State Machine 說明狀態與轉換，Class Diagram 說明需求層級概念與關係。只能描述圖中已呈現的內容，不得加入新需求；不要寫「未擴張、未臆測、未確認」這類自我辯護或否定句，只正向說明圖中呈現了什麼。"""
            description_field = ', "description": "此圖釐清的需求面向與圖中已呈現的重點。"'

        if diagram_type == "use_case_text":
            models = self.system_model_rows(artifact_context)
            use_case_diagram = next(
                (
                    model for model in models
                    if model.get("type") == "use_case_diagram" and model.get("plantuml")
                ),
                None,
            )
            use_case_diagram_text = json.dumps(
                {
                    "name": use_case_diagram.get("name"),
                    "type": use_case_diagram.get("type"),
                    "plantuml": use_case_diagram.get("plantuml"),
                    "source": use_case_diagram.get("source"),
                },
                ensure_ascii=False,
                indent=2,
            ) if use_case_diagram else "{}"
            task = f"""根據已生成的 Use Case Diagram 整理文字版使用案例。這不是 UML 圖，而是附在 use_case_diagram.text 的需求層級使用案例規格。

    需求 ID 對照（只可用於 related_requirements，不可用來新增 use case）:
    {req_text}

    Use Case Diagram:
    {use_case_diagram_text}

    補充背景（不得擴張 requirements；只可用於邊界判斷；feedback.open_items 只是不確定性提示，不可畫成已確認元素）:
    {context_text}

    - 只能整理 Use Case Diagram 中已出現的 actor 與 use case；不要補入圖中沒有的 use case。
    - 需求 ID 對照只用來填 related_requirements，不可作為新增 use case 的依據。
    - 每個 use case 必須代表使用者或外部角色透過系統完成的一個可觀察任務。
    - 不要把技術元件、資料表、API 或內部演算法寫成 use case。
    - purpose 寫此 use case 的目的／說明。
    - interface 寫使用者進入或操作的頁面、畫面、入口或系統介面；若需求未明確，使用需求層級名稱，不要臆測 UI 細節。
    - related_requirements 只能放本次需求中已出現的 requirement id。
    - 不要輸出 source；source 由系統依建模來源補上。
    - 若 UML skill 範例與本任務輸出格式不同，必須以本任務 JSON 結構為準。
    輸出 JSON:
    {{
      "type": "use_case_text",
      "text": [
        {{
          "id": "UC-1",
          "actor": "主要參與者",
          "name": "使用案例名稱",
          "purpose": "目的／說明",
          "interface": "介面或入口",
          "related_requirements": ["URL-1"]
        }}
      ]
    }}"""
            skill = uml_skill_subset(get_skill("UML"), "use_case_text")
            messages = self.build_skill_messages(skill, "UML", task)
            result = self.chat_json(messages)
            return parse_use_case_text(result)

        if existing_model and existing_model.get("plantuml"):
            task = f"""根據更新後的需求，精煉以下 {type_name}。只修改受影響的部分，保留未變動的元素。

    當前 PlantUML:
    {existing_model['plantuml']}

    需求:
    {req_text}

    補充背景（不得擴張 requirements；只可用於邊界判斷；feedback.open_items 只是不確定性提示，不可畫成已確認元素）:
    {context_text}
    {diagram_layout_hint}

    - 這是帶有修訂脈絡的模型迭代：以上一版 PlantUML 為基礎，只修訂受 model_revision_context / requirements 影響的元素。
    - 未受影響的 actor、use case、流程、資料輸入/輸出、狀態或概念必須保留；不得因重畫而改名或刪除仍有效元素。
    - PlantUML 圖中元素（actor/use case/class/message/lifeline/relation label）必須使用目前輸出語系；若目前輸出語系是繁體中文，圖中元素使用繁體中文；若目前輸出語系是英文，圖中元素使用英文。不要混用語言。
    - 若資訊不足，不可臆測，也不要硬畫未確認元素。
    - 此為需求層級模型，不是設計／架構模型；不可擴張需求。
    - feedback 不可被轉成新的 actor、use case、class、state 或流程步驟；只能影響模型邊界、限制標註或缺口說明。
    - name 請使用簡短、直觀的名稱，讓讀者快速理解此模型內容；不要加入專案全名、圖型名稱、冗長修飾詞或不必要形容詞。
{description_rule}
    - 不要輸出 source；source 由系統依建模來源補上。
    - 若 UML skill 範例與本任務輸出格式不同，必須以本任務 JSON 結構為準。
    輸出 JSON:
    {{"name": "簡短直觀的模型名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "description": "此圖釐清的需求面向與圖中已呈現的重點。"}}"""
        else:
            task = f"""根據以下需求產生 {type_name}。

    需求:
    {req_text}

    補充背景（不得擴張 requirements；只可用於邊界判斷；feedback.open_items 只是不確定性提示，不可畫成已確認元素）:
    {context_text}
    {diagram_layout_hint}

    - PlantUML 圖中元素（actor/use case/class/message/lifeline/relation label）必須使用目前輸出語系；若目前輸出語系是繁體中文，圖中元素使用繁體中文；若目前輸出語系是英文，圖中元素使用英文。不要混用語言。
    - 若資訊不足，不可臆測，也不要硬畫未確認元素。
    - 此為需求層級模型，不是設計／架構模型；不可擴張需求。
    - feedback 不可被轉成新的 actor、use case、class、state 或流程步驟；只能影響模型邊界、限制標註或缺口說明。
    - name 請使用簡短、直觀的名稱，讓讀者快速理解此模型內容；不要加入專案全名、圖型名稱、冗長修飾詞或不必要形容詞。
{description_rule}
    - 不要輸出 source；source 由系統依建模來源補上。
    - 若 UML skill 範例與本任務輸出格式不同，必須以本任務 JSON 結構為準。
    輸出 JSON:
    {{"name": "簡短直觀的模型名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "description": "此圖釐清的需求面向與圖中已呈現的重點。"}}"""

        skill = uml_skill_subset(get_skill("UML"), "diagram", diagram_type)
        messages = self.build_skill_messages(skill, "UML", task)
        result = self.chat_json(messages)
        return parse_diagram_model(result, expected_type=diagram_type)

    def parse_model_output(self, result, *, source: str = "") -> list[Dict[str, Any]]:
        return parse_model_list(result, source=source)

    def validate_plantuml_models(self, model_data: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """用 plantuml_validate 工具驗證每個模型的 PlantUML 語法，有錯則自動修正"""
        validator = self.tools.get("plantuml_validate")
        if not validator:
            return model_data

        models = model_data if isinstance(model_data, list) else []
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

        # 依序處理需修正的模型（repair_plantuml 呼叫 LLM，維持順序並控制並發）
        for i in range(len(models)):
            m, result = validation_results.get(i, (models[i], None))
            if result is None:
                continue
            if "通過" in result:
                continue
            self.logger.warning(f"  {m.get('name', '')} 語法修正中")
            fixed = self.repair_plantuml(m, result)
            if fixed:
                m["plantuml"] = fixed

        return model_data

    def repair_plantuml(self, model: Dict, error_msg: str) -> Optional[str]:
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
    - 修正語法時必須維持原圖元素語言，不可把繁體中文改成英文，也不可把英文改成繁體中文。
    - 不要新增或移除需求內容；如果資訊不足，維持原本抽象元素，不要臆測補齊。

    # 輸出 JSON
    {{{{
    "plantuml": "@startuml\\n...修正後的完整程式碼...\\n@enduml"
    }}}}"""

        try:
            skill = uml_skill_subset(get_skill("UML"), "repair", model.get("type", ""))
            messages = self.build_skill_messages(skill, "UML", user_prompt)
            response = self.chat_json(messages)
            return parse_plantuml_fix(response)["plantuml"]
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
