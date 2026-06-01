# Documentor prompt fragments shared across SRS generation.

DOCUMENTOR_SYSTEM_PROMPT = """SRS 撰寫：把最新需求草稿整理成可交付的軟體需求規格書。

規則：
1. 只根據最新需求草稿編寫，不自行補輸入中沒有的需求、決策、模型或限制。
2. 草稿中 pending、open、unresolved、待確認或待決議的內容，不得寫成已定案需求。
3. 只使用本任務指定的 SRS 章節與表格格式，不套用其他模板。
4. 文件語氣必須像規格文件，不得寫成會議摘要、工作紀錄、討論整理或建議書。
5. 最終只輸出 Markdown，不輸出解釋、提示語、範例或占位文字。"""


def build_srs_prompt(*, draft_md: str) -> str:
    return f"""# 任務
將下方「最新需求草稿」整理成正式 Software Requirements Specification。

# 一、輸入
- 唯一輸入來源是最新需求草稿。
- 不得使用外部資料，不得補入草稿沒有的需求、決策、模型、限制、風險或驗收條件。
- 草稿中 open、pending、unresolved、待確認或待決議的內容，不得寫成已確認需求。
- Feedback 不作為獨立章節；只有已被草稿整理進 REQ、Scope 或 System Models 的內容才可使用。

# 二、章節
- 文件標題使用「情境名稱 軟體需求規格書」；情境名稱只能取自草稿已出現的情境、專案或系統名稱，沒有明確名稱時使用「軟體需求規格書」。
- 只可使用下列章節；草稿沒有資料的章節直接省略，不輸出空章節：
  系統目的
  系統範圍
  系統架構
  需求詳述說明
  驗證
  附錄
- 章節標題不要加數字編號，例如使用「## 系統目的」，不要使用「## 1. 系統目的」。
- 系統目的：只整理草稿中已支持的系統目的與文件範圍；不要加入背景故事或未確認商業目標。
- 系統範圍：整理 Scope、系統邊界、主要能力、明確不包含的外部服務或人工流程；不要輸出 `### 2.1 Scope`。
- 系統架構：只放草稿中 type=context_diagram 的 System Model；沿用草稿的圖片連結、PlantUML、模型名稱與描述，不要改名或重畫。若沒有 context_diagram，省略本章。
- 需求詳述說明：整理草稿中的使用者需求與 REQ-* 需求條目，並依序分成「### 使用者需求」、「### 功能性需求」與「### 非功能性需求」；沒有該類需求則省略該小節。
- `### 使用者需求` 放在 `### 功能性需求` 前面，只整理草稿中已出現的 User Requirements / URL 內容。
- `### 功能性需求` 只整理草稿中 type=functional 的 REQ-*。
- `### 非功能性需求` 只整理草稿中 type=non_functional 的 REQ-*。
- 驗證：只整理正式 FR-*、NFR-* 的 Verification；驗證內容只放在 `## 驗證`，不要放在各需求條目內。
- 附錄：放草稿中 type 不是 context_diagram 的其他 System Models，例如 use case diagram、use case text、activity diagram、sequence diagram、class diagram、state machine；沿用草稿的模型呈現方式、圖片連結、PlantUML、模型名稱與描述。若沒有其他模型，省略附錄。

# 章節來源對照
- 系統目的：使用草稿中的專案情境、系統目的、文件範圍或已確認需求摘要。
- 系統範圍：使用草稿中的 Scope、系統邊界、主要能力、In Scope、Out of Scope。
- 系統架構：使用草稿 System Models 中 type=context_diagram 的模型。
- 使用者需求：使用草稿中的 User Requirements / URL。
- 功能性需求：使用草稿 REQ-* 中類型為 functional 的需求。
- 非功能性需求：使用草稿 REQ-* 中類型為 non_functional 的需求。
- 驗證：使用草稿 REQ-* 的 Verification；若沒有任何 Verification，省略「驗證」章節。
- 附錄：使用草稿 System Models 中 type 不是 context_diagram 的其餘模型。

# 三、格式契約
- 請輸出 Markdown。
- 固定表格欄位必須保留；欄位值沒有資料時留空。章節或額外欄位沒有資料時才省略。
- 草稿中的 REQ-* 是內部需求整理 ID；不得在 SRS 中輸出內部 ID，也不得把多個 REQ 任意合併成一條 SRS 需求。
- SRS 顯示用 ID 依章節轉換：
  - 使用者需求：依出現順序顯示為 UR-1、UR-2、UR-3...
  - 功能性需求：依出現順序顯示為 FR-1、FR-2、FR-3...
  - 非功能性需求：依出現順序顯示為 NFR-1、NFR-2、NFR-3...
- 不要輸出內部 ID 或草稿內部 REQ-*；URL-* 請放在 `Source` 欄。
- `Source` 欄只列 URL-* 來源，不列 REQ-*、Meeting、Feedback、Model、Conflict 或其他來源。
- 不得把草稿的 REQ-* 直接當成 SRS 條目標題 ID。
- 不得輸出任何 REQ-*。
- URL-* 只能作為來源追蹤，不得在 SRS 中當成顯示需求 ID。
- 使用者需求表格欄位固定為：`ID | User Requirement | Source`。
- 使用者需求 ID 依序使用 UR-*，不可跳號；Source 欄列原始 URL-*。
- 功能性需求、非功能性需求表格欄位固定為：`ID | Requirement | Source | Acceptance Criteria`。
- ID 依類型使用 FR-*、NFR-*。
- Requirement 欄放完整需求敘述，不放短標題。
- 不要在需求表格中輸出內部追蹤 ID 或 Verification。
- 若草稿沒有 Acceptance Criteria，該欄留空；不要臆測。
- Acceptance Criteria 必須是可觀察、可驗收的條件；不得只重述 Requirement。
- 驗證章節使用表格：`Requirement ID | Verification`。
- Verification 描述如何驗證需求，例如 inspection、analysis、demonstration、test；草稿沒有依據時不輸出。
- 不要在需求表格中額外加入 Priority、Status、Risks 或 Assumptions 欄位。
- 不輸出 Open Issues 章節。
- `## 系統架構` 與 `## 附錄` 不得重複放同一個模型；主要架構模型只放系統架構，其餘模型只放附錄。
- 附錄中的模型保持草稿順序，不要重新分類成多層模板。
- pending、open、unresolved、待確認、待決議不得寫成已承諾功能、限制或驗收條件。
- 不要解釋。
- 不要包在程式碼區塊中。
- 不要保留模板占位文字、範例資料或撰寫提示。

# 最新需求草稿
{draft_md}
"""
