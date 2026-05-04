# User topic logic: propose stakeholder issues and build user-perspective responses.
import json
from typing import Any, Dict, List, Optional


class UserTopics:
    def build_stakeholder_contract(
        self,
        artifact_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        rough_idea = ""
        if isinstance(artifact_snapshot, dict):
            rough_idea = str(artifact_snapshot.get("rough_idea") or "").strip()
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

    def propose_topics(
        self,
        artifact: Dict[str, Dict],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict]:
        """僅提出使用者視角合理的議題：缺漏需求補充、或需由使用者回答的待確認問題。"""
        proposals: List[Dict] = []

        for sh in self.stakeholders or []:
            name = (sh.get("name") or "").strip()
            texts = sh.get("text") or []
            if not name or not isinstance(texts, list):
                continue
            needs = [str(t).strip() for t in texts if str(t).strip()]
            if not needs:
                continue
            desc = "；".join(needs[:2])
            proposals.append(
                {
                    "title": f"{name} 的需求補充",
                    "description": desc,
                    "category": "new_requirement",
                    "participants": ["user", "analyst", "expert", "modeler"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["user", "analyst", "expert", "modeler"],
                    "source_ids": [name],
                    "priority_hint": "medium",
                    "impact_level": "medium",
                    "why_now": "使用者情境中的需求或限制尚未完全反映到當前需求中。",
                    "proposed_by": "user",
                    "round": round_num,
                }
            )

        for oq in artifact.get("open_questions", []) or []:
            if oq.get("status") == "answered":
                continue
            to_agent = str(oq.get("to") or "").strip().lower()
            from_agent = str(oq.get("from_agent") or "").strip().lower()
            q = str(oq.get("question") or "").strip()
            if not q or (to_agent != "user" and from_agent != "user"):
                continue
            proposals.append(
                {
                    "title": "使用者觀點待確認問題",
                    "description": q,
                    "category": "open_question",
                    "participants": ["user", "analyst"],
                    "discussion_mode": "simultaneous",
                    "speaking_order": ["user", "analyst"],
                    "source_ids": [],
                    "priority_hint": "medium",
                    "impact_level": "medium",
                    "why_now": "此問題需要使用者視角補充，否則可能影響需求收斂。",
                    "proposed_by": "user",
                    "round": round_num,
                }
            )

        return proposals[: max(1, max_items)]

    def build_topic_response_prompt(
        self,
        *,
        topic: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_category = (topic.get("category") or "").strip()
        stakeholder_contract = self.build_stakeholder_contract(artifact_snapshot)
        target_stakeholders = [
            str(x).strip()
            for x in (topic.get("target_stakeholders") or [])
            if str(x).strip()
        ]
        target_set = set(target_stakeholders)
        answer_all_questions = bool(topic.get("answer_all_interviewer_questions"))

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
            texts = sh.get("text", [])
            needs = (
                "\n".join(f"  - {t}" for t in texts)
                if isinstance(texts, list)
                else f"  - {texts}"
            )
            roles_text = f"\n# 你本輪發言身份\n請「僅」以【{name}】的身份發言。\n\n【{name}】的需求與關切：\n{needs}"
        elif len(speaking_as_list) > 1:
            role_parts = []
            names = [s.get("name", "") for s in speaking_as_list]
            names_list = list(names)
            for sh in speaking_as_list:
                n = sh.get("name", "")
                t = sh.get("text", [])
                needs = (
                    "\n".join(f"  - {x}" for x in t)
                    if isinstance(t, list)
                    else f"  - {t}"
                )
                role_parts.append(f"【{n}】\n{needs}")
            roles_text = (
                f"\n# 你本輪發言身份（多位）\n請以【{'】與【'.join(names)}】的身份發言。可分別表述各角色在此議題上的立場與需求，或綜合表述；若以第一人稱分段表述，請明確區分是哪一位在發言。\n\n"
                + "\n\n".join(role_parts)
            )
        elif self.stakeholders:
            role_parts = []
            for sh in self.stakeholders:
                n = sh.get("name", "")
                t = sh.get("text", [])
                needs = (
                    "\n".join(f"  - {x}" for x in t)
                    if isinstance(t, list)
                    else f"  - {t}"
                )
                role_parts.append(f"【{n}】\n{needs}")
            names_list = [sh.get("name", "") for sh in self.stakeholders]
            roles_text = (
                "\n# 你代表的利害關係人角色\n"
                "本輪請先宣告你以「哪一位」或「哪幾位」身份發言（speaking_as），再撰寫發言內容。\n\n"
                + "\n\n".join(role_parts)
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

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"
        allow_suggested_next_action = (
            topic_category != "conflict_discussion"
            and not str(topic.get("id") or "").startswith("ELICIT-")
        )

        # 多位時輸出要含 speaking_as；一位時不必
        need_speaking_as = len(self.stakeholders) > 1
        if need_speaking_as:
            json_hint = (
                '"speaking_as": ["本輪發言身份名稱"]（必須是上述角色之一或數位）, '
                '"statement": "完整發言內容", '
                '"open_questions": [...]'
            )
            if topic_category == "open_question":
                flow_hint = (
                    "1. 先決定本輪以哪些利害關係人發言（open_question 建議優先涵蓋多方利害關係人）"
                    " 2. 再撰寫 statement；最終決策會在討論後整理為選項並交由使用者確認"
                )
            else:
                flow_hint = "1. 先決定本輪以誰發言（speaking_as） 2. 再撰寫 statement；最終決策會在討論後整理為選項並交由使用者確認"
        else:
            json_hint = '"statement": "針對此議題的完整發言內容", "open_questions": [...]'
            flow_hint = "撰寫一段完整的發言（statement），以第一人稱表達立場與需求；最終決策會在討論後整理為選項並交由使用者確認"
        if answer_all_questions:
            flow_hint = (
                "逐題回答前面每一位 agent 提出的問題；statement 內請用「發問者 → 回答身份」分段，"
                "每題都要明確回答，不要只回最後一題。"
            )

        category_hint = ""
        if topic_category == "new_requirement":
            category_hint = (
                "\n# 本議題特別說明（new_requirement）\n"
                "此題不只可提出新需求，也請檢視你先前提出的需求是否需要調整（如修正文句、補上限制條件、調整優先順序或刪除不再需要的內容）。\n"
                "若要調整，請在 statement 中清楚指出「原需求需調整」與「調整後方向」。"
            )
        elif topic_category == "open_question":
            category_hint = (
                "\n# 本議題特別說明（open_question）\n"
                "若這是需求挖掘會議：請像實務需求會議中的利害關係人一樣，針對目前理解指出「哪裡正確、哪裡不確定、哪裡需要補充」，並直接回答對方提出的問題。\n"
                "可補充你在意的流程、內容、操作、輸出、介面偏好、限制與底線。\n"
                "若資訊不足，請直接說缺少哪個情境、角色或使用條件，不要假裝已確認。"
            )
        elif topic_category == "conflict_discussion":
            category_hint = (
                "\n# 本議題特別說明（conflict_discussion）\n"
                "請從利害關係人角度說明：兩項需求在實際使用上是否真的互相衝突、是否只是重複改寫、或其實彼此無直接關聯。\n"
                "你的任務是提供真實使用情境、顧慮、底線與可接受條件，不是做最終標籤裁定。\n"
                "只有在你認為兩項需求既不衝突、也不重複，且在使用情境上沒有直接語義關係時，才可支持 Neutral。\n"
                "若只是資訊不足、情境未講清楚或條件未補齊，請直接指出缺口，不要勉強支持 Neutral。"
            )
        suggested_next_action_rule = ""
        suggested_next_action_json = ""
        if allow_suggested_next_action:
            suggested_next_action_rule = (
                "- 若你認為本議題討論結束後需要安排下一步，可額外提供 suggested_next_action；"
                "這只是建議，不會在會議中直接執行。"
            )
            suggested_next_action_json = (
                ', "suggested_next_action": {"type": "direct_clarification | new_topic", '
                '"reason": "為何建議會後安排這一步", '
                '"target_ids": ["可選，相關 requirement/conflict/topic id"], "urgency": "low | medium | high"}'
            )

        return f"""{stakeholder_contract}

{roles_text}

{topic_text}
{prev_text}
{snapshot_text}
{category_hint}

# 任務
{flow_hint}
請以利害關係人角度，用第一人稱說出情境、痛點、需求、顧慮與底線。

# 規則
- statement 應自然、口語、貼近日常經驗，不要像分析師或架構師。
- 優先講你遇到的情境、在意的風險、可接受底線與希望系統做到的事。
- 所有回答必須站在 speaking_as 指定的已選利害關係人立場，且必須扣回原始產品情境。
- 不要提出技術解決方案，只表達需要什麼與擔心什麼。
- 不要決定議題路由、需求優先級、正式核准狀態或最終 requirement wording。
- 不要把自己說成分析師、專家、建模者或最終裁定者；你只代表利害關係人視角。
- 若需要他人補資訊，再放進 open_questions。
- {suggested_next_action_rule}
- 若資訊不足，可直接說明不確定之處。
{('- 若前面有多位 agent 提問，statement 必須逐題回答每一題。' if answer_all_questions else '')}
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list}' if need_speaking_as else ''}

# 輸出 JSON
{{{{
    {json_hint}{suggested_next_action_json}
}}}}"""
