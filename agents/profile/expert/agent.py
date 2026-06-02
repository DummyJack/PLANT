# Expert agent: domain research, constraints, compliance risks, and issue response.
from pathlib import Path
import json
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .domain_research import ExpertDomainResearch, research_source
from .read_file import ExpertParsing, ExpertReadFile
from .issues import ExpertIssues
from .prompts import EXPERT_SYSTEM_PROMPT


class ExpertAgent(
    ExpertDomainResearch,
    ExpertIssues,
    ExpertReadFile,
    ExpertParsing,
    BaseAgent,
):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 read_file 等工具。"""

    name = "expert"

    system_prompt = EXPERT_SYSTEM_PROMPT

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
        return self.build_research_observation(
            kwargs["artifact"],
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
        return self.decide_research_action(observation, last_result)

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
- 用於候選需求涉及外部法規、標準、安全、隱私、稽核、認證、第三方限制、外部資料限制、產業流程或 domain risk。
- 只有當外部資料會影響候選需求、constraint、risk 或外部限制邊界判斷時才使用。
- 用於確認某項 obligation 是否真有約束力，或區分強制義務、最佳實務、風險提醒與待查證缺口。
- 不用於一般功能需求討論、scope/priority/UX preference、純需求語意衝突，或既有領域研究資料已足夠的情況。"""

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        lines = []
        if "artifact_query" in self.tools:
            lines.append(
                "- artifact_query 用於先確認 scenario、scope、需求、stakeholders、open_questions 與既有 domain research；研究前先查既有 artifact，只有既有資料不足時才用 read_file 或 web_search。"
            )
        if "read_file" in self.tools:
            lines.append(
                "- read_file 用於查 doc/ 內專案參考文件；需要文件證據時先搜尋再讀相關片段。"
            )
        if "web_search" in self.tools:
            lines.append(
                "- web_search 只用於補外部法規、標準、官方文件、最佳實務或外部風險依據；不得覆蓋專案已知事實。"
            )
        lines.append(
            "- 區分強制義務、最佳實務、風險提醒與 evidence gap；外部研究結果預設只是候選依據。"
        )
        return "\n".join(lines)

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
            available_actions={
                "answer_question": "使用時機：有人在 open_questions 中指定 expert 回答。不要使用：一般議題發言或領域研究。寫回或影響：只回答問題，不更新專案資料。",
                "respond_issue": "使用時機：只需要根據 issue、前文與現有資料表達領域意見。不要使用：需要專案文件證據、外部法規/標準、第三方限制或 feedback 更新時。寫回或影響：只產生會議發言，不更新 feedback。",
                "research_domain": "使用時機：需要專案文件證據、外部領域知識、法規/標準、合規限制、安全/隱私風險、第三方條款或最佳實務來判斷需求邊界。不要使用：一般功能偏好、純需求語意討論或既有資料已足夠的情況。寫回或影響：內部可先 read_reference_docs，再 research_issue；只要產生研究結果就必須 update_feedback，結果整理為 feedback，不直接定案需求。",
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
        action = str(decision.get("action") or "").strip()
        artifact = kwargs.get("artifact")
        expert_action_result: Optional[Dict[str, Any]] = None
        if action == "answer_question":
            expert_action_result = {
                "action": action,
                "summary": "回答 open question，不更新專案資料。",
            }
        elif action == "respond_issue":
            expert_action_result = {
                "action": action,
                "summary": "只產生會議回答，不更新專案資料。",
            }
        elif action == "research_domain":
            if not isinstance(artifact, dict):
                return {
                    "action": action,
                    "status": "failed",
                    "error": "missing_artifact",
                    "format_error": "research_domain requires artifact context",
                    "summary": "expert research_domain 缺少 artifact，無法執行領域研究流程",
                }
            self.apply_issue_research_context(
                artifact,
                issue=issue,
                previous_responses=kwargs.get("previous_responses"),
            )
            loop_result = self.run_domain_research_loop(artifact)
            trace = loop_result.get("opa_trace") if isinstance(loop_result, dict) else []
            source_ref = research_source(artifact)
            expert_action_result = {
                "action": action,
                "steps": [
                    str((row.get("decision") or {}).get("action") or "").strip()
                    for row in (trace or [])
                    if isinstance(row, dict) and str((row.get("decision") or {}).get("action") or "").strip()
                ],
                "feedback": self.feedback_for_source(
                    artifact.get("feedback", {}),
                    source_ref,
                ),
            }
        return expert_action_result or {"action": action, "summary": f"完成 expert action: {action}"}

    def apply_issue_research_context(
        self,
        artifact: Dict[str, Any],
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        parts = [
            f"正式會議議題：{issue.get('title', '')}",
            f"類型：{issue.get('category', '')}",
        ]
        description = str(issue.get("description") or "").strip()
        if description:
            parts.append(f"描述：{description}")
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        artifact_ids = trace.get("artifact_ids") or []
        if artifact_ids:
            parts.append(f"來源需求/資料 id：{json.dumps(artifact_ids, ensure_ascii=False)}")
        if previous_responses:
            summaries = []
            for row in previous_responses[-4:]:
                if not isinstance(row, dict):
                    continue
                response = row.get("response") if isinstance(row.get("response"), dict) else {}
                text = str(response.get("text") or "").strip()
                if text:
                    summaries.append(f"{row.get('agent', '?')}: {text[:500]}")
            if summaries:
                parts.append("前面發言重點：" + " / ".join(summaries))
        artifact["current_issue"] = {
            "id": issue.get("id"),
            "meeting_id": issue.get("meeting_id"),
            "title": issue.get("title"),
            "category": issue.get("category"),
            "description": issue.get("description", ""),
            "trace": trace,
            "discussion_context": "；".join(part for part in parts if part),
        }

    @staticmethod
    def feedback_for_source(feedback: Any, source_ref: str) -> Dict[str, Any]:
        if not isinstance(feedback, dict) or not str(source_ref or "").strip():
            return {}
        source_ref = str(source_ref).strip()
        out: Dict[str, Any] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows = []
            for row in (feedback.get(section) or []):
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source") or "").strip()
                if source == source_ref:
                    rows.append(dict(row))
            if rows:
                out[section] = rows
        return out
