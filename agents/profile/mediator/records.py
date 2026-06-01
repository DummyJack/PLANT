# Mediator records: meeting markdown and design rationale.
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import conflict_entries_count

from .validation import ISSUE_CATEGORY_LABEL, trace_artifact_ids, trace_proposal_ids


class MediatorRecords:
    @staticmethod
    def extract_traceability_ids(issue: Dict, conversation: List[Dict], resolution: Dict) -> List[str]:
        """從 trace 與討論/決議文字抓出可追溯 id。"""
        ids = set()
        for sid in trace_artifact_ids(issue):
            if isinstance(sid, str) and sid.strip():
                ids.add(sid.strip())
        texts = [
            issue.get("title", ""),
            issue.get("description", ""),
            resolution.get("summary", ""),
            resolution.get("decision", ""),
        ]
        for c in conversation:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            texts.append(resp.get("text", ""))
        blob = "\n".join(t for t in texts if t)
        for m in re.findall(r"\b(?:REQ|R|CF)-[A-Za-z0-9-]+\b", blob):
            ids.add(m)
        return sorted(ids)

    def run_meeting_record_loop(self, action: str, **context: Any) -> Any:
        opa = self.run_action_loop(
            name="meeting_record",
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
        meeting_records = kwargs.get("meeting_records") or []
        issue_context = kwargs.get("issue_context") or {}
        return {
            "action": kwargs.get("meeting_record_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "meeting_record_count": len(meeting_records),
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
            if action == "write_rationale":
                output = self.write_rationale_record(
                    kwargs.get("issue_context") or {}
                )
            elif action == "update_rationale":
                output = self.update_rationale_record(
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

    def write_rationale(self, issue_context: Dict[str, Any]) -> str:
        return self.run_meeting_record_loop(
            "write_rationale",
            issue_context=issue_context,
        )

    def update_rationale(self, existing_md: str, issue_context: Dict[str, Any]) -> str:
        return self.run_meeting_record_loop(
            "update_rationale",
            existing_md=existing_md,
            issue_context=issue_context,
        )

    @staticmethod
    def design_rationale_entry_prompt(issue_context: Dict[str, Any]) -> str:
        return f"""請根據 formal meeting issue context 產生單筆 Design Rationale Markdown entry。

# formal meeting issue context
{json.dumps(issue_context, ensure_ascii=False, indent=2)}

# 寫作目標
- 這是設計理由紀錄，不是 MoM，也不是 JSON 摘要。
- 只整理本議題已存在的討論、resolution、artifact updates 與 traceability。
- 不得編造 context、alternative、impact、open issue 或不存在的理由。
- 不要整段貼上會議逐字稿。
- 不要輸出「待補」。
- 若某節沒有可用內容，省略該節。

# entry 格式
請輸出 Markdown，且只能輸出單筆 entry：

## {{issue_id}} {{issue_title}}

### Context
說明本議題要解決的需求問題、衝突、邊界或決策背景。

### Decision
條列最後採用的決策。若 decision 包含多個 CR/REQ/URL，請拆成多條。

### Rationale
條列為什麼採用此決策；需根據 summary、discussion、recommendation 或 agreed_points。

### Alternatives
只在 options 或 discussion 中真的有方案比較時輸出；列出未採用方案與原因。

### Impact
條列此決策影響的 artifact，例如 requirements.json、conflict report、system_models.json、draft。

### Open Issues
只在仍有 unresolved_points、open questions 或 human decision pending 時輸出。

### Traceability
條列可追溯 id，例如 CR-*、URL-*、REQ-*、SM-*；去重即可。

### Meeting
條列 Round、Issue ID、Participants、Generated At。

# 輸出限制
- 只能輸出 Markdown。
- 不要輸出 H1。
- 不要使用 JSON 或程式碼區塊。
- 不要提到 prompt、schema、欄位規則或「根據輸入資料」。
"""

    def write_meeting_note(
        self,
        issue: Dict,
        conversation: List[Dict],
        resolution: Dict,
        round_num: int = 0,
        *,
        proposed_by: Optional[str] = None,
    ) -> str:
        participants = []
        proposer = (proposed_by if proposed_by is not None else issue.get("proposed_by"))
        proposer = (proposer or "").strip() or None
        if proposer:
            participants.append(proposer)
        for item in conversation or []:
            if not isinstance(item, dict):
                continue
            agent_name = str(item.get("agent") or "").strip()
            if agent_name:
                participants.append(agent_name)
        if not participants:
            participants = issue.get("participants") or []
        participants = list(dict.fromkeys(participants))

        md = f"# {issue.get('title', '')}\n\n"
        if proposer:
            md += f"- **Proposed by**: {proposer}\n"
        else:
            md += "- **Proposed by**: mediator\n"
        md += f"- **Participants**: {', '.join(participants) if participants else '（無參與者）'}\n"
        summary = resolution.get("summary", "")
        if summary:
            md += f"- **Summary**: {summary}\n"
        decision = resolution.get("decision", "")
        resolution_status = resolution.get("resolution_status", "")
        if decision:
            md += f"- **Decision**: {decision}\n"
        if resolution_status:
            label = "Recommendation status" if resolution_status == "pending_confirmation" else "Resolution"
            md += f"- **{label}**: {resolution_status}\n"

        if resolution.get("needs_human"):
            md += "- **Decision status**: pending human decision\n"
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
            md += "\n"
        agreed_points = resolution.get("agreed_points", []) or []
        unresolved_points = resolution.get("unresolved_points", []) or []
        affected_requirement_ids = resolution.get("affected_requirement_ids", []) or []
        if agreed_points:
            md += f"- **Agreed points**: {'; '.join(agreed_points)}\n"
        if unresolved_points:
            md += f"- **Unresolved points**: {'; '.join(unresolved_points)}\n"
        if affected_requirement_ids:
            md += f"- **Affected requirements**: {', '.join(affected_requirement_ids)}\n"
        if resolution.get("needs_human"):
            md += "- **Needs human**: true\n"
        md += "\n"

        def clean_for_mom(text: str) -> str:
            value = str(text or "").strip()
            if not value:
                return ""
            if not ((value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]"))):
                return value
            try:
                parsed = json.loads(value)
            except Exception:
                return value

            def list_lines(items: Any) -> str:
                rows = [str(item).strip() for item in (items or []) if str(item).strip()]
                return "\n".join(f"- {item}" for item in rows)

            if isinstance(parsed, dict):
                if isinstance(parsed.get("pair_reviews"), list):
                    lines = []
                    if parsed.get("review_summary"):
                        lines.append(str(parsed.get("review_summary")).strip())
                    for row in parsed.get("pair_reviews") or []:
                        if not isinstance(row, dict):
                            continue
                        title = str(row.get("id") or "").strip()
                        label = str(row.get("proposed_label") or row.get("label") or "").strip()
                        reason = str(row.get("reason") or "").strip()
                        item = " / ".join(part for part in (title, label) if part)
                        if reason:
                            item = f"{item}: {reason}" if item else reason
                        if item:
                            lines.append(f"- {item}")
                    return "\n".join(lines).strip()
                lines = []
                for key in ("summary", "decision", "proposal", "rationale", "reason", "text"):
                    item = parsed.get(key)
                    if isinstance(item, dict):
                        summary = str(item.get("summary") or "").strip()
                        rationale = str(item.get("rationale") or "").strip()
                        tradeoffs = list_lines(item.get("tradeoffs"))
                        if summary:
                            lines.append(summary)
                        if rationale:
                            lines.append(f"理由：{rationale}")
                        if tradeoffs:
                            lines.append("取捨：\n" + tradeoffs)
                    elif item not in (None, "", [], {}):
                        lines.append(str(item).strip())
                if lines:
                    return "\n".join(lines).strip()
            if isinstance(parsed, list):
                return list_lines(parsed)
            return value

        def table_cell(value: Any) -> str:
            if isinstance(value, list):
                text = ", ".join(str(item).strip() for item in value if str(item).strip())
            else:
                text = str(value or "").strip()
            return text.replace("|", "\\|").replace("\n", "<br>")

        def as_text_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        def render_list_line(prefix: str, values: Any) -> str:
            items = as_text_list(values)
            if not items:
                return ""
            return f"- {prefix}: {'; '.join(items)}"

        def render_requirements_markdown(rows: Any, reason: Any = None) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = ["#### Analysis", "", "**Requirements**", "", "| ID | Type | Requirement | Source |", "|---|---|---|---|"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                req_id = row.get("id", "")
                req_type = row.get("type", "")
                requirement = row.get("requirement") or row.get("description") or row.get("title") or ""
                source_ids = row.get("source_ids") or row.get("sources") or row.get("source") or []
                out.append(
                    f"| {table_cell(req_id)} | {table_cell(req_type)} | {table_cell(requirement)} | {table_cell(source_ids)} |"
                )

            criteria_lines = []
            risk_lines = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                req_id = str(row.get("id") or "").strip()
                criteria = as_text_list(row.get("acceptance_criteria"))
                if criteria:
                    criteria_lines.append(f"- {req_id}: {'; '.join(criteria)}")
                risks = as_text_list(row.get("risks"))
                assumptions = as_text_list(row.get("assumptions"))
                if risks:
                    risk_lines.append(f"- {req_id} risks: {'; '.join(risks)}")
                if assumptions:
                    risk_lines.append(f"- {req_id} assumptions: {'; '.join(assumptions)}")

            if criteria_lines:
                out.extend(["", "**Acceptance Criteria**", "", *criteria_lines])
            if risk_lines:
                out.extend(["", "**Risks / Assumptions**", "", *risk_lines])
            reason_text = str(reason or "").strip()
            if reason_text:
                out.extend(["", f"**Reason**: {reason_text}"])
            return "\n".join(out).strip()

        def render_user_requirements_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = ["**User Requirements**", "", "| ID | Requirement | Stakeholder | Source |", "|---|---|---|---|"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append(
                    f"| {table_cell(row.get('id'))} | {table_cell(row.get('text'))} | {table_cell(row.get('stakeholder'))} | {table_cell(row.get('source'))} |"
                )
            return "\n".join(out)

        def render_conflict_report_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = ["**Conflict Report**", "", "| ID | Type | Description | Recommendation |", "|---|---|---|---|"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = row.get("label") or row.get("type") or ""
                recommendation = row.get("recommended_resolution") or ""
                if not recommendation and isinstance(row.get("resolution_options"), list):
                    option_texts = []
                    for option in row.get("resolution_options") or []:
                        if isinstance(option, dict):
                            text = option.get("description") or option.get("recommendation") or ""
                            if text:
                                option_texts.append(str(text).strip())
                    recommendation = "; ".join(option_texts)
                out.append(
                    f"| {table_cell(row.get('id'))} | {table_cell(label)} | {table_cell(row.get('description'))} | {table_cell(recommendation)} |"
                )
            return "\n".join(out)

        def render_scope_markdown(scope: Any, reason: Any = None) -> str:
            if not isinstance(scope, dict) or not any(scope.get(key) for key in scope):
                return ""
            labels = {
                "in_scope": "In Scope",
                "out_of_scope": "Out of Scope",
                "assumptions": "Assumptions",
                "risks": "Risks",
            }
            out = ["**Scope**"]
            for key, label in labels.items():
                values = as_text_list(scope.get(key))
                if values:
                    out.extend(["", f"{label}", *[f"- {value}" for value in values]])
            reason_text = str(reason or "").strip()
            if reason_text:
                out.extend(["", f"**Reason**: {reason_text}"])
            return "\n".join(out)

        def render_model_consistency_markdown(report: Any) -> str:
            if not isinstance(report, dict) or not report:
                return ""
            out = ["**Model Consistency**"]
            summary_text = str(report.get("consistency_summary") or report.get("impact_summary") or "").strip()
            if summary_text:
                out.extend(["", summary_text])
            gaps = as_text_list(report.get("gaps"))
            if gaps:
                out.extend(["", "Gaps", *[f"- {gap}" for gap in gaps]])
            targets = report.get("model_targets")
            if isinstance(targets, list) and targets:
                out.extend(["", "| Operation | Type | Name | Reason |", "|---|---|---|---|"])
                for target in targets:
                    if not isinstance(target, dict):
                        continue
                    out.append(
                        f"| {table_cell(target.get('operation'))} | {table_cell(target.get('type'))} | {table_cell(target.get('name'))} | {table_cell(target.get('reason'))} |"
                    )
            return "\n".join(out)

        def render_analysis_markdown(artifacts: Dict[str, Any]) -> str:
            parts = []
            user_requirements = render_user_requirements_markdown(artifacts.get("URL"))
            if user_requirements:
                parts.append(user_requirements)
            conflict_report = render_conflict_report_markdown(artifacts.get("conflict_report"))
            if conflict_report:
                parts.append(conflict_report)
            scope = render_scope_markdown(artifacts.get("scope"), artifacts.get("scope_reason"))
            if scope:
                parts.append(scope)
            model_report = render_model_consistency_markdown(artifacts.get("model_consistency_report"))
            if model_report:
                parts.append(model_report)
            reason = str(artifacts.get("requirement_reason") or "").strip()
            if reason and not artifacts.get("REQ"):
                parts.append(f"**Reason**: {reason}")
            if not parts:
                return ""
            return "#### Analysis\n\n" + "\n\n".join(parts)

        def render_feedback_markdown(feedback: Any) -> str:
            if not isinstance(feedback, dict) or not feedback:
                return ""
            labels = {
                "findings": "Findings",
                "constraints": "Constraints",
                "risks": "Risks",
                "recommendations": "Recommendations",
            }
            parts = []
            for key, label in labels.items():
                rows = feedback.get(key)
                if not isinstance(rows, list) or not rows:
                    continue
                lines = [f"**{label}**"]
                for row in rows:
                    if isinstance(row, dict):
                        text = str(row.get("text") or "").strip()
                        related = table_cell(row.get("related_requirement_ids") or row.get("related_ids") or [])
                        source = str(row.get("source") or "").strip()
                        details = []
                        if related:
                            details.append(f"Related: {related}")
                        if source:
                            details.append(f"Source: {source}")
                        suffix = f" ({'; '.join(details)})" if details else ""
                        if text:
                            lines.append(f"- {text}{suffix}")
                    elif str(row).strip():
                        lines.append(f"- {str(row).strip()}")
                if len(lines) > 1:
                    parts.append("\n".join(lines))
            sources = as_text_list(feedback.get("sources"))
            if sources:
                parts.append("**Sources**\n" + "\n".join(f"- {source}" for source in sources))
            if not parts:
                return ""
            return "#### Feedback\n\n" + "\n\n".join(parts)

        def model_display_type(model: Dict[str, Any]) -> str:
            raw_type = str(model.get("display_type") or model.get("type") or "").strip()
            labels = {
                "context_diagram": "Context Diagram",
                "use_case_diagram": "Use Case Diagram",
                "activity_diagram": "Activity Diagram",
                "sequence_diagram": "Sequence Diagram",
                "state_machine": "State Machine",
                "class_diagram": "Class Diagram",
            }
            return labels.get(raw_type, raw_type or "System Model")

        def render_use_case_text(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                actor = str(row.get("actor") or row.get("role") or "General").strip() or "General"
                grouped.setdefault(actor, []).append(row)
            if not grouped:
                return ""
            out = ["##### Use Case Text"]
            roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
            for index, (actor, actor_rows) in enumerate(grouped.items(), 1):
                label = roman[index - 1] if index <= len(roman) else str(index)
                out.append(f"###### {label}. {actor} Use Cases")
                out.append("| ID | Use Case | Purpose | Interface |")
                out.append("|---|---|---|---|")
                for item in actor_rows:
                    use_case_id = str(item.get("id") or item.get("use_case_id") or "").strip()
                    name = str(item.get("use_case") or item.get("name") or item.get("title") or "").strip()
                    purpose = str(item.get("purpose") or item.get("description") or "").strip()
                    interface = str(item.get("interface") or "").strip()
                    out.append(f"| {use_case_id} | {name} | {purpose} | {interface} |")
            return "\n".join(out)

        def render_system_models_markdown(system_models: Any) -> str:
            if not isinstance(system_models, list) or not system_models:
                return ""
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for model in system_models:
                if isinstance(model, dict):
                    groups.setdefault(model_display_type(model), []).append(model)
            if not groups:
                return ""
            sections: List[str] = []
            for display_type, models in groups.items():
                single = len(models) == 1
                for index, model in enumerate(models, 1):
                    name = str(model.get("name") or "").strip()
                    if single and model.get("type") not in {"context_diagram", "use_case_diagram"} and name:
                        heading = f"##### {display_type} -- {name}"
                    elif single:
                        heading = f"##### {display_type}"
                    else:
                        heading = f"##### {display_type}\n\n{chr(96 + index)}. {name or model.get('id') or 'Model'}"
                    parts = [heading]
                    image_path = str(model.get("image_path") or "").strip()
                    plantuml = str(model.get("plantuml") or "").strip()
                    if image_path:
                        alt = name or display_type
                        parts.append(f"![{alt}]({image_path})")
                    elif plantuml:
                        parts.append("```plantuml\n" + plantuml + "\n```")
                    description = str(model.get("description") or "").strip()
                    if description and model.get("type") != "use_case_diagram":
                        parts.append(description)
                    use_case_text = render_use_case_text(model.get("text") or model.get("use_case_text"))
                    if use_case_text:
                        parts.append(use_case_text)
                    sections.append("\n\n".join(part for part in parts if part))
            return "\n\n".join(sections)

        def render_action_outputs(entry: Dict[str, Any]) -> str:
            sections = []
            artifacts = entry.get("artifacts") if isinstance(entry.get("artifacts"), dict) else {}
            req_analysis = render_requirements_markdown(
                artifacts.get("REQ"),
                artifacts.get("requirement_reason"),
            )
            if req_analysis:
                sections.append(req_analysis)
            analysis = render_analysis_markdown(artifacts)
            if analysis:
                if req_analysis and analysis.startswith("#### Analysis\n\n"):
                    analysis = analysis.replace("#### Analysis\n\n", "", 1)
                sections.append(analysis)
            feedback = artifacts.get("feedback")
            rendered_feedback = render_feedback_markdown(feedback)
            if rendered_feedback:
                sections.append(rendered_feedback)
            system_models = artifacts.get("system_models")
            rendered_models = render_system_models_markdown(system_models)
            if rendered_models:
                sections.append("#### System Model\n\n" + rendered_models)
            return "\n\n".join(sections)

        main_records = [c for c in conversation if not c.get("is_reply", False)]
        md += "## 會議記錄\n\n"
        if not main_records:
            md += "（本議題無人發言）\n\n"
        else:
            for c in main_records:
                agent = c.get("agent", "?")
                resp = c.get("response", {})
                text = clean_for_mom(resp.get("text", ""))
                md += f"### {agent}\n\n"
                md += f"{text or '（本發言無可讀內容）'}\n\n"
                action_outputs = render_action_outputs(c)
                if action_outputs:
                    md += f"{action_outputs}\n\n"

        question_pairs: List[Dict[str, Any]] = []
        question_index: Dict[tuple[str, str, str], Dict[str, Any]] = {}
        for c in conversation:
            if c.get("is_reply"):
                continue
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            from_agent = str(c.get("agent") or "?").strip() or "?"
            for question in resp.get("open_questions", []) or []:
                q = question if isinstance(question, dict) else {"question": str(question)}
                question_text = str(q.get("question") or "").strip()
                if not question_text:
                    continue
                to_agent = str(q.get("to") or "user").strip() or "user"
                key = (from_agent, to_agent, question_text)
                if key in question_index:
                    continue
                pair = {
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "question": question_text,
                    "answer_agent": "",
                    "answer": "",
                }
                question_index[key] = pair
                question_pairs.append(pair)
        for c in conversation:
            if not c.get("is_reply"):
                continue
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            question_text = str(resp.get("reply_to_question") or "").strip()
            from_agent = str(resp.get("reply_to_agent") or "?").strip() or "?"
            answer_agent = str(c.get("agent") or "?").strip() or "?"
            answer = clean_for_mom(resp.get("text", ""))
            if not question_text and not answer:
                continue
            matched = None
            for pair in question_pairs:
                if (
                    pair.get("from_agent") == from_agent
                    and pair.get("question") == question_text
                    and not pair.get("answer")
                ):
                    matched = pair
                    break
            if matched is None:
                matched = {
                    "from_agent": from_agent,
                    "to_agent": answer_agent,
                    "question": question_text,
                    "answer_agent": answer_agent,
                    "answer": "",
                }
                question_pairs.append(matched)
            matched["answer_agent"] = answer_agent
            matched["answer"] = answer
        if question_pairs:
            md += "## Open Questions\n\n"
            for i, pair in enumerate(question_pairs):
                if i > 0:
                    md += "\n---\n\n"
                from_agent = pair.get("from_agent") or "?"
                to_agent = pair.get("to_agent") or "?"
                question = pair.get("question") or ""
                answer_agent = pair.get("answer_agent") or to_agent
                answer = str(pair.get("answer") or "").strip()
                md += f"**{from_agent}**: {question or '（未記錄問題內容）'}\n\n"
                if answer:
                    md += f"**{answer_agent}**: {answer}\n\n"
                else:
                    md += f"**Status**: 未回答，待 {to_agent} 回覆\n\n"

        return md

    def build_design_rationale_entry_context(
        self,
        issue: Dict,
        conversation: List[Dict],
        resolution: Dict,
        issue_open_questions: List[Dict],
        round_num: int,
    ) -> Dict[str, Any]:
        """將單一議題討論結果整理為 Design Rationale 單筆上下文。"""
        main_records = [c for c in conversation if not c.get("is_reply", False)]
        texts = []
        action_artifacts = []
        for c in main_records:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            st = (resp.get("text") or "").strip()
            if st:
                texts.append({"agent": c.get("agent", "?"), "text": st})
            artifacts = c.get("artifacts") if isinstance(c.get("artifacts"), dict) else {}
            if artifacts:
                action_artifacts.append(
                    {
                        "agent": c.get("agent", "?"),
                        "round_index": c.get("round_index"),
                        "actions": c.get("actions", []),
                        "artifacts": artifacts,
                    }
                )

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
                "participants": issue.get("participants", []),
                "trace": issue.get("trace", {}),
            },
            "discussion": {
                "texts": texts,
                "open_issues": unresolved_oq,
                "action_artifacts": action_artifacts,
            },
            "resolution": {
                "resolution_status": resolution.get("resolution_status", ""),
                "summary": resolution.get("summary", ""),
                "decision": resolution.get("decision", ""),
                "agreed_points": resolution.get("agreed_points", []),
                "unresolved_points": resolution.get("unresolved_points", []),
                "new_open_questions": resolution.get("new_open_questions", []),
                "affected_conflict_ids": resolution.get("affected_conflict_ids", []),
                "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
                "url_updates": resolution.get("url_updates", []),
                "artifact_updates": resolution.get("artifact_updates", {}),
                "needs_human": resolution.get("needs_human", False),
                "options": resolution.get("options", []),
                "recommendation": resolution.get("recommendation", {}),
            },
            "traceability_ids": self.extract_traceability_ids(issue, conversation, resolution),
            "metadata": {
                "round": round_num,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def write_rationale_entry(self, issue_context: Dict[str, Any]) -> str:
        """Use Mediator prompt to render one Design Rationale entry."""
        def clean_entry(raw_text: Any) -> str:
            value = str(raw_text or "").strip()
            if value.startswith("```"):
                value = re.sub(r"^```(?:markdown|md)?\s*", "", value)
                value = re.sub(r"\s*```$", "", value).strip()
            return value

        def validate_entry(value: str) -> None:
            if not value.startswith("## "):
                raise ValueError("design rationale entry must start with '## '")
            if issue_id and issue_id not in value.splitlines()[0]:
                raise ValueError(f"design rationale entry heading must include issue id: {issue_id}")
            if "待補" in value:
                raise ValueError("design rationale entry must not contain 待補")

        issue_id = str((issue_context.get("issue") or {}).get("id") or "").strip()
        prompt = self.design_rationale_entry_prompt(issue_context)
        raw = self.model.chat(
            self.build_direct_messages(prompt),
            action="mediator.design_rationale_entry",
        )
        entry = clean_entry(raw)
        try:
            validate_entry(entry)
        except ValueError as first_error:
            repair_prompt = (
                prompt
                + "\n\n# 上一次輸出不合格\n"
                + f"- 錯誤：{first_error}\n"
                + "- 請重新輸出完整單筆 entry。\n"
                + "- 若某節沒有內容，直接省略該節；不要寫「待補」、空值、占位文字或說明。\n"
            )
            raw = self.model.chat(
                self.build_direct_messages(repair_prompt),
                action="mediator.design_rationale_entry.repair",
            )
            entry = clean_entry(raw)
            validate_entry(entry)
        return entry

    def write_rationale_record(self, issue_context: Dict[str, Any]) -> str:
        """初次建立 design_rationale.md。"""
        entry = self.write_rationale_entry(issue_context)
        return "# Design Rationale\n\n" + entry

    def update_rationale_record(self, existing_md: str, issue_context: Dict[str, Any]) -> str:
        """既有 design_rationale.md 追加單一議題章節。"""
        base = (existing_md or "").rstrip()
        entry = self.write_rationale_entry(issue_context)
        if not base:
            return self.write_rationale_record(issue_context)
        return f"{base}\n\n---\n\n{entry}"
