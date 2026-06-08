# Plans the next action for the agent.

from typing import Any, Dict, Optional

# Defines UserPlan class for this module workflow.
class UserPlan:
    # Defines plan stakeholder function for this module workflow.
    def plan_stakeholder(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪利害關係人需求擴展已完成，結束本次任務。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"以 User agent 情境利害關係人視角執行：{action}。",
        }

    # Defines plan issue function for this module workflow.
    def plan_issue(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪 User issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_issues",
            "params": {},
            "reasoning": "根據利害關係人情境、未回答問題與既有需求判斷是否提出使用者視角議題。",
        }
