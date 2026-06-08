# Defines agent profile initialization, system prompt, and public interface.
from pathlib import Path
from typing import Optional

from agents.base import BaseAgent

from .feedback import ExpertDomainResearch
from .issues import ExpertIssues
from .response import ExpertResponse
from .rules import (
    skill_usage_policy as expert_skill_usage_policy,
    tool_usage_policy as expert_tool_usage_policy,
)

expert_system = """你是一位專業領域研究員。

目標：
- 補充外部法規、標準、產業限制、安全、隱私、稽核與領域風險資訊。
- 協助判斷需求是否受到外部限制、風險或證據缺口影響。

工作原則：
- 區分強制義務、最佳實務、風險提醒與待查證缺口。
- 證據不足時必須明確指出不確定性。
- 說明外部限制如何影響需求、驗收、風險與系統邊界。

邊界：
- 可提供 feedback、constraint、risk、evidence gap 或研究依據。
- 外部研究結果只作為需求判斷依據，不直接成為正式需求。
- 涉及需求措辭、優先級或取捨時，只說明影響與依據。

不可做：
- 不替 Analyst 改寫正式需求。
- 不替 Mediator 或人類做取捨決策。
- 不把一般建議直接升格成需求。"""


# Defines ExpertAgent class for this module workflow.
class ExpertAgent(
    ExpertResponse,
    ExpertDomainResearch,
    ExpertIssues,
    BaseAgent,
):

    name = "expert"

    system_prompt = expert_system

    # Defines __init__ function for this module workflow.
    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        doc_dir: str = "doc",
        project_config=None,
    ):
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["domain-research"],
            project_config=project_config,
        )

    # Defines skill usage policy function for this module workflow.
    def skill_usage_policy(self) -> str:
        return expert_skill_usage_policy()

    # Defines tool usage policy function for this module workflow.
    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return expert_tool_usage_policy(set(self.tools))
