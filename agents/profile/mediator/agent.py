# Defines agent profile initialization, system prompt, and public interface.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .actions.judge import closure_vote as build_closure_vote
from .plan import MediatorIssuePlanning
from agents.meeting.discussion import MediatorDiscussion
from agents.meeting.record import MediatorRecords
from .decision import MediatorDecision
from .rules import tool_usage_policy as mediator_tool_usage_policy

mediator_system = """你是一位專業需求會議主持人。

目標：
- 規劃正式會議議題，主持討論，促成需求、衝突、取捨與責任邊界的收斂。
- 將會議結果整理成可追蹤的 resolution 與 MoM 依據。

工作原則：
- 根據目前專案資料、agent 提案、會議狀態與人類決策推進流程。
- 引導參與者釐清需求、衝突、取捨、責任邊界與未決問題。
- 無法自然收斂時，整理方案、影響與建議，交由人類裁決。

邊界：
- 只根據既有專案資料、議題來源與會議討論形成會議結果。
- 會議結果應可被 Analyst 後續沉澱成需求。
- 可主持討論與整理決議，但不替專家、建模者或需求分析師產生其專屬 artifact。

不可做：
- 不自行新增需求來源。
- 不替人類做高風險或有爭議裁決。
- 不把未討論或未確認內容寫成會議決議。"""


class MediatorAgentSupport:
    def conflict_review_description(self, conflict_summaries: List[str]) -> str:
        return (
            "以下為本輪會前需審查的 Conflict/Neutral 項目。\n"
            "請各 agent 根據自己的職責審查每個項目的 User Requirements（URL-*）原文，"
            "並將職責內的判斷填入 proposed_label（Conflict 或 Neutral）。"
            "若該 pair 不屬於自己的職責範圍，應維持 current_label，並在 reason 說明原因。\n"
            "角色分工：Analyst 判斷需求槽位、SRS 邊界與是否需要合併/改寫/裁定；"
            "Expert 只判斷已有 feedback、evidence_type、coverage 或 gaps 支持的外部證據、外部限制、領域風險或品質底線；"
            "Modeler 只判斷流程、狀態、資料、角色互動、責任邊界與模型可共存性。\n"
            "必須同時做兩層檢視：\n"
            "1) 整體檢視：說明對整批標註品質的整體判斷（是否有系統性偏誤）。\n"
            "2) 逐筆檢視：每個 [PAIR-xxx] 或 [MULTIPLE-xxx] 都必須明確寫出：\n"
            "   - proposed_label: 依自身職責建議採用的標籤（Conflict 或 Neutral）\n"
            "   - reason: 一句到兩句審查理由，需說明獨立判斷依據\n"
            "reason 只能填純理由文字，不要包含 id、proposed_label 或欄位名稱。\n"
            "待審清單：\n" + "\n".join(conflict_summaries)
        )

    def build_reply_issue(
        self,
        *,
        question: str,
        from_agent: str,
        target_stakeholders=None,
    ) -> Dict[str, Any]:
        return {
            "id": "OQ",
            "title": f"回答 {from_agent} 的問題",
            "description": question,
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
        affected_conflict_ids: Optional[List[str]] = None,
        affected_requirement_ids: Optional[List[str]] = None,
        url_updates: Optional[List[Dict[str, Any]]] = None,
        requirement_changes: Optional[List[Dict[str, Any]]] = None,
        model_changes: Optional[List[Dict[str, Any]]] = None,
        open_questions: Optional[List[Dict[str, Any]]] = None,
        needs_human: bool = False,
        options: Optional[List[Dict[str, Any]]] = None,
        recommendation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
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
        options = [row for row in (options or []) if isinstance(row, dict)]
        recommendation = recommendation if isinstance(recommendation, dict) else {}
        result = {
            "summary": summary,
            "decision": decision,
            "agreed_points": agreed_points,
            "unresolved_points": unresolved_points,
            "needs_human": bool(needs_human),
            "options": options,
            "recommendation": recommendation,
            "requirement_changes": requirement_changes,
            "model_changes": model_changes,
            "open_questions": open_questions,
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

    system_prompt = mediator_system

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
        return mediator_tool_usage_policy()

    def closure_vote_prompt(
        self,
        *,
        role: str,
        proposer_role: str,
        proposer_roles: Optional[List[str]] = None,
        role_focus: str,
        scenario: Dict[str, Any],
        requirements: List[Dict[str, Any]],
        candidate_texts: List[str],
        recent_ask_history: List[Dict[str, Any]],
    ) -> str:
        return build_closure_vote(
            role=role,
            proposer_role=proposer_role,
            proposer_roles=proposer_roles,
            role_focus=role_focus,
            scenario=scenario,
            requirements=requirements,
            candidate_texts=candidate_texts,
            recent_ask_history=recent_ask_history,
        )
