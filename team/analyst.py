import itertools
import json

from typing import Dict, List, Optional

from agents.base import BaseAgent
from agents.memory import Memory


class AnalystAgent(BaseAgent):
    """系統分析師 Agent — Reflection + Agent Communication"""

    name = "analyst"

    system_prompt = """你是系統分析師（Analyst Agent），專責需求分析與衝突辨識。

核心原則：
1. 逐條比對 — 針對利害關係人的每條需求逐一交叉比對，找出矛盾
2. 引用具體條目 — 判斷衝突時必須指出是哪些具體需求項目之間的矛盾
3. 中立立場 — 不偏袒任何利害關係人，不提出解決方案
4. 寧嚴勿漏 — 寧可標記為潛在衝突，也不要遺漏明顯矛盾"""

    reflection_criteria = "衝突判斷必須引用具體的需求條目，說明哪條與哪條矛盾、為什麼矛盾。若標記為 Neutral，需確認確實不存在任何衝突。"

    def __init__(self, model, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None):
        super().__init__(model, tools=tools, memory=memory, registry=registry)

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

        is_refined = any(
            (isinstance(sh.get("text"), list) and any("[KEEP]" in t or "[REVISE]" in t or "[ADD]" in t for t in sh["text"]))
            or (isinstance(sh.get("text"), str) and ("[KEEP]" in sh["text"] or "[REVISE]" in sh["text"] or "[ADD]" in sh["text"]))
            for sh in stakeholder_group
        )

        refined_note = ""
        if is_refined:
            refined_note = """# 特別注意
這是精煉後的需求，每條標記 [KEEP] 保留、[REVISE] 修正、[ADD] 新增。
請特別比對 [REVISE] 和 [ADD] 部分是否與其他利害關係人產生新衝突。
"""

        if is_all_analysis:
            user_prompt = f"""# 任務
針對所有利害關係人的需求進行全面分析：辨識整體衝突 + 提取候選需求。
{refined_note}
# 利害關係人發言
{stakeholder_texts}

# 分析步驟
1. 先逐條交叉比對所有利害關係人的需求，判斷整體是否存在矛盾或衝突
2. 根據比對結果，明確判定 label 為 "Conflict"（存在任何衝突）或 "Neutral"（完全無衝突）
3. 在 reason 中具體說明哪些需求之間存在矛盾，或為何判定無衝突
4. 從每位利害關係人的發言中提取候選需求（去重、合併相似項）

# 輸出 JSON（所有欄位皆為必填，不可為 null）
{{{{
    "label": "Conflict" 或 "Neutral"（必填，不可為 null）,
    "reason": "整體判斷理由，須引用具體需求條目（必填，不可為 null）",
    "candidates": [
        {{{{"id": "R-01", "text": "需求描述", "source": ["stakeholder_name"]}}}}
    ]
}}}}"""
        else:
            user_prompt = f"""# 任務
針對以下兩位利害關係人的需求進行衝突辨識。
{refined_note}
# 利害關係人發言
{stakeholder_texts}

# 分析步驟
1. 逐條比對兩位利害關係人的每條需求
2. 識別是否存在矛盾、衝突或不相容

# 輸出 JSON
{{{{
    "label": "Conflict" 或 "Neutral",
    "reason": "判斷理由"
}}}}"""

        self.memory.add("user", user_prompt)
        response = self.generate_with_reflection(user_prompt, temperature=1)

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

# 約束
- 保持中立，不偏袒任何利害關係人
- 論點須有具體需求依據，不得空泛

輸出 JSON:
{{{{
    "position": "從分析角度...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"]
}}}}"""

        self.memory.add("user", f"回應議題: {topic.get('title', '')[:50]}")
        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "position": response.get("position", ""),
            "arguments": response.get("arguments", []),
            "suggestions": response.get("suggestions", []),
        }
