from typing import Dict, List, Optional
from agents.base import BaseAgent


class UserAgent(BaseAgent):
    """利害關係人模擬 Agent — 從不同角度提出需求和期望"""

    name = "user"

    system_prompt = """你是利害關係人模擬專家，負責模擬不同利害關係人的角色。

核心原則：
1. 角色扮演 — 以第一人稱代入每位利害關係人，用口語化方式表達
2. 立場忠實 — 只代表被指派的角色立場，不做系統分析或技術設計
3. 需求具體 — 每條需求必須來自該角色的日常使用情境，不得抽象空泛
4. 衝突自然 — 不同角色的需求可能矛盾，如實表達，不要預先調和
5. 禁止越權 — 不要提出技術解決方案，只描述「想要什麼」和「為什麼」"""

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
- 避免角色重疊（如「使用者」和「一般使用者」）

# 輸出 JSON
{{{{
    "proposed_stakeholders": [
        {{{{"name": "利害關係人名稱", "reason": "選擇理由"}}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages, temperature=1)
        return response.get("proposed_stakeholders", [])

    def generate_stakeholder_requirements(self, rough_idea: str, selected_stakeholders: List[str]) -> List[Dict]:
        stakeholder_list = ", ".join(f"{i+1}. {sh}" for i, sh in enumerate(selected_stakeholders))

        user_prompt = f"""# 任務
模擬以下利害關係人，以第一人稱、口語方式從各自的角度提出需求與期望。

# 利害關係人
{stakeholder_list}

# 背景（僅供參考）
{rough_idea}

# 發言指引
每位利害關係人請依以下面向發言：
1. 日常使用情境 — 你平常怎麼使用這個系統？
2. 痛點與困擾 — 目前最讓你困擾的問題是什麼？
3. 期望功能 — 你最希望系統能做到什麼？
4. 擔心的事 — 你對這個系統有什麼顧慮？

# 約束
- 每位利害關係人提出 3-5 條獨立需求（text 陣列）
- 每條需求是一個完整的獨立陳述
- 以該角色的日常經驗出發，禁止提出技術實作方案
- 不同角色的需求可以矛盾，如實表達

# 輸出 JSON
{{{{
    "stakeholders": [
        {{{{
            "name": "利害關係人名稱",
            "text": ["需求1", "需求2", "需求3"]
        }}}}
    ]
}}}}"""

        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages, temperature=1.2)
            stakeholders = response.get("stakeholders", [])

            for sh in stakeholders:
                if not all(key in sh for key in ["name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
                if isinstance(sh["text"], str):
                    sh["text"] = [s.strip() for s in sh["text"].split("\n") if s.strip()]
                if len(sh["text"]) < 3:
                    self.logger.warning(f"{sh['name']} 只有 {len(sh['text'])} 條需求，不足 3 條")
                elif len(sh["text"]) > 5:
                    sh["text"] = sh["text"][:5]

            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗: {e}")

    def respond_to_topic(self, topic, previous_responses=None):
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
            needs = "\n".join(f"  - {t}" for t in texts) if isinstance(texts, list) else f"  - {texts}"
            roles_text = f"\n# 你本輪發言身份\n請「僅」以【{name}】的身份發言。\n\n【{name}】的需求與關切：\n{needs}"
        elif len(speaking_as_list) > 1:
            role_parts = []
            names = [s.get("name", "") for s in speaking_as_list]
            for sh in speaking_as_list:
                n = sh.get("name", "")
                t = sh.get("text", [])
                needs = "\n".join(f"  - {x}" for x in t) if isinstance(t, list) else f"  - {t}"
                role_parts.append(f"【{n}】\n{needs}")
            roles_text = f"\n# 你本輪發言身份（多位）\n請以【{'】與【'.join(names)}】的身份發言。可分別表述各角色在此議題上的立場與需求，或綜合表述；若以第一人稱分段表述，請明確區分是哪一位在發言。\n\n" + "\n\n".join(role_parts)
        elif self.stakeholders:
            role_parts = []
            for sh in self.stakeholders:
                n = sh.get("name", "")
                t = sh.get("text", [])
                needs = "\n".join(f"  - {x}" for x in t) if isinstance(t, list) else f"  - {t}"
                role_parts.append(f"【{n}】\n{needs}")
            roles_text = "\n# 你代表的利害關係人角色（請擇一立場發言）\n" + "\n\n".join(role_parts)

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n# 前面的發言\n" + "\n\n".join(parts)

        user_prompt = f"""你正在以利害關係人代表的身份參與需求討論。
{roles_text}

{topic_text}
{prev_text}

# 思考與發言流程
1. 先思考：(1) 我代表的角色在此議題上的核心需求與顧慮 (2) 不可退讓的立場 (3) 可妥協或配合的部分
2. 再撰寫一段完整的發言（statement），以第一人稱表達你的立場與需求
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "analyst"、"expert"、"modeler"）

# 約束
- 必須以你代表的利害關係人角色立場發言
- statement 須以第一人稱、該角色的日常經驗為基礎撰寫完整發言
- 禁止提出技術解決方案，只表達「需要什麼」

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages, temperature=1.2)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }
