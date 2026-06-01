# Modeler agent: UML model generation, model updates, and issue response.
import json
from typing import Any, Dict, Optional

from agents.base import BaseAgent
from agents.skills.base import get_skill

from .modeling import ModelerModeling
from .prompts import (
    MODELER_SYSTEM_PROMPT,
    model_action_prompt,
    model_impact_prompt,
    uml_skill_subset,
)
from .issues import ModelerIssues
from .validation import ALLOWED_MODEL_TYPES, parse_impact_assessment


MODELER_LOOP_ACTIONS = [
    "plan_models",
    "create_model",
    "update_model",
    "validate_model",
    "fix_model",
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

    system_prompt = MODELER_SYSTEM_PROMPT

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
- 只在議題有互動、流程、資料、狀態、責任邊界或模型追蹤價值時使用；若用圖能讓討論更清楚，也可以建立或更新模型輔助說明。
- 沒有流程、資料、狀態、角色互動、責任邊界或視覺化價值時不要使用。
- 若使用，只產生需求層級模型參考；不可從模型反推新增需求或把未確認內容畫成正式模型。"""

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return """- artifact_query 用於查詢需求、scope、feedback、open_questions 與既有 models。
- plantuml_validate 用於驗證或修正 PlantUML 語法；驗證通過不代表需求內容已被正式決策。
- 模型必須以 User Requirements（URL-*）與目前 scope 為主。
- feedback 只能作為邊界、限制、風險或不確定性提示，不可被轉成新的 actor、use case、class、state 或流程步驟。
- 資訊不足時不要硬畫未確認元素，不可用圖反推新增需求。"""

    def build_model_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_model_state(
            kwargs["artifact"],
            kwargs.get("recent_discussions"),
            kwargs.get("issue"),
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

    def run_model_loop(self, artifact, recent_discussions=None, issue=None):
        """Modeler 子 OODA：依 plan_models 產生的 targets 逐一建模，完成後由 done 結束。"""
        sentinel = object()
        previous_issue = artifact.get("current_issue", sentinel)
        if issue is not None:
            artifact["current_issue"] = issue
        try:
            result = self.run_action_loop(
                name="model",
                context={
                    "artifact": artifact,
                    "recent_discussions": recent_discussions,
                    "issue": issue,
                },
                build_observation=self.build_model_observation,
                decide_action=self.decide_model_action,
                execute_action=self.execute_model_loop_action,
            )
            models = self.parse_model_output(
                artifact.get("system_models", []),
                source=artifact.get("model_source", ""),
            )
            artifact["system_models"] = self.validate_plantuml_models(models)
            return result
        finally:
            if issue is not None:
                if previous_issue is sentinel:
                    artifact.pop("current_issue", None)
                else:
                    artifact["current_issue"] = previous_issue

    def build_model_state(
        self, artifact, recent_discussions, issue, actions_taken,
        iteration, max_iterations,
    ):
        models = self.system_model_rows(artifact)
        current_model_rows = [
            {"id": m.get("id"), "name": m.get("name"), "type": m.get("type"),
             "source": m.get("source"),
             "has_plantuml": bool(m.get("plantuml"))}
            for m in models
        ]
        summary_reqs = self.model_requirements(artifact)
        disc_summaries = []
        for disc in (recent_discussions or []):
            discussion_issue = disc.get("issue", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "issue_id": discussion_issue.get("id"),
                "title": discussion_issue.get("title"),
                "summary": (resolution.get("summary") or ""),
            })
        return {
            "issue": self.model_issue_context(issue),
            "scenario": artifact.get("scenario", "") or artifact.get("rough_idea", ""),
            "stakeholders": self.model_stakeholders(artifact),
            "requirements": summary_reqs,
            "requirement_source": self.model_requirement_source(artifact),
            "user_requirements": self.model_user_requirements(artifact),
            "REQ": self.model_spec_requirements(artifact),
            "scope": artifact.get("scope", {}),
            "feedback": self.model_feedback(artifact),
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

    @staticmethod
    def model_issue_context(issue: Any) -> Dict[str, Any]:
        if not isinstance(issue, dict):
            return {}
        return {
            "id": issue.get("id"),
            "title": issue.get("title"),
            "category": issue.get("category"),
            "description": issue.get("description", ""),
            "trace": issue.get("trace", {}),
            "discussion_round_index": issue.get("discussion_round_index"),
            "discussion_rounds": issue.get("discussion_rounds"),
        }

    def execute_model_action(
        self, action, params, artifact, last_observation=None,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "plan_models":
            reqs = self.model_requirements(artifact)
            models = self.system_model_rows(artifact)
            context = {
                "issue": self.model_issue_context(
                    artifact.get("current_issue")
                    or artifact.get("issue")
                    or artifact.get("model_issue")
                ),
                "scenario": artifact.get("scenario", "") or artifact.get("rough_idea", ""),
                "stakeholders": self.model_stakeholders(artifact),
                "requirements": reqs,
                "requirement_source": self.model_requirement_source(artifact),
                "user_requirements": self.model_user_requirements(artifact),
                "REQ": self.model_spec_requirements(artifact),
                "scope": artifact.get("scope", {}),
                "feedback": self.model_feedback(artifact),
                "open_questions": artifact.get("open_questions", []),
                "current_models": [
                    {
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "type": m.get("type"),
                        "source": m.get("source"),
                    }
                    for m in models
                ],
                "model_revision_context": artifact.get("model_revision_context", {}) or {},
            }
            task = model_impact_prompt(context=context)
            skill = uml_skill_subset(get_skill("UML"), "selection")
            messages = self.build_skill_messages(skill, "UML", task)
            try:
                result = parse_impact_assessment(self.chat_json(messages))
                obs["result"] = result
                targets = result.get("model_targets", [])
                to_update = result.get("models_to_update", [])
                to_create = result.get("models_to_create", [])
                consistency_summary = result.get("consistency_summary", "")
                gaps = result.get("gaps", [])
                if not isinstance(gaps, list):
                    gaps = []
                obs["summary"] = (
                    f"影響評估: 目標 {len(targets)}, 更新 {len(to_update)}, 新建 {len(to_create)}"
                )
                if consistency_summary:
                    obs["summary"] += f"；一致性: {consistency_summary}"
                if gaps:
                    obs["summary"] += f"；缺口 {len(gaps)} 項"
                report = {
                    "consistency_summary": consistency_summary,
                    "gaps": gaps,
                    "model_targets": targets,
                    "models_to_update": to_update,
                    "models_to_create": to_create,
                    "impact_summary": result.get("impact_summary", ""),
                }
                artifact["model_consistency_report"] = report
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"影響評估失敗: {e}"
            return obs

        if action in {"create_model", "update_model"}:
            target = params.get("target") if isinstance(params.get("target"), dict) else {}
            diagram_type = target.get("type") or params.get("diagram_type", "")
            if not diagram_type:
                obs["error"] = "diagram_type 參數為空"
                return obs
            models = self.system_model_rows(artifact)
            operation = "create" if action == "create_model" else "update"
            target = {**target, "operation": operation}
            existing = None if operation == "create" else self.find_model_target(models, target)
            reqs = self.model_requirements(artifact)
            try:
                result = self.generate_or_update_model(
                    diagram_type, reqs,
                    existing_model=existing,
                    artifact_context={**artifact, "model_target": target},
                )
                if diagram_type == "use_case_text":
                    use_case_diagram = self.find_model_target(models, {**target, "type": "use_case_diagram"})
                    if not use_case_diagram:
                        raise ValueError("use_case_text requires existing use_case_diagram")
                    use_case_diagram["text"] = result.get("text", [])
                    obs["summary"] = "use_case_diagram 文字用例已更新"
                    return obs
                new_name = (
                    str(result.get("name") or "").strip()
                    or str(target.get("name") or "").strip()
                    or self.model_name(diagram_type)
                )
                new_row = {
                    "id": str((existing or {}).get("id") or target.get("target_model_id") or "").strip()
                    or self.next_model_id(models),
                    "name": new_name,
                    "type": result.get("type") or diagram_type,
                }
                if result.get("plantuml"):
                    new_row["plantuml"] = result.get("plantuml", "")
                if result.get("description") and diagram_type != "use_case_diagram":
                    new_row["description"] = result.get("description", "")
                if result.get("text"):
                    new_row["text"] = result.get("text", [])
                new_row["source"] = artifact.get("model_source") or self.model_source(
                    artifact.get("model_revision_context")
                )
                if existing:
                    existing.clear()
                    existing.update(new_row)
                    existing["name"] = new_name
                    target_row = existing
                else:
                    models.append(new_row)
                    artifact["system_models"] = models
                    target_row = new_row
                if diagram_type == "use_case_diagram":
                    use_case_text = self.generate_or_update_model(
                        "use_case_text",
                        reqs,
                        artifact_context=artifact,
                    )
                    target_row["text"] = use_case_text.get("text", [])
                label = "更新" if existing else "新建"
                obs["result"] = {
                    "target_model_id": target_row.get("id"),
                    "type": target_row.get("type"),
                    "name": target_row.get("name"),
                }
                obs["summary"] = f"{diagram_type}:{target_row.get('name', '')} 已{label}"
                if diagram_type == "use_case_diagram":
                    obs["summary"] += "，並已產生文字用例"
            except Exception as e:
                obs["error"] = str(e)
                label = "建立" if operation == "create" else "更新"
                obs["summary"] = f"{diagram_type} {label}失敗: {e}"
            return obs

        if action == "validate_model":
            target_info = params.get("target") if isinstance(params.get("target"), dict) else {}
            diagram_type = target_info.get("type") or params.get("diagram_type", "")
            models = self.system_model_rows(artifact)
            target = self.find_model_target(models, target_info) or (
                next((m for m in models if m.get("type") == diagram_type), None)
                if not target_info.get("target_model_id") and not target_info.get("name")
                else None
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

        if action == "fix_model":
            target_info = params.get("target") if isinstance(params.get("target"), dict) else {}
            diagram_type = target_info.get("type") or params.get("diagram_type", "")
            models = self.system_model_rows(artifact)
            target = self.find_model_target(models, target_info) or (
                next((m for m in models if m.get("type") == diagram_type), None)
                if not target_info.get("target_model_id") and not target_info.get("name")
                else None
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

    def decide_next_model_action(self, state, last_observation=None):
        if not state.get("current_models") and not state.get("actions_taken"):
            return {
                "action": "plan_models",
                "params": {},
                "reasoning": "尚無系統模型，先規劃需要建立的模型。",
            }
        planned = self.model_target_action_plan(last_observation)
        if planned:
            return planned
        user_prompt = model_action_prompt(
            state=state,
            last_observation=last_observation or {},
        )

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

    @staticmethod
    def model_target_action_plan(last_observation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(last_observation, dict):
            return {}
        if last_observation.get("action") != "plan_models":
            return {}
        result = last_observation.get("result")
        if not isinstance(result, dict):
            return {}
        targets = result.get("model_targets")
        if not isinstance(targets, list) or not targets:
            return {}
        steps = []
        for idx, target in enumerate(targets, 1):
            if not isinstance(target, dict):
                continue
            operation = str(target.get("operation") or "").strip()
            if operation not in {"create", "update"}:
                continue
            action = "create_model" if operation == "create" else "update_model"
            clean_target = {
                key: value
                for key, value in target.items()
                if value not in (None, "", [], {})
            }
            steps.append(
                {
                    "id": f"model-target-{idx}",
                    "action": action,
                    "params": {"target": clean_target},
                    "reasoning": str(target.get("reason") or "").strip(),
                }
            )
        if not steps:
            return {}
        return {
            "action": steps[0]["action"],
            "params": steps[0]["params"],
            "reasoning": "依 plan_models 的 model_targets 逐一建立或更新模型。",
            "action_plan": {
                "goal": "完成 plan_models 指定的所有模型目標",
                "steps": steps,
            },
        }

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
            available_actions={
                "answer_question": "使用時機：有人在 open_questions 中指定 modeler 回答。不要使用：一般議題發言或建模流程。寫回或影響：只回答問題，不更新專案資料。",
                "respond_issue": "使用時機：只需要根據 issue、前文與現有資料表達建模觀點。不要使用：需要建立、更新或驗證 UML/system model 時。寫回或影響：只產生會議發言，不更新系統模型。",
                "model_system": "使用時機：議題涉及系統邊界、actor/use case、流程、資料、狀態、互動順序、責任分工或模型追蹤性，且建立/更新 UML/system model 能讓討論更清楚或檢查一致性。不要使用：只是需求文字、業務偏好或衝突取捨，且沒有流程、資料、狀態、角色互動、責任邊界或視覺化價值。寫回或影響：內部依序選 plan_models、create_model/update_model、validate_model、fix_model；結果更新系統模型，不從模型反推需求。",
            },
            default_action="respond_issue",
            last_result=last_result,
        )

    def execute_issue_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        artifact = kwargs.get("artifact")
        model_action_result: Optional[Dict[str, Any]] = None
        if action == "answer_question":
            model_action_result = {
                "action": action,
                "output": None,
                "summary": "回答 open question，不更新專案資料。",
            }
        elif action == "respond_issue":
            model_action_result = {
                "action": action,
                "output": None,
                "summary": "只產生會議回答，不更新專案資料。",
            }
        elif action == "model_system":
            if not isinstance(artifact, dict):
                return {
                    "action": action,
                    "status": "failed",
                    "error": "missing_artifact",
                    "format_error": "model_system requires artifact context",
                    "summary": "modeler model_system 缺少 artifact，無法執行建模流程",
                }
            loop_result = self.run_model_loop(
                artifact,
                recent_discussions=kwargs.get("previous_responses"),
                issue=kwargs.get("issue"),
            )
            trace = loop_result.get("opa_trace") if isinstance(loop_result, dict) else []
            model_action_result = {
                "action": action,
                "steps": [
                    {
                        "decision": row.get("decision", {}),
                        "result": row.get("result", {}),
                    }
                    for row in (trace or [])
                    if isinstance(row, dict)
                ],
                "system_models": artifact.get("system_models", []),
                "model_consistency_report": artifact.get("model_consistency_report", {}),
            }
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "action_result": model_action_result or {"action": action, "output": None},
            "summary": f"完成 modeler action: {decision.get('action', '')}",
        }
