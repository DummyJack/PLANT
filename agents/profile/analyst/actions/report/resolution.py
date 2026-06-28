# Defines action prompts and output contracts.
from utils.language import current_output_language, output_language_directive
from agents.profile.base import forbidden_output_rules

def report_resolution() -> str:
    if current_output_language() == "en":
        strategy_rule = (
            "strategy must use an English strategy name, such as Conditional Logic, "
            "Stakeholder Negotiation, Prioritization, Technical Solution, Decomposition, "
            "Compromise, Scope Adjustment, Sequencing, or Parallel Tracks."
        )
    else:
        strategy_rule = (
            "strategy 必須使用繁體中文策略名稱；可使用「條件邏輯」、「利害關係人協商」、"
            "「優先順序決策」、「技術方案」、「需求拆解」、「折衷方案」、「範圍調整」、"
            "「分階段處理」或「並行處理」。"
        )
    return f"""# 任務
根據單一已定案 Conflict 項目產生解決選項。

# Action Boundary
- action=conflict_resolution
- 本 action 對單一已定案 Conflict 產生 conflict_resolution JSON。
- conflict_resolution 提供可供後續討論或採用的 resolution_options 與 recommended_resolution。
- 輸入的 final_label、final_type、description 視為定案內容。

# Input
- 單一已定案 Conflict 項目由 runtime context 提供。
- resolution strategy guidance 若存在，由 runtime context 提供。

# Generation Rules
- 輸入資料已完成衝突辨識與衝突再審查。
- final_label、final_type、description 視為定案內容。
- final_type 只作為策略候選方向；實際解法必須根據需求內容與衝突描述決定。
- 若 final_type 是 other，不要硬套特定衝突類型；請根據需求內容與衝突描述產生可行解法。
- 若本任務沒有提供 resolution strategy guidance，代表此 Conflict 無對應類型策略；請只根據需求內容與衝突描述產生解法。
- {output_language_directive()}
- {strategy_rule}
- recommended_resolution 不要顯示 strategy 或策略名稱；請用「建議採用選項 A」或具體處理方式描述建議理由。
- id 必須使用輸入 Conflict 項目的 id，不可自行產生 CONF-* 或 CR-*。
- 需求 id 與 text 只作為判斷依據，不可改寫。
- 輸出只包含下方 JSON 欄位。

# Output JSON
{{
  "conflict_resolution": {{
    "id": "Conflict 項目 id",
    "resolution_options": [
      {{
        "option": "A",
        "strategy": "Resolution strategy name",
        "description": "處理方式",
        "pros": ["優點"],
        "cons": ["限制或代價"],
        "recommendation": true
      }}
    ],
    "recommended_resolution": "建議採用的 resolution 與理由"
  }}
}}

{forbidden_output_rules(
        [
            "不輸出 conflict report。",
            "不輸出 Conflict/Neutral 重新分類結果。",
            "不新增、改寫、刪除 URL 或 REQ。",
            "不輸出 conflict_resolution 以外的 wrapper。",
        ]
    )}"""
