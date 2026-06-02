# User agent: stakeholder voice, elicitation support, and issue response.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .stakeholder import UserStakeholder
from .issues import UserIssues
from .prompts import USER_SYSTEM_PROMPT


class UserAgent(
    UserStakeholder,
    UserIssues,
    BaseAgent,
):
    """利害關係人模擬 Agent — 從不同角度提出需求和期望"""

    name = "user"
    system_prompt = USER_SYSTEM_PROMPT

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model, tools=tools, registry=registry, project_config=project_config
        )
        self.stakeholders: List[Dict] = []

    def build_issue_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        observation = self.issue_response_observation(**kwargs)
        observation["stakeholder_count"] = len(self.stakeholders or [])
        return observation

    def decide_issue_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.issue_response_decision(
            observation,
            done_reasoning="上一輪利害關係人回應已完成，結束本次回應。",
            active_reasoning="根據議題類型與 open question 指派，選擇利害關係人回應策略。",
            available_actions={
                "answer_question": "使用時機：議題是 OQ（待回答 open question）或 expected_actions 指定 user 回答特定問題。不要使用：一般議題發言。寫回或影響：只回覆問題文字，補 `reply_to_question`、`reply_to_agent` 與 `speaking_as`，不主動更新需求。",
                "respond_issue": "使用時機：在一般正式會議中代表被指定或最相關利害關係人給出立場、顧慮、底線與可接受條件。不要使用：回答 open question。寫回或影響：只回應發言內容，不直接更新需求。",
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
        issue = kwargs["issue"]
        user_prompt = self.build_issue_response_prompt(
            issue=issue,
            previous_responses=kwargs.get("previous_responses"),
            artifact_context=(kwargs.get("observation") or {}).get("artifact_context"),
        )
        messages = self.build_direct_messages(user_prompt)
        issue_id = str(issue.get("id") or "")
        contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
        is_pair_review = str(contract.get("type") or "").strip() == "pair_reviews"
        include_stance = issue_id != "OQ" and not is_pair_review
        response = self.chat_for_issue_response(
            messages,
            temperature=1,
            include_stance=include_stance,
            allow_pair_reviews=is_pair_review,
        )
        if response.get("format_error"):
            output_contract = (
                '{\n  "text": "自然語言發言",\n  "open_questions": [],\n  "stance": {"state": "ready_to_close"}\n}'
                if include_stance
                else '{\n  "text": "自然語言回答",\n  "open_questions": []\n}'
            )
            stance_rule = (
                "- stance.state 必須輸出，且只能是 ready_to_close 或 needs_more_discussion。\n"
                if include_stance
                else ""
            )
            retry_prompt = (
                "# 任務\n"
                "上一個利害關係人回應格式不合格。請只修正輸出格式與必要欄位，重新產生自然語言回應。\n\n"
                "# 限制\n"
                "- text 必須是自然語言，不要輸出 action 結果 JSON。\n"
                f"{stance_rule}"
                "- open_questions 沒有就輸出空陣列。\n\n"
                "# 原始議題提示\n"
                f"{user_prompt}\n\n"
                "# 上次錯誤\n"
                f"{response.get('format_error')}\n\n"
                "# 輸出 JSON\n"
                f"{output_contract}"
            )
            response = self.chat_for_issue_response(
                self.build_direct_messages(retry_prompt),
                temperature=1,
                include_stance=include_stance,
                allow_pair_reviews=is_pair_review,
            )

        text = response.get("text", "")
        open_questions = (
            [] if issue_id.startswith("ELICIT-") else response.get("open_questions", [])
        )
        stance = response.get("stance") if include_stance else {}
        if response.get("error") or response.get("format_error") or not str(text or "").strip():
            return {
                "action": decision.get("action", ""),
                "status": "failed",
                "error": response.get("error") or "missing_text",
                "format_error": response.get("format_error") or "issue response must include text",
                "summary": "user issue_response 格式不合格",
            }

        speaking_as = []
        need_speaking_as = len(self.stakeholders) > 1
        speaking_as_list = []
        target_stakeholders = [
            str(name).strip()
            for name in (issue.get("target_stakeholders") or [])
            if str(name).strip()
        ]
        target_set = set(target_stakeholders)
        if self.stakeholders:
            if target_set:
                speaking_as_list = [
                    sh for sh in self.stakeholders
                    if str(sh.get("name") or "").strip() in target_set
                ]
            elif len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []
        if need_speaking_as:
            raw = response.get("speaking_as")
            if isinstance(raw, str):
                raw = [raw]
            valid_names = {sh.get("name", "") for sh in self.stakeholders}
            speaking_as = [n for n in (raw or []) if n and n in valid_names]
            if target_set:
                speaking_as = [name for name in speaking_as if name in target_set]
            if not speaking_as and target_stakeholders:
                speaking_as = [
                    name for name in target_stakeholders if name in valid_names
                ]
            if not speaking_as:
                if issue_id == "OQ":
                    speaking_as = list(target_set) if target_set else [
                        str(sh.get("name", "")).strip()
                        for sh in self.stakeholders
                        if str(sh.get("name", "")).strip()
                    ]
                else:
                    return {
                        "action": decision.get("action", ""),
                        "status": "failed",
                        "error": "missing_valid_speaking_as",
                        "format_error": (
                            "user issue_response must include speaking_as with at least "
                            "one valid assigned stakeholder name"
                        ),
                        "summary": "user issue_response 缺少合法 speaking_as",
                    }
        elif len(speaking_as_list) == 1:
            speaking_as = [speaking_as_list[0].get("name", "")]
        if len(speaking_as) > 1:
            labeled_parts = []
            labeled_by_name = {}
            for name in speaking_as:
                marker = f"【{name}】"
                start = str(text).find(marker)
                if start < 0:
                    continue
                next_positions = [
                    pos
                    for other in speaking_as
                    if other != name
                    for pos in [str(text).find(f"【{other}】", start + len(marker))]
                    if pos >= 0
                ]
                end = min(next_positions) if next_positions else len(str(text))
                part = str(text)[start + len(marker):end].strip()
                labeled_parts.append(part)
                labeled_by_name[name] = part
            if len(labeled_parts) < len(speaking_as):
                labeled_names = [
                    name for name in speaking_as
                    if str(labeled_by_name.get(name) or "").strip()
                ]
                speaking_as = labeled_names or speaking_as[:1]
        return {
            "actions": [decision.get("action", "")] if decision.get("action") else [],
            "status": "success",
            "text": text,
            "open_questions": open_questions,
            "stance": stance,
            "speaking_as": speaking_as,
            "summary": "完成 user issue_response",
        }
