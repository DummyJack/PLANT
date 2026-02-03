from typing import Dict, List, Any
import json


# 文件代理
class DocumentorAgent:
    """
    - 依 mom.json 產出 Design Rationale (dr.md)
    - 依 spec.json + 29148.json 產出 srs.json 和 srs.md
    """

    def __init__(self, model, store):
        self.model = model
        self.store = store

    # 根據 MoM JSON 產生 Design Rationale
    def generate_design_rationale(self) -> str:

        mom_data = self.store.load_mom()

        # 將 JSON 轉為字串當作 LLM 上下文
        mom_json_str = json.dumps(mom_data, ensure_ascii=False, indent=2)

        user_prompt = f"""請根據以下會議記錄 JSON 整理 Design Rationale。

                會議記錄：{mom_json_str}
                

                請整理出以下章節的 Design Rationale（只整理會議記錄中已有的資訊，不要額外假設）：
                1. **決策理由**：整理每個重要決策的原因和考量因素
                2. **方案取捨過程**：整理如何在多個方案中進行選擇的過程
                3. **替代方案**：整理被考慮但未採用的方案
                4. **依據與參考**：整理決策所依據的專家建議或資源

                請以完整的 Markdown 格式輸出，使用清晰的章節結構和要點列表。
                重要：只整理會議記錄中已有的內容，不要添加額外的建議或假設。"""

        dr_content = self.model.generate(user_prompt)
        return dr_content

    # 根據 draft.json 和 IEEE 29148 模板產生 srs.json
    def generate_srs_json(
        self, draft: Dict[str, Any], ieee_template: List[Dict]
    ) -> Dict[str, Any]:
        draft_text = json.dumps(draft, ensure_ascii=False, indent=2)
        template_text = json.dumps(ieee_template, ensure_ascii=False, indent=2)

        system_prompt = (
            "你是軟體需求規格書撰寫專家，擅長撰寫符合 IEEE 29148 標準的 SRS 文件。"
        )

        user_prompt = f"""需求草稿（Draft）：
                {draft_text}

                IEEE 29148 標準結構：
                {template_text}

                請將需求草稿轉換為符合 IEEE 29148 標準的 SRS 文件。
                將 draft 中的內容對應到 IEEE 29148 的章節結構中。

                請以 JSON 格式回應，遵循 IEEE 29148 結構。"""

        srs = self.model.generate_json(user_prompt, system_prompt)
        return srs
