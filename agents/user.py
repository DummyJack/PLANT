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
        self, current_stakeholders: List[Dict], additional_ideas: List[Dict] = None
    ) -> List[Dict[str, str]]:

        user_prompt = f"""根據目前的利害關係人需求：
                    {current_stakeholders}

                    {additional_ideas}

                    請根據上一輪的成果和額外想法，在原有需求的基礎上繼續提出新的需求。
                    
                    任務：
                    1. **整合額外想法**：如果有人類提出的額外想法，請將其轉化為利害關係人的需求表達
                    2. **演進需求**：基於系統演進，提出新的需求，例如：
                       - 提出新的功能需求（基於上一輪未滿足的部分）
                       - 提出更深入的操作流程需求
                       - 提出新的使用情境和場景
                       - 發現新的問題和改進點
                    
                    注意：
                    - 不是精煉或調整原有需求，而是新增需求
                    - 保留原有需求，並新增額外的需求描述
                    - 以利害關係人的第一人稱口吻表達（例如："我希望..."、"我需要..."）

                    請以 JSON 格式回應：
                    {{{{
                        "stakeholders": [
                        {{{{
                            "id": "SH-XX",
                            "name": "利害關係人名稱",
                            "text": ["原有需求", "新增的需求描述(包含額外想法轉化的需求"]
                        }}}}
                        ]
                    }}}}"""

        try:
            response = self.model.generate_json(user_prompt)
            return response.get("stakeholders", current_stakeholders)
        except Exception as e:
            return current_stakeholders
