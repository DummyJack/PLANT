# Shared prompt fragments for conflict review issue responses.

CONFLICT_REVIEW_RESPONSE_CONTRACT = """- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"overall_assessment":"...","pair_reviews":[...]}。
- overall_assessment 用 1-3 句說明整批標註品質是否有系統性偏誤。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx] 或 [MULTIPLE-xxx]；每筆都要有：id、proposed_label、confidence、reason。
- 此會議不提出 open_questions；open_questions 必須輸出空陣列。
- 不可用類 JSON 條列或文字摘要取代合法 JSON。"""

CONFLICT_REVIEW_LABEL_RULES = """- 只有在兩項需求無法同時成立、或一方成立會直接違反另一方時，才支持 Conflict。
- Conflict 不只表示執行時互斥；若兩項需求不能原樣共同放入軟體需求規格書，必須先合併、改寫、刪除或人工裁定，也應支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 重複、近似重複、細化、範圍重疊、同一需求槽位的不同措辭、限制、觸發條件、數量或頻率，不可直接支持 Neutral；需判斷是否需要合併、改寫、刪除或人工裁定。"""

CONFLICT_REVIEW_REASON_RULES = """- proposed_label 可以和其他 agent 相同，但 reason 必須提供獨立判斷依據；不要只重複一般語意判斷。
- reason 必須根據需求原文或會議中可追溯的證據，不可臆測不存在的需求、設計方案或外部情境。"""


def conflict_review_statement_hint() -> str:
    return (
        '"statement": "{\\"overall_assessment\\":\\"整批標註品質判斷\\",'
        '\\"pair_reviews\\":[{\\"id\\":\\"PAIR-1 或 MULTIPLE-1\\",'
        '\\"proposed_label\\":\\"Conflict | Neutral\\",'
        '\\"confidence\\":\\"high | medium | low\\",'
        '\\"reason\\":\\"完整審查理由\\"}]}"'
    )
