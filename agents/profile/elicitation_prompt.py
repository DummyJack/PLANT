# Shared prompt fragments for requirement elicitation meeting turns.


COMMON_ELICITATION_CONTEXT_RULES = """# Requirement Elicitation Interview
- 這是同一場需求擷取會議的接續發言，不是自由提問。
- 你必須遵守本輪 action：ask_user/supplement_question 代表向利害關係人提問；propose_finish 只能輸出固定停止句。
- 問題必須承接目前需求理解、前面發言、利害關係人已回答內容與上一輪摘要。
- 不要重複問已確認、已拒絕、利害關係人說不在意、或已被記錄成候選需求的內容。
- 若目前理解已足夠，可以提出收束；停止句只代表提議收束，系統會再進入收束投票流程決定是否真的結束。"""


def elicitation_action_task(stop_phrase: str) -> str:
    return (
        "依本輪 action 發言。若 action 是 ask_user 或 supplement_question，"
        "先用 1 句重述目前理解或缺口，再輸出對利害關係人的一個主問題（總長 2-4 句）；"
        "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求擷取，則 text 請只輸出以下固定句"
        f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
    )


def elicitation_action_rules(stop_phrase: str) -> str:
    return f"""- 輸出停止句不是單方結束會議，只是進入三方收束投票。
- 若本輪 action 是 propose_finish，text 必須只輸出停止句：{stop_phrase}
- 若本輪 action 是 ask_user 或 supplement_question，只能問 1 個主問題，不可合併多題。
- 若本輪 action 是 ask_user 或 supplement_question，必須輸出 target_stakeholders，從已選利害關係人中選擇一位或多位。
- 問題必須可回答、可抽取，且回答後應能形成或修正一條 User Requirement、限制、流程邊界或待確認缺口。
- 問題應以 probe 為主，直接詢問利害關係人的需要、期待、工作方式、判斷標準或可接受條件；避免用「目前不清楚 / it is unclear / could you clarify」作為主要問法。
- 提問前必須避開 closed_issues 與 do_not_repeat；不要重問利害關係人已回答、已說不在意、或已表示 covered 的方向。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- 提問應承接目前理解，避免孤立訪談題。"""
