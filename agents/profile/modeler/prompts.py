# Modeler prompt fragments shared across model generation and meeting responses.

from agents.profile.conflict_review import (
    CONFLICT_REVIEW_LABEL_RULES,
    CONFLICT_REVIEW_REASON_RULES,
    CONFLICT_REVIEW_RESPONSE_CONTRACT,
)

MODEL_SELECTION_RULES = """- 所有 diagram type 都不是必產生；只在模型能幫助需求理解、驗證或追溯時才建立、保留或更新。
- 不從模型反推新增需求，也不可把 open_questions / pending candidates 畫成正式模型內容。
- 資訊不足時不要畫死，改在 gaps、to_confirm 或 assumptions 說明。
- 系統脈絡圖、使用案例圖、活動圖或資料流程圖，可用於呈現系統邊界、角色互動、流程或資料流。
- 循序圖只在互動順序會影響需求理解時建立。
- State Machine Diagram 只在需求已有明確生命週期或狀態轉換時建立。
- 類別圖若建立，只能作為暫定領域模型，不可當成設計模型。"""


MODELER_ISSUE_TASK = (
    "輸出模型影響、元素邊界、待確認點與建議下一步。"
)

MODELER_ISSUE_RULES = """- statement 需包含：結論、模型影響、元素邊界、建議下一步。
- 需明確指出受影響的模型元素、圖型或責任邊界，不要只講抽象原則。
- 若資訊不足，說明需補哪些角色互動、事件流程、資料流、狀態或例外邊界，不可臆測。
- 可提到使用案例圖、類別圖或循序圖的具體影響。
- 若需要他人補資訊，再在 open_questions 提具體問題。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""


MODELER_CONFLICT_ISSUE_TASK = (
    "請逐筆再審查目前這批 Conflict/Neutral 項目，"
    "先根據 requirements 原文獨立重判，並將重判結果填入 proposed_label。"
)

MODELER_CONFLICT_ISSUE_RULES = f"""{CONFLICT_REVIEW_RESPONSE_CONTRACT}
- 使用建模觀點判斷，不需要真的產生圖。
- reason 必須寫成完整審查意見：說明你的獨立判斷依據，並至少指出資料結構、狀態轉移、事件流程、責任邊界、使用案例圖／類別圖／循序圖影響中的一種；不要只寫一般語義判斷。
- 任務不是提出新需求，而是再審查目前的 Conflict/Neutral 標籤是否合理。
- 只有在兩項需求在資料結構、狀態轉移、事件流程或責任邊界上無法同時成立時，才支持 Conflict。
{CONFLICT_REVIEW_LABEL_RULES}
{CONFLICT_REVIEW_REASON_RULES}
- 需特別檢查：同一角色、物件、關係、觸發條件、狀態、輸出或多重度是否被重複、細化或用不同限制描述，導致模型需要合併、改寫或裁定。
- 若只是流程未定、資料欄位未補齊、責任分工未明，不能因看不出衝突就直接支持 Neutral。
- 若支持 Conflict，必須指出模型層的互斥點；若支持 Neutral，必須說明為何兩項需求既不衝突、也不重複，且無直接語義關係。
- 不要跳到技術實作細節。"""


MODELER_ELICITATION_CONTEXT_RULES = """# ELICIT Requirement Interview
- 這是同一場會議的接續發言，不是自由提問；你的問題必須承接目前需求理解、前面發言、user 已回答內容與訪談記憶。
- 你必須遵守「本輪你的 action」：ask_user/supplement_question 才能問 user；propose_finish 只能輸出固定停止句。
- 不要重複問已確認、已拒絕、user 說不在意、或已被記錄成需求的內容。
- 聚焦使用者實際流程：怎麼開始、輸入、選擇、產生、查看結果、判斷任務完成，以及流程中的判斷點、例外情況與人工介入。
- 請用 user 能回答的需求訪談語言，不要要求使用者理解 UML、類別、狀態機或技術實作。
- 不要追問一般動機、商業價值或優先級；除非它會直接改變操作流程、角色互動、輸入/輸出、狀態、例外或人工介入。
- 前半段請先補足主要使用流程，不要把會議變成流程細節審查；只有當細節會直接改變主要流程、任務完成方式或需求成立性時才追問。
- 若本輪已有前面發言，請先判斷前面問題是否已覆蓋模型關注點；若已覆蓋，不要換句話重問，請提出更精準的下一層追問，或在資訊足夠時提出收束。
- 若目前流程、操作與例外理解已足夠，可以提出收束；停止句只代表提議收束，系統會再進入收束投票流程決定是否真的結束。"""


def modeler_elicitation_action_task(stop_phrase: str) -> str:
    return (
        "依本輪 action 發言。若 action 是 ask_user 或 supplement_question，"
        "先用 1 句重述目前理解或缺口，再輸出對 user 的一個主問題（總長 2-4 句）；"
        "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
        f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
    )


def modeler_elicitation_action_rules(stop_phrase: str) -> str:
    return f"""- 只有在目前需求理解已足夠，且沒有關鍵流程缺口時，才可輸出停止句：{stop_phrase}
- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，statement 必須只輸出停止句：{stop_phrase}
- 若本輪 action 是 ask_user 或 supplement_question，只能問 1 個主問題，不可合併多題。
- 若本輪 action 是 ask_user 或 supplement_question，必須輸出 target_stakeholders，從已選 stakeholder 中選擇一位或多位。
- target_stakeholders 優先選擇最清楚實際操作流程、交接、例外處理、狀態判斷或人工介入的 stakeholder。
- 問題必須可回答、可抽取；回答後應能支援需求修正，或角色、工作流程、資料流、狀態、例外邊界修正。
- 問題應以 probe 為主，直接詢問 user 的使用步驟、輸入/輸出、角色互動、判斷點、例外流程、狀態變化或人工介入；避免用「目前不清楚 / it is unclear / could you clarify」作為主要問法。
- 不要重複 analyst 的需求目標/成功標準問題，也不要重複 expert 的限制/風險問題；你的問題應讓流程、互動或邊界更清楚。
- 提問前必須避開 `closed_issues` 與 `do_not_repeat`；不要重問 user 已回答、已說不在意、或已表示 covered 的流程/互動方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 提問應承接目前理解，避免孤立訪談題。
- 若問題得到回答，應能直接支援需求修正或模型邊界修正。
- open_questions 請輸出空陣列。"""
