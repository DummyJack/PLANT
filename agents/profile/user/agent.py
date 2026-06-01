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
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪利害關係人回應已完成，結束本次回應。",
            }
        issue = observation.get("issue") or {}
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        user_expected = expected_actions.get("user")
        if isinstance(user_expected, str):
            user_expected = [user_expected]
        if (
            str(issue.get("id") or "").strip() == "OQ"
            or "answer_question" in [str(action).strip() for action in (user_expected or [])]
        ):
            return {
                "action": "answer_question",
                "params": {},
                "reasoning": "以議題規劃指定的利害關係人身份回答 open question。",
            }
        return {
            "action": "respond_issue",
            "params": {},
            "reasoning": "以利害關係人視角回應議題。",
        }

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
        response = self.chat_for_issue_response(
            messages,
            temperature=1,
            include_stance=issue_id != "OQ",
        )

        text = response.get("text", "")
        open_questions = (
            [] if issue_id.startswith("ELICIT-") else response.get("open_questions", [])
        )
        stance = response.get("stance") if issue_id != "OQ" else {}
        if issue_id != "OQ":
            default_state = "ready_to_close"
            if open_questions:
                default_state = "needs_more_discussion"
            if not isinstance(stance, dict) or not str((stance or {}).get("state") or "").strip():
                stance = {"state": default_state}
        if response.get("error") or not str(text or "").strip():
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
