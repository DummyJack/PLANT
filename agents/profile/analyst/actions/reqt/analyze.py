# Defines action prompts and output contracts.

from typing import Any

from ...rules import requirement_candidates_output_schema
from utils.template import render_template


def analyze_requirement(**context: Any) -> str:
    template = """# 任務
只根據目前這一條 source_text 抽取尚未記錄的新 User Requirements。

# Action Boundary
- action=analyze_requirement
- 本 action 只抽取 requirement_candidates。
- 不產生 REQ、不更新 scope、不更新 draft、不做衝突辨識。
- 不直接更新 artifact；runtime 會驗證後才合併到 artifact.URL。

# Context Rules
- source_text 是唯一可新增候選需求的直接來源。
- stakeholder 只用於理解說話者角色與來源追蹤。
- existing_requirements 只用於去重，不可改寫既有需求。
- 完整 all_text 只作為理解語境的背景，不可從其他 all_text 條目產生需求。

# Input
- source_text、stakeholder、existing_requirements 與 all_text 由 runtime context 提供。

# Generation Rules
{extraction_rules}

- 若 source_text 同時包含目標與細節，輸出的 text 只保留粗粒度 stakeholder goal、need 或 constraint。
- 同一個利害關係人目標下的操作步驟、欄位、狀態、通知、例外、驗收條件或量化門檻要合併到同一筆 User Requirement，不要拆成多筆。
- 每筆 User Requirement 應代表一個可討論的使用者目標、需求、限制或責任邊界，而不是單一 UI 元件、單一規則細節或單一步驟。

- 若 source_text 只是重述、同義改寫或細化目前已有候選需求，且沒有形成新的 stakeholder goal、need、constraint 或責任邊界，回傳空陣列。
- 若 source_text 只補充條件、例外、處理方式、驗收方式、SOP 或量化門檻，不新增 User Requirement；這些細節留到後續需求正式化階段。
- requirement_candidates 每筆只包含 text；不要輸出 priority、acceptance criteria、REQ 欄位、scope 或 reason。

# Output JSON
{requirement_candidates_output_schema()}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 REQ、scope_updates、draft_plan 或 conflicts。
- 不輸出 artifact 全文。
- 不輸出舊格式，例如最外層直接使用陣列。
- 不從其他 all_text 條目單獨創造需求。"""
    return render_template(
        template,
        {
            **context,
            "requirement_candidates_output_schema": requirement_candidates_output_schema,
        },
    )
