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
- 本 action 只裁定 new_label 與一句 reason。
- 不整理 final description、不判定 final_type、不產生 resolution options。
- 不新增、刪除或改寫 proposal_list 項目。
- 最外層只能輸出 conflict_signoff。

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
- 解讀 pair_reviews 時需依 agent 職責加權：Analyst 代表需求語意與 SRS 邊界；Expert 只代表外部義務、法規/標準、合規、風險或品質底線；Modeler 只代表流程、狀態、資料、角色互動、責任邊界與模型可共存性。
- 若 Expert 或 Modeler 因 pair 不屬於自身職責而維持 current_label，這不是一般投票支持，而是「職責外不介入」。
- 若 pair_reviews 與 pair 原文足以支持改判，new_label 可改為 Conflict 或 Neutral。
- 若 extracted_pair_reviews 為空，預設維持 current_label，除非 User Requirements（URL-*）原文本身已足以明確推翻現標籤。
- 若證據不足、理由不一致或沒有明確共識，維持 current_label。
{label_rules}
- proposal_list 中每一個項目都必須輸出一筆 decision；即使決定維持 current_label，也不可省略。
- 輸出只包含 conflict_signoff JSON。
- 請直接做最終裁定，不要重述整場會議。

# Output JSON
{{
  "conflict_signoff": {{
    "decisions": [
      {{"id": "衝突ID", "new_label": "Conflict 或 Neutral", "reason": "一句繁中裁定理由"}}
    ]
  }}
}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 conflict_finalization 或 conflict_resolution。
- 不輸出 resolution options。
- 不新增、刪除或改寫 proposal_list 項目。
- 不新增、改寫、刪除 URL 或 REQ。
- 不輸出 conflict_signoff 以外的 wrapper。"""

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
為每個已定案項目整理 description；若 final_label 是 Conflict，也要根據討論後的主要衝突原因判定 final_type。

# Action Boundary
- action=finalize_conflict_review
- 本 action 只整理 conflict_finalization.reasons。
- 不改變 final_label、不重新做 signoff、不產生 resolution options。
- 不新增、刪除或改寫 decision_list 項目。
- 最外層只能輸出 conflict_finalization。

# Input
Decision List:
{json.dumps(decision_list, ensure_ascii=False, indent=2)}

Agent Pair Reviews:
{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}

Type Guidance:
{type_guidance}

description 用來寫入 artifact/result.json，作為該項 final_label 的最終說明。
請根據 final_label 與各 agent 逐筆理由，整理出一段清楚、精簡、可追溯的裁定描述。

# Generation Rules
- 若 final_label 是 Conflict：說明需求之間的主要衝突點，或為什麼需要合併、改寫、刪除或裁定。
- 若 final_label 是 Conflict：必須輸出 final_type；final_type 只能是 logical、technical、resource、temporal、data、state、priority、scope、other。
- final_type 根據討論後的主要衝突原因決定，不必沿用 initial_type；若無法歸入前八類但仍是 Conflict，使用 other。
- 若 final_label 是 Neutral：說明為什麼需求之間不構成衝突。
- 若 final_label 是 Neutral：只輸出 id 與 description。
- 使用各 agent 已提出的理由，不加入新的需求解釋或新的判準。
- description 只整理裁定理由，不列 agent 名稱、投票過程或完整需求原文。

# Output JSON
{{
  "conflict_finalization": {{
    "reasons": [
      {{"id": "PAIR-1", "description": "Conflict 的最終裁定描述", "final_type": "scope"}},
      {{"id": "PAIR-2", "description": "Neutral 的最終裁定描述"}}
    ]
  }}
}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 conflict_signoff 或 conflict_resolution。
- 不輸出 resolution options。
- 不新增、刪除或改寫 decision_list 項目。
- 不新增、改寫、刪除 URL 或 REQ。
- 不輸出 conflict_finalization 以外的 wrapper。"""
