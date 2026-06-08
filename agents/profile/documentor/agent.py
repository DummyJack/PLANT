# Defines agent profile initialization, system prompt, and public interface.
from typing import Optional

from agents.base import BaseAgent

from .srs import DocumentorSrs
from .dr_generate import DocumentorDr

documentor_system = """你是一位專業 SRS 撰寫者。

目標：
- 將最新需求草稿整理成可交付的軟體需求規格書。
- 整理每條正式需求的 Design Rationale，說明需求如何從訪談、衝突、回饋、模型與會議逐步形成。
- 讓 SRS 與 Design Rationale 保持正式、清楚、一致且可追蹤。

工作原則：
- 只根據最新 draft 與其可追蹤來源撰寫。
- 保持正式文件語氣、章節一致性與需求命名一致性。
- pending、open、unresolved 或未決內容不得寫成已定案需求。

邊界：
- 可整理正式需求、系統情境、系統限制、系統模型、需求追蹤表與 Design Rationale。
- 只轉換與整理已確認內容，不新增需求或決策。
- SRS 應讀起來像交付文件，而不是會議紀錄或工作摘要。

不可做：
- 不新增 draft 中不存在的需求、限制、模型或決策。
- 不把會議摘要、工作紀錄或建議文字直接當成 SRS 條文。
- 不改變需求原本的決策狀態。"""


# Defines DocumentorAgent class for this module workflow.
class DocumentorAgent(
    DocumentorSrs,
    DocumentorDr,
    BaseAgent,
):
    name = "documentor"

    system_prompt = documentor_system

    # Defines __init__ function for this module workflow.
    def __init__(
        self,
        model,
        store,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=[],
            project_config=project_config,
        )
        self.store = store

    # Defines generate srs function for this module workflow.
    def generate_srs(self) -> str:
        return self.generate_latest_srs()
