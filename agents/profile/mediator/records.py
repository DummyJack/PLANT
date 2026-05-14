# Mediator records: meeting markdown, decision updates, and design rationale.
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import all_conflict_rows, conflict_entries_count

from .prompts import update_decisions_prompt
from .validation import ISSUE_CATEGORY_LABEL


class MediatorRecords:
    @staticmethod
    def extract_traceability_ids(issue: Dict, contributions: List[Dict], resolution: Dict) -> List[str]:
        """從 source_ids 與討論/決議文字抓出可追溯 id（優先 REQ-*；相容 FR-* / NFR-* / CF-*）。"""
        ids = set()
        for sid in issue.get("source_ids", []) or []:
            if isinstance(sid, str) and sid.strip():
                ids.add(sid.strip())
        texts = [
            issue.get("title", ""),
            issue.get("description", ""),
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

    def run_meeting_record_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="meeting_record",
            max_iterations=3,
            loop_cap=self.agent_loop_round_cap(),
            context={
                "meeting_record_action": action,
                **context,
            },
            build_observation=self.build_meeting_record_observation,
            decide_action=self.decide_meeting_record_action,
            execute_action=self.execute_meeting_record_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_meeting_record_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        round_discussions = kwargs.get("round_discussions") or []
        issue_context = kwargs.get("issue_context") or {}
        return {
            "action": kwargs.get("meeting_record_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 3),
            "round_discussion_count": len(round_discussions),
            "conflicts_count": conflict_entries_count(artifact),
            "issue_id": (issue_context.get("issue") or {}).get("id", ""),
            "has_existing_design_rationale": bool(kwargs.get("existing_md")),
        }

    def decide_meeting_record_action(
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
                "reasoning": "上一輪 meeting record 任務已完成，結束本次紀錄更新。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行會議紀錄與 rationale 任務：{action}。",
        }

    def execute_meeting_record_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "update_decisions":
                output = self.update_decisions_record(
                    kwargs.get("artifact") or {},
                    kwargs.get("round_discussions") or [],
                )
            elif action == "generate_design_rationale":
                output = self.generate_design_rationale_record(
                    kwargs.get("issue_context") or {}
                )
            elif action == "update_design_rationale":
                output = self.update_design_rationale_record(
                    kwargs.get("existing_md") or "",
                    kwargs.get("issue_context") or {},
                )
            else:
                raise ValueError(f"未知 meeting record action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"meeting record failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 meeting record: {action}",
        }

    def update_decisions(
        self, artifact: Dict[str, Any], round_discussions: List[Dict]
    ) -> Dict:
        return self.run_meeting_record_loop(
            "update_decisions",
            artifact=artifact,
            round_discussions=round_discussions,
        ) or {"new_decisions": [], "conflicts": [], "new_conflicts": []}

    def generate_design_rationale(self, issue_context: Dict[str, Any]) -> str:
        return self.run_meeting_record_loop(
            "generate_design_rationale",
            issue_context=issue_context,
        ) or ""

    def update_design_rationale(self, existing_md: str, issue_context: Dict[str, Any]) -> str:
        return self.run_meeting_record_loop(
            "update_design_rationale",
            existing_md=existing_md,
            issue_context=issue_context,
        ) or ""

    def update_decisions_record(
        self, artifact: Dict[str, Any], round_discussions: List[Dict]
    ) -> Dict:
        user_prompt = update_decisions_prompt(
            round_discussions=round_discussions,
            conflicts=all_conflict_rows(artifact),
        )

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages)

        def dict_rows(value: Any) -> List[Dict[str, Any]]:
            if not isinstance(value, list):
                return []
            return [row for row in value if isinstance(row, dict)]

        return {
            "new_decisions": dict_rows(response.get("new_decisions", [])),
            "conflicts": dict_rows(response.get("conflicts", all_conflict_rows(artifact))),
            "new_conflicts": dict_rows(response.get("new_conflicts", [])),
        }

    def generate_meeting_markdown(
        self,
        issue: Dict,
        contributions: List[Dict],
        resolution: Dict,
        round_num: int = 0,
        *,
        proposed_by: Optional[str] = None,
    ) -> str:
        mode = issue.get("discussion_mode", "sequential")
        participants = (
            issue.get("participants")
            or issue.get("speaking_order")
            or []
        )
        category = issue.get("category", "")
        cat_label = ISSUE_CATEGORY_LABEL.get(category, category)
        description = issue.get("description", "")
        proposer = (proposed_by if proposed_by is not None else issue.get("proposed_by"))
        proposer = (proposer or "").strip() or None

        md = f"# {issue.get('title', '')}\n\n"
        md += f"- **Round**: {round_num}\n"
        md += f"- **Category**: {cat_label}\n"
        if description:
            md += f"- **Description**: {description}\n"
        if proposer:
            md += f"- **Proposed by**: {proposer}\n"
        elif issue.get("source_issue_ids"):
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
        requirement_impact = resolution.get("requirement_impact", {}) or {}
        if agreed_points:
            md += f"- **Agreed points**: {'; '.join(agreed_points)}\n"
        if unresolved_points:
            md += f"- **Unresolved points**: {'; '.join(unresolved_points)}\n"
        if affected_requirement_ids:
            md += f"- **Affected requirements**: {', '.join(affected_requirement_ids)}\n"
        if isinstance(requirement_impact, dict):
            level = str(requirement_impact.get("level") or "").strip()
            notes = str(requirement_impact.get("notes") or "").strip()
            if level or notes:
                line = level or "none"
                if notes:
                    line = f"{line} — {notes}" if line else notes
                md += f"- **Requirement impact**: {line}\n"
        if resolution.get("needs_approval") and not resolution.get("needs_user_confirmation"):
            md += "- **Decision status**: pending user confirmation\n"
        if resolution.get("needs_human"):
            md += "- **Needs human**: true\n"
        md += "\n"

        def clean_for_mom(text: str) -> str:
            return str(text or "").strip()

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
            answer = clean_for_mom(resp.get("statement", ""))
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
        issue: Dict,
        contributions: List[Dict],
        resolution: Dict,
        issue_open_questions: List[Dict],
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
        for q in issue_open_questions:
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
            "issue": {
                "id": issue.get("id", ""),
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "category": issue.get("category", ""),
                "category_label": ISSUE_CATEGORY_LABEL.get(issue.get("category", ""), issue.get("category", "")),
                "discussion_mode": issue.get("discussion_mode", "sequential"),
                "participants": issue.get("participants", []) or issue.get("speaking_order", []),
                "source_ids": issue.get("source_ids", []),
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
                "requirement_impact": resolution.get("requirement_impact", {}),
                "requirement_change_candidates": resolution.get("requirement_change_candidates", []),
                "needs_human": resolution.get("needs_human", False),
                "options": resolution.get("options", []),
                "recommendation": resolution.get("recommendation", {}),
                "needs_user_confirmation": resolution.get("needs_user_confirmation", False),
                "confirmation_status": resolution.get("confirmation_status", ""),
            },
            "traceability_ids": self.extract_traceability_ids(issue, contributions, resolution),
            "metadata": {
                "round": round_num,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def generate_design_rationale_entry(self, issue_context: Dict[str, Any]) -> str:
        """結構化 render 單一議題的 Design Rationale 章節（不呼叫 LLM，避免事後敘事化）。"""
        issue = issue_context.get("issue", {}) or {}
        discussion = issue_context.get("discussion", {}) or {}
        resolution = issue_context.get("resolution", {}) or {}
        traceability_ids = issue_context.get("traceability_ids", []) or []
        metadata = issue_context.get("metadata", {}) or {}

        issue_id = issue.get("id", "T-??")
        issue_title = issue.get("title", "")

        def bullet(items, empty="待補"):
            items = [str(x).strip() for x in (items or []) if str(x).strip()]
            if not items:
                return f"- {empty}\n"
            return "".join(f"- {it}\n" for it in items)

        lines: List[str] = []
        lines.append(f"## {issue_id} {issue_title}\n")

        lines.append("\n### 問題與背景 (Issue / Context)\n")
        lines.append(f"{issue.get('description') or '待補'}\n")

        lines.append("\n### 設計目標 (Goals / Objectives)\n")
        lines.append(bullet([issue.get("category_label", "")]))

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
            f"Issue ID: {issue_id}",
            f"Participants: {', '.join(issue.get('participants', []) or []) or '待補'}",
            f"User Confirmation: {confirmation}",
            f"Generated At: {metadata.get('generated_at', '')}",
        ]
        lines.append(bullet(meta_items))

        return "".join(lines).strip()

    def generate_design_rationale_record(self, issue_context: Dict[str, Any]) -> str:
        """初次建立 design_rationale.md。"""
        issue_id = (issue_context.get("issue") or {}).get("id", "")
        entry = self.generate_design_rationale_entry(issue_context)
        header = "# Design Rationale\n\n"
        header += "> 本文件由 Mediator 於每個議題討論完成後持續維護與更新。\n\n"
        if not entry:
            entry = f"## {issue_id or 'T-??'}\n\n待補\n"
        return header + entry

    def update_design_rationale_record(self, existing_md: str, issue_context: Dict[str, Any]) -> str:
        """既有 design_rationale.md 追加單一議題章節。"""
        base = (existing_md or "").rstrip()
        entry = self.generate_design_rationale_entry(issue_context)
        if not entry:
            issue_id = (issue_context.get("issue") or {}).get("id", "")
            entry = f"## {issue_id or 'T-??'}\n\n待補\n"
        if not base:
            return self.generate_design_rationale_record(issue_context)
        return f"{base}\n\n---\n\n{entry}"
