# Mediator agent: plans agenda actions and coordinates formal requirement meetings.
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent, mediator_collect_line

from .agenda import MediatorAgenda
from .discussion import MediatorDiscussion
from .resolution import MediatorResolution
from .validation import AGENDA_ACTIONS, AGENDA_CATEGORY_LABEL, AGENDA_TYPE_IDS, AGENDA_TYPES




class MediatorAgentSupport:
    def build_reply_topic(
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
    def build_topic_result(
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
        verification_impact: Optional[Dict[str, Any]] = None,
        needs_approval: bool = False,
        requirement_change_candidates: Optional[List[Dict[str, Any]]] = None,
        suggested_next_actions: Optional[List[Dict[str, Any]]] = None,
        needs_human: bool = False,
        options: Optional[List[Dict[str, Any]]] = None,
        recommendation: Optional[Dict[str, Any]] = None,
        needs_user_confirmation: bool = False,
        confirmation_status: str = "",
    ) -> Dict[str, Any]:
        """統一 topic_result schema。"""
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
        verification_impact = verification_impact or {}
        if not isinstance(verification_impact, dict):
            verification_impact = {}
        verification_impact = {
            "level": str(verification_impact.get("level") or "none").strip() or "none",
            "notes": str(verification_impact.get("notes") or "").strip(),
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
            "schema_version": "topic_result.v1",
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
            "verification_impact": verification_impact,
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
        """產出專案狀態摘要，供 topic_response loop 的 artifact_snapshot 使用"""
        if not artifact:
            return {}
        reqs = artifact.get("requirements", [])
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

    @staticmethod
    def extract_traceability_ids(topic: Dict, contributions: List[Dict], resolution: Dict) -> List[str]:
        """從 source_ids 與討論/決議文字抓出可追溯 id（優先 REQ-*；相容 FR-* / NFR-* / CF-*）。"""
        ids = set()
        for sid in topic.get("source_ids", []) or []:
            if isinstance(sid, str) and sid.strip():
                ids.add(sid.strip())
        texts = [
            topic.get("title", ""),
            topic.get("description", ""),
            resolution.get("summary", ""),
            resolution.get("decision", ""),
        ]
        for c in contributions:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            texts.append(resp.get("statement", ""))
        blob = "\n".join(t for t in texts if t)
        for m in re.findall(r"\b(?:FR|NFR|R|CF)-[A-Za-z0-9-]+\b", blob):
            ids.add(m)
        return sorted(ids)


    def update_decisions(
        self, artifact: Dict[str, Any], round_discussions: List[Dict]
    ) -> Dict:
        discussions_text = json.dumps(round_discussions, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(
            artifact.get("conflicts", []), ensure_ascii=False, indent=2
        )

        user_prompt = f"""# 任務
    彙整本輪所有議程的討論決策，並更新 Conflict 的 label。

    # 本輪討論結果
    {discussions_text}

    # 當前 Conflict 列表
    {conflicts_text}

    # 規則
    - 若本輪討論認定某筆 Conflict 已解決（非 Conflict），將該筆 label 改為 Neutral
    - 若本輪討論認定某筆 Neutral 實為 Conflict，將該筆 label 改為 Conflict（誤判修正與升級皆經討論 + 本步驟）
    - 其餘依討論結果維持原 label。輸出 conflicts 時請保留每筆原有的所有欄位（id、description、conflict_type、requirement_ids、stakeholder_names 等），僅依討論結果更新 label
    - 每個 new_decisions 項目請填寫 resolved_conflict_ids：此決策所解決的 Conflict id 列表（若該議題討論解決了某個 Conflict 則填其 CF-xx id，否則空陣列）
    - 若本輪討論中有人指出「尚未列在當前 Conflict 列表中的需求/立場 Conflict」（辨識漏報），請將該筆填入 new_conflicts，格式見下方。id 留空由系統指派。
    - {mediator_collect_line()}

    # 輸出 JSON
    {{{{
    "new_decisions": [...],
    "conflicts": [...],
    "new_conflicts": [
        {{{{
            "description": "Conflict 描述",
            "conflict_type": "Logical | Technical | Resource | Temporal | Data | State | Priority | Scope",
            "requirement_ids": ["R-01", "R-02"]
        }}}}
    ]
    }}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages)

        def dict_rows(value: Any) -> List[Dict[str, Any]]:
            if not isinstance(value, list):
                return []
            return [row for row in value if isinstance(row, dict)]

        return {
            "new_decisions": dict_rows(response.get("new_decisions", [])),
            "conflicts": dict_rows(response.get("conflicts", artifact.get("conflicts", []))),
            "new_conflicts": dict_rows(response.get("new_conflicts", [])),
        }

    def generate_meeting_markdown(
        self,
        topic: Dict,
        contributions: List[Dict],
        resolution: Dict,
        round_num: int = 0,
        *,
        proposed_by: Optional[str] = None,
    ) -> str:
        mode = topic.get("discussion_mode", "sequential")
        participants = (
            topic.get("participants")
            or topic.get("speaking_order")
            or []
        )
        category = topic.get("category", "")
        cat_label = AGENDA_CATEGORY_LABEL.get(category, category)
        description = topic.get("description", "")
        proposer = (proposed_by if proposed_by is not None else topic.get("proposed_by"))
        proposer = (proposer or "").strip() or None

        md = f"# {topic.get('title', '')}\n\n"
        md += f"- **Round**: {round_num}\n"
        md += f"- **Category**: {cat_label}\n"
        if description:
            md += f"- **Description**: {description}\n"
        if proposer:
            md += f"- **Proposed by**: {proposer}\n"
        elif topic.get("source_issue_ids"):
            md += "- **Proposed by**: （無法自提案池追溯）\n"
        else:
            md += "- **Proposed by**: （本議題非來自 agent 提案池，無單一提案者）\n"
        summary = resolution.get("summary", "")
        decision = resolution.get("decision", "")
        resolution_status = resolution.get("resolution_status", resolution.get("resolution", ""))
        md += f"- **Summary**: {summary}\n"
        if decision:
            md += f"- **Decision**: {decision}\n"
        if resolution_status:
            label = "Recommendation status" if resolution_status == "pending_confirmation" else "Resolution"
            md += f"- **{label}**: {resolution_status}\n"
        md += f"- **Participants**: {', '.join(participants) if participants else '（無參與者）'}\n"
        md += f"- **Discussion mode**: {mode}\n"

        if resolution.get("needs_human"):
            md += "- **Decision status**: pending human decision\n"
        elif resolution.get("needs_user_confirmation"):
            md += "- **Decision status**: pending user confirmation\n"
        options = resolution.get("options", []) or []
        recommendation = resolution.get("recommendation", {}) or {}
        if options:
            md += "\n## Decision Options\n\n"
            for option in options:
                if not isinstance(option, dict):
                    continue
                md += f"### Option {option.get('id', '')}\n\n"
                md += f"{option.get('summary', '')}\n\n"
                for label, key in (("Pros", "pros"), ("Cons", "cons"), ("Impact", "impact")):
                    values = [str(x).strip() for x in (option.get(key) or []) if str(x).strip()]
                    if values:
                        md += f"- **{label}**: {'; '.join(values)}\n"
                if option.get("risk"):
                    md += f"- **Risk**: {option.get('risk')}\n"
                md += "\n"
        if recommendation:
            md += "## Recommendation\n\n"
            md += f"- **Option**: {recommendation.get('option_id', '')}\n"
            if recommendation.get("confidence"):
                md += f"- **Confidence**: {recommendation.get('confidence')}\n"
            if recommendation.get("rationale"):
                md += f"- **Rationale**: {recommendation.get('rationale')}\n"
            if resolution.get("needs_human"):
                md += "- **Human decision**: pending\n"
            elif resolution.get("needs_user_confirmation"):
                md += "- **User confirmation**: pending\n"
            md += "\n"
        agreed_points = resolution.get("agreed_points", []) or []
        unresolved_points = resolution.get("unresolved_points", []) or []
        affected_requirement_ids = resolution.get("affected_requirement_ids", []) or []
        verification_impact = resolution.get("verification_impact", {}) or {}
        if agreed_points:
            md += f"- **Agreed points**: {'; '.join(agreed_points)}\n"
        if unresolved_points:
            md += f"- **Unresolved points**: {'; '.join(unresolved_points)}\n"
        if affected_requirement_ids:
            md += f"- **Affected requirements**: {', '.join(affected_requirement_ids)}\n"
        if isinstance(verification_impact, dict):
            level = str(verification_impact.get("level") or "").strip()
            notes = str(verification_impact.get("notes") or "").strip()
            if level or notes:
                line = level or "none"
                if notes:
                    line = f"{line} — {notes}" if line else notes
                md += f"- **Verification impact**: {line}\n"
        if resolution.get("needs_approval") and not resolution.get("needs_user_confirmation"):
            md += "- **Decision status**: pending user confirmation\n"
        if resolution.get("needs_human"):
            md += "- **Needs human**: true\n"
        md += "\n"

        def clean_for_mom(text: str) -> str:
            raw = self.sanitize_statement_fallback(text)
            cleaned = self.extract_statement_from_structured_text(raw) or raw
            stripped = cleaned.strip()
            # 最後保險：若清理後仍像 JSON/dict/array 原文，就不顯示，避免 MoM 出現 JSON。
            if stripped.startswith("{") or stripped.startswith("["):
                return ""
            return stripped

        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        md += "## 討論內容\n\n"
        if not main_contribs:
            md += "（本議題無人發言）\n\n"
        else:
            for c in main_contribs:
                agent = c.get("agent", "?")
                resp = c.get("response", {})
                statement = clean_for_mom(resp.get("statement", ""))
                md += f"### {agent}\n\n"
                md += f"{statement or '（本發言無可讀內容）'}\n\n"

        oq_pairs = []
        for c in contributions:
            if not c.get("is_reply"):
                continue
            resp = c.get("response", {})
            question = resp.get("reply_to_question", "")
            from_agent = resp.get("reply_to_agent", "?")
            reply_agent = c.get("agent", "?")
            answer = clean_for_mom(resp.get("statement", "") or resp.get("content", ""))
            if question or answer:
                oq_pairs.append((from_agent, question, reply_agent, answer))
        if oq_pairs:
            md += "## 開放問題\n\n"
            for i, (from_agent, question, reply_agent, answer) in enumerate(oq_pairs):
                if i > 0:
                    md += "\n---\n\n"
                md += f"**{from_agent}** 問 **{reply_agent}**: {question}\n\n"
                md += f"**{reply_agent}**: {answer}\n\n"

        return md

    def build_design_rationale_entry_context(
        self,
        topic: Dict,
        contributions: List[Dict],
        resolution: Dict,
        topic_open_questions: List[Dict],
        round_num: int,
    ) -> Dict[str, Any]:
        """將單一議題討論結果整理為 Design Rationale 單筆上下文。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        statements = []
        for c in main_contribs:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            st = (resp.get("statement") or "").strip()
            if st:
                statements.append({"agent": c.get("agent", "?"), "statement": st})

        unresolved_oq = []
        for q in topic_open_questions:
            status = q.get("status", "")
            if status == "answered":
                continue
            unresolved_oq.append(
                {
                    "from_agent": q.get("from_agent", ""),
                    "to_agent": q.get("to_agent", ""),
                    "question": q.get("question", ""),
                    "status": status or "deferred",
                }
            )

        return {
            "topic": {
                "id": topic.get("id", ""),
                "title": topic.get("title", ""),
                "description": topic.get("description", ""),
                "category": topic.get("category", ""),
                "category_label": AGENDA_CATEGORY_LABEL.get(topic.get("category", ""), topic.get("category", "")),
                "discussion_mode": topic.get("discussion_mode", "sequential"),
                "participants": topic.get("participants", []) or topic.get("speaking_order", []),
                "source_ids": topic.get("source_ids", []),
            },
            "discussion": {
                "statements": statements,
                "open_issues": unresolved_oq,
            },
            "resolution": {
                "resolution": resolution.get("resolution", ""),
                "resolution_status": resolution.get("resolution_status", resolution.get("resolution", "")),
                "summary": resolution.get("summary", ""),
                "decision_summary": resolution.get("decision_summary", resolution.get("summary", "")),
                "decision": resolution.get("decision", ""),
                "agreed_points": resolution.get("agreed_points", []),
                "unresolved_points": resolution.get("unresolved_points", []),
                "new_open_questions": resolution.get("new_open_questions", []),
                "affected_conflict_ids": resolution.get("affected_conflict_ids", []),
                "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
                "verification_impact": resolution.get("verification_impact", {}),
                "requirement_change_candidates": resolution.get("requirement_change_candidates", []),
                "needs_human": resolution.get("needs_human", False),
                "options": resolution.get("options", []),
                "recommendation": resolution.get("recommendation", {}),
                "needs_user_confirmation": resolution.get("needs_user_confirmation", False),
                "confirmation_status": resolution.get("confirmation_status", ""),
            },
            "traceability_ids": self.extract_traceability_ids(topic, contributions, resolution),
            "metadata": {
                "round": round_num,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def generate_design_rationale_entry(self, topic_context: Dict[str, Any]) -> str:
        """結構化 render 單一議題的 Design Rationale 章節（不呼叫 LLM，避免事後敘事化）。"""
        topic = topic_context.get("topic", {}) or {}
        discussion = topic_context.get("discussion", {}) or {}
        resolution = topic_context.get("resolution", {}) or {}
        traceability_ids = topic_context.get("traceability_ids", []) or []
        metadata = topic_context.get("metadata", {}) or {}

        topic_id = topic.get("id", "T-??")
        topic_title = topic.get("title", "")

        def bullet(items, empty="待補"):
            items = [str(x).strip() for x in (items or []) if str(x).strip()]
            if not items:
                return f"- {empty}\n"
            return "".join(f"- {it}\n" for it in items)

        lines: List[str] = []
        lines.append(f"## {topic_id} {topic_title}\n")

        lines.append("\n### 問題與背景 (Issue / Context)\n")
        lines.append(f"{topic.get('description') or '待補'}\n")

        lines.append("\n### 設計目標 (Goals / Objectives)\n")
        lines.append(bullet([topic.get("category_label", "")]))

        lines.append("\n### 替代方案 (Alternatives)\n")
        options = resolution.get("options", []) or []
        if options:
            alt_items = [
                f"{opt.get('id', '')}: {opt.get('summary', '')}"
                for opt in options
                if isinstance(opt, dict)
            ]
        else:
            alt_items = ["本議題自然收斂，未產生多個正式替代方案。"]
        lines.append(bullet(alt_items))

        lines.append("\n### 最終決策 (Decision)\n")
        decision_status = resolution.get("resolution_status") or resolution.get("resolution") or ""
        if resolution.get("needs_human"):
            lines.append(f"待人類裁決：{resolution.get('summary') or '待補'}\n")
        elif resolution.get("needs_user_confirmation"):
            lines.append(f"待使用者確認：{resolution.get('summary') or '待補'}\n")
        else:
            lines.append(f"{resolution.get('decision') or resolution.get('summary') or '待補'}\n")
        if decision_status:
            lines.append(f"\nDecision Status: {decision_status}\n")

        lines.append("\n### 決策理由 (Justification)\n")
        recommendation = resolution.get("recommendation") or {}
        if isinstance(recommendation, dict) and recommendation:
            rec_parts = []
            if recommendation.get("option_id"):
                rec_parts.append(f"Recommended option: {recommendation.get('option_id')}")
            if recommendation.get("confidence"):
                rec_parts.append(f"Confidence: {recommendation.get('confidence')}")
            if recommendation.get("rationale"):
                rec_parts.append(f"Rationale: {recommendation.get('rationale')}")
            lines.append("\n".join(rec_parts) + "\n")
        else:
            lines.append(f"{resolution.get('decision_summary') or resolution.get('summary') or '待補'}\n")

        lines.append("\n### 取捨與影響 (Trade-offs & Impacts)\n")
        impact_items: List[str] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            for impact in option.get("impact") or []:
                impact_text = str(impact).strip()
                if impact_text:
                    impact_items.append(f"Option {option.get('id', '')}: {impact_text}")
        if not impact_items:
            impact_items = [str(x) for x in (resolution.get("agreed_points", []) or [])]
        lines.append(bullet(impact_items))

        lines.append("\n### 未決議事項 (Open Issues)\n")
        unresolved = discussion.get("open_issues", []) or []
        oq_items = [f"{q.get('from_agent','?')} → {q.get('to_agent','?')}: {q.get('question','')}" for q in unresolved]
        oq_items += [str(x) for x in (resolution.get("unresolved_points") or [])]
        lines.append(bullet(oq_items))

        lines.append("\n### 需求追蹤 (Traceability)\n")
        trace_items = list(traceability_ids) + list(resolution.get("affected_requirement_ids") or [])
        lines.append(bullet(trace_items))

        lines.append("\n### 會議資訊 (Metadata)\n")
        confirmation = resolution.get("confirmation_status") or (
            "pending" if resolution.get("needs_user_confirmation") else "not_required"
        )
        meta_items = [
            f"Round: {metadata.get('round', '')}",
            f"Topic ID: {topic_id}",
            f"Participants: {', '.join(topic.get('participants', []) or []) or '待補'}",
            f"User Confirmation: {confirmation}",
            f"Generated At: {metadata.get('generated_at', '')}",
        ]
        lines.append(bullet(meta_items))

        return "".join(lines).strip()

    def generate_design_rationale(self, topic_context: Dict[str, Any]) -> str:
        """初次建立 design_rationale.md。"""
        topic_id = (topic_context.get("topic") or {}).get("id", "")
        entry = self.generate_design_rationale_entry(topic_context)
        header = "# Design Rationale\n\n"
        header += "> 本文件由 Mediator 於每個議題討論完成後持續維護與更新。\n\n"
        if not entry:
            entry = f"## {topic_id or 'T-??'}\n\n待補\n"
        return header + entry

    def update_design_rationale(self, existing_md: str, topic_context: Dict[str, Any]) -> str:
        """既有 design_rationale.md 追加單一議題章節。"""
        base = (existing_md or "").rstrip()
        entry = self.generate_design_rationale_entry(topic_context)
        if not entry:
            topic_id = (topic_context.get("topic") or {}).get("id", "")
            entry = f"## {topic_id or 'T-??'}\n\n待補\n"
        if not base:
            return self.generate_design_rationale(topic_context)
        return f"{base}\n\n---\n\n{entry}"


class MediatorAgent(
    MediatorAgentSupport,
    MediatorAgenda,
    MediatorDiscussion,
    MediatorResolution,
    BaseAgent,
):
    name = "mediator"

    system_prompt = """你是需求調解主持人，負責 triage、主持討論、形成收斂結果。

規則：
1. 根據 proposal pool、queue、open conflicts、open questions 與本輪容量分流議題；不得憑空新增議題來源。
2. 優先走 direct clarification / direct apply / human decision；只有真的需要協調時才進 formal meeting。
3. 未自然收斂時，整理可選方案、影響與 recommendation，交由人類裁決；不得由代理人或 user agent 替人類定案。
4. 保持中立，不直接編寫 requirement；輸出可追蹤的 topic_result。
5. 無法形成明確建議時，升級至人類裁決。"""

    enabled_agenda_type_ids: Optional[List[str]] = None
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

    def build_agenda_action_observation(self, **kwargs: Any) -> Dict[str, Any]:
        state_summary = kwargs.get("state_summary") or {}
        return {
            "state_summary": state_summary,
            "topics_count": len(state_summary.get("topics") or []),
            "open_topics_count": len(state_summary.get("open_topics") or []),
            "queue_pending_count": int(state_summary.get("queue_pending_count") or 0),
            "can_expand_decision_topics": bool(state_summary.get("can_expand_decision_topics")),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 1),
        }

    def decide_agenda_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.plan_agenda_action_impl(
            kwargs.get("state_summary") or {},
            last_result,
        )

    def execute_agenda_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "action": decision.get("action", "finish_round"),
            "status": "planned",
            "summary": f"decision topic action selected: {decision.get('action', 'finish_round')}",
            "params": decision.get("params") or {},
        }

    def plan_agenda_action_via_opa(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        opa = self.run_action_loop(
            name="agenda_action",
            max_iterations=1,
            loop_cap=1,
            context={
                "state_summary": state_summary,
                "last_result": last_observation,
            },
            build_observation=self.build_agenda_action_observation,
            decide_action=self.decide_agenda_action,
            execute_action=self.execute_agenda_action,
        )
        trace = opa.get("opa_trace") or []
        decision = dict((trace[-1].get("decision") if trace else {}) or {})
        decision["opa_trace"] = opa.get("opa_trace", [])
        return decision
