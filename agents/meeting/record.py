# Handles meeting execution, response collection, records, and issue state.
import json
import re
from typing import Any, Dict, List, Optional

# Defines MediatorRecords class for this module workflow.
class MediatorRecords:
    @staticmethod
    # Defines clean repeated text function for this module workflow.
    def clean_repeated_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        for sep in ("，", "；", ";", "。"):
            parts = [part.strip() for part in text.split(sep) if part.strip()]
            if len(parts) < 2:
                continue
            cleaned: List[str] = []
            for part in parts:
                if part not in cleaned:
                    cleaned.append(part)
            if len(cleaned) != len(parts):
                text = sep.join(cleaned)
                if value and str(value).strip().endswith(sep):
                    text += sep
        half = len(text) // 2
        if half > 12 and len(text) % 2 == 0 and text[:half].strip("，；;。 ") == text[half:].strip("，；;。 "):
            text = text[:half].strip("，；;。 ")
        return text.strip()

    @staticmethod
    # Defines valid mom artifact id function for this module workflow.
    def valid_mom_artifact_id(value: Any, prefixes: tuple[str, ...]) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
        return bool(re.fullmatch(rf"(?:{prefix_pattern})-\d+", text))

    @classmethod
    # Defines clean id list function for this module workflow.
    def clean_id_list(cls, values: Any, prefixes: tuple[str, ...]) -> List[str]:
        rows = values if isinstance(values, list) else [values]
        out: List[str] = []
        for value in rows:
            text = str(value or "").strip()
            if cls.valid_mom_artifact_id(text, prefixes) and text not in out:
                out.append(text)
        return out

    @classmethod
    # Defines clean mom question function for this module workflow.
    def clean_mom_question(cls, value: Any) -> str:
        text = cls.clean_repeated_text(value)
        if not text:
            return ""
        return text

    @staticmethod
    # Defines natural artifact id sort key for this module workflow.
    def artifact_id_sort_key(value: Any) -> tuple[str, int, str]:
        text = str(value or "").strip()
        match = re.fullmatch(r"([A-Za-z]+)-(\d+)", text)
        if not match:
            return (text, 999999, text)
        return (match.group(1).upper(), int(match.group(2)), text)

    @classmethod
    # Defines normalized issue title function for this module workflow.
    def normalized_issue_title(
        cls,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> str:
        original = cls.clean_repeated_text(issue.get("title", ""))
        category = str(issue.get("category") or "").strip()
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        artifact_ids = cls.clean_id_list(trace.get("artifact_ids"), ("REQ", "URL", "SM", "OQ"))
        req_ids = [rid for rid in artifact_ids if rid.startswith("REQ-")]
        model_ids = [rid for rid in artifact_ids if rid.startswith("SM-")]
        oq_ids = [rid for rid in artifact_ids if rid.startswith("OQ-")]

        output_req_ids: List[str] = []
        output_model_ids: List[str] = []
        for c in conversation or []:
            if not isinstance(c, dict) or c.get("is_reply"):
                continue
            resp = c.get("response") if isinstance(c.get("response"), dict) else {}
            action_results = c.get("issue_action_results")
            if not isinstance(action_results, list):
                action_results = resp.get("issue_action_results")
            for result in action_results if isinstance(action_results, list) else []:
                if not isinstance(result, dict):
                    continue
                for row in result.get("REQ") or []:
                    if isinstance(row, dict):
                        req_id = str(row.get("id") or "").strip()
                        if cls.valid_mom_artifact_id(req_id, ("REQ",)):
                            output_req_ids.append(req_id)
                for row in result.get("system_models") or []:
                    if isinstance(row, dict):
                        model_id = str(row.get("id") or "").strip()
                        if cls.valid_mom_artifact_id(model_id, ("SM",)):
                            output_model_ids.append(model_id)

        req_ids = list(dict.fromkeys(req_ids + output_req_ids))
        model_ids = list(dict.fromkeys(model_ids + output_model_ids))
        summary_blob = " ".join(
            cls.clean_repeated_text(value)
            for value in (
                resolution.get("summary"),
                resolution.get("decision"),
                issue.get("description"),
            )
            if cls.clean_repeated_text(value)
        )
        object_label = ""
        if req_ids:
            object_label = "、".join(sorted(req_ids, key=cls.artifact_id_sort_key)[:3])
            if len(req_ids) > 3:
                object_label += f" 等 {len(req_ids)} 筆需求"
        elif model_ids:
            object_label = "、".join(sorted(model_ids, key=cls.artifact_id_sort_key)[:3])
            if len(model_ids) > 3:
                object_label += f" 等 {len(model_ids)} 張模型"
        elif oq_ids:
            object_label = "、".join(sorted(oq_ids, key=cls.artifact_id_sort_key)[:3])

        if category == "align_model" or "模型" in original:
            prefix = "對齊需求與系統模型"
        elif category == "define_boundary" or "邊界" in original or "責任" in summary_blob:
            prefix = "釐清系統邊界與責任"
        elif category == "tradeoff" or "取捨" in original or "方案" in summary_blob:
            prefix = "確認需求方案取捨"
        elif "驗收" in original or "acceptance" in summary_blob.lower():
            prefix = "補齊需求驗收條件"
        elif "feedback" in original.lower() or "風險" in original or "限制" in original:
            prefix = "確認風險限制與需求回寫"
        elif "最終檢查" in original:
            prefix = "最終檢查需求與模型缺口"
        elif "需求正式化" in original:
            prefix = "正式化使用者需求"
        elif category == "resolve_conflict":
            prefix = "解決需求衝突"
        else:
            prefix = original or "正式會議議題"

        return prefix[:80].rstrip()

    @staticmethod
    # Defines clean mom title function for this module workflow.
    def clean_mom_title(value: Any) -> str:
        title = str(value or "").strip() or "正式會議議題"
        title = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", title).strip()
        return title or "正式會議議題"

    @classmethod
    # Defines action result summary function for this module workflow.
    def action_result_summary(cls, result: Dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return ""
        action = str(result.get("action") or "").strip() or "action"
        parts: List[str] = []
        req_ids = cls.clean_id_list(
            [row.get("id") for row in (result.get("REQ") or []) if isinstance(row, dict)],
            ("REQ",),
        )
        if req_ids:
            parts.append("更新需求 " + "、".join(sorted(req_ids, key=cls.artifact_id_sort_key)))
        url_ids = cls.clean_id_list(
            [row.get("id") for row in (result.get("requirements") or []) if isinstance(row, dict)],
            ("URL",),
        )
        if url_ids:
            parts.append("更新使用者需求 " + "、".join(sorted(url_ids, key=cls.artifact_id_sort_key)))
        model_ids = cls.clean_id_list(
            [
                row.get("id") or row.get("target_model_id")
                for row in (result.get("system_models") or result.get("model_changes") or [])
                if isinstance(row, dict)
            ],
            ("SM",),
        )
        if model_ids:
            parts.append("更新模型 " + "、".join(sorted(model_ids, key=cls.artifact_id_sort_key)))
        conflicts = [
            str(row.get("id") or "").strip()
            for row in (result.get("conflict_report") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
        if conflicts:
            parts.append("更新衝突 " + "、".join(dict.fromkeys(conflicts)))
        if isinstance(result.get("feedback"), dict):
            feedback_count = sum(
                len([row for row in (result["feedback"].get(key) or []) if isinstance(row, dict)])
                for key in ("findings", "constraints", "risks", "recommendations")
            )
            if feedback_count:
                parts.append(f"新增/更新 feedback {feedback_count} 筆")
        if isinstance(result.get("scope_updates") or result.get("scope"), dict) and (result.get("scope_updates") or result.get("scope")):
            parts.append("更新 scope")
        if not parts:
            reason = cls.clean_repeated_text(result.get("reason", ""))
            if reason:
                parts.append(reason)
        return f"{action}：" + "；".join(parts) if parts else action

    @classmethod
    # Defines meeting outcome function for this module workflow.
    def meeting_outcome(
        cls,
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> str:
        req_ids: List[str] = []
        url_ids: List[str] = []
        model_ids: List[str] = []
        conflict_ids: List[str] = []
        feedback_count = 0
        open_questions = 0
        for c in conversation or []:
            if not isinstance(c, dict):
                continue
            resp = c.get("response") if isinstance(c.get("response"), dict) else {}
            if not c.get("is_reply"):
                open_questions += len([q for q in (resp.get("open_questions") or []) if q])
            action_results = c.get("issue_action_results")
            if not isinstance(action_results, list):
                action_results = resp.get("issue_action_results")
            for result in action_results if isinstance(action_results, list) else []:
                if not isinstance(result, dict):
                    continue
                req_ids.extend(
                    cls.clean_id_list([row.get("id") for row in (result.get("REQ") or []) if isinstance(row, dict)], ("REQ",))
                )
                url_ids.extend(
                    cls.clean_id_list([row.get("id") for row in (result.get("requirements") or []) if isinstance(row, dict)], ("URL",))
                )
                model_ids.extend(
                    cls.clean_id_list(
                        [
                            row.get("id") or row.get("target_model_id")
                            for row in (result.get("system_models") or result.get("model_changes") or [])
                            if isinstance(row, dict)
                        ],
                        ("SM",),
                    )
                )
                conflict_ids.extend(
                    str(row.get("id") or "").strip()
                    for row in (result.get("conflict_report") or [])
                    if isinstance(row, dict) and str(row.get("id") or "").strip()
                )
                if isinstance(result.get("feedback"), dict):
                    feedback_count += sum(
                        len([row for row in (result["feedback"].get(key) or []) if isinstance(row, dict)])
                        for key in ("findings", "constraints", "risks", "recommendations")
                    )
        parts: List[str] = []
        req_ids = sorted(dict.fromkeys(req_ids), key=cls.artifact_id_sort_key)
        url_ids = sorted(dict.fromkeys(url_ids), key=cls.artifact_id_sort_key)
        model_ids = sorted(dict.fromkeys(model_ids), key=cls.artifact_id_sort_key)
        conflict_ids = list(dict.fromkeys(conflict_ids))
        if req_ids:
            parts.append("更新需求 " + "、".join(req_ids))
        if url_ids:
            parts.append("更新使用者需求 " + "、".join(url_ids))
        if model_ids:
            parts.append("更新模型 " + "、".join(model_ids))
        if conflict_ids:
            parts.append("更新衝突 " + "、".join(conflict_ids))
        if feedback_count:
            parts.append(f"新增/更新 feedback {feedback_count} 筆")
        if open_questions:
            parts.append(f"新增待確認事項 {open_questions} 筆")
        status = str((resolution or {}).get("status") or "").strip()
        if status and status not in {"agreed", "resolved"}:
            parts.append(f"狀態 {status}")
        if not parts:
            summary = cls.clean_repeated_text((resolution or {}).get("summary", ""))
            if summary:
                parts.append(summary)
        return "；".join(parts) if parts else "本次會議未產生 artifact 更新"

    # Defines polish meeting note header function for this module workflow.
    def polish_meeting_note_header(
        self,
        *,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
        display_title: str,
        summary: str,
        decision: str,
        outcome: str,
    ) -> Dict[str, str]:
        if not hasattr(self, "chat_json") or not hasattr(self, "build_direct_messages"):
            return {}

        def short_text(value: Any, limit: int = 600) -> str:
            text = self.clean_repeated_text(value)
            return text[:limit].rstrip()

        action_summaries: List[str] = []
        discussion_snippets: List[Dict[str, str]] = []
        for entry in conversation or []:
            if not isinstance(entry, dict) or entry.get("is_reply"):
                continue
            agent = str(entry.get("agent") or "").strip()
            resp = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            text = short_text(resp.get("text"), 280)
            if agent and text:
                discussion_snippets.append({"agent": agent, "text": text})
            action_results = entry.get("issue_action_results")
            if not isinstance(action_results, list):
                action_results = resp.get("issue_action_results")
            for result in action_results if isinstance(action_results, list) else []:
                line = self.action_result_summary(result)
                if line:
                    action_summaries.append(line)

        prompt = """# 任務
你只負責潤飾 MoM header 的可讀文字，不生成整份 MoM。

# 邊界
- 只能輸出 JSON object。
- 只能改寫 display_title、summary、decision。
- 不得新增 artifact id、需求內容、決議、風險、open question 或 action 產物。
- 不得改寫討論紀錄、產出明細或待確認事項。
- 若資訊不足，沿用 fallback。
- display_title 最多 80 字，必須保留原本已出現的 REQ/URL/SM/OQ id。
- summary 最多 2 句，需忠實反映本次會議。
- decision 只整理既有 decision；若 fallback decision 為空，輸出空字串。

# 輸出 JSON
{
  "display_title": "給人看的短標題",
  "summary": "短摘要",
  "decision": "決議文字"
}"""
        context = {
            "fallback": {
                "display_title": display_title,
                "summary": summary,
                "decision": decision,
                "outcome": outcome,
            },
            "issue": {
                "title": issue.get("title", ""),
                "category": issue.get("category", ""),
                "trace": issue.get("trace", {}),
            },
            "resolution": {
                "summary": summary,
                "decision": decision,
                "status": resolution.get("status", ""),
                "agreed_points": resolution.get("agreed_points", []),
                "unresolved_points": resolution.get("unresolved_points", []),
            },
            "action_summaries": list(dict.fromkeys(action_summaries))[:8],
            "discussion_snippets": discussion_snippets[:6],
        }
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        polished: Dict[str, str] = {}
        for key, limit in (("display_title", 80), ("summary", 500), ("decision", 350)):
            value = self.clean_repeated_text(data.get(key, ""))
            if value:
                polished[key] = value[:limit].rstrip()
        return polished


    # Defines write meeting note function for this module workflow.
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

        original_title = self.clean_repeated_text(issue.get("title", ""))
        display_title = self.normalized_issue_title(issue, conversation or [], resolution or {})
        summary = self.clean_repeated_text(resolution.get("summary", ""))
        decision = self.clean_repeated_text(resolution.get("decision", ""))
        outcome = self.meeting_outcome(conversation or [], resolution or {})
        polish = self.polish_meeting_note_header(
            issue=issue or {},
            conversation=conversation or [],
            resolution=resolution or {},
            display_title=display_title,
            summary=summary,
            decision=decision,
            outcome=outcome,
        )
        display_title = self.clean_mom_title(polish.get("display_title") or display_title)
        summary = polish.get("summary") if "summary" in polish else summary
        decision = polish.get("decision") if "decision" in polish else decision
        md = f"# {display_title}\n\n"
        if proposer:
            md += f"- **Proposed by**: {proposer}\n"
        else:
            md += "- **Proposed by**: mediator\n"
        md += f"- **Participants**: {', '.join(participants) if participants else '（無參與者）'}\n"
        md += f"- **Outcome**: {outcome}\n"
        status = resolution.get("status", "")
        if status:
            md += f"- **Status**: {status}\n"

        options = resolution.get("options", []) or []
        recommendation = resolution.get("recommendation", {}) or {}
        agreed_points = [
            self.clean_repeated_text(value)
            for value in (resolution.get("agreed_points", []) or [])
            if self.clean_repeated_text(value)
        ]
        unresolved_points = [
            self.clean_repeated_text(value)
            for value in (resolution.get("unresolved_points", []) or [])
            if self.clean_repeated_text(value)
        ]

        if summary:
            md += "\n## 摘要\n\n"
            md += summary + "\n\n"

        if decision or agreed_points or unresolved_points or options or recommendation:
            md += "## 決議\n\n"
            if decision:
                md += f"{decision}\n\n"
            if agreed_points:
                md += "\n".join(agreed_points) + "\n\n"
            if unresolved_points:
                md += "\n".join(unresolved_points) + "\n\n"
            if options or recommendation:
                md += "\n"

        if options:
            md += "### Decision Options\n\n"
            for option in options:
                if not isinstance(option, dict):
                    continue
                md += f"#### Option {option.get('id', '')}\n\n"
                md += f"{option.get('summary', '')}\n\n"
                for label, key in (("Pros", "pros"), ("Cons", "cons"), ("Impact", "impact")):
                    values = [str(x).strip() for x in (option.get(key) or []) if str(x).strip()]
                    if values:
                        md += f"- **{label}**: {'; '.join(values)}\n"
                if option.get("risk"):
                    md += f"- **Risk**: {option.get('risk')}\n"
                md += "\n"
        if recommendation:
            md += "### Recommendation\n\n"
            md += f"- **Option**: {recommendation.get('option_id', '')}\n"
            if recommendation.get("rationale"):
                md += f"- **Rationale**: {recommendation.get('rationale')}\n"
            md += "\n"
        md += "\n"

        # Defines clean for mom function for this module workflow.
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

            # Defines list lines function for this module workflow.
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

        # Defines table cell function for this module workflow.
        def table_cell(value: Any) -> str:
            if isinstance(value, list):
                text = ", ".join(str(item).strip() for item in value if str(item).strip())
            else:
                text = str(value or "").strip()
            return text.replace("|", "\\|").replace("\n", "<br>")

        # Defines as text list function for this module workflow.
        def as_text_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        # Defines render list line function for this module workflow.
        def render_list_line(prefix: str, values: Any) -> str:
            items = as_text_list(values)
            if not items:
                return ""
            return f"- {prefix}: {'; '.join(items)}"

        # Defines reason lines function for this module workflow.
        def reason_lines(value: Any) -> List[str]:
            text = str(value or "").strip()
            if not text:
                return []
            parts = [
                self.clean_repeated_text(part).strip(" ；;")
                for part in re.split(r"[；;]\s*", text)
                if part.strip(" ；;")
            ]
            return list(dict.fromkeys(part for part in (parts or [self.clean_repeated_text(text)]) if part))

        # Defines render requirements markdown function for this module workflow.
        def render_requirements_markdown(rows: Any, reason: Any = None) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            latest_by_id: Dict[str, Dict[str, Any]] = {}
            ordered_ids: List[str] = []
            fallback_rows: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                req_id = str(row.get("id") or "").strip()
                if req_id:
                    if req_id not in latest_by_id:
                        ordered_ids.append(req_id)
                    latest_by_id[req_id] = row
                else:
                    fallback_rows.append(row)
            sorted_ids = sorted(ordered_ids, key=self.artifact_id_sort_key)
            display_rows = [latest_by_id[req_id] for req_id in sorted_ids] + fallback_rows
            out = ["### 需求更新", ""]
            for row in display_rows:
                if not isinstance(row, dict):
                    continue
                req_id = row.get("id", "")
                req_type = row.get("type", "")
                requirement = row.get("description") or row.get("title") or ""
                acceptance = as_text_list(row.get("acceptance_criteria"))
                risks = as_text_list(row.get("risks"))
                title = str(row.get("title") or "").strip()
                heading = f"#### {req_id}"
                if title:
                    heading += f": {title}"
                out.extend([heading, ""])
                if req_type:
                    out.append(f"- **Type**: {req_type}")
                if requirement:
                    out.append(f"- **Requirement**: {requirement}")
                if acceptance:
                    out.extend(["- **Acceptance Criteria**:", *[f"  - {item}" for item in acceptance]])
                if risks:
                    out.extend(["- **Risks**:", *[f"  - {item}" for item in risks]])
                out.append("")
            reason_text = str(reason or "").strip()
            if reason_text:
                lines = reason_lines(reason_text)
                out.extend(["**Reason**:"])
                out.extend(f"- {line}" for line in lines)
            return "\n".join(out).strip()

        # Defines render user requirements markdown function for this module workflow.
        def render_user_requirements_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = ["### User Requirements", "", "| ID | Requirement | Stakeholder | Source |", "|---|---|---|---|"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append(
                    f"| {table_cell(row.get('id'))} | {table_cell(row.get('text'))} | {table_cell(row.get('stakeholder'))} | {table_cell(row.get('source'))} |"
                )
            return "\n".join(out)

        # Defines render conflict report markdown function for this module workflow.
        def render_conflict_report_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = ["### 衝突處理", "", "| ID | Type | Description | Recommendation |", "|---|---|---|---|"]
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

        # Defines render scope markdown function for this module workflow.
        def render_scope_markdown(scope: Any, reason: Any = None) -> str:
            if not isinstance(scope, dict) or not any(scope.get(key) for key in scope):
                return ""
            labels = {
                "in_scope": "In Scope",
                "out_of_scope": "Out of Scope",
                "assumptions": "Assumptions",
                "risks": "Risks",
            }
            out = ["### Scope 更新"]
            for key, label in labels.items():
                values = as_text_list(scope.get(key))
                if values:
                    out.extend(["", f"{label}", *[f"- {value}" for value in values]])
            reason_text = str(reason or "").strip()
            if reason_text:
                out.extend(["", f"**Reason**: {reason_text}"])
            return "\n".join(out)

        # Defines render analysis markdown function for this module workflow.
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
            return "\n\n".join(parts)

        # Defines render feedback markdown function for this module workflow.
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
            return "### 領域回饋\n\n" + "\n\n".join(parts)

        # Defines render system models markdown function for this module workflow.
        def render_system_models_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            latest_by_id: Dict[str, Dict[str, Any]] = {}
            ordered_ids: List[str] = []
            fallback_rows: List[Dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                model_id = str(row.get("id") or "").strip()
                if model_id:
                    if model_id not in latest_by_id:
                        ordered_ids.append(model_id)
                    latest_by_id[model_id] = row
                else:
                    fallback_rows.append(row)
            sorted_ids = sorted(ordered_ids, key=self.artifact_id_sort_key)
            display_rows = [latest_by_id[model_id] for model_id in sorted_ids] + fallback_rows
            out = ["### 模型更新", "", "| ID | Type | Name | Related Requirements |", "|---|---|---|---|"]
            for row in display_rows:
                if not isinstance(row, dict):
                    continue
                related_requirement_ids = sorted(
                    dict.fromkeys(str(item).strip() for item in (row.get("related_requirement_ids") or []) if str(item).strip()),
                    key=self.artifact_id_sort_key,
                )
                out.append(
                    "| "
                    + " | ".join(
                        table_cell(value)
                        for value in (
                            row.get("id"),
                            row.get("type"),
                            row.get("name"),
                            related_requirement_ids,
                        )
                    )
                    + " |"
                )
            return "\n".join(out)

        # Defines render model changes markdown function for this module workflow.
        def render_model_changes_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            display_rows = []
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                operation = str(row.get("operation") or "").strip()
                if operation not in {"create", "update"}:
                    continue
                model_id = str(row.get("id") or row.get("target_model_id") or "").strip()
                if not model_id:
                    continue
                key = (operation, model_id)
                if key in seen:
                    continue
                seen.add(key)
                display_rows.append(row)

            display_rows = sorted(
                display_rows,
                key=lambda row: (
                    0 if str(row.get("operation") or "").strip() == "create" else 1,
                    self.artifact_id_sort_key(row.get("id") or row.get("target_model_id")),
                ),
            )
            if not display_rows:
                return ""
            out = [
                "### 模型變更",
                "",
                "| Change | ID | Type | Name | Related Requirements |",
                "|---|---|---|---|---|",
            ]
            for row in display_rows:
                operation = str(row.get("operation") or "").strip()
                change_label = "新建" if operation == "create" else "更新"
                related_requirement_ids = sorted(
                    dict.fromkeys(
                        str(item).strip()
                        for item in (row.get("related_requirement_ids") or [])
                        if str(item).strip()
                    ),
                    key=self.artifact_id_sort_key,
                )
                out.append(
                    "| "
                    + " | ".join(
                        table_cell(value)
                        for value in (
                            change_label,
                            row.get("id") or row.get("target_model_id"),
                            row.get("type"),
                            row.get("name"),
                            related_requirement_ids,
                        )
                    )
                    + " |"
                )
            return "\n".join(out)

        # Defines merge table rows function for this module workflow.
        def merge_table_rows(current: List[Dict[str, Any]], rows: Any) -> None:
            if not isinstance(rows, list):
                return
            seen = {json.dumps(row, ensure_ascii=False, sort_keys=True) for row in current if isinstance(row, dict)}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = json.dumps(row, ensure_ascii=False, sort_keys=True)
                if key not in seen:
                    current.append(row)
                    seen.add(key)

        # Defines collect meeting outputs function for this module workflow.
        def collect_meeting_outputs(records: List[Dict[str, Any]]) -> Dict[str, Any]:
            outputs: Dict[str, Any] = {
                "REQ": [],
                "URL": [],
                "conflict_report": [],
                "system_models": [],
                "feedback": {"findings": [], "constraints": [], "risks": [], "recommendations": [], "sources": []},
                "scope": {},
                "reasons": [],
            }
            for entry in records:
                if not isinstance(entry, dict):
                    continue
                artifacts = entry.get("artifacts") if isinstance(entry.get("artifacts"), dict) else {}
                merge_table_rows(outputs["REQ"], artifacts.get("REQ"))
                merge_table_rows(outputs["URL"], artifacts.get("URL"))
                merge_table_rows(outputs["conflict_report"], artifacts.get("conflict_report"))
                merge_table_rows(outputs["system_models"], artifacts.get("system_models"))
                if isinstance(artifacts.get("feedback"), dict):
                    for key in ("findings", "constraints", "risks", "recommendations", "sources"):
                        merge_table_rows(outputs["feedback"].setdefault(key, []), artifacts["feedback"].get(key))
                if isinstance(artifacts.get("scope"), dict):
                    outputs["scope"].update(artifacts.get("scope") or {})
                if artifacts.get("requirement_reason"):
                    outputs["reasons"].append(str(artifacts.get("requirement_reason")).strip())
                if artifacts.get("scope_reason"):
                    outputs["reasons"].append(str(artifacts.get("scope_reason")).strip())

                action_results = entry.get("issue_action_results")
                if not isinstance(action_results, list):
                    continue
                for result in action_results:
                    if not isinstance(result, dict):
                        continue
                    req_rows = result.get("REQ")
                    merge_table_rows(outputs["REQ"], req_rows)
                    merge_table_rows(outputs["URL"], result.get("requirements"))
                    merge_table_rows(outputs["conflict_report"], result.get("conflict_report"))
                    merge_table_rows(outputs["system_models"], result.get("system_models"))
                    feedback = result.get("feedback")
                    if isinstance(feedback, dict):
                        for key in ("findings", "constraints", "risks", "recommendations", "sources"):
                            merge_table_rows(outputs["feedback"].setdefault(key, []), feedback.get(key))
                    scope = result.get("scope_updates") or result.get("scope")
                    if isinstance(scope, dict):
                        outputs["scope"].update(scope)
                    if result.get("reason"):
                        outputs["reasons"].append(str(result.get("reason")).strip())
            outputs["reasons"] = list(dict.fromkeys(reason for reason in outputs["reasons"] if reason))
            return outputs

        # Defines render meeting outputs function for this module workflow.
        def render_meeting_outputs(records: List[Dict[str, Any]]) -> str:
            outputs = collect_meeting_outputs(records)
            sections = []
            if outputs.get("REQ"):
                sections.append(render_requirements_markdown(outputs.get("REQ"), "; ".join(outputs.get("reasons") or [])))
            if outputs.get("URL"):
                sections.append(render_user_requirements_markdown(outputs.get("URL")))
            if outputs.get("conflict_report"):
                sections.append(render_conflict_report_markdown(outputs.get("conflict_report")))
            scope = render_scope_markdown(outputs.get("scope"))
            if scope:
                sections.append(scope)
            feedback = render_feedback_markdown(outputs.get("feedback"))
            if feedback:
                sections.append(feedback)
            if outputs.get("system_models"):
                sections.append(render_system_models_markdown(outputs.get("system_models")))
            if not sections:
                return ""
            return "\n\n".join(sections)

        main_records = [c for c in conversation if not c.get("is_reply", False)]
        md += "## 討論紀錄\n\n"
        if not main_records:
            md += "（本議題無人發言）\n\n"
        else:
            for c in main_records:
                agent = c.get("agent", "?")
                resp = c.get("response", {})
                text = clean_for_mom(resp.get("text", ""))
                md += f"### {agent}\n\n"
                md += f"{text or '（本發言無可讀內容）'}\n\n"

        meeting_outputs = render_meeting_outputs(main_records)
        if meeting_outputs:
            md += meeting_outputs + "\n\n"

        question_pairs: List[Dict[str, Any]] = []
        question_index: Dict[tuple[str, str, str], Dict[str, Any]] = {}

        # Defines labeled answers function for this module workflow.
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

        # Defines answer lines function for this module workflow.
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
                question_text = self.clean_mom_question(q.get("question"))
                if not question_text:
                    continue
                to_agent = str(q.get("to") or "").strip()
                if not to_agent:
                    continue
                if to_agent == from_agent:
                    continue
                normalized_question = re.sub(r"\s+", "", question_text.lower())
                key = (from_agent, to_agent, normalized_question)
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
            question_text = self.clean_mom_question(resp.get("reply_to_question"))
            from_agent = str(resp.get("reply_to_agent") or "?").strip() or "?"
            answer_agent = str(c.get("agent") or "?").strip() or "?"
            answer = clean_for_mom(resp.get("text", ""))
            if not question_text and not answer:
                continue
            matched = None
            for pair in question_pairs:
                if (
                    pair.get("from_agent") == from_agent
                    and re.sub(r"\s+", "", str(pair.get("question") or "").lower()) == re.sub(r"\s+", "", question_text.lower())
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
            md += "## 待確認事項\n\n"
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
