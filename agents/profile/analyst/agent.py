# Analyst agent: requirement extraction, conflict analysis, elicitation, and topic response.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .conflicts import AnalystConflicts
from .elicitation import AnalystElicitation
from .analyze import AnalystRequirements
from .topics import AnalystTopics


ANALYST_PROJECT_SYSTEM_PROMPT = """你是需求分析師，負責把多方意見整理成可落地、可驗證、可追蹤的需求規格。

規則：
1. 主動辨識衝突、缺口與歧義，保留不確定性。
2. 僅整理 scope 內需求；超出範圍者保留待決。
3. 可修正文句、結構與欄位，但不得自行解除 trade-off、裁定衝突、擴張 scope 或刪除有爭議需求。
4. 重大變更優先產生 requirement_change_candidates；只有低風險變更可自動落地。
5. 需求應盡量清楚、可驗證、可測試；不足時標記待確認。"""


class AnalystAgent(
    AnalystTopics,
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
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        return super().get_optional_skill_context(topic, artifact_snapshot)

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
            reasoning="根據議題類型選擇對應的單輪回應策略。",
        )

    def execute_topic_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_prompt = self.build_topic_response_prompt(
            topic=kwargs["topic"],
            previous_responses=kwargs.get("previous_responses"),
            artifact_snapshot=kwargs.get("artifact_snapshot"),
        )
        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
            "summary": f"完成 topic_response: {decision.get('action', '')}",
        }
