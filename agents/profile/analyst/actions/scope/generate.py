# Defines action prompts and output contracts.
from agents.profile.base import forbidden_output_rules


def generate_scope() -> str:
    return """# 任務
根據產品情境（scenario）與 URL / User Requirements，界定本專案初始需求範圍。

# Action Boundary
- action=generate_scope
- 本 action 根據 scenario 與 URL / User Requirements 產生初始 scope_definition JSON。
- scope_definition 只描述高層 in_scope / out_of_scope 專案邊界。
- runtime 會驗證後寫入 artifact.scope。

# Context Rules
- scenario 只作為產品邊界背景。
- URL / User Requirements 是 scope 的主要直接來源。
- current_scope 若存在，只作為避免重複與延續既有邊界，不可無來源擴張。
- scope_consideration / human_decision 若存在，代表使用者對初始需求範圍的審查考量；只能用來檢查遺漏、過寬、過窄或分類錯誤，不是直接採納指令。
- 審查考量需有 scenario 或 URL / User Requirements 支持，才可反映到 scope。
- scope_consideration / human_decision 是全局檢查角度，不代表整份 scope 都要朝該方向改寫；只修正被資料支持且確實受影響的範圍項目。
- 不要把同一條使用者建議逐項附加到每個 in_scope / out_of_scope，也不要為了呼應建議而重複新增相近範圍。

# Input
- scenario、URL / User Requirements、current_scope、scope_consideration 與 human_decision 由 runtime context 提供。

# Generation Rules
- 根據產品情境與 URL / User Requirements 判斷 scope。
- 使用者審查考量若缺少 scenario 或 URL 支持，保留為後續確認方向，不要寫入 scope。
- 若使用者建議只影響部分能力域、流程域、資料責任或外部介接邊界，只調整該部分；未受影響且仍被 URL 支持的既有 scope 應保留。
- Scope 是專案邊界，不是需求清單；詳細功能、驗收條件、限制與風險留給後續需求條目與草稿章節處理。
- 範圍內（in_scope）只放高層系統責任邊界，不放逐條 User Requirement；每項應代表一組能力域、流程域、資料責任或外部介接邊界。
- in_scope 建議 3 到 7 項；每項代表能力域、流程域、資料責任或外部介接邊界。
- 不要把情緒、抱怨、商業目標、抽象品質或研究建議直接放入範圍內。
- 範圍外（out_of_scope）只放資料明確排除，或明顯由第三方、線下流程、外部組織負責的內容。
- out_of_scope 建議 0 到 5 項；不要為了完整而自行補排除項。
- 沒有明確排除項時，out_of_scope 輸出空陣列。
- scope_definition.scope 只包含 in_scope 與 out_of_scope。
- reason、source、REQ、URL、coverage 不屬於本 action 輸出。

# Output JSON
{
  "scope_definition": {
    "scope": {
      "in_scope": [],
      "out_of_scope": []
    }
  }
}

""" + forbidden_output_rules(
        [
            "不輸出 requirement_candidates、REQ、draft_plan 或 conflicts。",
            "不輸出 scope_definition 以外的 wrapper。",
            "不把 URL-* 需求逐條改寫成 scope item。",
            "不新增未被 scenario 或 User Requirements 支持的範圍。",
        ]
    )
