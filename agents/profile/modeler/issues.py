# Modeler issue logic: propose model issues and build modeler meeting responses.
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
from agents.profile.analyst.requirements import requirement_discussion_pool

from .prompts import (
    MODELER_CONFLICT_RESOLUTION_RULES,
    MODELER_CONFLICT_RESOLUTION_TASK,
    MODELER_CONFLICT_ISSUE_RULES,
    MODELER_CONFLICT_ISSUE_TASK,
    MODELER_ELICITATION_CONTEXT_RULES,
    MODELER_ISSUE_RULES,
    MODELER_ISSUE_TASK,
    modeler_elicitation_action_rules,
    modeler_elicitation_action_task,
)


class ModelerIssues:
    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 20,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="modeler_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            build_observation=self.build_modeler_issue_observation,
            decide_action=self.decide_modeler_issue_action,
            execute_action=self.execute_modeler_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    def build_model_issue_signals(self, artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        models = self.system_model_rows(artifact)
        baseline_candidate_types = {
            "context_diagram",
            "use_case_diagram",
            "activity_diagram",
        }
        existing_types = {m.get("type") for m in models if m.get("type")}
        missing = sorted(list(baseline_candidate_types - existing_types))
        if missing:
            signals.append(
                {
                    "kind": "baseline_candidate_gap",
                    "ids": [f"SM-GAP-{mtype}" for mtype in missing],
                    "missing_diagram_types": missing,
                    "summary": (
                        "目前沒有部分候選基礎模型；只有在缺少模型會阻礙需求討論、"
                        "流程理解、系統邊界或追蹤性時才需要提案。"
                    ),
                }
            )

        return signals

    def build_modeler_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 20),
            "latest_draft": artifact.get("latest_draft", ""),
            "proposal_context": artifact.get("proposal_context") if isinstance(artifact.get("proposal_context"), dict) else {},
        }

    def decide_modeler_issue_action(
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
                "reasoning": "上一輪 Modeler issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_issues",
            "params": {},
            "reasoning": "根據需求、既有模型、模型缺口與近期決策判斷是否需要提出建模相關議題。",
        }

    def execute_modeler_issue_action(
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
                "format_error": f"Modeler issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 20)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "proposal_context": observation.get("proposal_context") or {},
        }
        prompt = build_issue_proposal_prompt(
            agent_label="需求建模",
            focus="模型一致性、系統邊界、actor/use case、流程、資料或狀態缺口",
            common_problem_examples=[
                "同一流程或狀態規則在多筆需求中不一致",
                "actor、use case、資料生命週期或系統邊界無法對齊",
                "模型揭露出一組需求的責任分工或狀態轉換仍未確認",
            ],
            value_gate=[
                "會阻礙需求規格中的流程、角色、資料、狀態、系統邊界或模型追蹤性的定稿。",
                "需要正式會議確認需求語意、角色責任、流程分歧、資料狀態或模型影響；若 modeler 可直接建立或更新模型，不要提出。",
            ],
            reject_rule=(
                "不要提出：單純補圖、命名調整、版面修正、可由建模 action 直接處理的模型生成工作。"
                "若單一模型缺口代表較大的流程、狀態、資料生命週期或責任邊界問題，"
                "可以提出，但 reason 必須說清楚共同模型問題。"
            ),
            max_items=max_items,
            proposal_context=context["proposal_context"],
        )
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.modeler_issue_proposals_payload(
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
                "summary": "Modeler issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"Modeler 提出 {len(proposals)} 筆 issue proposal",
        }

    def modeler_issue_proposals_payload(
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
            raise ValueError("Modeler issue proposal 必須直接輸出 issues list")

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
                    "proposed_by": "modeler",
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
        elicitation_hint = ""
        task_block = MODELER_ISSUE_TASK
        rules_block = MODELER_ISSUE_RULES
        if issue_id == "OQ":
            task_block = "以建模角度直接回答提問。"
            rules_block = """- 只回答 description 中的問題；不要做正式議題提案或收斂判斷。
- 回答需聚焦流程、狀態、資料、actor/use case、責任邊界或 system model 影響。
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
        if issue_id != "OQ" and not issue_id.startswith("ELICIT-") and (issue.get("category") or "").strip() != "resolve_conflict":
            rules_block += (
                "\n- stance.state 表示本次發言的討論狀態："
                "ready_to_close=資訊已足夠且可讓 mediator 結束本議題；"
                "needs_more_discussion=還需要其他參與者補充或回應。"
                "\n- 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議的模型或需求邊界處理方案。"
                "\n"
                + READY_TO_CLOSE_QUALITY_GATE
            )
        category = (issue.get("category") or "").strip()
        contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        modeler_expected = expected_actions.get("modeler")
        modeler_expected_actions = []
        if isinstance(modeler_expected, str):
            modeler_expected_actions = [str(modeler_expected).strip()]
        elif isinstance(modeler_expected, list):
            modeler_expected_actions = [str(a).strip() for a in modeler_expected]

        is_pair_review = (
            category == "resolve_conflict"
            and str(contract.get("type") or "").strip() == "pair_reviews"
        )
        if is_pair_review:
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            task_block = MODELER_CONFLICT_ISSUE_TASK
            rules_block = (
                MODELER_CONFLICT_ISSUE_RULES
                + "\n- 外層輸出只包含 text 欄位的 JSON object。"
                + "\n- text 必須是 JSON object 字串，不是巢狀 object。"
                + "\n- text JSON 結構必須為 {\"pair_reviews\":[...]}。"
                + "\n- pair_reviews 必須逐筆涵蓋 本輪必須涵蓋的 pair id 中每個 id，不能遺漏、不能新增未知 id。"
                + "\n- 每筆 pair_reviews 都必須有 id、proposed_label、reason。"
                + "\n- proposed_label 只能是 Conflict 或 Neutral。"
                + "\n- 本輪必須涵蓋的 pair id：" + json.dumps(known_pair_ids, ensure_ascii=False)
            )
        elif category == "resolve_conflict":
            task_block = MODELER_CONFLICT_RESOLUTION_TASK
            rules_block = MODELER_CONFLICT_RESOLUTION_RULES
        elif category == "align_model":
            rules_block += "\n- 本議題聚焦模型揭露的流程、狀態、actor、use case、資料或權限不一致；請明確指出需求與模型如何對齊。"
        elif category == "define_boundary":
            rules_block += "\n- 本議題聚焦系統邊界、外部系統、人工流程與角色責任；請用模型觀點說明邊界影響。"
        elif category == "clarify_requirement":
            rules_block += "\n- 本議題聚焦需求語意、條件、成功結果與驗收方式；請指出模型是否需要補充流程或狀態。"
        elif category == "tradeoff":
            rules_block += "\n- 本議題聚焦方案取捨；請比較各方案對流程、狀態、資料與 actor 的影響。"
        if issue_id != "OQ" and not issue_id.startswith("ELICIT-"):
            rules_block += (
                "\n- 若本輪已產生或更新 System Models 或模型一致性報告，"
                "text 必須引用本輪模型結果說明它如何釐清需求、流程、狀態、actor/use case、資料或責任邊界；"
                "不要只說已建立或已更新模型。"
                "\n- 若本輪沒有產生新模型，但當前專案資料已有與本議題相關的 System Models，"
                "可以引用既有圖中的 actor、use case、流程、狀態、資料或邊界來支撐發言；"
                "若引用既有圖，需明確說出引用哪張圖與它支持或揭露的需求點。"
                "\n- 只能引用「當前專案資料」中實際存在的 system_models id/name；不要說有 SM-*、use case diagram 或 activity diagram，除非它真的出現在輸入資料或本輪 action result。"
                "\n- 若當前專案資料沒有可引用的 system_models，明確說目前沒有可引用模型；若本議題需要模型支撐，應選 model_system，而不是假設已有模型。"
                "\n- 若模型揭露流程缺口、狀態不明、責任邊界不清或資料流不一致，必須明確說明應轉成哪一類後續處理：更新需求、提出 open question、建立/更新模型，或交由 define_boundary 議題處理。"
                "\n- 模型新增或更新後，應說明它支援哪些 REQ-*，並避免從模型反推未被需求來源支持的新需求。"
                "\n- 不要為了引用模型而硬解讀無關的圖；模型與本議題無關時，直接用文字建模觀點回答。"
            )
        if issue_id.startswith("ELICIT-"):
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = MODELER_ELICITATION_CONTEXT_RULES
            task_block = modeler_elicitation_action_task(stop_phrase)
            rules_block = modeler_elicitation_action_rules(stop_phrase)
        pair_reviews_json = ""
        text_hint = '"text": "依需求建模立場對此議題的自然會議發言"'
        if issue_id == "OQ":
            output_fields = (
                '    "text": "直接回答問題",\n'
                '    "open_questions": []'
            )
        elif is_pair_review:
            pair_reviews_json = ""
            text_hint = conflict_review_text_hint()
            output_fields = f"    {text_hint}"
        else:
            if issue_id.startswith("ELICIT-"):
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
