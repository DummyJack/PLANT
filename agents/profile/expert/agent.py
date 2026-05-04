# Expert agent: domain research, constraints, compliance risks, and topic response.
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, expert_fallback_viewpoint

from .domain_research import ExpertDomainResearch
from .read_file import ExpertParsing, ExpertReadFile
from .topics import ExpertTopics


class ExpertAgent(
    ExpertDomainResearch,
    ExpertTopics,
    ExpertReadFile,
    ExpertParsing,
    BaseAgent,
):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 file_parser 等工具。"""

    name = "expert"

    system_prompt = """你是領域專家，負責把外部法規、標準與安全約束轉成可用的限制與風險資訊。

規則：
1. 你提供的是證據、限制、風險與適用範圍，不負責決定產品 scope、優先級或最終需求 wording。
2. 強制義務、最佳實務與建議必須分開表達；證據不足時要明講。
3. 只有在合規風險、證據缺口或標準衝突明確時，才主張升級討論。"""

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
            kwargs.get("max_iterations", 1),
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
            if last.get("action") == "research_topic" and kwargs.get("research_results"):
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
            kwargs.get("pending_issues", []),
            kwargs.get("research_results", []),
        )

    def build_topic_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_topic_response_observation_payload(**kwargs)

    def decide_topic_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.decide_default_topic_response_action(
            observation,
            reasoning="根據議題類型選擇對應的單輪專家回應策略。",
        )

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
        response = self.chat_for_topic_response(messages)
        statement = (response.get("statement") or "").strip()
        if not statement:
            fallback_prompt = (
                f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n"
                f"描述: {topic.get('description', '')}\n\n{expert_fallback_viewpoint()}"
            )
            fallback_messages = self.build_direct_messages(fallback_prompt)
            try:
                raw_fallback = self.model.chat(fallback_messages)
                statement = (raw_fallback or "").strip()
            except Exception as e:
                self.logger.warning("expert 簡短重試失敗: %s", e)
                statement = "（依目前資訊暫無法提供具體法規依據，建議會後再查證後補充分享。）"
        if statement in {"{}", "[]", "```json\n{}\n```", "```json\n[]\n```", "```\n{}\n```", "```\n[]\n```"}:
            statement = "（依目前資訊尚無足夠依據提出具體專業判斷，建議補充更多情境或約束後再審。）"
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": statement,
            "open_questions": response.get("open_questions", []),
            "summary": f"完成 expert topic_response: {decision.get('action', '')}",
        }
