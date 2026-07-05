# Defines agent profile initialization, system prompt, and public interface.
from typing import Optional

from agents.base import BaseAgent

from .model_flow import ModelerModeling
from .issues import ModelerIssues
from .response import ModelerResponse
from .rules import (
    tool_usage_policy as modeler_tool_usage_policy,
)

modeler_system = """你是一位專業系統建模者。

目標：
- 用系統模型協助釐清需求、系統邊界、角色互動、流程、資料、狀態與責任分工。
- 讓需求與系統模型彼此一致，支援後續 SRS 撰寫。

工作原則：
- 根據目前需求、需求範圍、會議結果與既有模型建立或更新模型。
- 發現模型與需求不一致時，指出需求缺口、模型影響與需要討論的問題。
- 資訊不足時指出缺口，不臆造未確認元素。

邊界：
- 模型是需求理解與溝通的輔助，不是需求決策本身。
- 建立或更新模型時，只使用已確認或可追蹤的需求內容。
- 可用模型說明流程、狀態、資料或責任邊界。

不可做：
- 不從模型反推新增需求。
- 不把未確認內容畫成正式模型元素。
- 不替人類裁定需求取捨。"""


# Defines ModelerAgent class for this module workflow.
class ModelerAgent(
    ModelerResponse,
    ModelerModeling,
    ModelerIssues,
    BaseAgent,
):

    name = "modeler"

    system_prompt = modeler_system

    # Defines __init__ function for this module workflow.
    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["UML"],
            project_config=project_config,
        )

    # Defines tool usage policy function for this module workflow.
    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return modeler_tool_usage_policy()
