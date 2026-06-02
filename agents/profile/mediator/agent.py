# Mediator agent: plans meeting issue actions and coordinates formal requirement meetings.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .prompts import (
    MEDIATOR_SYSTEM_PROMPT,
    closure_vote_prompt as build_closure_vote_prompt,
)
from .issue_planning import MediatorIssuePlanning
from .discussion import MediatorDiscussion
from .records import MediatorRecords
from .decision import MediatorDecision


class MediatorAgentSupport:
    def conflict_review_description(self, conflict_summaries: List[str]) -> str:
        return (
            "以下為本輪會前需審查的 Conflict/Neutral 項目。\n"
            "請先根據每個項目的 User Requirements（URL-*）原文獨立重判，"
            "並將重判結果填入 proposed_label（Conflict 或 Neutral）。\n"
            "必須同時做兩層檢視：\n"
            "1) 整體檢視：說明對整批標註品質的整體判斷（是否有系統性偏誤）。\n"
            "2) 逐筆檢視：每個 [PAIR-xxx] 或 [MULTIPLE-xxx] 都必須明確寫出：\n"
            "   - proposed_label: 重判後建議採用的標籤（Conflict 或 Neutral）\n"
            "   - reason: 一句到兩句審查理由，需說明獨立判斷依據\n"
            "reason 只能填純理由文字，不要包含 id、proposed_label 或欄位名稱。\n"
            "待審清單：\n" + "\n".join(conflict_summaries)
        )

    def build_reply_issue(
        self,
        *,
        question: str,
        from_agent: str,
        follow_up_hint: str,
        target_stakeholders=None,
    ) -> Dict[str, Any]:
        return {
            "id": "OQ",
            "title": f"回答 {from_agent} 的問題",
            "description": f"{question}\n\n{follow_up_hint}",
            "target_stakeholders": [
                str(name).strip()
                for name in (target_stakeholders or [])
                if str(name).strip()
            ],
        }

    @staticmethod
    def build_issue_result(
        *,
        status: str,
        summary: str,
        decision: str,
        mediator_compromise: Optional[Dict[str, Any]] = None,
        agreed_points: Optional[List[str]] = None,
        unresolved_points: Optional[List[str]] = None,
        new_open_questions: Optional[List[Dict[str, Any]]] = None,
        affected_conflict_ids: Optional[List[str]] = None,
        affected_requirement_ids: Optional[List[str]] = None,
        url_updates: Optional[List[Dict[str, Any]]] = None,
        requirement_changes: Optional[List[Dict[str, Any]]] = None,
        model_changes: Optional[List[Dict[str, Any]]] = None,
        open_questions: Optional[List[Dict[str, Any]]] = None,
        follow_up_actions: Optional[List[str]] = None,
        needs_human: bool = False,
        options: Optional[List[Dict[str, Any]]] = None,
        recommendation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """統一 issue_result schema。"""
        status = (status or "").strip()
        if status and status not in {"agreed", "human_decision"}:
            raise ValueError(f"resolution status 不合法: {status}")
        summary = (summary or "").strip()
        decision = (decision or "").strip()
        mediator_compromise = mediator_compromise or {
            "title": "",
            "description": "",
            "rationale": "",
        }
        agreed_points = [p.strip() for p in (agreed_points or []) if isinstance(p, str) and p.strip()]
        unresolved_points = [p.strip() for p in (unresolved_points or []) if isinstance(p, str) and p.strip()]
        new_open_questions = [
            q for q in (new_open_questions or [])
            if isinstance(q, dict) and ((q.get("question") or "").strip())
        ]
        affected_conflict_ids = [
            cid.strip() for cid in (affected_conflict_ids or [])
            if isinstance(cid, str) and cid.strip()
        ]
        affected_requirement_ids = [
            rid.strip() for rid in (affected_requirement_ids or [])
            if isinstance(rid, str) and rid.strip()
        ]
        url_updates = [
            row for row in (url_updates or [])
            if isinstance(row, dict) and str(row.get("action") or "").strip()
        ]
        requirement_changes = [row for row in (requirement_changes or []) if isinstance(row, dict)]
        model_changes = [row for row in (model_changes or []) if isinstance(row, dict)]
        open_questions = [
            q for q in (open_questions or [])
            if isinstance(q, dict) and str(q.get("question") or "").strip()
        ]
        follow_up_actions = [
            str(item).strip()
            for item in (follow_up_actions or [])
            if str(item).strip()
        ]
        options = [row for row in (options or []) if isinstance(row, dict)]
        recommendation = recommendation if isinstance(recommendation, dict) else {}
        result = {
            "summary": summary,
            "decision": decision,
            "agreed_points": agreed_points,
            "unresolved_points": unresolved_points,
            "new_open_questions": new_open_questions,
            "needs_human": bool(needs_human),
            "options": options,
            "recommendation": recommendation,
            "requirement_changes": requirement_changes,
            "model_changes": model_changes,
            "open_questions": open_questions,
            "follow_up_actions": follow_up_actions,
        }
        if status:
            result["status"] = status
        if affected_conflict_ids:
            result["affected_conflict_ids"] = affected_conflict_ids
        if affected_requirement_ids:
            result["affected_requirement_ids"] = affected_requirement_ids
        if url_updates:
            result["url_updates"] = url_updates
        if mediator_compromise and any(str(v or "").strip() for v in mediator_compromise.values()):
            result["mediator_compromise"] = mediator_compromise
        return result

class MediatorAgent(
    MediatorAgentSupport,
    MediatorIssuePlanning,
    MediatorDiscussion,
    MediatorRecords,
    MediatorDecision,
    BaseAgent,
):
    name = "mediator"

    system_prompt = MEDIATOR_SYSTEM_PROMPT

    enabled_issue_type_ids: Optional[List[str]] = None
    enable_human_judgment: bool = True

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model, tools=tools, registry=registry, project_config=project_config
        )

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return """- artifact_query 用於查詢目前需求、衝突、未決問題、決策、討論紀錄與議題池相關脈絡。
- 工具只能補足主持、分類、分流、收斂判斷所需的專案事實。
- 若資訊不足或未收斂，整理成待決選項或升級人類裁決，不得自行替利害關係人定案。"""

    def closure_vote_prompt(
        self,
        *,
        role: str,
        proposer_role: str,
        role_focus: str,
        scenario: Dict[str, Any],
        requirements: List[Dict[str, Any]],
        candidate_texts: List[str],
        recent_ask_history: List[Dict[str, Any]],
    ) -> str:
        return build_closure_vote_prompt(
            role=role,
            proposer_role=proposer_role,
            role_focus=role_focus,
            scenario=scenario,
            requirements=requirements,
            candidate_texts=candidate_texts,
            recent_ask_history=recent_ask_history,
        )

    def build_meeting_action_observation(self, **kwargs: Any) -> Dict[str, Any]:
        state_summary = kwargs.get("state_summary") or {}
        return {
            "state_summary": state_summary,
            "issues_count": len(state_summary.get("issues") or []),
            "open_issues_count": len(state_summary.get("open_issues") or []),
            "human_decision_pending_count": int(
                (state_summary.get("human_decision_status") or {}).get("human_decision_queue_count")
                or 0
            ),
            "can_add_issues": bool(state_summary.get("can_add_issues")),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
        }

    def decide_meeting_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if (
            isinstance(last_result, dict)
            and last_result.get("status") == "planned"
            and last_result.get("action")
        ):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪已完成 meeting action 規劃，結束本次規劃。",
            }
        return self.plan_meeting_action_internal(
            kwargs.get("state_summary") or {},
            last_result,
        )

    def execute_meeting_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "action": decision.get("action", "finish_round"),
            "status": "planned",
            "summary": f"meeting issue action selected: {decision.get('action', 'finish_round')}",
            "params": decision.get("params") or {},
        }

    def plan_meeting_action_via_opa(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        opa = self.run_action_loop(
            name="meeting_action",
            context={
                "state_summary": state_summary,
                "last_result": last_observation,
            },
            build_observation=self.build_meeting_action_observation,
            decide_action=self.decide_meeting_action,
            execute_action=self.execute_meeting_action,
        )
        trace = opa.get("opa_trace") or []
        decision = dict((trace[-1].get("decision") if trace else {}) or {})
        return decision
