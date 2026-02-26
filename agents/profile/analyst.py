import json

from itertools import combinations
from typing import Dict, List, Optional
from agents.base import BaseAgent


class AnalystAgent(BaseAgent):
    """需求轉換、分類、利害關係人衝突辨識、草稿版本管理。"""

    name = "analyst"

    system_prompt = """你是需求分析師。

核心職責：
1. 需求轉換 — 將口語化利害關係人需求轉換為正式需求描述
2. 需求分類 — 區分功能性（FR）與非功能性需求（NFR）
3. 衝突辨識 — 辨識利害關係人之間需求衝突"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)
    
    def detect_stakeholder_conflicts(self, stakeholders: List[Dict]) -> List[Dict]:
        """辨識利害關係人需求衝突：pair-wise + 全部，合併去重"""
        if len(stakeholders) < 2:
            return []
        pairwise = self.detect_stakeholder_conflicts_pairwise(stakeholders)
        holistic = self.detect_stakeholder_conflicts_all(stakeholders)
        return self.merge_conflicts(pairwise, holistic, key="stakeholder_names")

    def detect_stakeholder_conflicts_pairwise(self, stakeholders: List[Dict]) -> List[Dict]:
        """逐對比較利害關係人的發言，辨識兩兩之間的衝突"""
        conflicts = []
        for s1, s2 in combinations(stakeholders, 2):
            name1 = s1.get("name", "")
            name2 = s2.get("name", "")
            raw1 = s1.get("text", "")
            raw2 = s2.get("text", "")
            texts1 = raw1 if isinstance(raw1, list) else [raw1] if raw1 else []
            texts2 = raw2 if isinstance(raw2, list) else [raw2] if raw2 else []
            if not texts1 or not texts2:
                continue
            lines1 = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts1))
            lines2 = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts2))

            user_prompt = f"""# 任務
辨識以下兩位利害關係人的發言之間是否存在衝突。

# {name1} 的發言（共 {len(texts1)} 條）
{lines1}

# {name2} 的發言（共 {len(texts2)} 條）
{lines2}

# 衝突類型
- Inconsistency: 不一致（陳述互相矛盾或無法同時成立）
- Ambiguity: 歧義（表述有多種解讀、指涉不明或定義模糊）
- Redundancy: 冗餘（重複或重疊的表述，可能造成衝突或維護負擔）
- Contradiction: 直接矛盾（兩方主張互斥）
- Overlap: 重疊衝突（部分重疊但意圖或優先性不同）

# 判斷標準
- 某一對（{name1} 第 i 條 vs {name2} 第 j 條）存在語意衝突時，輸出一筆 Conflict，description 請簡要說明是哪幾條以及衝突內容
- 若某對僅是不同關注點但不矛盾，標記為 Neutral
- 可輸出多筆 conflicts（每對衝突的發言配對一筆）

# 輸出 JSON
{{{{
    "conflicts": [
        {{{{
            "label": "Conflict 或 Neutral",
            "description": "衝突描述（若 Neutral 則簡述原因）",
            "stakeholder_names": ["{name1}", "{name2}"]
        }}}}
    ]
}}}}"""

            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages)
            conflicts.extend(response.get("conflicts", []))

        return conflicts

    def detect_stakeholder_conflicts_all(self, stakeholders: List[Dict]) -> List[Dict]:
        """一次檢視所有利害關係人發言（text[0]、text[1]…），辨識整體性或多方衝突"""
        parts = []
        for s in stakeholders:
            raw = s.get("text", "")
            texts = raw if isinstance(raw, list) else [raw] if raw else []
            segs = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(texts))
            parts.append(f"【{s.get('name', '')}】的發言：\n{segs}")
        speeches_text = "\n\n".join(parts)

        user_prompt = f"""# 任務
辨識以下利害關係人發言之間是否存在衝突。

# 利害關係人發言
{speeches_text}

# 衝突類型
- Inconsistency: 不一致（陳述互相矛盾或無法同時成立）
- Ambiguity: 歧義（表述有多種解讀、指涉不明或定義模糊）
- Redundancy: 冗餘（重複或重疊的表述，可能造成衝突或維護負擔）
- Contradiction: 直接矛盾（主張互斥）
- Overlap: 重疊衝突（部分重疊但意圖或優先性不同）

# 判斷標準
- 有衝突，label 填寫 Conflict
- 若沒有衝突，label 填寫 Neutral

# 輸出 JSON
{{{{
    "conflicts": [
        {{{{
            "label": "Conflict" or "Neutral",
            "description": "衝突描述（若 Neutral 則簡述原因）",
            "stakeholder_names": ["涉及的利害關係人"],
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)
        return response.get("conflicts", [])

    def merge_conflicts(self, pairwise: List[Dict], holistic: List[Dict], key: str = "stakeholder_names") -> List[Dict]:
        """合併 pair-wise 和全部衝突結果"""
        merged = list(pairwise)
        existing_sets = set()
        for c in pairwise:
            names = tuple(sorted(c.get(key, [])))
            existing_sets.add(names)

        for c in holistic:
            names = tuple(sorted(c.get(key, [])))
            if names not in existing_sets:
                merged.append(c)
                existing_sets.add(names)

        return merged

    def create_draft(self, stakeholders: List[Dict]) -> Dict:
        requirements = self.convert_to_requirements(stakeholders)
        return {"requirements": requirements, "conflicts": []}

    def convert_to_requirements(self, stakeholders: List[Dict]) -> List[Dict]:
        stakeholder_text = json.dumps(stakeholders, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
將以下利害關係人需求轉換為結構化的需求規格。

# 利害關係人資料
{stakeholder_text}

# 處理步驟
1. 將每位利害關係人的 text 轉換為正式的 requirements，標記 source_stakeholders
2. 分類為 FR（功能性需求）或 NFR（非功能性需求）

# NFR 要求
每條 NFR 必須包含可量化的指標，禁止使用模糊形容詞。
- 效能：須指定回應時間（如「API 回應時間 ≤ 200ms，P99」）、吞吐量、並發數
- 可用性：須指定正常運行時間（如「系統可用性 ≥ 99.9%」）
- 安全性：須指定安全等級或標準（如「符合 OWASP Top 10 防護要求」）
- 可擴展性：須指定預期負載範圍（如「支援 10,000 並發使用者」）
若利害關係人原始需求模糊，分析師應根據系統類型推定合理的量化指標。

# 輸出 JSON
{{{{
    "requirements": [
        {{{{
            "id": "R-01",
            "text": "正式的需求描述",
            "type": "FR 或 NFR",
            "source_stakeholders": ["利害關係人名稱"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        requirements = response.get("requirements", [])
        for req in requirements:
            req.setdefault("type", "FR")
            req.setdefault("source_stakeholders", [])

        return requirements

    def update_draft(self, artifact: Dict) -> Dict:
        """Round 級更新 Step 5.2: 根據決策更新需求草稿"""
        context = {
            "requirements": artifact.get("requirements", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
        }
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
根據最新的決策和討論結果，更新需求草稿。

# 當前資料
{context_text}

# 更新規則
1. 根據 discussions 修改或新增 requirements
2. 已解決的衝突（label 改為 Neutral）對應的需求應反映最終決策
3. 保留未受影響的需求不變
4. 去除因決策而不再需要的需求

# 輸出 JSON
{{{{
    "requirements": [
        {{{{
            "id": "R-01",
            "text": "需求描述",
            "type": "FR 或 NFR 或 constraint",
            "source_stakeholders": ["來源"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        requirements = response.get("requirements", artifact.get("requirements", []))
        return {
            "requirements": requirements,
            "conflicts": artifact.get("conflicts", []),
        }

    def respond_to_topic(self, topic, previous_responses=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        user_prompt = f"""你正在以系統分析師的身份參與需求討論。

{topic_text}
{prev_text}

# 思考與發言流程
1. 先思考：(1) 此議題與既有需求的一致性與缺口 (2) 不可讓步的要點（須有需求依據）(3) 可接受調整或折衷的要點
2. 再根據思考結果，撰寫一段完整的發言（statement），針對議題提出你的分析與建議
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"expert"、"modeler"）

# 約束
- 保持中立，不偏袒任何利害關係人
- statement 必須是完整、有條理的發言，論點須有具體需求依據

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }
