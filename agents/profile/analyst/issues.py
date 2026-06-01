# Analyst issue logic: propose meeting issues and build analyst meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language

from agents.profile.issue_proposal_prompt import build_issue_proposal_prompt
from agents.profile.conflict_review import (
    CONFLICT_REVIEW_LABEL_RULES,
    CONFLICT_REVIEW_REASON_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
    conflict_review_text_hint,
)
from agents.profile.issue_response_prompt import READY_TO_CLOSE_QUALITY_GATE, STANCE_RESPONSE_TEXT_RULES

from .prompts import (
    ANALYST_ELICITATION_CONTEXT_RULES,
    analyst_elicitation_action_rules,
    analyst_elicitation_action_task,
)


ANALYST_ISSUE_TASK = (
    "聚焦需求意圖、需求範圍、需求條目品質、驗收條件、"
    "來源追蹤與未決缺口。"
)

ANALYST_ISSUE_RULES = """- text 需說明：此議題對需求的相關、目前可確認的需求內容、仍不可寫入正式需求的缺口、以及建議的需求處理方式。
- 依據優先引用 requirement id、conflict id、stakeholder 觀點、既有討論或議題描述。
- 判斷重點是需求是否清楚、可驗收、可追蹤、範圍是否穩定、是否需要拆成功能需求、非功能需求、限制條件或保留為未決問題。
- 若提出需求修正，必須指出要改哪個欄位：需求文字、優先級、驗收條件或來源追蹤。
- 若資訊不足，請說明缺少哪個可寫入需求的必要訊號，而不是只說需要更多資訊。
- 若需要他人補資訊，才在 open_questions 中提出能直接支援需求修正的具體問題。
- open_questions 的 to 欄位只能用系統角色名：user、analyst、expert、modeler；禁止用利害關係人名稱。
- 若建議新增或修改需求，請說明應落在需求、驗收條件或未決問題哪一類。"""

ANALYST_CONFLICT_RESOLUTION_TASK = (
    "直接針對既有衝突報告中的解決選項與建議解法做取捨。"
)

ANALYST_CONFLICT_RESOLUTION_RULES = """- 不重新判斷 Conflict/Neutral，也不重新執行 conflict detection。
- 以衝突報告已提供的解決選項與建議解法為主要討論對象。
- text 需說明：哪些既有方案可採用、哪些需要調整、調整理由、以及會影響哪些需求或驗收條件。
- 必須把結論落到 URL 層級：在 stance.proposal.url_updates 輸出 keep / revise / remove；revise 必須給出改寫後 text。
- url_updates 不得把多筆 URL 串成一筆巨大需求；若需要語意整合，應保留 URL 粒度並在後續 REQ 中整合。
- 若會議內容已足以採用或調整某個 resolution，stance.state 填 ready_to_close，stance.proposal 填具體建議方案與 url_updates。
- 若缺少業務取捨、領域規則或模型影響判斷，stance.state 填 needs_more_discussion，stance.proposal 仍須填目前最合理的候選方案或可裁決選項；不要提出 open_questions。
- 若無法在會議中做出內容抉擇，stance.proposal 應整理可交由人類裁決的方案，而不是要求重新分析衝突或延長討論。"""

ANALYST_CONFLICT_ISSUE_TASK = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "先根據 User Requirements（URL-*）原文獨立重判，並將重判結果填入 proposed_label。"
)

ANALYST_CONFLICT_ISSUE_RULES = f"""{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- 先只根據 User Requirements（URL-*）原文獨立判斷 proposed_label；不要先順著既有標籤想理由。
- reason 必須寫成完整審查意見：說明獨立判斷依據，並說明需求語意、範圍、條件、互斥點或可驗證性；不要只重述兩句需求文字。
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
        max_items: int = 5,
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
                        "ids": [cid] + list(c.get("requirement_ids", []) or []),
                        "summary": str(c.get("description") or "").strip(),
                    }
                )

        for oq in artifact.get("open_questions", []) or []:
            if not isinstance(oq, dict) or oq.get("status") == "answered":
                continue
            question = str(oq.get("question") or "").strip()
            if question:
                signals.append(
                    {
                        "kind": "unanswered_open_question",
                        "ids": [
                            str(oq.get("source_conflict_id") or "").strip()
                        ] if str(oq.get("source_conflict_id") or "").strip() else [],
                        "summary": question,
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
                        "ids": [rid],
                        "summary": text,
                        "issues": issues,
                    }
                )

        return signals

    def build_analyst_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 5),
            "latest_draft": artifact.get("latest_draft", ""),
            "proposal_context": artifact.get("proposal_context") if isinstance(artifact.get("proposal_context"), dict) else {},
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
            "action": "propose_issues",
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
        if action != "propose_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"Analyst issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 5)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "proposal_context": observation.get("proposal_context") or {},
        }
        prompt = build_issue_proposal_prompt(
            agent_label="需求工程",
            focus="需求語意、範圍、驗收條件、來源追蹤或需求規格化",
            common_problem_examples=[
                "同一流程下多筆需求的狀態規則不清楚",
                "一組需求的責任邊界或 scope 影響未定",
                "多筆需求缺少共同驗收標準或來源追蹤",
            ],
            value_gate=[
                "會阻礙需求規格定稿、需求可驗收性、scope 穩定或來源追蹤。",
                "需要正式會議中的至少兩方觀點、取捨、確認或決策；若 analyst 可直接修稿或整理，不要提出。",
            ],
            reject_rule=(
                "不要提出：措辭潤飾、單一欄位補字、單一 acceptance criteria 補充、"
                "一般最佳實務提醒、無 source id 的猜測、小型重複問題。"
                "若單一 id 代表較大的流程、狀態、責任邊界、驗收標準或風險面向，"
                "可以提出，但 reason 必須說清楚共同問題。"
            ),
            max_items=max_items,
            proposal_context=context["proposal_context"],
        )
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
        raw_issues = data
        if isinstance(raw_issues, dict):
            raw_issues = raw_issues.get("issues") or raw_issues.get("proposals") or []
        if not isinstance(raw_issues, list):
            raise ValueError("Analyst issue proposal 必須直接輸出 issues list")

        allowed_importance = {"high", "medium", "low"}
        proposals: List[Dict[str, Any]] = []
        seen = set()
        for idx, row in enumerate(raw_issues, 1):
            if not isinstance(row, dict):
                raise ValueError(f"issues[{idx}] 必須是 object")
            title = str(row.get("title") or "").strip()
            if not title:
                raise ValueError(f"issues[{idx}] 缺少 title")
            expect_outcome = str(row.get("expect_outcome") or "").strip()
            sources = []
            for source in row.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                artifact = str(source.get("artifact") or "").strip()
                ids = [
                    str(x).strip()
                    for x in (source.get("ids") or [])
                    if str(x).strip()
                ]
                evidence = str(source.get("evidence") or "").strip()
                if artifact and evidence:
                    sources.append({"artifact": artifact, "ids": list(dict.fromkeys(ids)), "evidence": evidence})
            reason = str(row.get("reason") or "").strip()
            if not expect_outcome or not sources or not reason:
                raise ValueError(f"issues[{idx}] 缺少 expect_outcome/sources/reason")

            importance = str(row.get("importance") or "").strip().lower()
            if importance not in allowed_importance:
                raise ValueError(f"issues[{idx}] importance 不合法: {importance or '<empty>'}")

            key = (title, json.dumps(sources, ensure_ascii=False, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "title": title,
                    "expect_outcome": expect_outcome,
                    "sources": sources,
                    "importance": importance,
                    "reason": reason,
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )
            if len(proposals) >= max_items:
                break
        return proposals

    def build_issue_response_prompt(
        self,
        *,
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_context: Optional[Dict[str, Any]],
    ) -> str:
        issue_text = f"議題 [{issue.get('id', '')}]: {issue.get('title', '')}\n描述: {issue.get('description', '')}"
        issue_id = str(issue.get("id") or "")
        target_stakeholders = [
            str(name).strip()
            for name in (issue.get("target_stakeholders") or [])
            if str(name).strip()
        ]

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('text', '')}"
                for r in previous_responses
            ]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        context_text = ""
        if artifact_context:
            context_text = f"\n# 當前專案資料（供參考）\n{json.dumps(artifact_context, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = issue.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )
        skill_section = ""
        skill_context = self.get_optional_skill_context(issue, artifact_context)
        if skill_context:
            skill_section = f"\n# 可用技能參考（本輪自行判斷使用）\n{skill_context}\n"
        elicitation_hint = ""
        task_block = ANALYST_ISSUE_TASK
        rules_block = ANALYST_ISSUE_RULES
        if issue_id == "OQ":
            task_block = "以需求分析角度直接回答提問。"
            rules_block = """- 只回答 description 中的問題；不要做正式議題提案或收斂判斷。
- 回答需聚焦需求語意、scope、驗收條件、來源追蹤或需求缺口。
- 不更新專案資料，不輸出 stance。
- open_questions 預設輸出空陣列；只有問題本身無法回答且需要一個關鍵澄清時，才提出一個 open question。"""
        if target_stakeholders and issue_id != "OQ":
            rules_block += (
                "\n- 若 open_questions 的 to 是 user，問題必須是問議題規劃指定的利害關係人："
                + "、".join(target_stakeholders)
                + "；不得改問其他利害關係人。"
            )
        if issue_id != "OQ" and not issue_id.startswith("ELICIT-"):
            rules_block += "\n" + STANCE_RESPONSE_TEXT_RULES
        if issue_id != "OQ" and not issue_id.startswith("ELICIT-") and issue.get("category") != "resolve_conflict":
            rules_block += (
                "\n- stance.state 表示本次發言的討論狀態："
                "ready_to_close=資訊已足夠且可讓 mediator 結束本議題；"
                "needs_more_discussion=還需要其他參與者補充或回應。"
                "\n- 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議的需求處理方案。"
                "\n"
                + READY_TO_CLOSE_QUALITY_GATE
            )
        contract = issue.get("response_contract") if isinstance(issue.get("response_contract"), dict) else {}
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        analyst_expected = expected_actions.get("analyst")
        analyst_expected_actions = []
        if isinstance(analyst_expected, str):
            analyst_expected_actions = [str(analyst_expected).strip()]
        elif isinstance(analyst_expected, list):
            analyst_expected_actions = [str(a).strip() for a in analyst_expected]
        is_pair_review = (
            issue.get("category") == "resolve_conflict"
            and str(contract.get("type") or "").strip() == "pair_reviews"
        )
        if is_pair_review:
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            task_block = ANALYST_CONFLICT_ISSUE_TASK
            rules_block = (
                ANALYST_CONFLICT_ISSUE_RULES
                + "\n- 外層輸出只包含 text 欄位的 JSON object。"
                + "\n- text 必須是 JSON object 字串，不是巢狀 object。"
                + "\n- text JSON 結構必須為 {\"pair_reviews\":[...]}。"
                + "\n- pair_reviews 必須逐筆涵蓋 本輪必須涵蓋的 pair id 中每個 id，不能遺漏、不能新增未知 id。"
                + "\n- 每筆 pair_reviews 都必須有 id、proposed_label、reason。"
                + "\n- proposed_label 只能是 Conflict 或 Neutral。"
                + "\n- 本輪必須涵蓋的 pair id：" + json.dumps(known_pair_ids, ensure_ascii=False)
            )
        elif issue.get("category") == "resolve_conflict":
            task_block = ANALYST_CONFLICT_RESOLUTION_TASK
            rules_block = ANALYST_CONFLICT_RESOLUTION_RULES
        elif issue.get("category") == "clarify_requirement":
            rules_block += "\n- 本議題聚焦釐清需求語意、條件、成功結果與驗收方式；不要擴張未被來源支持的新需求。"
        elif issue.get("category") == "define_boundary":
            rules_block += "\n- 本議題聚焦系統、外部服務、人工流程與角色責任邊界；請明確指出應寫入 scope、requirement 或 open question 的結果。"
        elif issue.get("category") == "tradeoff":
            rules_block += "\n- 本議題聚焦方案比較、取捨與推薦；stance.proposal 必須提出可落地的需求處理方案。"
        elif issue.get("category") == "align_model":
            rules_block += "\n- 本議題聚焦模型揭露的流程、狀態、actor、資料或權限不一致；請指出應更新需求、模型或 open question。"
        if issue_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = ANALYST_ELICITATION_CONTEXT_RULES
            task_block = analyst_elicitation_action_task(stop_phrase)
            rules_block = analyst_elicitation_action_rules(stop_phrase)
        if issue_id == "OQ":
            output_fields = (
                '    "text": "直接回答問題",\n'
                '    "open_questions": []'
            )
        elif is_pair_review:
            text_hint = conflict_review_text_hint()
            output_fields = f"    {text_hint}"
        else:
            text_hint = '"text": "依需求分析立場對此議題的自然會議發言"'
            if issue_id.startswith("ELICIT-"):
                output_fields = (
                    f"    {text_hint},\n"
                    '    "target_stakeholders": ["要詢問的 stakeholder 名稱，可一位或多位"]'
                )
            else:
                output_fields = (
                    f"    {text_hint},\n"
                    '    "open_questions": [{"to": "目標參與者名稱（user、analyst、expert、modeler）", "question": "當下最重要、會相關決策的問題"}]'
                    ',\n    "stance": {"state": "ready_to_close | needs_more_discussion", "proposal": {"summary": "建議方案", "rationale": "理由", "tradeoffs": ["取捨或限制"]}}'
                )
        return f"""{issue_text}
{prev_text}
{context_text}
{recent_ask_history_text}
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
