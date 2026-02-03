import json

from typing import Dict, List, Any

# 文件代理
class DocumentorAgent:
    def __init__(self, model, store):
        self.model = model
        self.store = store

    # 根據 MoM JSON 產生 Design Rationale
    def generate_design_rationale(self) -> str:
        mom_data = self.store.load_mom()
        mom_json_str = json.dumps(mom_data, ensure_ascii=False, indent=2)

        user_prompt = f"""請根據會議記錄: {mom_json_str}，

請整理出 Design Rationale，包含以下內容:
1. 決策理由：整理每個重要決策的原因和考量因素
2. 方案取捨過程：整理如何在多個方案中進行選擇的過程
3. 替代方案：整理被考慮但未採用的方案
4. 依據與參考：整理決策所依據的專家建議或資源

請以完整的 Markdown 格式輸出，使用清晰的章節結構和要點列表。
注意：只整理會議記錄中已有的內容，不要添加額外的建議或假設。"""

        dr_content = self.model.generate(user_prompt)
        return dr_content

    # 根據 draft.json 和 IEEE 29148 模板產生 srs.json
    def generate_srs_json(self, draft: Dict[str, Any], ieee_template: List[Dict]) -> Dict[str, Any]:
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        template_text = json.dumps(ieee_template, ensure_ascii=False, indent=2)

        system_prompt = "你是軟體需求規格書撰寫專家，任務是撰寫符合 IEEE 29148 標準的 SRS 文件。"

        user_prompt = f"""需求草稿:
{draft_text}

輸出 JSON，遵循以下 IEEE 29148 模板結構:
{template_text}"""

        print(user_prompt)

        srs = self.model.generate_json(user_prompt, system_prompt)
        return srs
