from typing import Dict, List, Optional
from agents.base import BaseAgent
from agents.memory import Memory


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

    def __init__(self, model, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None):
        super().__init__(model, tools=tools, memory=memory, registry=registry)
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

        self.memory.add("user", f"為 '{rough_idea[:50]}...' 提出利害關係人建議")
        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)
        result = response.get("proposed_stakeholders", [])
        self.memory.add("assistant", f"建議了 {len(result)} 位利害關係人")
        return result

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
- 每位利害關係人提出 3-5 條獨立需求（最少 3 條，最多 5 條）
- 每條需求是一個完整的獨立陳述，直接放入 text 的 list 中
- 每條需求必須足夠具體，能獨立與其他利害關係人的需求做衝突比對
- 以該角色的日常經驗出發，禁止提出技術實作方案
- 不同角色的需求可以矛盾，如實表達

# 輸出 JSON
{{{{
    "stakeholders": [
        {{{{
            "id": "SH-01",
            "name": "利害關係人名稱",
            "text": [
                "",
                "",
                ...(最多 5 條)
            ]
        }}}}
    ]
}}}}"""

        self.memory.add("user", f"為 {len(selected_stakeholders)} 位利害關係人生成需求")
        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages, temperature=1.2)
            stakeholders = response.get("stakeholders", [])

            for sh in stakeholders:
                if not all(key in sh for key in ["id", "name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
                if isinstance(sh["text"], str):
                    sh["text"] = [s.strip() for s in sh["text"].split("\n") if s.strip()]
                # 強制 3-5 條
                if len(sh["text"]) < 3:
                    self.logger.warning(f"{sh['name']} 只有 {len(sh['text'])} 條需求，不足 3 條")
                elif len(sh["text"]) > 5:
                    sh["text"] = sh["text"][:5]

            self.memory.add("assistant", f"已生成 {len(stakeholders)} 位利害關係人需求")
            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗: {e}")

    # 覆寫：議題討論回應

    def respond_to_topic(self, topic, previous_responses=None):
        """以選定的利害關係人角色參與議題討論"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        # 組裝角色資訊
        roles_text = ""
        if self.stakeholders:
            role_parts = []
            for sh in self.stakeholders:
                name = sh.get("name", "")
                texts = sh.get("text", [])
                needs = "\n".join(f"  - {t}" for t in texts) if texts else "  （無具體需求）"
                role_parts.append(f"【{name}】\n{needs}")
            roles_text = "\n# 你代表的利害關係人角色\n" + "\n\n".join(role_parts)
        else:
            roles_text = "\n# 你代表的角色\n一般使用者"

        prev_text = ""
        if previous_responses:
            parts = []
            for r in previous_responses:
                agent = r.get("agent", "?")
                resp = r.get("response", {})
                content = resp.get("content", resp.get("position", ""))
                parts.append(f"【{agent}】{content}")
            prev_text = "\n# 前面的發言\n" + "\n".join(parts)

        user_prompt = f"""你正在以利害關係人代表的身份參與需求討論。
{roles_text}

{topic_text}
{prev_text}

# 回應要求
1. position: 這個議題對你代表的利害關係人的影響和立場（以第一人稱表達）
2. arguments: 從利害關係人的實際使用情境出發的論點
3. suggestions: 從利害關係人角度提出的期望（不涉及技術方案）
4. questions_to_others: 想請其他角色（analyst/expert）回答的問題

# 約束
- 必須以你代表的利害關係人角色立場發言
- 使用第一人稱，以該角色的日常經驗為基礎
- 禁止提出技術解決方案，只表達「需要什麼」

輸出 JSON:
{{{{
    "position": "作為...，我認為...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["期望1", "期望2"],
    "questions_to_others": [{{{{"to": "agent名稱", "question": "問題"}}}}]
}}}}"""

        self.memory.add("user", f"回應議題: {topic.get('title', '')[:50]}")
        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "position": response.get("position", ""),
            "arguments": response.get("arguments", []),
            "suggestions": response.get("suggestions", []),
            "questions_to_others": response.get("questions_to_others", []),
        }
