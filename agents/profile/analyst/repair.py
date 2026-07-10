# Defines repair prompts for agent output.
import json
from typing import Any

from agents.profile.base import render_template


requirement_update_output_schema = """# Output JSON
{
  "requirement_update": {
    "REQ": [],
    "remove_REQ": [],
    "coverage": [],
    "reason": "一句說明"
  }
}"""

requirement_candidates_output_schema = """# Output JSON
{
  "requirement_candidates": [
    {"text": "候選 User Requirement"}
  ]
}"""

conflict_signoff_output_schema = """# Output JSON
{
  "conflict_signoff": {
    "decisions": [
      {"id": "衝突ID", "final_label": "Conflict 或 Neutral", "reason": "一句繁中裁定理由"}
    ]
  }
}"""

conflict_finalization_output_schema = """# Output JSON
{
  "conflict_finalization": {
    "reasons": [
      {"id": "PAIR-1", "title": "簡短衝突標題", "description": "最終裁定描述", "final_type": "scope"}
    ]
  }
}"""


repair_prompts: dict[str, tuple[bool, str]] = {
    "extract_repair": (
        True,
        """上一輪 elicitation extraction 輸出不是合法 requirement_candidates JSON object。請只修正格式，不要重新分析、不要新增需求。

{requirement_candidates_output_schema}

# Repair Rules
- 最外層必須只有 requirement_candidates。
- 每筆只包含 text。
- 不要輸出 priority、acceptance criteria、validation、metric、dependencies、risks 或 assumptions。
- 如果原始輸出沒有可抽取的新需求，輸出 []。
- 不要輸出 Markdown、程式碼區塊、前言或額外文字。

# 原始輸出
{str(raw_text or "")}""",
    ),
    "pair_repair": (
        True,
        """上一輪 {error_label} 輸出不是合法或完整的 pairwise JSON object。請根據原始輸出與指定 pairs 修正為完整格式。

# 必須輸出
{{"conflicts":[...]}}

# 欄位規則
- conflicts 必須是 array。
- conflicts 必須逐筆涵蓋所有指定 pairs；即使 final_label 是 Neutral 也必須輸出。
- 每筆必須包含 pair_index、final_label、reason。
- final_label 只能是 "Conflict" 或 "Neutral"。
- final_label 是 "Conflict" 時必須包含 title 與 final_type。
- title 必須是 4 到 30 字的名詞片語，描述衝突主題；不可只輸出 Conflict、衝突、需求衝突或 CR 編號。
- pair_index 只能來自指定 pairs。

# 指定 pairs
{json.dumps(pair_rows, ensure_ascii=False, indent=2)}

# 原始輸出
{str(raw or "")}""",
    ),
    "group_repair": (
        True,
        """上一輪整體 Conflict 分析輸出不是合法 JSON object。請修正為合法 JSON 格式。

# 必須輸出
{{"conflicts":[...]}}

# Repair Rules
- 原始輸出沒有明確 group conflict 時，輸出 {{"conflicts":[]}}。
- 每筆 Conflict 必須包含 title、final_label="Conflict" 與 requirement_ids。
- title 必須是 4 到 30 字的名詞片語，描述衝突主題；不可只輸出 Conflict、衝突、需求衝突或 CR 編號。
- requirement_ids 必須包含至少 2 個需求 id。
- related_pairs 可選；只有原始輸出有明確 pair 來源時才保留。
- 輸出只包含上述 JSON object。

# 原始輸出
{str(holistic_raw or "")}""",
    ),
    "signoff_repair": (
        True,
        """上一輪 conflict signoff 輸出不是合法 conflict_signoff JSON object。請只修正格式，不要重新裁定。

{conflict_signoff_output_schema}

# Repair Rules
- 最外層必須只有 conflict_signoff。
- 必須對 proposal_list 中每個 id 輸出一筆 decision。
- final_label 只能是 Conflict 或 Neutral。
- 輸出只包含上述 conflict_signoff JSON object。

# proposal_list
{json.dumps(proposal_list, ensure_ascii=False, indent=2)}

# 原始輸出
{raw}""",
    ),
    "reason_repair": (
        True,
        """上一輪 conflict final reason 輸出不是合法 conflict_finalization JSON object。請只修正格式，不要重新分析、不要新增項目。

{conflict_finalization_output_schema}

# Repair Rules
- 最外層必須只有 conflict_finalization。
- 必須只包含 decision_list 中存在的 id。
- 每筆必須包含 id 與 description。
- final_label 是 Conflict 時必須包含 title 與 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。
- title 必須是 4 到 30 字的名詞片語，描述衝突主題；不可只輸出 Conflict、衝突、需求衝突或 CR 編號。
- final_label 是 Neutral 時只輸出 id 與 description。
- 輸出只包含上述 conflict_finalization JSON object。

# decision_list
{json.dumps(decision_list, ensure_ascii=False, indent=2)}

# 原始輸出
{raw}""",
    ),
    "resolution_repair": (
        True,
        """上一輪 conflict resolution 輸出不是合法 conflict_resolution JSON object。請只修正格式，不要重新分析、不要新增解法。

# 必須輸出
{{
  "conflict_resolution": {{
    "id": "{conflict_id}",
    "resolution_options": [
      {{
        "option": "A",
        "strategy": "策略名稱",
        "description": "處理方式",
        "pros": ["優點"],
        "cons": ["限制或代價"],
        "recommendation": true
      }}
    ],
    "recommended_resolution": "建議採用的 resolution 與理由"
  }}
}}

# Repair Rules
- 最外層必須只有 conflict_resolution。
- id 必須等於 {conflict_id}。
- resolution_options 必須是非空 array。
- option 可用 A/B/C；若原始輸出使用 1/2/3，轉成 A/B/C。
- strategy、description、recommended_resolution 不可空白。
- pros 與 cons 必須是 array；沒有內容時可用 []。
- recommendation 必須是 boolean。
- 請只修正格式與欄位，不要新增原始輸出沒有支持的新方案。

# 原始輸出
{raw}""",
    ),
    "url_repair": (
        True,
        """上一個回覆不是合法 requirement_candidates JSON object。請只修正格式，不要重新分析、不要新增需求。

輸出必須是 JSON object，最外層只有 requirement_candidates，每筆只包含 text。

{requirement_candidates_output_schema}

原始回覆：
{raw}""",
    ),
    "coverage_repair": (
        True,
        """# 任務
修復 requirement action 輸出的 coverage 欄位。

# coverage 問題
{json.dumps(coverage_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 只修正 coverage。
- 最外層必須只有 requirement_update。
- coverage 每筆必須包含 source_id、status、covered_by、reason。
- status 只能是 covered、needs_clarification、assumption、risk、excluded。
- 不要把不合法 status 自動改成預設值；請根據原始輸出語意選擇正確 status。
- covered_by 只能放 REQ-* id；沒有對應 REQ 時使用空陣列。
- 保留 REQ、remove_REQ 與 reason 的既有語意。
- 若原始輸出包含 remove_REQ，必須原樣保留。
- 只輸出修復後 JSON。

{requirement_update_output_schema}""",
    ),
    "title_repair": (
        True,
        """# 任務
修復 requirement action 輸出的 REQ title，使其符合 title 規則。

# title 問題
{json.dumps(title_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 只修正 REQ[*].title。
- 最外層必須只有 requirement_update。
- title 是 brief description，只寫需求核心短語，不寫完整句。
- title 不要用 stakeholder 角色名稱作為前綴；角色資訊保留在 description、source 或 trace。
- 不得改變 description、type、priority、source、acceptance_criteria、rationale、dependencies、risks、assumptions、remove_REQ、coverage 或 reason 的語意。
- 保留原本 JSON 結構與所有欄位。
- 只輸出修復後 JSON。

{requirement_update_output_schema}""",
    ),
    "type_repair": (
        True,
        """# 任務
修復 requirement action 輸出的 mixed requirement。

# mixed requirement 問題
{json.dumps(mixed_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 每筆 REQ 只能表達一種主要性質：functional、non-functional 或 constraint。
- priority 只適用於 functional / non-functional；constraint 是限制或底線，不做 priority 取捨，若 constraint 有 priority 請移除。
- 最外層必須只有 requirement_update。
- 若同一筆 REQ 同時包含系統能力與品質要求，且兩者可獨立驗收或追蹤，請拆成 functional 與 non-functional。
- 若同一筆 REQ 同時包含系統能力與外部限制、法規、政策、資料保存/刪除、第三方或技術限制，請拆成 functional 與 constraint。
- 若品質要求只是該功能的驗收條件，且不能獨立追蹤，可保留在 acceptance_criteria，不必拆。
- 不要自動改成預設 type；請依本專案需求規則修正。
- 保留原本 source；拆分後的新 REQ 也要保留可追蹤 source。
- 若原始輸出包含 remove_REQ，必須原樣保留。
- update 模式中若修正既有 REQ，保留原 REQ id；拆出新需求時新項目不要填 id。
- 只輸出修復後 JSON。
- 每筆 REQ 只保留一個核心意圖；若能力、品質、限制意圖仍在同一筆中，請拆成多筆。
- 若多個來源使用相同名詞、資料物件或功能名稱，但系統責任、業務目的、觸發情境、受影響角色或完成邊界不同，應拆成不同 REQ；不得只因共同名詞而合併成泛化 description。
- 若多個來源描述的是相同系統責任、相同業務目的、相同主要角色與相同可驗收結果，即使措辭不同，也應合併或更新同一筆 REQ；不得因來源句數不同而機械式拆成多筆。
- description 應在來源支持範圍內盡可能具體完整；不得為了增加細節而加入來源未支持的功能、流程、資料欄位、角色、權限、例外處理或驗收條件。

{requirement_update_output_schema}""",
    ),
    "targeted_repair": (
        True,
        """# 任務
上一輪 mixed requirement 修復仍失敗。請只針對被點名的 REQ 做定點修復，輸出可直接寫回 requirements.json 的結果。

# 仍不合格的項目
{json.dumps(mixed_issues, ensure_ascii=False, indent=2)}

# 目前輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 定點修復規則
- 只修改「仍不合格的項目」中點名的 REQ；其他 REQ 必須原樣保留。
- 最外層必須只有 requirement_update。
- 被點名為 functional 但混入品質、穩定性或效能語意時，必須拆成：
  1. functional：只保留系統能力本體。
  2. non-functional：只保留品質、穩定性、可用性、可靠性、效能、SLA、錯誤率或高峰負載等要求。
- 被點名為 functional 但混入限制、法規或政策語意時，必須拆成：
  1. functional：只保留系統能力本體。
  2. constraint：只保留系統不能違反或必須遵守的限制。
- 被點名為 non-functional 但內容主要是系統能力時，請改成 functional；若同時有可獨立追蹤的品質要求，再另外拆出 non-functional。
- 拆出的新 REQ 不要填 id；由程式配置新 REQ-*。
- 修正既有 REQ 時保留原 id。
- id 只能是既有的 REQ-數字；不得輸出 REQ-文字、中文標題或自行編造的新 id。
- 每筆新/修正後的 REQ 都必須保留原本可追蹤 source。
- priority 只適用於 functional / non-functional；constraint 是限制或底線，不做 priority 取捨，若 constraint 有 priority 請移除。
- 若原始輸出包含 remove_REQ，必須原樣保留。
- description 必須只描述一種主要性質，不要用「並維持穩定」「且高效」「並符合法規」把不同性質重新串在一起。
- 若某個品質要求只是功能的 acceptance criteria，且不能獨立追蹤，才可留在 acceptance_criteria；否則必須拆出 non-functional。
- 若該筆仍同時出現兩種以上核心意圖（如能力+品質、能力+限制），請先拆分再輸出，不可以合併字句（「同時」「並且」「且」）硬塞在一筆中。
- 若多個來源使用相同名詞、資料物件或功能名稱，但系統責任、業務目的、觸發情境、受影響角色或完成邊界不同，應拆成不同 REQ；不得只因共同名詞而合併成泛化 description。
- 若多個來源描述的是相同系統責任、相同業務目的、相同主要角色與相同可驗收結果，即使措辭不同，也應合併或更新同一筆 REQ；不得因來源句數不同而機械式拆成多筆。
- description 應在來源支持範圍內盡可能具體完整；不得為了增加細節而加入來源未支持的功能、流程、資料欄位、角色、權限、例外處理或驗收條件。
- description 說明系統責任與完成結果；具體可測試條件、輸入輸出檢查、狀態驗證、錯誤處理驗收方式應放入 acceptance_criteria，不要全部塞進 description。
- 只輸出完整修復後 JSON；不要解釋。

{requirement_update_output_schema}""",
    ),
    "nfr_repair": (
        True,
        """# 任務
修復 requirement action 輸出的 non-functional 缺欄位問題。

# 非完整欄位問題
{json.dumps(nfr_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 只補齊被點名 REQ 的 non-functional 欄位：category、metric、validation。
- 最外層必須只有 requirement_update。
- 僅能使用輸入內容可支持的描述，禁止虛構數值與門檻。
- category 依 ISO/IEC 25010 取值（如 Performance / Reliability / Security / Usability / Maintainability），不使用 functional suitability。
- metric 以 acceptance_criteria 或 description / rationale 中可觀測條件為準；若只有描述字眼，保留可觀測語句，不用空字串。
- validation 用可執行驗證方式（測試、稽核、流程驗證），可直接回應「以 acceptance criteria 驗證」。
- 若原始輸出包含 remove_REQ，必須原樣保留。
- 不能確定時，保留既有欄位，不得新增不實內容。
- 只輸出修復後 JSON，不要說明。

{requirement_update_output_schema}""",
    ),
}


# ========
# Defines render repair prompt function for this module workflow.
# ========
def render_repair_prompt(key: str, **context: Any) -> str:
    is_f, template = repair_prompts[key]
    if not is_f:
        return template
    return render_template(
        template,
        {
            "json": json,
            "requirement_candidates_output_schema": requirement_candidates_output_schema,
            "requirement_update_output_schema": requirement_update_output_schema,
            "conflict_signoff_output_schema": conflict_signoff_output_schema,
            "conflict_finalization_output_schema": conflict_finalization_output_schema,
            **context,
        },
    )


# ========
# Defines requirement repair prompt function for this module workflow.
# ========
def requirement_repair_prompt(kind: str, **context: Any) -> str:
    return render_repair_prompt(kind, **context)
