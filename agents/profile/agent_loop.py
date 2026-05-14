# Shared agent action loop: observe, plan, execute planned steps, trace, repeat.
from typing import Any, Callable, Dict, List, Optional


class AgentLoop:
    ACTION_LOOP_MAX_ITERATIONS = 3

    def action_plan_payload(self, raw_plan: Any) -> Dict[str, Any]:
        if not isinstance(raw_plan, dict):
            return {"goal": "", "steps": []}
        steps: List[Dict[str, Any]] = []
        for idx, raw_step in enumerate(raw_plan.get("steps") or [], 1):
            if not isinstance(raw_step, dict):
                continue
            action = str(raw_step.get("action") or "").strip()
            if not action:
                continue
            step = dict(raw_step)
            step.setdefault("id", f"step_{idx}")
            step.setdefault("params", {})
            step.setdefault("status", "pending")
            steps.append(step)
        return {
            "goal": str(raw_plan.get("goal") or "").strip(),
            "steps": steps,
        }

    def pending_plan_steps(self, action_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            step
            for step in action_plan.get("steps") or []
            if step.get("status") in {"pending", "format_invalid"}
        ]

    def mark_plan_step_result(
        self,
        step: Dict[str, Any],
        result: Optional[Dict[str, Any]],
        *,
        result_valid: bool,
    ) -> None:
        if not result_valid:
            step["status"] = "format_invalid"
            return
        if result and result.get("error"):
            step["status"] = "failed"
            return
        step["status"] = "completed"

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
        context: Optional[Dict[str, Any]] = None,
        build_observation: Callable[..., Dict[str, Any]],
        decide_action: Callable[..., Dict[str, Any]],
        execute_action: Callable[..., Dict[str, Any]],
        validate_result: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        context = dict(context or {})
        actions_taken = []
        action_plan = self.action_plan_payload(context.get("action_plan"))
        context["action_plan"] = action_plan
        effective_max = self.ACTION_LOOP_MAX_ITERATIONS
        extra_format_retry_used = False
        i = 0

        while i < effective_max:
            decision_context = {
                key: value
                for key, value in context.items()
                if key not in {"last_result", "action_plan"}
            }
            observation_context = {
                key: value for key, value in context.items() if key != "action_plan"
            }
            observation = build_observation(
                iteration=i,
                max_iterations=effective_max,
                actions_taken=actions_taken,
                action_plan=action_plan,
                **observation_context,
            )
            current_steps = self.pending_plan_steps(action_plan)
            if not current_steps:
                planned_decision = decide_action(
                    observation=observation,
                    last_result=context.get("last_result"),
                    **decision_context,
                )
                if isinstance(planned_decision.get("action_plan"), dict):
                    action_plan = self.action_plan_payload(planned_decision.get("action_plan"))
                context["action_plan"] = action_plan
                current_steps = self.pending_plan_steps(action_plan)
                if not current_steps:
                    decisions = [(planned_decision, None)]
                else:
                    decisions = [
                        (
                            {
                                **planned_decision,
                                "action": step.get("action", "done"),
                                "params": step.get("params") or {},
                                "plan_step_id": step.get("id"),
                                "plan_goal": action_plan.get("goal", ""),
                            },
                            step,
                        )
                        for step in current_steps
                    ]
            else:
                decisions = [
                    (
                        {
                            "action": step.get("action", "done"),
                            "params": step.get("params") or {},
                            "reasoning": step.get("reasoning", ""),
                            "plan_step_id": step.get("id"),
                            "plan_goal": action_plan.get("goal", ""),
                        },
                        step,
                    )
                    for step in current_steps
                ]
            stop_loop = False
            last_result_valid = True
            for decision, current_step in decisions:
                action = decision.get("action", "done")
                if action == "done":
                    if validate_result is not None and context.get("last_result") is not None:
                        if not context.get("last_result_valid", False):
                            if i >= effective_max - 1 and not extra_format_retry_used:
                                effective_max += 1
                                extra_format_retry_used = True
                            action = "repair_output_format"
                        else:
                            stop_loop = True
                            break
                    else:
                        stop_loop = True
                        break

                if action == "repair_output_format":
                    decision = {
                        **dict(decision or {}),
                        "action": action,
                        "reasoning": "上一輪輸出格式不合格，需修正格式後才能結束。",
                    }

                if action == "done":
                    stop_loop = True
                    break

                self.logger.info(
                    "%s %s [%s/%s]: %s",
                    self.__class__.__name__.replace("Agent", ""),
                    name,
                    i + 1,
                    effective_max,
                    action,
                )
                result = execute_action(
                    decision=decision,
                    observation=observation,
                    **context,
                )
                result_valid = True
                if validate_result is not None:
                    try:
                        result = validate_result(dict(result or {}))
                    except ValueError as e:
                        result = dict(result or {})
                        result["error"] = "output_contract_invalid"
                        result["format_error"] = str(e)
                        result_valid = False
                        issue = context.get("issue")
                        if isinstance(issue, dict):
                            context["issue"] = {
                                **issue,
                                "description": (
                                    f"{issue.get('description', '')}\n\n"
                                    "# 上一輪輸出格式不合格\n"
                                    f"{e}\n\n"
                                    "# 請在本輪修正\n"
                                    "- 只輸出合法 JSON。\n"
                                    "- 必須符合本議題的 response_contract。\n"
                                    "- 不要解釋格式錯誤。"
                                ),
                            }
                context["last_result"] = result
                context["last_result_valid"] = result_valid
                last_result_valid = result_valid
                if current_step is not None:
                    self.mark_plan_step_result(
                        current_step,
                        result,
                        result_valid=result_valid,
                    )
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
                if not result_valid:
                    break
            if stop_loop:
                break
            i += 1
            if (
                validate_result is not None
                and not last_result_valid
                and i >= effective_max
                and not extra_format_retry_used
            ):
                effective_max += 1
                extra_format_retry_used = True

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "action_plan": action_plan,
            "opa_trace": context.get("opa_trace", []),
        }
