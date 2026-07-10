# Defines action prompts and output contracts.
import json
from typing import Optional

from agents.profile.analyst.rules import label_rules

# ========
# Defines review signoff function for this module workflow.
# ========
def review_signoff(
    *,
    proposal_list: list,
    extracted_pair_reviews: Optional[list],
    discussion_rows: list,
) -> str:
    return f"""# 任務
根據 User Requirements（URL-*）原文與各 agent 的逐筆 pair_reviews，對每筆 Conflict/Neutral 項目做最終裁定。

# Action Boundary
- action=review_conflict_signoff
- 本 action 裁定 final_label 與一句 reason。
- 最外層輸出 conflict_signoff。

# Input
Proposal List:
{json.dumps(proposal_list, ensure_ascii=False, indent=2)}

Agent Pair Reviews:
{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}

Discussion Rows:
{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}

# Generation Rules
- 先看 User Requirements（URL-*）原文，再看各 agent 的 pair_reviews。
- discussion_rows 只在 pair_reviews 證據不足時作補充參考。
- 解讀 pair_reviews 時需依審查職責加權：需求語意與 SRS 邊界、外部證據/風險、模型可共存性各自只代表其職責範圍。
- 若某審查者因 pair 不屬於自身職責而維持 current_label，這不是一般投票支持，而是「職責外不介入」。
- 「沒有外部證據介入」只代表沒有外部限制介入；不得因此把需求語意、SRS 邊界或模型衝突改判為 Neutral。
- 若需求語意與模型邊界都指出衝突，而外部證據審查只表示無外部介入，通常應維持或裁定 Conflict。
- 裁定骨架：不同槽位且可並存為 Neutral；同一槽位且改變支援集合、義務強度、門檻、輸出行為、允許/禁止範圍或驗收邊界為 Conflict；明確例外、條件分支、方法與配件可共存時為 Neutral。
- 若 pair_reviews 與 pair 原文足以支持改判，final_label 可改為 Conflict 或 Neutral。
- 若 extracted_pair_reviews 為空，預設維持 current_label，除非 User Requirements（URL-*）原文本身已足以明確推翻現標籤。
- 若證據不足、理由不一致或沒有明確共識，維持 current_label。
{label_rules}
- proposal_list 中每一個項目都必須輸出一筆 decision；即使決定維持 current_label，也不可省略。
- 輸出 conflict_signoff JSON。
- 請直接做最終裁定。

# Output JSON
{{
  "conflict_signoff": {{
    "decisions": [
      {{"id": "衝突ID", "final_label": "Conflict 或 Neutral", "reason": "一句繁中裁定理由"}}
    ]
  }}
}}"""

# ========
# Defines review reason function for this module workflow.
# ========
def review_reason(
    *,
    decision_list: list,
    extracted_pair_reviews: Optional[list],
    type_guidance: str,
) -> str:
    return f"""# 任務
為每個已定案項目整理 title 與 description；若 final_label 是 Conflict，也要根據討論後的主要衝突原因判定 final_type。

# Action Boundary
- action=finalize_conflict_review
- 本 action 整理 conflict_finalization.reasons。
- 最外層輸出 conflict_finalization。

# Input
Decision List:
{json.dumps(decision_list, ensure_ascii=False, indent=2)}

Agent Pair Reviews:
{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}

Type Guidance:
{type_guidance}

title 與 description 會寫入 artifact/result.json，作為後續 conflict report 與 MoM 標題來源。
title 是短標題，description 是該項 final_label 的最終說明。
請根據 final_label 與各 agent 逐筆理由，整理出一段清楚、精簡、可追溯的裁定描述。

# Generation Rules
- 若 final_label 是 Conflict：說明需求之間的主要衝突點，或為什麼需要合併、改寫、刪除或裁定。
- 若 final_label 是 Conflict：必須輸出 title，且 title 必須是 4 到 30 字的名詞片語，描述衝突主題；不可只輸出 Conflict、衝突、需求衝突或 CR 編號。
- 若 final_label 是 Conflict：必須輸出 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。
- final_type 根據討論後的主要衝突原因決定；若無法歸入前八類但仍是 Conflict，使用 other。
- 若 final_label 是 Neutral：說明為什麼需求之間不構成衝突。
- 若 final_label 是 Neutral：輸出 id 與 description。
- 使用各 agent 已提出的理由，不加入新的需求解釋或新的判準。
- description 整理裁定理由。
- description 必須服從 Decision List 的 final_label；若 pair_reviews 與 final_label 不一致，以 final_label 為準整理理由。
- 若 final_label 是 Conflict，description 不可寫「no conflict」、「not conflict」、「can coexist」作為結論；若 final_label 是 Neutral，description 不可寫「mutually exclusive」、「cannot coexist」作為結論。
- 若 decision reason 與 final_label 不一致，description 必須以 final_label 為準整理理由。

# Output JSON
{{
  "conflict_finalization": {{
    "reasons": [
      {{"id": "PAIR-1", "title": "簡短衝突標題", "description": "Conflict 的最終裁定描述", "final_type": "scope"}},
      {{"id": "PAIR-2", "description": "Neutral 的最終裁定描述"}}
    ]
  }}
}}"""
