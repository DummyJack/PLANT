# Plans the next action for the agent.
from typing import Any, Dict, Optional


ANALYST_AVAILABLE_ACTIONS = {
    "answer_question": "使用時機：有人在 open_questions 中指定 analyst 回答。不要使用：一般議題發言或資料更新。寫回或影響：只回答問題，不更新專案資料。",
    "respond_issue": "使用時機：只需要根據議題、前文與現有資料表達分析意見。不要使用：需要抽取需求、更新 scope、正式化 REQ-* 需求條目或處理衝突時。寫回或影響：只產生會議發言，不更新需求、scope 或衝突報告。",
    "refine_scope": "使用時機：議題明確討論系統邊界、in scope / out of scope、外部系統或第三方責任。不要使用：只是在補需求文字或處理衝突解法。寫回或影響：更新 scope.json。",
    "update_requirement": "使用時機：預設需求正式化會議，需要把全部 User Requirements 整理成 REQ-* 需求條目。不要使用：一般議題只修正少數既有 REQ。寫回或影響：重整並更新 REQ-* 需求條目，包含類型、驗收條件、相依性、風險、假設與來源追蹤。",
    "refine_requirement": "使用時機：一般正式會議已針對既有 REQ 收斂，需要依討論結果修正受影響的 REQ 欄位。不要使用：把全部 URL 重新正式化，或 stakeholder 剛提出尚未整理的新需求。寫回或影響：只更新本議題影響到的 REQ-*。",
    "discuss_conflict": "使用時機：針對既有衝突報告的解決選項與建議解法做採用、調整或人類裁決取捨。不要使用：有新需求需重新跑衝突辨識。寫回或影響：只形成會議發言與提案，不直接重跑衝突辨識。",
}
ANALYST_NEW_REQUIREMENT_ACTION = {
    "analyze_requirements": "使用時機：new_requirement 議題中，stakeholder 以自然語言提出、補充或改寫需求。不要使用：只是整理既有 User Requirements、修正既有 REQ、補驗收條件或討論既有衝突報告。寫回或影響：抽取需求候選或需求變更候選，並更新對應 User Requirement 來源。",
}


def analyst_available_actions_for_issue(observation: Dict[str, Any]) -> Dict[str, str]:
    actions = dict(ANALYST_AVAILABLE_ACTIONS)
    issue = observation.get("issue") if isinstance(observation.get("issue"), dict) else {}
    issue_focus = str(issue.get("issue_focus") or observation.get("issue_focus") or "").strip()
    category = str(issue.get("category") or observation.get("issue_category") or "").strip()
    if issue_focus == "new_requirement" or category == "new_requirement":
        actions.update(ANALYST_NEW_REQUIREMENT_ACTION)
    return actions


# Defines AnalystPlan class for this module workflow.
class AnalystPlan:
    def plan_actions(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.issue_response_decision(
            observation,
            done_reasoning="上一輪需求分析師回應已符合格式契約，結束本次回應。",
            active_reasoning="根據議題類型選擇需求分析師回應策略。",
            available_actions=analyst_available_actions_for_issue(observation),
            default_action="respond_issue",
            last_result=last_result,
        )
