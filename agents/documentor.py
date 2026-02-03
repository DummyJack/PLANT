import json

from typing import Dict, List, Any

# 文件代理
class DocumentorAgent:
    def __init__(self, model, store):
        self.model = model
        self.store = store

    # 根據 MoM 產生 Design Rationale
    def generate_design_rationale(self) -> str:
        mom_data = self.store.load_mom()
        
        # 提取需要的內容
        extracted_data = self.extract_dr_data(mom_data)
        mom_json_str = json.dumps(extracted_data, ensure_ascii=False, indent=2)

        user_prompt = f"""請根據以下資料整理出 Design Rationale:

{mom_json_str}

請整理出以下內容:

## 1. 決策理由
- 整理每個重要決策的原因和考量因素
- 從 conflict_resolutions 中提取決策和理由

## 2. 方案取捨過程
- 整理如何在多個方案中進行選擇的過程
- 從 options 中提取所有考慮過的方案
- 說明為什麼選擇某個方案，為什麼不選擇其他方案

## 3. 替代方案
- 整理被考慮但未採用的方案
- 從 options 中提取未被採用的選項
- 說明這些方案的優缺點

## 4. 依據與參考
- 整理決策所依據的專家建議或資源
- 從 feedback 中提取專家建議和參考來源

請以完整的 Markdown 格式輸出，使用清晰的章節結構和要點列表。
重要：只整理提供的資料中已有的內容，不要添加額外的建議或假設。"""

        print(user_prompt)

        dr_content = self.model.generate(user_prompt)
        return dr_content
    
    # 從 MoM 中提取 Design Rationale 需要的資料
    def extract_dr_data(self, mom_data: Dict[str, Any]) -> Dict[str, Any]:
        extracted = {
            "feedback": [],
            "options": [],
            "conflict_resolutions": []
        }
        
        rounds = mom_data.get("rounds", [])
        
        for round_data in rounds:
            # 提取 conflict_resolutions
            if "conflict_resolutions" in round_data:
                extracted["conflict_resolutions"].extend(
                    round_data["conflict_resolutions"]
                )
            
            # 從 stages 中提取 feedback 和 options
            stages = round_data.get("stages", [])
            for stage in stages:
                outputs = stage.get("outputs", {})
                
                # 提取 feedback
                if "feedback" in outputs:
                    extracted["feedback"].extend(outputs["feedback"])
                
                # 提取 decision_options (options)
                if "decision_options" in outputs:
                    extracted["options"].extend(outputs["decision_options"])
        
        return extracted

    # 根據 draft.json 和 IEEE 29148 模板產生 srs.json
    def generate_srs_json(self, draft: Dict[str, Any], uml: Dict[str, Any], ieee_template: List[Dict]) -> Dict[str, Any]:
        formatted_draft = self.store.generate_draft_markdown(draft)
        uml_text = json.dumps(uml, ensure_ascii=False, indent=2)
        template_text = json.dumps(ieee_template, ensure_ascii=False, indent=2)

        system_prompt = "你是軟體需求規格書撰寫專家，任務是撰寫符合 IEEE 29148 標準的 SRS 文件。"

        user_prompt = f"""請根據以下需求草稿和 UML 系統模型，產生符合 IEEE 29148 標準的 SRS 文件:

需求草稿:
{formatted_draft}

UML 系統模型:
{uml_text}

輸出 JSON，遵循以下結構:
{template_text}"""

        srs = self.model.generate_json(user_prompt, system_prompt)
        return srs
