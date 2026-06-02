# Expert issue logic: propose domain issues and build expert meeting responses.
import json
from typing import Any, Dict, List, Optional

from utils.language import current_output_language

from agents.profile.issue_proposal_prompt import build_issue_proposal_prompt
from agents.profile.conflict_review import conflict_review_text_hint
from agents.profile.issue_response_prompt import (
    READY_TO_CLOSE_QUALITY_GATE,
    STANCE_RESPONSE_TEXT_RULES,
    issue_response_context_sections,
)
from agents.profile.analyst.conflict_store import all_conflict_rows
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import (
    EXPERT_CONFLICT_RESOLUTION_RULES,
    EXPERT_CONFLICT_ISSUE_RULES,
    EXPERT_ELICITATION_CONTEXT_RULES,
    EXPERT_ISSUE_RULES,
    EXPERT_ISSUE_TASK,
    expert_elicitation_action_rules,
    expert_elicitation_action_task,
)


class ExpertIssues:
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 20,
    ) -> List[Dict]:
        opa = self.run_action_loop(
            name="expert_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            build_observation=self.build_expert_issue_observation,
            decide_action=self.decide_expert_issue_action,
            execute_action=self.execute_expert_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    def build_expert_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 20),
            "latest_draft": artifact.get("latest_draft", ""),
            "proposal_context": artifact.get("proposal_context") if isinstance(artifact.get("proposal_context"), dict) else {},
        }

    def decide_expert_issue_action(
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
                "reasoning": "上一輪 Expert issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_issues",
            "params": {},
            "reasoning": "從外部義務、domain risk 與 evidence gap 角度提出需要會議處理的議題。",
        }

    def execute_expert_issue_action(
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
                "format_error": f"Expert issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 20)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "proposal_context": observation.get("proposal_context") or {},
        }
        prompt = build_issue_proposal_prompt(
            agent_label="domain / compliance / risk",
            focus="外部限制、風險、證據缺口或待確認議題",
            common_problem_examples=[
                "同一合規限制或資料保存規則影響多筆需求",
                "安全、隱私、稽核、外部服務限制或證據缺口會改變需求定稿",
                "一組需求需要確認是否轉成 constraint、NFR、risk 或 open question",
            ],
            value_gate=[
                "會阻礙需求規格的外部限制、合規/安全風險、證據依據、品質底線或待確認義務定稿。",
                "需要正式會議確認適用範圍、風險取捨、是否轉成需求或是否交由人類裁決；若只是研究建議或可直接寫入 feedback，不要提出。",
            ],
            reject_rule=(
                "不要提出：一般最佳實務提醒、無明確適用範圍的法規猜測、低影響風險、"
                "可由 research_domain 直接更新 feedback 的事項。若單一限制或風險會影響一組需求、"
                "驗收底線或是否能寫入 SRS，可以提出，但 reason 必須說清楚共同領域問題。"
            ),
            max_items=max_items,
            proposal_context=context["proposal_context"],
        )
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.expert_issue_proposals_payload(
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
                "summary": "Expert issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"Expert 提出 {len(proposals)} 筆 issue proposal",
        }

    def expert_issue_proposals_payload(
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
            raise ValueError("Expert issue proposal 必須直接輸出 issues list")

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
                    "category": str(row.get("category") or "").strip(),
                    "issue_focus": str(row.get("issue_focus") or "").strip(),
                    "expect_outcome": expect_outcome,
                    "sources": sources,
                    "importance": importance,
                    "reason": reason,
                    "proposed_by": "expert",
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
        skill_context = self.get_optional_skill_context(issue, artifact_context)
        sections = issue_response_context_sections(
            issue=issue,
            previous_responses=previous_responses,
            artifact_context=artifact_context,
            skill_context=skill_context,
        )
        issue_text = sections["issue_text"]
        issue_id = sections["issue_id"]
        target_stakeholders = sections["target_stakeholders"]
        prev_text = sections["prev_text"]
        context_text = sections["context_text"]
        recent_ask_history_text = sections["recent_ask_history_text"]
        skill_section = sections["skill_section"]
        category = (issue.get("category") or "").strip()
        contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        expert_expected = expected_actions.get("expert")
        expert_expected_actions = []
        if isinstance(expert_expected, str):
            expert_expected_actions = [str(expert_expected).strip()]
        elif isinstance(expert_expected, list):
            expert_expected_actions = [str(a).strip() for a in expert_expected]

        is_pair_review = (
            category == "resolve_conflict"
            and str(contract.get("type") or "").strip() == "pair_reviews"
        )
        if is_pair_review:
            category_hint = EXPERT_CONFLICT_ISSUE_RULES
        elif category == "resolve_conflict":
            category_hint = EXPERT_CONFLICT_RESOLUTION_RULES
        elif category == "tradeoff":
            category_hint = """# 本議題特別要求（tradeoff）
    - 說明外部限制、證據強度、風險後果，以及在合規/安全底線下不可接受的選項。"""
        elif category == "clarify_requirement":
            category_hint = """# 本議題特別要求（clarify_requirement）
    - 說明需求語意、驗收邊界或風險條件是否需要外部證據支撐。"""
        elif category == "define_boundary":
            category_hint = """# 本議題特別要求（define_boundary）
    - 說明本系統、第三方服務、人工流程或角色責任的外部限制與風險邊界。"""
        elif category == "align_model":
            category_hint = """# 本議題特別要求（align_model）
    - 說明模型揭露的流程、資料、狀態或角色責任是否受到外部限制或風險影響。"""
        else:
            category_hint = ""

        response_rules = """# 回應契約
    - text 必須有依據，不可只表態或宣告最終決議。
    - 若本輪已產生或更新 feedback，text 必須引用本輪 feedback 結果說明它如何影響本議題的限制、風險、證據強度、驗收邊界或可接受方案；不要只說已更新 feedback。
    - 若本輪沒有更新 feedback，但當前專案資料已有與本議題相關的 feedback.json 內容，可以引用既有 findings、constraints、risks 或 recommendations 來支撐發言；若引用既有 feedback，需明確說出引用的是哪一類內容與它支持或揭露的需求點。
    - 只有議題涉及法規、外部標準、支付/退款、資料保存、隱私、安全、稽核、可靠性或高風險營運限制時，才需要 domain research；一般需求語意或模型對齊問題優先使用既有 feedback 或直接發言。
    - 若進行新的 domain research，必須更新 feedback.json，並保留來源 URL；不要只在會議發言中描述研究結論。
    - 不要為了引用 feedback 而硬套無關資料；feedback 與本議題無關時，直接以 Expert 觀點回答。
    - open_questions 只放真正需要後續回答、且會相關限制/風險/驗收邊界的單一具體問題；沒有就輸出空陣列。
    - stance.state 表示本次發言的討論狀態：ready_to_close=資訊已足夠且可讓 mediator 結束本議題；needs_more_discussion=還需要其他參與者補充或回應。
    - 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議的領域限制、風險或處理方案。
""" + READY_TO_CLOSE_QUALITY_GATE + "\n\n" + STANCE_RESPONSE_TEXT_RULES
        if issue_id == "OQ":
            response_rules = """# 回應契約
    - 只回答 description 中的問題；不要做正式議題提案或收斂判斷。
    - 回答需保持 Expert 視角，聚焦領域限制、法規/標準、風險、證據強度或 evidence gap。
    - 不更新專案資料，不輸出 stance。
    - open_questions 預設輸出空陣列；只有問題本身無法回答且需要一個關鍵澄清時，才提出一個 open question。"""
        if target_stakeholders:
            response_rules += (
                "\n    - 若 open_questions 的 to 是 user，問題必須是問議題規劃指定的利害關係人："
                + "、".join(target_stakeholders)
                + "；不得改問其他利害關係人。"
            )

        pair_reviews_json = ""
        text_hint = '"text": "依領域/風險/限制立場對此議題的自然會議發言"'
        if is_pair_review:
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            known_pair_ids_text = json.dumps(known_pair_ids, ensure_ascii=False)
            pair_reviews_json = ""
            response_rules = """# 回應契約
    - 外層輸出只包含 text 欄位的 JSON object。
    - text 必須是 JSON object 字串，不是巢狀 object。
    - text JSON 結構必須為 {"pair_reviews":[...]}。
    - pair_reviews 必須逐筆涵蓋 本輪必須涵蓋的 pair id 中每個 id，不能遺漏、不能新增未知 id。
    - 每筆 pair_reviews 都必須有 id、proposed_label、reason。
    - proposed_label 只能是 Conflict 或 Neutral。
    - reason 必須有依據，不可只表態或宣告最終決議。
    - 本輪必須涵蓋的 pair id：""" + known_pair_ids_text
            text_hint = conflict_review_text_hint()
            output_fields = f"    {text_hint}"
        elif issue_id == "OQ":
            output_fields = (
                '    "text": "直接回答問題",\n'
                '    "open_questions": []'
            )
        elif issue_id.startswith("ELICIT-"):
            output_fields = (
                f"    {text_hint},\n"
                '    "target_stakeholders": ["要詢問的 stakeholder 名稱，可一位或多位"]'
                f"{pair_reviews_json}"
            )
        else:
            output_fields = (
                f"    {text_hint},\n"
                '    "open_questions": [{"to": "目標參與者名稱（user、analyst、expert、modeler）", "question": "當下最重要、會相關決策的問題"}]'
                ',\n    "stance": {"state": "ready_to_close | needs_more_discussion", "proposal": {"summary": "建議方案", "rationale": "理由", "tradeoffs": ["取捨或限制"]}}'
                f"{pair_reviews_json}"
            )

        elicitation_hint = ""
        task_block = EXPERT_ISSUE_TASK
        rules_block = EXPERT_ISSUE_RULES
        if issue_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = EXPERT_ELICITATION_CONTEXT_RULES
            task_block = expert_elicitation_action_task(stop_phrase)
            rules_block = expert_elicitation_action_rules(stop_phrase)
        return f"""{issue_text}
    {prev_text}
    {context_text}
    {recent_ask_history_text}
    {skill_section}
    {category_hint}
    {elicitation_hint}

    {response_rules}

    # 任務
    {task_block}

    # 規則
    {rules_block}

    # 輸出 JSON
    {{
{output_fields}
    }}"""
