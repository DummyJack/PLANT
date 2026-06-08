# Defines action prompts and output contracts.

def report_resolution() -> str:
    return """# 任務
根據單一已定案 Conflict 項目產生解決選項。

# Action Boundary
- action=conflict_resolution
- 本 action 只對單一已定案 Conflict 產生 conflict_resolution。
- 不重新分類 Conflict/Neutral、不新增衝突、不移除衝突。
- 不改寫 URL / REQ 原文；只提出可供後續討論或決策的解法。
- 最外層只能輸出 conflict_resolution。

# Input
- 單一已定案 Conflict 項目由 runtime context 提供。
- resolution strategy guidance 若存在，由 runtime context 提供。

# Generation Rules
- 輸入資料已完成衝突辨識與衝突再審查。
- 不重新分類、不新增衝突、不移除衝突。
- label、type、description 視為定案內容。
- type 只作為策略候選方向；實際解法必須根據需求內容與衝突描述決定。
- 若 type 是 other，不要硬套特定衝突類型；請根據需求內容與衝突描述產生可行解法。
- 若本任務沒有提供 resolution strategy guidance，代表此 Conflict 無對應類型策略；請只根據需求內容與衝突描述產生解法。
- id 必須使用輸入 Conflict 項目的 id，不可自行產生 CONF-* 或 CR-*。
- 需求 id 與 text 只作為判斷依據，不可改寫。
- 輸出只包含下方 JSON 欄位。

# Output JSON
{
  "conflict_resolution": {
    "id": "Conflict 項目 id",
    "resolution_options": [
      {
        "option": "A",
        "strategy": "Resolution strategy name",
        "description": "處理方式",
        "pros": ["優點"],
        "cons": ["限制或代價"],
        "recommendation": true
      }
    ],
    "recommended_resolution": "建議採用的 resolution 與理由"
  }
}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 conflict report。
- 不輸出 Conflict/Neutral 重新分類結果。
- 不新增、改寫、刪除 URL 或 REQ。
- 不輸出 conflict_resolution 以外的 wrapper。"""
