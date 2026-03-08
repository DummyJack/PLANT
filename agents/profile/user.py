import json
from typing import Dict, List, Optional
from agents.base import BaseAgent


class UserAgent(BaseAgent):
    """利害關係人模擬 Agent — 從不同角度提出需求和期望"""

    name = "user"

    system_prompt = """你負責模擬不同利害關係人的角色。

核心原則：
1. 角色扮演 — 以第一人稱代入每位利害關係人，用口語化方式表達
2. 立場忠實 — 只代表被指派的角色立場，模擬現實中的他們"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)
        self.stakeholders: List[Dict] = []

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
- name、reason 請使用繁體中文

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
- name、text 陣列內容請使用繁體中文

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

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

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

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        # 多位時輸出要含 speaking_as；一位時不必
        need_speaking_as = len(self.stakeholders) > 1
        if need_speaking_as:
            json_hint = (
                '"speaking_as": ["本輪發言身份名稱"]（必須是上述角色之一或數位）, '
                '"statement": "完整發言內容", '
                '"vote": "agreed 或 unresolved（依你的立場）", '
                '"open_questions": [...]'
            )
            flow_hint = "1. 先決定本輪以誰發言（speaking_as） 2. 再撰寫 statement 3. 依立場投票（vote）"
        else:
            json_hint = '"statement": "針對此議題的完整發言內容", "vote": "agreed 或 unresolved", "open_questions": [...]'
            flow_hint = "撰寫一段完整的發言（statement），以第一人稱表達立場與需求，並依立場投票（vote）"

        user_prompt = f"""{roles_text}

{topic_text}
{prev_text}
{snapshot_text}

# 思考與發言流程
{flow_hint}
若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "analyst"、"expert"、"modeler"）

# 發言風格
- 以該利害關係人在會議中的真實口吻：第一人稱、口語化，像真人表達需求與顧慮，不制式
- 可帶入角色情境（例如「我們現場作業時會…」「我們最在意的是…」）

# 約束
- 必須以你代表的利害關係人角色立場發言
- statement 須以第一人稱、該角色的日常經驗為基礎撰寫完整發言
- 禁止提出技術解決方案，只表達「需要什麼」
- statement、open_questions 的 question 請使用繁體中文
{f'- speaking_as 的名稱必須從以下選一個或數個：{names_list}' if need_speaking_as else ''}

輸出 JSON:
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
            "vote": response.get("vote", "unresolved"),
            "open_questions": open_questions,
            "speaking_as": speaking_as,
        }
