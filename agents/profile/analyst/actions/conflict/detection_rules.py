# Defines conflict detection prompts used before conflict review meetings.


def conflict_detection_base_task() -> str:
    return f"""# 任務
根據輸入的 User Requirements 判斷 Conflict / Neutral。

# Action Boundary
- action=detect_conflicts
- 本 action 只輸出 conflicts JSON。

# Generation Rules
- 本步做 requirement candidate conflict classification。
- 輸出呼叫端指定的 JSON。
- 產品情境與需求範圍只作為產品邊界背景；Conflict / Neutral 仍以 User Requirements 原文為主要依據。

# 判斷要求
- final_label 只用英文 "Conflict" 或 "Neutral"。
- 若 final_label 是 "Conflict"，必須輸出 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。
- 若無法歸入前八類但仍是 Conflict，final_type 使用 other。
- Neutral 項目包含 final_label 與 reason。
- 檢查所有有分析價值的需求對或需求群；不同互斥核心請拆成不同項目。
- 若需求不能原樣共同放入 SRS，必須先合併、改寫、刪除或人工裁定，標為 Conflict。
- Conflict 不限於執行時互斥；只要兩項需求改變同一功能、資料、使用者權限、流程、輸出、限制或驗收目標的 SRS 邊界，且不能原樣同時寫入同一份 SRS，就標為 Conflict。
- 先判斷是否同一需求槽位；不同槽位且可並存時標 Neutral。同一槽位內若限制、範圍、條件、角色、狀態、格式、數量、頻率、門檻、唯一性、允許集合或驗收邊界不同，且需要合併、改寫、刪除或人工裁定，標為 Conflict。
- 一般/具體、子集/超集、細化、補充步驟、近似重複或不同措辭，若改變同一槽位的驗收門檻、允許範圍、必要條件或完成邊界，標為 Conflict；若只是可無損合併的同義重複或不同上下文/流程階段，標為 Neutral。
- 不要只因兩項需求可同時實作、可做成選項、可合併、或其中一項較具體，就判 Neutral；只有原文清楚表示不同情境、不同使用者群體、不同事件、不同資料類型、不同階段，或一者明確包含另一者且不改變驗收邊界時，才判 Neutral。
- 若判定為 Neutral，reason 需說明為何兩者不產生需求衝突。

# 輸出要求
- 兩兩判斷：只需輸出 pair_index、final_label、reason；若 final_label 是 Conflict，再輸出 final_type。
- 整體判斷：Conflict 需包含 requirement_ids。
- 整體判斷的 requirement_ids 必須精確對應直接涉及的需求。"""
