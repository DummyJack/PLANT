# Handles meeting execution, response collection, records, and issue state.
import json
import importlib.util
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from . import mom
except ImportError:  # pragma: no cover - supports direct file loading in small tools.
    _mom_spec = importlib.util.spec_from_file_location("meeting_mom", Path(__file__).with_name("mom.py"))
    if _mom_spec is None or _mom_spec.loader is None:
        raise
    mom = importlib.util.module_from_spec(_mom_spec)
    _mom_spec.loader.exec_module(mom)

# Defines MediatorRecords class for this module workflow.
class MediatorRecords:
    @staticmethod
    # Defines clean repeated text function for this module workflow.
    def clean_repeated_text(value: Any) -> str:
        return mom.clean_repeated_text(value)

    @staticmethod
    # Defines valid mom artifact id function for this module workflow.
    def valid_mom_artifact_id(value: Any, prefixes: tuple[str, ...]) -> bool:
        return mom.valid_artifact_id(value, prefixes)

    @classmethod
    # Defines clean id list function for this module workflow.
    def clean_id_list(cls, values: Any, prefixes: tuple[str, ...]) -> List[str]:
        return mom.clean_id_list(values, prefixes)

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
        return mom.artifact_id_sort_key(value)

    @staticmethod
    # Defines option display label function for this module workflow.
    def option_display_label(value: Any, index: int = 0) -> str:
        return mom.option_display_label(value, index)

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
            action_results = c.get("issue_action_results")
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
                row.get("id")
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
                            row.get("id")
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

    @classmethod
    # Defines unclear mom header text function for this module workflow.
    def unclear_mom_header_text(cls, value: Any, *, allow_empty: bool = False) -> bool:
        return mom.unclear_header_text(value, allow_empty=allow_empty)

    @classmethod
    # Defines mom referenced ids function for this module workflow.
    def mom_referenced_ids(
        cls,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
    ) -> List[str]:
        return mom.referenced_ids(issue, conversation, resolution)

    # Defines write meeting note header function for this module workflow.
    def write_meeting_note_header(
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
        human_decision_notes: List[str] = []
        for entry in conversation or []:
            if not isinstance(entry, dict) or entry.get("is_reply"):
                continue
            agent = str(entry.get("agent") or "").strip()
            resp = entry.get("response") if isinstance(entry.get("response"), dict) else {}
            text = short_text(resp.get("text"), 280)
            if agent and text:
                discussion_snippets.append({"agent": agent, "text": text})
            action_results = entry.get("issue_action_results")
            for result in action_results if isinstance(action_results, list) else []:
                line = self.action_result_summary(result)
                if line:
                    action_summaries.append(line)
        human_choice = resolution.get("human_choice") if isinstance(resolution.get("human_choice"), dict) else {}
        if human_choice:
            chosen_option_id = str(human_choice.get("chosen_option_id") or "").strip()
            chosen_option_title = str(human_choice.get("chosen_option_title") or "").strip()
            if chosen_option_id or chosen_option_title:
                human_decision_notes.append(
                    f"人類採納{self.option_display_label(chosen_option_id) if chosen_option_id else '自訂裁決'}"
                    + (f"：{chosen_option_title}" if chosen_option_title else "")
                )
            for option in human_choice.get("chosen_options") or []:
                if isinstance(option, dict):
                    option_id = str(option.get("option_id") or "").strip()
                    title = self.clean_repeated_text(option.get("title", ""))
                    description = self.clean_repeated_text(option.get("description", ""))
                    note = "，".join(part for part in (title, description) if part)
                    if option_id or note:
                        human_decision_notes.append(
                            f"{self.option_display_label(option_id)}：{note}" if option_id else note
                        )
        referenced_ids = self.mom_referenced_ids(issue, conversation, resolution)

        prompt = """# 任務
你負責根據會議證據撰寫單一正式會議議題的 MoM header，輸出清楚的「摘要」與「決議」。

# 邊界
- 只能輸出 JSON object。
- 只能根據 context 內已存在的 issue、discussion_snippets、resolution、human_decision_notes、action_summaries、artifact_updates 撰寫。
- 不得新增 artifact id、需求內容、決議、風險、open question 或 action 產物。
- 不得把尚未裁決的事項寫成已裁決。
- 若資訊不足，必須明確寫「尚未形成決議」或沿用 fallback，不可編造。
- display_title 最多 80 字，必須保留原本已出現的 REQ/URL/SM/OQ id。
- summary 必須像正式會議摘要：用 2 到 4 句整理本議題討論的核心問題、主要參與者關注點、已確認的差異與收斂方向；不要寫成流水帳或只列選項代號。
- decision 必須像正式會議決議：明確寫出最後採納的處理方式、影響的需求/模型/衝突 ID、後續要落實的內容；不要只寫「採用 A」、「選 B」或只列狀態。
- 若有 human_decision_notes，decision 必須把採納選項寫成完整內容，例如「採用選項 A：完整顯示配送費率與預估里程」，不可只寫「採用選項 A」。
- summary 或 decision 若提到選項 A/B/C，必須把選項內容自然寫進句子中；不要用孤立括號補充，也不可只寫 A/B/C。
- 若沒有決議，decision 輸出「尚未形成決議；...」並說明仍缺什麼。
- 不要只輸出 agreed、resolved、completed 或單一句狀態。
- evidence 必須列出 1 到 5 個使用到的來源線索，來源只能來自 context。

# 輸出 JSON
{
  "display_title": "給人看的短標題",
  "summary": "本議題摘要，2 到 4 句",
  "decision": "本議題決議，包含採納內容與影響對象；沒有決議時寫尚未形成決議",
  "evidence": ["使用到的來源線索"]
}"""
        context = {
            "fallback": {
                "display_title": display_title,
                "summary": summary,
                "decision": decision,
                "outcome": outcome,
            },
            "referenced_ids": referenced_ids[:20],
            "issue": {
                "title": issue.get("title", ""),
                "description": issue.get("description", ""),
                "category": issue.get("category", ""),
                "trace": issue.get("trace", {}),
                "participants": issue.get("participants", []),
            },
            "resolution": {
                "summary": summary,
                "decision": decision,
                "status": resolution.get("status", ""),
                "agreed_points": resolution.get("agreed_points", []),
                "unresolved_points": resolution.get("unresolved_points", []),
                "recommendation": resolution.get("recommendation", {}),
                "human_choice": human_choice,
                "artifact_updates": resolution.get("artifact_updates", {}),
            },
            "human_decision_notes": list(dict.fromkeys(human_decision_notes))[:8],
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
            if value and not self.unclear_mom_header_text(value, allow_empty=(key == "decision")):
                polished[key] = value[:limit].rstrip()
        evidence = data.get("evidence")
        if isinstance(evidence, list):
            evidence_rows = [
                self.clean_repeated_text(item)
                for item in evidence
                if self.clean_repeated_text(item)
            ]
            if evidence_rows:
                polished["evidence"] = "；".join(evidence_rows[:5])[:500].rstrip()
        return polished

    # Defines write conflict discussion groups function for this module workflow.
    def write_conflict_discussion_groups(
        self,
        *,
        issue: Dict[str, Any],
        conversation: List[Dict[str, Any]],
        resolution: Dict[str, Any],
        conflict_options: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return mom.write_conflict_discussion_groups(
            issue=issue,
            conversation=conversation,
            resolution=resolution,
            conflict_options=conflict_options,
            chat_json=getattr(self, "chat_json", None),
            build_direct_messages=getattr(self, "build_direct_messages", None),
        )


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
        polish = self.write_meeting_note_header(
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
            md += f"- **提出者**: {proposer}\n"
        else:
            md += "- **提出者**: mediator\n"
        md += f"- **參與者**: {', '.join(participants) if participants else '（無參與者）'}\n"
        status = resolution.get("status", "")
        if status:
            md += f"- **狀態**: {status}\n"

        options = resolution.get("options", []) or []
        recommendation = resolution.get("recommendation", {}) or {}

        def conflict_report_decision_options() -> List[Dict[str, Any]]:
            if str((issue or {}).get("category") or "").strip() != "resolve_conflict":
                return []
            store = getattr(self, "store", None)
            artifact_dir = getattr(store, "artifact_dir", None)
            if not artifact_dir:
                return []
            try:
                from storage.artifact import latest_conflict_report_payload

                rows = latest_conflict_report_payload(Path(artifact_dir))
            except Exception:
                return []
            if not rows:
                return []

            affected_ids = [
                str(value).strip()
                for value in (resolution.get("affected_conflict_ids") or [])
                if str(value).strip()
            ]
            if not affected_ids:
                affected_ids = [
                    str(value).strip()
                    for value in (issue.get("trace") or {}).get("artifact_ids", [])
                    if str(value).strip().startswith("CR-")
                ]
            affected_set = set(affected_ids)
            scoped_rows = [
                row
                for row in rows
                if isinstance(row, dict)
                and (not affected_set or str(row.get("id") or "").strip() in affected_set)
            ]
            if not scoped_rows:
                scoped_rows = [row for row in rows if isinstance(row, dict)]

            conflict_blocks: List[Dict[str, Any]] = []
            for row in scoped_rows:
                conflict_id = str(row.get("id") or "").strip()
                row_title = str(row.get("title") or "").strip()
                row_description = str(row.get("description") or "").strip()
                recommended = str(row.get("recommended_resolution") or "").strip()
                row_options: List[Dict[str, Any]] = []
                for option in row.get("resolution_options") or []:
                    if not isinstance(option, dict):
                        continue
                    option_id = str(option.get("option_id") or "").strip()
                    description = str(option.get("description") or "").strip()
                    if not any((option_id, description)):
                        continue
                    row_options.append(
                        {
                            "option_id": option_id,
                            "title": str(option.get("title") or "").strip(),
                            "description": description,
                            "recommended": bool(option.get("recommendation")),
                        }
                    )
                if row_options or recommended:
                    conflict_blocks.append(
                        {
                            "kind": "conflict_decision",
                            "conflict_id": conflict_id,
                            "title": row_title or row_description,
                            "options": row_options,
                            "recommended_resolution": recommended,
                        }
                    )

            return conflict_blocks

        if str((issue or {}).get("category") or "").strip() == "resolve_conflict":
            has_conflict_options = any(
                isinstance(option, dict) and option.get("kind") == "conflict_decision"
                for option in options
            )
            if not has_conflict_options:
                options = conflict_report_decision_options() or options
            recommendation = {}

        def option_detail_map(option_rows: List[Dict[str, Any]]) -> Dict[str, str]:
            details: Dict[str, str] = {}
            for option_index, option in enumerate(option_rows or []):
                if not isinstance(option, dict):
                    continue
                if option.get("kind") == "conflict_decision":
                    for nested_index, row in enumerate(option.get("options") or []):
                        if not isinstance(row, dict):
                            continue
                        option_id = str(row.get("option_id") or "").strip()
                        label = self.option_display_label(option_id, nested_index)
                        detail = self.clean_repeated_text(
                            row.get("description") or row.get("title") or ""
                        )
                        if detail:
                            details[label] = detail
                    continue
                option_id = str(option.get("option_id") or "").strip()
                label = self.option_display_label(option_id, option_index)
                detail = self.clean_repeated_text(
                    option.get("description") or option.get("title") or ""
                )
                if detail:
                    details[label] = detail
            return details

        def expand_option_mentions(text: Any, option_rows: List[Dict[str, Any]]) -> str:
            value = self.clean_repeated_text(text)
            if not value:
                return ""
            details = option_detail_map(option_rows)
            for label, detail in details.items():
                raw_label = label.replace("選項 ", "").strip()
                if not raw_label:
                    continue
                if not detail or detail in value:
                    continue
                replacement = f"{label}：{detail}"
                next_value = re.sub(
                    rf"(採用|選擇|建議採用|決議採用)(選項|方案)?\s*{re.escape(raw_label)}(?![A-Za-z])",
                    rf"\1{replacement}",
                    value,
                    count=1,
                )
                if next_value != value:
                    value = next_value
                    continue
                next_value = re.sub(
                    rf"(選項|方案)\s*{re.escape(raw_label)}(?![A-Za-z])",
                    replacement,
                    value,
                    count=1,
                )
                if next_value != value:
                    value = next_value
                    continue
                value = re.sub(
                    rf"(?<![A-Za-z]){re.escape(raw_label)}(?![A-Za-z])",
                    replacement,
                    value,
                    count=1,
                )
            value = re.sub(r"。{2,}", "。", value)
            value = re.sub(r"．{2,}", "．", value)
            return value

        if str((issue or {}).get("category") or "").strip() == "resolve_conflict":
            summary = expand_option_mentions(summary, options)
            decision = expand_option_mentions(decision, options)

        agreed_points = [
            expand_option_mentions(value, options)
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
            md += "### 決策選項\n\n"
            for index, option in enumerate(options):
                if not isinstance(option, dict):
                    continue
                if option.get("kind") == "conflict_decision":
                    conflict_id = str(option.get("conflict_id") or "").strip()
                    title = str(option.get("title") or "").strip()
                    heading = conflict_id or f"CR-{index + 1}"
                    if title:
                        heading += f"：{title}"
                    md += f"#### {heading}\n\n"
                    option_rows = [row for row in (option.get("options") or []) if isinstance(row, dict)]
                    for option_index, row in enumerate(option_rows, start=1):
                        option_id = str(row.get("option_id") or "").strip()
                        label = self.option_display_label(option_id, option_index - 1)
                        summary_text = str(row.get("description") or row.get("title") or "").strip()
                        line = f"{label}："
                        line += summary_text or label
                        md += line.rstrip() + "\n"
                    md += "\n"
                    continue
                option_id = str(option.get("option_id") or "").strip()
                if not option_id:
                    option_id = chr(ord("A") + index)
                title = str(option.get("title") or option.get("strategy") or "").strip()
                heading = self.option_display_label(option_id, index)
                if title:
                    heading += f"：{title}"
                md += f"#### {heading}\n\n"
                summary_text = str(option.get("description") or option.get("title") or "").strip()
                if summary_text:
                    md += f"{summary_text}\n\n"
                conflict_ids = [
                    str(value).strip()
                    for value in (option.get("conflict_ids") or [])
                    if str(value).strip()
                ]
                if conflict_ids:
                    md += f"- **適用衝突**: {'、'.join(conflict_ids)}\n"
                recommended_conflict_ids = [
                    str(value).strip()
                    for value in (option.get("recommended_conflict_ids") or [])
                    if str(value).strip()
                ]
                if recommended_conflict_ids:
                    md += f"- **推薦**: {'、'.join(recommended_conflict_ids)}\n"
                recommendation_notes = [
                    str(value).strip()
                    for value in (option.get("recommendation_notes") or [])
                    if str(value).strip()
                ]
                if recommendation_notes:
                    md += f"- **推薦理由**: {'; '.join(recommendation_notes)}\n"
                for label, key in (("優點", "pros"), ("限制", "cons"), ("影響", "impact")):
                    values = [str(x).strip() for x in (option.get(key) or []) if str(x).strip()]
                    if values:
                        md += f"- **{label}**: {'; '.join(values)}\n"
                if option.get("risk"):
                    md += f"- **風險**: {option.get('risk')}\n"
                md += "\n"
        if recommendation:
            md += "### 建議\n\n"
            option_id = str(recommendation.get("option_id") or "").strip()
            if option_id:
                md += f"- **建議選項**: {self.option_display_label(option_id)}\n"
            conflict_ids = [
                str(value).strip()
                for value in (recommendation.get("conflict_ids") or [])
                if str(value).strip()
            ]
            if conflict_ids:
                md += f"- **適用衝突**: {'、'.join(conflict_ids)}\n"
            if recommendation.get("rationale"):
                md += f"- **理由**: {recommendation.get('rationale')}\n"
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
                        label = str(row.get("proposed_label") or "").strip()
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
                    out.append(f"- **類型**: {req_type}")
                if requirement:
                    out.append(f"- **需求**: {requirement}")
                if acceptance:
                    out.extend(["- **驗收條件**:", *[f"  - {item}" for item in acceptance]])
                if risks:
                    out.extend(["- **風險**:", *[f"  - {item}" for item in risks]])
                out.append("")
            reason_text = str(reason or "").strip()
            if reason_text:
                lines = reason_lines(reason_text)
                out.extend(["**理由**:"])
                out.extend(f"- {line}" for line in lines)
            return "\n".join(out).strip()

        # Defines render user requirements markdown function for this module workflow.
        def render_user_requirements_markdown(rows: Any) -> str:
            if not isinstance(rows, list) or not rows:
                return ""
            out = ["### 使用者需求", "", "| ID | 需求 | 利害關係人 | 來源 |", "|---|---|---|---|"]
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
            out = ["### 衝突處理", "", "| ID | 標題 | 類型 | 描述 | 解決選項 | 建議 |", "|---|---|---|---|---|---|"]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = row.get("final_label") or row.get("final_type") or ""
                recommendation = row.get("recommended_resolution") or ""
                option_texts = []
                for option_index, option in enumerate(row.get("resolution_options") or [], start=1):
                    if not isinstance(option, dict):
                        continue
                    option_id = str(option.get("option_id") or "").strip()
                    if option_id.isdigit():
                        option_id = chr(ord("A") + max(0, int(option_id) - 1))
                    if not option_id:
                        option_id = chr(ord("A") + option_index - 1)
                    text = str(option.get("description") or option.get("title") or "").strip()
                    if text:
                        option_texts.append(f"選項 {option_id}：{text}")
                out.append(
                    f"| {table_cell(row.get('id'))} | {table_cell(row.get('title'))} | {table_cell(label)} | {table_cell(row.get('description'))} | {table_cell('; '.join(option_texts))} | {table_cell(recommendation)} |"
                )
            return "\n".join(out)

        # Defines render scope markdown function for this module workflow.
        def render_scope_markdown(scope: Any, reason: Any = None) -> str:
            if not isinstance(scope, dict) or not any(scope.get(key) for key in scope):
                return ""
            labels = {
                "in_scope": "範圍內",
                "out_of_scope": "範圍外",
                "assumptions": "假設",
                "risks": "風險",
            }
            out = ["### Scope 更新"]
            for key, label in labels.items():
                values = as_text_list(scope.get(key))
                if values:
                    out.extend(["", f"{label}", *[f"- {value}" for value in values]])
            reason_text = str(reason or "").strip()
            if reason_text:
                out.extend(["", f"**理由**: {reason_text}"])
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
                parts.append(f"**理由**: {reason}")
            if not parts:
                return ""
            return "\n\n".join(parts)

        # Defines render feedback markdown function for this module workflow.
        def render_feedback_markdown(feedback: Any) -> str:
            if not isinstance(feedback, dict) or not feedback:
                return ""
            labels = {
                "findings": "發現",
                "constraints": "限制",
                "risks": "風險",
                "recommendations": "建議",
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
                            details.append(f"相關需求: {related}")
                        if source:
                            details.append(f"來源: {source}")
                        suffix = f" ({'; '.join(details)})" if details else ""
                        if text:
                            lines.append(f"- {text}{suffix}")
                    elif str(row).strip():
                        lines.append(f"- {str(row).strip()}")
                if len(lines) > 1:
                    parts.append("\n".join(lines))
            sources = as_text_list(feedback.get("sources"))
            if sources:
                parts.append("**來源**\n" + "\n".join(f"- {source}" for source in sources))
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
            out = ["### 模型更新", "", "| ID | 類型 | 名稱 | 相關需求 |", "|---|---|---|---|"]
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
                model_id = str(row.get("id") or "").strip()
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
                    self.artifact_id_sort_key(row.get("id")),
                ),
            )
            if not display_rows:
                return ""
            out = [
                "### 模型變更",
                "",
                "| 變更 | ID | 類型 | 名稱 | 相關需求 |",
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
                            row.get("id"),
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

        # Defines nested markdown headings function for this module workflow.
        def nested_markdown_headings(text: str) -> str:
            return re.sub(r"(?m)^(#{1,5})(\s+)", r"#\1\2", str(text or "").strip())

        main_records = [c for c in conversation if not c.get("is_reply", False)]
        md += "## 討論紀錄\n\n"
        conflict_discussion_groups = self.write_conflict_discussion_groups(
            issue=issue or {},
            conversation=conversation or [],
            resolution=resolution or {},
            conflict_options=options if isinstance(options, list) else [],
        )
        if conflict_discussion_groups:
            md += mom.render_discussion_groups(conflict_discussion_groups) + "\n\n"
        elif not main_records:
            md += "（本議題無人發言）\n\n"
        else:
            for c in main_records:
                agent = c.get("agent", "?")
                resp = c.get("response", {})
                text = clean_for_mom(resp.get("text", ""))
                md += f"### {agent}\n\n"
                md += f"{text or '（本發言無可讀內容）'}\n\n"
                record_outputs = render_meeting_outputs([c])
                if record_outputs:
                    md += nested_markdown_headings(record_outputs) + "\n\n"

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
            md += "## 開放問題\n\n"
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
