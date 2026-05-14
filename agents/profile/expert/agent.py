# Expert agent: domain research, constraints, compliance risks, and issue response.
from pathlib import Path
from typing import Any, Dict, Optional

from agents.base import BaseAgent

from .domain_research import ExpertDomainResearch
from .read_file import ExpertParsing, ExpertReadFile
from .issues import ExpertIssues


class ExpertAgent(
    ExpertDomainResearch,
    ExpertIssues,
    ExpertReadFile,
    ExpertParsing,
    BaseAgent,
):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 file_parser 等工具。"""

    name = "expert"

    system_prompt = """你是領域專家，負責把外部法規、標準與安全約束轉成可用的限制與風險資訊。

規則：
1. 你提供證據、限制、風險與適用範圍；涉及 scope、優先級或需求 wording 時，只整理影響與依據，不直接定案。
2. 強制義務、最佳實務與建議必須分開表達；證據不足時要明講。
3. 只有在合規風險、證據缺口或標準衝突明確時，才主張升級討論。
4. 涉及資料流、狀態或互動流程時，只指出限制、風險或待確認事項。
5. 不把外部最佳實務或一般建議直接升格成正式需求，只能作為候選依據、風險或 open question。"""

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

    def build_domain_research_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_domain_research_state(
            kwargs["artifact"],
            kwargs.get("recent_discussions"),
            kwargs.get("actions_taken", []),
            kwargs.get("research_results", []),
            kwargs.get("iteration", 0),
            kwargs["max_iterations"],
        )

    def decide_domain_research_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if kwargs.get("force_update_after_research"):
            last = last_result or {}
            if last.get("action") == "research_issue" and kwargs.get("research_results"):
                return {
                    "action": "update_findings",
                    "params": {},
                    "reasoning": "單輪 domain research 已完成研究，補跑 update_findings 寫回結果。",
                }
        return self.decide_next_domain_research_action(observation, last_result)

    def execute_domain_research_loop_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.execute_domain_research_action(
            decision.get("action", "done"),
            decision.get("params") or {},
            kwargs["artifact"],
            kwargs.get("research_results", []),
        )

    def skill_usage_policy(self) -> str:
        return """domain-research：
- 用於議題涉及外部法規、標準、安全、合規、領域最佳實務、domain risk 或 evidence gap。
- 只有當外部資料會影響 requirement、constraint、risk 或 acceptance boundary 判斷時才使用。
- 用於確認某項外部 obligation 是否真有約束力，或區分強制義務、最佳實務、風險提醒與待查證缺口。
- 不用於一般功能需求討論、scope/priority/UX preference、純需求語意衝突，或 artifact 已有足夠 domain research 的情況。"""

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return """- artifact_query 用於先確認專案內部 requirements、conflicts、decisions、open_questions 與既有 domain research。
- file_parser 用於查 doc/ 內專案參考文件；需要文件證據時先搜尋再讀相關片段。
- web_search 只用於補外部法規、標準、官方文件、最佳實務或外部風險依據；不得覆蓋 artifact 內已知事實。
- 區分強制義務、最佳實務、風險提醒與 evidence gap；外部研究結果預設只是候選依據。"""

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
            done_reasoning="上一輪領域專家回應已符合格式契約，結束本次回應。",
            active_reasoning="根據議題類型選擇對應的單輪專家回應策略。",
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
        response = self.chat_for_issue_response(messages)
        statement = (response.get("statement") or "").strip()
        if response.get("error") or not statement:
            return {
                "action": decision.get("action", ""),
                "status": "failed",
                "error": response.get("error") or "missing_statement",
                "format_error": response.get("format_error") or "issue response must include statement",
                "summary": f"expert issue_response 格式不合格: {decision.get('action', '')}",
            }
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": statement,
            "pair_reviews": response.get("pair_reviews", []),
            "open_questions": response.get("open_questions", []),
            "target_stakeholders": response.get("target_stakeholders", []),
            "summary": f"完成 expert issue_response: {decision.get('action', '')}",
        }
