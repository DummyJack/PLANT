# Documentor prompt fragments shared across SRS generation.

DOCUMENTOR_SYSTEM_PROMPT = """SRS 撰寫：把最新需求草稿整理成可交付的軟體需求規格書。

規則：
1. 只根據最新需求草稿編寫，不自行補輸入中沒有的需求、決策、模型或限制。
2. 草稿中 pending、open、unresolved、待確認或待決議的內容，不得寫成已定案需求。
3. 只使用本任務指定的 SRS 章節與欄位格式，不套用其他模板。
4. 文件語氣必須像規格文件，不得寫成會議摘要、工作紀錄、討論整理或建議書。
5. 最終只輸出 Markdown，不輸出解釋、提示語、範例或占位文字。"""


def build_srs_prompt(*, draft_md: str) -> str:
    return f"""# 任務
將下方「最新需求草稿」轉成正式 Software Requirements Specification。

# 輸入邊界
- 唯一輸入來源是最新需求草稿。
- 只做呈現轉換與章節整理；不得改變需求語意、重新判斷、合併、拆分或補充需求。
- 不得使用外部資料，也不得補入草稿沒有的需求、限制、模型、驗收條件、決策或追蹤關係。
- 草稿中 open、pending、unresolved、待確認或待決議的內容，不得寫成已確認需求。
- Feedback 不作為 SRS 章節；只有已整理進 Scope、System Requirement、系統模型 或 需求追蹤表 的內容才可使用。

# 目標章節
沒有資料的章節直接省略，不輸出空標題。
- H1：`# 情境名稱 軟體需求規格書`；沒有情境名稱時用 `# 軟體需求規格書`。
- 二級章節順序：`## 系統目的`、`## 系統範圍`、`## 系統架構`、`## 系統限制`、`## 需求`、`## 附錄`。
- `## 需求` 下只放 `### 功能性需求` 與 `### 非功能性需求`。
- 功能性需求格式：`#### FR-1: title`，下一行直接輸出 `**Description**:`、`**Priority**:`、`**Acceptance Criteria**:`。
- 非功能性需求格式：`#### NFR-1: title`，下一行直接輸出 `**Description**:`、`**Category**:`、`**Metric**:`、`**Validation**:`。
- `## 附錄` 下只放 `### A. 系統模型` 與 `### B. 需求追蹤表`。
- 章節標題不要加數字編號，不要輸出 placeholder。

# 章節來源
- 文件標題：使用草稿中明確的情境或專案名稱；沒有就使用「軟體需求規格書」。
- 系統目的：草稿中的專案情境、系統目的、文件範圍或已確認的高層需求摘要。
- 系統範圍：草稿中的 Scope、系統邊界、主要能力、In Scope、Out of Scope。
- 系統架構：只放草稿 System Models 中 type=context_diagram 的模型；沿用模型名稱、描述、圖片連結或 PlantUML，不輸出「支援需求」。
- 系統限制：只放草稿 REQ-* 中 type=constraint 的需求；使用 1. 2. 3. 編號清單列出完整限制敘述，不顯示 REQ-* 或 CON-*。
- 需求：只放草稿 REQ-* 中 type=functional 與 type=non-functional 的需求，分成「### 功能性需求」與「### 非功能性需求」。
- 附錄 A：放 type 不是 context_diagram 的其餘系統模型，保持草稿順序。
- 附錄 B：放草稿需求追蹤表，排在系統模型後面。

# 需求轉換
- 每一筆草稿 REQ-* 必須對應到一筆 SRS 需求或一條系統限制；不得任意合併或拆分。
- 若草稿有 N 筆 REQ-*，SRS 必須完整轉出 N 筆：functional 放入功能性需求，non-functional 放入非功能性需求，constraint 放入系統限制；不得因內容相似而省略、合併或只摘要。
- functional 依出現順序顯示為 FR-1、FR-2、FR-3...
- non-functional 依出現順序顯示為 NFR-1、NFR-2、NFR-3...
- constraint 只放在「## 系統限制」，不放入「## 需求」。
- 系統限制每一條使用 constraint REQ 的完整 Description；不得改寫成短摘要，不顯示 REQ-*、Priority、Source、Rationale、Risks 或 Assumptions。
- 功能性需求與非功能性需求不要使用表格；每筆需求使用四級標題。
- 每筆需求欄位使用粗體欄位名，不要用 `-` 條列符號。
- Functional 欄位順序：`**Description**:`、`**Priority**:`、`**Acceptance Criteria**:`。
- Non-functional 欄位順序：`**Description**:`、`**Category**:`、`**Metric**:`、`**Validation**:`。
- Non-functional 即使沒有 Category、Metric 或 Validation，也必須輸出 Description；Category、Metric、Validation 只有有資料才輸出。
- Non-functional 的 Category 來自 REQ.category，Metric 來自 REQ.metric，Validation 來自 REQ.validation；沒有資料的欄位直接省略。
- Description 放完整需求敘述，不放短標題。
- Acceptance Criteria 沒有資料時省略整個欄位；不得臆測，也不得只重述 Description。
- 每筆需求使用緊湊格式：需求標題後直接接 `**Description**:`，欄位之間不要空行；`**Acceptance Criteria**:` 後直接接 1. 2. 編號清單。
- 需求正文不得輸出 REQ-*、URL-*、Source、Status、Risks、Assumptions 或 Rationale。
- Traceability 保留草稿表格欄位 `REQ ID | Requirement | Source | System Model`；不得改成 FR/NFR ID，也不得加欄位。

# 輸出限制
- 請輸出 Markdown。
- 不輸出「使用者需求」章節、Open Issues 章節、空章節、範例資料或占位文字。
- 不輸出 UR-*、CON-*；REQ-* 與 URL-* 只可出現在附錄 Traceability，不可出現在正文需求內容。
- `## 系統架構` 與 `## 附錄` 不得重複放同一個模型；context_diagram 只放系統架構，其餘模型只放附錄。
- 附錄中的模型保持草稿順序，不要重新分類成多層模板。
- pending、open、unresolved、待確認、待決議不得寫成已承諾功能、限制或驗收條件。
- 若沒有 context_diagram，不輸出「## 系統架構」。
- 若沒有非 context_diagram 模型，也沒有 Traceability，不輸出「## 附錄」。
- 不要解釋。
- 不要包在程式碼區塊中。

# 最新需求草稿
{draft_md}
"""
