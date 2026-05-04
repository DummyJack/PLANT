# Shared agent action loop: observe, decide, execute, trace, repeat.
from typing import Any, Callable, Dict, Optional


class AgentActionLoop:
    def summarize_opa_observation(
        self, observation: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not isinstance(observation, dict):
            return {}
        summary: Dict[str, Any] = {}
        for key in (
            "iteration",
            "max_iterations",
            "requirements_count",
            "has_scan_results",
            "has_validator",
        ):
            if key in observation:
                summary[key] = observation.get(key)
        if "conflicts" in observation and isinstance(observation.get("conflicts"), list):
            summary["conflict_count"] = len(observation.get("conflicts") or [])
        if "recent_discussions" in observation and isinstance(
            observation.get("recent_discussions"), list
        ):
            summary["recent_discussion_count"] = len(
                observation.get("recent_discussions") or []
            )
        if "current_models" in observation and isinstance(
            observation.get("current_models"), list
        ):
            summary["current_model_count"] = len(observation.get("current_models") or [])
        if not summary:
            summary["keys"] = sorted(observation.keys())
        return summary

    def make_opa_trace_entry(
        self,
        *,
        mode: str,
        iteration: int,
        observation: Dict[str, Any],
        decision: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "mode": mode,
            "iteration": iteration,
            "observation": self.summarize_opa_observation(observation),
            "decision": dict(decision or {}),
            "result": dict(result or {}),
        }

    def run_action_loop(
        self,
        *,
        name: str,
        max_iterations: int,
        loop_cap: int,
        context: Optional[Dict[str, Any]] = None,
        build_observation: Callable[..., Dict[str, Any]],
        decide_action: Callable[..., Dict[str, Any]],
        execute_action: Callable[..., Dict[str, Any]],
    ) -> Dict[str, Any]:
        context = dict(context or {})
        actions_taken = []
        pending_issues = context.setdefault("pending_issues", [])
        effective_max = min(max_iterations, loop_cap)
        i = 0

        while i < effective_max:
            decision_context = {
                key: value for key, value in context.items() if key != "last_result"
            }
            observation = build_observation(
                iteration=i,
                max_iterations=effective_max,
                actions_taken=actions_taken,
                **context,
            )
            decision = decide_action(
                observation=observation,
                last_result=context.get("last_result"),
                **decision_context,
            )
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= effective_max:
                    effective_max = n
                    self.logger.info(
                        "  %s %s 輪數: %s/%s",
                        self.__class__.__name__.replace("Agent", ""),
                        name,
                        effective_max,
                        loop_cap,
                    )
            action = decision.get("action", "done")
            self.logger.info(
                "  %s %s [%s/%s]: %s",
                self.__class__.__name__.replace("Agent", ""),
                name,
                i + 1,
                effective_max,
                action,
            )
            if action == "done":
                break

            result = execute_action(
                decision=decision,
                observation=observation,
                **context,
            )
            context["last_result"] = result
            if isinstance(result, dict):
                context_updates = result.get("context_updates")
                if isinstance(context_updates, dict):
                    context.update(context_updates)
            actions_taken.append(
                {
                    "action": action,
                    "params": decision.get("params") or {},
                    "result_summary": (result or {}).get("summary", ""),
                }
            )
            if result and result.get("error"):
                self.logger.warning(
                    "  %s %s error: %s",
                    self.__class__.__name__.replace("Agent", ""),
                    name,
                    result["error"],
                )
            context.setdefault("opa_trace", []).append(
                self.make_opa_trace_entry(
                    mode=name,
                    iteration=i + 1,
                    observation=observation,
                    decision=decision,
                    result=result,
                )
            )
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
            "opa_trace": context.get("opa_trace", []),
        }
