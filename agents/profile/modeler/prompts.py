# Modeler prompt fragments shared across model generation and meeting responses.
import json
import re

from agents.profile.elicitation_prompt import (
    COMMON_ELICITATION_CONTEXT_RULES,
    elicitation_action_rules,
    elicitation_action_task,
)

from agents.profile.conflict_review import (
    CONFLICT_REVIEW_LABEL_RULES,
    CONFLICT_REVIEW_REASON_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
)


MODELER_SYSTEM_PROMPT = """需求建模：根據正式 REQ-*；若尚未產生 REQ，則根據 User Requirements（URL-*）與目前 scope 建立、更新和驗證 UML 系統模型，並指出模型與需求之間的不一致、缺口與影響範圍。

規則：
1. 若有 REQ-*，模型必須以 REQ-* 與目前 scope 為主；若沒有 REQ-*，才以 User Requirements（URL-*）為主。
2. 精煉既有模型時只修改受影響部分，保留未變動的 actor、use case、流程、資料、狀態與關係。
3. 發現不一致時只指出模型影響、需求缺口或需要正式討論的問題；不得直接改變需求語意。
4. 資訊不足時不要硬畫未確認元素，不可臆造 actor、流程、資料物件、class、state 或外部系統。
5. 不可從模型反推新增需求，也不可把 feedback 或研究建議畫成已確認模型元素。
6. context_diagram 在本專案對外視為「系統架構圖」，只呈現本系統、外部角色、外部系統、主要資料/事件流與責任邊界；不得畫成流程圖、use case 圖或內部模組設計圖。"""


def model_action_prompt(*, state: dict, last_observation: dict) -> str:
    state_text = json.dumps(state, ensure_ascii=False, indent=2)
    obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)
    return f"""# 任務
    根據當前狀態與上一步結果，選下一個動作。

    # 動作
    - plan_models：先判斷哪些模型需要建立或更新
    - create_model：{{"target": {{"type":"context_diagram/use_case_diagram/activity_diagram/sequence_diagram/state_machine/class_diagram", "name":"模型名稱"}}}}；建立新的模型
    - update_model：{{"target": {{"type":"...", "target_model_id":"既有模型 id", "name":"模型名稱"}}}}；更新既有模型
    - validate_model：{{"target": {{"type":"...", "target_model_id":"...", "name":"..."}}}}
    - fix_model：{{"target": {{"type":"...", "target_model_id":"...", "name":"..."}}}}
    - done：結束

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - 尚無模型或有需求/議題變更時，都先選 plan_models。
    - 模型是否需要建立或更新，以 plan_models 輸出的 model_targets 為準；不要自行新增未列入的模型。
    - 若 plan_models 判斷沒有需要建立或更新的模型，下一步選 done。
    - create_model 只用於 plan_models 指定 operation=create 的 target。
    - update_model 只用於 plan_models 指定 operation=update 的 target。
    - validate_model 只在 create_model 或 update_model 後使用。
    - fix_model 只在 validate_model 失敗或回報 PlantUML 語法錯誤後使用。
    - 同一 type 可以有多張模型；更新既有模型時使用 target_model_id，沒有 id 時才用 type + name。
    - context_diagram 只在系統邊界、外部角色、外部系統、主要資料/事件流或責任邊界改變時處理。
    - use_case_diagram 只在 actor 可執行能力或系統功能集合改變時處理。
    - activity_diagram 只在流程步驟、分支、例外、狀態切換或責任交接改變時處理。
    - sequence_diagram 只在多方互動順序、訊息往返或協作責任需要釐清時處理。
    - class_diagram 只在需求層級資料物件、概念關係或屬性責任改變時處理。
    - state_machine 只在某個業務物件的狀態與轉移規則明確需要呈現時處理。
    - use_case_text 由流程在 use_case_diagram 後自動產生；不要單獨選 use_case_text。
    - 需要補專案事實或驗證模型語法時，遵守本輪工具使用資料
    - 每個需處理的模型都走：create_model/update_model → validate_model →（若失敗）fix_model → validate_model
    - 所有受影響圖表處理完後選 done
    - reasoning 請使用一句繁體中文簡述。

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}},
      "reasoning": "一句說明"
    }}"""


def model_impact_prompt(*, context: dict) -> str:
    ctx_text = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""分析需求輸入與現有模型，完成兩件事：(1) 判斷哪些模型需要更新或新建；(2) 產出與需求的一致性說明與缺口報告。

    # 輸入資料
    {ctx_text}

    # 輸出要求
    - model_targets：需處理的模型目標；同一 type 可有多張模型。
    - 每個 model target 都要輸出 related_requirement_ids，列出此圖預計支援或釐清的 REQ-*；若目前尚未產生 REQ，才可使用 URL-*。
    - operation 只能是 create 或 update。
    - type 限 context_diagram, use_case_diagram, activity_diagram, sequence_diagram, state_machine, class_diagram；use_case_text 會由流程附在 use_case_diagram.text。
    - update 必須盡量指定 target_model_id；若沒有 id，至少提供 type 與 name。
    - create 必須提供簡短、直觀、可區分同 type 其他模型的 name。
    - 若 context.requirement_source 是 REQ，請以 REQ-* 作為主要建模依據，URL-* 只作為來源追蹤背景。
    - 若 context.requirement_source 是 URL，代表尚未產生正式 REQ-*，才以 User Requirements（URL-*）作為主要建模依據。
    - 若既有模型已存在，這是帶有修訂脈絡的模型迭代；只標記受本次修訂脈絡或主要需求輸入影響的模型。
    - 既有模型的 source 只用於追蹤來源，不可改寫成新需求。
    - 未受影響的既有模型不得列入 model_targets。
    - feedback 只作為領域背景、限制、風險、建議與未決事項參考；不得轉成新的模型元素。
    - 未決、建議或研究性內容不可畫成已確認模型元素；只能影響模型邊界、限制註記或缺口說明。
    - context_diagram 在本專案就是系統架構圖；只有角色/外部系統/主要資料流/責任邊界變動時才列入，不得因一般功能、流程或驗收條件更新就重畫。
    - use_case_diagram 只處理 actor 與用例能力；activity_diagram 只處理流程；sequence_diagram 只處理互動順序；class_diagram 只處理需求層級資料概念；state_machine 只處理狀態生命週期。
    輸出 JSON:
    {{
    "model_targets": [
      {{
        "operation": "create | update",
        "type": "diagram type",
        "target_model_id": "既有模型 id，create 時留空",
        "name": "模型名稱",
        "related_requirement_ids": ["REQ-1"],
        "reason": "為何需要處理此模型"
      }}
    ],
    "impact_summary": "影響摘要",
    "consistency_summary": "與需求一致性的整體說明",
    "gaps": ["缺口或不一致項目1", "缺口或不一致項目2"]
    }}
    只輸出 JSON。"""

UML_DIAGRAM_HEADINGS = {
    "context_diagram": "## Context Diagram",
    "use_case_diagram": "## Use Case Diagram",
    "activity_diagram": "## Activity Diagram",
    "sequence_diagram": "## Sequence Diagram",
    "state_machine": "## State Machine",
    "class_diagram": "## Class Diagram",
}


def markdown_section(content: str, heading: str) -> str:
    pattern = re.compile(
        rf"(^|\n)({re.escape(heading)}\n.*?)(?=\n## |\Z)",
        re.DOTALL,
    )
    match = pattern.search(content or "")
    return match.group(2).strip() if match else ""


def uml_skill_guidance(content: str, mode: str, diagram_type: str = "") -> str:
    mode_name = str(mode or "").strip()
    diagram_name = str(diagram_type or "").strip()
    common = [
        markdown_section(content, "## Overview"),
        markdown_section(content, "## MANDATORY: Evidence-First Approach"),
    ]
    if mode_name == "selection":
        sections = common + [
            markdown_section(content, "### Requirement-Level Diagrams"),
            markdown_section(content, "### Diagram Selection Guide"),
        ]
    elif mode_name == "use_case_text":
        sections = common + [
            markdown_section(content, "## Use Case Diagram"),
        ]
    elif mode_name == "repair":
        sections = [
            markdown_section(content, UML_DIAGRAM_HEADINGS.get(diagram_name, "")),
        ]
    else:
        sections = common + [
            markdown_section(content, UML_DIAGRAM_HEADINGS.get(diagram_name, "")),
        ]
    return "\n\n".join(section for section in sections if section)


def uml_skill_subset(skill: dict, mode: str, diagram_type: str = "") -> dict:
    content = str(skill.get("content") or "")
    guidance = uml_skill_guidance(content, mode, diagram_type)
    subset = dict(skill)
    subset["content"] = guidance or content
    subset.pop("content_user", None)
    subset.pop("reference_files", None)
    return subset


MODELER_ISSUE_TASK = (
    "輸出模型影響、元素邊界、待確認點與建議下一步。"
)

MODELER_ISSUE_RULES = """- text 需包含：結論、模型影響、元素邊界、建議下一步。
- 需明確指出受影響的模型元素、圖型或責任邊界，不要只講抽象原則。
- 若資訊不足，說明需補哪些角色互動、事件流程、資料輸入/輸出、資料物件、狀態或例外邊界，不可臆測。
- 可提到使用案例圖、類別圖或循序圖的具體影響。
- 若需要他人補資訊，再在 open_questions 提具體問題。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""


MODELER_CONFLICT_ISSUE_TASK = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "先根據 User Requirements（URL-*）原文獨立重判，並將重判結果填入 proposed_label。"
)

MODELER_CONFLICT_ISSUE_RULES = f"""{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- 使用建模觀點判斷，不需要真的產生圖。
- reason 必須寫成完整審查意見：說明獨立判斷依據，並至少指出資料結構、狀態轉移、事件流程、責任邊界、使用案例圖／類別圖／循序圖影響中的一種；不要只寫一般語義判斷。
- 任務不是提出新需求，而是再審查目前的 Conflict/Neutral 標籤是否合理。
{CONFLICT_REVIEW_LABEL_RULES}
{CONFLICT_REVIEW_REASON_RULES}
- 需特別檢查：同一角色、物件、關係、觸發條件、狀態、輸出或多重度是否被重複、細化或用不同限制描述，導致模型需要合併、改寫或裁定。
- 若支持 Conflict，必須指出模型層的互斥點，或說明為何模型元素、流程、狀態或責任邊界需要合併、改寫或裁定。
- 不要跳到技術實作細節。"""

MODELER_CONFLICT_RESOLUTION_TASK = (
    "從系統模型、流程、狀態、資料與責任邊界角度，討論既有 conflict resolution 是否可採用或需要調整。"
)

MODELER_CONFLICT_RESOLUTION_RULES = """- 直接針對衝突報告中既有解決選項與建議解法做取捨。
- 不重新判斷 Conflict/Neutral，也不重新執行 conflict detection。
- text 需說明：哪個既有方案對模型最一致、是否需要調整流程/狀態/資料/責任邊界、以及可能影響哪些模型。
- 若資訊足以支持採用或調整某個 resolution，stance.state 填 ready_to_close，stance.proposal 填具體模型/需求邊界建議。
- 若缺少關鍵流程、狀態、資料物件或責任邊界，stance.state 填 needs_more_discussion，stance.proposal 仍須填目前最合理的候選方案或可裁決選項；不要提出 open_questions。
- 若無法在會議內判斷，stance.proposal 應整理可交由人類裁決的模型影響取捨，不要求延長討論。"""


MODELER_ELICITATION_CONTEXT_RULES = f"""{COMMON_ELICITATION_CONTEXT_RULES}

# Modeler 角度
- 聚焦使用者實際流程：怎麼開始、輸入、選擇、產生、查看結果、判斷任務完成，以及流程中的判斷點、例外情況與人工介入。
- 請用 user 能回答的需求訪談語言，不要要求使用者理解 UML、類別、狀態機或技術實作。
- 若需要提問，只提出最會影響流程、角色互動、輸入/輸出、狀態或例外邊界的那一個問題。
- 若目前流程、操作與例外理解已足夠，提出收束，不要為了模型細節硬問。"""


def modeler_elicitation_action_task(stop_phrase: str) -> str:
    return elicitation_action_task(stop_phrase)


def modeler_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""{elicitation_action_rules(stop_phrase)}
- target_stakeholders 優先選擇最清楚實際操作流程、交接、例外處理、狀態判斷或人工介入的 stakeholder。
- 問題應聚焦流程節點、狀態轉移、actor 責任、資料輸入輸出、例外流程或人工介入。
- 不要詢問一般需求優先級、領域法規或風險底線；這些分別交給 analyst 或 expert。
- 提問前必須避開 `closed_issues` 與 `do_not_repeat`；不要重問利害關係人已回答、已說不在意、或已表示 covered 的流程/互動方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 問題應承接目前理解，避免孤立訪談題。"""
