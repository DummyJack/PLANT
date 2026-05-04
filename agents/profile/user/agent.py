# User agent: stakeholder voice, elicitation support, and topic response.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .stakeholder import UserStakeholder
from .topics import UserTopics


class UserAgent(
    UserStakeholder,
    UserTopics,
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

    def build_topic_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        payload = self.build_topic_response_observation_payload(**kwargs)
        payload["stakeholder_count"] = len(self.stakeholders or [])
        return payload

    def decide_topic_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "action": "respond_as_stakeholder",
            "params": {},
            "reasoning": "以利害關係人視角回應議題。",
        }

    def execute_topic_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        topic = kwargs["topic"]
        user_prompt = self.build_topic_response_prompt(
            topic=topic,
            previous_responses=kwargs.get("previous_responses"),
            artifact_snapshot=kwargs.get("artifact_snapshot"),
        )
        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages, temperature=1)

        statement = response.get("statement", "")
        open_questions = response.get("open_questions", [])

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
            if not speaking_as and self.stakeholders:
                speaking_as = [self.stakeholders[0].get("name", "")]
        elif len(speaking_as_list) == 1:
            speaking_as = [speaking_as_list[0].get("name", "")]

        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": statement,
            "open_questions": open_questions,
            "speaking_as": speaking_as,
            "summary": "完成 user topic_response",
        }
