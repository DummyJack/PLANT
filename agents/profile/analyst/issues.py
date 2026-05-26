# Analyst issue logic: propose decision issues and build analyst meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language

from agents.profile.conflict_review import (
    CONFLICT_REVIEW_LABEL_RULES,
    CONFLICT_REVIEW_REASON_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
    conflict_review_text_hint,
)

from .conflict_store import all_conflict_rows
from .requirements import requirement_discussion_pool
from .prompts import (
    ANALYST_ELICITATION_CONTEXT_RULES,
    analyst_elicitation_action_rules,
    analyst_elicitation_action_task,
)
from .validation import resolution_options_payload


ANALYST_ISSUE_TASK = (
    "聚焦需求意圖、需求範圍、需求條目品質、驗收條件、"
    "來源追蹤與未決缺口。"
)

ANALYST_ISSUE_RULES = """- text 需說明：此議題對需求的影響、目前可確認的需求內容、仍不可寫入正式需求的缺口、以及建議的需求處理方式。
- 依據優先引用 requirement id、conflict id、stakeholder 觀點、既有討論或議題描述。
- 判斷重點是需求是否清楚、可驗收、可追蹤、範圍是否穩定、是否需要拆成功能需求、非功能需求、限制條件或保留為未決問題。
- 若提出需求修正，必須指出要改哪個欄位：需求文字、優先級、驗收條件或來源追蹤。
- 若資訊不足，請說明缺少哪個可寫入需求的必要訊號，而不是只說需要更多資訊。
- 若需要他人補資訊，才在 open_questions 中提出能直接支援需求修正的具體問題。
- open_questions 的 to 欄位只能用系統角色名：user、analyst、expert、modeler；禁止用利害關係人名稱。
- 若建議新增或修改需求，請說明應落在需求、驗收條件或未決問題哪一類。"""

ANALYST_CONFLICT_ISSUE_TASK = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "先根據 requirements 原文獨立重判，並將重判結果填入 proposed_label。"
)

ANALYST_CONFLICT_ISSUE_RULES = f"""{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- 先只根據 requirements 原文獨立判斷 proposed_label；不要先順著既有標籤想理由。
- reason 必須寫成完整審查意見：說明你的獨立判斷依據，並說明需求語意、範圍、條件、互斥點或可驗證性；不要只重述兩句需求文字。
{CONFLICT_REVIEW_LABEL_RULES}
{CONFLICT_REVIEW_REASON_RULES}
- 需特別檢查：是否為同一需求槽位、重複／近似重複、細化、範圍重疊，或需要合併、改寫、刪除、人工裁定後才能放入軟體需求規格書。
- 若只是語意模糊、範圍未明、角色不同、情境不同、優先級不同或仍需補充條件，不能因看不出衝突就直接支持 Neutral。
- 若支持 Conflict，必須清楚指出互斥點；若支持 Neutral，必須清楚說明為何既不衝突、也不重複，且無直接語義關係。
- 不要跳到實作方案或最終決策。"""


class AnalystIssues:
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 3,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="analyst_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            build_observation=self.build_analyst_issue_observation,
            decide_action=self.decide_analyst_issue_action,
            execute_action=self.execute_analyst_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    def build_requirement_issue_signals(self, artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        for c in all_conflict_rows(artifact):
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or "").strip()
            if cid and str(c.get("label") or "").strip() == "Conflict":
                signals.append(
                    {
                        "kind": "unresolved_conflict",
                        "source_ids": [cid] + list(c.get("requirement_ids", []) or []),
                        "summary": str(c.get("description") or "").strip(),
                        "suggested_category": "conflict_resolution",
                    }
                )

        for oq in artifact.get("open_questions", []) or []:
            if not isinstance(oq, dict) or oq.get("status") == "answered":
                continue
            question = str(oq.get("question") or "").strip()
            if question:
                signals.append(
                    {
                        "kind": "unanswered_srs_open_question",
                        "source_ids": [
                            str(oq.get("source_conflict_id") or "").strip()
                        ] if str(oq.get("source_conflict_id") or "").strip() else [],
                        "summary": question,
                        "suggested_category": "srs_open_question",
                    }
                )

        for req in requirement_discussion_pool(artifact):
            if not isinstance(req, dict):
                continue
            rid = str(req.get("id") or "").strip()
            text = str(req.get("text") or "").strip()
            if not rid or not text:
                continue
            issues: List[str] = []
            source_text = str(req.get("source") or "").strip()
            if not source_text:
                issues.append("missing_source_trace")
            if len(text) < 12:
                issues.append("unclear_requirement_text")
            if issues:
                signals.append(
                    {
                        "kind": "requirement_quality_gap",
                        "source_ids": [rid],
                        "summary": text,
                        "issues": issues,
                        "suggested_category": "requirement_revision",
                    }
                )

        for rc in artifact.get("change_record", []) or []:
            if not isinstance(rc, dict):
                continue
            status = str(rc.get("status") or "proposed").strip()
            if status in {"proposed", "pending_review", "pending_confirmation"}:
                signals.append(
                    {
                        "kind": "pending_requirement_change",
                        "source_ids": [
                            str(x).strip()
                            for x in [rc.get("requirement_id"), rc.get("id")]
                            if str(x or "").strip()
                        ],
                        "summary": (
                            f"change_type={rc.get('change_type') or 'unknown'}, "
                            f"field={rc.get('field') or 'requirement'}, status={status}"
                        ),
                        "suggested_category": "requirement_revision",
                    }
                )
        return signals

    def build_analyst_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 3),
            "latest_draft": artifact.get("latest_draft", ""),
            "system_models": artifact.get("system_models", []),
            "conflict_report": artifact.get("conflict_report", []),
            "feedback": artifact.get("feedback", {}),
        }

    def decide_analyst_issue_action(
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
                "reasoning": "上一輪 Analyst issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_requirement_issues",
            "params": {},
            "reasoning": "根據需求品質、需求範圍、可驗收性、可追蹤性與未決缺口提出需要會議處理的議題。",
        }

    def execute_analyst_issue_action(
        self,
        *,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        if action != "propose_requirement_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"Analyst issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 3)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "system_models": observation.get("system_models", []),
            "conflict_report": observation.get("conflict_report", []),
            "feedback": observation.get("feedback", {}),
        }
        prompt = f"""# 任務
提出本輪需要進入 issue proposal 的需求工程議題。目標是讓 latest draft 更 SRS-ready。

# 提案邊界
- 只根據 latest_draft、system_models、conflict_report、feedback 提案。
- 只提出最能讓 draft 更 SRS-ready 的議題：需求語意、範圍、驗收條件、來源追蹤、衝突決議或需求修訂。
- 可以提出 conflict_resolution，但焦點必須是需求語意、範圍、條件、互斥點或可驗證性；外部依據不足時列為待確認事項。
- 議題必須聚焦需求品質、可驗證性、來源追蹤或需求收斂，不提出缺乏需求影響的一般討論。
- 不要替 user 發明新的偏好或需求。
- 最多提出 {max_items} 筆；若沒有必要議題，issues 請輸出空陣列。

# 每筆 issue schema
- title：短標題
- description：說明要解決的需求品質或收斂問題，以及會影響哪些 requirement 欄位
- category：只能是 srs_open_question、requirement_revision、tradeoff_decision、conflict_resolution 其中之一
- participants：從 analyst、expert、modeler、user 挑選，必須包含 analyst；需要使用者回答時加入 user
- discussion_mode：sequential 或 simultaneous
- speaking_order：必須與 participants 成員一致
- source_ids：相關 requirement/conflict/open question/change candidate id；沒有就空陣列
- priority_hint：high / medium / low
- impact_level：high / medium / low
- why_now：說明為何本輪需要處理，而不是延後
- requires_multi_party：true/false
- blocks_decision：true/false
- routing_preference：direct_clarification / formal_meeting / human_decision

# 輸出 JSON
{{"issues": []}}"""
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.analyst_issue_proposals_payload(
                data,
                round_num=int(observation.get("round_num") or 0),
                max_items=max_items,
            )
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": "invalid_issue_proposal_output",
                "format_error": str(e),
                "summary": "Analyst issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"Analyst 提出 {len(proposals)} 筆 issue proposal",
        }

    def analyst_issue_proposals_payload(
        self,
        data: Dict[str, Any],
        *,
        round_num: int,
        max_items: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(data, dict):
            raise ValueError("Analyst issue proposal 必須輸出 JSON object")
        raw_issues = data.get("issues")
        if not isinstance(raw_issues, list):
            raise ValueError("Analyst issue proposal 必須包含 issues list")

        allowed_categories = {
            "conflict_resolution",
            "requirement_revision",
            "srs_open_question",
            "tradeoff_decision",
        }
        allowed_participants = {"analyst", "expert", "modeler", "user"}
        allowed_modes = {"sequential", "simultaneous"}
        allowed_priority = {"high", "medium", "low"}
        allowed_routing = {
            "direct_clarification",
            "formal_meeting",
            "human_decision",
        }
        proposals: List[Dict[str, Any]] = []
        seen = set()
        for idx, row in enumerate(raw_issues, 1):
            if not isinstance(row, dict):
                raise ValueError(f"issues[{idx}] 必須是 object")
            title = str(row.get("title") or "").strip()
            description = str(row.get("description") or "").strip()
            category = str(row.get("category") or "").strip()
            why_now = str(row.get("why_now") or "").strip()
            if not title or not description or not why_now:
                raise ValueError(f"issues[{idx}] 缺少 title/description/why_now")
            if category not in allowed_categories:
                raise ValueError(f"issues[{idx}] category 不合法: {category or '<empty>'}")

            participants = [
                str(x).strip()
                for x in (row.get("participants") or [])
                if str(x).strip()
            ]
            participants = list(dict.fromkeys(participants))
            if not participants or any(p not in allowed_participants for p in participants):
                raise ValueError(f"issues[{idx}] participants 不合法")
            if "analyst" not in participants:
                raise ValueError(f"issues[{idx}] participants 必須包含 analyst")

            mode = str(row.get("discussion_mode") or "").strip()
            if mode not in allowed_modes:
                raise ValueError(f"issues[{idx}] discussion_mode 不合法: {mode or '<empty>'}")
            speaking_order = [
                str(x).strip()
                for x in (row.get("speaking_order") or [])
                if str(x).strip()
            ]
            if set(speaking_order) != set(participants):
                raise ValueError(f"issues[{idx}] speaking_order 必須與 participants 成員一致")

            priority = str(row.get("priority_hint") or "").strip().lower()
            impact = str(row.get("impact_level") or "").strip().lower()
            if priority not in allowed_priority:
                raise ValueError(f"issues[{idx}] priority_hint 不合法: {priority or '<empty>'}")
            if impact not in allowed_priority:
                raise ValueError(f"issues[{idx}] impact_level 不合法: {impact or '<empty>'}")
            routing = str(row.get("routing_preference") or "").strip()
            if routing not in allowed_routing:
                raise ValueError(f"issues[{idx}] routing_preference 不合法: {routing or '<empty>'}")

            source_ids = [
                str(x).strip()
                for x in (row.get("source_ids") or [])
                if str(x).strip()
            ]
            key = (category, title, tuple(source_ids))
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "title": title,
                    "description": description,
                    "category": category,
                    "participants": participants,
                    "discussion_mode": mode,
                    "speaking_order": speaking_order,
                    "source_ids": list(dict.fromkeys(source_ids)),
                    "priority_hint": priority,
                    "impact_level": impact,
                    "why_now": why_now,
                    "requires_multi_party": bool(row.get("requires_multi_party")),
                    "blocks_decision": bool(row.get("blocks_decision")),
                    "routing_preference": routing,
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )
            if len(proposals) >= max_items:
                break
        return proposals

    def get_resolution_options_for_issue(
        self, issue: Dict, artifact: Dict[str, Any]
    ) -> Optional[Dict]:
        output = self.run_conflict_analysis_loop(
            "get_resolution_options_for_issue",
            issue=issue,
            artifact=artifact,
        )
        return output if isinstance(output, dict) else None

    def fetch_resolution_options_for_issue(
        self, issue: Dict, artifact: Dict[str, Any]
    ) -> Optional[Dict]:
        """議題為 Conflict 協調時，整理需求層級處理選項；Analyst 不裁決商業方案。"""
        if issue.get("category") not in ("conflict_resolution",):
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        source_ids = issue.get("source_ids") or []
        conflict_ids = [
            s
            for s in source_ids
            if isinstance(s, str)
            and (s.startswith("PAIR-") or s.startswith("MULTIPLE-"))
        ]
        conflicts = all_conflict_rows(artifact)
        if conflict_ids:
            relevant = [c for c in conflicts if c.get("id") in conflict_ids]
        else:
            relevant = [c for c in conflicts if c.get("label") == "Conflict"]
        if not relevant:
            return None
        context = {
            "issue": issue,
            "conflicts": relevant,
            "requirements": requirement_discussion_pool(artifact),
            "stakeholders": artifact.get("stakeholders", []),
        }
        task = """請針對輸入議題與對應 Conflict/Neutral，整理需求層級的處理選項。

本專案覆蓋規則：
- 本次只做需求層級的處理選項。
- 輸入衝突項目的 label 視為既有判定，不要重新分類 Conflict/Neutral。
- 不要改寫 artifact；只輸出下方指定 JSON。

只輸出一個 JSON 物件，須含：
- resolution_options：每筆含 option、strategy、description、pros、cons、recommendation
- recommended_resolution：建議方案摘要

邊界：
- 只整理需求層級的處理選項，例如調整需求文字、拆分需求、補驗收條件、保留待確認。
- description 必須說明此選項會如何影響需求文字、驗收條件或未決問題。
- 若需要人類裁決，請在 recommendation 中明確標示為待裁決建議。

勿輸出 Markdown 或其它文字。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_issue_response_json(raw)
        except Exception as e:
            raise RuntimeError(f"resolution_options 生成失敗: {e}") from e
        return resolution_options_payload(data)

    def build_issue_response_prompt(
        self,
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_context: Optional[Dict[str, Any]],
    ) -> str:
        issue_text = f"議題 [{issue.get('id', '')}]: {issue.get('title', '')}\n描述: {issue.get('description', '')}"
        issue_id = str(issue.get("id") or "")

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('text', '')}"
                for r in previous_responses
            ]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        context_text = ""
        if artifact_context:
            context_text = f"\n# 當前 artifact 分檔內容（供參考）\n{json.dumps(artifact_context, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = issue.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )
        my_action_text = ""
        agent_actions = issue.get("agent_actions") if isinstance(issue.get("agent_actions"), dict) else {}
        my_action = agent_actions.get("analyst") if isinstance(agent_actions.get("analyst"), dict) else {}
        if my_action:
            my_action_text = (
                "\n# 本輪你的 action\n"
                + json.dumps(my_action, ensure_ascii=False, indent=2)
            )

        skill_section = ""
        skill_context = self.get_optional_skill_context(issue, artifact_context)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪由 agent 自行判斷使用）\n{skill_context}\n"
        allow_suggested_next_action = (
            issue.get("category") != "conflict_resolution"
            and not issue_id.startswith("ELICIT-")
        )

        elicitation_hint = ""
        task_block = ANALYST_ISSUE_TASK
        rules_block = ANALYST_ISSUE_RULES
        if allow_suggested_next_action:
            rules_block += "\n- 若此議題暴露需求缺口，可額外提供 suggested_next_action；它只能是需求工程後續處理建議，例如 direct_clarification 或 new_issue，不代表會議已決策。"
        if issue.get("category") == "conflict_resolution":
            contract = issue.get("response_contract") if isinstance(issue.get("response_contract"), dict) else {}
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            task_block = ANALYST_CONFLICT_ISSUE_TASK
            rules_block = (
                ANALYST_CONFLICT_ISSUE_RULES
                + "\n- 外層只能輸出合法 JSON object；不要 markdown、不要 ```json fence、不要額外說明文字。"
                + "\n- 外層只能有 text 欄位。"
                + "\n- text 必須是 JSON object 字串，不是巢狀 object。"
                + "\n- text JSON 結構必須為 {\"pair_reviews\":[...]}。"
                + "\n- pair_reviews 必須逐筆涵蓋 response_contract.known_pair_ids 中每個 id，不能遺漏、不能新增未知 id。"
                + "\n- 每筆 pair_reviews 都必須有 id、proposed_label、reason。"
                + "\n- proposed_label 只能是 Conflict 或 Neutral。"
                + "\n- 本輪必須涵蓋的 pair id：" + json.dumps(known_pair_ids, ensure_ascii=False)
            )
        if issue_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = ANALYST_ELICITATION_CONTEXT_RULES
            task_block = analyst_elicitation_action_task(stop_phrase)
            rules_block = analyst_elicitation_action_rules(stop_phrase)
        suggested_next_action_json = ""
        if allow_suggested_next_action:
            suggested_next_action_json = """,
    "suggested_next_action": {
        "type": "direct_clarification | new_issue",
        "reason": "為何建議會後安排這一步",
        "target_ids": ["可選，相關 requirement/conflict/issue id"],
        "urgency": "low | medium | high"
    }"""
        if issue.get("category") == "conflict_resolution":
            text_hint = conflict_review_text_hint()
            output_fields = f"    {text_hint}"
        else:
            text_hint = '"text": "針對此議題的完整發言內容"'
            if issue_id.startswith("ELICIT-"):
                output_fields = (
                    f"    {text_hint},\n"
                    '    "target_stakeholders": ["要詢問的 stakeholder 名稱，可一位或多位"]'
                    f"{suggested_next_action_json}"
                )
            else:
                output_fields = (
                    f"    {text_hint},\n"
                    '    "open_questions": [{"to": "目標 agent 名稱", "question": "當下最重要、會影響決策的問題"}]'
                    f"{suggested_next_action_json}"
                )
        return f"""{issue_text}
{prev_text}
{context_text}
{recent_ask_history_text}
    {my_action_text}
    {skill_section}
    {elicitation_hint}

# 任務
{task_block}

# 規則
{rules_block}

# 輸出 JSON
{{
{output_fields}
}}"""
