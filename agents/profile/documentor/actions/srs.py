# Defines module workflow behavior.


def generate_srs(*, draft_md: str) -> str:
    return f"""# 任務
將下方「最新需求草稿」轉成正式軟體需求規格書。

# Action Boundary
- action=documentor.generate_srs
- 本 action 將最新需求草稿轉成正式 Markdown SRS。
- SRS 只做呈現轉換、章節整理與需求格式化。
- runtime 只會做 Markdown 清理、連結修正、圖片路徑修正與 Design Rationale link insertion。

# Source Boundary
- 唯一輸入來源是最新需求草稿。
- 只做呈現轉換與章節整理；不得改變需求語意、重新判斷、合併、拆分或補充需求。
- 不得使用外部資料，也不得補入草稿沒有的需求、限制、模型、驗收條件、決策或追蹤關係。
- 草稿中 open、pending、unresolved、待確認或待決議的內容，不得寫成已確認需求。
- Feedback 不作為 SRS 章節；只有已整理進 Scope、System Requirement 或系統模型的內容才可使用。

# Output Format
- 請輸出 Markdown。
- 不輸出 JSON。
- 不要包在程式碼區塊中。
- 不要解釋。

# Document Structure
沒有資料的章節直接省略，不輸出空標題。
- H1：`# 情境名稱 軟體需求規格書`；沒有情境名稱時用 `# 軟體需求規格書`。
- 二級章節順序：`## 系統目的`、`## 系統範圍`、`## 系統情境`、`## 系統限制`、`## 需求`、`## 附錄`。
- `## 需求` 下只放 `### 功能性需求` 與 `### 非功能性需求`。
- 功能性需求格式：`#### FR-1: title`，下一行直接輸出 `**Description**: 完整需求敘述`、`**Priority**:`、`**Acceptance Criteria**:`；Description 冒號後直接接文字，不要換行。
- 非功能性需求格式：`#### NFR-1: title`，下一行直接輸出 `**Description**: 完整需求敘述`、`**Category**:`、`**Metric**:`、`**Validation**:`；Description 冒號後直接接文字，不要換行。
- `## 附錄` 下只放 `### A. 系統模型`。
- 章節標題不要加數字編號，不要輸出 placeholder。

# Section Content Rules
- 文件標題：只使用草稿標題中明確的情境或專案名稱；沒有就使用「軟體需求規格書」。
- 系統目的：只用一段自然文字說明「為什麼要開發這個系統」；只根據草稿中已確認的 stakeholder pain points、Scope、User Requirements 或 System Requirement 高層目標濃縮，聚焦要解決的主要問題、服務的主要對象、核心價值或要降低的風險，不新增草稿沒有的目標。
- 系統目的不得使用條列、不得分成多段、不得改寫成系統功能介紹；不要列出功能、模組、流程步驟或技術架構。
- 系統目的必須避免「本系統提供...功能」、「本系統包含...模組」、「使用者可以...」這類功能清單式寫法；應寫成類似「本系統的目的在於建立一個...，協助...，並降低...風險。」的一段 why statement。
- 系統範圍：只根據草稿 Scope 章節產生，直接輸出條列項目；不要輸出 `In Scope`、`Out of Scope` 或其他範圍小標題。
- 系統情境：只放草稿 System Models 中 type=context_diagram 的模型；不要輸出模型小標題或 `SM-*` 標題；在 `## 系統情境` 後直接先輸出 Markdown 圖片，再輸出一段簡短模型說明文字；說明只回答「這張圖用來釐清什麼」，不要輸出 `**用途**`、`**反映需求**`、`**讀圖重點**`、`**限制**` 等小標題；圖片必須用 Markdown 圖片語法 `![模型名稱](./models/檔名.png)`，不要寫成「圖片：路徑」文字；不輸出「支援需求」。
- 系統限制：只放草稿 System Requirement 中 type=constraint 的 REQ；使用 1. 2. 3. 編號清單列出完整限制敘述，不顯示 REQ-* 或 CON-*。
- 需求：只放草稿 System Requirement 中 type=functional 與 type=non-functional 的 REQ，分成「### 功能性需求」與「### 非功能性需求」。
- 附錄 A：只放草稿 System Models 中 type 不是 context_diagram 的其餘模型，保持草稿順序；每個模型標題只顯示模型名稱，不得包含 SM-*，格式為 `#### 模型名稱`；模型標題後先輸出 Markdown 圖片，圖片必須用 Markdown 圖片語法 `![模型名稱](./models/檔名.png)`，不要寫成「圖片：路徑」文字。
- 附錄 A 中每個模型圖片下方都輸出兩段模型說明文字：第一段說明這張圖用來釐清什麼，第二段說明它支撐哪些需求面向或 REQ/FR；兩段之間必須空一行；不要輸出 Actor 分組、Use Case 表格、`**用途**`、`**反映需求**`、`**讀圖重點**`、`**支撐需求**` 或 `**限制**` 等小標題。
- 不輸出需求追蹤表；SRS 的 FR/NFR 標題與系統限制條目會由 runtime 加上 Design Rationale 連結。

# Requirement Conversion Rules
- 每一筆草稿 REQ-* 必須對應到一筆 SRS 需求或一條系統限制；不得任意合併或拆分。
- 若草稿有 N 筆 REQ-*，SRS 必須完整轉出 N 筆：functional 放入功能性需求，non-functional 放入非功能性需求，constraint 放入系統限制；不得因內容相似而省略、合併或只摘要。
- 若草稿 System Requirement 條目含 `SRS ID: FR-*`、`SRS ID: NFR-*` 或 `SRS ID: CON-*`，必須使用該既有 SRS ID；不得自行重新編號。
- 若草稿缺少 SRS ID，functional 才依出現順序顯示為 FR-1、FR-2、FR-3...
- 若草稿缺少 SRS ID，non-functional 才依出現順序顯示為 NFR-1、NFR-2、NFR-3...
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
- 每筆需求使用清楚欄位格式：需求標題後接 `**Description**: 完整需求敘述`，Description 不得換行到下一段；`Priority`、`Category`、`Metric`、`Validation`、`Acceptance Criteria` 各自獨立成段；`**Acceptance Criteria**:` 後接 1. 2. 編號清單。
- 需求正文不得輸出 REQ-*、URL-*、Source、Status、Risks、Assumptions 或 Rationale。

# Design Rationale Link Rules
- 不要自行產生 Design Rationale 連結；runtime 會讓每筆 FR-* / NFR-* 標題可點，並讓系統限制條目依序連到 CON-*。
- Design Rationale 連結由 runtime 保持原文字顏色，不使用預設藍色超連結樣式。
- 不要輸出需求追蹤表。

# Forbidden Output
- 不輸出「使用者需求」章節、Feedback 章節、Open Questions 章節、Open Issues 章節、空章節、測試資料或占位文字。
- 舊格式不相容：不得用 REQ-* 作為 SRS 需求標題，不得輸出非粗體 `Description:` 欄位，不得連到 `design_rationale.md`。
- 不輸出 UR-*；CON-* 不可出現在正文系統限制內容；URL-* 不可出現在正文需求內容。
- 不輸出需求追蹤表；不得輸出 `### B. 需求追蹤表`、`Traceability` 或 `REQ ID | Requirement | Source` 表格。
- `## 系統情境` 與 `## 附錄` 不得重複放同一個模型；context_diagram 只放系統情境，其餘模型只放附錄。
- 附錄中的模型保持草稿順序，不要重新分類成多層模板。
- pending、open、unresolved、待確認、待決議不得寫成已承諾功能、限制或驗收條件。
- 若沒有 context_diagram，不輸出「## 系統情境」。
- 若沒有 constraint，不輸出「## 系統限制」。
- 若沒有 functional 與 non-functional 需求，不輸出「## 需求」。
- 若只有 functional 或只有 non-functional，只輸出有資料的需求子章節。
- 若沒有非 context_diagram 模型，不輸出「## 附錄」。

# Input
{draft_md}
"""
