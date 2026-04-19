"""MeetingCoordinator — 會議協調窗口。

所有實作已拆至子模組：
  - main_meeting          : 每輪主會議生命週期
  - meeting_hidden_elicitation : 隱性需求挖掘
  - meeting_conflict_review    : 衝突再審查 / 需求變更
  - meeting_subflows           : agenda loop / queue 子流程
"""
from typing import Any, Dict, List, Optional

from .main_meeting import (
    _apply_mediator_updates,
    _collect_topic_proposals,
    _normalize_topic_proposal,
    _recent_topic_discussions,
    _run_enabled_reviews,
    run_meeting_round_block,
)
from .meeting_conflict_review import run_pre_meeting_conflict_review_block
from .meeting_hidden_elicitation import run_hidden_requirement_elicitation_meeting_block
from .meeting_subflows import run_agenda_loop_block


class MeetingCoordinator:
    def __init__(self, flow):
        self.flow = flow

    def _json_safe_trace_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self._json_safe_trace_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe_trace_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._json_safe_trace_value(item)
                for key, item in value.items()
            }
        if isinstance(value, MeetingCoordinator):
            return {"type": "MeetingCoordinator"}
        return {
            "type": type(value).__name__,
            "repr": repr(value),
        }

    # ------ 共用小工具（window 保留供 flow.py 委派呼叫） ------

    def _is_last_meeting_round(self, artifact: Dict[str, Any], round_num: int) -> bool:
        meta = artifact.get("meta") or {}
        end = meta.get("session_end_round")
        if end is not None:
            try:
                return int(round_num) == int(end)
            except (TypeError, ValueError):
                pass
        try:
            total = int(self.flow.config.get("rounds", 1) or 1)
        except (TypeError, ValueError):
            total = 1
        return int(round_num) >= total

    def _record_contribution_opa_trace(
        self,
        artifact: Dict[str, Any],
        *,
        topic: Dict[str, Any],
        contributions: List[Dict[str, Any]],
        stage: str,
    ) -> None:
        trace_rows = artifact.setdefault("meeting_opa_trace", [])
        topic_id = topic.get("id")
        topic_title = topic.get("title")
        topic_category = topic.get("category")
        for c in contributions or []:
            if not isinstance(c, dict):
                continue
            response = c.get("response") or {}
            if not isinstance(response, dict):
                continue
            opa_trace = response.get("opa_trace") or []
            for row in opa_trace:
                if not isinstance(row, dict):
                    continue
                trace_rows.append(
                    {
                        "stage": stage,
                        "topic_id": topic_id,
                        "topic_title": topic_title,
                        "topic_category": topic_category,
                        "agent": c.get("agent"),
                        "trace": row,
                    }
                )

    def plan_agenda_action(
        self,
        *,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.flow.mediator_agent.plan_agenda_action_via_opa(
            state_summary,
            last_observation,
        )

    def _record_coordinator_step_trace(
        self,
        artifact: Dict[str, Any],
        *,
        stage: str,
        round_num: int,
        observation: Dict[str, Any],
        decision: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        artifact.setdefault("meeting_opa_trace", []).append(
            {
                "stage": stage,
                "topic_id": None,
                "topic_title": None,
                "topic_category": None,
                "agent": "meeting_coordinator",
                "trace": {
                    "agent": "meeting_coordinator",
                    "mode": "round_pipeline_step",
                    "iteration": 1,
                    "observation": self._json_safe_trace_value(observation),
                    "decision": self._json_safe_trace_value(decision),
                    "result": self._json_safe_trace_value(result),
                    "round_num": round_num,
                },
            }
        )

    def run_round_pipeline_step(
        self,
        *,
        stage: str,
        round_num: int,
        artifact: Dict[str, Any],
        action_fn,
        action_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        action_kwargs = dict(action_kwargs or {})
        observation = {
            "stage": stage,
            "round_num": round_num,
            "requirements_count": len(artifact.get("requirements", []) or []),
            "conflicts_count": len(artifact.get("conflicts", []) or []),
            "open_questions_count": len(artifact.get("open_questions", []) or []),
        }
        decision = {
            "action": stage,
            "params": self._json_safe_trace_value(action_kwargs),
            "reasoning": f"執行 {stage} pipeline step。",
        }
        updated_artifact = action_fn(**action_kwargs)
        result = {
            "status": "success",
            "summary": f"completed {stage}",
            "artifact_changed": updated_artifact is not None,
        }
        self._record_coordinator_step_trace(
            artifact,
            stage=stage,
            round_num=round_num,
            observation=observation,
            decision=decision,
            result=result,
        )
        return updated_artifact if updated_artifact is not None else artifact

    def observe_round_state(
        self,
        *,
        runner: Any,
        last_action_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state_summary = runner.get_state_summary()
        return {
            "round_num": runner.round_num,
            "state_summary": state_summary,
            "last_action_result": last_action_result or {},
            "topics_count": len(state_summary.get("topics") or []),
            "round_discussions_length": state_summary.get("round_discussions_length", 0),
            "has_pending_queue_items": bool(
                ((state_summary.get("queue_status") or {}).get("has_pending_queue_items"))
            ),
            "can_expand_agenda": bool(state_summary.get("can_expand_agenda")),
        }

    def plan_round_step(
        self,
        *,
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        state_summary = observation.get("state_summary") or {}
        last_observation = observation.get("last_action_result") or {}
        decision = self.plan_agenda_action(
            state_summary=state_summary,
            last_observation=last_observation,
        )
        return {
            "action": decision.get("action", "finish_round"),
            "params": decision.get("params") or {},
            "reasoning": decision.get("reasoning", ""),
            "opa_trace": decision.get("opa_trace", []),
        }

    def act_round_step(
        self,
        *,
        runner: Any,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = runner.run(decision.get("action", "finish_round"), decision.get("params") or {})
        result.setdefault("coordinator_opa_trace", []).append(
            {
                "agent": "meeting_coordinator",
                "mode": "round_orchestrator",
                "iteration": 1,
                "observation": {
                    "round_num": observation.get("round_num"),
                    "topics_count": observation.get("topics_count"),
                    "round_discussions_length": observation.get("round_discussions_length"),
                    "has_pending_queue_items": observation.get("has_pending_queue_items"),
                    "can_expand_agenda": observation.get("can_expand_agenda"),
                },
                "decision": {
                    "action": decision.get("action", "finish_round"),
                    "params": decision.get("params") or {},
                    "reasoning": decision.get("reasoning", ""),
                },
                "result": {
                    "error": result.get("error"),
                    "result": result.get("result"),
                },
            }
        )
        self.flow._ensure_artifact_contract(runner.artifact)
        runner.artifact.setdefault("meeting_opa_trace", []).extend(
            {
                "stage": "meeting_coordinator.round_step",
                "topic_id": (decision.get("params") or {}).get("topic_id"),
                "topic_title": None,
                "topic_category": None,
                "agent": "meeting_coordinator",
                "trace": row,
            }
            for row in (result.get("coordinator_opa_trace") or [])
            if isinstance(row, dict)
        )
        return result

    def run_round_opa_loop(self, runner: Any) -> None:
        last_action_result: Optional[Dict[str, Any]] = None
        while True:
            observation = self.observe_round_state(
                runner=runner,
                last_action_result=last_action_result,
            )
            decision = self.plan_round_step(observation=observation)
            action = decision.get("action", "finish_round")
            self.flow.logger.info("  決策: %s — %s", action, decision.get("reasoning", ""))
            if action == "finish_round":
                break
            result = self.act_round_step(
                runner=runner,
                decision=decision,
                observation=observation,
            )
            if result.get("error"):
                self.flow.logger.warning(f"  執行失敗: {result['error']}")
            elif action == "save_topic":
                latest = runner.get_round_discussions()
                if latest:
                    from .meeting_subflows import _post_topic_processing
                    _post_topic_processing(
                        self,
                        runner.artifact,
                        latest[-1],
                        round_num=runner.round_num,
                    )
            last_action_result = result

    # ------ 委派：main_meeting ------

    def _run_enabled_reviews(self, artifact, *, recent_discussions, roles):
        _run_enabled_reviews(self, artifact, recent_discussions=recent_discussions, roles=roles)

    def _recent_topic_discussions(self, artifact, *, rounds=1):
        return _recent_topic_discussions(artifact, rounds=rounds)

    def _normalize_topic_proposal(self, item, *, proposed_by, round_num, index):
        return _normalize_topic_proposal(item, proposed_by=proposed_by, round_num=round_num, index=index)

    def _collect_topic_proposals(self, artifact, *, round_num):
        return _collect_topic_proposals(self, artifact, round_num=round_num)

    def _apply_mediator_updates(self, artifact, updates):
        return _apply_mediator_updates(artifact, updates)

    # ------ 委派：meeting_subflows ------

    def _run_agenda_loop(self, runner):
        run_agenda_loop_block(self, runner)

    # ------ 委派：主流程入口 ------

    def run_hidden_requirement_elicitation_meeting(self, artifact, round_num):
        return self.run_round_pipeline_step(
            stage="hidden_requirement_elicitation",
            round_num=round_num,
            artifact=artifact,
            action_fn=run_hidden_requirement_elicitation_meeting_block,
            action_kwargs={
                "coordinator": self,
                "artifact": artifact,
                "round_num": round_num,
            },
        )

    def run_pre_meeting_conflict_review(self, artifact, round_num):
        return self.run_round_pipeline_step(
            stage="pre_meeting_conflict_review",
            round_num=round_num,
            artifact=artifact,
            action_fn=run_pre_meeting_conflict_review_block,
            action_kwargs={
                "coordinator": self,
                "artifact": artifact,
                "round_num": round_num,
            },
        )

    def run_meeting_round(self, artifact, round_num):
        return run_meeting_round_block(self, artifact, round_num)
