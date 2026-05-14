# Shared prompt fragments for conflict review issue responses.

CONFLICT_REVIEW_RESPONSE_CONTRACT = """- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"overall_assessment":"...","pair_reviews":[...]}。
- overall_assessment 用 1-3 句說明整批標註品質是否有系統性偏誤。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、proposed_label、reason。"""

CONFLICT_REVIEW_EVIDENCE_RULES = """- proposed_label 可以和其他 agent 相同，但 reason 必須來自你的角色專屬角度；不要只重複一般語意判斷。
- current_label 是 Analyst 初判，只是待挑戰標籤；不得預設 current_label 正確，也不要替既有標籤辯護。
- 不要只因兩條需求可同時實作就判 Neutral；若它們會造成需求、scope、acceptance、責任、模型邊界或外部義務衝突，應判 Conflict。
- reason 必須根據 requirement 原文或會議中可追溯的證據，不可臆測不存在的需求、設計方案或外部情境。"""


def conflict_review_statement_hint() -> str:
    return (
        '"statement": "{\\"overall_assessment\\":\\"整批標註品質判斷\\",'
        '\\"pair_reviews\\":[{\\"id\\":\\"PAIR-001\\",'
        '\\"proposed_label\\":\\"Conflict | Neutral\\",'
        '\\"reason\\":\\"完整審查理由\\"}]}"'
    )
