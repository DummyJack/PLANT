# Modeler modeling helpers: generate, refine, validate, and repair UML models.
from agents.profile.prompt_catalog import render_prompt
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
    def next_model_id(models: list[Dict[str, Any]]) -> str:
        max_num = 0
        for model in models or []:
            if not isinstance(model, dict):
                continue
            raw_id = str(model.get("id") or "").strip()
            if not raw_id.startswith("SM-"):
                continue
            try:
                max_num = max(max_num, int(raw_id.split("-", 1)[1]))
            except (IndexError, ValueError):
                continue
        return f"SM-{max_num + 1}"

    @staticmethod
    def find_model_target(
        models: list[Dict[str, Any]],
        target: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        target_id = str(target.get("target_model_id") or target.get("id") or "").strip()
        if target_id:
            for model in models or []:
                if isinstance(model, dict) and str(model.get("id") or "").strip() == target_id:
                    return model
        target_type = str(target.get("type") or target.get("diagram_type") or "").strip()
        target_name = str(target.get("name") or "").strip()
        if target_type and target_name:
            for model in models or []:
                if (
                    isinstance(model, dict)
                    and str(model.get("type") or "").strip() == target_type
                    and str(model.get("name") or "").strip() == target_name
                ):
                    return model
        return None

    @staticmethod
    def model_name(model_type: str) -> str:
        zh_names = {
            "context_diagram": "系統架構圖",
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
        return "initial"

    @staticmethod
    def system_model_rows(artifact: Any) -> list[Dict[str, Any]]:
        if not isinstance(artifact, dict):
            return []
        models = artifact.get("system_models", [])
        if not isinstance(models, list):
            return []
        return [row for row in models if isinstance(row, dict)]

    @staticmethod
    def model_user_requirements(artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        source_rows = artifact.get("URL") or []
        return [
            {"id": r.get("id"), "text": r.get("text", "")}
            for r in source_rows
            if isinstance(r, dict) and str(r.get("text") or "").strip()
        ]

    @staticmethod
    def model_spec_requirements(artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        rows = []
        for req in artifact.get("REQ") or []:
            if not isinstance(req, dict):
                continue
            req_id = str(req.get("id") or "").strip()
            title = str(req.get("title") or "").strip()
            description = str(req.get("description") or "").strip()
            if not req_id or not (title or description):
                continue
            row: Dict[str, Any] = {
                "id": req_id,
                "title": title,
                "text": description or title,
            }
            req_type = str(req.get("type") or "").strip()
            if req_type:
                row["type"] = req_type
            raw_source = req.get("source") or []
            if isinstance(raw_source, list):
                source = [str(value).strip() for value in raw_source if str(value).strip()]
            else:
                source = [str(raw_source).strip()] if str(raw_source or "").strip() else []
            if source:
                row["source"] = source
            acceptance = [
                str(value).strip()
                for value in (req.get("acceptance_criteria") or [])
                if str(value).strip()
            ]
            if acceptance:
                row["acceptance_criteria"] = acceptance
            rows.append(row)
        return rows

    def model_requirements(self, artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        spec_rows = self.model_spec_requirements(artifact)
        return spec_rows or self.model_user_requirements(artifact)

    def model_requirement_source(self, artifact: Dict[str, Any]) -> str:
        return "REQ" if self.model_spec_requirements(artifact) else "URL"

    @staticmethod
    def model_related_requirement_ids(
        model: Dict[str, Any],
        target: Optional[Dict[str, Any]] = None,
    ) -> list[str]:
        rows: list[str] = []
        for source in (model, target or {}):
            if not isinstance(source, dict):
                continue
            for value in source.get("related_requirement_ids") or []:
                text = str(value).strip()
                if text and text not in rows:
                    rows.append(text)
            for item in source.get("text") or []:
                if not isinstance(item, dict):
                    continue
                for value in item.get("related_requirement_ids") or []:
                    text = str(value).strip()
                    if text and text not in rows:
                        rows.append(text)
        return rows

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
        out: Dict[str, Any] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows = []
            for item in feedback.get(section) or []:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                row: Dict[str, Any] = {"text": text}
                related_ids = [
                    str(value).strip()
                    for value in (item.get("related_requirement_ids") or [])
                    if str(value).strip()
                ]
                if related_ids:
                    row["related_requirement_ids"] = related_ids
                source = str(item.get("source") or "").strip()
                if source:
                    row["source"] = source
                rows.append(row)
            if rows:
                out[section] = rows
        sources = [
            str(source).strip()
            for source in (feedback.get("sources") or [])
            if str(source).strip()
        ]
        if sources:
            out["sources"] = sources
        return out

    def build_model_context(
        self,
        artifact: Dict[str, Any],
        *,
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """保留建模需要的 artifact 欄位，避免把 pending 內容畫成正式模型。"""
        return {
            "scenario": artifact.get("scenario", "") or artifact.get("rough_idea", ""),
            "stakeholders": self.model_stakeholders(artifact),
            "model_requirements": self.model_requirements(artifact),
            "requirement_source": self.model_requirement_source(artifact),
            "URL": self.model_user_requirements(artifact),
            "REQ": self.model_spec_requirements(artifact),
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
        return model_data

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
            "scenario": artifact_context.get("scenario", "") or artifact_context.get("rough_idea", ""),
            "stakeholders": self.model_stakeholders(artifact_context),
            "scope": artifact_context.get("scope", {}) or {},
            "feedback": self.model_feedback(artifact_context),
            "open_questions": artifact_context.get("open_questions", []) or [],
            "model_revision_context": artifact_context.get("model_revision_context", {}) or {},
            "model_target": artifact_context.get("model_target", {}) or {},
        }
        context_text = json.dumps(context_payload, ensure_ascii=False, indent=2)
        diagram_layout_hint = ""
        if diagram_type == "context_diagram":
            diagram_layout_hint = """
    本專案限制：context_diagram 對外作為「系統架構圖」，呈現系統邊界與高層互動，不是功能分解圖、流程圖、使用案例圖或內部元件圖。
    圖中心只能是本系統；外圍只能放外部 actor 或已明確存在的 external system。
    線條只標示主要資料流、事件流、請求/回應、通知或責任邊界；不要畫詳細操作步驟、流程分支、use case、資料表、service、database、controller 或內部模組。
    不可把未確認的 provider/API 畫成已定案外部系統；若來源未定，請使用抽象資料來源。
    只有 requirements 明確指出某項系統是既有外部系統或第三方服務時，才可畫成 external system。
    同一個外部角色只能畫一次；若多筆需求都指向同一角色，必須合併成同一個 actor，並把多個互動合併到同一條或同一組關係標籤。不得因來源需求不同而重複畫出同名或同義 actor。
    actor 命名必須使用穩定的利害關係人名稱；例如「外送員」「餐廳店員」各只能出現一次，不要分成多個外送員或多個餐廳店員。
    若需求只改變流程步驟、例外條件、驗收標準或功能細節，而沒有改變 actor、外部系統、主要資料/事件流或責任邊界，不應更新 context_diagram。"""
        elif diagram_type == "use_case_diagram":
            diagram_layout_hint = """
    版面要求：actor 與 use case 的關聯要一目了然；若單圖連線過多，可精簡為核心用例或依角色拆分。
    同一個 actor 或 use case 只能畫一次；若多筆需求指向同一使用者任務或同一角色，必須合併成同一元素，不得因來源需求不同而重複畫出同名或同義元素。"""
        elif diagram_type == "activity_diagram":
            diagram_layout_hint = """
    本專案限制：不要放入技術實作步驟。
    相同語意的活動節點只畫一次；若多筆需求描述同一操作、判斷或狀態更新，請合併成同一流程節點，不要重複畫同義步驟。"""
        elif diagram_type == "class_diagram":
            diagram_layout_hint = """
    本專案限制：只作為需求層級 domain model；避免加入未確認的 service、database、API 或實作類別。
    同一個 domain concept 只能畫一次；若多筆需求指向同一資料物件、業務概念或角色概念，必須合併成同一 class，不得重複畫同名或同義 class。"""
        elif diagram_type == "sequence_diagram":
            diagram_layout_hint = """
    本專案限制：一張圖聚焦一個主要情境流程；lifeline 使用需求層級角色/系統，不要放入低階 service/database 實作。
    同一個參與者、系統或外部服務只能有一條 lifeline；若多筆需求指向同一參與者，必須合併成同一 participant，不得重複畫同名或同義 lifeline。"""
        elif diagram_type == "state_machine":
            diagram_layout_hint = """
    本專案限制：若狀態不明確，不要硬畫。
    同一個業務狀態只能畫一次；若多筆需求描述同一狀態，必須合併成同一 state，不得因不同轉移來源重複畫同名或同義 state。"""


        description_rule = ""
        description_field = ""
        if diagram_type != "use_case_diagram":
            description_rule = """
    - description 請說明這張圖用來釐清哪一個需求面向，以及圖中實際呈現的關鍵元素或關係。描述重點必須符合該 UML 圖型本身的用途。只能描述圖中已呈現的內容，不得加入新需求；不要寫「未擴張、未臆測、未確認」這類自我辯護或否定句，只正向說明圖中呈現了什麼。"""
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
            task = f"""依照 UML skill，根據已生成的 Use Case Diagram 整理文字版使用案例。

需求 ID 對照（只可用於 related_requirement_ids，不可用來新增 use case）:
{req_text}

Use Case Diagram:
{use_case_diagram_text}

補充背景（只作為邊界、限制、風險或未決事項參考）:
{context_text}

專案邊界：
- 只能整理圖中已出現的 actor 與 use case；不要補入圖中沒有的 use case。
- related_requirement_ids 只能引用輸入中存在的 REQ-* 或 URL-*。
- interface 未明確時，使用需求層級名稱，不臆測 UI 細節。

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
      "related_requirement_ids": ["REQ-1"]
    }}
  ]
}}"""
            skill = uml_skill_subset(get_skill("UML"), "use_case_text")
            messages = self.build_skill_messages(skill, "UML", task)
            result = self.chat_json(messages)
            return parse_use_case_text(result)

        if existing_model and existing_model.get("plantuml"):
            task = f"""依照 UML skill，根據更新後的需求輸入精煉以下 {type_name}。

當前 PlantUML:
{existing_model['plantuml']}

需求輸入（優先為 REQ-*；若尚未產生 REQ，則為 URL-*）:
{req_text}

補充背景（只作為邊界、限制、風險或未決事項參考）:
{context_text}

{diagram_layout_hint}

專案邊界：
- 以上一版 PlantUML 為基礎，只修改受本次需求輸入或修訂脈絡影響的元素。
- 保留未受影響且仍有效的 actor、use case、流程、資料、狀態或概念。
- 圖中元素使用目前輸出語系，不混用語言。
- feedback 不可畫成已確認元素。
- related_requirement_ids 只能引用輸入中存在的 REQ-*；沒有 REQ 時才可用 URL-*。
{description_rule}

輸出 JSON:
{{"name": "簡短直觀的模型名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "related_requirement_ids": ["REQ-1"]{description_field}}}"""
        else:
            task = f"""依照 UML skill，根據以下需求輸入產生 {type_name}。

需求輸入（優先為 REQ-*；若尚未產生 REQ，則為 URL-*）:
{req_text}

補充背景（只作為邊界、限制、風險或未決事項參考）:
{context_text}

{diagram_layout_hint}

專案邊界：
- 只根據輸入中的需求與已接受脈絡建模。
- 圖中元素使用目前輸出語系，不混用語言。
- feedback 不可畫成已確認元素。
- related_requirement_ids 只能引用輸入中存在的 REQ-*；沒有 REQ 時才可用 URL-*。
{description_rule}

輸出 JSON:
{{"name": "簡短直觀的模型名稱", "type": "{diagram_type}", "plantuml": "@startuml\\n...\\n@enduml", "related_requirement_ids": ["REQ-1"]{description_field}}}"""

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
        user_prompt = render_prompt('agents_profile_modeler_modeling_user_prompt_19', **locals())

        try:
            skill = uml_skill_subset(get_skill("UML"), "repair", model.get("type", ""))
            messages = self.build_skill_messages(skill, "UML", user_prompt)
            response = self.chat_json(messages)
            return parse_plantuml_fix(response)["plantuml"]
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
