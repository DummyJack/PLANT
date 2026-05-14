# Analyst agent: requirement extraction, conflict analysis, elicitation, and issue response.
from typing import Any, Dict, Optional

from agents.base import BaseAgent

from .conflicts import AnalystConflicts
from .elicitation import AnalystElicitation
from .analyze import AnalystRequirements
from .issues import AnalystIssues


ANALYST_PROJECT_SYSTEM_PROMPT = """你是需求分析師，負責把 stakeholder 訊號、會議討論與決策整理成可落地、可驗證、可追蹤的需求規格。

規則：
1. 主動辨識需求缺口、歧義、衝突、驗收條件不足與來源追蹤不足，並保留不確定性。
2. 僅整理 scope 內需求；超出範圍、證據不足或尚未確認者，保留為 open question、assumption 或 requirement_change_candidate。
3. 可修正文句、結構與欄位，使需求更清楚、可驗證、可測試、可追蹤，但不得改變需求實質語意。
4. 發現資料結構、狀態轉移、互動流程、法規或外部義務疑慮時，只整理為需求風險、限制或 open question，不自行定案。
5. 不自行解除 trade-off、裁定有爭議衝突、擴張 scope 或刪除有爭議需求。
6. 重大變更優先產生 change_record；只有低風險且有明確依據的文字修正可自動落地。

核心輸出：
- requirement text：清楚描述誰在什麼情境下需要什麼能力或結果。
- acceptance criteria：可觀察、可驗收，不能只重述需求。
- source trace：保留 stakeholder、discussion、decision 或 conflict 來源。
- open question：只在缺少可寫入需求的關鍵資訊時提出。"""


class AnalystAgent(
    AnalystIssues,
    AnalystRequirements,
    AnalystConflicts,
    AnalystElicitation,
    BaseAgent,
):
    name = "analyst"

    system_prompt = ""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["conflict-analyzer", "requirements-analyst"],
            project_config=project_config,
        )
        from agents.skills.base import get_skill

        parts = []
        for skill_name in ("requirements-analyst", "conflict-analyzer"):
            skill = get_skill(skill_name)
            if skill.get("content_system"):
                parts.append(skill["content_system"])
        blocks = [ANALYST_PROJECT_SYSTEM_PROMPT]
        blocks.extend(parts)
        self.system_prompt = "\n\n---\n\n".join([b for b in blocks if b])

    def get_optional_skill_context(
        self, issue: Dict, artifact_context: Optional[Dict]
    ) -> Optional[str]:
        return super().get_optional_skill_context(issue, artifact_context)

    def skill_usage_policy(self) -> str:
        return """requirements-analyst：
- 用於需求品質、需求文字、需求欄位完整性、acceptance criteria、可驗收性、歧義與 scope 邊界判斷。
- 用於 ELICIT 或會議回答需要轉成 requirement candidate、requirement change candidate 或 open question 時。
- 輸出限於需求品質與需求資料整理；遇到無法由需求證據支持的內容，改列 open question 或 change candidate。

conflict-analyzer：
- 用於 requirement pair conflict classification、conflict_discussion、需求間互斥/重疊/語義關係、SRS 條文衝突、驗收衝突、責任不清、scope 不清、重複但不一致，以及 requirement-level resolution options。
- 輸出限於需求間關係判斷與 resolution options；缺乏判斷依據時保留不確定性。

若議題只需要 Analyst 根據目前 artifact 做一般需求分析，不要使用 skill。"""

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return """- artifact_query 用於查詢目前 requirements、conflicts、open_questions、decisions 與相關來源。
- 使用工具取得專案事實後，仍須以 Analyst 角色判斷需求品質、可測試性、追蹤性與 scope 邊界。
- 工具結果不得直接覆蓋已定案需求；有不確定性時提出 open question 或 change candidate。"""

    def build_issue_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.issue_response_observation(**kwargs)

    def decide_issue_response_action(
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
            last_result=last_result,
        )

    def execute_issue_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_prompt = self.build_issue_response_prompt(
            issue=kwargs["issue"],
            previous_responses=kwargs.get("previous_responses"),
            artifact_context=(kwargs.get("observation") or {}).get("artifact_context"),
        )
        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_issue_response(messages)
        if response.get("error") or not str(response.get("statement") or "").strip():
            return {
                "action": decision.get("action", ""),
                "status": "failed",
                "error": response.get("error") or "missing_statement",
                "format_error": response.get("format_error") or "issue response must include statement",
                "summary": f"analyst issue_response 格式不合格: {decision.get('action', '')}",
            }
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": response.get("statement", ""),
            "pair_reviews": response.get("pair_reviews", []),
            "open_questions": response.get("open_questions", []),
            "target_stakeholders": response.get("target_stakeholders", []),
            "summary": f"完成 issue_response: {decision.get('action', '')}",
        }
