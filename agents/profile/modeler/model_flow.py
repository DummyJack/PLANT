# Handles system model planning, creation, updates, and validation.
from agents.profile.modeler.repair import render_repair_prompt
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from agents.skills.base import get_skill
from utils.language import current_output_language
from .actions.create import create_model
from .actions.update import update_model
from .actions.use_case import use_case_text
from .plan import ModelPlan, modeling_phase_policy, target_prompt
from .rules import model_description_contract, model_layout_hint
from .skill import uml_skill_subset
from .validation import (
    model_type_set,
    parse_diagram_model,
    parse_model_list,
    parse_use_case,
    parse_plantuml_fix,
    parse_impact_assessment,
)


# Defines ModelerModeling class for this module workflow.
class ModelerModeling(ModelPlan):
    model_type_list = sorted(model_type_set)

    # Defines obs model function for this module workflow.
    def obs_model(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_model_state(
            kwargs["artifact"],
            kwargs.get("recent_discussions"),
            kwargs.get("issue"),
            kwargs.get("actions_taken", []),
            kwargs["iteration"],
            kwargs["max_iterations"],
        )

    # Defines decide model action function for this module workflow.
    def decide_model_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.plan_model(observation, last_result)

    # Defines run model step function for this module workflow.
    def run_model_step(
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

    # Defines run model loop function for this module workflow.
    def run_model_loop(
        self,
        artifact,
        recent_discussions=None,
        issue=None,
        modeling_phase: Optional[str] = None,
    ):
        sentinel = object()
        previous_issue = artifact.get("current_issue", sentinel)
        previous_phase = artifact.get("modeling_phase", sentinel)
        if issue is not None:
            artifact["current_issue"] = issue
        if modeling_phase:
            artifact["modeling_phase"] = modeling_phase
        try:
            result = self.run_action_loop(
                name="model",
                context={
                    "artifact": artifact,
                    "recent_discussions": recent_discussions,
                    "issue": issue,
                },
                obs_fn=self.obs_model,
                decide_action=self.decide_model_action,
                execute_action=self.run_model_step,
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
            if modeling_phase:
                if previous_phase is sentinel:
                    artifact.pop("modeling_phase", None)
                else:
                    artifact["modeling_phase"] = previous_phase

    # Defines build model state function for this module workflow.
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
        phase = self.modeling_phase(artifact, issue)
        policy = modeling_phase_policy(phase)
        return {
            "modeling_phase": phase,
            "modeling_policy": policy,
            "resume_checkpoint": (
                artifact.get("meta", {}).get("last_resume_checkpoint")
                if isinstance(artifact.get("meta"), dict)
                and isinstance(artifact.get("meta", {}).get("last_resume_checkpoint"), dict)
                else {}
            ),
            "issue": self.model_issue_context(issue),
            "scenario": artifact.get("scenario", "") or artifact.get("rough_idea", ""),
            "stakeholders": self.model_stakeholders(artifact),
            "model_requirements": summary_reqs,
            "requirement_source": self.model_requirement_source(artifact),
            "URL": self.model_user_requirements(artifact),
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
            "available_model_types": list(self.model_type_list),
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    @staticmethod
    # Defines modeling phase function for this module workflow.
    def modeling_phase(artifact: Dict[str, Any], issue: Any = None) -> str:
        explicit = str(artifact.get("modeling_phase") or "").strip()
        if explicit:
            return explicit
        if isinstance(issue, dict):
            category = str(issue.get("category") or "").strip()
            description = str(issue.get("description") or "").strip()
            if category == "align_model" and "正式化" in description:
                return "post_requirement_formalization"
            if category == "align_model":
                return "align_model_issue"
        return "align_model_issue"

    @staticmethod
    # Defines model issue context function for this module workflow.
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

    # Defines execute model action function for this module workflow.
    def execute_model_action(
        self, action, params, artifact, last_observation=None,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}
        checkpoint_target = params.get("target") if isinstance(params.get("target"), dict) else {}
        checkpoint_label = (
            str(checkpoint_target.get("target_model_id") or "").strip()
            or str(checkpoint_target.get("type") or "").strip()
            or action
        )
        self.record_runtime_checkpoint(
            stage_id="system_model",
            step_id=f"system_model.{action}.{checkpoint_label}",
            action=action,
        )

        if action == "plan_models":
            reqs = self.model_requirements(artifact)
            models = self.system_model_rows(artifact)
            context = {
                "modeling_phase": self.modeling_phase(
                    artifact,
                    artifact.get("current_issue")
                    or artifact.get("issue")
                    or artifact.get("model_issue"),
                ),
                "issue": self.model_issue_context(
                    artifact.get("current_issue")
                    or artifact.get("issue")
                    or artifact.get("model_issue")
                ),
                "scenario": artifact.get("scenario", "") or artifact.get("rough_idea", ""),
                "stakeholders": self.model_stakeholders(artifact),
                "model_requirements": reqs,
                "requirement_source": self.model_requirement_source(artifact),
                "URL": self.model_user_requirements(artifact),
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
            context["modeling_policy"] = modeling_phase_policy(context["modeling_phase"])
            task = target_prompt(context=context)
            skill = uml_skill_subset(get_skill("UML"), "selection")
            messages = self.build_skill_messages(skill, "UML", task)
            try:
                raw_plan = self.chat_json(messages)
                try:
                    result = parse_impact_assessment(raw_plan)
                except Exception as plan_error:
                    repair_prompt = render_repair_prompt(
                        "model_plan_repair",
                        raw=json.dumps(raw_plan, ensure_ascii=False, indent=2)
                        if isinstance(raw_plan, (dict, list))
                        else str(raw_plan),
                        error_msg=str(plan_error),
                    )
                    repaired = self.chat_json(
                        self.build_skill_messages(
                            skill,
                            "UML",
                            repair_prompt,
                        )
                    )
                    result = parse_impact_assessment(repaired)
                plan = result.get("model_plan") if isinstance(result.get("model_plan"), dict) else {}
                plan["model_targets"] = self.apply_modeling_policy(
                    plan.get("model_targets", []),
                    context["modeling_policy"],
                )
                result["model_plan"] = plan
                obs["result"] = result
                targets = plan.get("model_targets", [])
                to_update = [
                    target.get("type")
                    for target in targets
                    if target.get("operation") == "update" and target.get("type")
                ]
                to_create = [
                    target.get("type")
                    for target in targets
                    if target.get("operation") == "create" and target.get("type")
                ]
                consistency_summary = plan.get("consistency_summary", "")
                gaps = plan.get("gaps", [])
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
                    "modeling_phase": context["modeling_phase"],
                    "modeling_policy": context["modeling_policy"],
                    "model_plan": plan,
                }
                artifact["model_consistency_report"] = report
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"影響評估失敗: {e}"
            return obs

        if action in {"create_model", "update_model"}:
            target = params.get("target") if isinstance(params.get("target"), dict) else {}
            diagram_type = target.get("type")
            if not diagram_type:
                obs["error"] = "target.type 參數為空"
                return obs
            models = self.system_model_rows(artifact)
            operation = "create" if action == "create_model" else "update"
            target = {**target, "operation": operation}
            existing = None if operation == "create" else self.find_model_target(models, target)
            reqs = self.model_requirements(artifact)
            try:
                model_context = self.build_model_context(artifact)
                model_context["model_target"] = target
                result = self.build_model(
                    diagram_type, reqs,
                    existing_model=existing,
                    artifact_context=model_context,
                )
                new_name = str(result.get("name") or "").strip()
                result_type = str(result.get("type") or "").strip()
                if not new_name:
                    raise ValueError("model result missing name")
                if result_type != diagram_type:
                    raise ValueError(f"model result type must be {diagram_type}, got {result_type or '<empty>'}")
                new_row = {
                    "id": str((existing or {}).get("id") or target.get("target_model_id") or "").strip()
                    or self.next_model_id(models),
                    "name": new_name,
                    "type": result_type,
                }
                if result.get("plantuml"):
                    new_row["plantuml"] = result.get("plantuml", "")
                if result.get("description"):
                    new_row["description"] = result.get("description", "")
                if result.get("text"):
                    new_row["text"] = result.get("text", [])
                related_requirement_ids = self.related_req_ids(result, target)
                if related_requirement_ids:
                    new_row["related_requirement_ids"] = related_requirement_ids
                current_issue = (
                    artifact.get("current_issue")
                    if isinstance(artifact.get("current_issue"), dict)
                    else {}
                )
                source_ids = [
                    str(value).strip()
                    for source in (
                        (existing or {}).get("source_ids"),
                        result.get("source_ids"),
                        target.get("source_ids"),
                    )
                    for value in (source if isinstance(source, list) else [source])
                    if str(value or "").strip()
                ]
                source_ids.extend(
                    str(value).strip()
                    for value in (current_issue.get("meeting_id"), current_issue.get("id"))
                    if str(value or "").strip()
                )
                source_text = str(result.get("source") or "").strip()
                if source_text:
                    new_row["source"] = source_text
                    source_ids.append(source_text)
                elif source_ids:
                    new_row["source"] = source_ids[0]
                if source_ids:
                    new_row["source_ids"] = list(dict.fromkeys(source_ids))
                if existing:
                    existing.clear()
                    existing.update(new_row)
                    existing["name"] = new_name
                    target_row = existing
                else:
                    models.append(new_row)
                    artifact["system_models"] = models
                    target_row = new_row
                label = "更新" if existing else "新建"
                obs["result"] = {
                    "operation": operation,
                    "target_model_id": target_row.get("id"),
                    "type": target_row.get("type"),
                    "name": target_row.get("name"),
                    "related_requirement_ids": target_row.get("related_requirement_ids", []),
                }
                obs["summary"] = f"{diagram_type}:{target_row.get('name', '')} 已{label}"
            except Exception as e:
                obs["error"] = str(e)
                label = "建立" if operation == "create" else "更新"
                obs["summary"] = f"{diagram_type} {label}失敗: {e}"
            return obs

        if action == "write_use_case_text":
            target = params.get("target") if isinstance(params.get("target"), dict) else {}
            models = self.system_model_rows(artifact)
            use_case_diagram = self.find_model_target(models, {**target, "type": "use_case_diagram"})
            if not use_case_diagram:
                use_case_diagram = next(
                    (
                        model for model in reversed(models)
                        if isinstance(model, dict)
                        and str(model.get("type") or "").strip() == "use_case_diagram"
                    ),
                    None,
                )
            if not use_case_diagram:
                obs["error"] = "找不到 use_case_diagram"
                return obs
            reqs = self.model_requirements(artifact)
            try:
                model_context = self.build_model_context(artifact)
                model_context["model_target"] = target
                use_case_text = self.build_model(
                    "use_case_text",
                    reqs,
                    artifact_context=model_context,
                )
                use_case_diagram["text"] = use_case_text.get("text", [])
                related_requirement_ids = self.related_req_ids(use_case_diagram)
                if related_requirement_ids:
                    use_case_diagram["related_requirement_ids"] = related_requirement_ids
                obs["result"] = {
                    "target_model_id": use_case_diagram.get("id"),
                    "type": use_case_diagram.get("type"),
                    "name": use_case_diagram.get("name"),
                }
                obs["summary"] = "use_case_diagram 文字用例已更新"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"use_case_diagram 文字用例更新失敗: {e}"
            return obs

        if action == "validate_model":
            target_info = params.get("target") if isinstance(params.get("target"), dict) else {}
            diagram_type = target_info.get("type")
            previous_action = str((last_observation or {}).get("action") or "").strip()
            previous_result = (
                last_observation.get("result")
                if isinstance(last_observation, dict) and isinstance(last_observation.get("result"), dict)
                else {}
            )
            if previous_action in {"create_model", "update_model"}:
                if last_observation.get("error"):
                    obs["result"] = {"valid": False, "skipped": True}
                    obs["summary"] = f"{diagram_type}: 前一步模型建立或更新失敗，跳過驗證"
                    return obs
                if previous_result.get("target_model_id"):
                    target_info = {
                        **target_info,
                        "target_model_id": previous_result.get("target_model_id"),
                    }
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
                obs["result"] = {
                    "valid": True,
                    "target_model_id": target.get("id"),
                    "type": target.get("type"),
                    "name": target.get("name"),
                }
                obs["summary"] = f"{diagram_type} 驗證通過"
            else:
                fixed = self.repair_plantuml(target, result)
                if fixed:
                    target["plantuml"] = fixed
                    retry_result = self.execute_tool(
                        "plantuml_validate",
                        {"plantuml_code": fixed},
                        active_skill="UML",
                    )
                    if "通過" in retry_result:
                        obs["result"] = {
                            "valid": True,
                            "repaired": True,
                            "target_model_id": target.get("id"),
                            "type": target.get("type"),
                            "name": target.get("name"),
                        }
                        obs["summary"] = f"{diagram_type} 驗證失敗後已修正並通過"
                    else:
                        obs["result"] = {
                            "valid": False,
                            "repaired": True,
                            "error": retry_result,
                            "target_model_id": target.get("id"),
                            "type": target.get("type"),
                            "name": target.get("name"),
                        }
                        obs["error"] = "plantuml_validation_failed"
                        obs["summary"] = f"{diagram_type} 修正後仍驗證失敗"
                else:
                    obs["result"] = {
                        "valid": False,
                        "error": result,
                        "target_model_id": target.get("id"),
                        "type": target.get("type"),
                        "name": target.get("name"),
                    }
                    obs["error"] = "plantuml_validation_failed"
                obs["summary"] = f"{diagram_type} 驗證失敗"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    @staticmethod
    # Defines apply modeling policy function for this module workflow.
    def apply_modeling_policy(
        targets: Any,
        policy: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        if not isinstance(targets, list):
            return []
        allowed_types = set(policy.get("allowed_types") or [])
        try:
            max_targets = int(policy.get("max_targets") or len(targets))
        except (TypeError, ValueError):
            max_targets = len(targets)
        max_targets = max(0, min(max_targets, len(targets)))
        filtered: list[Dict[str, Any]] = []
        for target in targets:
            if not isinstance(target, dict):
                continue
            if allowed_types and target.get("type") not in allowed_types:
                continue
            filtered.append(target)
            if len(filtered) >= max_targets:
                break
        return filtered


    @staticmethod
    # Defines next model id function for this module workflow.
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
    # Defines find model target function for this module workflow.
    def find_model_target(
        models: list[Dict[str, Any]],
        target: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        target_id = str(target.get("target_model_id") or target.get("id") or "").strip()
        if target_id:
            for model in models or []:
                if isinstance(model, dict) and str(model.get("id") or "").strip() == target_id:
                    return model
        target_type = str(target.get("type") or "").strip()
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
    # Defines model name function for this module workflow.
    def model_name(model_type: str) -> str:
        zh_names = {
            "context_diagram": "情境圖",
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
    # Defines model source function for this module workflow.
    def model_source(revision_context: Optional[Dict[str, Any]] = None) -> str:
        if isinstance(revision_context, dict):
            meeting_ids = [
                str(value).strip()
                for value in (revision_context.get("meeting_ids") or [])
                if str(value).strip()
            ]
            if meeting_ids:
                return ",".join(dict.fromkeys(meeting_ids))
        return ""

    @staticmethod
    # Defines system model rows function for this module workflow.
    def system_model_rows(artifact: Any) -> list[Dict[str, Any]]:
        if not isinstance(artifact, dict):
            return []
        models = artifact.get("system_models", [])
        if not isinstance(models, list):
            return []
        return [row for row in models if isinstance(row, dict)]

    @staticmethod
    # Defines model user requirements function for this module workflow.
    def model_user_requirements(artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        source_rows = artifact.get("URL") or []
        return [
            {"id": r.get("id"), "text": r.get("text", "")}
            for r in source_rows
            if isinstance(r, dict) and str(r.get("text") or "").strip()
        ]

    @staticmethod
    # Defines model spec requirements function for this module workflow.
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

    # Defines model requirements function for this module workflow.
    def model_requirements(self, artifact: Dict[str, Any]) -> list[Dict[str, Any]]:
        spec_rows = self.model_spec_requirements(artifact)
        return spec_rows or self.model_user_requirements(artifact)

    # Defines model requirement source function for this module workflow.
    def model_requirement_source(self, artifact: Dict[str, Any]) -> str:
        return "REQ" if self.model_spec_requirements(artifact) else "URL"

    @staticmethod
    # Defines related req ids function for this module workflow.
    def related_req_ids(
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
    # Defines model stakeholders function for this module workflow.
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
    # Defines model feedback function for this module workflow.
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

    # Defines build model context function for this module workflow.
    def build_model_context(
        self,
        artifact: Dict[str, Any],
        *,
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "modeling_phase": self.modeling_phase(artifact),
            "modeling_policy": modeling_phase_policy(self.modeling_phase(artifact)),
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

    # Defines generate system models function for this module workflow.
    def generate_system_models(
        self,
        artifact: Dict[str, Any],
        revision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        model_artifact = self.build_model_context(
            artifact,
            revision_context=revision_context,
        )
        model_artifact["modeling_phase"] = "initial_system_model"
        model_artifact["modeling_policy"] = modeling_phase_policy("initial_system_model")
        self.record_runtime_checkpoint(
            stage_id="system_model",
            step_id="system_model.ensure_context_diagram",
            action="ensure_context_diagram",
        )
        self.ensure_context_diagram(model_artifact)
        artifact["system_models"] = self.parse_model_output(
            model_artifact.get("system_models", []),
            source=model_artifact.get("model_source", ""),
        )
        store = getattr(self, "runtime_store", None)
        if store:
            store.save_artifact(artifact)
        self.run_model_loop(model_artifact, modeling_phase="initial_system_model")
        model_data = self.parse_model_output(
            model_artifact.get("system_models", []),
            source=model_artifact.get("model_source", ""),
        )
        artifact["system_models"] = model_data
        if store:
            store.save_artifact(artifact)
        self.record_runtime_checkpoint(
            stage_id="system_model",
            step_id="system_model.ensure_use_case",
            action="ensure_use_case",
        )
        self.ensure_use_case(model_data, model_artifact)
        artifact["system_models"] = model_data
        if store:
            store.save_artifact(artifact)
        return model_data

    # Defines ensure context diagram function for this module workflow.
    def ensure_context_diagram(self, artifact_context: Dict[str, Any]) -> None:
        models = self.system_model_rows(artifact_context)
        has_context = any(
            model.get("type") == "context_diagram" and model.get("plantuml")
            for model in models
        )
        if has_context:
            return

        reqs = self.model_requirements(artifact_context)
        if not reqs:
            return

        context = dict(artifact_context)
        context["model_target"] = {
            "operation": "create",
            "type": "context_diagram",
            "name": "系統情境圖" if current_output_language() != "en" else "System Context Diagram",
            "reason": "建立初始系統情境，釐清系統邊界、外部角色與主要互動。",
            "value_reason": "SRS 需要穩定的系統情境作為後續模型與需求追蹤的邊界基準。",
        }
        result = self.build_model(
            "context_diagram",
            reqs,
            artifact_context=context,
        )
        new_row = {
            "id": self.next_model_id(models),
            "name": str(result.get("name") or context["model_target"]["name"]).strip(),
            "type": "context_diagram",
        }
        if result.get("plantuml"):
            new_row["plantuml"] = result.get("plantuml", "")
        if result.get("description"):
            new_row["description"] = result.get("description", "")
        related_requirement_ids = self.related_req_ids(result, context["model_target"])
        if related_requirement_ids:
            new_row["related_requirement_ids"] = related_requirement_ids
        source_text = str(result.get("source") or artifact_context.get("model_source") or "").strip()
        if source_text:
            new_row["source"] = source_text
        models.append(new_row)
        artifact_context["system_models"] = models

    # Defines ensure use case function for this module workflow.
    def ensure_use_case(
        self,
        model_data: list[Dict[str, Any]],
        artifact_context: Dict[str, Any],
    ) -> None:
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
        result = self.build_model(
            "use_case_text",
            self.model_requirements(context),
            artifact_context=context,
        )
        use_case_text = result.get("text", []) if isinstance(result, dict) else []
        if not use_case_text:
            raise RuntimeError("use_case_diagram 已生成，但 use_case_text 生成失敗")
        use_case_diagram["text"] = use_case_text

    # Defines build model function for this module workflow.
    def build_model(
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
        diagram_layout_hint = model_layout_hint(diagram_type)
        description_rule, description_field = model_description_contract(diagram_type)

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
            task = use_case_text(
                req_text=req_text,
                use_case_diagram_text=use_case_diagram_text,
                context_text=context_text,
            )
            skill = uml_skill_subset(get_skill("UML"), "use_case_text")
            messages = self.build_skill_messages(skill, "UML", task)
            result = self.chat_json(messages)
            return parse_use_case(result)

        if existing_model and existing_model.get("plantuml"):
            task = update_model(
                type_name=type_name,
                existing_plantuml=existing_model["plantuml"],
                req_text=req_text,
                context_text=context_text,
                diagram_layout_hint=diagram_layout_hint,
                diagram_type=diagram_type,
                description_rule=description_rule,
                description_field=description_field,
            )
        else:
            task = create_model(
                type_name=type_name,
                req_text=req_text,
                context_text=context_text,
                diagram_layout_hint=diagram_layout_hint,
                diagram_type=diagram_type,
                description_rule=description_rule,
                description_field=description_field,
            )

        skill = uml_skill_subset(get_skill("UML"), "diagram", diagram_type)
        messages = self.build_skill_messages(skill, "UML", task)
        result = self.chat_json(messages)
        return parse_diagram_model(result, expected_type=diagram_type)

    # Defines parse model output function for this module workflow.
    def parse_model_output(self, result, *, source: str = "") -> list[Dict[str, Any]]:
        try:
            return parse_model_list(result, source=source)
        except ValueError as exc:
            repair_prompt = render_repair_prompt(
                "model_output_repair",
                raw=json.dumps(result, ensure_ascii=False, indent=2)
                if isinstance(result, (dict, list))
                else str(result),
                error_msg=str(exc),
            )
            repaired = self.chat_json(
                self.build_skill_messages(
                    uml_skill_subset(get_skill("UML"), "diagram"),
                    "UML",
                    repair_prompt,
                )
            )
            return parse_model_list(repaired, source=source)

    # Defines validate plantuml models function for this module workflow.
    def validate_plantuml_models(self, model_data: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        validator = self.tools.get("plantuml_validate")
        if not validator:
            return model_data

        models = model_data if isinstance(model_data, list) else []
        if not models:
            return model_data

        validation_results = {}

        # Defines validate one function for this module workflow.
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

        for i in range(len(models)):
            m, result = validation_results.get(i, (models[i], None))
            if result is None:
                continue
            if "通過" in result:
                m["plantuml_validation_status"] = "passed"
                m.pop("plantuml_validation_error", None)
                continue
            self.logger.warning(f"  {m.get('name', '')} 語法修正中")
            fixed = self.repair_plantuml(m, result)
            if fixed:
                m["plantuml"] = fixed
                retry_result = self.execute_tool(
                    "plantuml_validate",
                    {"plantuml_code": fixed},
                    active_skill="UML",
                )
                m["plantuml_repaired"] = True
                if "通過" in retry_result:
                    m["plantuml_validation_status"] = "repaired"
                    m.pop("plantuml_validation_error", None)
                else:
                    m["plantuml_validation_status"] = "failed_after_repair"
                    m["plantuml_validation_error"] = retry_result
                    self.logger.warning(f"  {m.get('name', '')} 修正後仍驗證失敗")
            else:
                m["plantuml_validation_status"] = "failed"
                m["plantuml_validation_error"] = result

        return model_data

    # Defines repair plantuml function for this module workflow.
    def repair_plantuml(self, model: Dict, error_msg: str) -> Optional[str]:
        user_prompt = render_repair_prompt(
            'modeler_plantuml_repair',
            model=model,
            error_msg=error_msg,
        )

        try:
            skill = uml_skill_subset(get_skill("UML"), "repair", model.get("type", ""))
            messages = self.build_skill_messages(skill, "UML", user_prompt)
            response = self.chat_json(messages)
            return parse_plantuml_fix(response)["plantuml"]
        except Exception as e:
            self.logger.warning(f"  修正失敗: {e}")
        return None
