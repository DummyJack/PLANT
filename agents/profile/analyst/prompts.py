# Analyst prompt fragments shared across requirement analysis, issues, and conflicts.
import re

from agents.profile.elicitation_prompt import (
    COMMON_ELICITATION_CONTEXT_RULES,
    elicitation_action_rules,
    elicitation_action_task,
)


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


def smart_user_requirement_guidance(content: str) -> str:
    smart_section = markdown_between(
        content,
        "**SMART Requirements:**",
        "**Completeness Checklist:**",
    )
    if not smart_section:
        return ""
    selected = []
    for label in ("Specific", "Relevant"):
        match = re.search(
            rf"({label}:\n(?:  - .+\n?)+)",
            smart_section,
            re.MULTILINE,
        )
        if match:
            selected.append(match.group(1).strip())
    if not selected:
        return ""
    return "**SMART Requirements:**\n```yaml\n" + "\n\n".join(selected) + "\n```"


def user_story_guidance(content: str) -> str:
    story_block = markdown_between(
        content,
        "**Universal User Story Format:**",
        "Acceptance Criteria:",
    ).strip()
    if not story_block:
        return ""
    if not story_block.endswith("```"):
        story_block = story_block.rstrip()
        if story_block.endswith("```yaml"):
            return story_block
        story_block += "\n```"
    return story_block


def requirements_skill_guidance(content: str, mode: str) -> str:
    mode_name = str(mode or "").strip()
    if mode_name == "analysis":
        selected = [
            user_story_guidance(content),
            markdown_section(content, "### 3. Priority Frameworks"),
            smart_user_requirement_guidance(content),
        ]
        return "\n\n".join(section for section in selected if section)

    headings_by_mode = {
        "draft": [
            "### Step 4: Documentation",
            "### 4. Requirement Quality Criteria",
        ],
    }
    sections = [
        markdown_section(content, heading)
        for heading in headings_by_mode.get(mode_name, [])
    ]
    selected = [section for section in sections if section]
    return "\n\n".join(selected)


def user_requirement_extraction_contract() -> str:
    return """# 輸出契約
- 只輸出 JSON array。
- 每筆只包含 text、priority。
- text 以利害關係人能做什麼或需要什麼來表達。
- text 不要寫成內部設計、技術實作或正式系統功能規格。
- priority 只能是 must、should 或 could；不收錄的項目不要輸出。
- 不要輸出其他欄位。

# 需求抽取規則
1. 只抽取原文明確支持的系統能力或限制；不要輸出情緒、期待、抱怨或抽象品質描述。
2. 若原文描述快速、方便、安全、穩定、信任、焦慮等感受，請改寫成具體系統行為，例如查詢、提示、通知、權限控管、狀態更新、異常處理或紀錄保存。
3. 不得自行補入原文沒有支持的 SLA、法規、責任歸屬、補償方式或技術實作。
4. 不得在 text 中把利害關係人改成「客戶、使用者、利害關係人」等泛稱；請沿用輸入中的利害關係人名稱。"""


def build_draft_prompt(*, is_revision: bool, version_note: str, version: int = 0) -> str:
    revision_rule = ""
    if is_revision:
        revision_rule = """
修訂規則：
- 這是文字層面的迭代修訂，不是從零重寫；請保留上一版草稿中仍有效的使用者需求、摘要與待確認內容。
- 依最新 user_requirements、conflict_report 與 meeting_record 更新；若上一版內容已過期，必須修正或移到待確認區。
- 若 user_requirements 已移除或不再包含某個 URL-*，新的草稿不得保留該 URL-*。
- 不得保留上一版中已被最新會議記錄或 user_requirements 推翻的內容。
"""

    return f"""請根據輸入資料產出需求草稿 Markdown，讓後續正式會議能審查使用者需求、系統範圍、領域限制與系統模型。{version_note}
{revision_rule}
# Skill 使用方式
- 使用 Documentation 原則，整理草稿文件、風險摘要、限制摘要與模型摘要。
- 使用 Requirement Quality Criteria 檢查使用者需求是否清楚與可驗證；若缺少量化指標或驗收邊界，只能在摘要中標示待確認，不得自行補成已確認需求。

# 草稿邊界
- 這是一份草稿，不是正式定版文件；只整理輸入資料內已有的需求、衝突、決議與開放問題。
- 本步驟不是需求抽取或需求分析；不得從 scenario、stakeholders、feedback、system_models、conflict_report 或 open_questions 推導新的 User Requirements。
- user_requirements 是 User Requirements 表的唯一來源。
- feedback、open_questions、system_models、conflict_report、meeting_record 只能產生摘要、風險、限制、模型覆蓋、待確認或已決議說明；不得直接產生新的 User Requirements。
- User Requirements 表不得重新編號、合併、拆分或改寫 URL-*。

# 角色使用規則
- 不得新增輸入 stakeholders 以外的角色。
- User Requirements 表中的 Stakeholder 必須使用輸入 user_requirements 的 stakeholder name，不得改名。

# 章節寫作依據
- 文件標題使用輸入中可辨識的系統名稱；優先採用情境名稱，若沒有明確名稱，請用初始想法或情境內容整理出中性的系統名稱，不要創造品牌名。
- 系統概述請寫成一段自然描述，主要依據 scenario 與 scope.in_scope 撰寫；若 scenario 不完整或過於簡略，可參考 rough_idea 補足系統背景，但不得超出 scope 與 user_requirements 支持的內容。只描述目前資料已支持的系統目標；不要列出利害關係人，也不要加入需求或範圍中沒有出現的新功能。
- 需求範圍只整理已給定的範圍內與範圍外內容；In Scope 或 Out of Scope 若沒有資料，省略該子節，不要寫「目前無資料」。
- 系統利害關係人只根據已選定的利害關係人撰寫；類別與名稱要沿用輸入。關注重點以該利害關係人的文字敘述為主，並可參考同名利害關係人的使用者需求；對系統的核心需求以同名利害關係人的使用者需求為主，並可參考其文字敘述。不得拿其他利害關係人的需求補入本列；資料不足時寫「待確認」。
- 使用者需求表要逐筆保留原始使用者需求；不要合併、拆分、改寫、重新命名或重新排序需求 ID。
- 領域研究與限制摘要只整理領域研究已提供的發現、來源、限制、風險、建議與未決事項；沒有資料的子節直接省略，不要寫「目前無資料」。建議要保持建議語氣，不要寫成系統必須做到的需求。每個項目若有 related_URL，請在句尾以「（來源：URL-1, URL-2）」標示；若 related_URL 為空但內容是整體專案層級，標示「（來源：整體專案）」。
- 系統模型章節要先依模型 type 分組；標題顯示使用 display_type，例如 use_case_diagram 顯示為 Use Case Diagram。只輸出實際存在的 model type，不得輸出 placeholder 或空 model section。context_diagram 與 use_case_diagram 的小節標題只使用 display_type，不加「-- name」；其他 type 若只有一張模型，標題使用「display_type -- name」格式；若同一 type 有多張模型，display_type 作為小節標題，並使用 a.、b.、c. 依序列出「name」與模型內容，不要在 a.、b. 重複 display_type。有 image_path 就直接放圖；若沒有 image_path 但有 plantuml，改用 fenced code block 顯示 plantuml；若兩者都沒有，才不放模型圖內容。除 use_case_diagram 外，若模型有 description，放在圖片或 PlantUML 下方，沒有 description 就不要自行補寫。Use Case Text 只整理 use case diagram 已附帶的文字用例；沒有 text/use_case_text 就省略 Use Case Text 表，不要從 PlantUML 反推出新需求。
- 衝突紀錄、開放問題與會議紀錄只能用來標示待確認或已決議說明，不得轉成新的使用者需求。

# 防止瞎編規則
- 草稿完整性來自輸入資料整理，不是來自自行補齊缺漏。
- 所有摘要型欄位只能濃縮與改寫已出現的內容，不得補入新需求、新限制、新功能或新角色。
- 不得為了讓草稿看起來完整而自行補功能、角色、流程、例外情境、法規、第三方服務、量化指標或驗收標準。
- 若資料不足，請明確寫「待確認」，不要猜測。
- 若某項內容只出現在 feedback、open_questions、system_models、conflict_report 或 meeting_record，不得寫入 User Requirements 表。
- 若 system model 圖或 use_case_text 出現 user_requirements 未支持的元素，不得轉成需求。
- 若 NFR 缺少具體數值，請保留為待確認，不得自行補 TPS、延遲、可用性、RPO/RTO、安全標準或法規名稱。

# 固定輸出格式
請輸出以下固定 Markdown 結構，不得刪除或重新命名主要章節；若主要章節沒有資料，保留章節與表頭，填入「目前無資料」或 "-"；但需求範圍中的 In Scope / Out of Scope 子節沒有資料時請直接省略。
- 不得在文件標題後加入文件前言、版本聲明、用途說明、免責說明或流程說明；標題後請直接進入「## 1. 系統概述」。

# {{系統名稱}}

## 1. 系統概述
{{請以一段文字描述系統目標。}}

## 2. 需求範圍
### In Scope
{{若 scope.in_scope 沒有資料，省略本子節。}}

### Out of Scope
{{若 scope.out_of_scope 沒有資料，省略本子節。}}

## 3. 系統利害關係人
| 類別 | 利害關係人 | 關注重點 | 對系統的核心需求 |
|---|---|---|---|

## 4. 使用者需求
| ID | 優先級 | 利害關係人 | 使用者需求 | 來源 |
|---|---|---|---|---|

## 5. 領域研究與限制摘要
### 1. Findings
{{若 feedback.findings 沒有資料，省略本子節。}}

### 2. Sources
{{若 feedback.sources 沒有資料，省略本子節。}}

### 3. Constraints
{{若 feedback.constraints 沒有資料，省略本子節。}}

### 4. Risks
{{若 feedback.risks 沒有資料，省略本子節。}}

### 5. Recommendations
{{若 feedback.recommendations 沒有資料，省略本子節。}}

### 6. Open Items
{{若 feedback.open_items 沒有資料，省略本子節。}}

## 6. 系統模型
### 1. {{display_type}}
{{若 type 不是 context_diagram 或 use_case_diagram，且只有一張該 type 模型，標題才使用「display_type -- name」。}}

{{若該模型提供 image_path，直接使用 Markdown 圖片語法引用該圖片；若沒有 image_path 但提供 plantuml，請用 ```plantuml fenced code block 顯示；若兩者都沒有，略過模型圖內容，不要寫 Image 欄位。}}

{{除 use_case_diagram 外，若該模型提供 description，請放在圖片或 PlantUML 下方；若沒有 description，不要自行補寫。}}

若本 type 是 use_case_diagram 且包含 text/use_case_text，請接在同一 type 小節下。沒有 text/use_case_text 時，不要輸出 Use Case Text。Use Case Text 需依 actor 分組，每個 actor 一個小節；小節標題格式為「I. {{actor}} Use Cases」、「II. {{actor}} Use Cases」依序編號。

#### I. {{actor}} Use Cases
| 編號 | Use Case | 目的／說明 | 介面 |
|---|---|---|---|

### 2. {{下一個 display_type}}
若同一 type 有多張模型，請在該 type 小節中使用：

a. {{模型名稱}}

{{圖片；若沒有圖片但有 plantuml，改放 PlantUML fenced code block}}

{{description，如果有}}

b. {{模型名稱}}

{{圖片；若沒有圖片但有 plantuml，改放 PlantUML fenced code block}}

{{description，如果有}}

其餘 type 依相同格式依序編號；不得把不同 type 合併成單一小節。

# 完整性要求
- 每個 URL-* 必須出現在「使用者需求」表。
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
            "## Conflicts",
            "## 衝突需求（Conflicting Requirements）",
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
- 聚焦 User Requirement 是否能成立：使用者目標、使用價值、產出內容、優先級、成功標準與待確認缺口。
- 問題應補足可寫成 User Requirement 的資訊；不要追問流程步驟、系統狀態或外部合規細節，除非它們會直接改變需求文字。
- 若本輪已有前面發言，請判斷前面問題是否已覆蓋需求分析關注點；若已覆蓋，提出更精準的下一層追問，或在資訊足夠時提出收束。
- 前半段請先補足需求主幹，不要過早進入細節審查。"""


def analyst_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


def analyst_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇能說明需求目標、使用情境、成功標準、優先級或待確認缺口的 stakeholder。
- 問題必須對準需求文字可落地的欄位，例如：需求目標、使用情境、輸入/輸出、成功標準、優先級或待確認缺口。
- 不要只問「為什麼需要」或一般動機；只有當答案會改變需求內容、優先級、成功標準或範圍時才問動機。
- 若 Mediator 本輪已安排其他 agent 補流程、例外、限制或風險，你的問題應避開那些角度，專注需求文字與需求判斷。"""
