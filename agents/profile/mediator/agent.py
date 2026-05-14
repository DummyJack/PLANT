# Mediator agent: plans meeting issue actions and coordinates formal requirement meetings.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import closure_vote_prompt as build_closure_vote_prompt
from .issue_planning import MediatorIssuePlanning
from .discussion import MediatorDiscussion
from .records import MediatorRecords
from .decision import MediatorDecision


class MediatorAgentSupport:
    def conflict_review_description(self, conflict_summaries: List[str]) -> str:
        return (
            "以下為本輪會前需審查的 Conflict/Neutral 項目。\n"
            "請先根據每個 pair 的 requirement_a / requirement_b 原文獨立重判，"
            "並將重判結果填入 proposed_label（Conflict 或 Neutral）。\n"
            "你必須同時做兩層檢視：\n"
            "1) 整體檢視：說明你對整批標註品質的整體判斷（是否有系統性偏誤）。\n"
            "2) 逐筆檢視：每個 [PAIR-xxx] 都必須明確寫出：\n"
            "   - proposed_label: 你重判後建議採用的標籤（Conflict 或 Neutral）\n"
            "   - confidence: high / medium / low\n"
            "   - reason: 一句到兩句審查理由，需說明你的獨立判斷依據\n"
            "reason 只能填純理由文字，不要包含 id、proposed_label、confidence 或欄位名稱。\n"
            "Neutral 的定義：兩項需求既不衝突、也不重複，且沒有直接語義關係。\n\n"
            "待審清單：\n" + "\n".join(conflict_summaries)
        )

    def build_reply_issue(
        self,
        *,
        question: str,
        from_agent: str,
        follow_up_hint: str,
    ) -> Dict[str, Any]:
        return {
            "id": "OQ",
            "title": f"回答 {from_agent} 的問題",
            "description": f"{question}\n\n{follow_up_hint}",
        }

    @staticmethod
    def build_issue_result(
        *,
        resolution_status: str,
        summary: str,
        decision: str,
        mediator_compromise: Optional[Dict[str, Any]] = None,
        agreed_points: Optional[List[str]] = None,
        unresolved_points: Optional[List[str]] = None,
        new_open_questions: Optional[List[Dict[str, Any]]] = None,
        affected_conflict_ids: Optional[List[str]] = None,
        affected_requirement_ids: Optional[List[str]] = None,
        requirement_impact: Optional[Dict[str, Any]] = None,
        needs_approval: bool = False,
        requirement_change_candidates: Optional[List[Dict[str, Any]]] = None,
        suggested_next_actions: Optional[List[Dict[str, Any]]] = None,
        needs_human: bool = False,
        options: Optional[List[Dict[str, Any]]] = None,
        recommendation: Optional[Dict[str, Any]] = None,
        needs_user_confirmation: bool = False,
        confirmation_status: str = "",
    ) -> Dict[str, Any]:
        """統一 issue_result schema。"""
        resolution_status = (resolution_status or "").strip() or "unresolved"
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
        requirement_impact = requirement_impact or {}
        if not isinstance(requirement_impact, dict):
            requirement_impact = {}
        requirement_impact = {
            "level": str(requirement_impact.get("level") or "none").strip() or "none",
            "notes": str(requirement_impact.get("notes") or "").strip(),
        }
        requirement_change_candidates = [
            row for row in (requirement_change_candidates or []) if isinstance(row, dict)
        ]
        suggested_next_actions = [
            row for row in (suggested_next_actions or []) if isinstance(row, dict)
        ]
        options = [row for row in (options or []) if isinstance(row, dict)]
        recommendation = recommendation if isinstance(recommendation, dict) else {}
        confirmation_status = (
            confirmation_status
            or ("pending" if needs_user_confirmation else "not_required")
        )
        dod_complete = bool(
            decision
            and (resolution_status not in {"agreed", "human_decision"}
                 or affected_requirement_ids)
        )
        result = {
            "schema_version": "issue_result.v1",
            "resolution": resolution_status,
            "summary": summary,
            "decision": decision,
            "resolution_status": resolution_status,
            "decision_summary": summary,
            "agreed_points": agreed_points,
            "unresolved_points": unresolved_points,
            "new_open_questions": new_open_questions,
            "affected_conflict_ids": affected_conflict_ids,
            "affected_requirement_ids": affected_requirement_ids,
            "requirement_impact": requirement_impact,
            "requirement_change_candidates": requirement_change_candidates,
            "suggested_next_actions": suggested_next_actions,
            "needs_human": bool(needs_human),
            "options": options,
            "recommendation": recommendation,
            "needs_user_confirmation": bool(needs_user_confirmation),
            "confirmation_status": confirmation_status,
            "dod_complete": dod_complete,
        }
        if mediator_compromise and any(str(v or "").strip() for v in mediator_compromise.values()):
            result["mediator_compromise"] = mediator_compromise
        if needs_approval:
            result["needs_approval"] = True
        return result

    @staticmethod
    def build_artifact_snapshot(artifact: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """產出專案狀態摘要，供 agent response 的 artifact_snapshot 使用"""
        if not artifact:
            return {}
        reqs = requirement_discussion_pool(artifact)
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"), "text": (r.get("text") or "")}
            for r in reqs
        ]
        conflicts = [
            {
                "id": c.get("id"),
                "label": c.get("label"),
                "description": (c.get("description") or ""),
            }
            for c in artifact.get("conflicts", [])
        ]
        oqs = [
            {"from_agent": q.get("from_agent"), "question": (q.get("question") or "")}
            for q in artifact.get("open_questions", [])
            if q.get("status") != "answered"
        ]
        out = {
            "rough_idea": artifact.get("rough_idea", ""),
            "scope": artifact.get("scope", {}),
            "stakeholders": [
                {
                    "name": s.get("name"),
                    "text": s.get("text", []),
                }
                for s in (artifact.get("stakeholders", []) or [])
                if isinstance(s, dict)
            ],
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "open_questions": oqs,
        }
        feedback = artifact.get("feedback", {})
        if feedback:
            out["feedback"] = feedback
        models = artifact.get("system_models", {}).get("models", [])
        if models:
            out["system_models"] = [
                {"name": m.get("name"), "type": m.get("type")}
                for m in models
            ]
        return out

class MediatorAgent(
    MediatorAgentSupport,
    MediatorIssuePlanning,
    MediatorDiscussion,
    MediatorRecords,
    MediatorDecision,
    BaseAgent,
):
    name = "mediator"

    system_prompt = """你是需求調解主持人，負責 triage、主持討論、形成收斂結果。

規則：
1. 根據 proposal pool、queue、open conflicts、open questions 與本輪容量分流議題；不得憑空新增議題來源。
2. 優先走 direct clarification / direct apply / human decision；只有真的需要協調時才進 formal meeting。
3. 未自然收斂時，整理可選方案、影響與 recommendation，交由人類裁決；不得由代理人或 user agent 替人類定案。
4. 保持中立，輸出可追蹤的 issue_result。
5. 無法形成明確建議時，升級至人類裁決。"""

    enabled_issue_type_ids: Optional[List[str]] = None
    enable_human_escalation: bool = True

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
        rough_idea: str,
        requirements: List[Dict[str, Any]],
        candidate_texts: List[str],
        recent_ask_history: List[Dict[str, Any]],
    ) -> str:
        return build_closure_vote_prompt(
            role=role,
            proposer_role=proposer_role,
            role_focus=role_focus,
            rough_idea=rough_idea,
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
            "queue_pending_count": int(state_summary.get("queue_pending_count") or 0),
            "can_expand_decision_issues": bool(state_summary.get("can_expand_decision_issues")),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 1),
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
            "summary": f"decision issue action selected: {decision.get('action', 'finish_round')}",
            "params": decision.get("params") or {},
        }

    def plan_meeting_action_via_opa(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        opa = self.run_action_loop(
            name="meeting_action",
            max_iterations=3,
            loop_cap=self.agent_loop_round_cap(),
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
        decision["opa_trace"] = opa.get("opa_trace", [])
        return decision
