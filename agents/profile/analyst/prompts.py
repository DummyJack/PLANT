# Analyst prompt fragments shared across requirement analysis, issues, and conflicts.
import re

from agents.profile.elicitation_prompt import (
    COMMON_ELICITATION_CONTEXT_RULES,
    elicitation_action_rules,
    elicitation_action_task,
)


ANALYST_SYSTEM_PROMPT = """需求分析：把 stakeholder 訊號、會議討論與決策整理成可落地、可驗證、可追蹤的需求規格。

規則：
1. 主動辨識需求缺口、歧義、衝突、驗收條件不足與來源追蹤不足，並保留不確定性。
2. 僅整理 scope 內需求；超出範圍、證據不足或尚未確認者，保留為 open question 或 assumption。
3. 可修正文句、結構與欄位，使需求更清楚、可驗證、可測試、可追蹤，但不得改變需求實質語意。
4. 發現資料結構、狀態轉移、互動流程、法規或外部義務疑慮時，只整理為需求風險、限制或 open question，不自行定案。
5. 不自行解除 trade-off、裁定有爭議衝突、擴張 scope 或刪除有爭議需求。
6. 需求變更必須透過對應 action 更新 URL 或 REQ，不產生獨立變更帳。

核心輸出：
- requirement text：清楚描述誰在什麼情境下需要什麼能力或結果。
- acceptance criteria：可觀察、可驗收，不能只重述需求。
- 來源追蹤：保留利害關係人、討論、決策或衝突來源。
- open question：只在缺少可寫入需求的關鍵資訊時提出。"""


def markdown_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^|\n)({re.escape(heading)}\n.*?)(?=\n### |\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content or "")
    return match.group(2).strip() if match else ""


def markdown_between(content: str, start: str, end: str) -> str:
    source = content or ""
    start_index = source.find(start)
    if start_index < 0:
        return ""
    end_index = source.find(end, start_index + len(start))
    if end_index < 0:
        end_index = len(source)
    return source[start_index:end_index].strip()


def markdown_from_heading_until(content: str, starts: list[str], stops: list[str]) -> str:
    source = content or ""
    start_index = -1
    for heading in starts:
        found = source.find(heading)
        if found >= 0 and (start_index < 0 or found < start_index):
            start_index = found
    if start_index < 0:
        return ""
    end_index = len(source)
    for marker in stops:
        found = source.find(marker, start_index + 1)
        if found >= 0 and found < end_index:
            end_index = found
    return source[start_index:end_index].strip()


def requirements_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    if mode_name == "analysis":
        skill_guidance = markdown_between(
            content,
            "**Universal User Story Format:**",
            "Acceptance Criteria:",
        )
        if skill_guidance and not skill_guidance.rstrip().endswith("```"):
            skill_guidance = skill_guidance.rstrip() + "\n```"
        override = """# 本專案抽取限制
- 只抽取粗粒度 User Requirement：stakeholder goal、need、constraint 或 responsibility boundary。
- 不輸出 UI 欄位、單一步驟、acceptance criteria、metrics、priority、validation、risks 或 assumptions。
- 只根據目前 source_text；不要推論未明說功能。
- measurable/testable 細節留到 refine_requirement。"""
        return "\n\n".join(section for section in (skill_guidance, override) if section)

    if mode_name in {"system_requirement", "refine_requirement"}:
        category_guidance = markdown_between(
            content,
            "### 1. Requirement Decomposition",
            "### 2. Requirement Analysis Framework",
        )
        analysis_framework_guidance = markdown_between(
            content,
            "### 2. Requirement Analysis Framework",
            "### 3. Priority Frameworks",
        )
        priority_guidance = markdown_between(
            content,
            "### 3. Priority Frameworks",
            "**Kano Model:**",
        )
        quality_guidance = markdown_section(content, "### 4. Requirement Quality Criteria")
        validation_guidance = markdown_section(content, "### 5. Requirement Validation")
        selected = [
            category_guidance,
            analysis_framework_guidance,
            priority_guidance,
            quality_guidance,
            validation_guidance,
        ]
        guidance = "\n\n".join(section.strip() for section in selected if section.strip())
        override = """# 本專案覆寫規則
- type 分類依 requirements-analyst skill；不要在本 prompt 重新定義 functional / non-functional / constraint。
- feedback.constraints 是 Expert 的限制候選與證據，不等於正式需求；只有來源可追蹤且可寫成系統必須遵守的限制時，才正式化為 type=constraint。
- 明確外部限制、法規、政策、資料保存/刪除、第三方或技術限制用 constraint；品質、安全、隱私、稽核、可靠性或可用性要求用 non-functional；不確定時寫入 risks、assumptions 或 open_questions。
- title 是 brief description，只寫需求核心短語；不要把 stakeholder 名稱寫進 title，除非該角色就是需求概念不可分割的一部分。
- priority 依 requirements-analyst skill 判斷，但本專案只使用 must、should、could；沒有足夠依據就省略，不輸出 wont，也不要預設。
- description 必須是單一正式需求敘述；每筆 REQ 只保留一個核心意圖（功能、品質、限制三者擇一），不得同時承載可獨立驗收的「做什麼」與「要達到多少」或「不得違反什麼」。
- 若同一筆來源同時包含功能、品質與/或限制語意且各自可獨立追蹤，請拆成多筆 REQ；若不可獨立拆分，將次要語意移到 acceptance_criteria、risks 或 assumptions，不改變核心敘述。
- acceptance_criteria 必須可驗收；不要只重述 description。缺口寫入 risks、assumptions、open_questions 或 coverage，不硬補成已確認需求。
- non-functional 可輸出 category、metric、validation：category 依 ISO/IEC 25010 且不用 functional suitability；metric 從 acceptance_criteria 或需求內容萃取可觀察條件，不假造數字；validation 依 skill 的 Requirement Validation 寫成可執行方式。
- 每筆 REQ 只能表達一種主要性質：functional、non-functional 或 constraint。若來源同時包含系統能力、品質要求與限制，且各自可獨立驗收或追蹤，請拆成多筆 REQ；否則保留為同一筆 REQ 的 acceptance_criteria、risks 或 assumptions。
- source 只放可追蹤 ID，例如 URL-*、R*-M*、Feedback、SM-*；不要放 stakeholder 名稱、initial、document 或一般文字。
- rationale、risks、assumptions 不得重複 description。
- coverage 只作內部檢查，不是正式需求內容；Traceability 只維持 Source 與 System Model。"""
        return "\n\n".join(section for section in (guidance, override) if section)

    return ""


def url_extraction_rules() -> str:
    return """# 輸出
- 只輸出 JSON array。
- 每筆只包含 text。
- text 用中性需求描述，表達該利害關係人的目標、需求或限制。

# 規則
1. 只抽取輸入明確支持的需求。
2. 保持粗粒度；同一個利害關係人目標下的細節要合併。
3. 不要把按鈕、欄位、通知、狀態變化、例外、SOP 步驟或驗收細節拆成獨立需求。
4. 每筆 text 應能回答：哪個利害關係人在什麼目標或情境下，需要什麼能力、結果或限制。
5. 抽取時以 skill 的 User Story 三要素判斷需求是否成立：as_a、i_want、so_that。
6. 輸出時不要使用 User Story 欄位；請合併成一條中性的 User Requirement text。
7. 若輸入包含數值門檻、驗收條件、系統處理方式或技術限制，URL 只保留 stakeholder goal；細節留到 refine_requirement。
8. 不要產生系統規格、實作細節、量化指標、驗證方式、優先級、相依性、風險或假設。
9. 不使用第一人稱；不要輸出「我需要」「我希望」「我擔心」等發言語氣。請改寫為以利害關係人為主詞的中性需求描述。
10. 若輸入有利害關係人名稱，沿用原名稱。"""


def build_draft_prompt(*, mode: str, version_note: str, version: int = 0) -> str:
    mode = "update" if str(mode or "").strip() == "update" else "create"
    feedback_rule = """- 若輸入有 feedback.json 內容，draft 必須輸出獨立 Feedback 章節，整理對需求規格有用的領域發現、限制、風險與建議。
- Feedback 章節只整理 feedback.json 既有內容，不得新增研究結論、法規、限制、風險或建議。
- feedback.findings 整理為 Findings。
- feedback.constraints 整理為 Constraints。
- Feedback 的 Constraints 只是領域限制候選與證據，不是正式 System Requirement；正式限制只能來自 REQ type=constraint。
- feedback.risks 整理為 Risks。
- feedback.recommendations 整理為 Recommendations。
- 若某一類沒有資料，省略該子節；若 feedback.json 沒有可用內容，省略整個 Feedback 章節。
- 不得根據 feedback 新增 User Requirements 或 REQ-* 需求條目。
- Feedback 的 Findings、Constraints、Risks、Recommendations 只輸出整理後的文字內容，不要在每筆文字後面用括號附 source。
- 若 feedback.json 有 sources，或 feedback item 有 source，請在 Feedback 章節最後輸出 Sources 子節集中列出來源。
- Sources 只列來源名稱或 URL，不要放入分析文字；不顯示 Related 或 related_requirement_ids，詳細追蹤留在 feedback.json。"""
    mode_rule = """
create_draft 規則：
- 這是第一次建立草稿；只整理目前 artifact 中已存在的 scope、User Requirements、feedback、open questions 與 system models。
- 可使用 rough_idea 與 scenario 輔助文件標題，但不得用來產生新的 User Requirements、REQ-*、Feedback 或 Open Questions。
- create_draft 不處理 REQ-*；不得輸出 Requirements、System Requirement 或 Traceability。
""" if mode == "create" else """
draft update 規則：
- 這是 artifact 同步，不是自由重寫；請以上一版 previous_draft 的章節順序與標題為基底，同步最新輸入資料。
- 只根據最新範圍、User Requirements、REQ-* 需求條目、正式會議決議、開放問題、feedback 與系統模型更新對應章節。
- default_update_draft / general_update_draft 是正式會議後的整合點：必須完整反映最新 REQ、System Models、Traceability 與仍未解的 Open Questions。
- 每次 draft update 都要移除或修正 previous_draft 中已過時、已被覆蓋、已被刪除或已決議的內容；不要保留舊段落造成雙版本並存。
- draft update 不使用 rough_idea 或 scenario；若 previous_draft 與最新輸入資料衝突，以最新輸入資料為準。
- draft update 不使用原始 stakeholders；利害關係人資訊只以 URL / User Requirements 與 REQ-* 既有欄位為準。
- 若上一版內容已過期，必須修正或移到待確認區。
- 若 URL / User Requirements 已移除或不再包含某個 URL-*，新的草稿不得保留該 URL-*。
- 正式會議決議與 action 結果摘要只能用來更新已存在的 REQ-* 需求條目、Open Questions、System Requirement 中的 Risks/Assumptions 或已決議說明，不得從會議摘要直接創造沒有來源支持的新需求。
- 正式會議的決議與 action 結果摘要只能用來判斷哪些章節需要同步更新；不得替代對應輸入資料的最新內容。
- draft update 必須在文件最後輸出 Traceability，追蹤最新 REQ-*、來源與支援該需求的 System Model。
"""
    requirement_rules = """
- 若輸入已有 REQ-*，draft 必須輸出 System Requirement；若沒有 REQ-*，省略此章。
- REQ-* 需求條目是 System Requirement、Acceptance Criteria、Risks 與 Assumptions 的唯一來源；沒有 REQ-* 時省略這些章節。
- System Requirement 只列既有 REQ-* 需求條目；不得自行新增、刪除、合併、拆分或重新命名。
- draft update 不輸出 Requirements 總表。
- draft update 不是摘要任務；若輸入有 36 筆 REQ-*，System Requirement 就必須展開 36 筆，不得只列前幾筆。
""" if mode == "update" else """
- create_draft 不輸出 Requirements、System Requirement 或 Traceability。
- create_draft 不整理 REQ-*；REQ-* 只從 default_update_draft / general_update_draft 開始進入草稿。
"""
    traceability_rules = """
- Traceability 放在文件最後，逐筆列出既有 REQ-*、需求內容、來源與支援該需求的 System Model；欄位固定為 REQ ID、Requirement、Source、System Model。
- Traceability 的 Requirement 使用 REQ-* 既有 description 內容；Source 只使用 REQ-* 中已存在的 source；System Model 只使用 system_models 中 related_requirement_ids 包含該 REQ-* 的模型 id（SM-*）；不得自行補需求、來源或模型。
""" if mode == "update" else """
- create_draft 不輸出 Traceability；即使目前已有 REQ-*，也等 default_update_draft / general_update_draft 再建立需求追蹤表。
"""
    requirements_section = """
## System Requirement
### REQ-{{number}}: {{title}}
- Type: {{functional|non-functional|constraint}}
- Priority: {{若有資料才輸出}}
- Description: {{description}}
- Category: {{non-functional 且有資料才輸出}}
- Metric: {{non-functional 且有資料才輸出}}
- Validation: {{non-functional 且有資料才輸出}}
- Rationale: {{若有資料才輸出}}
- Source: {{source}}
- Acceptance Criteria:
  - {{criterion，若沒有資料省略整個 Acceptance Criteria 欄位}}
- Risks:
  - {{risk，若沒有資料省略}}
- Assumptions:
  - {{assumption，若沒有資料省略}}
""" if mode == "update" else ""
    traceability_section = """
## Traceability
| REQ ID | Requirement | Source | System Model |
|---|---|---|---|
""" if mode == "update" else ""
    return f"""請根據輸入資料產出 SRS-ready 需求草稿 Markdown，讓後續正式會議能審查 User Requirements、REQ-* 與 System Models。{version_note}
{mode_rule}
# 草稿整理原則
- draft 是工作草稿，不是正式 SRS；內部 ID 一律維持 URL-* 與 REQ-*。
- 不要在 draft 中轉成 FR-*、NFR-* 或 CON-*；這個轉換只由 Documentor 產生正式 SRS 時處理。
- 檢查 User Requirements 是否清楚與可驗證；若缺少量化指標或驗收邊界，只能在 System Requirement 的 assumptions、risks 或 Open Questions 中標示，不得自行補成已確認需求。
{requirement_rules}

# 草稿邊界
- 這是一份草稿，不是正式定版文件；只整理輸入資料內已有的需求、衝突、決議與開放問題。
- 本步驟不是需求抽取或需求分析；不得從 scenario、stakeholders、系統模型或 open questions 推導新的 User Requirements。
- URL 是 User Requirements 表的唯一來源。
- 正式會議決議、feedback、open questions 與系統模型只能同步各自對應章節或已決議說明；不得直接產生新的 User Requirements 或 REQ-* 需求條目，也不得直接寫入 System Requirement、Risks 或 Assumptions。
- User Requirements 表不得重新編號、合併、拆分或改寫 URL-*。

# 章節寫作依據
- 文件標題使用輸入中可辨識的系統名稱；create_draft 可參考 scenario 或 rough_idea，draft update 優先沿用 previous_draft 的標題，除非最新 scope 或 URL / User Requirements 明確支持修正。
- Scope 只整理已給定的範圍內與範圍外內容；In Scope 或 Out of Scope 若沒有資料，省略該子節，不要寫「目前無資料」。
- User Requirements 表要逐筆保留原始 User Requirements；不要合併、拆分、改寫、重新命名或重新排序需求 ID。
{traceability_rules}
- draft update 的 System Requirement 再逐筆展開既有 REQ-*；小節標題使用該項 id（REQ-*）；沒有 REQ-* 時不要輸出 System Requirement 標題或範例內容；不得用「其餘同上」、「略」、「依輸入資料內容」等方式省略。
- draft update 的每筆 System Requirement 以輸入資料為準；Type、Priority、Description、Source 有資料才輸出。non-functional 需求若有 Category、Metric、Validation 也要輸出；其他類型不要輸出這三個欄位。Rationale、Acceptance Criteria、Risks、Assumptions 也只有有資料時才輸出，不得輸出空欄位。
- Risks 與 Assumptions 不獨立成章；只放在對應的 System Requirement 裡。
{feedback_rule}
- Open Questions 使用輸入 open_questions 作為主要來源；它已依序整合 formal meeting resolution.open_questions / new_open_questions，再補 artifact.open_questions 中仍 open 的問題。
- previous_draft 既有 Open Questions 只作為補漏；若問題已在輸入 open_questions 出現、已回答、已進入 REQ、已納入 assumptions/risks，或不影響規格，不要保留。
- 只保留真正仍會影響需求、驗收、scope、模型或 SRS 的未解問題；已回答、已進入 REQ、已納入 assumptions/risks 或不影響規格的問題要移除。
- 不要把同一個已解決或重複問題重複列兩次；若來源重複，保留最完整的一筆。
- Open Questions 每筆必須保留或整理可追蹤來源；沒有可追蹤來源時不要列入。
- Open Questions 表格中的 Related Source 請使用對讀者有意義的來源名稱，例如 URL-*、REQ-*、Conflict CR-*、Meeting R*-M*、Feedback 或 Model SM-*；不要輸出 artifact 內部欄位名。
- 已決議、已正式化為 REQ-* 需求條目，或只是不影響 SRS 的一般研究建議，不要放入 Open Questions。
- Open Questions 沒有資料時省略整個 Open Questions 章節。
- System Models 章節要先依模型 type 分組；小節標題使用 display_type 的值。只輸出實際存在的 model type，不得輸出 placeholder 或空 model section。context_diagram 與 use_case_diagram 的小節標題只使用 display_type，不加「-- name」；其他 type 若只有一張模型，標題使用「display_type -- name」格式；若同一 type 有多張模型，display_type 作為小節標題，並使用 a.、b.、c. 依序列出「name」與模型內容，不要在 a.、b. 重複 display_type。有 image_path 就直接放圖；若沒有 image_path 但有 plantuml，改用 fenced code block 顯示 plantuml；若兩者都沒有，才不放模型圖內容。System Models 章節不要輸出「支援需求」或 related_requirement_ids；需求與模型對應只放在 Traceability。除 use_case_diagram 外，若模型有 description，放在模型圖下方，沒有 description 就不要自行補寫。Use Case Text 只整理 use case diagram 已附帶的文字用例；沒有 text/use_case_text 就省略 Use Case Text 表，不要從 PlantUML 反推出新需求。
- System Models 沒有資料時省略整個 System Models 章節。
- 衝突紀錄、Open Questions、正式會議決議與 action 結果摘要只能用來標示待確認或已決議說明，不得轉成新的User Requirements。

# 防止瞎編規則
- 草稿完整性來自輸入資料整理，不是來自自行補齊缺漏。
- 所有摘要型欄位只能濃縮與改寫已出現的內容，不得補入新需求、新限制、新功能或新角色。
- 不得為了讓草稿看起來完整而自行補功能、角色、流程、例外情境、法規、第三方服務、量化指標或驗收標準。
- 若資料不足，請省略該欄位或放入 Open Questions；不要猜測，也不要寫待補。
- 若某項內容只出現在 feedback、open questions 或系統模型，不得寫入 User Requirements 表。
- 若某項內容沒有出現在既有 REQ-* 需求條目中，不得寫入 System Requirement、Risks 或 Assumptions。
- 若 system model 圖或 use_case_text 出現 URL / User Requirements 未支持的元素，不得轉成需求。
- 若 NFR 缺少具體數值，請保留為待確認，不得自行補 TPS、延遲、可用性、RPO/RTO、安全標準或法規名稱。
- 不得輸出「其餘同上」、「略」、「依輸入資料內容」、「待補」或 JSON code block。

# 固定輸出格式
請輸出以下 Markdown 結構，不得重新命名主要章節；若主要章節沒有資料，依各章節規則省略。Scope 中的 In Scope / Out of Scope 子節沒有資料時請直接省略。System Requirement、Feedback、Open Questions、System Models 沒有資料時省略。
- 不得在文件標題後加入文件前言、版本聲明、用途說明、免責說明或流程說明；標題後請直接進入「## Scope」。

# {{系統名稱}}

## Scope
### In Scope
{{若 scope.in_scope 沒有資料，省略本子節。}}

### Out of Scope
{{若 scope.out_of_scope 沒有資料，省略本子節。}}

## User Requirements
| ID | Stakeholder | User Requirement | Source |
|---|---|---|---|

{requirements_section}

## Feedback
### Findings
- {{text}}

### Constraints
- {{text}}

### Risks
- {{text}}

### Recommendations
- {{text}}

### Sources
- {{source}}

## Open Questions
| ID | Question | Related Source |
|---|---|---|

## System Models
### 1. {{display_type}}
{{若 type 不是 context_diagram 或 use_case_diagram，且只有一張該 type 模型，標題才使用「display_type -- name」。}}

{{若該模型提供 image_path，直接使用 Markdown 圖片語法引用該圖片；若沒有 image_path 但提供 plantuml，請用 ```plantuml fenced code block 顯示；若兩者都沒有，略過模型圖內容，不要寫 Image 欄位。}}

{{System Models 章節不要輸出「支援需求」或 related_requirement_ids；需求與模型對應只放在 Traceability。}}

{{除 use_case_diagram 外，若該模型提供 description，請放在模型圖下方；若沒有 description，不要自行補寫。}}

若本 type 是 use_case_diagram 且包含 text/use_case_text，請接在同一 type 小節下。沒有 text/use_case_text 時，不要輸出 Use Case Text。Use Case Text 需依 actor 分組，每個 actor 一個小節；小節標題格式為「I. {{actor}} Use Cases」、「II. {{actor}} Use Cases」依序編號。

#### I. {{actor}} Use Cases
| 編號 | Use Case | 目的／說明 | 介面 |
|---|---|---|---|

### 2. {{next display_type}}
若同一 type 有多張模型，請在該 type 小節中使用：

a. {{模型名稱}}

{{圖片；若沒有圖片但有 plantuml，改放 PlantUML fenced code block}}

{{description，如果有}}

b. {{模型名稱}}

{{圖片；若沒有圖片但有 plantuml，改放 PlantUML fenced code block}}

{{description，如果有}}

其餘 type 依相同格式依序編號；不得把不同 type 合併成單一小節。

{traceability_section}

# 完整性要求
- 每個 URL-* 必須出現在「User Requirements」表。
- 不得出現輸入資料以外的 URL-*。
- 不得引用輸入中不存在的 image_path。
- 未決議內容只能在相關摘要中標示待確認，不得寫成已確認需求。"""


CONFLICT_ANALYSIS_HEADINGS = [
    "### Step 2: Systematic Conflict Detection",
    "## Common Pitfalls to Avoid",
]

CONFLICT_RESOLUTION_STRATEGIES = {
    "logical": ["Prioritization", "Conditional Logic", "Stakeholder Negotiation"],
    "technical": ["Technical Solution", "Decomposition", "Scope Adjustment"],
    "resource": ["Prioritization", "Sequencing", "Parallel Tracks"],
    "temporal": ["Sequencing", "Relaxation", "Scope Adjustment"],
    "data": ["Technical Solution", "Conditional Logic", "Decomposition"],
    "state": ["Decomposition", "Conditional Logic", "Technical Solution"],
    "priority": ["Stakeholder Negotiation", "Prioritization", "Compromise"],
    "scope": ["Scope Adjustment", "Prioritization", "Sequencing"],
}


def resolution_reference_guidance(content: str, conflict_type: str) -> str:
    conflict_type = str(conflict_type or "").strip().lower()
    if conflict_type == "other":
        return ""
    strategies = CONFLICT_RESOLUTION_STRATEGIES.get(conflict_type, [])
    if not strategies:
        return ""
    selected = [markdown_section(content, "## Resolution Framework")]
    for strategy in strategies:
        pattern = re.compile(
            rf"(^|\n)(### \d+\. {re.escape(strategy)}\n.*?)(?=\n### \d+\. |\n## |\Z)",
            re.DOTALL,
        )
        match = pattern.search(content or "")
        if match:
            selected.append(match.group(2).strip())
    return "\n\n".join(section for section in selected if section)


def conflict_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    base_mode, _, mode_detail = mode_name.partition(":")
    if base_mode == "report":
        report_guidance = markdown_from_heading_until(
            content,
            [
                "### Step 7: Create Conflict Report",
                "### Step 4: Create Conflict Report",
                "### Create Conflict Report",
            ],
            ["\n## Output Formats", "\n## Best Practices"],
        )
        return re.sub(
            r"\n## Recommendations\n.*?(?=\n```|\Z)",
            "",
            report_guidance,
            flags=re.DOTALL,
        ).replace(
            "### CONF-001: Connectivity Model",
            "### CR-1: Connectivity Model",
        ).strip()
    if base_mode == "resolution":
        resolution_guidance = markdown_from_heading_until(
            content,
            [
                "### Step 3: Recommend Resolution Strategies",
                "### Recommend Resolution Strategies",
            ],
            ["\n### Step 4:", "\n## Output Formats", "\n## Best Practices"],
        )
        resolution_guidance = re.sub(
            r"\n\d+\.\s+\*\*Implementation effort\*\*.*",
            "",
            resolution_guidance,
        )
        resolution_guidance = re.sub(
            r"\n- Effort:.*",
            "",
            resolution_guidance,
        )
        resolution_guidance = resolution_guidance.strip()
        if mode_detail == "other":
            return ""
        return resolution_guidance
    headings = CONFLICT_ANALYSIS_HEADINGS
    selected = [markdown_section(content, heading) for heading in headings]
    return "\n\n".join(section for section in selected if section)


def conflict_skill_subset(skill: dict, mode: str) -> dict:
    mode_name = str(mode or "").strip()
    base_mode, _, mode_detail = mode_name.partition(":")
    content = str(skill.get("content") or "")
    guidance = conflict_skill_guidance(content, mode_name)
    subset = dict(skill)
    subset["content"] = guidance if base_mode == "resolution" else (guidance or content)
    subset.pop("content_user", None)
    reference_files = skill.get("reference_files") or {}
    if base_mode == "report":
        keep = set()
    elif base_mode == "resolution":
        keep = {"resolution_strategies.md"}
    else:
        keep = {"conflict_patterns.md"}
    subset_refs = {}
    for name, value in reference_files.items():
        if name not in keep:
            continue
        if base_mode == "resolution" and name == "resolution_strategies.md":
            sliced = resolution_reference_guidance(value, mode_detail)
            if sliced:
                subset_refs[name] = sliced
            continue
        subset_refs[name] = value
    subset["reference_files"] = subset_refs
    return subset


ANALYST_ELICITATION_CONTEXT_RULES = f"""{COMMON_ELICITATION_CONTEXT_RULES}

# Analyst 角度
- 聚焦 User Requirement 是否能成立：使用者目標、使用價值、產出內容、成功標準與待確認缺口。
- 若需要提問，只提出最會影響需求文字、範圍或可驗證性的那一個問題。
- 若資訊足以支撐需求草稿，提出收束，不要為了角色分工硬問。"""


def analyst_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


def analyst_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明需求目標、使用情境、成功標準或待確認缺口的 stakeholder。
- 問題應直接補足最關鍵的需求判斷缺口；不要只問一般動機。
- 不要詢問領域法規、系統狀態建模或技術流程細節；這些分別交給 expert 或 modeler。"""
