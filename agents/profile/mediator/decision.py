# Mediator decision logic: convergence checks and human decision option analysis.
from typing import Any, Dict, List, Optional

from .prompts import (
    convergence_prompt,
    decision_option_analysis_prompt,
    human_option_slates_prompt,
)
from .validation import (
    convergence_result,
    decision_option_analysis,
    human_option_slates,
)

class MediatorDecision:
    def run_decision_loop(
        self,
        action: str,
        *,
        issue: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        opa = self.run_action_loop(
            name="decision",
            max_iterations=3,
            loop_cap=self.agent_loop_round_cap(),
            context={
                "decision_action": action,
                "issue": issue,
                "contributions": contributions,
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
        contributions = kwargs.get("contributions") or []
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        return {
            "action": kwargs.get("decision_action", ""),
            "issue_id": issue.get("id", ""),
            "issue_category": issue.get("category", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 3),
            "contribution_count": len(contributions),
            "main_contribution_count": len(main_contribs),
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
        contributions = kwargs.get("contributions") or []
        try:
            if action == "assess_discussion_convergence":
                output = self.evaluate_discussion_convergence(issue, contributions)
            elif action == "analyze_decision_options":
                output = self.build_decision_option_analysis(issue, contributions)
            elif action == "prepare_human_options":
                output = self.build_human_option_slates(issue, contributions)
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

    def assess_discussion_convergence(
        self,
        issue: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        return self.run_decision_loop(
            "assess_discussion_convergence",
            issue=issue,
            contributions=contributions,
        )

    def analyze_decision_options(
        self,
        issue: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        return self.run_decision_loop(
            "analyze_decision_options",
            issue=issue,
            contributions=contributions,
        )

    def prepare_human_options(self, issue: Dict, contributions: List[Dict]) -> Dict:
        return self.run_decision_loop(
            "prepare_human_options",
            issue=issue,
            contributions=contributions,
        )

    def evaluate_discussion_convergence(
        self,
        issue: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        """討論結束後判斷各方意見是否已自然收斂（無需折衷方案即可形成決議）。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        if not main_contribs:
            return {"converged": False, "reason": "無發言"}
        discussion_text = ""
        for c in main_contribs:
            agent = c.get("agent", "?")
            statement = (c.get("response") or {}).get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = convergence_prompt(issue=issue, discussion_text=discussion_text)
        messages = self.build_direct_messages(user_prompt)
        try:
            data = self.chat_json(messages)
            return convergence_result(data)
        except Exception as e:
            self.logger.warning("收斂判斷失敗: %s", e)
            return {"converged": False, "reason": str(e)}

    def build_converged_resolution(
        self,
        issue: Dict,
        contributions: List[Dict],
        convergence: Dict[str, Any],
    ) -> Dict[str, Any]:
        """討論已自然收斂時，直接產出 agreed resolution（無需折衷方案與投票）。"""
        summary = convergence.get("summary") or "討論各方意見一致，已自然收斂。"
        decision = convergence.get("decision") or summary
        affected_conflict_ids = [
            sid for sid in (issue.get("source_ids") or [])
            if isinstance(sid, str)
            and (sid.startswith("CF-") or sid.startswith("CF-D") or sid.startswith("NF-"))
        ]
        affected_requirement_ids = [
            sid for sid in (issue.get("source_ids") or [])
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "FR-", "NFR-", "R-", "ELICIT-"))
        ]
        return self.build_issue_result(
            resolution_status="agreed",
            summary=summary,
            decision=decision,
            mediator_compromise={"title": "", "description": "", "rationale": ""},
            agreed_points=[decision] if decision else [summary],
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            affected_requirement_ids=affected_requirement_ids,
            needs_approval=bool(affected_requirement_ids),
            needs_human=False,
        )

    def build_decision_option_analysis(
        self,
        issue: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        """將未收斂議題整理為可供人類裁決的決策選項，不由 agents 投票定案。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        discussion_text = ""
        for c in main_contribs:
            agent = c.get("agent", "?")
            statement = (c.get("response") or {}).get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = decision_option_analysis_prompt(
            issue=issue,
            discussion_text=discussion_text,
        )
        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.chat_json(messages)
        except Exception as e:
            self.logger.warning("決策選項分析失敗: %s", e)
            response = {}

        source_req_ids = [
            sid for sid in (issue.get("source_ids") or [])
            if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-", "R-", "ELICIT-"))
        ]
        return decision_option_analysis(
            response,
            source_requirement_ids=source_req_ids,
        )

    def build_human_option_slates(self, issue: Dict, contributions: List[Dict]) -> Dict:
        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = human_option_slates_prompt(
            issue=issue,
            discussion_text=discussion_text,
        )

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages)
        return human_option_slates(response)
