# Defines action prompts and output contracts.

def update_report() -> str:
    return """# 任務
根據上一版與最新需求衝突資料修訂需求衝突 Markdown 報告。

# Action Boundary
- action=update_conflict_report
- 本 action 只輸出修訂後的需求衝突 Markdown 報告。
- 不重新分類 Conflict/Neutral。
- 不新增、移除或改寫最新衝突資料以外的項目。
- 不更新 URL、REQ、scope、draft 或 artifact。

# Input
- previous_report 與最新需求衝突資料由 runtime context 提供。

# Generation Rules
- 每筆最新衝突都要列入報告。
- 保留上一版仍有效內容，移除與最新衝突資料不一致的內容。
- 只渲染輸入資料，不重新分類、不新增或移除項目。
- 衝突描述、解決選項與建議解法視為已定案內容，不可改寫。
- 報告 H1 標題固定使用「需求衝突報告」。
- 每筆衝突使用 id 作為顯示編號；不要輸出 Source 欄位。
- 不要輸出 Label 欄位，也不要輸出 Type 欄位；label/type 只供內部判斷，不放進 Markdown 報告。
- 解決選項每個選項必須用 Markdown bullet 獨立成行，例如「- 選項 A：處理方式」；不要把多個選項寫在同一段。
- 解決選項只顯示「選項 A：處理方式」；不要顯示 strategy、策略名稱或方法分類。
- 建議解法不要顯示 strategy、策略名稱或方法分類；若輸入含策略名稱，改以「建議採用選項 A」或具體處理方式描述。
- 涉及需求必須完整列出每個需求 ID 與需求內容；多需求也要逐筆列出，不省略、不留下空白段落。
- 不要產生 Executive Summary。
- 不要產生整體 recommendations 區塊。

# Output Format
- 請輸出 Markdown。
- 不輸出 JSON。
- 不要包在程式碼區塊中。

# 需求衝突報告

## 衝突ID：衝突標題或簡短描述

### 涉及需求
- URL-1：需求內容
- URL-2：需求內容

### 衝突描述
使用輸入中的定案描述，不重新分析。

### 解決選項
- 選項 A：選項內容。

### 建議解法
使用輸入中的 recommended_resolution。

# Forbidden Output
- 不輸出 JSON。
- 不輸出 artifact 全文。
- 不輸出最新衝突資料不存在的衝突、需求或解決方案。
- 不保留已和最新資料不一致的上一版內容。
- 不重新分析或改寫已定案內容。"""
