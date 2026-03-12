from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.policy import AgentSkillToolPolicy


@dataclass
class PlanStep:
    kind: str  # no_skill | single_skill | multi_skill
    agent: Optional[str] = None
    skill: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    rationale: str = ""
    score: float = 0.0


class PlannerService:
    """
    Planner v1:
    intent_classification -> candidate_skills -> scoring -> execution_plan
    """

    DEFAULT_PIPELINES: Dict[str, List[str]] = {
        "requirements_engineering": [
            "domain-research",
            "requirements-analyst",
            "conflict-analyzer",
            "srs-generation",
        ],
        "diagram_output": ["plantuml-ascii"],
    }

    def __init__(self, policy: AgentSkillToolPolicy):
        self.policy = policy

    def build_plan(self, task: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        intent = self._classify_intent(task)
        candidates = self._candidate_skills(intent)
        scored = [self._score_candidate(task, c, context or {}) for c in candidates]
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[0] if scored else None

        if not top or top["score"] <= 0:
            step = PlanStep(
                kind="no_skill",
                rationale="任務不符合既有 skill trigger 或輸入不足，走一般對話流程。",
                score=0.0,
            )
        elif top["kind"] == "single_skill":
            step = PlanStep(
                kind="single_skill",
                agent=top["agent"],
                skill=top["skill"],
                rationale=top["rationale"],
                score=top["score"],
            )
        else:
            step = PlanStep(
                kind="multi_skill",
                skills=list(top["skills"]),
                rationale=top["rationale"],
                score=top["score"],
            )

        return {
            "intent": intent,
            "candidates": scored,
            "step": step.__dict__,
        }

    def _classify_intent(self, task: str) -> str:
        q = (task or "").lower()
        if any(k in q for k in ["uml", "plantuml", "圖", "diagram", "模型"]):
            return "diagram_output"
        if any(k in q for k in ["需求", "srs", "規格", "conflict", "衝突", "分析"]):
            return "requirements_engineering"
        return "general"

    def _candidate_skills(self, intent: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if intent == "requirements_engineering":
            out.append(
                {
                    "kind": "multi_skill",
                    "skills": self.DEFAULT_PIPELINES["requirements_engineering"],
                    "agent": None,
                    "skill": None,
                    "base_score": 0.9,
                }
            )
            out.extend(
                [
                    {
                        "kind": "single_skill",
                        "agent": "analyst",
                        "skill": "requirements-analyst",
                        "base_score": 0.75,
                    },
                    {
                        "kind": "single_skill",
                        "agent": "analyst",
                        "skill": "conflict-analyzer",
                        "base_score": 0.65,
                    },
                    {
                        "kind": "single_skill",
                        "agent": "documentor",
                        "skill": "srs-generation",
                        "base_score": 0.6,
                    },
                ]
            )
            return out

        if intent == "diagram_output":
            out.append(
                {
                    "kind": "single_skill",
                    "agent": "modeler",
                    "skill": "plantuml-ascii",
                    "base_score": 0.8,
                }
            )
            return out

        return out

    def _score_candidate(self, task: str, candidate: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        score = float(candidate.get("base_score", 0.0))
        rationale: List[str] = []

        # 維度 1: 任務匹配度
        if score >= 0.8:
            rationale.append("任務匹配度高")
        elif score >= 0.6:
            rationale.append("任務匹配度中")
        else:
            rationale.append("任務匹配度低")

        # 維度 2: 輸入可用性
        has_context = bool(context)
        if has_context:
            score += 0.05
            rationale.append("輸入可用性足夠")
        else:
            rationale.append("輸入可用性有限")

        # 維度 3: 工具可用性 / policy
        policy_penalty = 0.0
        if candidate["kind"] == "single_skill":
            agent = candidate.get("agent")
            skill = candidate.get("skill")
            if agent and skill and not self.policy.can_agent_use_skill(agent, skill):
                policy_penalty += 0.5
                rationale.append("policy 不允許此 agent 使用該 skill")
        else:
            for skill in candidate.get("skills", []):
                # multi-skill 先做弱檢查（只要有一個可用即不封殺）
                mapped_agents = [
                    a for a in self.policy.agent_skill_mapping.keys()
                    if self.policy.can_agent_use_skill(a, skill)
                ]
                if not mapped_agents:
                    policy_penalty += 0.2
                    rationale.append(f"skill {skill} 無可用 agent")
        score -= policy_penalty

        # 維度 4: 成本與風險（多 skill 成本較高）
        if candidate["kind"] == "multi_skill":
            score -= 0.1
            rationale.append("多 skill 串接成本較高")
        else:
            rationale.append("單 skill 成本較低")

        return {
            **candidate,
            "score": round(max(score, 0.0), 3),
            "rationale": "；".join(rationale),
        }
