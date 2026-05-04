import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents.profile.user import UserAgent
from Baseline.env.prompts import generate_user_response, judge_interviewer_action
from Baseline.env.utils import relevant_requirement_ids_from_judgement
from utils import CostTracker

from .utils import task_implicit_requirements, task_initial_requirements


@dataclass
class OracleConfigs:
    judge_model_config: Dict[str, Any]
    user_model_config: Dict[str, Any]


def parse_mediator_turn(topic_id: str) -> int:
    m = re.search(r"ELICIT-R\d+-T(\d+)", str(topic_id or ""))
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0


class OracleUserAgent(UserAgent):
    """將 RQ1 oracle user 接到 Plant flow 的 user agent。"""

    def __init__(
        self,
        model,
        oracle_configs: OracleConfigs,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model=model,
            tools=tools,
            registry=registry,
            project_config=project_config,
        )
        self.oracle = oracle_configs
        self.current_task: Dict[str, Any] = {}
        self.remaining_requirements: List[Dict[str, Any]] = []
        self.conversation_history: List[Dict[str, str]] = []
        self.last_action_info: Dict[str, Any] = {}
        self.oracle_trace: List[Dict[str, Any]] = []
        self.oracle_usage_total: Dict[str, Dict[str, int]] = {
            "judge": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "user": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        self.oracle_runtime_total_s: Dict[str, float] = {"judge": 0.0, "user": 0.0}

    @staticmethod
    def merge_usage(dst: Dict[str, int], usage: Dict[str, Any]) -> None:
        if not isinstance(usage, dict):
            return
        dst["prompt_tokens"] = int(dst.get("prompt_tokens", 0) or 0) + int(
            usage.get("prompt_tokens", 0) or 0
        )
        dst["completion_tokens"] = int(dst.get("completion_tokens", 0) or 0) + int(
            usage.get("completion_tokens", 0) or 0
        )
        dst["total_tokens"] = int(dst.get("total_tokens", 0) or 0) + int(
            usage.get("total_tokens", 0) or 0
        )

    @staticmethod
    def estimate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        tracker = CostTracker(str(model_name or ""))
        return float(tracker.estimateCost(int(prompt_tokens or 0), int(completion_tokens or 0)))

    def export_cost_summary(self) -> Dict[str, Any]:
        user_usage = self.oracle_usage_total.get("user", {})

        # 成本摘要口徑：僅統計 oracle user，不納入 LLM judge。
        input_tokens = int(user_usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(user_usage.get("completion_tokens", 0) or 0)
        total_tokens = int(user_usage.get("total_tokens", 0) or 0)

        user_model = str((self.oracle.user_model_config or {}).get("model_name") or "")
        estimated_cost = self.estimate_cost(
            user_model,
            int(user_usage.get("prompt_tokens", 0) or 0),
            int(user_usage.get("completion_tokens", 0) or 0),
        )

        return {
            "model": user_model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "run_time(s)": round(float(self.oracle_runtime_total_s.get("user", 0.0) or 0.0), 3),
            "estimated_cost(USD)": round(float(estimated_cost), 8),
        }

    def set_task(self, task: Dict[str, Any]) -> None:
        self.current_task = task
        self.conversation_history = []
        self.oracle_trace = []
        initial = task_initial_requirements(task)
        if initial:
            self.conversation_history.append({"role": "user", "content": initial})
        self.remaining_requirements = []
        for i, req in enumerate(task_implicit_requirements(task), start=1):
            text = str(req.get("text") or "").strip()
            if not text:
                continue
            self.remaining_requirements.append(
                {
                    "id": f"IR-{i:02d}",
                    "aspect": str(req.get("aspect") or "").strip() or "Unknown",
                    "requirement": text,
                }
            )
        self.stakeholders = [
            {
                "name": "Oracle User",
                "text": [initial] if initial else ["請透過提問挖掘我的隱性需求。"],
            }
        ]

    def propose_stakeholders(self, rough_idea: str) -> List[Dict[str, str]]:
        return [{"name": "Oracle User", "reason": "RQ1 oracle stakeholder"}]

    def generate_stakeholder_requirements(
        self, rough_idea: str, selected_stakeholders: List[str]
    ) -> List[Dict[str, Any]]:
        initial = task_initial_requirements(self.current_task) or str(rough_idea or "").strip()
        return [
            {
                "name": "Oracle User",
                "text": [initial] if initial else ["請透過提問挖掘我的隱性需求。"],
            }
        ]

    def latest_interviewer_inputs(
        self,
        topic: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
    ) -> tuple[Dict[str, str], str]:
        interviewer_roles = ("analyst", "expert", "modeler")
        if previous_responses:
            answer_all_questions = bool((topic or {}).get("answer_all_interviewer_questions"))
            if not answer_all_questions:
                for item in reversed(previous_responses):
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("agent") or "").strip()
                    if role not in interviewer_roles:
                        continue
                    resp = item.get("response", {}) if isinstance(item.get("response"), dict) else {}
                    text = str(resp.get("statement") or resp.get("content") or "").strip()
                    if text:
                        return {role: text}, self.format_interviewer_actions(topic, {role: text})

            actions_by_role: Dict[str, str] = {}
            for item in previous_responses:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("agent") or "").strip()
                if role not in interviewer_roles:
                    continue
                resp = item.get("response", {}) if isinstance(item.get("response"), dict) else {}
                text = str(resp.get("statement") or resp.get("content") or "").strip()
                if text:
                    actions_by_role[role] = text
            if actions_by_role:
                return actions_by_role, self.format_interviewer_actions(topic, actions_by_role)
        fallback = str(topic.get("description") or topic.get("title") or "").strip()
        return {}, fallback

    @staticmethod
    def format_interviewer_actions(topic: Dict[str, Any], actions_by_role: Dict[str, str]) -> str:
        lines = [
            "[STRUCTURED_INTERVIEWER_ACTION]",
            f"topic_id: {str((topic or {}).get('id') or '').strip()}",
            "interviewer_round_inputs:",
        ]
        for role, text in actions_by_role.items():
            lines.append(f"- role: {role}")
            lines.append(f"  statement: {text}")
        return "\n".join(lines)

    @staticmethod
    def aggregate_judgements(judge_details: List[Dict[str, Any]]) -> Dict[str, Any]:
        relevant_ids: List[str] = []
        relevant = False
        action_types: List[str] = []
        reasoning_parts: List[str] = []
        for detail in judge_details:
            judgement = detail.get("judgement") or {}
            if not isinstance(judgement, dict):
                continue
            action_type = str(judgement.get("action_type") or "").strip().lower()
            if action_type:
                action_types.append(action_type)
            if bool(judgement.get("is_relevant_to_implied_requirements", False)):
                relevant = True
            for rid in relevant_requirement_ids_from_judgement(judgement):
                if rid and rid not in relevant_ids:
                    relevant_ids.append(rid)
            role = str(detail.get("role") or "").strip()
            reason = str(judgement.get("reasoning") or "").strip()
            if role and reason:
                reasoning_parts.append(f"{role}: {reason}")

        if "probe" in action_types:
            action_type = "probe"
        elif "clarify" in action_types:
            action_type = "clarify"
        elif action_types:
            action_type = action_types[0]
        else:
            action_type = "probe"

        return {
            "action_type": action_type,
            "is_relevant_to_implied_requirements": relevant,
            "relevant_implied_requirements_id": relevant_ids[0] if relevant_ids else None,
            "relevant_implied_requirements_ids": relevant_ids,
            "reasoning": "\n".join(reasoning_parts),
        }

    def judge_interviewer_action_type(self, action_text: str) -> str:
        """用 oracle judge 直接判斷 interviewer 動作型態（clarify/probe/finish）。"""
        text = str(action_text or "").strip()
        if not text:
            return "probe"
        judge_t0 = time.perf_counter()
        judgement, judge_usage = judge_interviewer_action(
            action=text,
            task=self.current_task,
            model_config=self.oracle.judge_model_config,
            conversation_history=self.conversation_history,
            remaining_requirements=self.remaining_requirements,
            return_usage=True,
        )
        self.oracle_runtime_total_s["judge"] += max(0.0, time.perf_counter() - judge_t0)
        self.merge_usage(self.oracle_usage_total["judge"], judge_usage or {})
        if isinstance(judgement, dict):
            return str(judgement.get("action_type") or "probe").strip().lower() or "probe"
        return "probe"

    def build_observation(self, *, mode: str, **kwargs: Any) -> Dict[str, Any]:
        if mode == "topic_response":
            topic = kwargs["topic"]
            previous_responses = kwargs.get("previous_responses") or []
            artifact_snapshot = kwargs.get("artifact_snapshot") or {}
            return {
                "topic": topic,
                "topic_id": str(topic.get("id") or ""),
                "topic_category": str(topic.get("category") or ""),
                "previous_response_count": len(previous_responses),
                "has_artifact_snapshot": bool(artifact_snapshot),
                "iteration": kwargs.get("iteration", 0) + 1,
                "max_iterations": kwargs.get("max_iterations", 1),
            }
        return super().build_observation(mode=mode, **kwargs)

    def decide_action(
        self,
        *,
        mode: str,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "topic_response":
            return {
                "action": "oracle_user_response",
                "params": {},
                "reasoning": "以 oracle user simulator 回應本輪 interviewer action。",
            }
        return super().decide_action(
            mode=mode,
            observation=observation,
            last_result=last_result,
            **kwargs,
        )

    def build_topic_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.build_observation(mode="topic_response", **kwargs)

    def decide_topic_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.decide_action(
            mode="topic_response",
            observation=observation,
            last_result=last_result,
            **kwargs,
        )

    def execute_topic_response_action(
        self,
        *,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        response = self.oracle_topic_response(
            kwargs["topic"],
            previous_responses=kwargs.get("previous_responses"),
            artifact_snapshot=kwargs.get("artifact_snapshot"),
        )
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
            "oracle_action_type": response.get("oracle_action_type", ""),
            "oracle_is_relevant": bool(response.get("oracle_is_relevant", False)),
            "oracle_revealed_ids": response.get("oracle_revealed_ids", []) or [],
            "summary": "完成 oracle user topic_response",
        }

    def oracle_topic_response(self, topic, previous_responses=None, artifact_snapshot=None):
        interviewer_actions, merged_action = self.latest_interviewer_inputs(
            topic, previous_responses
        )
        topic_id = str((topic or {}).get("id") or "")
        mediator_turn = parse_mediator_turn(topic_id)
        judge_details: List[Dict[str, Any]] = []
        selected_role = ""
        selected_action = merged_action
        selected_judgement: Dict[str, Any] = {
            "action_type": "probe",
            "is_relevant_to_implied_requirements": False,
            "relevant_implied_requirements_id": None,
            "reasoning": "",
        }

        if interviewer_actions:
            ordered_roles = list(interviewer_actions.keys())
            for role in ordered_roles:
                action_text = interviewer_actions[role]
                judge_t0 = time.perf_counter()
                judgement, judge_usage = judge_interviewer_action(
                    action=action_text,
                    task=self.current_task,
                    model_config=self.oracle.judge_model_config,
                    conversation_history=self.conversation_history,
                    remaining_requirements=self.remaining_requirements,
                    return_usage=True,
                )
                self.oracle_runtime_total_s["judge"] += max(0.0, time.perf_counter() - judge_t0)
                self.merge_usage(self.oracle_usage_total["judge"], judge_usage or {})
                judge_details.append(
                    {
                        "role": role,
                        "action": action_text,
                        "judgement": judgement or {},
                    }
                )
            if bool((topic or {}).get("answer_all_interviewer_questions")) and judge_details:
                selected_role = "all"
                selected_action = merged_action
                selected_judgement = self.aggregate_judgements(judge_details)
            elif judge_details:
                first = judge_details[0]
                selected_role = str(first.get("role") or "")
                selected_action = str(first.get("action") or merged_action)
                selected_judgement = first.get("judgement") or selected_judgement
        else:
            selected_role = "merged"
            judge_t0 = time.perf_counter()
            judgement, judge_usage = judge_interviewer_action(
                action=selected_action,
                task=self.current_task,
                model_config=self.oracle.judge_model_config,
                conversation_history=self.conversation_history,
                remaining_requirements=self.remaining_requirements,
                return_usage=True,
            )
            self.oracle_runtime_total_s["judge"] += max(0.0, time.perf_counter() - judge_t0)
            self.merge_usage(self.oracle_usage_total["judge"], judge_usage or {})
            selected_judgement = judgement or selected_judgement

        user_response = ""
        user_usage: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        action_type = str(selected_judgement.get("action_type") or "").strip().lower()
        if action_type != "finish":
            user_t0 = time.perf_counter()
            user_response, user_usage = generate_user_response(
                action=selected_action,
                action_judgement=selected_judgement,
                conversation_history=self.conversation_history,
                simulator_model_config=self.oracle.user_model_config,
                remaining_requirements=self.remaining_requirements,
                return_usage=True,
            )
            self.oracle_runtime_total_s["user"] += max(0.0, time.perf_counter() - user_t0)
        self.merge_usage(self.oracle_usage_total["user"], user_usage or {})

        elicited_req_ids: List[str] = []
        is_relevant = bool(selected_judgement.get("is_relevant_to_implied_requirements", False))
        relevant_req_ids = relevant_requirement_ids_from_judgement(selected_judgement)
        if is_relevant and relevant_req_ids:
            relevant_req_id_set = set(relevant_req_ids)
            for req in self.remaining_requirements:
                req_id = str(req.get("id") or "").strip()
                if req_id in relevant_req_id_set:
                    elicited_req_ids.append(req_id)

        if elicited_req_ids:
            hit_ids = set(elicited_req_ids)
            self.remaining_requirements = [
                req for req in self.remaining_requirements if req.get("id") not in hit_ids
            ]
        self.conversation_history.append({"role": "interviewer", "content": selected_action})
        self.conversation_history.append({"role": "user", "content": user_response})
        self.last_action_info = selected_judgement or {}
        self.oracle_trace.append(
            {
                "turn": len(self.oracle_trace) + 1,
                "topic_id": topic_id,
                "mediator_turn": mediator_turn,
                "interviewer_action": selected_action,
                "interviewer_action_merged": merged_action,
                "selected_interviewer_role": selected_role,
                "judge_per_role": judge_details,
                "user_response": user_response,
                "judge": self.last_action_info,
                "revealed_ids": list(elicited_req_ids or []),
                "remaining_implicit": len(self.remaining_requirements),
                "usage": {
                    "judge": {"checked_actions": len(judge_details) if judge_details else 1},
                    "user": user_usage or {},
                },
            }
        )
        return {
            "agent": self.name,
            "statement": user_response,
            "open_questions": [],
            "oracle_action_type": self.last_action_info.get("action_type", ""),
            "oracle_is_relevant": bool(
                self.last_action_info.get("is_relevant_to_implied_requirements", False)
            ),
            "oracle_revealed_ids": elicited_req_ids,
        }
