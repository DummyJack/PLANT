# Handles agent responses during meetings.
from typing import Any, Dict, Optional


# Defines ModelerResponse class for this module workflow.
class ModelerResponse:
    # Defines obs response function for this module workflow.
    def obs_response(self, **kwargs: Any) -> Dict[str, Any]:
        return self.issue_response_observation(**kwargs)

    # Defines plan actions function for this module workflow.
    def plan_actions(
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
                "system_modeling": "流程 action。使用時機：議題涉及系統邊界、actor/use case、流程、資料、狀態、互動順序、責任分工或模型追蹤性，且建立/更新 UML/system model 能讓討論更清楚或檢查一致性。不要使用：只是需求文字、業務偏好或衝突取捨，且沒有流程、資料、狀態、角色互動、責任邊界或視覺化價值。寫回或影響：內部只規劃一次 plan_models，之後依 plan 逐一執行 create_model/update_model、必要時 write_use_case_text，並由 validate_model 驗證；驗證失敗時由 validate_model 內部修復一次。正式產物只更新 system_models，不從模型反推需求。",
            },
            default_action="respond_issue",
            last_result=last_result,
        )

    # Defines execute action function for this module workflow.
    def execute_action(
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
                "summary": "回答 open question，不更新專案資料。",
            }
        elif action == "respond_issue":
            model_action_result = {
                "action": action,
                "summary": "只產生會議回答，不更新專案資料。",
            }
        elif action == "system_modeling":
            if not isinstance(artifact, dict):
                return {
                    "action": action,
                    "status": "failed",
                    "error": "missing_artifact",
                    "format_error": "system_modeling requires artifact context",
                    "summary": "modeler system_modeling 缺少 artifact，無法執行建模流程",
                }
            logger = getattr(self, "logger", None)
            if logger is not None:
                logger.info("=== Modeler: 系統模型 ===")
            loop_result = self.run_model_loop(
                artifact,
                recent_discussions=kwargs.get("previous_responses"),
                issue=kwargs.get("issue"),
                modeling_phase="align_model_issue",
            )
            trace = loop_result.get("opa_trace") if isinstance(loop_result, dict) else []
            model_changes = []
            for row in trace or []:
                if not isinstance(row, dict):
                    continue
                decision_action = str((row.get("decision") or {}).get("action") or "").strip()
                if decision_action not in {"create_model", "update_model"}:
                    continue
                result = row.get("result") if isinstance(row.get("result"), dict) else {}
                model_id = str(result.get("target_model_id") or "").strip()
                if not model_id:
                    continue
                operation = str(result.get("operation") or "").strip()
                if operation not in {"create", "update"}:
                    operation = "create" if decision_action == "create_model" else "update"
                model_changes.append(
                    {
                        "operation": operation,
                        "id": model_id,
                        "type": str(result.get("type") or "").strip(),
                        "name": str(result.get("name") or "").strip(),
                        "related_requirement_ids": result.get("related_requirement_ids") or [],
                    }
                )
            if logger is not None:
                if model_changes:
                    labels = [
                        str(change.get("name") or change.get("id") or "").strip()
                        for change in model_changes
                        if str(change.get("name") or change.get("id") or "").strip()
                    ]
                    logger.info(
                        "Modeler: 系統模型已更新%s",
                        f"：{'、'.join(labels)}" if labels else "",
                    )
                else:
                    logger.info("Modeler: 系統模型無需新增或更新")
            model_action_result = {
                "action": action,
                "steps": [
                    str((row.get("decision") or {}).get("action") or "").strip()
                    for row in (trace or [])
                    if isinstance(row, dict) and str((row.get("decision") or {}).get("action") or "").strip()
                ],
                "model_changes": model_changes,
                "system_models": artifact.get("system_models", []),
                "model_consistency_report": artifact.get("model_consistency_report", {}),
            }
        return model_action_result or {"action": action, "summary": f"完成 modeler action: {action}"}
