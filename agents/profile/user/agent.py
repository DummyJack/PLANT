# User agent: stakeholder voice, elicitation support, and issue response.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .stakeholder import UserStakeholder
from .issues import UserIssues


class UserAgent(
    UserStakeholder,
    UserIssues,
    BaseAgent,
):
    """利害關係人模擬 Agent — 從不同角度提出需求和期望"""

    name = "user"
    system_prompt = """你負責模擬不同利害關係人的角色。

規則：
1. 以第一人稱代入角色，用真實會議口吻表達。
2. 只代表被指派角色的需求、顧慮與底線，不代替技術團隊或主持人下結論。
3. 優先講情境、痛點、需求與可接受底線，不講技術解法。"""

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
        return {
            "action": "respond_as_stakeholder",
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
        response = self.chat_for_issue_response(messages, temperature=1)

        text = response.get("text", "")
        issue_id = str(issue.get("id") or "")
        open_questions = (
            [] if issue_id.startswith("ELICIT-") else response.get("open_questions", [])
        )
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
        if self.stakeholders:
            if len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []
        if need_speaking_as:
            raw = response.get("speaking_as")
            if isinstance(raw, str):
                raw = [raw]
            valid_names = {sh.get("name", "") for sh in self.stakeholders}
            speaking_as = [n for n in (raw or []) if n and n in valid_names]
            if not speaking_as:
                return {
                    "action": decision.get("action", ""),
                    "status": "failed",
                    "error": "missing_valid_speaking_as",
                    "format_error": (
                        "multi-stakeholder user issue_response must include "
                        "speaking_as with at least one valid stakeholder name"
                    ),
                    "summary": "user issue_response 缺少合法 speaking_as",
                }
        elif len(speaking_as_list) == 1:
            speaking_as = [speaking_as_list[0].get("name", "")]

        return {
            "action": decision.get("action", ""),
            "status": "success",
            "text": text,
            "open_questions": open_questions,
            "speaking_as": speaking_as,
            "summary": "完成 user issue_response",
        }
