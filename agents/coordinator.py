from typing import Any, Dict, Optional

from agents.planner import PlannerService


class BaseAgentCoordinator:
    """協調入口：包裝 Planner，輸出決策可觀測資料。"""

    def __init__(self, planner: PlannerService):
        self.planner = planner

    def plan(self, task: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        result = self.planner.build_plan(task=task, context=context or {})
        step = result.get("step") or {}
        return {
            "decision": step.get("kind", "no_skill"),
            "rationale": step.get("rationale", ""),
            "plan_steps": step,
            "raw": result,
        }
