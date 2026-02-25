import itertools

from typing import Dict, List, Optional
from agents.base import BaseAgent


class AnalystAgent(BaseAgent):
    """系統分析師 Agent — Reflection + Agent Communication"""

    name = "analyst"

    system_prompt = """你是需求分析師，專門辨識利害關係人之間的需求衝突。

在需求工程中，當不同利害關係人對同一系統的描述存在不一致時即為衝突，包括但不限於：
- 術語衝突：對同一元件使用不同名稱或定義
- 範圍衝突：對系統組成、功能範圍的描述不同（增減元件、功能）
- 數值衝突：對數量、規格、限制條件的描述不同
- 行為衝突：對系統行為或流程的期望不同

只有當兩方描述完全一致、或各自描述不相關的獨立需求時，才判定為 Neutral。"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)

    @staticmethod
    def format_text(text) -> str:
        """將 text（str 或 list）格式化為帶編號的文字"""
        if isinstance(text, list):
            return "\n".join(f"  {i}. {t}" for i, t in enumerate(text, 1))
        return text

    def analyze_groups(self, stakeholders: List[Dict]) -> List[Dict]:
        """按發言索引分組：同一索引位置的發言跨利害關係人做兩兩 + 全部分析"""
        groups = []

        # 找出最大發言數量
        max_len = max(
            len(sh["text"]) if isinstance(sh.get("text"), list) else 1
            for sh in stakeholders
        )

        for idx in range(max_len):
            # 收集每位利害關係人在此索引的發言
            index_group = []
            for sh in stakeholders:
                text = sh.get("text", [])
                if isinstance(text, list) and idx < len(text):
                    index_group.append({"name": sh["name"], "text": text[idx]})
                elif isinstance(text, str) and idx == 0:
                    index_group.append({"name": sh["name"], "text": text})

            if len(index_group) < 2:
                continue

            # 兩兩分析
            for combo in itertools.combinations(index_group, 2):
                groups.append(self.analyze_conflict(list(combo)))

            # 全部分析（不提取候選需求）
            if len(index_group) > 2:
                groups.append(self.analyze_conflict(index_group))

        # 最後：全部利害關係人的所有發言提取候選需求（只做一次）
        if len(stakeholders) > 1:
            groups.append(self.analyze_conflict(stakeholders, is_all_analysis=True))

        return groups

    def analyze_conflict(self, stakeholder_group: List[Dict], is_all_analysis: bool = False) -> Dict:
        stakeholder_texts = "\n\n".join(
            f"{sh['name']}:\n{self.format_text(sh['text'])}" for sh in stakeholder_group
        )

        if is_all_analysis:
            user_prompt = f"""# 利害關係人發言
{stakeholder_texts}

# 任務
1. 比較各方發言，找出術語、範圍、數值或行為上的任何不一致
2. 有不一致 → label="Conflict"；完全一致或各自獨立 → label="Neutral"
3. 提取候選需求（去重、合併相似項）

# 輸出 JSON
{{{{
    "label": "Conflict 或 Neutral",
    "reason": "簡述不一致之處",
    "candidates": [
        {{{{"id": "R-01", "text": "需求描述", "source": ["stakeholder_name"]}}}}
    ]
}}}}"""
        else:
            user_prompt = f"""# 利害關係人發言
{stakeholder_texts}

# 任務
比較兩方發言，找出術語、範圍、數值或行為上的任何不一致。
有不一致 → label="Conflict"；完全一致或各自獨立 → label="Neutral"。

# 輸出 JSON
{{{{
    "label": "Conflict 或 Neutral",
    "reason": "簡述不一致之處"
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages, temperature=1)

        result = {
            "texts": {sh["name"]: sh["text"] for sh in stakeholder_group},
            "label": response.get("label"),
            "reason": response.get("reason"),
        }
        if is_all_analysis:
            result["candidates"] = response.get("candidates", [])
        return result

    # 覆寫：議題討論回應

    def respond_to_topic(self, topic, previous_responses=None):
        """從需求一致性與衝突角度回應議題"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = []
            for r in previous_responses:
                agent = r.get("agent", "?")
                resp = r.get("response", {})
                content = resp.get("content", resp.get("position", ""))
                parts.append(f"【{agent}】{content}")
            prev_text = "\n前面的發言:\n" + "\n".join(parts)

        user_prompt = f"""你正在以系統分析師的身份參與需求討論。

{topic_text}
{prev_text}

# 回應要求
1. position: 從需求一致性與完整性角度的分析結論
2. arguments: 基於需求分析的客觀論點（標明衝突風險、遺漏風險等）
3. suggestions: 降低衝突或提升需求完整性的建議
4. questions_to_others: 想請其他角色（user/expert）回答的問題

# 約束
- 保持中立，不偏袒任何利害關係人
- 論點須有具體需求依據，不得空泛

輸出 JSON:
{{{{
    "position": "從分析角度...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"],
    "questions_to_others": [{{{{"to": "agent名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "position": response.get("position", ""),
            "arguments": response.get("arguments", []),
            "suggestions": response.get("suggestions", []),
            "questions_to_others": response.get("questions_to_others", []),
        }
