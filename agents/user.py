import json

from typing import Dict, List

# 利害關係人模擬代理
class UserAgent:

    def __init__(self, model):
        self.model = model

    # 產生利害關係人
    def propose_stakeholders(self, rough_idea: str) -> List[str]:
        user_prompt = f"""根據初始想法: {rough_idea}，建議 5-8 位可能相關的利害關係人(核心使用者優先考慮，再來考慮系統所有者與管理者與外部相關單位)，並附上選擇理由。

        輸出 JSON:
        {{{{
        "proposed_stakeholders": [
        {{{{
            "name": "利害關係人名稱",
            "reason": "選擇理由"
        }}}}
        ]
        }}}}"""

        response = self.model.generate_json(user_prompt)
        return response.get("proposed_stakeholders", [])

    # 模擬所選中的利害關係人，產生需求
    def generate_stakeholder_requirements(
        self, rough_idea: str, selected_stakeholders: List[str]
    ) -> List[Dict[str, str]]:
        # 利害關係人列表
        stakeholder_list = ", ".join(
            [f"{i+1}. {sh}" for i, sh in enumerate(selected_stakeholders)]
        )

        user_prompt = f"""模擬利害關係人有 {stakeholder_list}，請以第一人稱、口語方式從自己角度提出需求、期望。

背景(僅供參考): {rough_idea}

輸出 JSON：
{{{{
"stakeholders": [
    {{{{"id": "SH-01", "name": "...", "text": "..."}}}}
]
}}}}"""
        try:
            response = self.model.generate_json(user_prompt, temperature=1.2)
            stakeholders = response.get("stakeholders", [])

            # 驗證格式
            for sh in stakeholders:
                if not all(key in sh for key in ["id", "name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")

            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗，原因: {str(e)}")

    # 第二輪以上，原有基礎上繼續提出需求
    def refine_stakeholders(
        self, current_stakeholders: List[Dict], additional_ideas: List[Dict] = None, draft_text: str = None
    ) -> List[Dict[str, str]]:
        
        # 如果沒有提供 draft_text，使用預設文字
        if draft_text is None:
            draft_text = "目前無需求草稿"
        
        # 準備所有利害關係人的第一輪發言
        stakeholders_summary = ""
        for sh in current_stakeholders:
            stakeholders_summary += f"\n【{sh['name']}】(ID: {sh['id']})\n{sh['text']}\n"
        
        # 準備額外想法（如果有）
        additional_ideas_text = ""
        if additional_ideas:
            additional_ideas_text = "\n額外想法:"
            for idea in additional_ideas:
                additional_ideas_text += f"Round {idea.get('round', '?')}: {idea.get('idea', '')}\n"
        
        user_prompt = f"""
需求草稿:
{draft_text}

【第一輪各利害關係人的發言】
{stakeholders_summary}

{additional_ideas_text}

任務:
- 每一位利害關係人，閱讀需求草稿後，針對自己的需求進行調整。
- 每位利害關係人需要從三個面向表達：

1. **KEEP（保留）**
   - 列出草稿中已經反映、且希望繼續保留的需求
   - 這些需求符合期待，不需要修改

2. **REVISE（修正）**
   - 指出草稿中「已存在但不夠好」的需求
   - 說明希望如何調整，以及為什麼需要調整
   - 例如：描述不夠明確、遺漏重要細節、與立場不一致

3. **ADD（新增）**
   - 提出草稿中「完全沒有但認為必要」的新需求
   - 可能是第一輪未提及，或是基於草稿內容產生的新想法

撰寫規則:
- 每位利害關係人只代表自己的立場，使用第一人稱
- 不需要考慮其他利害關係人是否同意
- 不要裁決衝突或提出折衷方案
- 使用條列式，每點簡潔明確
- 即使某個部分沒有內容，標題仍需保留並標註「無」


輸出 JSON:
{{
  "stakeholders": [
    {{"id": "SH-01", "name": "利害關係人名稱", "text": "[KEEP]\\n- ...\\n\\n[REVISE]\\n- ...\\n\\n[ADD]\\n- ..."}}
  ]
}}

請確保:
- 每位利害關係人都要有輸出
- text 欄位必須包含 [KEEP]、[REVISE]、[ADD] 三個區塊
- 使用 \\n 表示換行
"""
        try:
            response = self.model.generate_json(user_prompt, temperature=1.2)
            refined_stakeholders = response.get("stakeholders", [])
            
            # 驗證格式
            for sh in refined_stakeholders:
                if not all(key in sh for key in ["id", "name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
            
            return refined_stakeholders
        except Exception as e:
            print(f"精煉利害關係人失敗: {str(e)}")
            # 如果失敗，返回原有的利害關係人
            return current_stakeholders
