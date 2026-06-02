# Mediator decision logic: human decision option analysis.
from typing import Any, Dict, List, Optional

from .prompts import (
    close_issue_prompt,
    judge_options_prompt,
)
from .validation import (
    close_issue_data,
    judgment_data,
    trace_artifact_ids,
)

class MediatorDecision:
    def run_decision_loop(
        self,
        action: str,
        *,
        issue: Dict,
        conversation: List[Dict],
        decision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        opa = self.run_action_loop(
            name="decision",
            context={
                "decision_action": action,
                "issue": issue,
                "conversation": conversation,
                "decision_context": decision_context or {},
            },
            build_observation=self.build_decision_observation,
            decide_action=self.decide_decision_action,
            execute_action=self.execute_decision_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output", {})

    def build_decision_observation(self, **kwargs: Any) -> Dict[str, Any]:
        issue = kwargs.get("issue") or {}
        conversation = kwargs.get("conversation") or []
        main_records = [c for c in conversation if not c.get("is_reply", False)]
        return {
            "action": kwargs.get("decision_action", ""),
            "issue_id": issue.get("id", ""),
            "issue_category": issue.get("category", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "conversation_count": len(conversation),
            "main_conversation_count": len(main_records),
        }

    def decide_decision_action(
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
                "reasoning": "上一輪 decision 任務已完成，結束本次判斷。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行會議收斂與決議任務：{action}。",
        }

    def execute_decision_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        issue = kwargs.get("issue") or {}
        conversation = kwargs.get("conversation") or []
        decision_context = kwargs.get("decision_context") or {}
        try:
            if action == "prepare_judgment":
                output = self.build_judgment(issue, conversation, decision_context=decision_context)
            else:
                raise ValueError(f"未知 decision action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"decision failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 decision: {action}",
        }

    def prepare_judgment(
        self,
        issue: Dict,
        conversation: List[Dict],
        decision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        return self.run_decision_loop(
            "prepare_judgment",
            issue=issue,
            conversation=conversation,
            decision_context=decision_context,
        )

    def close_issue(
        self,
        issue: Dict,
        conversation: List[Dict],
        readiness: Dict[str, Any],
    ) -> Dict[str, Any]:
        """所有參與者都表示資訊足夠時，直接產出 agreed resolution。"""
        affected_conflict_ids = [
            sid for sid in trace_artifact_ids(issue)
            if isinstance(sid, str)
            and sid.startswith(("CR-", "PAIR-", "MULTIPLE-"))
        ]
        affected_requirement_ids = [
            sid for sid in trace_artifact_ids(issue)
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "R-", "ELICIT-"))
        ]
        discussion_text = ""
        for c in conversation:
            agent = c.get("agent", "?")
            response = c.get("response") or {}
            text = response.get("text", "")
            proposal = response.get("proposal")
            if proposal in (None, "", [], {}):
                stance = response.get("stance") if isinstance(response.get("stance"), dict) else {}
                proposal = stance.get("proposal")
            reply_label = "（回覆提問）" if c.get("is_reply") else ""
            discussion_text += f"\n【{agent}{reply_label}】\n{text}\n"
            if isinstance(proposal, dict) and proposal:
                discussion_text += f"proposal: {proposal}\n"
        try:
            user_prompt = close_issue_prompt(
                issue=issue,
                discussion_text=discussion_text,
                readiness=readiness,
            )
            response = self.chat_json(self.build_direct_messages(user_prompt))
            closed = close_issue_data(
                response,
                source_requirement_ids=affected_requirement_ids,
                source_conflict_ids=affected_conflict_ids,
            )
            summary = closed["summary"]
            decision = closed["decision"]
            agreed_points = closed["agreed_points"]
            affected_requirement_ids = closed["affected_requirement_ids"]
            affected_conflict_ids = closed["affected_conflict_ids"]
            requirement_changes = closed.get("requirement_changes", [])
            model_changes = closed.get("model_changes", [])
            open_questions = closed.get("open_questions", [])
            follow_up_actions = closed.get("follow_up_actions", [])
        except Exception:
            summary = readiness.get("summary") or "所有參與者都表示資訊已足夠，可以結束本議題。"
            decision = readiness.get("decision") or summary
            agreed_points = [decision] if decision else [summary]
            requirement_changes = []
            model_changes = []
            open_questions = []
            follow_up_actions = []
        return self.build_issue_result(
            status="agreed",
            summary=summary,
            decision=decision,
            mediator_compromise={"title": "", "description": "", "rationale": ""},
            agreed_points=agreed_points,
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            affected_requirement_ids=affected_requirement_ids,
            requirement_changes=requirement_changes,
            model_changes=model_changes,
            open_questions=open_questions,
            follow_up_actions=follow_up_actions,
            needs_human=False,
        )

    def build_judgment(
        self,
        issue: Dict,
        conversation: List[Dict],
        decision_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """將未收斂議題整理為可供人類裁決的決策選項，不由 agents 投票定案。"""
        discussion_text = ""
        for c in conversation:
            agent = c.get("agent", "?")
            text = (c.get("response") or {}).get("text", "")
            reply_label = "（回覆提問）" if c.get("is_reply") else ""
            discussion_text += f"\n【{agent}{reply_label}】\n{text}\n"

        user_prompt = judge_options_prompt(
            issue=issue,
            discussion_text=discussion_text,
            decision_context=decision_context,
        )
        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"決策選項分析失敗: {e}") from e

        source_req_ids = [
            sid for sid in trace_artifact_ids(issue)
            if isinstance(sid, str) and sid.startswith(("REQ-", "R-", "ELICIT-"))
        ]
        return judgment_data(
            response,
            source_requirement_ids=source_req_ids,
        )
