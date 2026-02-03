from typing import Dict, List
import json


# 利害關係人模擬代理
class UserAgent:

    def __init__(self, model):
        self.model = model

    # 產生利害關係人
    def propose_stakeholders(self, rough_idea: str) -> List[str]:
        user_prompt = f"""根據初始想法: {rough_idea}，建議 5-8 位可能的利害關係人(核心使用者優先考慮，再來考慮系統所有者與管理者與外部相關單位)，並附上選擇理由。

                請以 JSON 格式回應：
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
        stakeholder_list = "\n".join(
            [f"{i+1}. {sh}" for i, sh in enumerate(selected_stakeholders)]
        )

        system_prompt = f"""
        你是一個軟體需求工程流程中的「利害關係人模擬代理人」。

        你的任務是模擬多位不同的利害關係人。
        本次必須模擬的利害關係人清單如下：
        {stakeholder_list}

        對於清單中的「每一位」利害關係人，你都必須產生一段發言，
        且每位利害關係人的觀點可以彼此不同，甚至互相衝突。

        請遵守以下原則：
        - 以第一人稱、口語、非正式方式表達想法
        - 使用模糊、不完整或帶有主觀感受的描述
        - 不需要追求一致性或完整性
        - 可以隱含假設，但不必說明理由
        - 嚴禁使用技術術語、系統架構、解決方案描述

        請注意：
        - 不要分析需求
        - 不要整理或總結
        - 不要提出系統層級建議
        - 只表達「我想要什麼 / 我在意什麼 / 我不滿什麼」

        系統初始想法（背景，不需重述）：
        {rough_idea}

        請以以下 JSON 格式輸出，且不得包含任何額外說明文字：

        {{
        "stakeholders": [
        {{
            "id": "SH-01",
            "name": "利害關係人名稱（需來自清單）",
            "text": "該利害關係人的發言內容"
        }}
        ]
        }}
        """

        try:
            response = self.model.generate_json("", system_prompt)
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
        self, current_stakeholders: List[Dict], previous_draft: Dict
    ) -> List[Dict[str, str]]:
        current_text = json.dumps(current_stakeholders, ensure_ascii=False, indent=2)
        draft_text = json.dumps(previous_draft, ensure_ascii=False, indent=2)
        stakeholder_names = [sh["name"] for sh in current_stakeholders]
        stakeholder_list = "\n".join(
            [f"{i+1}. {name}" for i, name in enumerate(stakeholder_names)]
        )

        user_prompt = f"""目前的利害關係人需求：
                    {current_text}

                    上一輪的需求草稿摘要：
                    {draft_text}

                    請根據上一輪的成果，在原有需求的基礎上繼續提出新的需求。
                    注意：不是精煉或調整原有需求，而是基於系統演進，提出新的需求，例如：
                    - 提出新的功能需求（基於上一輪未滿足的部分）
                    - 提出更深入的操作流程需求
                    - 提出新的使用情境和場景
                    - 發現新的問題和改進點
                    
                    保留原有需求，並新增額外的需求描述。

                    請以 JSON 格式回應：
                    {{{{
                        "stakeholders": [
                        {{{{
                            "id": "SH-XX",
                            "name": "利害關係人名稱",
                            "text": "原有需求 + 新增的需求描述（新的功能、流程、情境）"
                        }}}}
                        ]
                    }}}}"""

        try:
            response = self.model.generate_json(user_prompt)
            return response.get("stakeholders", current_stakeholders)
        except Exception as e:
            return current_stakeholders
