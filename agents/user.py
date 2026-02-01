from typing import Dict, List
import json

class UserAgent:
    """
    User Agent: 利害關係人模擬代理
        - 以利害關係人的角度提出需求
    """
    
    def __init__(self, model):
        self.model = model
    
    # 模擬所選中的利害關係人，產生需求
    def generate_stakeholder_requirements(self, system_description: str, selected_stakeholders: List[str]) -> List[Dict[str, str]]:
        # 準備利害關係人列表
        stakeholder_list = "\n".join([f"{i+1}. {sh}" for i, sh in enumerate(selected_stakeholders)])

        system_prompt = f"你會模擬不同的真實的利害關係人，用他們各自的角度對系統提出需求"
        
        user_prompt = f"""
                  系統概述：{system_description}

                  利害關係人列表：{stakeholder_list}

                  根據以上的利害關係人列表，讓他們各自獨自思考自己的需求

                  請以 JSON 格式回應：
                  {{{{
                    "stakeholders": [
                      {{{{
                        "id": "SH-01",
                        "name": "利害關係人名稱",
                        "text": "利害關係人敘述"
                      }}}}
                    ]
                  }}}}"""
   
        try:
            response = self.model.generate_json(user_prompt, system_prompt)
            stakeholders = response.get("stakeholders", [])
            
            # 驗證格式
            for sh in stakeholders:
                if not all(key in sh for key in ["id", "name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
            
            return stakeholders
        except Exception as e:
            raise RuntimeError(f"UserAgent 生成失敗，原因: {str(e)}")
    
    # 多輪時在原有基礎上繼續提出需求
    def refine_stakeholders(self, current_stakeholders: List[Dict], previous_draft: Dict) -> List[Dict[str, str]]:
        current_text = json.dumps(current_stakeholders, ensure_ascii=False, indent=2)
        draft_text = json.dumps(previous_draft, ensure_ascii=False, indent=2)
        
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
        
        # 準備 system prompt
        stakeholder_names = [sh['name'] for sh in current_stakeholders]
        stakeholder_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(stakeholder_names)])
        system_prompt = f"你會扮演的利害關係人:{stakeholder_list}，以他們的角度持續提出需求。"
        
        try:
            response = self.model.generate_json(user_prompt, system_prompt)
            return response.get("stakeholders", current_stakeholders)
        except Exception as e:
            return current_stakeholders
