# Handles agent responses during meetings.
import json
from typing import Any, Dict, List, Optional

from .feedback import research_source
from .plan import external_research_required


# Defines ExpertResponse class for this module workflow.
class ExpertResponse:
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
        if not isinstance(last_result, dict) or last_result.get("error"):
            issue = observation.get("issue") if isinstance(observation.get("issue"), dict) else {}
            full_issue = kwargs.get("issue") if isinstance(kwargs.get("issue"), dict) else {}
            contract = (
                full_issue.get("conflict_review_contract")
                if isinstance(full_issue.get("conflict_review_contract"), dict)
                else {}
            )
            if str(contract.get("type") or "").strip() == "pair_reviews":
                return self.issue_response_decision(
                    observation,
                    done_reasoning="上一輪領域專家回應已符合格式契約，結束本次回應。",
                    active_reasoning="pair-review 只根據 pair 原文、current_label 與會議脈絡判斷，不執行領域研究或工具查詢。",
                    available_actions={
                        "respond_issue": "使用時機：根據 pair 原文與目前討論輸出衝突再審查意見。不要使用：文件查詢、外部研究或 feedback 更新。寫回或影響：只產生 pair_reviews 發言，不更新 feedback。",
                    },
                    default_action="respond_issue",
                    last_result=last_result,
                )
            if issue.get("id") != "OQ" and external_research_required({"issue": issue}):
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": "議題涉及外部法規、合規、安全、支付、隱私或第三方限制，先執行領域研究。",
                    "action_plan": {
                        "goal": "用 URL-backed feedback 支撐 Expert 會議發言",
                        "steps": [
                            {
                                "id": "research_domain",
                                "action": "research_domain",
                                "params": {},
                                "reasoning": "外部限制訊號需要先取得或更新 feedback，再產生會議發言。",
                            }
                        ],
                    },
                }
        return self.issue_response_decision(
            observation,
            done_reasoning="上一輪領域專家回應已符合格式契約，結束本次回應。",
            active_reasoning="根據議題類型選擇對應的單輪專家回應策略。",
            available_actions={
                "answer_question": "使用時機：有人在 open_questions 中指定 expert 回答。不要使用：一般議題發言或領域研究。寫回或影響：只回答問題，不更新專案資料。",
                "respond_issue": "使用時機：只需要根據 issue、前文與現有資料表達領域意見。不要使用：需要專案文件證據、外部法規/標準、第三方限制或 feedback 更新時。寫回或影響：只產生會議發言，不更新 feedback。",
                "research_domain": "流程 action。使用時機：議題需要文件證據、外部知識、法規/標準、第三方限制、合規、安全或隱私風險判斷。不要使用：一般功能偏好、純需求語意討論或現有資料已足夠。寫回或影響：內部依需要執行 read_reference_docs、research_issue、update_feedback；正式產物只寫回 feedback，不直接定案需求。",
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
        issue = kwargs["issue"]
        action = str(decision.get("action") or "").strip()
        artifact = kwargs.get("artifact")
        expert_action_result: Optional[Dict[str, Any]] = None
        if action == "answer_question":
            expert_action_result = {
                "action": action,
                "summary": "回答 open question，不更新專案資料。",
            }
        elif action == "respond_issue":
            expert_action_result = {
                "action": action,
                "summary": "只產生會議回答，不更新專案資料。",
            }
        elif action == "research_domain":
            if not isinstance(artifact, dict):
                return {
                    "action": action,
                    "status": "failed",
                    "error": "missing_artifact",
                    "format_error": "research_domain requires artifact context",
                    "summary": "expert research_domain 缺少 artifact，無法執行領域研究流程",
                }
            self.apply_research_context(
                artifact,
                issue=issue,
                previous_responses=kwargs.get("previous_responses"),
            )
            loop_result = self.run_research_loop(artifact)
            trace = loop_result.get("opa_trace") if isinstance(loop_result, dict) else []
            source_ref = research_source(artifact)
            expert_action_result = {
                "action": action,
                "steps": [
                    str((row.get("decision") or {}).get("action") or "").strip()
                    for row in (trace or [])
                    if isinstance(row, dict) and str((row.get("decision") or {}).get("action") or "").strip()
                ],
                "feedback": self.feedback_for_source(
                    artifact.get("feedback", {}),
                    source_ref,
                ),
            }
        return expert_action_result or {"action": action, "summary": f"完成 expert action: {action}"}

    @staticmethod
    # Defines apply research context function for this module workflow.
    def apply_research_context(
        artifact: Dict[str, Any],
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        parts = [
            f"正式會議議題：{issue.get('title', '')}",
            f"類型：{issue.get('category', '')}",
        ]
        description = str(issue.get("description") or "").strip()
        if description:
            parts.append(f"描述：{description}")
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        artifact_ids = trace.get("artifact_ids") or []
        if artifact_ids:
            parts.append(f"來源需求/資料 id：{json.dumps(artifact_ids, ensure_ascii=False)}")
        if previous_responses:
            summaries = []
            for row in previous_responses:
                if not isinstance(row, dict):
                    continue
                response = row.get("response") if isinstance(row.get("response"), dict) else {}
                text = str(response.get("text") or "").strip()
                if text:
                    summaries.append(f"{row.get('agent', '?')}: {text}")
            if summaries:
                parts.append("前面發言重點：" + " / ".join(summaries))
        artifact["current_issue"] = {
            "id": issue.get("id"),
            "meeting_id": issue.get("meeting_id"),
            "title": issue.get("title"),
            "category": issue.get("category"),
            "description": issue.get("description", ""),
            "trace": trace,
            "discussion_context": "；".join(part for part in parts if part),
        }

    @staticmethod
    # Defines feedback for source function for this module workflow.
    def feedback_for_source(feedback: Any, source_ref: str) -> Dict[str, Any]:
        if not isinstance(feedback, dict) or not str(source_ref or "").strip():
            return {}
        source_ref = str(source_ref).strip()
        out: Dict[str, Any] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows = []
            for row in (feedback.get(section) or []):
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source") or "").strip()
                if source == source_ref:
                    rows.append(dict(row))
            if rows:
                out[section] = rows
        return out
