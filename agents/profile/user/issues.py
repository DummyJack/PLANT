# User issue logic: propose stakeholder issues and build user-perspective responses.
import json
from typing import Any, Dict, List, Optional

from agents.profile.conflict_review import conflict_review_text_hint
from agents.profile.analyst.requirements import requirement_discussion_pool


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
            "\n# 利害關係人角色約束（必須遵守）\n"
            f"原始產品情境：{rough_idea or '（未提供）'}\n\n"
            "你正在扮演本專案已選定的情境利害關係人；只能代表下列角色發言，不得新增其他角色或轉向其他產品情境。\n\n"
            + "\n\n".join(role_parts)
            + "\n\n規則：\n"
            "- 每個需求、顧慮、例外情境都必須能明確回扣原始產品情境。\n"
            "- 若問題很泛，請主動拉回上述產品情境與已選利害關係人日常使用場景。\n"
            "- 不得代表未列出的角色發言；不得把產品轉成資料權限、人資、薪資、通用內部管理等無關系統。\n"
            f"- speaking_as 只能從這些名稱選擇：{', '.join(allowed_names)}。\n"
        )

    def propose_issues(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
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
            "max_items": kwargs.get("max_items", 2),
            "latest_draft": artifact.get("latest_draft", ""),
            "system_models": artifact.get("system_models", []),
            "conflict_report": artifact.get("conflict_report", []),
            "feedback": artifact.get("feedback", {}),
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
            "action": "propose_stakeholder_issues",
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
        if action != "propose_stakeholder_issues":
            return {
                "action": action,
                "status": "failed",
                "error": "unsupported_action",
                "format_error": f"User issue proposal 不支援 action: {action}",
            }

        max_items = int(observation.get("max_items") or 2)
        context = {
            "round_num": observation.get("round_num"),
            "latest_draft": observation.get("latest_draft", ""),
            "system_models": observation.get("system_models", []),
            "conflict_report": observation.get("conflict_report", []),
            "feedback": observation.get("feedback", {}),
        }
        prompt = f"""# 任務
提出本輪需要進入 issue proposal 的使用者 / 利害關係人議題。目標是讓 latest draft 更 SRS-ready。

# 提案邊界
- 只根據 latest_draft、system_models、conflict_report、feedback 提案。
- 只提出最能讓 draft 更 SRS-ready 的使用者語意、使用邊界、責任歸屬、可接受條件或待確認議題。
- 可以提出 requirement_revision 或 srs_open_question；只有當利害關係人需求互相拉扯時才提出 tradeoff_decision；只有從使用情境能看出需求互斥或重複時才提出 conflict_resolution。
- 議題必須聚焦利害關係人情境、目標、痛點、使用底線或回答缺口，不提出缺乏使用者影響的一般討論。
- 最多提出 {max_items} 筆；若沒有必要議題，issues 請輸出空陣列。

# 每筆 issue schema
- title：issue proposal 的短標籤，供 triage 參考；正式會議標題由 Mediator 另行命名
- description：說明要釐清或補充的使用者情境、需求、顧慮或底線，以及它如何影響需求收斂
- category：只能是 srs_open_question、requirement_revision、tradeoff_decision、conflict_resolution 其中之一
- participants：從 user、analyst、expert、modeler 挑選，必須包含 user；需要需求整理時加入 analyst，需要 domain 風險時加入 expert，需要流程/互動釐清時加入 modeler
- discussion_mode：sequential 或 simultaneous
- speaking_order：必須與 participants 成員一致
- source_ids：相關 stakeholder 名稱、requirement/open question/conflict id；沒有就空陣列
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
        if not isinstance(data, dict):
            raise ValueError("User issue proposal 必須輸出 JSON object")
        raw_issues = data.get("issues")
        if not isinstance(raw_issues, list):
            raise ValueError("User issue proposal 必須包含 issues list")

        allowed_categories = {
            "conflict_resolution",
            "requirement_revision",
            "srs_open_question",
            "tradeoff_decision",
        }
        allowed_participants = {"user", "analyst", "expert", "modeler"}
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
            if "user" not in participants:
                raise ValueError(f"issues[{idx}] participants 必須包含 user")

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
            roles_text = f"\n# 你本輪發言身份\n請「僅」以【{name}】的身份發言。"
        elif len(speaking_as_list) > 1:
            names = [s.get("name", "") for s in speaking_as_list]
            names_list = list(names)
            roles_text = (
                f"\n# 你本輪發言身份（多位）\n請以【{'】與【'.join(names)}】的身份發言；若分段表述，請標明身份。"
            )
        elif self.stakeholders:
            names_list = [sh.get("name", "") for sh in self.stakeholders]
            roles_text = (
                "\n# 你代表的利害關係人角色\n"
                "本輪請選擇一位或多位最適合回答此議題的身份發言。"
            )
        else:
            names_list = []
            roles_text = ""
        if target_stakeholders:
            roles_text += (
                "\n# 本輪指定回答身份\n"
                f"本輪只能代表這些利害關係人回答：{', '.join(target_stakeholders)}。\n"
                "不得自行切換到其他 stakeholder；如果問題不適合指定身份，請以該身份說明不適用或缺少情境。\n"
            )

        prev_text = self.format_previous_responses(
            previous_responses, title="前面的發言"
        )

        context_text = ""
        if artifact_context:
            context_text = f"\n# 當前 artifact 分檔內容（供參考）\n{json.dumps(artifact_context, ensure_ascii=False, indent=2)}"
        allow_suggested_next_action = (
            issue_category != "conflict_resolution"
            and not str(issue.get("id") or "").startswith("ELICIT-")
        )
        is_elicitation = str(issue.get("id") or "").startswith("ELICIT-")

        # 多位時輸出要含 speaking_as；一位時不必
        need_speaking_as = len(self.stakeholders) > 1
        if need_speaking_as:
            json_hint = '"speaking_as": ["本輪發言身份名稱"], "text": "完整發言內容"'
            if not is_elicitation:
                json_hint += ', "open_questions": [...]'
            if issue_category == "srs_open_question":
                flow_hint = "選擇適合回答的利害關係人，直接回答問題並補充必要情境。"
            else:
                flow_hint = "選擇適合的 speaking_as，說明該身份在此議題上的立場、需求與底線。"
        else:
            json_hint = '"text": "針對此議題的完整發言內容"'
            if not is_elicitation:
                json_hint += ', "open_questions": [...]'
            flow_hint = "以第一人稱撰寫一段完整發言，說明立場、需求與底線。"
        if answer_all_questions:
            flow_hint = (
                "逐題回答前面每一位 agent 提出的問題；text 內請用「發問者 → 回答身份」分段，"
                "每題都要明確回答，不要只回最後一題。"
            )

        category_hint = ""
        if issue_category == "requirement_revision":
            category_hint = (
                "\n# 本議題特別說明（requirement_revision）\n"
                "可提出新需求，也可指出既有需求需要調整、補限制、改優先順序或移除。"
            )
        elif issue_category == "srs_open_question":
            category_hint = (
                "\n# 本議題特別說明（srs_open_question）\n"
                "直接回答問題；若資訊不足，說明缺少的情境、角色或使用條件。"
            )
        elif issue_category == "conflict_resolution":
            contract = issue.get("response_contract") if isinstance(issue.get("response_contract"), dict) else {}
            known_pair_ids = [
                str(pair_id).strip()
                for pair_id in (contract.get("known_pair_ids") or [])
                if str(pair_id).strip()
            ]
            category_hint = (
                "\n# 本議題特別說明（conflict_resolution）\n"
                "從實際使用情境說明兩項需求是否衝突、重複、可共存或資訊不足。\n"
                "- 外層只能輸出合法 JSON object；不要 markdown、不要 ```json fence、不要額外說明文字。\n"
                "- 外層只能有 text 欄位。\n"
                "- text 必須是 JSON object 字串，不是巢狀 object。\n"
                "- text JSON 結構必須為 {\"pair_reviews\":[...]}。\n"
                "- pair_reviews 必須逐筆涵蓋 response_contract.known_pair_ids 中每個 id，不能遺漏、不能新增未知 id。\n"
                "- 每筆 pair_reviews 都必須有 id、proposed_label、reason。\n"
                "- proposed_label 只能是 Conflict 或 Neutral。\n"
                f"- 本輪必須涵蓋的 pair id：{json.dumps(known_pair_ids, ensure_ascii=False)}"
            )
        suggested_next_action_rule = []
        suggested_next_action_json = ""
        if allow_suggested_next_action:
            suggested_next_action_rule.append(
                "若你認為會後需要安排下一步，可額外提供 suggested_next_action；"
                "這只是建議，不會在會議中直接執行。"
            )
            suggested_next_action_json = (
                ', "suggested_next_action": {"type": "direct_clarification | new_issue", '
                '"reason": "為何建議會後安排這一步", '
                '"target_ids": ["可選，相關 requirement/conflict/issue id"], "urgency": "low | medium | high"}'
            )
        suggested_next_action_rules_text = "".join(
            f"- {rule}\n" for rule in suggested_next_action_rule
        )
        open_questions_rule = "" if is_elicitation else "- 若需要他人補資訊，只把當下最重要、會影響決策的一個問題放進 open_questions。\n"
        names_list_text = ", ".join(str(name) for name in names_list if str(name).strip())
        if issue_category == "conflict_resolution":
            json_hint = conflict_review_text_hint()
            suggested_next_action_json = ""

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
- 回答必須扣回原始產品情境與 speaking_as 指定身份。
- 只表達需求、顧慮、底線與可接受條件；不要寫技術解法或最終 requirement wording。
{open_questions_rule.rstrip()}
- 若資訊不足，可直接說明不確定之處。
{suggested_next_action_rules_text}
{('- 若前面有多位 agent 提問，text 必須逐題回答每一題。' if answer_all_questions else '')}
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list_text}' if need_speaking_as else ''}

# 輸出 JSON
{{{{
    {json_hint}{suggested_next_action_json}
}}}}"""
