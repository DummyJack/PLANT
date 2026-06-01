# User issue logic: propose stakeholder issues and build user-perspective responses.
import json
from typing import Any, Dict, List, Optional

from agents.profile.issue_proposal_prompt import build_issue_proposal_prompt
from agents.profile.conflict_review import conflict_review_text_hint
from agents.profile.analyst.requirements import requirement_discussion_pool
from agents.profile.issue_response_prompt import READY_TO_CLOSE_QUALITY_GATE, STANCE_RESPONSE_TEXT_RULES


class UserIssues:
    def build_stakeholder_contract(
        self,
        artifact_context: Optional[Dict[str, Any]],
    ) -> str:
        rough_idea = ""
        if isinstance(artifact_context, dict):
            rough_idea = str(artifact_context.get("rough_idea") or "").strip()
        role_parts = []
        allowed_names: List[str] = []
        for sh in self.stakeholders or []:
            name = str(sh.get("name") or "").strip()
            if not name:
                continue
            allowed_names.append(name)
            texts = sh.get("text") or []
            if isinstance(texts, list):
                needs = "\n".join(f"  - {str(t).strip()}" for t in texts if str(t).strip())
            else:
                needs = f"  - {str(texts).strip()}" if str(texts).strip() else ""
            role_parts.append(f"【{name}】\n{needs or '  - 待補'}")
        if not role_parts:
            return ""
        return (
            "\n# 利害關係人回答約束（必須遵守）\n"
            f"原始產品情境：{rough_idea or '（未提供）'}\n\n"
            "只能代表本專案已選定的情境利害關係人發言；不得新增其他回答身份或轉向其他產品情境。\n\n"
            + "\n\n".join(role_parts)
            + "\n\n規則：\n"
            "- 每個需求、顧慮、例外情境都必須能明確回扣原始產品情境。\n"
            "- 若問題很泛，請主動拉回上述產品情境與已選利害關係人日常使用場景。\n"
            "- 不得代表未列出的利害關係人發言；不得把產品轉成資料權限、人資、薪資、通用內部管理等無關系統。\n"
            f"- speaking_as 只能從這些名稱選擇：{', '.join(allowed_names)}。\n"
        )

    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 5,
    ) -> List[Dict[str, Any]]:
        opa = self.run_action_loop(
            name="user_issue_proposal",
            context={
                "artifact": artifact,
                "round_num": round_num,
                "max_items": max(1, max_items),
            },
            build_observation=self.build_user_issue_observation,
            decide_action=self.decide_user_issue_action,
            execute_action=self.execute_user_issue_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("format_error") or result.get("error"))
        return result.get("proposals", [])[: max(1, max_items)]

    def build_user_issue_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs["artifact"]
        return {
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs["max_iterations"],
            "round_num": kwargs.get("round_num"),
            "max_items": kwargs.get("max_items", 5),
            "latest_draft": artifact.get("latest_draft", ""),
            "proposal_context": artifact.get("proposal_context") if isinstance(artifact.get("proposal_context"), dict) else {},
        }

    def decide_user_issue_action(
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
                "reasoning": "上一輪 User issue proposal 已符合格式契約，結束提案。",
            }
        return {
            "action": "propose_issues",
            "params": {},
            "reasoning": "根據利害關係人情境、未回答問題與既有需求判斷是否提出使用者視角議題。",
        }

    def execute_user_issue_action(
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
                "format_error": f"User issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 5)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "proposal_context": observation.get("proposal_context") or {},
        }
        prompt = build_issue_proposal_prompt(
            agent_label="使用者 / 利害關係人",
            focus="使用者語意、使用邊界、責任歸屬、可接受條件或待確認議題",
            common_problem_examples=[
                "同一角色責任或使用流程下多筆需求需要利害關係人表態",
                "一組需求的成功條件、接受底線或不可接受情況未定",
                "多個角色對同一流程、責任或取捨方向有拉扯",
            ],
            value_gate=[
                "會阻礙需求規格定稿、使用者需求確認、責任邊界、可接受條件或重要 tradeoff。",
                "需要指定利害關係人進入正式會議表態、確認或取捨；若只是一般偏好、細節補充或可從 draft 直接整理，不要提出。",
            ],
            reject_rule=(
                "不要提出：泛泛使用者意見、低影響 UI 偏好、沒有明確利害關係人的小問題、"
                "可直接寫成草稿修正的內容。若單一缺口會影響一組需求的使用底線、"
                "責任歸屬或驗收方式，可以提出，但 reason 必須說清楚共同利害關係人問題。"
            ),
            max_items=max_items,
            proposal_context=context["proposal_context"],
        )
        try:
            data = self.chat_json(self.build_direct_messages(prompt, context=context))
            proposals = self.user_issue_proposals_payload(
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
                "summary": "User issue proposal 輸出格式不合格",
            }
        return {
            "action": action,
            "status": "success",
            "proposals": proposals,
            "summary": f"User 提出 {len(proposals)} 筆 issue proposal",
        }

    def user_issue_proposals_payload(
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
            raise ValueError("User issue proposal 必須直接輸出 issues list")

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
                    "proposed_by": "user",
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
        issue_category = (issue.get("category") or "").strip()
        stakeholder_contract = self.build_stakeholder_contract(artifact_context)
        target_stakeholders = [
            str(x).strip()
            for x in (issue.get("target_stakeholders") or [])
            if str(x).strip()
        ]
        target_set = set(target_stakeholders)
        answer_all_questions = bool(issue.get("answer_all_interviewer_questions"))

        speaking_as_list = []
        names_list: List[str] = []
        if self.stakeholders and target_set:
            speaking_as_list = [
                sh for sh in self.stakeholders
                if str(sh.get("name") or "").strip() in target_set
            ]
        if self.stakeholders and not speaking_as_list:
            if len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []  # 多位時交由系統擇一或擇多立場發言

        if len(speaking_as_list) == 1:
            sh = speaking_as_list[0]
            name = sh.get("name", "")
            names_list = [name]
            roles_text = f"\n# 本輪發言身份\n請「僅」以【{name}】的身份發言。"
        elif len(speaking_as_list) > 1:
            names = [s.get("name", "") for s in speaking_as_list]
            names_list = list(names)
            roles_text = (
                f"\n# 本輪發言身份（多位）\n請以【{'】與【'.join(names)}】的身份發言；若分段表述，請標明身份。"
            )
        elif self.stakeholders:
            names_list = [sh.get("name", "") for sh in self.stakeholders]
            roles_text = (
                "\n# 本輪回答身份\n"
                "本輪未指定回答身份；請只選擇與此議題最直接相關的一位或多位利害關係人發言，不要代表全部利害關係人泛泛回答。"
            )
        else:
            names_list = []
            roles_text = ""
        if target_stakeholders:
            roles_text += (
                "\n# 本輪指定回答身份\n"
                f"本輪身份由議題規劃指定，只能代表這些利害關係人回答：{', '.join(target_stakeholders)}。\n"
                "不得自行切換到其他利害關係人；如果問題不適合指定身份，請以該身份說明不適用或缺少情境。\n"
            )

        prev_text = self.format_previous_responses(
            previous_responses, title="前面的發言"
        )

        context_text = ""
        if artifact_context:
            context_text = f"\n# 當前專案資料（供參考）\n{json.dumps(artifact_context, ensure_ascii=False, indent=2)}"
        is_elicitation = str(issue.get("id") or "").startswith("ELICIT-")
        is_answer_question = str(issue.get("id") or "") == "OQ"

        # 多位時輸出要含 speaking_as；一位時不必
        need_speaking_as = len(self.stakeholders) > 1
        if need_speaking_as:
            json_hint = '"speaking_as": ["本輪發言身份名稱"], "text": "完整發言內容"'
            if not is_elicitation:
                json_hint += ', "open_questions": [...]'
            flow_hint = "依議題規劃指定的 speaking_as，說明該身份在此議題上的立場、需求與底線。"
        else:
            json_hint = '"text": "針對此議題的完整發言內容"'
            if not is_elicitation:
                json_hint += ', "open_questions": [...]'
            flow_hint = "以第一人稱撰寫一段完整發言，說明立場、需求與底線。"
        if answer_all_questions:
            flow_hint = (
                "逐題回答前面每一位參與者提出的問題；text 內請用「發問者 → 回答身份」分段，"
                "每題都要明確回答，不要只回最後一題。"
            )

        expected_actions = issue.get("expected_actions") if isinstance(issue.get("expected_actions"), dict) else {}
        user_expected = expected_actions.get("user")
        user_expected_actions = []
        if isinstance(user_expected, str):
            user_expected_actions = [str(user_expected).strip()]
        elif isinstance(user_expected, list):
            user_expected_actions = [str(a).strip() for a in user_expected]

        category_hint = ""
        if issue_category == "clarify_requirement":
            category_hint = (
                "\n# 本議題特別說明（clarify_requirement）\n"
                "聚焦需求語意、使用條件、成功結果、例外情境與可接受的驗收方式。"
            )
            if str(issue.get("title") or "").strip() == "需求分類":
                category_hint = (
                    "\n# 本議題特別說明（需求分類）\n"
                    "先閱讀前面 Analyst 產生或更新的 REQ-* 整理結果，再以 speaking_as 身份檢查："
                    "是否漏掉重要使用情境、業務規則或例外條件；"
                    "驗收條件是否可接受；優先級是否符合實際需要；"
                    "限制、風險或假設是否正確。"
                )
        elif issue_category == "define_boundary":
            category_hint = (
                "\n# 本議題特別說明（define_boundary）\n"
                "說明此需求在實際使用上應由本系統、外部服務、人工流程或哪個角色負責。"
            )
        elif issue_category == "tradeoff":
            category_hint = (
                "\n# 本議題特別說明（tradeoff）\n"
                "比較可接受與不可接受方案，說明取捨底線與推薦方向。"
            )
        elif issue_category == "align_model":
            category_hint = (
                "\n# 本議題特別說明（align_model）\n"
                "從使用者/利害關係人角度確認流程、狀態、actor 或責任分工是否符合實際情境。"
            )
        elif issue_category == "resolve_conflict":
            contract = issue.get("response_contract") if isinstance(issue.get("response_contract"), dict) else {}
            is_pair_review = (
                str(contract.get("type") or "").strip() == "pair_reviews"
            )
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            if is_pair_review:
                category_hint = (
                    "\n# 本議題特別說明（resolve_conflict）\n"
                    "從實際使用情境說明兩項需求是否衝突、重複、可共存或資訊不足。\n"
                    "- 外層輸出只包含 text 欄位的 JSON object。\n"
                    "- text 必須是 JSON object 字串，不是巢狀 object。\n"
                    "- text JSON 結構必須為 {\"pair_reviews\":[...]}。\n"
                    "- pair_reviews 必須逐筆涵蓋 本輪必須涵蓋的 pair id 中每個 id，不能遺漏、不能新增未知 id。\n"
                    "- 每筆 pair_reviews 都必須有 id、proposed_label、reason。\n"
                    "- proposed_label 只能是 Conflict 或 Neutral。\n"
                    f"- 本輪必須涵蓋的 pair id：{json.dumps(known_pair_ids, ensure_ascii=False)}"
                )
            else:
                category_hint = (
                    "\n# 本議題特別說明（resolve_conflict）\n"
                    "逐一針對 conflict report 中列出的 URL 需求與既有 resolution option 表態。\n"
                    "- 不泛談整體平台感受。\n"
                    "- 明確說出哪些 URL 的內容可以合併、保留、改寫或不可接受。\n"
                    "- 說明此 speaking_as 的最低可接受條件、不能被刪掉的語意，以及需要保留的例外情境。\n"
                    "- 不提出 open_questions；資訊不足時直接說明目前可接受的保守處理方式。"
                )
        open_questions_rule = "" if is_elicitation else "- 若需要他人補資訊，只把當下最重要、會相關決策的一個問題放進 open_questions。\n"
        if is_answer_question:
            open_questions_rule = "- open_questions 預設輸出空陣列；只有問題本身無法回答且需要一個關鍵澄清時，才提出一個 open question。\n"
        stance_rule = "" if is_elicitation or issue_category == "resolve_conflict" or is_answer_question else (
            "- stance.state 表示本輪 speaking_as 身份的討論狀態："
            "ready_to_close=資訊已足夠且可結束本議題；"
            "needs_more_discussion=還需要其他參與者補充或回應。\n"
            "- 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議如何處理此議題。\n"
            f"{READY_TO_CLOSE_QUALITY_GATE}\n"
        )
        stance_json = "" if is_elicitation or issue_category == "resolve_conflict" or is_answer_question else (
            ', "stance": {"state": "ready_to_close | needs_more_discussion", "proposal": {"summary": "建議方案", "rationale": "理由", "tradeoffs": ["取捨或限制"]}}'
        )
        names_list_text = ", ".join(str(name) for name in names_list if str(name).strip())
        if issue_category == "resolve_conflict" and is_pair_review:
            json_hint = conflict_review_text_hint()
        if is_answer_question:
            flow_hint = "以議題規劃指定的 speaking_as 身份，直接回答 description 中的問題。"
            json_hint = '"text": "直接回答問題", "open_questions": []'

        return f"""{stakeholder_contract}

{roles_text}

{issue_text}
{prev_text}
{context_text}
{category_hint}

# 任務
{flow_hint}

# 規則
- text 要自然、口語、貼近日常使用情境。
- text 使用第一人稱，以 speaking_as 身份在會議中直接發言；不要寫成第三人稱需求描述。
- 回答必須扣回原始產品情境與 speaking_as 指定身份。
- 只表達需求、顧慮、底線與可接受條件；不要寫技術解法或最終需求文字。
- text 必須像該 speaking_as 身份在會議中的發言，不是需求規格文字、JSON、action 結果或專案資料內容貼上。
- 若本輪是需求分類，請針對前面 Analyst 整理出的 REQ-* 結果回應；若有遺漏或欄位需要修正，具體說明要補哪個使用情境、業務規則、例外條件、驗收條件、限制、優先級、風險或假設。
- 需求分類不提出 open_questions；若整理結果仍不完整，請在 text 與 stance.proposal 說明需要補充或修正的內容。
- 若本輪是解決需求衝突，必須引用具體 URL id 或 conflict id 表態，說明採用、調整或拒絕既有 resolution 的理由；不要只描述一般痛點。
- 不得使用其他利害關係人的第一人稱經驗回答；例如不能讓外送員、餐廳、第三方支付或平台營運主管用「我的訂單」這種消費者口吻回答。
- 若同一題指定多個 speaking_as，text 必須用「【身份名稱】」分段，各段內容要反映該身份不同的責任、痛點、利益或限制，不得複製同一段回答。
- 若本輪是回答 open question，只回答被問的問題，不做正式提案或收斂判斷。
{open_questions_rule.rstrip()}
{stance_rule.rstrip()}
- 若資訊不足，可直接說明不確定之處。
{('- 若前面有多位參與者提問，text 必須逐題回答每一題。' if answer_all_questions else '')}
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list_text}' if need_speaking_as else ''}
{f'- 若本輪有指定回答身份，speaking_as 必須只使用議題規劃指定的 target_stakeholders：{", ".join(target_stakeholders)}' if target_stakeholders else ''}

# 輸出 JSON
{{{{
    {json_hint}{stance_json}
}}}}"""
