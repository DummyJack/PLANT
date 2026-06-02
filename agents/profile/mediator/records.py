# Mediator records: meeting markdown and design rationale.
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import conflict_entries_count

from .validation import ISSUE_CATEGORY_LABEL, trace_artifact_ids, trace_proposal_ids


class MediatorRecords:
    @staticmethod
    def allowed_design_source_id(value: Any) -> bool:
        text = str(value or "").strip()
        return bool(re.fullmatch(r"(?:REQ-\d+|URL-\d+|CR-\d+|PAIR-\d+|MULTIPLE-\d+|SM-\d+)", text))

    @classmethod
    def extract_source_ids(cls, issue: Dict, conversation: List[Dict], resolution: Dict) -> List[str]:
        """從 trace 與討論/決議文字抓出 DR 來源 id。"""
        ids = set()
        for sid in trace_artifact_ids(issue):
            if isinstance(sid, str) and sid.strip() and cls.allowed_design_source_id(sid):
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
        for m in re.findall(r"\b(?:REQ-\d+|URL-\d+|CR-\d+|PAIR-\d+|MULTIPLE-\d+|SM-\d+)\b", blob):
            if cls.allowed_design_source_id(m):
                ids.add(m)
        return sorted(ids)

    @staticmethod
    def _append_unique(target: Dict[str, List[str]], key: str, values: Any) -> None:
        rows = target.setdefault(key, [])
        raw_values = values if isinstance(values, list) else [values]
        for value in raw_values:
            text = str(value or "").strip()
            if text and text not in rows:
                rows.append(text)

    @classmethod
    def design_changed_artifacts(
        cls,
        issue: Dict,
        action_artifacts: List[Dict[str, Any]],
        resolution: Dict,
    ) -> Dict[str, List[str]]:
        changed: Dict[str, List[str]] = {}
        meeting_id = str(issue.get("meeting_id") or "").strip()
        cls._append_unique(changed, "meeting", meeting_id)
        cls._append_unique(changed, "URL", [
            req_id
            for update in (resolution.get("url_updates") or [])
            if isinstance(update, dict)
            for req_id in (update.get("ids") or [])
        ])
        cls._append_unique(changed, "REQ", resolution.get("affected_requirement_ids") or [])
        cls._append_unique(changed, "conflict_report", resolution.get("affected_conflict_ids") or [])
        artifact_updates = resolution.get("artifact_updates") if isinstance(resolution.get("artifact_updates"), dict) else {}
        for key, source in (
            ("URL", "URL"),
            ("REQ", "REQ"),
            ("conflict_report", "conflict_report"),
            ("system_models", "system_models"),
        ):
            row = artifact_updates.get(source) if isinstance(artifact_updates.get(source), dict) else {}
            cls._append_unique(changed, key, row.get("ids") or [])
        for artifact_row in action_artifacts:
            artifacts = artifact_row.get("artifacts") if isinstance(artifact_row.get("artifacts"), dict) else {}
            for req in artifacts.get("REQ") or []:
                if isinstance(req, dict):
                    cls._append_unique(changed, "REQ", req.get("id"))
            for req in artifacts.get("URL") or []:
                if isinstance(req, dict):
                    cls._append_unique(changed, "URL", req.get("id"))
            for conflict in artifacts.get("conflict_report") or []:
                if isinstance(conflict, dict):
                    cls._append_unique(changed, "conflict_report", conflict.get("id"))
            for model in artifacts.get("system_models") or []:
                if isinstance(model, dict):
                    cls._append_unique(changed, "system_models", model.get("id") or model.get("name"))
            feedback = artifacts.get("feedback") if isinstance(artifacts.get("feedback"), dict) else {}
            if feedback:
                cls._append_unique(
                    changed,
                    "feedback",
                    [
                        key
                        for key in ("findings", "constraints", "risks", "recommendations")
                        if feedback.get(key)
                    ],
                )
        return {key: values for key, values in changed.items() if values}

    @staticmethod
    def artifact_change_summary(changed_artifacts: Dict[str, List[str]], resolution: Dict) -> Dict[str, str]:
        out: Dict[str, str] = {}
        labels = {
            "URL": "User Requirements",
            "REQ": "REQ-*",
            "conflict_report": "conflict report",
            "system_models": "system models",
            "feedback": "feedback",
            "open_questions": "open questions",
        }
        for key, values in changed_artifacts.items():
            if key == "meeting":
                continue
            label = labels.get(key, key)
            out[key] = f"{label} affected: {', '.join(values)}"
        decision = str(resolution.get("decision") or "").strip()
        summary = str(resolution.get("summary") or "").strip()
        if summary:
            out["resolution_summary"] = summary
        if decision:
            out["resolution_decision"] = decision
        return out

    @staticmethod
    def quality_impact_hints(issue: Dict, resolution: Dict, changed_artifacts: Dict[str, List[str]]) -> List[str]:
        category = str(issue.get("category") or "").strip()
        hints: List[str] = []
        if category == "clarify_requirement":
            hints.extend(["提升需求完整性", "提升可測試性", "強化來源追蹤"])
        elif category == "define_boundary":
            hints.extend(["釐清系統邊界", "降低責任歸屬不清風險"])
        elif category == "tradeoff":
            hints.extend(["明確取捨依據", "降低方案選擇不一致風險"])
        elif category == "align_model":
            hints.extend(["提升模型與需求一致性", "改善流程、狀態或資料邊界可追蹤性"])
        elif category == "resolve_conflict":
            hints.extend(["提升需求一致性", "降低衝突需求造成的驗收與責任風險"])
        if changed_artifacts.get("REQ"):
            hints.append("改善 REQ-* 可交付性")
        if changed_artifacts.get("conflict_report"):
            hints.append("收斂需求衝突")
        if changed_artifacts.get("system_models"):
            hints.append("強化系統模型對需求的支撐")
        if resolution.get("needs_human"):
            hints.append("保留人類裁決以避免代理人逕自定案")
        return list(dict.fromkeys(hints))

    @staticmethod
    def risk_if_not_decided(issue: Dict, resolution: Dict) -> str:
        unresolved = [
            str(value).strip()
            for value in (resolution.get("unresolved_points") or [])
            if str(value).strip()
        ]
        if unresolved:
            return "若不處理，仍未解的問題會阻礙需求定稿：" + "；".join(unresolved[:3])
        category = str(issue.get("category") or "").strip()
        if category == "resolve_conflict":
            return "若不先處理需求衝突，後續 REQ 與驗收標準可能建立在互相矛盾的 User Requirements 上。"
        if category == "clarify_requirement":
            return "若不釐清並正式化需求，後續 SRS 可能缺少可測試、可追蹤的正式需求條目。"
        if category == "define_boundary":
            return "若不界定責任邊界，需求可能混合系統、人工與外部服務責任，造成實作與驗收爭議。"
        if category == "tradeoff":
            return "若不形成取捨決策，後續設計可能在多個方案間搖擺，造成需求不一致。"
        if category == "align_model":
            return "若不對齊模型與需求，流程、狀態、actor 或資料邊界可能在 SRS 與設計模型間不一致。"
        return ""

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
- 這是給人閱讀的 Design Rationale，不是 MoM，也不是 JSON 摘要。
- 只記錄本議題形成的設計決策、採用理由、影響與來源；不要貼會議逐字稿。
- 不得編造 context、alternative、impact、open issue 或不存在的理由。
- 不要寫成會議摘要語氣，例如「討論過程中」「各方表示」「會議中」。
- Context 寫決策背景；Decision 寫採用結果；Rationale 寫採用理由；Impact 寫此決策造成的需求、模型、草稿、衝突報告或後續工作影響，並說明此決策為什麼重要，例如改善哪些需求完整性、一致性、可測試性、可追溯性、系統邊界、風險降低、模型對齊或 SRS 可交付性；不要只列 artifact 名稱。
- Decision 與 Impact 優先使用 changed_artifacts、artifact_change_summary、quality_impact_hints、risk_if_not_decided；discussion.text 只作補充脈絡，不得取代結構化變更資料。
- Source 只寫 artifact 來源 id，且只能使用 REQ-*、URL-*、CR-*、PAIR-*、MULTIPLE-*、SM-*；不要把 meeting id、findings、risks、recommendations、T-* 或一般文字當 Source。
- 標題第一個 ID 必須使用 issue.meeting_id，例如 R2-M1；不得用 T-* 取代 meeting_id。
- 不要輸出「待補」。
- 核心章節固定使用 Context、Decision、Rationale、Impact、Source；Alternatives 與 Open Issues 只有真的有資料時才輸出。

# entry 格式
請輸出 Markdown，且只能輸出單筆 entry：

## {{meeting_id}} {{issue_title}}

### Context
用 1-3 句說明需求問題、衝突、邊界或決策背景。

### Decision
條列最後採用的可執行決策；若包含多個 CR/REQ/URL/SM，請拆成多條。不得只寫「採用現有內容」「完成整理」或抽象方法名；需說明相關 artifact 要保留、修正、移除、新增或如何反映。

### Rationale
條列為什麼採用此決策；需根據 resolution summary、discussion、recommendation 或 agreed_points，不要重複 Decision。

### Alternatives
只在 options 或 discussion 中真的有方案比較時輸出；列出未採用方案與原因。

### Impact
條列此決策造成的實際影響，並說明為什麼重要。必須盡量使用 Artifact change、Requirement quality、Risk if not decided 三種角度：哪些 REQ/URL/CR/SM/draft 被影響；改善了哪些完整性/一致性/可測試性/可追溯性/邊界清楚度；若不做此決策會有什麼風險。不要只列 artifact 名稱。

### Open Issues
只在仍有 unresolved_points、open questions 或 human decision pending 時輸出。

### Source
條列本決策依據的 artifact 來源 id，例如 CR-*、URL-*、REQ-*、SM-*；去重即可。不要稱為 Traceability，不要列 meeting id。

# 輸出限制
- 只能輸出 Markdown。
- 不要輸出 H1、JSON、程式碼區塊、prompt/schema 說明。
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
        status = resolution.get("status", "")
        if decision:
            md += f"- **Decision**: {decision}\n"
        if status:
            md += f"- **Resolution**: {status}\n"

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

        def reason_lines(value: Any) -> List[str]:
            text = str(value or "").strip()
            if not text:
                return []
            parts = [
                part.strip(" ；;")
                for part in re.split(r"[；;]\s*", text)
                if part.strip(" ；;")
            ]
            return parts or [text]

        def render_requirements_markdown(rows: Any, reason: Any = None) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = [
                "#### Analysis",
                "",
                "| ID | Type | Requirement | Acceptance Criteria | Risks |",
                "|---|---|---|---|---|",
            ]
            display_rows = [row for row in rows if isinstance(row, dict)]
            for row in display_rows:
                if not isinstance(row, dict):
                    continue
                req_id = row.get("id", "")
                req_type = row.get("type", "")
                requirement = row.get("description") or row.get("title") or ""
                acceptance = as_text_list(row.get("acceptance_criteria"))
                risks = as_text_list(row.get("risks"))
                out.append(
                    "| "
                    + " | ".join(
                        table_cell(value)
                        for value in (
                            req_id,
                            req_type,
                            requirement,
                            acceptance,
                            risks,
                        )
                    )
                    + " |"
                )
            reason_text = str(reason or "").strip()
            if reason_text:
                lines = reason_lines(reason_text)
                out.extend(["", "**Reason**:"])
                out.extend(f"- {line}" for line in lines)
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

        def labeled_answers(text: Any) -> Dict[str, str]:
            source = str(text or "").strip()
            if not source or "【" not in source:
                return {}
            matches = list(re.finditer(r"(?:^|\n)\s*【([^】]+)】\s*", source))
            if not matches:
                return {}
            parts: Dict[str, str] = {}
            for idx, match in enumerate(matches):
                name = str(match.group(1) or "").strip()
                start = match.end()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(source)
                body = source[start:end].strip()
                body = re.sub(r"^\s*[-—]+\s*", "", body).strip()
                if name and body:
                    parts[name] = body
            return parts

        def answer_lines(pair: Dict[str, Any]) -> List[tuple[str, str]]:
            answer = str(pair.get("answer") or "").strip()
            if not answer:
                return []
            split = labeled_answers(answer)
            if split:
                return [(name, text) for name, text in split.items() if text]
            answer_agent = str(pair.get("answer_agent") or pair.get("to_agent") or "?").strip() or "?"
            if answer_agent == "user" and pair.get("to_stakeholder"):
                answer_agent = str(pair.get("to_stakeholder") or answer_agent).strip()
            return [(answer_agent, answer)]

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
                if to_agent == from_agent:
                    continue
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
                if to_agent not in {"user", "analyst", "expert", "modeler", "mediator"}:
                    pair["to_stakeholder"] = to_agent
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
                    and (
                        pair.get("to_agent") == answer_agent
                        or (answer_agent == "user" and pair.get("to_stakeholder"))
                        or not pair.get("answer_agent")
                    )
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
                answer = str(pair.get("answer") or "").strip()
                md += f"**{from_agent}**: {question or '（未記錄問題內容）'}\n\n"
                if answer:
                    for name, text in answer_lines(pair):
                        md += f"**{name}**: {text}\n\n"
                else:
                    md += f"未回答，待 {to_agent} 回覆\n\n"

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

        issue_meeting_id = str(issue.get("meeting_id") or "").strip()
        issue_context = issue.get("issue_context") if isinstance(issue.get("issue_context"), dict) else {}
        if not issue_meeting_id:
            issue_meeting_id = str(issue_context.get("meeting_id") or "").strip()

        changed_artifacts = self.design_changed_artifacts(issue, action_artifacts, resolution)
        artifact_change_summary = self.artifact_change_summary(changed_artifacts, resolution)
        quality_hints = self.quality_impact_hints(issue, resolution, changed_artifacts)
        risk_text = self.risk_if_not_decided(issue, resolution)

        return {
            "issue": {
                "id": issue.get("id", ""),
                "meeting_id": issue_meeting_id,
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "category": issue.get("category", ""),
                "category_label": ISSUE_CATEGORY_LABEL.get(issue.get("category", ""), issue.get("category", "")),
                "discussion_mode": issue.get("discussion_mode", "sequential"),
                "participants": issue.get("participants", []),
                "trace": {"artifact_ids": trace_artifact_ids(issue)},
            },
            "discussion": {
                "texts": texts,
                "open_issues": unresolved_oq,
                "action_artifacts": action_artifacts,
            },
            "resolution": {
                "status": resolution.get("status", ""),
                "summary": resolution.get("summary", ""),
                "decision": resolution.get("decision", ""),
                "agreed_points": resolution.get("agreed_points", []),
                "unresolved_points": resolution.get("unresolved_points", []),
                "new_open_questions": resolution.get("new_open_questions", []),
                "affected_conflict_ids": resolution.get("affected_conflict_ids", []),
                "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
                "requirement_changes": resolution.get("requirement_changes", []),
                "model_changes": resolution.get("model_changes", []),
                "open_questions": resolution.get("open_questions", []),
                "follow_up_actions": resolution.get("follow_up_actions", []),
                "url_updates": resolution.get("url_updates", []),
                "artifact_updates": resolution.get("artifact_updates", {}),
                "needs_human": resolution.get("needs_human", False),
                "options": resolution.get("options", []),
                "recommendation": resolution.get("recommendation", {}),
            },
            "changed_artifacts": changed_artifacts,
            "artifact_change_summary": artifact_change_summary,
            "quality_impact_hints": quality_hints,
            "risk_if_not_decided": risk_text,
            "source": self.extract_source_ids(issue, conversation, resolution),
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
            value = remove_placeholder_sections(value)
            value = normalize_entry_heading(value)
            return filter_source_section(value)

        def normalize_entry_heading(value: str) -> str:
            if not meeting_id:
                return value
            lines = str(value or "").splitlines()
            if not lines:
                return value
            first = lines[0].strip()
            if not first.startswith("## "):
                return value
            if meeting_id in first:
                return value
            title = str((issue_context.get("issue") or {}).get("title") or "").strip()
            heading_title = re.sub(r"^##\s+", "", first).strip()
            heading_title = re.sub(r"\bT-\d+\b", "", heading_title).strip(" -｜|")
            if title:
                heading_title = title
            lines[0] = f"## {meeting_id} {heading_title}".rstrip()
            return "\n".join(lines).strip()

        def filter_source_section(value: str) -> str:
            lines = str(value or "").splitlines()
            out: List[str] = []
            in_source = False
            kept_source = False
            for line in lines:
                if line.startswith("### "):
                    if in_source and not kept_source:
                        while out and not out[-1].strip():
                            out.pop()
                        if out and out[-1].strip() == "### Source":
                            out.pop()
                    in_source = line.strip() == "### Source"
                    kept_source = False
                    out.append(line)
                    continue
                if in_source:
                    candidate = line.strip().lstrip("-").strip()
                    if not candidate:
                        out.append(line)
                        continue
                    if MediatorRecords.allowed_design_source_id(candidate):
                        out.append(f"- {candidate}")
                        kept_source = True
                        continue
                    ids = re.findall(r"\b(?:REQ-\d+|URL-\d+|CR-\d+|PAIR-\d+|MULTIPLE-\d+|SM-\d+)\b", candidate)
                    for source_id in ids:
                        if MediatorRecords.allowed_design_source_id(source_id):
                            out.append(f"- {source_id}")
                            kept_source = True
                    continue
                out.append(line)
            if in_source and not kept_source:
                while out and not out[-1].strip():
                    out.pop()
                if out and out[-1].strip() == "### Source":
                    out.pop()
            return "\n".join(out).strip()

        def remove_placeholder_sections(value: str) -> str:
            lines = [line.rstrip() for line in str(value or "").splitlines()]
            cleaned: List[str] = []
            skip_section = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("### "):
                    skip_section = stripped == "### Meeting"
                    if skip_section:
                        continue
                if skip_section:
                    continue
                if "待補" in stripped:
                    continue
                if stripped in {"無", "無。", "None", "N/A", "-", "- 無", "- 無。"}:
                    continue
                cleaned.append(line)

            sections: List[List[str]] = []
            current: List[str] = []
            for line in cleaned:
                if line.startswith("### "):
                    if current:
                        sections.append(current)
                    current = [line]
                else:
                    current.append(line)
            if current:
                sections.append(current)

            kept: List[str] = []
            for section in sections:
                if section and section[0].startswith("### "):
                    body = [line.strip() for line in section[1:] if line.strip()]
                    if not body:
                        continue
                kept.extend(section)
            return "\n".join(kept).strip()

        def validate_entry(value: str) -> None:
            if not value.startswith("## "):
                raise ValueError("design rationale entry must start with '## '")
            if value.startswith("# "):
                raise ValueError("design rationale entry must not include H1")
            if "```" in value:
                raise ValueError("design rationale entry must not include code fences")
            expected_id = meeting_id
            heading = value.splitlines()[0]
            if expected_id:
                if expected_id not in heading:
                    raise ValueError(f"design rationale entry heading must include meeting id: {expected_id}")
                if re.search(r"\bT-\d+\b", heading):
                    raise ValueError("design rationale entry heading should not use T-* issue id")
            if "待補" in value:
                raise ValueError("design rationale entry must not contain 待補")
            source_match = re.search(r"(?ms)^### Source\s*\n(?P<body>.*?)(?=^###\s+|\Z)", value)
            if source_match:
                source_ids = re.findall(
                    r"\b(?:REQ-\d+|URL-\d+|CR-\d+|PAIR-\d+|MULTIPLE-\d+|SM-\d+)\b",
                    source_match.group("body"),
                )
                invalid_lines = [
                    line.strip()
                    for line in source_match.group("body").splitlines()
                    if line.strip()
                    and not re.search(
                        r"\b(?:REQ-\d+|URL-\d+|CR-\d+|PAIR-\d+|MULTIPLE-\d+|SM-\d+)\b",
                        line,
                    )
                ]
                if invalid_lines or not source_ids:
                    raise ValueError("design rationale Source must contain only valid source ids")

        issue_id = str((issue_context.get("issue") or {}).get("id") or "").strip()
        meeting_id = str((issue_context.get("issue") or {}).get("meeting_id") or "").strip()
        if not meeting_id:
            raise ValueError(f"design rationale context missing meeting_id for issue: {issue_id or 'unknown'}")
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
