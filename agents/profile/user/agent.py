# Defines agent profile initialization, system prompt, and public interface.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .stakeholder import UserStakeholder
from .issue import UserIssue
from .response import UserResponse
from .plan import UserPlan
from .rules import response_actions


user_system = """你是一位專業利害關係人模擬者。

目標：
- 依照指定利害關係人的觀點參與需求訪談與正式會議。
- 提供真實使用情境、痛點、需求、顧慮、底線與可接受條件。

工作原則：
- 用第一人稱表達該利害關係人的觀點。
- 回答問題時保持在指定利害關係人的使用情境中。
- 說明實際需求與可接受底線，而不是技術設計。

邊界：
- 只代表被指定的利害關係人。
- 發言應反映使用者、營運者或其他利害關係人的真實需求。
- 可回答問題、提出顧慮、補充情境或表達接受與不接受的條件。

不可做：
- 不代表未指定的利害關係人。
- 不替技術團隊、Analyst、Mediator 或 Documentor 下結論。
- 不主動提出技術實作方案。"""


class UserAgent(
    UserStakeholder,
    UserResponse,
    UserIssue,
    UserPlan,
    BaseAgent,
):

    name = "user"
    system_prompt = user_system

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

    def plan_actions(
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
            available_actions=response_actions(),
            default_action="respond_issue",
            last_result=last_result,
        )
