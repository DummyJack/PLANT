# Modeler agent: UML model generation, model updates, and issue response.
import json
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from agents.skills.base import get_skill

from .modeling import ModelerModeling
from .prompts import uml_skill_subset
from .issues import ModelerIssues
from .validation import ALLOWED_MODEL_TYPES, model_types, parse_impact_assessment


MODELER_ROLE_PROMPT = """你是 UML 系統建模專家，負責把需求轉成可驗證、可追溯的 UML 模型。

規則：
1. 精煉時只改受影響部分，保留未變動元素。
2. 發現不一致時指出模型影響與缺口；不得直接改變已知需求語意。
3. 資訊不足時不要硬畫未確認元素；不可臆造。"""


MODELER_LOOP_ACTIONS = [
    "build_full_model",
    "assess_impact",
    "update_diagram",
    "validate_diagram",
    "fix_diagram",
    "done",
]


AVAILABLE_MODEL_TYPES = sorted(ALLOWED_MODEL_TYPES)

class ModelerAgent(
    ModelerModeling,
    ModelerIssues,
    BaseAgent,
):
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
            skill_names=["UML"],
            project_config=project_config,
        )

    def skill_usage_policy(self) -> str:
        return """UML：
- 用於議題涉及系統邊界、actor/use case、角色互動、流程、資料輸入/輸出、資料物件、互動順序、狀態轉換或需求到模型元素追蹤。
- 用於模型能幫助釐清需求一致性、可行性、缺口或影響範圍時。
- 只在議題有互動、流程、資料、狀態或模型追蹤價值時使用；沒有模型影響時不要使用。
- 若使用，只產生需求層級模型參考；不可從模型反推新增需求或把未確認內容畫成正式模型。"""

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return """- artifact_query 用於查詢 URL、scope、feedback、open_questions 與既有 models。
- plantuml_validate 用於驗證或修正 PlantUML 語法；驗證通過不代表需求內容已被正式決策。
- 模型必須以 URL 與目前 scope 為依據；資訊不足時不要硬畫未確認元素，不可用圖反推新增需求。"""

    def build_model_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_model_state(
            kwargs["artifact"],
            kwargs.get("recent_discussions"),
            kwargs.get("actions_taken", []),
            kwargs["iteration"],
            kwargs["max_iterations"],
        )

    def decide_model_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.decide_next_model_action(observation, last_result)

    def execute_model_loop_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.execute_model_action(
            decision.get("action", "done"),
            decision.get("params") or {},
            kwargs["artifact"],
            kwargs.get("last_result"),
        )

    def run_model_loop(self, artifact, recent_discussions=None):
        """Modeler 子 OODA：最多三輪，由 done 判斷是否提前結束。"""
        return self.run_action_loop(
            name="model",
            context={
                "artifact": artifact,
                "recent_discussions": recent_discussions,
            },
            build_observation=self.build_model_observation,
            decide_action=self.decide_model_action,
            execute_action=self.execute_model_loop_action,
        )

    def build_model_state(
        self, artifact, recent_discussions, actions_taken,
        iteration, max_iterations,
    ):
        models = self.system_model_rows(artifact)
        current_model_rows = [
            {"name": m.get("name"), "type": m.get("type"),
             "source": m.get("source"),
             "has_plantuml": bool(m.get("plantuml"))}
            for m in models
        ]
        summary_reqs = self.model_requirements(artifact)
        disc_summaries = []
        for disc in (recent_discussions or []):
            issue = disc.get("issue", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "issue_id": issue.get("id"),
                "title": issue.get("title"),
                "summary": (resolution.get("summary") or ""),
            })
        return {
            "requirements": summary_reqs,
            "scope": artifact.get("scope", {}),
            "feedback": artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {},
            "current_models": current_model_rows,
            "model_revision_context": artifact.get("model_revision_context", {}) or {},
            "open_questions": [
                {
                    "question": q.get("question"),
                    "status": q.get("status"),
                    "type": q.get("type"),
                }
                for q in artifact.get("open_questions", [])
                if isinstance(q, dict)
            ],
            "recent_discussions": disc_summaries,
            "actions_taken": actions_taken,
            "has_validator": "plantuml_validate" in self.tools,
            "available_model_types": list(AVAILABLE_MODEL_TYPES),
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_model_action(
        self, action, params, artifact, last_observation=None,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "build_full_model":
            records = self.execute_full_modeling(
                artifact,
                last_observation=last_observation,
            )
            obs["result"] = {"records": records}
            obs["summary"] = f"完整建模流程完成：{len(records)} 個步驟"
            return obs

        if action == "assess_impact":
            reqs = self.model_requirements(artifact)
            models = self.system_model_rows(artifact)
            context = {
                "requirements": reqs,
                "scope": artifact.get("scope", {}),
                "feedback": artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {},
                "open_questions": artifact.get("open_questions", []),
                "current_models": [
                    {
                        "name": m.get("name"),
                        "type": m.get("type"),
                        "source": m.get("source"),
                    }
                    for m in models
                ],
                "model_revision_context": artifact.get("model_revision_context", {}) or {},
            }
            ctx_text = json.dumps(context, ensure_ascii=False, indent=2)
            task = f"""分析需求與現有模型，完成兩件事：(1) 判斷哪些圖表需要更新或新建；(2) 產出與需求的一致性說明與缺口報告。

    # 輸入資料
    {ctx_text}

    # 輸出要求
    - models_to_update：需更新的 model type 列表（限 use_case_text, context_diagram, use_case_diagram, activity_diagram, sequence_diagram, state_machine, class_diagram；use_case_text 會附在 use_case_diagram.text）
    - models_to_create：需新建的 model type 列表
    - 若既有模型已存在，這是 revision-aware 模型迭代；只標記受 model_revision_context 或 requirements 影響的圖表。
    - current_models.source 表示既有模型來源，例如 initial_modeling 或 R1-M1；只用於追蹤來源，不可改寫成新需求。
    - 未受影響的既有圖表不得列入 models_to_update。
    - feedback 只作為限制/風險註記，不可擴張功能。
    輸出 JSON:
    {{
    "models_to_update": ["需更新的 diagram type"],
    "models_to_create": ["需新建的 diagram type"],
    "impact_summary": "影響摘要",
    "consistency_summary": "與需求一致性的整體說明",
    "gaps": ["缺口或不一致項目1", "缺口或不一致項目2"]
    }}
    只輸出 JSON。"""
            skill = uml_skill_subset(get_skill("UML"), "selection")
            messages = self.build_skill_messages(skill, "UML", task)
            try:
                result = parse_impact_assessment(self.chat_json(messages))
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
                report = {
                    "consistency_summary": consistency_summary,
                    "gaps": gaps,
                    "models_to_update": to_update,
                    "models_to_create": to_create,
                    "impact_summary": result.get("impact_summary", ""),
                }
                artifact["model_consistency_report"] = report
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"影響評估失敗: {e}"
            return obs

        if action == "update_diagram":
            diagram_type = params.get("diagram_type", "")
            if not diagram_type:
                obs["error"] = "diagram_type 參數為空"
                return obs
            models = self.system_model_rows(artifact)
            existing = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            reqs = self.model_requirements(artifact)
            try:
                result = self.generate_or_update_model(
                    diagram_type, reqs,
                    existing_model=existing,
                    artifact_context=artifact,
                )
                if diagram_type == "use_case_text":
                    use_case_diagram = next(
                        (
                            m for m in models
                            if m.get("type") == "use_case_diagram"
                        ),
                        None,
                    )
                    if not use_case_diagram:
                        raise ValueError("use_case_text requires existing use_case_diagram")
                    use_case_diagram["text"] = result.get("text", [])
                    obs["summary"] = "use_case_diagram 文字用例已更新"
                    return obs
                new_name = str(result.get("name") or "").strip() or self.model_name(diagram_type)
                new_row = {
                    "name": new_name,
                    "type": result.get("type") or diagram_type,
                }
                if result.get("plantuml"):
                    new_row["plantuml"] = result.get("plantuml", "")
                if result.get("text"):
                    new_row["text"] = result.get("text", [])
                new_row["source"] = artifact.get("model_source", "")
                if existing:
                    existing.clear()
                    existing.update(new_row)
                    existing["name"] = new_name
                else:
                    models.append(new_row)
                    artifact["system_models"] = models
                label = "更新" if existing else "新建"
                obs["summary"] = f"{diagram_type} 已{label}"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"{diagram_type} 更新失敗: {e}"
            return obs

        if action == "validate_diagram":
            diagram_type = params.get("diagram_type", "")
            models = self.system_model_rows(artifact)
            target = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            if not target:
                obs["error"] = f"找不到 {diagram_type}"
                return obs
            if not target.get("plantuml"):
                obs["result"] = {"valid": True}
                obs["summary"] = f"{diagram_type}: 非 PlantUML 模型，跳過語法驗證"
                return obs
            validator = self.tools.get("plantuml_validate")
            if not validator:
                obs["result"] = {"valid": True}
                obs["summary"] = f"{diagram_type}: 無驗證工具，跳過"
                return obs
            code = target.get("plantuml", "")
            result = self.execute_tool(
                "plantuml_validate",
                {"plantuml_code": code},
                active_skill="UML",
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
            models = self.system_model_rows(artifact)
            target = next(
                (m for m in models if m.get("type") == diagram_type), None
            )
            if not target:
                obs["error"] = f"找不到 {diagram_type}"
                return obs
            if not target.get("plantuml"):
                obs["result"] = {"skipped": True}
                obs["summary"] = f"{diagram_type}: 非 PlantUML 模型，無需修正"
                return obs
            error_msg = ""
            if (
                last_observation
                and isinstance(last_observation.get("result"), dict)
            ):
                error_msg = last_observation["result"].get("error", "")
            if not error_msg:
                error_msg = "語法錯誤"
            fixed = self.repair_plantuml(target, error_msg)
            if fixed:
                target["plantuml"] = fixed
                obs["summary"] = f"{diagram_type} 已修正"
            else:
                obs["error"] = "修正失敗"
                obs["summary"] = f"{diagram_type} 修正失敗"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    def execute_full_modeling(
        self,
        artifact: Dict[str, Any],
        *,
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """在一個 model action 內執行 assess → update → validate/fix 的完整建模流程。"""
        self.logger.info("  Modeler: assess → update → validate")
        records: List[Dict[str, Any]] = []

        assess_obs = self.execute_model_action(
            "assess_impact",
            {},
            artifact,
            last_observation,
        )
        records.append(
            {
                "action": "assess_impact",
                "params": {},
                "result_summary": assess_obs.get("summary", ""),
            }
        )
        last_obs = assess_obs

        refreshed_report = artifact.get("model_consistency_report") or {}
        refreshed_targets = self.model_types(
            (refreshed_report.get("models_to_update") or [])
            + (refreshed_report.get("models_to_create") or [])
        )
        target_types: List[str] = []
        if refreshed_targets:
            target_types = refreshed_targets
        if "use_case_diagram" in target_types:
            target_types = [
                item for item in target_types
                if item not in {"use_case_diagram", "use_case_text"}
            ]
            target_types = ["use_case_diagram", "use_case_text"] + target_types

        if not target_types:
            return records

        for diagram_type in target_types:
            update_params = {"diagram_type": diagram_type}
            update_obs = self.execute_model_action(
                "update_diagram",
                update_params,
                artifact,
                last_obs,
            )
            records.append(
                {
                    "action": "update_diagram",
                    "params": update_params,
                    "result_summary": update_obs.get("summary", ""),
                }
            )
            last_obs = update_obs
            if update_obs.get("error"):
                continue
            if diagram_type == "use_case_text":
                continue

            validate_obs = self.execute_model_action(
                "validate_diagram",
                update_params,
                artifact,
                last_obs,
            )
            records.append(
                {
                    "action": "validate_diagram",
                    "params": update_params,
                    "result_summary": validate_obs.get("summary", ""),
                }
            )
            last_obs = validate_obs

            valid = (
                isinstance(validate_obs.get("result"), dict)
                and validate_obs["result"].get("valid") is True
            )
            if valid:
                continue

            fix_obs = self.execute_model_action(
                "fix_diagram",
                update_params,
                artifact,
                last_obs,
            )
            records.append(
                {
                    "action": "fix_diagram",
                    "params": update_params,
                    "result_summary": fix_obs.get("summary", ""),
                }
            )
            last_obs = fix_obs

            revalidate_obs = self.execute_model_action(
                "validate_diagram",
                update_params,
                artifact,
                last_obs,
            )
            records.append(
                {
                    "action": "validate_diagram",
                    "params": update_params,
                    "result_summary": revalidate_obs.get("summary", ""),
                }
            )
            last_obs = revalidate_obs

        return records

    def diagram_types(self, items: List[Any]) -> List[str]:
        return self.model_types(items)

    def model_types(self, items: List[Any]) -> List[str]:
        return model_types(items)

    def decide_next_model_action(self, state, last_observation=None):
        if not state.get("current_models") and not state.get("actions_taken"):
            return {
                "action": "build_full_model",
                "params": {},
                "reasoning": "尚無系統模型，先用單一 model action 建立完整核心 UML。",
            }
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)
        user_prompt = f"""# 任務
    根據當前狀態與上一步結果，選下一個動作。

    # 動作
    - build_full_model：尚無模型時，一次建立完整 requirement-level models，並完成驗證/修正
    - assess_impact：先判斷哪些圖表受影響
    - update_diagram：{{"diagram_type":"use_case_text/context_diagram/use_case_diagram/activity_diagram/sequence_diagram/state_machine/class_diagram"}}；use_case_text 會附在 use_case_diagram.text
    - validate_diagram：{{"diagram_type":"..."}}
    - fix_diagram：{{"diagram_type":"..."}}
    - done：結束

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - 先 assess_impact，再決定是否更新模型
    - 圖表是否需要建立或更新，以 assess_impact 的 UML skill 判斷結果為準；不要自行新增未列入的圖表。
    - 需要補專案事實或驗證模型語法時，遵守本輪工具使用資料
    - 每個需更新的圖表都走：update_diagram → validate_diagram →（若失敗）fix_diagram → validate_diagram
    - 所有受影響圖表處理完後選 done
    - reasoning 請使用一句繁體中文簡述。

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}},
      "reasoning": "一句說明"
    }}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(messages)
                response = self.parse_issue_response_json(raw)
            else:
                response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"Modeler model loop 決策輸出格式不合格: {e}") from e

        action = (response.get("action") or "").strip()
        if action not in MODELER_LOOP_ACTIONS:
            raise ValueError(f"Modeler model loop action 不合法: {action or '<empty>'}")
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        return out

    def build_issue_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.issue_response_observation(**kwargs)

    def decide_issue_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.issue_response_decision(
            observation,
            done_reasoning="上一輪建模回應已符合格式契約，結束本次回應。",
            active_reasoning="根據議題類型選擇對應的建模回應策略。",
            last_result=last_result,
        )

    def execute_issue_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_prompt = self.build_issue_response_prompt(
            issue=kwargs["issue"],
            previous_responses=kwargs.get("previous_responses"),
            artifact_context=(kwargs.get("observation") or {}).get("artifact_context"),
        )
        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_issue_response(messages)
        if response.get("error") or not str(response.get("text") or "").strip():
            return {
                "action": decision.get("action", ""),
                "status": "failed",
                "error": response.get("error") or "missing_text",
                "format_error": response.get("format_error") or "issue response must include text",
                "summary": f"modeler issue_response 格式不合格: {decision.get('action', '')}",
            }
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "text": response.get("text", ""),
            "pair_reviews": response.get("pair_reviews", []),
            "open_questions": response.get("open_questions", []),
            "target_stakeholders": response.get("target_stakeholders", []),
            "summary": f"完成 modeler issue_response: {decision.get('action', '')}",
        }
