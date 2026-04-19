import json
from typing import Dict, List, Optional, Any
from agents.base import BaseAgent
from utils import user_requirement_cards, user_stakeholder_name_reason


class UserAgent(BaseAgent):
    """利害關係人模擬 Agent — 從不同角度提出需求和期望"""

    name = "user"

    system_prompt = """你負責模擬不同利害關係人的角色。

規則：
1. 以第一人稱代入角色，用真實會議口吻表達。
2. 只代表被指派角色的需求、顧慮與底線，不代替技術團隊或主持人下結論。
3. 優先講情境、痛點、需求與可接受底線，不講技術解法。"""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model, tools=tools, registry=registry, project_config=project_config
        )
        self.stakeholders: List[Dict] = []

    # ===== Action: stakeholder simulation =====

    def propose_stakeholders(self, rough_idea: str) -> List[str]:
        user_prompt = f"""# 任務
根據初始想法: {rough_idea}，建議 5-8 位可能相關的利害關係人。

# 選擇優先順序
1. 核心使用者（直接使用系統的人）
2. 系統擁有者與管理者
3. 外部相關單位

# 約束
- 每位利害關係人須有明確且不同的角色職責
- 避免角色重疊
- name 只填名稱，不要用括號補充說明
- reason 選擇理由用一句話即可
- {user_stakeholder_name_reason()}

# 輸出 JSON
{{{{
    "proposed_stakeholders": [
        {{{{"name": "利害關係人名稱", "reason": "一句話選擇理由"}}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages, temperature=1)
        return response.get("proposed_stakeholders", [])

    def generate_stakeholder_requirements(
        self, rough_idea: str, selected_stakeholders: List[str]
    ) -> List[Dict]:
        stakeholder_list = ", ".join(
            f"{i+1}. {sh}" for i, sh in enumerate(selected_stakeholders)
        )

        user_prompt = f"""# 任務
模擬以下利害關係人，以第一人稱、口語方式從各自的角度提出需求與期望。

# 利害關係人
{stakeholder_list}

# 背景（僅供參考）
{rough_idea}

# 發言指引
每位利害關係人請依以下面向發言：
1. 日常使用情境 — 你平常怎麼使用這個系統
2. 痛點與困擾 — 目前最讓你困擾的問題是什麼
3. 期望功能 — 你最希望系統能做到什麼
4. 擔心的事 — 你對這個系統有什麼顧慮

# 約束
- 每位利害關係人提出 3-5 條獨立需求（text 陣列）
- 以該角色的日常經驗出發
- {user_requirement_cards()}

# 輸出 JSON
{{{{
    "stakeholders": [
        {{{{
            "name": "利害關係人名稱",
            "text": ["發言1", "發言2", "發言3", ...]
        }}}}
    ]
}}}}"""

        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages, temperature=1)
            stakeholders = response.get("stakeholders", [])

            for sh in stakeholders:
                if not all(key in sh for key in ["name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
                if isinstance(sh["text"], str):
                    sh["text"] = [
                        s.strip() for s in sh["text"].split("\n") if s.strip()
                    ]
                if len(sh["text"]) < 3:
                    self.logger.warning(
                        f"{sh['name']} 只有 {len(sh['text'])} 條需求，不足 3 條"
                    )

            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗: {e}")

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

    def build_observation(self, *, mode: str, **kwargs: Any) -> Dict[str, Any]:
        if mode == "topic_response":
            previous_responses = kwargs.get("previous_responses") or []
            artifact_snapshot = kwargs.get("artifact_snapshot") or {}
            topic = kwargs["topic"]
            return {
                "topic": topic,
                "topic_id": str(topic.get("id") or ""),
                "topic_category": str(topic.get("category") or ""),
                "previous_response_count": len(previous_responses),
                "has_artifact_snapshot": bool(artifact_snapshot),
                "stakeholder_count": len(self.stakeholders or []),
                "iteration": kwargs.get("iteration", 0) + 1,
                "max_iterations": kwargs.get("max_iterations", 1),
            }
        return super().build_observation(mode=mode, **kwargs)

    def decide_action(
        self,
        *,
        mode: str,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "topic_response":
            return {
                "action": "respond_as_stakeholder",
                "params": {},
                "reasoning": "以利害關係人視角回應議題。",
            }
        return super().decide_action(
            mode=mode,
            observation=observation,
            last_result=last_result,
            **kwargs,
        )

    def _build_topic_response_prompt(
        self,
        *,
        topic: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_category = (topic.get("category") or "").strip()

        speaking_as_list = []
        if self.stakeholders:
            if len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []  # 多位時交由系統擇一或擇多立場發言

        if len(speaking_as_list) == 1:
            sh = speaking_as_list[0]
            name = sh.get("name", "")
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
                    " 2. 再撰寫 statement；投票在討論結束後另行進行"
                )
            else:
                flow_hint = "1. 先決定本輪以誰發言（speaking_as） 2. 再撰寫 statement；投票在討論結束後另行進行"
        else:
            json_hint = '"statement": "針對此議題的完整發言內容", "open_questions": [...]'
            flow_hint = "撰寫一段完整的發言（statement），以第一人稱表達立場與需求；投票在討論結束後另行進行"

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
                "若這是需求挖掘會議的 collector 階段：只提供『還沒被問清楚的方向』、『你真正在意的點』與『為什麼這件事重要』，不要直接替正式問題作答，也不要一次給出完整規格。\n"
                "若這是正式問答階段：直接回答對方的主問題。\n"
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
                ', "suggested_next_action": {"type": "analyst_review | expert_review | '
                'modeler_review | direct_clarification | new_topic", "reason": "為何建議會後安排這一步", '
                '"target_ids": ["可選，相關 requirement/conflict/topic id"], "urgency": "low | medium | high"}'
            )

        return f"""{roles_text}

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
- 不要提出技術解決方案，只表達需要什麼與擔心什麼。
- 不要決定議題路由、需求優先級、正式核准狀態或最終 requirement wording。
- 不要把自己說成分析師、專家、建模者或最終裁定者；你只代表利害關係人視角。
- 若需要他人補資訊，再放進 open_questions。
- {suggested_next_action_rule}
- 若資訊不足，可直接說明不確定之處。
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list}' if need_speaking_as else ''}

# 輸出 JSON
{{{{
    {json_hint}{suggested_next_action_json}
}}}}"""

    def _respond_topic_core(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_category = (topic.get("category") or "").strip()

        speaking_as_list = []
        if self.stakeholders:
            if len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []  # 多位時交由系統擇一或擇多立場發言

        if len(speaking_as_list) == 1:
            sh = speaking_as_list[0]
            name = sh.get("name", "")
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

        prev_text = self.format_previous_responses(
            previous_responses, title="前面的發言"
        )

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

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
                    " 2. 再撰寫 statement；投票在討論結束後另行進行"
                )
            else:
                flow_hint = "1. 先決定本輪以誰發言（speaking_as） 2. 再撰寫 statement；投票在討論結束後另行進行"
        else:
            json_hint = '"statement": "針對此議題的完整發言內容", "open_questions": [...]'
            flow_hint = "撰寫一段完整的發言（statement），以第一人稱表達立場與需求；投票在討論結束後另行進行"

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
                "若這是需求挖掘會議的 collector 階段：只提供『還沒被問清楚的方向』、『你真正在意的點』與『為什麼這件事重要』，不要直接替正式問題作答，也不要一次給出完整規格。\n"
                "若這是正式問答階段：直接回答對方的主問題。\n"
                "可補充你在意的流程、內容、操作、輸出、介面偏好、限制與底線。\n"
                "若資訊不足，請直接說缺少哪個情境、角色或使用條件，不要假裝已確認。"
            )
        elif topic_category == "conflict_discussion":
            category_hint = (
                "\n# 本議題特別說明（conflict_discussion）\n"
                "請從利害關係人角度說明：兩項需求在實際使用上是否真的互相衝突、是否只是重複改寫、或其實彼此無直接關聯。\n"
                "只有在你認為兩項需求既不衝突、也不重複，且在使用情境上沒有直接語義關係時，才可支持 Neutral。\n"
                "若只是資訊不足、情境未講清楚或條件未補齊，請直接指出缺口，不要勉強支持 Neutral。"
            )

        user_prompt = f"""{roles_text}

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
- 不要提出技術解決方案，只表達需要什麼與擔心什麼。
- 若需要他人補資訊，再放進 open_questions。
- 若資訊不足，可直接說明不確定之處。
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list}' if need_speaking_as else ''}

# 輸出 JSON
{{{{
    {json_hint}
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_conflict_topic_response(messages, temperature=1)

        statement = response.get("statement", "")
        open_questions = response.get("open_questions", [])

        # 多位時解析 speaking_as 並驗證為合法名稱
        speaking_as = []
        if need_speaking_as:
            raw = response.get("speaking_as")
            if isinstance(raw, str):
                raw = [raw]
            valid_names = {sh.get("name", "") for sh in self.stakeholders}
            speaking_as = [n for n in (raw or []) if n and n in valid_names]
            if not speaking_as and self.stakeholders:
                speaking_as = [self.stakeholders[0].get("name", "")]
        elif len(speaking_as_list) == 1:
            speaking_as = [speaking_as_list[0].get("name", "")]

        return {
            "agent": self.name,
            "statement": statement,
            "open_questions": open_questions,
            "speaking_as": speaking_as,
        }
    def respond_to_conflict_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        return self._respond_topic_core(
            topic,
            previous_responses=previous_responses,
            artifact_snapshot=artifact_snapshot,
        )

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_category = (topic.get("category") or "").strip()

        speaking_as_list = []
        if self.stakeholders:
            if len(self.stakeholders) == 1:
                speaking_as_list = self.stakeholders
            else:
                speaking_as_list = []  # 多位時交由系統擇一或擇多立場發言

        if len(speaking_as_list) == 1:
            sh = speaking_as_list[0]
            name = sh.get("name", "")
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

        prev_text = self.format_previous_responses(
            previous_responses, title="前面的發言"
        )

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

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
                    " 2. 再撰寫 statement；投票在討論結束後另行進行"
                )
            else:
                flow_hint = "1. 先決定本輪以誰發言（speaking_as） 2. 再撰寫 statement；投票在討論結束後另行進行"
        else:
            json_hint = '"statement": "針對此議題的完整發言內容", "open_questions": [...]'
            flow_hint = "撰寫一段完整的發言（statement），以第一人稱表達立場與需求；投票在討論結束後另行進行"

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
                "若這是需求挖掘會議的 collector 階段：只提供『還沒被問清楚的方向』、『你真正在意的點』與『為什麼這件事重要』，不要直接替正式問題作答，也不要一次給出完整規格。\n"
                "若這是正式問答階段：直接回答對方的主問題。\n"
                "可補充你在意的流程、內容、操作、輸出、介面偏好、限制與底線。\n"
                "若資訊不足，請直接說缺少哪個情境、角色或使用條件，不要假裝已確認。"
            )
        elif topic_category == "conflict_discussion":
            category_hint = (
                "\n# 本議題特別說明（conflict_discussion）\n"
                "請從利害關係人角度說明：兩項需求在實際使用上是否真的互相衝突、是否只是重複改寫、或其實彼此無直接關聯。\n"
                "只有在你認為兩項需求既不衝突、也不重複，且在使用情境上沒有直接語義關係時，才可支持 Neutral。\n"
                "若只是資訊不足、情境未講清楚或條件未補齊，請直接指出缺口，不要勉強支持 Neutral。"
            )

        user_prompt = f"""{roles_text}

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
- 不要提出技術解決方案，只表達需要什麼與擔心什麼。
- 若需要他人補資訊，再放進 open_questions。
- 若資訊不足，可直接說明不確定之處。
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list}' if need_speaking_as else ''}

# 輸出 JSON
{{{{
    {json_hint}
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages, temperature=1)

        statement = response.get("statement", "")
        open_questions = response.get("open_questions", [])

        # 多位時解析 speaking_as 並驗證為合法名稱
        speaking_as = []
        if need_speaking_as:
            raw = response.get("speaking_as")
            if isinstance(raw, str):
                raw = [raw]
            valid_names = {sh.get("name", "") for sh in self.stakeholders}
            speaking_as = [n for n in (raw or []) if n and n in valid_names]
            if not speaking_as and self.stakeholders:
                speaking_as = [self.stakeholders[0].get("name", "")]
        elif len(speaking_as_list) == 1:
            speaking_as = [speaking_as_list[0].get("name", "")]

        return {
            "agent": self.name,
            "statement": statement,
            "open_questions": open_questions,
            "speaking_as": speaking_as,
        }
    def execute_action(
        self,
        *,
        mode: str,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "topic_response":
            topic = kwargs["topic"]
            user_prompt = self._build_topic_response_prompt(
                topic=topic,
                previous_responses=kwargs.get("previous_responses"),
                artifact_snapshot=kwargs.get("artifact_snapshot"),
            )
            messages = self.build_direct_messages(user_prompt)
            response = self.chat_for_topic_response(messages, temperature=1)

            statement = response.get("statement", "")
            open_questions = response.get("open_questions", [])

            speaking_as = []
            need_speaking_as = len(self.stakeholders) > 1
            speaking_as_list = []
            if self.stakeholders:
                if len(self.stakeholders) == 1:
                    speaking_as_list = self.stakeholders
                else:
                    speaking_as_list = []
            if need_speaking_as:
                raw = response.get("speaking_as")
                if isinstance(raw, str):
                    raw = [raw]
                valid_names = {sh.get("name", "") for sh in self.stakeholders}
                speaking_as = [n for n in (raw or []) if n and n in valid_names]
                if not speaking_as and self.stakeholders:
                    speaking_as = [self.stakeholders[0].get("name", "")]
            elif len(speaking_as_list) == 1:
                speaking_as = [speaking_as_list[0].get("name", "")]

            return {
                "action": decision.get("action", ""),
                "status": "success",
                "statement": statement,
                "open_questions": open_questions,
                "speaking_as": speaking_as,
                "summary": "完成 user topic_response",
            }
        return super().execute_action(mode=mode, decision=decision, **kwargs)
